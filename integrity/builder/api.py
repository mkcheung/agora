"""Python API of Part A (plan section 9.9). The CLI is a thin wrapper around these functions."""

from __future__ import annotations

from integrity.builder.build import BatchSummary, BuildError, run_build
from integrity.common.llm import ModelClient
from integrity.common.settings import Settings, load_settings

__all__ = ["BatchSummary", "BuildError", "build"]


def build(
    count: int | None = None,
    false_premise: int | None = None,
    sources: list[str] | None = None,
    authors: list[str] | None = None,
    seed: int | None = None,
    dry_run: bool = False,
    *,
    settings: Settings | None = None,
    drafter_client: ModelClient | None = None,
    attribution_client: ModelClient | None = None,
) -> BatchSummary:
    """Sample paragraphs, draft and check cards, write a batch. dry_run plans and renders prompts only."""
    settings = settings or load_settings()
    return run_build(
        settings,
        count=settings.build.default_count if count is None else count,
        false_premise=settings.build.default_false_premise if false_premise is None else false_premise,
        sources=sources, authors=authors, seed=seed, dry_run=dry_run,
        drafter_client=drafter_client, attribution_client=attribution_client,
        options={"count": count, "false_premise": false_premise, "sources": sources, "authors": authors,
                 "dry_run": dry_run},
    )
