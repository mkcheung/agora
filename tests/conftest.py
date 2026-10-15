"""Keep test-only LangChain callbacks offline, including background workers."""

import os

# Set these before application imports load .env; do not change project settings.
os.environ["LANGSMITH_TRACING"] = "false"
os.environ["LANGCHAIN_TRACING_V2"] = "false"
