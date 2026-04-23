import os

from dotenv import load_dotenv

# Load ~/.env early so SLACK_ETL_DATA_ROOT (and the token) are available at
# import time, before any module-level constants are evaluated.
ENV_FILE = os.path.expanduser("~/.env")
load_dotenv(ENV_FILE)

# ============================================================================
# Configuration Constants
# ============================================================================

DISK_WARN_THRESHOLD_BYTES = 1 * 1024**3  # 1 GB
DISK_FATAL_THRESHOLD_BYTES = 100 * 1024**2  # 100 MB
TOKEN_PREFIX = "xoxp-"
LOG_DIR = "logs"
LOG_FILE = f"{LOG_DIR}/etl.log"
LOG_MAX_BYTES = 5 * 1024 * 1024  # 5 MB
LOG_BACKUP_COUNT = 5

# Optional: set SLACK_ETL_DATA_ROOT in ~/.env to store DB, data, and
# attachments outside the project directory.
_DATA_ROOT = os.environ.get("SLACK_ETL_DATA_ROOT", "").strip()

if _DATA_ROOT:
    DATA_DIR = os.path.join(_DATA_ROOT, "data")
    ATTACHMENTS_DIR = os.path.join(_DATA_ROOT, "_attachments")
    DB_PATH = os.path.join(_DATA_ROOT, "database.sqlite")
else:
    DATA_DIR = "data"
    ATTACHMENTS_DIR = "_attachments"
    DB_PATH = "database.sqlite"
