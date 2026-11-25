"""Runner (plan section 9.2): ask each card's question, one at a time, and record raw answers."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from integrity.common import storage
from integrity.common.schema import Card
from integrity.quiz.agora import ContractViolation

EXIT_AGORA, EXIT_RUN_FAILED = 3, 5
CREDIT_MESSAGE = (
    "integrity quiz: provider credits are exhausted; stopped without further answer or grading calls.\n"
    "Saved answers and the credit-error receipt are preserved in raw.jsonl. "
    "Restore credits and start a fresh run; --resume cannot produce a clean baseline from saved credit errors.\n"
)


def _credit_error(error: dict[str, str] | None) -> bool:
    message = (error or {}).get("message", "").lower()
    return any(marker in message for marker in
               ("insufficient_quota", "credit_balance_exhausted", "credit balance is too low"))


class CallTimeout(Exception):
    pass


@dataclass
class RunnerOutcome:
    records: list[dict[str, Any]] = field(default_factory=list)  # one per card, in card order
    timeouts: list[str] = field(default_factory=list)
    aborted: tuple[int, str] | None = None
    first_info: dict[str, Any] | None = None
    dropped_lines: int = 0  # incomplete final raw.jsonl line discarded on resume
    interrupted: bool = False  # Ctrl-C: raw.jsonl keeps every finished card, so --resume continues

    @property
    def all_errored(self) -> bool:
        return bool(self.records) and all(r.get("error") for r in self.records)


def call_with_timeout(fn: Callable[[str], Any], arg: str, timeout_s: float) -> Any:
    """Run fn(arg) in a daemon worker thread; a timed-out thread is abandoned (it cannot be killed)."""
    box: dict[str, Any] = {}

    def target() -> None:
        try:
            box["value"] = fn(arg)
        except BaseException as e:  # noqa: BLE001
            box["error"] = e

    t = threading.Thread(target=target, daemon=True)
    t.start()
    t.join(timeout_s)
    if t.is_alive():
        raise CallTimeout(f"no answer within {timeout_s}s")
    if "error" in box:
        raise box["error"]
    return box["value"]


def read_raw(path: Path, *, tolerate_torn_tail: bool = False) -> dict[str, dict[str, Any]]:
    """Last line per card_id."""
    return {r["card_id"]: r for r in storage.read_jsonl(path, tolerate_torn_tail=tolerate_torn_tail)}


def run_cards(
    cards: list[Card],
    ask: Callable[[str], dict[str, Any]],
    run_dir: Path,
    *,
    timeout_s: float,
    retries: int,
    on_progress: Callable[[dict], None] | None = None,
) -> RunnerOutcome:
    """Ask every card (skipping cards that already have a line in raw.jsonl, which is how --resume works)."""
    raw_path = run_dir / "raw.jsonl"
    lines, dropped = storage.read_jsonl_ex(raw_path, tolerate_torn_tail=True)
    if dropped:  # rewrite without the torn tail so that new lines are not glued onto it
        storage.write_jsonl_atomic(raw_path, lines)
    done = {r["card_id"]: r for r in lines}
    out = RunnerOutcome(dropped_lines=dropped)
    emit = on_progress or (lambda e: None)
    contract_ok = any(r.get("result") for r in done.values())
    total = len(cards)
    for i, card in enumerate(cards, start=1):
        if card.card_id in done:
            rec = done[card.card_id]
            out.records.append(rec)
            if _credit_error(rec.get("error")):
                out.aborted = (EXIT_RUN_FAILED, CREDIT_MESSAGE)
                return out
            if out.first_info is None and rec.get("result"):
                out.first_info = rec["result"].get("info")
            continue
        emit({"event": "card_started", "card_id": card.card_id, "index": i, "total": total})
        started = storage.iso_z(storage.utc_now())
        t0 = time.monotonic()
        result: dict[str, Any] | None = None
        error: dict[str, str] | None = None
        attempts = 0
        violation: ContractViolation | None = None
        for attempt in range(retries + 1):
            attempts = attempt + 1
            try:
                result = call_with_timeout(ask, card.question, timeout_s)
                error = None
                break
            except ContractViolation as e:
                violation = e
                error = {"type": "contract_violation", "message": str(e)[:2000]}
                break  # never retried
            except CallTimeout as e:
                error = {"type": "timeout", "message": str(e)}
                out.timeouts.append(card.card_id)
            except KeyboardInterrupt:
                out.interrupted = True
                return out
            except (Exception, SystemExit) as e:  # noqa: BLE001  (Agora calling sys.exit() is an error for this card)
                error = {"type": type(e).__name__, "message": str(e)[:2000]}
                if _credit_error(error):
                    out.aborted = (EXIT_RUN_FAILED, CREDIT_MESSAGE)
                    break
        rec = {
            "card_id": card.card_id, "question": card.question, "started_at": started,
            "latency_s": round(time.monotonic() - t0, 3), "attempts": attempts,
            "result": result, "error": error,
        }
        storage.append_jsonl(raw_path, rec)
        out.records.append(rec)
        emit({"event": "card_finished", "card_id": card.card_id, "index": i, "total": total,
              "ok": error is None, "latency_s": rec["latency_s"]})
        if out.aborted:
            return out
        if result is not None:
            contract_ok = True
            if out.first_info is None:
                out.first_info = result.get("info")
        if violation is not None and not contract_ok:
            from integrity.quiz.agora import CONTRACT_SUMMARY
            out.aborted = (EXIT_AGORA, "integrity quiz: the Agora result for the first card breaks the contract: "
                                       + f"{violation}\n\n{CONTRACT_SUMMARY}\n")
            return out
    return out
