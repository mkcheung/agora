"""Atomic writes, JSONL appends, lock files, and run/batch directory helpers."""

from __future__ import annotations

import json
import os
import re
import tempfile
import time
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Self


class LockError(Exception):
    """A lock is held by a live process."""


def _dump(obj: Any, indent: int | None = 2) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=indent) + "\n"


def atomic_write_text(path: str | Path, text: str, *, overwrite: bool = True, mode: int | None = None) -> Path:
    """Write text via a temp file in the same directory, then os.replace.

    With overwrite=False the write is write-once: an existing file raises FileExistsError
    (implemented with an atomic hard link, so it is race-free).
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not overwrite and path.exists():
        raise FileExistsError(str(path))
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        if mode is not None:
            os.chmod(tmp, mode)
        if overwrite:
            os.replace(tmp, path)
        else:
            os.link(tmp, path)  # raises FileExistsError if it appeared meanwhile
            os.unlink(tmp)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return path


def atomic_write_json(path: str | Path, obj: Any, *, overwrite: bool = True, mode: int | None = None) -> Path:
    return atomic_write_text(path, _dump(obj), overwrite=overwrite, mode=mode)


def read_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def append_jsonl(path: str | Path, obj: Any) -> None:
    """Append one JSON line, flushed and fsynced."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n"
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(line)
        fh.flush()
        os.fsync(fh.fileno())


class JsonlError(ValueError):
    """A line in a JSONL file is not valid JSON (other than a torn final line when that is tolerated)."""


def read_jsonl_ex(path: str | Path, *, tolerate_torn_tail: bool = False) -> tuple[list[Any], int]:
    """Return (records, dropped). A single unparseable FINAL line is dropped (dropped == 1) only when
    ``tolerate_torn_tail``; an unparseable line anywhere else always raises JsonlError."""
    path = Path(path)
    if not path.exists():
        return [], 0
    lines = [(n, line) for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1) if line.strip()]
    out: list[Any] = []
    dropped = 0
    for i, (n, line) in enumerate(lines):
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError as e:
            if tolerate_torn_tail and i == len(lines) - 1:
                dropped = 1
                break
            raise JsonlError(f"{path.name} line {n} is not valid JSON ({e.msg}); the file is corrupt") from e
    return out, dropped


def read_jsonl(path: str | Path, *, tolerate_torn_tail: bool = False) -> list[Any]:
    return read_jsonl_ex(path, tolerate_torn_tail=tolerate_torn_tail)[0]


def write_jsonl_atomic(path: str | Path, records: Iterable[Any]) -> Path:
    text = "".join(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n" for r in records)
    return atomic_write_text(path, text)


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class FileLock:
    """Lock file that records the owner PID; a lock whose process is gone is stale and is taken over."""

    GRACE_SECONDS = 10.0

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._held = False

    def holder(self) -> int | None:
        try:
            return int(self.path.read_text().split()[0])
        except (OSError, ValueError, IndexError):
            return None

    def is_stale(self) -> bool:
        if not self.path.exists():
            return False
        pid = self.holder()
        if pid is None:
            # An empty/garbage file may be a lock being written right now (created, PID not yet written):
            # treat it as live unless it is older than GRACE_SECONDS.
            try:
                age = time.time() - self.path.stat().st_mtime
            except OSError:
                return False
            return age >= self.GRACE_SECONDS
        return not pid_alive(pid)

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(2):
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                if self.is_stale():
                    try:
                        self.path.unlink()
                    except FileNotFoundError:
                        pass
                    continue
                raise LockError(f"{self.path} is held by process {self.holder()}") from None
            with os.fdopen(fd, "w") as fh:
                fh.write(f"{os.getpid()}\n")
            self._held = True
            return
        raise LockError(f"could not acquire {self.path}")

    def release(self) -> None:
        if self._held:
            if self.holder() != os.getpid():  # taken over by someone else: it is not ours to remove
                self._held = False
                return
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass
            self._held = False

    def __enter__(self) -> Self:
        self.acquire()
        return self

    def __exit__(self, *exc: object) -> None:
        self.release()


def utc_now() -> datetime:
    return datetime.now(UTC)


def iso_z(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


BATCH_ID_RE = re.compile(r"^b-[0-9]{8}-[0-9]{6}-s[0-9]+$")
RUN_ID_RE = re.compile(r"^r-[0-9]{8}-[0-9]{6}$")
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")  # card ids and other ids that appear in paths


def check_batch_id(batch_id: str) -> str:
    """Return ``batch_id`` if it is exactly b-YYYYMMDD-HHMMSS-s<seed>; ValueError otherwise (path safety)."""
    if not isinstance(batch_id, str) or not BATCH_ID_RE.fullmatch(batch_id):
        raise ValueError(f"invalid batch id {batch_id!r} (expected b-YYYYMMDD-HHMMSS-s<seed>)")
    return batch_id


def check_run_id(run_id: str) -> str:
    """Return ``run_id`` if it is exactly r-YYYYMMDD-HHMMSS; ValueError otherwise (path safety)."""
    if not isinstance(run_id, str) or not RUN_ID_RE.fullmatch(run_id):
        raise ValueError(f"invalid run id {run_id!r} (expected r-YYYYMMDD-HHMMSS)")
    return run_id


def check_safe_id(value: str, what: str = "id") -> str:
    if not isinstance(value, str) or not SAFE_ID_RE.fullmatch(value):
        raise ValueError(f"invalid {what} {value!r}")
    return value


def new_batch_id(seed: int, now: datetime | None = None) -> str:
    """b-YYYYMMDD-HHMMSS-s<seed>"""
    now = now or utc_now()
    return f"b-{now.strftime('%Y%m%d-%H%M%S')}-s{seed}"


def new_run_id(now: datetime | None = None) -> str:
    """r-YYYYMMDD-HHMMSS"""
    now = now or utc_now()
    return f"r-{now.strftime('%Y%m%d-%H%M%S')}"


def sheets_dir(data_dir: str | Path) -> Path:
    return Path(data_dir) / "sheets"


def batch_dir(data_dir: str | Path, batch_id: str) -> Path:
    return Path(data_dir) / "drafts" / batch_id


def run_dir(data_dir: str | Path, run_id: str) -> Path:
    return Path(data_dir) / "runs" / run_id


def runs_lock_path(data_dir: str | Path) -> Path:
    return Path(data_dir) / "runs" / ".lock"


def batch_lock_path(data_dir: str | Path, batch_id: str) -> Path:
    return batch_dir(data_dir, batch_id) / ".lock"
