import os

# ============================================================================
# Configuration Constants
# ============================================================================

DISK_WARN_THRESHOLD_BYTES = 1 * 1024**3  # 1 GB
DISK_FATAL_THRESHOLD_BYTES = 100 * 1024**2  # 100 MB
TOKEN_PREFIX = "xoxp-"
ENV_FILE = os.path.expanduser("~/.env")
LOG_DIR = "logs"
DATA_DIR = "data"
ATTACHMENTS_DIR = "_attachments"
LOG_FILE = f"{LOG_DIR}/etl.log"
LOG_MAX_BYTES = 5 * 1024 * 1024  # 5 MB
LOG_BACKUP_COUNT = 5
