from datetime import datetime

import pytest

import export
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
        assert export._ts_to_str(ts(APR)) in content

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
        assert "../../_attachments/FA" in content
        assert "../../_attachments/FB" in content

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


class TestExportHelpers:

    def test_ts_to_str(self):
        dt = datetime(2026, 4, 15, 9, 15, 0)
        assert export._ts_to_str(ts(dt)) == "2026-04-15 09:15:00"

    def test_filename_from_url(self):
        assert export._filename_from_url("https://files.slack.com/files/report.pdf", "F1") == "report.pdf"

    def test_filename_falls_back_to_id(self):
        assert export._filename_from_url(None, "F99") == "F99"

    def test_render_message_top_level(self):
        u = User(id="U1", name="bob")
        msg = Message(ts=ts(APR), user="U1", text="hey", files=[])
        result = export._render_message(msg, {"U1": u})
        assert "**[" in result
        assert "<@bob>" in result
        assert "hey" in result
        assert not result.startswith(">")

    def test_render_message_reply_prefix(self):
        u = User(id="U1", name="bob")
        msg = Message(ts=ts(APR), user="U1", text="reply text", files=[])
        result = export._render_message(msg, {"U1": u}, prefix="> ")
        assert result.startswith("> **[")
        assert "> reply text" in result

    def test_render_message_unknown_user(self):
        msg = Message(ts=ts(APR), user=None, text="anon", files=[])
        result = export._render_message(msg, {})
        assert "<@unknown>" in result


class TestResolveMentions:

    def test_known_user_resolved(self):
        u = User(id="U1", name="alice")
        result = export._resolve_mentions("hello <@U1>", {"U1": u})
        assert result == "hello <@alice>"

    def test_unknown_user_left_as_is(self):
        result = export._resolve_mentions("hello <@UUNKNOWN>", {})
        assert result == "hello <@UUNKNOWN>"

    def test_multiple_mentions_in_one_message(self):
        u1 = User(id="U1", name="alice")
        u2 = User(id="U2", name="bob")
        result = export._resolve_mentions("<@U1> and <@U2>", {"U1": u1, "U2": u2})
        assert result == "<@alice> and <@bob>"

    def test_mixed_known_and_unknown(self):
        u1 = User(id="U1", name="alice")
        result = export._resolve_mentions("<@U1> cc <@UGONE>", {"U1": u1})
        assert result == "<@alice> cc <@UGONE>"

    def test_no_mentions_unchanged(self):
        result = export._resolve_mentions("plain text message", {})
        assert result == "plain text message"

    def test_empty_text(self):
        result = export._resolve_mentions("", {})
        assert result == ""

    def test_mention_in_rendered_message_body(self):
        """Integration: mention in message.text is resolved in the full rendered output."""
        u1 = User(id="U1", name="alice")
        u2 = User(id="U2", name="bob")
        msg = Message(ts=ts(APR), user="U1", text="hey <@U2> how are you", files=[])
        result = export._render_message(msg, {"U1": u1, "U2": u2})
        assert "<@bob>" in result
        assert "<@U2>" not in result

    def test_mention_in_exported_file(self, db_conn, channel, user, data_dir):
        """End-to-end: mention in stored message text is resolved in the .md file."""
        from db import upsert_user
        u2 = User(id="U2", name="bob")
        upsert_user(db_conn, u2)
        insert_message(db_conn, channel.id, Message(ts=ts(APR), user=user.id,
                                                     text="ping <@U2> are you there"))

        export_markdown(db_conn, data_dir)

        content = open(f"{data_dir}/general/2026-04.md").read()
        assert "<@bob>" in content
        assert "<@U2>" not in content
