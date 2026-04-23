import dataclasses
import logging
import os
import sqlite3
from datetime import datetime

import db
import md

DATA_DIR = "data"

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
                lines.append(md.render_message(msg, user_map))
                msg_count += 1

                replies = list(db.iter_thread_replies(conn, channel.id, msg.ts))
                if replies:
                    for i, reply in enumerate(replies):
                        reply = dataclasses.replace(reply, files=list(db.iter_files_for_message(conn, reply.ts)))
                        lines.append(md.render_message(reply, user_map, prefix="> "))
                        if i < len(replies) - 1:
                            lines.append(">")
                    lines.append("")

            out_path = os.path.join(out_dir, f"{year:04d}-{month:02d}.md")
            with open(out_path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))

            logger.info("Exported #%s %s → %s (%d messages)", channel.name, month_label, out_path, msg_count)
            total_files += 1

    logger.info("Export complete: %d file(s) written", total_files)
