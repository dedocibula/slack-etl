from unittest.mock import MagicMock, patch

import pytest

from main import download_attachments
from models import File


def make_fake_download(size: int = 256):
    """Return a download_file side effect that writes `size` real bytes to dest_path."""
    def _download(url, dest_path):
        with open(dest_path, "wb") as f:
            f.write(b"x" * size)
    return _download


@pytest.fixture
def mock_slack():
    return MagicMock()


@pytest.fixture
def attachments_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("main.ATTACHMENTS_DIR", str(tmp_path))
    return tmp_path


class TestDownloadAttachments:
    """Test the download_attachments pipeline step."""

    def test_downloads_pending_file(self, db_conn, mock_slack, attachments_dir):
        """Pending file is downloaded and db updated with local_path and size_bytes."""
        from db import insert_file, iter_downloaded_files
        insert_file(db_conn, File(id="F1", message_ts="100", url="https://files.slack.com/F1"))

        mock_slack.download_file.side_effect = make_fake_download(2048)

        download_attachments(mock_slack, db_conn)

        dest = str(attachments_dir / "F1")
        mock_slack.download_file.assert_called_once_with("https://files.slack.com/F1", dest)

        downloaded = list(iter_downloaded_files(db_conn))
        assert len(downloaded) == 1
        assert downloaded[0].id == "F1"
        assert downloaded[0].local_path == dest
        assert downloaded[0].size_bytes == 2048

    def test_skips_already_downloaded_valid_file(self, db_conn, mock_slack, attachments_dir):
        """File with matching size on disk is not re-downloaded."""
        from db import insert_file

        dest = str(attachments_dir / "F1")
        with open(dest, "wb") as fh:
            fh.write(b"x" * 512)

        insert_file(db_conn, File(id="F1", message_ts="100", url="https://files.slack.com/F1",
                                  local_path=dest, size_bytes=512))

        download_attachments(mock_slack, db_conn)

        mock_slack.download_file.assert_not_called()

    def test_requeues_missing_file(self, db_conn, mock_slack, attachments_dir):
        """File with local_path set but missing from disk is re-downloaded."""
        from db import insert_file

        dest = str(attachments_dir / "F1")
        # No file on disk — DB thinks it was already downloaded
        insert_file(db_conn, File(id="F1", message_ts="100", url="https://files.slack.com/F1",
                                  local_path=dest, size_bytes=512))

        mock_slack.download_file.side_effect = make_fake_download(512)

        download_attachments(mock_slack, db_conn)

        mock_slack.download_file.assert_called_once()

    def test_requeues_size_mismatch_file(self, db_conn, mock_slack, attachments_dir):
        """File on disk with wrong size is re-downloaded."""
        from db import insert_file

        dest = str(attachments_dir / "F1")
        with open(dest, "wb") as fh:
            fh.write(b"x" * 100)  # 100 bytes on disk, but DB says 512

        insert_file(db_conn, File(id="F1", message_ts="100", url="https://files.slack.com/F1",
                                  local_path=dest, size_bytes=512))

        mock_slack.download_file.side_effect = make_fake_download(512)

        download_attachments(mock_slack, db_conn)

        mock_slack.download_file.assert_called_once()

    def test_continues_on_download_failure(self, db_conn, mock_slack, attachments_dir):
        """A failing download does not prevent subsequent files from downloading."""
        from db import insert_file
        insert_file(db_conn, File(id="F1", message_ts="100", url="https://files.slack.com/F1"))
        insert_file(db_conn, File(id="F2", message_ts="100", url="https://files.slack.com/F2"))

        responses = [Exception("403 Forbidden"), 256]

        def side_effect(url, dest_path):
            r = responses.pop(0)
            if isinstance(r, Exception):
                raise r
            with open(dest_path, "wb") as f:
                f.write(b"x" * r)

        mock_slack.download_file.side_effect = side_effect

        download_attachments(mock_slack, db_conn)

        assert mock_slack.download_file.call_count == 2

    def test_notifies_on_failures(self, db_conn, mock_slack, attachments_dir):
        """A notification is sent when at least one download fails."""
        from db import insert_file
        insert_file(db_conn, File(id="F1", message_ts="100", url="https://files.slack.com/F1"))

        mock_slack.download_file.side_effect = Exception("timeout")

        with patch("main.notifier") as mock_notifier:
            download_attachments(mock_slack, db_conn)

        mock_notifier.notify.assert_called_once()
        args = mock_notifier.notify.call_args[0]
        assert "failure" in args[0].lower() or "failed" in args[1].lower()

    def test_no_notification_on_clean_run(self, db_conn, mock_slack, attachments_dir):
        """No notification is sent when all downloads succeed."""
        from db import insert_file
        insert_file(db_conn, File(id="F1", message_ts="100", url="https://files.slack.com/F1"))

        mock_slack.download_file.side_effect = make_fake_download(128)

        with patch("main.notifier") as mock_notifier:
            download_attachments(mock_slack, db_conn)

        mock_notifier.notify.assert_not_called()

    def test_failed_download_not_recorded_in_db(self, db_conn, mock_slack, attachments_dir):
        """A failed download leaves local_path as NULL in the database."""
        from db import insert_file, iter_pending_files
        insert_file(db_conn, File(id="F1", message_ts="100", url="https://files.slack.com/F1"))

        mock_slack.download_file.side_effect = Exception("network error")

        download_attachments(mock_slack, db_conn)

        pending = list(iter_pending_files(db_conn))
        assert len(pending) == 1
        assert pending[0].id == "F1"
