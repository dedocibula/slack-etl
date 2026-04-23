import dataclasses
from datetime import datetime

import pytest

import db as db_module
import md
from db import insert_file, insert_message, upsert_channel, upsert_user
from export import export_markdown
from models import Channel, File, Message, User


def ts(dt: datetime) -> str:
    """Convert a datetime to a Slack-style float timestamp string."""
    return f"{dt.timestamp():.6f}"


@pytest.fixture
def data_dir(tmp_path):
    return str(tmp_path / "data")


@pytest.fixture
def channel(db_conn):
    ch = Channel(id="C1", name="general", is_private=False)
    upsert_channel(db_conn, ch)
    return ch


@pytest.fixture
def user(db_conn):
    u = User(id="U1", name="alice")
    upsert_user(db_conn, u)
    return u


APR = datetime(2026, 4, 15, 9, 0, 0)
MAR = datetime(2026, 3, 10, 8, 0, 0)


class TestExportMarkdown:

    def test_creates_output_directory(self, db_conn, channel, user, data_dir):
        insert_message(db_conn, channel.id, Message(ts=ts(APR), user=user.id, text="hello"))

        export_markdown(db_conn, data_dir)

        import os
        assert os.path.isdir(f"{data_dir}/general")

    def test_creates_file_per_month(self, db_conn, channel, user, data_dir):
        import os
        insert_message(db_conn, channel.id, Message(ts=ts(APR), user=user.id, text="april msg"))

        export_markdown(db_conn, data_dir)

        assert os.path.exists(f"{data_dir}/general/2026-04.md")

    def test_header_format(self, db_conn, channel, user, data_dir):
        insert_message(db_conn, channel.id, Message(ts=ts(APR), user=user.id, text="hi"))

        export_markdown(db_conn, data_dir)

        content = open(f"{data_dir}/general/2026-04.md").read()
        assert content.startswith("# #general - April 2026")

    def test_top_level_message_format(self, db_conn, channel, user, data_dir):
        insert_message(db_conn, channel.id, Message(ts=ts(APR), user=user.id, text="hello world"))

        export_markdown(db_conn, data_dir)

        content = open(f"{data_dir}/general/2026-04.md").read()
        assert "<@alice>" in content
        assert "hello world" in content
        assert md.ts_to_str(ts(APR)) in content

    def test_null_user_renders_unknown(self, db_conn, channel, data_dir):
        insert_message(db_conn, channel.id, Message(ts=ts(APR), user=None, text="bot message"))

        export_markdown(db_conn, data_dir)

        content = open(f"{data_dir}/general/2026-04.md").read()
        assert "<@unknown>" in content

    def test_thread_replies_blockquoted(self, db_conn, channel, user, data_dir):
        parent_ts = ts(APR)
        reply_ts = ts(datetime(2026, 4, 15, 9, 5, 0))
        insert_message(db_conn, channel.id, Message(ts=parent_ts, user=user.id, text="parent",
                                                     thread_ts=parent_ts))
        insert_message(db_conn, channel.id, Message(ts=reply_ts, user=user.id, text="reply",
                                                     thread_ts=parent_ts))

        export_markdown(db_conn, data_dir)

        content = open(f"{data_dir}/general/2026-04.md").read()
        assert "> **[" in content
        assert "> reply" in content

    def test_separator_between_multiple_replies(self, db_conn, channel, user, data_dir):
        parent_ts = ts(APR)
        r1_ts = ts(datetime(2026, 4, 15, 9, 5, 0))
        r2_ts = ts(datetime(2026, 4, 15, 9, 10, 0))
        for t, text in [(parent_ts, "parent"), (r1_ts, "r1"), (r2_ts, "r2")]:
            insert_message(db_conn, channel.id, Message(ts=t, user=user.id, text=text,
                                                         thread_ts=parent_ts))

        export_markdown(db_conn, data_dir)

        lines = open(f"{data_dir}/general/2026-04.md").readlines()
        assert any(line.strip() == ">" for line in lines)

    def test_downloaded_file_rendered(self, db_conn, channel, user, data_dir, tmp_path):
        msg_ts = ts(APR)
        insert_message(db_conn, channel.id, Message(ts=msg_ts, user=user.id, text="see file"))
        dest = str(tmp_path / "F1")
        open(dest, "wb").close()
        insert_file(db_conn, File(id="F1", message_ts=msg_ts,
                                  url="https://files.slack.com/files/report.pdf",
                                  local_path=dest, size_bytes=0))

        export_markdown(db_conn, data_dir)

        content = open(f"{data_dir}/general/2026-04.md").read()
        assert "![report.pdf](../../_attachments/F1)" in content

    def test_undownloaded_file_skipped(self, db_conn, channel, user, data_dir):
        msg_ts = ts(APR)
        insert_message(db_conn, channel.id, Message(ts=msg_ts, user=user.id, text="pending"))
        insert_file(db_conn, File(id="F2", message_ts=msg_ts,
                                  url="https://files.slack.com/files/doc.pdf",
                                  local_path=None))

        export_markdown(db_conn, data_dir)

        content = open(f"{data_dir}/general/2026-04.md").read()
        assert "![" not in content

    def test_multiple_files_per_message(self, db_conn, channel, user, data_dir, tmp_path):
        msg_ts = ts(APR)
        insert_message(db_conn, channel.id, Message(ts=msg_ts, user=user.id, text="two files"))
        for fid in ("FA", "FB"):
            dest = str(tmp_path / fid)
            open(dest, "wb").close()
            insert_file(db_conn, File(id=fid, message_ts=msg_ts,
                                      url=f"https://files.slack.com/files/{fid}.txt",
                                      local_path=dest, size_bytes=0))

        export_markdown(db_conn, data_dir)

        content = open(f"{data_dir}/general/2026-04.md").read()
        assert f"../../_attachments/FA" in content
        assert f"../../_attachments/FB" in content

    def test_past_month_gets_own_file(self, db_conn, channel, user, data_dir):
        import os
        insert_message(db_conn, channel.id, Message(ts=ts(MAR), user=user.id, text="march msg"))
        insert_message(db_conn, channel.id, Message(ts=ts(APR), user=user.id, text="april msg"))

        export_markdown(db_conn, data_dir)

        assert os.path.exists(f"{data_dir}/general/2026-03.md")
        assert os.path.exists(f"{data_dir}/general/2026-04.md")
        assert "march msg" in open(f"{data_dir}/general/2026-03.md").read()
        assert "april msg" in open(f"{data_dir}/general/2026-04.md").read()

    def test_multiple_channels_each_get_file(self, db_conn, user, data_dir):
        import os
        for cid, name in [("C2", "random"), ("C3", "dev")]:
            upsert_channel(db_conn, Channel(id=cid, name=name, is_private=False))
            insert_message(db_conn, cid, Message(ts=ts(APR), user=user.id, text="msg"))

        export_markdown(db_conn, data_dir)

        assert os.path.exists(f"{data_dir}/random/2026-04.md")
        assert os.path.exists(f"{data_dir}/dev/2026-04.md")


class TestMdHelpers:

    def test_ts_to_str(self):
        dt = datetime(2026, 4, 15, 9, 15, 0)
        assert md.ts_to_str(ts(dt)) == "2026-04-15 09:15:00"

    def test_filename_from_url(self):
        assert md.filename_from_url("https://files.slack.com/files/report.pdf", "F1") == "report.pdf"

    def test_filename_falls_back_to_id(self):
        assert md.filename_from_url(None, "F99") == "F99"

    def test_render_message_top_level(self):
        u = User(id="U1", name="bob")
        msg = Message(ts=ts(APR), user="U1", text="hey", files=[])
        result = md.render_message(msg, {"U1": u})
        assert "**[" in result
        assert "<@bob>" in result
        assert "hey" in result
        assert not result.startswith(">")

    def test_render_message_reply_prefix(self):
        u = User(id="U1", name="bob")
        msg = Message(ts=ts(APR), user="U1", text="reply text", files=[])
        result = md.render_message(msg, {"U1": u}, prefix="> ")
        assert result.startswith("> **[")
        assert "> reply text" in result

    def test_render_message_unknown_user(self):
        msg = Message(ts=ts(APR), user=None, text="anon", files=[])
        result = md.render_message(msg, {})
        assert "<@unknown>" in result
