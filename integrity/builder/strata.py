"""Strata (plan section 7.3): which stratum a paragraph belongs to, and which strata an author has."""

from __future__ import annotations

import re
from collections import OrderedDict
from dataclasses import dataclass

from integrity.builder.corpus import Paragraph
from integrity.common.settings import Settings, Stratum


@dataclass(frozen=True)
class StratumRule:
    name: str
    work_ids: tuple[str, ...]
    locator_regex: str | None
    paragraph_in: tuple[tuple[int, int], ...] | None
    weight: float

    def matches(self, p: Paragraph) -> bool:
        if p.work_id not in self.work_ids:
            return False
        if self.locator_regex and not re.search(self.locator_regex, p.locator):
            return False
        if self.paragraph_in is None:
            return True
        return p.paragraph is not None and any(a <= p.paragraph <= b for a, b in self.paragraph_in)


def parse_ranges(items: list[int | str] | None) -> tuple[tuple[int, int], ...] | None:
    if items is None:
        return None
    out = []
    for it in items:
        if isinstance(it, int):
            out.append((it, it))
            continue
        s = str(it).strip()
        m = re.fullmatch(r"(\d+)\s*-\s*(\d+)", s)
        if m:
            out.append((int(m.group(1)), int(m.group(2))))
        elif s.isdigit():
            out.append((int(s), int(s)))
        else:
            raise ValueError(f"bad paragraph_in entry {it!r}")
    return tuple(out)


def rule_from(s: Stratum) -> StratumRule:
    return StratumRule(s.name, tuple(s.work_id), s.locator_regex, parse_ranges(s.paragraph_in), s.weight)


def author_strata(
    settings: Settings, paragraphs: list[Paragraph], automatic: bool = False
) -> dict[str, list[StratumRule]]:
    """author -> ordered strata rules. Authors with no configured strata (or automatic=True) get one
    automatic stratum per work with equal weights."""
    works: OrderedDict[str, OrderedDict[str, None]] = OrderedDict()
    for p in paragraphs:
        works.setdefault(p.author, OrderedDict())[p.work_id] = None
    configured = [rule_from(s) for s in settings.strata]
    out: dict[str, list[StratumRule]] = {}
    for author, wids in works.items():
        mine = [] if automatic else [r for r in configured if any(w in wids for w in r.work_ids)]
        if not mine:
            mine = [StratumRule(w, (w,), None, None, 1.0) for w in wids]
        out[author] = mine
    return out


def assign(p: Paragraph, rules: list[StratumRule]) -> str | None:
    """First matching stratum wins."""
    for r in rules:
        if r.matches(p):
            return r.name
    return None
