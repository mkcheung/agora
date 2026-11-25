"""Keep test-only LangChain callbacks offline, including background workers."""

import os

# Set these before application imports load .env; do not change project settings.
os.environ["LANGSMITH_TRACING"] = "false"
os.environ["LANGCHAIN_TRACING_V2"] = "false"


import pytest


@pytest.fixture(scope='session')
def require_epubs():
    from ingest import ROOT, WORKS
    if not all((ROOT / w['file']).is_file() for w in WORKS):
        pytest.skip('Downloaded Gutenberg EPUBs are ignored local integration inputs')
