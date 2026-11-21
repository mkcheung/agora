"""Fake entrypoint module that reads AGORA_NAMESPACE at import time (like config.py does)."""

import os

NAMESPACE_AT_IMPORT = os.environ.get("AGORA_NAMESPACE")


def answer_question(question: str) -> dict:
    return {"answer": "x", "citations": [], "retrieved": [], "info": {"namespace": NAMESPACE_AT_IMPORT}}
