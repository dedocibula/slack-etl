import os
from datetime import datetime

from export import export_markdown
from main import download_attachments, extract
from models import Channel, File, Message, User


def _ts(dt: datetime) -> str:
    return f"{dt.timestamp():.6f}"


MSG1_TS  = _ts(datetime(2026, 4, 27, 10,  0, 0))   # top-level, has mention
MSG2_TS  = _ts(datetime(2026, 4, 27, 10,  5, 0))   # thread parent + file attachment
REPLY_TS = _ts(datetime(2026, 4, 27, 10, 10, 0))   # thread reply, has mention


class FakeSlackClient:
    def iter_users(self):
        yield User(id="U1", name="alice")
        yield User(id="U2", name="bob")

    def iter_channels(self):
        yield Channel(id="C1", name="general", is_private=False)

    def iter_history(self, channel_id, oldest=None):
        yield Message(ts=MSG1_TS, user="U1", text="hello <@U2> how are you?")
        yield Message(
            ts=MSG2_TS, user="U2", text="check this out",
            thread_ts=MSG2_TS,
            files=[File(id="F1", message_ts=MSG2_TS,
                        url="https://files.slack.com/files/report.pdf")],
        )

    def iter_replies(self, channel_id, thread_ts):
        yield Message(ts=REPLY_TS, user="U1", text="nice work <@U2>!", thread_ts=thread_ts)

    def download_file(self, url, dest_path):
        with open(dest_path, "wb") as f:
            f.write(b"x" * 128)


def test_full_pipeline(db_conn, tmp_path, monkeypatch):
    """
    Smoke test: FakeSlackClient → extract → download_attachments → export_markdown.
    Verifies the output .md file contains correct content end-to-end.
    """
    attachments_dir = tmp_path / "_attachments"
    attachments_dir.mkdir()
    data_dir = str(tmp_path / "data")
    monkeypatch.setattr("main.ATTACHMENTS_DIR", str(attachments_dir))

    slack = FakeSlackClient()

    extract(slack, db_conn)
    download_attachments(slack, db_conn)
    export_markdown(db_conn, data_dir)

    md_path = os.path.join(data_dir, "general", "2026-04.md")
    assert os.path.exists(md_path), "expected output file not created"
    content = open(md_path).read()

    # Header
    assert "# #general - April 2026" in content

    # Author resolution
    assert "<@alice>" in content
    assert "<@bob>" in content

    # Inline mention resolution: raw IDs must be gone
    assert "<@U1>" not in content
    assert "<@U2>" not in content

    # Thread reply is blockquoted
    assert "> " in content
    assert "nice work" in content

    # File attachment rendered
    assert "![report.pdf](../../_attachments/F1)" in content
