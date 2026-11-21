import json
import os
import subprocess
import sys
import time
from datetime import UTC

import pytest

from integrity.common import storage as st


def test_atomic_write_json_replaces_and_leaves_no_temp(tmp_path):
    p = tmp_path / "d" / "x.json"
    st.atomic_write_json(p, {"a": "é"})
    st.atomic_write_json(p, {"a": 2})
    assert json.loads(p.read_text()) == {"a": 2}
    assert [q.name for q in p.parent.iterdir()] == ["x.json"]


def test_atomic_write_failure_keeps_old_file(tmp_path):
    p = tmp_path / "x.json"
    st.atomic_write_json(p, {"ok": 1})
    with pytest.raises(TypeError):
        st.atomic_write_json(p, {"bad": object()})
    assert json.loads(p.read_text()) == {"ok": 1}


def test_write_once_and_mode(tmp_path):
    p = tmp_path / "w" / "s.json"
    st.atomic_write_json(p, {"a": 1}, overwrite=False, mode=0o444)
    assert (p.stat().st_mode & 0o777) == 0o444
    with pytest.raises(FileExistsError):
        st.atomic_write_json(p, {"a": 2}, overwrite=False)
    assert json.loads(p.read_text()) == {"a": 1}
    assert [q.name for q in p.parent.iterdir()] == ["s.json"]


def test_jsonl_append_and_read(tmp_path):
    p = tmp_path / "r" / "raw.jsonl"
    st.append_jsonl(p, {"a": 1})
    st.append_jsonl(p, {"b": "é"})
    assert st.read_jsonl(p) == [{"a": 1}, {"b": "é"}]
    assert st.read_jsonl(tmp_path / "none.jsonl") == []
    st.write_jsonl_atomic(p, [{"z": 1}])
    assert st.read_jsonl(p) == [{"z": 1}]


def test_lock_acquire_release_and_contention(tmp_path):
    p = tmp_path / "runs" / ".lock"
    a = st.FileLock(p)
    with a:
        assert p.read_text().split()[0] == str(os.getpid())
        with pytest.raises(st.LockError):
            st.FileLock(p).acquire()
    assert not p.exists()


def test_stale_lock_is_taken_over(tmp_path):
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    p = tmp_path / ".lock"
    p.write_text(f"{dead.pid}\n")
    lock = st.FileLock(p)
    assert lock.is_stale()
    lock.acquire()
    assert lock.holder() == os.getpid()
    lock.release()
    assert not p.exists()
    p.write_text("garbage")
    os.utime(p, (0, 0))  # old garbage file => stale
    assert st.FileLock(p).is_stale()


def test_fresh_empty_or_garbage_lock_is_live(tmp_path):
    p = tmp_path / ".lock"
    checked = 0
    for content in ("", "garbage"):
        p.write_text(content)  # just created: a writer may not have written its PID yet
        assert not st.FileLock(p).is_stale()
        with pytest.raises(st.LockError):
            st.FileLock(p).acquire()
        os.utime(p, (time.time() - 60, time.time() - 60))
        assert st.FileLock(p).is_stale()
        lock = st.FileLock(p)
        lock.acquire()
        assert lock.holder() == os.getpid()
        lock.release()
        checked += 1
    assert checked == 2


def test_release_does_not_unlink_a_lock_taken_by_another_pid(tmp_path):
    p = tmp_path / ".lock"
    lock = st.FileLock(p)
    lock.acquire()
    p.write_text(f"{os.getpid() + 1}\n")  # someone else took it over
    lock.release()
    assert p.exists() and p.read_text().split()[0] == str(os.getpid() + 1)


def test_ids_and_paths(tmp_path):
    from datetime import datetime

    now = datetime(2026, 11, 21, 10, 15, 0, tzinfo=UTC)
    assert st.new_batch_id(7, now) == "b-20261121-101500-s7"
    assert st.new_run_id(now) == "r-20261121-101500"
    assert st.iso_z(now) == "2026-11-21T10:15:00Z"
    assert st.batch_dir(tmp_path, "b") == tmp_path / "drafts" / "b"
    assert st.runs_lock_path(tmp_path) == tmp_path / "runs" / ".lock"
    assert st.batch_lock_path(tmp_path, "b") == tmp_path / "drafts" / "b" / ".lock"
    assert st.run_dir(tmp_path, "r") == tmp_path / "runs" / "r"
