"""Model client: protocol, LangChain implementation, fake for tests, prompt loading, tracing switch.

Importing this module is cheap and offline: langchain is imported only inside
LangChainModelClient.__init__.
"""

from __future__ import annotations

import os
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ValidationError

from integrity.common.schema import sha256_hex


class ModelOutputError(Exception):
    """The model's structured output could not be parsed (after one retry)."""


class ModelCallError(Exception):
    """Transport/API failure, including exhausted provider credits."""


class ModelAuthError(ModelCallError):
    """The provider rejected the API key (HTTP 401/403). Never retried: retrying cannot fix a bad key."""


_AUTH_MARKERS = ("authentication_error", "invalid x-api-key", "incorrect api key", "invalid_api_key",
                 "invalid api key")


def is_auth_error(exc: BaseException) -> bool:
    """True when ``exc`` looks like a provider rejecting the API key (status 401/403 or a known message)."""
    status = getattr(exc, "status_code", None)
    if status is None:
        status = getattr(getattr(exc, "response", None), "status_code", None)
    if status in (401, 403):
        return True
    text = str(exc).lower()
    return any(marker in text for marker in _AUTH_MARKERS)


@runtime_checkable
class ModelClient(Protocol):
    def structured(self, *, system: str, user: str, schema: type[BaseModel], purpose: str) -> BaseModel: ...


# --------------------------------------------------------------------------- prompts


@dataclass(frozen=True)
class Prompt:
    name: str
    text: str
    sha256: str

    def render(self, **values: Any) -> str:
        """str.format placeholders; literal braces must be doubled in the prompt file."""
        return self.text.format(**values)


def load_prompt(path: str | Path) -> Prompt:
    """Load a prompts/*.md file; its sha256 is recorded with every call that uses it."""
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    return Prompt(name=p.stem, text=text, sha256=sha256_hex(text))


# --------------------------------------------------------------------------- tracing


def disable_tracing() -> None:
    os.environ["LANGSMITH_TRACING"] = "false"
    os.environ["LANGCHAIN_TRACING_V2"] = "false"


def apply_tracing_setting(tracing: str) -> None:
    """models.tracing: 'off' disables tracing; 'inherit' leaves the environment alone."""
    if tracing == "off":
        disable_tracing()


# --------------------------------------------------------------------------- real client

_NO_TEMPERATURE_PREFIXES = ("o1", "o3", "o4", "gpt-5")
_CLAUDE_5_PLUS = re.compile(r"^claude-[a-z]+-([5-9]|\d{2,})(-\d+)?$")


def rejects_temperature(model_id: str) -> bool:
    """Heuristic: reasoning-style models and the Claude 5 family reject a temperature parameter.

    The heuristic is only a first guess. ``LangChainModelClient.structured`` also recovers from a provider error
    that says temperature is deprecated or unsupported (see ``is_temperature_error``).
    """
    name = model_id.split(":", 1)[-1].lower()
    return name.startswith(_NO_TEMPERATURE_PREFIXES) or bool(_CLAUDE_5_PLUS.match(name))


def is_temperature_error(exc: BaseException) -> bool:
    """True when the provider refused the request because of the temperature parameter."""
    text = str(exc).lower()
    return "temperature" in text and any(w in text for w in ("deprecated", "not supported", "unsupported", "invalid"))


class LangChainModelClient:
    """init_chat_model(...).with_structured_output(schema, method="json_schema")."""

    def __init__(
        self,
        model_id: str,
        *,
        temperature: float | None = 0,
        max_retries: int = 2,
        backoff_s: float = 1.0,
        sleep: Callable[[float], None] = time.sleep,
    ):
        from langchain.chat_models import (
            init_chat_model,  # lazy: keeps module import cheap/offline
        )

        self.model_id = model_id
        self.max_retries = max_retries
        self.backoff_s = backoff_s
        self._sleep = sleep
        self._credit_failure: str | None = None
        self.usage: list[dict[str, Any]] = []
        kwargs: dict[str, Any] = {}
        if temperature is not None and not rejects_temperature(model_id):
            kwargs["temperature"] = temperature
        self._init_chat_model = init_chat_model
        self._temperature_sent = "temperature" in kwargs
        self._model = init_chat_model(model_id, **kwargs)
        self._structured_cache: dict[type, Any] = {}

    def _rebuild_without_temperature(self) -> None:
        """The provider refused the temperature parameter: build the model again without it."""
        self._model = self._init_chat_model(self.model_id)
        self._temperature_sent = False
        self._structured_cache = {}

    def _runnable(self, schema: type[BaseModel]) -> Any:
        if schema not in self._structured_cache:
            self._structured_cache[schema] = self._model.with_structured_output(
                schema, method="json_schema", include_raw=True
            )
        return self._structured_cache[schema]

    def _record_usage(self, purpose: str, raw: Any) -> None:
        meta = getattr(raw, "usage_metadata", None)
        if meta:
            self.usage.append({"purpose": purpose, "model": self.model_id, **dict(meta)})

    def _invoke_once(self, runnable: Any, messages: list[tuple[str, str]], schema: type[BaseModel], purpose: str):
        out = runnable.invoke(messages)
        raw = out.get("raw") if isinstance(out, dict) else None
        self._record_usage(purpose, raw)
        if not isinstance(out, dict):
            parsed, err = out, None
        else:
            parsed, err = out.get("parsed"), out.get("parsing_error")
        if err is not None or parsed is None:
            raise ModelOutputError(f"{purpose}: structured output could not be parsed: {err}")
        if isinstance(parsed, schema):
            return parsed
        try:
            return schema.model_validate(parsed)
        except ValidationError as e:
            raise ModelOutputError(f"{purpose}: output failed schema validation: {e}") from e

    def structured(self, *, system: str, user: str, schema: type[BaseModel], purpose: str) -> BaseModel:
        if getattr(self, "_credit_failure", None):
            raise ModelCallError(f"{purpose}: provider credits exhausted; further calls stopped: {self._credit_failure}")
        runnable = self._runnable(schema)
        messages = [("system", system), ("user", user)]
        parse_failures = 0
        transport_failures = 0
        while True:
            try:
                return self._invoke_once(runnable, messages, schema, purpose)
            except ModelOutputError:
                parse_failures += 1
                if parse_failures > 1:  # one retry, then raise
                    raise
            except Exception as e:
                if any(marker in str(e).lower() for marker in
                       ("insufficient_quota", "credit_balance_exhausted", "credit balance is too low")):
                    self._credit_failure = str(e)
                    raise ModelCallError(f"{purpose}: provider credits exhausted; further calls stopped: {e}") from e
                if is_auth_error(e):
                    raise ModelAuthError(f"{purpose}: the provider rejected the API key: {e}") from e
                if getattr(self, "_temperature_sent", False) and is_temperature_error(e):
                    self._rebuild_without_temperature()  # not a transport failure: retry once without it
                    runnable = self._runnable(schema)
                    continue
                transport_failures += 1
                if transport_failures > self.max_retries:
                    raise ModelCallError(f"{purpose}: model call failed after retries: {e}") from e
                self._sleep(self.backoff_s * 2 ** (transport_failures - 1))


# --------------------------------------------------------------------------- fake client


class FakeModelClient:
    """Returns queued outputs in order and records every call for assertions.

    Queue items: a BaseModel instance, a dict (validated against the schema), an Exception
    (raised), or a callable taking the call dict and returning one of the former.
    """

    def __init__(self, outputs: list[Any] | None = None):
        self.outputs: list[Any] = list(outputs or [])
        self.calls: list[dict[str, Any]] = []

    def queue(self, *outputs: Any) -> FakeModelClient:
        self.outputs.extend(outputs)
        return self

    def structured(self, *, system: str, user: str, schema: type[BaseModel], purpose: str) -> BaseModel:
        call = {"system": system, "user": user, "schema": schema, "purpose": purpose}
        self.calls.append(call)
        if not self.outputs:
            raise AssertionError(f"FakeModelClient: no queued output left for purpose={purpose!r}")
        item = self.outputs.pop(0)
        if callable(item) and not isinstance(item, (BaseModel, dict)):
            item = item(call)
        if isinstance(item, BaseException):
            raise item
        if isinstance(item, dict):
            return schema.model_validate(item)
        return item
