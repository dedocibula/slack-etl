import dataclasses
import logging
import os
import re
import sqlite3
from datetime import datetime

import db
from config import ATTACHMENTS_DIR, DATA_DIR
from models import Message, User

# Edit these templates to change the output format.
# Available variables:
#   MESSAGE_TEMPLATE  : prefix, ts, username, text
#   ATTACHMENT_TEMPLATE : prefix, filename, path
MESSAGE_TEMPLATE = "{prefix}**[{ts}] <@{username}>:** {prefix}{text}"
ATTACHMENT_TEMPLATE = "{prefix}![{filename}]({path})"

logger = logging.getLogger(__name__)


def export_markdown(conn: sqlite3.Connection, data_dir: str = DATA_DIR) -> None:
    """Export all months with DB data to per-channel per-month Markdown files."""
    user_map = db.build_user_map(conn)
    total_files = 0

    for channel in db.iter_channels_from_db(conn):
        out_dir = os.path.join(data_dir, channel.name)
        os.makedirs(out_dir, exist_ok=True)

        for year, month in db.iter_distinct_months(conn, channel.id):
            month_start_dt = datetime(year, month, 1)
            if month < 12:
                month_end_dt = datetime(year, month + 1, 1)
            else:
                month_end_dt = datetime(year + 1, 1, 1)
            month_label = month_start_dt.strftime("%B %Y")

            lines = [f"# #{channel.name} - {month_label}", ""]
            msg_count = 0

            for msg in db.iter_top_level_messages(
                conn, channel.id, month_start_dt.timestamp(), month_end_dt.timestamp()
            ):
                msg = dataclasses.replace(msg, files=list(db.iter_files_for_message(conn, msg.ts)))
                lines.append(_render_message(msg, user_map))
                msg_count += 1

                replies = list(db.iter_thread_replies(conn, channel.id, msg.ts))
                if replies:
                    for i, reply in enumerate(replies):
                        reply = dataclasses.replace(reply, files=list(db.iter_files_for_message(conn, reply.ts)))
                        lines.append(_render_message(reply, user_map, prefix="> "))
                        if i < len(replies) - 1:
                            lines.append(">")
                    lines.append("")

            out_path = os.path.join(out_dir, f"{year:04d}-{month:02d}.md")
            with open(out_path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))

            logger.info("Exported #%s %s → %s (%d messages)", channel.name, month_label, out_path, msg_count)
            total_files += 1

    logger.info("Export complete: %d file(s) written", total_files)


def _render_message(msg: Message, user_map: dict[str, User], prefix: str = "") -> str:
    """Render a Message (with pre-populated files) as a markdown string."""
    u = user_map.get(msg.user) if msg.user else None
    username = u.name if u else "unknown"
    line = MESSAGE_TEMPLATE.format(
        prefix=prefix,
        ts=_ts_to_str(msg.ts),
        username=username,
        text=_resolve_mentions(msg.text or "", user_map),
    )

    attachment_lines = [
        ATTACHMENT_TEMPLATE.format(
            prefix=prefix,
            filename=_filename_from_url(f.url, f.id),
            path=f"../../{os.path.basename(ATTACHMENTS_DIR)}/{os.path.basename(f.local_path)}",
        )
        for f in msg.files
        if f.local_path is not None
    ]

    if attachment_lines:
        return line + "\n" + "\n".join(attachment_lines)
    return line


def _resolve_mentions(text: str, user_map: dict[str, User]) -> str:
    """Replace <@USERID> patterns in text with <@username>, leaving unknown IDs as-is."""
    def _replace(m: re.Match) -> str:
        user = user_map.get(m.group(1))
        return f"<@{user.name}>" if user else m.group(0)
    return re.sub(r"<@([A-Z0-9]+)>", _replace, text)


def _ts_to_str(ts: str) -> str:
    """Convert a Slack float-string timestamp to 'YYYY-MM-DD HH:MM:SS'."""
    return datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M:%S")


def _filename_from_url(url: str | None, file_id: str) -> str:
    """Extract the filename from a Slack URL, falling back to file_id."""
    if url:
        name = url.rsplit("/", 1)[-1]
        if name:
            return name
    return file_id
