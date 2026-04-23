from datetime import datetime

from models import File, Message, User

ATTACHMENTS_DIR = "_attachments"

# Edit these templates to change the output format.
# Available variables:
#   MESSAGE_TEMPLATE : prefix, ts, username, text
#   ATTACHMENT_TEMPLATE : prefix, filename, path
MESSAGE_TEMPLATE = "{prefix}**[{ts}] <@{username}>:** {prefix}{text}"
ATTACHMENT_TEMPLATE = "{prefix}![{filename}]({path})"


def render_message(msg: Message, user_map: dict[str, User], prefix: str = "") -> str:
    """Render a Message (with pre-populated files) as a markdown string."""
    u = user_map.get(msg.user) if msg.user else None
    username = u.name if u else "unknown"
    line = MESSAGE_TEMPLATE.format(
        prefix=prefix,
        ts=ts_to_str(msg.ts),
        username=username,
        text=msg.text or "",
    )

    attachment_lines = [
        ATTACHMENT_TEMPLATE.format(
            prefix=prefix,
            filename=filename_from_url(f.url, f.id),
            path=f"../../{ATTACHMENTS_DIR}/{f.id}",
        )
        for f in msg.files
        if f.local_path is not None
    ]

    if attachment_lines:
        return line + "\n" + "\n".join(attachment_lines)
    return line


def ts_to_str(ts: str) -> str:
    """Convert a Slack float-string timestamp to 'YYYY-MM-DD HH:MM:SS'."""
    return datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M:%S")


def filename_from_url(url: str | None, file_id: str) -> str:
    """Extract the filename from a Slack URL, falling back to file_id."""
    if url:
        name = url.rsplit("/", 1)[-1]
        if name:
            return name
    return file_id
