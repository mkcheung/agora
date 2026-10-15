import os

from dotenv import load_dotenv

load_dotenv()

EMBEDDING_DIMENSIONS = 1024
EMBEDDING_MODEL = "text-embedding-3-small"
INDEX_NAME = 'agora'
LEGACY_ID_PREFIX = "pg7370-chunk-"  # IDs from the first, metadata-less upload
DEFAULT_NAMESPACE = "epub-v1-04b8672ea20df6c7"
ACTIVE_NAMESPACE = os.getenv("AGORA_NAMESPACE", DEFAULT_NAMESPACE)
