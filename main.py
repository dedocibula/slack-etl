import dataclasses
import logging
import logging.handlers
import os
import shutil
import sqlite3
import sys

from dotenv import load_dotenv

import db
import notifier
from slack_client import SlackClient

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
# Extraction
# ============================================================================


def extract(slack: SlackClient, conn: sqlite3.Connection) -> None:
    """Extract all users, channels, messages, threads, and file records."""
    logger = logging.getLogger(__name__)

    # Phase 1: Sync users; track known IDs to handle deleted/bot message authors
    known_user_ids: set[str] = set()
    user_count = 0
    for user in slack.iter_users():
        db.upsert_user(conn, user)
        known_user_ids.add(user.id)
        user_count += 1
    logger.info("Synced %d users", user_count)

    # Phase 2: Extract channels → messages → replies
    total_messages = 0
    for channel in slack.iter_channels():
        db.upsert_channel(conn, channel)

        last_ts = db.get_last_fetched_ts(conn, channel.id)
        logger.info("Processing #%s (oldest=%s)", channel.name, last_ts or "beginning")

        msg_count = 0
        last_msg_ts = None

        for msg in slack.iter_history(channel.id, oldest=last_ts):
            # Null out user if not in our DB (deleted/bot users are filtered at import)
            if msg.user not in known_user_ids:
                msg = dataclasses.replace(msg, user=None)
            db.insert_message(conn, channel.id, msg)

            for f in msg.files:
                db.insert_file(conn, f)

            # Fetch replies if this message is a thread parent (ts == thread_ts)
            if msg.thread_ts and msg.ts == msg.thread_ts:
                for reply in slack.iter_replies(channel.id, msg.thread_ts):
                    if reply.user not in known_user_ids:
                        reply = dataclasses.replace(reply, user=None)
                    db.insert_message(conn, channel.id, reply)
                    for f in reply.files:
                        db.insert_file(conn, f)

            last_msg_ts = msg.ts
            msg_count += 1

        # Commit sync_state only after the full channel completes
        if last_msg_ts:
            with db.transaction(conn):
                db.update_sync_state(conn, channel.id, last_msg_ts)

        logger.info("Processed #%s: %d messages", channel.name, msg_count)
        total_messages += msg_count

    logger.info("Extraction complete: %d messages across all channels", total_messages)


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

        conn = db.get_connection()
        db.init_schema(conn)
        logger.info("Database initialized")

        extract(SlackClient(token), conn)

        notifier.notify("slack-etl complete", "Extraction finished successfully")
        logger.info("=== slack-etl pipeline complete ===")

    except Exception as e:
        logger.exception("Unhandled exception in pipeline")
        notifier.notify("slack-etl failed", str(e))
        sys.exit(1)


if __name__ == "__main__":
    main()
