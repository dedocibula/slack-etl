import logging
import logging.handlers
import os
import shutil
import sys

from dotenv import load_dotenv

import db
import notifier

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

# ============================================================================
# Logging Setup
# ============================================================================


def setup_logging() -> None:
    """Configure rotating file logger and stderr stream."""
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    # Ensure log directory exists
    os.makedirs(LOG_DIR, exist_ok=True)

    # Rotating file handler (DEBUG level, full detail)
    file_handler = logging.handlers.RotatingFileHandler(
        LOG_FILE,
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
    )
    file_handler.setLevel(logging.DEBUG)
    file_formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(file_formatter)
    root_logger.addHandler(file_handler)

    # Stream handler to stderr (WARNING and above only)
    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setLevel(logging.WARNING)
    stream_formatter = logging.Formatter("%(levelname)s: %(message)s")
    stream_handler.setFormatter(stream_formatter)
    root_logger.addHandler(stream_handler)


# ============================================================================
# Environment Verification
# ============================================================================


def load_token() -> str:
    """Load Slack user token from ~/.env (key=value format)."""
    if not os.path.exists(ENV_FILE):
        notifier.fatal(
            "Configuration Error",
            f"Token file not found at {ENV_FILE}",
        )

    load_dotenv(ENV_FILE)
    token = os.environ.get("SLACK_USER_TOKEN", "").strip()

    if not token:
        notifier.fatal(
            "Configuration Error",
            f"SLACK_USER_TOKEN not found in {ENV_FILE}",
        )

    if not token.startswith(TOKEN_PREFIX):
        notifier.fatal(
            "Configuration Error",
            f"Token must start with '{TOKEN_PREFIX}'",
        )

    return token


def verify_environment() -> str:
    """
    Check all system dependencies at startup.
    Returns the validated token.
    Raises on critical failures, warns on non-critical issues.
    """
    logger = logging.getLogger(__name__)

    # 1. Load and validate token
    token = load_token()
    logger.debug("Token loaded from %s", ENV_FILE)

    # 2. Warn if osascript is missing (not fatal, just won't notify)
    if not os.path.exists(notifier.OSASCRIPT_BIN):
        logger.warning(
            "osascript not found at %s; macOS notifications disabled",
            notifier.OSASCRIPT_BIN,
        )

    # 3. Create required directories
    for dir_path in [LOG_DIR, DATA_DIR, ATTACHMENTS_DIR]:
        os.makedirs(dir_path, exist_ok=True)
        logger.debug("Ensured directory exists: %s", dir_path)

    # 4. Check available disk space
    stat = shutil.disk_usage(".")
    free_bytes = stat.free
    if free_bytes < DISK_FATAL_THRESHOLD_BYTES:
        notifier.fatal(
            "Disk Full",
            f"Less than {DISK_FATAL_THRESHOLD_BYTES // 1024 // 1024} MB free",
        )
    if free_bytes < DISK_WARN_THRESHOLD_BYTES:
        logger.warning(
            "Low disk space: %.2f GB free",
            free_bytes / 1024 / 1024 / 1024,
        )
    logger.debug("Disk space check passed: %.2f GB free", free_bytes / 1024 / 1024 / 1024)

    return token


# ============================================================================
# Main Pipeline
# ============================================================================


def main() -> None:
    """Entry point: setup, verify environment, initialize DB, run pipeline."""
    setup_logging()
    logger = logging.getLogger(__name__)
    logger.info("=== slack-etl pipeline starting ===")

    try:
        token = verify_environment()
        logger.info("Environment verification passed")

        # Initialize database
        conn = db.get_connection()
        db.init_schema(conn)
        logger.info("Database initialized")

        # Placeholder: Extraction logic will go here in Milestone 3
        logger.info("(Extraction logic not yet implemented)")

        logger.info("=== slack-etl pipeline complete ===")

    except Exception as e:
        logger.exception("Unhandled exception in pipeline")
        notifier.notify("slack-etl failed", str(e))
        sys.exit(1)


if __name__ == "__main__":
    main()
