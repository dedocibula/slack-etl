import os
import subprocess
import sys

OSASCRIPT_BIN = "/usr/bin/osascript"


def notify(title: str, message: str, subtitle: str = "slack-etl") -> None:
    """
    Fire-and-forget macOS notification.
    Silently no-ops if osascript is not available (e.g. non-macOS or CI).
    """
    if not os.path.exists(OSASCRIPT_BIN):
        return

    # Escape double quotes for AppleScript
    title = title.replace('"', '\\"')
    message = message.replace('"', '\\"')
    subtitle = subtitle.replace('"', '\\"')

    script = f'display notification "{message}" with title "{title}" subtitle "{subtitle}"'

    try:
        subprocess.run(
            [OSASCRIPT_BIN, "-e", script],
            check=False,
            capture_output=True,
            timeout=5,
        )
    except Exception:
        # Notification failure must never crash the pipeline
        pass


def fatal(title: str, message: str) -> None:
    """
    Fire a notification and exit with code 1.
    Use only for unrecoverable states (quota exhausted, disk full, token revoked).
    """
    notify(title, message)
    sys.exit(1)
