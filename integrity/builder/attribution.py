"""Attribution safeguards (plan section 7.7): cue heuristics and the optional model advisory."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel

from integrity.builder.corpus import Paragraph
from integrity.builder.drafter import ADVISORY_PROMPT, PROMPT_DIR
from integrity.common import textnorm
from integrity.common.llm import ModelClient, ModelOutputError, load_prompt
from integrity.common.schema import AttributionAdvice
from integrity.common.settings import Settings

GENERAL_CUE_RE = re.compile(
    r"it may be (?:objected|said|thought|asked)|it is (?:said|urged|objected)|it will be (?:said|argued|added)|"
    r"perhaps may doubt|may be objected|objectors|it may be asked|will be said|it is said|"
    r"(?:they|some(?: men)?) say|say (?:they|these men|you)|says he|saith he|"
    r"he (?:alledgeth|alleges|insists|affirms|tells)|you may object|as we are told|his words are|"
    r"an? (?:enemy|adversary)|(?:first|second|third) argument",
    re.IGNORECASE,
)

# (regex, case_sensitive). Names are matched on word boundaries.
NAME_CUES: dict[str, list[tuple[str, bool]]] = {
    "John Locke": [(r"\bBarclay\b", True), (r"\bHooker\b", True), (r"\bFilmer\b", True), (r"\bSir Robert\b", True)],
    "Thomas Hobbes": [
        (r"\bBellarmine", True), (r"\bBeza\b", True), (r"\bAristotle\b", True), (r"\bFoole\b", True),
        (r"\bseditious\b", False),
    ],
    "John Stuart Mill": [
        (r"\bCarlyle\b", True), (r"\bJohnson\b", True), (r"\bCalvin\b", True), (r"\bAristotle\b", True),
        (r"pertinacious adversary", False),
    ],
    "Edmund Burke": [
        (r"\bPrice\b", True), (r"Revolution Society", True), (r"National Assembly", True),
        (r"\bMr\.\s+(?:Fox|Sheridan|Pitt|Dundas)\b", True), (r"La Tour du Pin", True),
    ],
}
# "Bellarmine" is matched without a trailing boundary because the source writes the possessive "Bellarmines".

REBUTTAL_RE = re.compile(
    r"^(?:I answer|To (?:this|which) I answer|To which let me|This specious reasoning|I affirm no such thing|"
    r"It is not true that|I fully admit|Conceding|—This is possible)"
)


def cue_phrases(text: str, author: str) -> list[str]:
    """Matched cue phrases or names (lower-cased for the generic cues), in order of appearance, de-duplicated."""
    found: list[tuple[int, str]] = []
    for m in GENERAL_CUE_RE.finditer(text):
        found.append((m.start(), m.group(0).lower()))
    for rx, case_sensitive in NAME_CUES.get(author, []):
        for m in re.finditer(rx, text, 0 if case_sensitive else re.IGNORECASE):
            found.append((m.start(), m.group(0).lower() if not case_sensitive else m.group(0)))
    out: list[str] = []
    for _, phrase in sorted(found):
        if phrase not in out:
            out.append(phrase)
    return out


def rebuttal_next(context_after: str) -> bool:
    t = context_after.lstrip().lstrip("\"“'‘ ")
    return bool(REBUTTAL_RE.match(t)) or bool(REBUTTAL_RE.match(context_after.lstrip()))


def first_person_in_quotes(text: str) -> bool:
    """Mill: a first-person 'I' inside quotation marks."""
    from integrity.builder.eligibility import quoted_ranges

    return any(re.search(r"\bI\b", text[s:e]) for s, e in quoted_ranges(text))


# --------------------------------------------------------------------------- model advisory


class AdviceItem(BaseModel):
    key_point_id: str
    speaker: Literal["author_sincere", "reported_view", "ironic", "unclear"]
    explanation: str
    evidence: str = ""


class AdvisoryOutput(BaseModel):
    items: list[AdviceItem]


def run_advisory(
    client: ModelClient,
    p: Paragraph,
    key_points: list[tuple[str, str, str]],  # (id, statement, quote)
    settings: Settings,
) -> tuple[list[AttributionAdvice], str]:
    """Ask the attribution model per key point. Returns (advice, prompt_sha256).

    Evidence is verified with textnorm against the paragraph and both context sections; advice whose
    evidence cannot be found is labelled "unverified advice". Raises ModelOutputError-derived errors to the
    caller, which records the failure; the advisory never discards or approves a card.
    """
    prompt = load_prompt(PROMPT_DIR / f"{ADVISORY_PROMPT}.md")
    kp_text = "\n".join(f'{kid}: {st}\n   quote: "{q}"' for kid, st, q in key_points)
    values = {
        "author": p.author, "work": p.work, "locator": p.locator, "context_before": p.context_before or "(none)",
        "paragraph": p.text, "context_after": p.context_after or "(none)", "key_points": kp_text,
    }
    tmpl_system, _, tmpl_user = prompt.text.partition("=== USER ===")
    out = client.structured(
        system=tmpl_system.format(**values).strip(), user=tmpl_user.format(**values).strip(),
        schema=AdvisoryOutput, purpose="attribution",
    )
    advice: list[AttributionAdvice] = []
    for it in out.items:  # type: ignore[attr-defined]
        ev = it.evidence.strip()
        verified = bool(ev) and any(
            textnorm.find_span(ev, src) is not None for src in (p.text, p.context_before, p.context_after) if src
        )
        advice.append(
            AttributionAdvice(
                key_point_id=it.key_point_id, speaker=it.speaker, explanation=it.explanation,
                evidence=ev, evidence_verified=verified,
                label="verified" if verified else "unverified advice",
            )
        )
    return advice, prompt.sha256


__all__ = ["ModelOutputError", "cue_phrases", "first_person_in_quotes", "rebuttal_next", "run_advisory"]
