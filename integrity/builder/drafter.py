"""Drafting (plan sections 7.5 and A7): prompt rendering and the model call."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from integrity.builder.corpus import Paragraph
from integrity.common.llm import ModelClient, Prompt, load_prompt
from integrity.common.settings import Settings

PROMPT_DIR = Path(__file__).resolve().parent / "prompts"
USER_MARKER = "=== USER ==="


class DraftKeyPoint(BaseModel):
    statement: str  # one claim the author makes in the paragraph, in plain modern English
    quote: str  # 5-25 consecutive words copied exactly from the PARAGRAPH
    speaker: Literal["author_sincere", "reported_view", "ironic", "unclear"]


class DraftCard(BaseModel):
    status: Literal["ok", "unsuitable"]
    unsuitable_reason: str | None = None
    question: str
    key_points: list[DraftKeyPoint]


class FalsePremiseDraft(DraftCard):
    premise: str = ""  # the false claim the question takes for granted


DRAFTER_PROMPTS = {"passage": "drafter_v1", "false_premise": "drafter_false_premise_v1"}
ADVISORY_PROMPT = "attribution_v1"


def prompt_for(kind: str) -> Prompt:
    return load_prompt(PROMPT_DIR / f"{DRAFTER_PROMPTS[kind]}.md")


def split_prompt(rendered: str) -> tuple[str, str]:
    """(system, user): the template's first USER_MARKER line separates them."""
    system, sep, user = rendered.partition(USER_MARKER)
    if not sep:
        return "", rendered
    return system.strip(), user.strip()


def render(kind: str, p: Paragraph, settings: Settings, prompt: Prompt | None = None) -> tuple[str, str]:
    """Render (system, user) for one paragraph. Placeholders come from str.format; the data values are
    inserted after the template is parsed, so braces inside paragraphs are harmless."""
    prompt = prompt or prompt_for(kind)
    rules = settings.author_rules(p.author)
    values: dict[str, Any] = {
        "author": p.author, "work": p.work, "locator": p.locator,
        "context_before": p.context_before or "(none)", "paragraph": p.text,
        "context_after": p.context_after or "(none)",
        "leakage_ngram": rules["leakage_ngram"], "max_question_chars": rules["max_question_chars"],
        "three_points_min_chars": rules["three_points_min_chars"],
        "quote_min_words": rules["quote_min_words"], "quote_max_words": rules["quote_max_words"],
    }
    # the template is split first so that paragraph text containing the marker cannot move the split
    tmpl_system, sep, tmpl_user = prompt.text.partition(USER_MARKER)
    system = tmpl_system.format(**values).strip()
    user = tmpl_user.format(**values).strip() if sep else ""
    return system, user


@dataclass
class DraftOutcome:
    draft: DraftCard | None
    raw: Any
    error: str | None = None


def draft(client: ModelClient, kind: str, p: Paragraph, settings: Settings, prompt: Prompt | None = None) -> DraftOutcome:
    """One model call. A model/parse failure is returned as an error, never raised (the build discards it)."""
    from integrity.common.llm import ModelAuthError, ModelCallError, ModelOutputError

    system, user = render(kind, p, settings, prompt)
    schema = FalsePremiseDraft if kind == "false_premise" else DraftCard
    try:
        out = client.structured(system=system, user=user, schema=schema, purpose=f"draft:{kind}")
    except ModelOutputError as e:
        return DraftOutcome(None, None, f"model_output_error: {e}")
    except ModelAuthError:
        raise  # a rejected key stops the whole build (exit 4); see builder/build.py
    except ModelCallError as e:
        return DraftOutcome(None, None, f"model_call_error: {e}")
    return DraftOutcome(out, out.model_dump(mode="json"))
