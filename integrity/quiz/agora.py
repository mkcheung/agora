"""Seam 2 adapter: loads the Agora entrypoint and validates every result (plan section 4.2).

This is the only quiz module that may call ``common.seams.load``.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping
from typing import Any

from pydantic import ValidationError

from integrity import CONTRACT_VERSION
from integrity.common import seams
from integrity.common.schema import AgoraResult

CONTRACT_SUMMARY = f"""Agora entrypoint contract, version {CONTRACT_VERSION}:
  def answer_question(question: str) -> dict      # synchronous, never prompts, raises on failure
Required result fields:
  answer     str    final answer text with inline (Author, Work, Locator) citations
  citations  list   items: passage_id, author, work, locator, quote (optional: chapter, section)
  retrieved  list   passages given to the answering model, in rank order;
                    items: passage_id, text, author, work, locator
                    (recommended: block_id, work_id, corpus_version, chapter, section; optional: score)
Optional fields: declined (bool), self_check [{{passage_id, quote, status}}], attempts (int),
                 claims [{{text, passage_ids}}], info {{model, namespace, k, filters, code_sha256}}.
A pydantic model is also accepted (model_dump() is called). Set seams.agora_entrypoint or pass --agora MOD:FUNC."""


class AgoraLoadError(Exception):
    """The entrypoint is missing, cannot be imported, or is not callable (exit code 3)."""


class ContractViolation(Exception):
    """A result does not satisfy the contract."""


def _short(e: ValidationError) -> str:
    parts = []
    for err in e.errors()[:6]:
        loc = ".".join(str(x) for x in err["loc"])
        parts.append(f"{loc}: {err['msg']}")
    more = "" if len(e.errors()) <= 6 else f" (+{len(e.errors()) - 6} more)"
    return "; ".join(parts) + more


def validate_result(raw: Any) -> dict[str, Any]:
    """Validate against AgoraResult; return a JSON-ready dict (ints coerced, ranks filled, extra keys kept)."""
    if not isinstance(raw, Mapping) and callable(getattr(raw, "model_dump", None)):
        raw = raw.model_dump()
    if not isinstance(raw, Mapping):
        raise ContractViolation(f"result is {type(raw).__name__}, expected a mapping")
    try:
        res = AgoraResult.model_validate(dict(raw))
    except ValidationError as e:
        raise ContractViolation(_short(e)) from e
    try:
        return res.model_dump(mode="json")
    except Exception as e:
        raise ContractViolation(f"result is not JSON-serialisable: {e}") from e


class AgoraAdapter:
    def __init__(self, spec: str, project_root: Any, namespace: str | None = None):
        self.spec = spec
        self.project_root = project_root
        self.namespace = namespace
        self._fn: Callable[[str], Any] | None = None

    def load(self) -> Callable[[str], Any]:
        """Import the entrypoint lazily; the namespace override is applied before the import."""
        try:
            fn = seams.load(self.spec, project_root=self.project_root, namespace=self.namespace)
        except seams.SeamError as e:
            raise AgoraLoadError(str(e)) from e
        if not callable(fn):
            raise AgoraLoadError(f"{self.spec!r} is not callable")
        try:
            inspect.signature(fn).bind("question")
        except TypeError as e:
            raise AgoraLoadError(f"{self.spec!r} cannot be called with one question argument: {e}") from e
        except ValueError:
            pass  # no introspectable signature
        self._fn = fn
        return fn

    def __call__(self, question: str) -> dict[str, Any]:
        if self._fn is None:
            self.load()
        assert self._fn is not None
        return validate_result(self._fn(question))
