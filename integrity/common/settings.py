"""Settings: integrity.toml + INTEGRITY_CONFIG override + INTEGRITY_* env + CLI overrides.

Precedence, highest first: CLI overrides > INTEGRITY_<SECTION>__<KEY> env (scalar keys only)
> file named by INTEGRITY_CONFIG (deep merge) > integrity/integrity.toml.
Unknown keys are an error (ConfigError, exit code 4).
"""

from __future__ import annotations

import copy
import os
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "integrity.toml"
RESERVED_ENV = {"INTEGRITY_CONFIG", "INTEGRITY_LIVE"}


class ConfigError(Exception):
    """Configuration problem (exit code 4)."""

    exit_code = 4


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Paths(_M):
    data_dir: str = "integrity_data"


class Seams(_M):
    project_root: str = ".."
    corpus_provider: str = "ingest:prepare_records"
    agora_entrypoint: str = "ask:answer_question"


class Models(_M):
    drafter: str
    attribution: str
    judge: str
    temperature: float | None = 0
    agora_model_hint: str = ""
    tracing: Literal["inherit", "off"] = "inherit"


class Build(_M):
    default_count: int = 24
    default_false_premise: int = 6
    max_attempts_per_slot: int = 3
    neighbor_exclusion: int = 1
    context_chars: int = 300
    attribution_advisory: bool = True


class Checks(_M):
    quote_min_words: int = 6
    quote_max_words: int = 40
    leakage_ngram: int = 5
    three_points_min_chars: int = 800
    require_author_in_question: bool = True
    max_question_chars: int = 300


class DenyEntry(_M):
    work_id: str | None = None
    locator_regex: str | None = None
    block_id: str | None = None
    reason: str = ""


class Eligibility(_M):
    content_types: list[str] = Field(default_factory=lambda: ["prose"])
    min_chars: int = 600
    max_chars: int = 4000
    min_stopword_ratio: float = 0.2
    max_latin_markers: int = 5
    max_quoted_fraction: float = 0.3
    max_question_fraction: float = 0.5
    max_money_terms: int = 2
    max_bible_refs: int = 2
    denylist: list[DenyEntry] = Field(default_factory=list)


class AuthorOverride(_M):
    """Per-author overrides of [eligibility] and [checks] keys (all optional)."""

    # eligibility keys
    content_types: list[str] | None = None
    min_chars: int | None = None
    max_chars: int | None = None
    min_stopword_ratio: float | None = None
    max_latin_markers: int | None = None
    max_quoted_fraction: float | None = None
    max_question_fraction: float | None = None
    max_money_terms: int | None = None
    max_bible_refs: int | None = None
    # checks keys
    quote_min_words: int | None = None
    quote_max_words: int | None = None
    leakage_ngram: int | None = None
    three_points_min_chars: int | None = None
    require_author_in_question: bool | None = None
    max_question_chars: int | None = None
    # author flags
    quoted_text_is_other_speaker: bool | None = None


class Sampling(_M):
    author_weights: dict[str, float] = Field(default_factory=dict)


class Stratum(_M):
    name: str
    work_id: list[str]
    locator_regex: str | None = None
    paragraph_in: list[int | str] | None = None
    weight: float


class Publish(_M):
    holdout_percent: int = 15


class Review(_M):
    sensitive_terms: list[str] = Field(default_factory=list)


class Quiz(_M):
    min_cards: int = 10
    timeout_s: int = 180
    retries: int = 1
    strict: bool = False


class Judge(_M):
    granularity: Literal["per_item", "per_card"] = "per_item"
    consistency_sample: float = 0.2
    controls_per_run: int = 4
    max_retries: int = 2
    prompts: dict[str, str] = Field(default_factory=dict)


class Settings(_M):
    paths: Paths = Field(default_factory=Paths)
    seams: Seams = Field(default_factory=Seams)
    models: Models
    build: Build = Field(default_factory=Build)
    checks: Checks = Field(default_factory=Checks)
    eligibility: Eligibility = Field(default_factory=Eligibility)
    authors: dict[str, AuthorOverride] = Field(default_factory=dict)
    sampling: Sampling = Field(default_factory=Sampling)
    strata: list[Stratum] = Field(default_factory=list)
    publish: Publish = Field(default_factory=Publish)
    review: Review = Field(default_factory=Review)
    quiz: Quiz = Field(default_factory=Quiz)
    judge: Judge = Field(default_factory=Judge)

    @property
    def project_root(self) -> Path:
        return Path(self.seams.project_root)  # absolute after load_settings

    @property
    def data_dir(self) -> Path:
        p = Path(self.paths.data_dir)
        return p if p.is_absolute() else self.project_root / p

    def author_rules(self, author: str) -> dict[str, Any]:
        """Effective eligibility + checks values (and quoted_text_is_other_speaker) for one author."""
        rules = self.eligibility.model_dump(exclude={"denylist"})
        rules.update(self.checks.model_dump())
        rules["quoted_text_is_other_speaker"] = False
        ov = self.authors.get(author)
        if ov is not None:
            rules.update(ov.model_dump(exclude_none=True))
        return rules

    def snapshot(self) -> dict[str, Any]:
        """The merged configuration as plain JSON-able data (for batch.json and run.json)."""
        return self.model_dump(mode="json")


# --------------------------------------------------------------------------- loading


def deep_merge(base: dict[str, Any], over: Mapping[str, Any]) -> dict[str, Any]:
    """Tables merge recursively; scalars and arrays (including arrays of tables) are replaced."""
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, Mapping) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        with open(path, "rb") as fh:
            data = tomllib.load(fh)
    except FileNotFoundError as e:
        raise ConfigError(f"config file not found: {path}") from e
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"invalid TOML in {path}: {e}") from e
    root = data.get("seams", {}).get("project_root")
    if isinstance(root, str):  # relative to the file that sets it
        data["seams"]["project_root"] = str((path.parent / root).resolve())
    return data


def _coerce(raw: str, like: Any, key: str) -> Any:
    try:
        if isinstance(like, bool):
            if raw.lower() in ("1", "true", "yes", "on"):
                return True
            if raw.lower() in ("0", "false", "no", "off"):
                return False
            raise ValueError("expected a boolean")
        if isinstance(like, int):
            return int(raw)
        if isinstance(like, float):
            return float(raw)
        return raw
    except ValueError as e:
        raise ConfigError(f"bad value for {key}: {raw!r} ({e})") from e


def _env_overrides(env: Mapping[str, str], merged: dict[str, Any]) -> dict[str, Any]:
    """INTEGRITY_<SECTION>__<KEY>=value, for existing scalar keys of plain sections only."""
    out: dict[str, Any] = {}
    for name, raw in env.items():
        if not name.startswith("INTEGRITY_") or name in RESERVED_ENV:
            continue
        parts = name[len("INTEGRITY_"):].lower().split("__")
        if len(parts) != 2:
            raise ConfigError(f"unrecognised environment variable {name} (use INTEGRITY_<SECTION>__<KEY>)")
        section, key = parts
        table = merged.get(section)
        if not isinstance(table, dict) or key not in table:
            raise ConfigError(f"environment variable {name} does not name a known setting")
        like = table[key]
        if isinstance(like, (dict, list)):
            raise ConfigError(f"environment variable {name}: only scalar settings can be set from the environment")
        out.setdefault(section, {})[key] = _coerce(raw, like, name)
    return out


def load_settings(
    cli_overrides: Mapping[str, Any] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    default_path: Path | None = None,
) -> Settings:
    """Load, merge and validate settings. Raises ConfigError on any problem."""
    env = os.environ if env is None else env
    merged = _read_toml(default_path or DEFAULT_CONFIG_PATH)
    override_file = env.get("INTEGRITY_CONFIG")
    if override_file:
        merged = deep_merge(merged, _read_toml(Path(override_file).expanduser()))
    merged = deep_merge(merged, _env_overrides(env, merged))
    if cli_overrides:
        merged = deep_merge(merged, cli_overrides)
    try:
        return Settings.model_validate(merged)
    except ValidationError as e:
        raise ConfigError(f"invalid configuration:\n{e}") from e
