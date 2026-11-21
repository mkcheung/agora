"""Seeded sampler (plan section 7.4): author quotas, stratum quotas, positional bins, replacement candidates."""

from __future__ import annotations

import os
import random
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Literal

from integrity.builder.corpus import Paragraph
from integrity.builder.strata import StratumRule, assign, author_strata
from integrity.common.settings import Settings


@dataclass
class Slot:
    slot: str
    kind: Literal["passage", "false_premise"]
    author: str
    stratum: str
    bin: int
    candidates: list[Paragraph]  # replacement order within the bin; candidates[0] is the planned paragraph
    tried: list[dict] = field(default_factory=list)

    @property
    def planned(self) -> Paragraph:
        return self.candidates[0]


def new_seed() -> int:
    return int.from_bytes(os.urandom(4), "big")


def _split(q: int, weights: dict[str, float], rng: random.Random) -> dict[str, int]:
    """floor(q*w) each; leftovers one at a time by a seeded weighted draw without replacement,
    weighted by the remainders q*w - floor(q*w) (so the expectation is exactly q*w)."""
    total = sum(weights.values())
    shares = {k: q * w / total for k, w in weights.items()}
    out = {k: int(s + 1e-9) for k, s in shares.items()}
    pool = {k: max(0.0, shares[k] - out[k]) for k in weights}
    for _ in range(q - sum(out.values())):
        cands = list(pool)
        tot = sum(pool.values())
        if tot <= 1e-9:
            pick = cands[int(rng.random() * len(cands))]
        else:
            r = rng.random() * tot
            acc = 0.0
            pick = cands[-1]
            for k in cands:
                acc += pool[k]
                if r < acc:
                    pick = k
                    break
        out[pick] += 1
        del pool[pick]
        if not pool:
            break
    return out


def allocate(q: int, weights: dict[str, float], rng: random.Random, caps: dict[str, int] | None = None) -> dict[str, int]:
    """Allocate q slots by weight. With caps, a key that cannot take its share is filled to its cap and
    the excess passes to the other keys proportionally to their weights."""
    result = {k: 0 for k in weights}
    active = {k: w for k, w in weights.items() if w > 0 and (caps is None or caps.get(k, 0) > 0)}
    remaining = q
    while remaining > 0 and active:
        grant = _split(remaining, active, rng)
        over = [k for k in active if caps is not None and grant[k] > caps[k]]
        if not over:
            for k, g in grant.items():
                result[k] += g
            break
        for k in over:
            result[k] = caps[k]  # type: ignore[index]
            del active[k]
        remaining = q - sum(result.values())
    return result


def make_bins(items: list[Paragraph], n: int) -> list[list[Paragraph]]:
    """n contiguous bins of (nearly) equal size over position order."""
    size = len(items)
    return [items[i * size // n : (i + 1) * size // n] for i in range(n)]


def plan_slots(
    eligible: list[Paragraph],
    settings: Settings,
    *,
    count: int,
    false_premise: int = 0,
    seed: int,
    authors: list[str] | None = None,
    automatic_strata: bool = False,
) -> list[Slot]:
    """The slot plan. Same seed, corpus, config and used set -> identical plan."""
    rng = random.Random(seed)
    strata_by_author = author_strata(settings, eligible, automatic=automatic_strata)
    pools: OrderedDict[str, OrderedDict[str, list[Paragraph]]] = OrderedDict()
    rules_of: dict[str, dict[str, StratumRule]] = {}
    for author, rules in strata_by_author.items():
        if authors is not None and author not in authors:
            continue
        rules_of[author] = {r.name: r for r in rules}
        buckets: OrderedDict[str, list[Paragraph]] = OrderedDict((r.name, []) for r in rules)
        for p in eligible:
            if p.author == author:
                name = assign(p, rules)
                if name is not None:
                    buckets[name].append(p)
        for lst in buckets.values():
            lst.sort(key=lambda p: p.sort_key)
        if any(buckets.values()):
            pools[author] = buckets

    slots: list[Slot] = []
    taken: set[str] = set()  # every candidate of the passage slots; false-premise slots never reuse them
    full_pools = pools
    for kind, n in (("passage", count), ("false_premise", false_premise)):
        pools = OrderedDict(
            (a, OrderedDict((s, [p for p in lst if p.block_id not in taken]) for s, lst in b.items()))
            for a, b in full_pools.items()
        )
        pools = OrderedDict((a, b) for a, b in pools.items() if any(b.values()))
        if n <= 0 or not pools:
            continue
        cfg = settings.sampling.author_weights
        aw = {a: (float(cfg.get(a, 1.0)) if cfg else 1.0) for a in pools}
        quotas = allocate(n, aw, rng, {a: sum(len(v) for v in pools[a].values()) for a in pools})
        for author in pools:  # corpus author order, then config stratum order, then bin
            q = quotas.get(author, 0)
            if q <= 0:
                continue
            buckets = pools[author]
            sw = {s: rules_of[author][s].weight for s in buckets}
            sq = allocate(q, sw, rng, {s: len(v) for s, v in buckets.items()})
            for sname in buckets:
                nslots = sq.get(sname, 0)
                if nslots <= 0:
                    continue
                for b, content in enumerate(make_bins(buckets[sname], nslots)):
                    order = rng.sample(content, min(len(content), settings.build.max_attempts_per_slot))
                    tag = "fp" if kind == "false_premise" else ""
                    slots.append(Slot(f"{sname}#{tag}{b + 1}", kind, author, sname, b, order))
                    taken.update(c.block_id for c in order)
    return slots
