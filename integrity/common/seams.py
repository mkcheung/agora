"""The two seams to the main program. Only builder/corpus.py and quiz/agora.py may call load()."""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from typing import Any


class SeamError(Exception):
    """A seam target could not be imported or resolved."""


def put_project_root_first(project_root: str | Path) -> str:
    root = str(Path(project_root).resolve())
    while root in sys.path:
        sys.path.remove(root)
    sys.path.insert(0, root)
    return root


def parse_spec(spec: str) -> tuple[str, str]:
    mod, sep, attr = spec.partition(":")
    if not sep or not mod or not attr:
        raise SeamError(f"invalid seam spec {spec!r}; expected 'module:attr'")
    return mod, attr


def load(spec: str, *, project_root: str | Path, namespace: str | None = None) -> Any:
    """Import "module:attr" lazily and return the attribute.

    The project root goes first on sys.path, and the namespace override (if any) is applied to
    AGORA_NAMESPACE *before* the import, because the main program reads it at import time.
    """
    mod_name, attr = parse_spec(spec)
    put_project_root_first(project_root)
    if namespace:
        os.environ["AGORA_NAMESPACE"] = namespace
    try:
        module = importlib.import_module(mod_name)
    except Exception as e:
        raise SeamError(f"cannot import {mod_name!r} for seam {spec!r}: {e}") from e
    try:
        return getattr(module, attr)
    except AttributeError as e:
        raise SeamError(f"module {mod_name!r} has no attribute {attr!r}") from e
