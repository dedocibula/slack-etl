import os
from unittest.mock import MagicMock, call, patch

import pytest

from main import download_attachments
from models import File


@pytest.fixture
def mock_slack():
    return MagicMock()


class TestDownloadAttachments:
    """Test the download_attachments pipeline step."""

    def test_downloads_pending_file(self, db_conn, mock_slack, tmp_path):
        """Pending file is downloaded and db updated with local_path and size_bytes."""
        from db import insert_file
        insert_file(db_conn, File(id="F1", message_ts="100", url="https://files.slack.com/F1"))

        dest = str(tmp_path / "F1")

        with patch("main.ATTACHMENTS_DIR", str(tmp_path)):
            with patch("os.path.getsize", return_value=2048):
                download_attachments(mock_slack, db_conn)

        mock_slack.download_file.assert_called_once_with("https://files.slack.com/F1", dest)

        from db import iter_downloaded_files
        downloaded = list(iter_downloaded_files(db_conn))
        assert len(downloaded) == 1
        assert downloaded[0].id == "F1"
        assert downloaded[0].local_path == dest
        assert downloaded[0].size_bytes == 2048

    def test_skips_already_downloaded_valid_file(self, db_conn, mock_slack, tmp_path):
        """File with matching size on disk is not re-downloaded."""
        from db import insert_file

        dest = str(tmp_path / "F1")
        # Create the file on disk
        with open(dest, "wb") as fh:
            fh.write(b"x" * 512)

        insert_file(db_conn, File(id="F1", message_ts="100", url="https://files.slack.com/F1",
                                  local_path=dest, size_bytes=512))

        with patch("main.ATTACHMENTS_DIR", str(tmp_path)):
            download_attachments(mock_slack, db_conn)

        mock_slack.download_file.assert_not_called()

    def test_requeues_missing_file(self, db_conn, mock_slack, tmp_path):
        """File with local_path set but missing from disk is re-downloaded."""
        from db import insert_file

        dest = str(tmp_path / "F1")
        # File is NOT on disk
        insert_file(db_conn, File(id="F1", message_ts="100", url="https://files.slack.com/F1",
                                  local_path=dest, size_bytes=512))

        with patch("main.ATTACHMENTS_DIR", str(tmp_path)):
            with patch("os.path.getsize", return_value=512):
                download_attachments(mock_slack, db_conn)

        mock_slack.download_file.assert_called_once()

    def test_requeues_size_mismatch_file(self, db_conn, mock_slack, tmp_path):
        """File on disk with wrong size is re-downloaded."""
        from db import insert_file

        dest = str(tmp_path / "F1")
        with open(dest, "wb") as fh:
            fh.write(b"x" * 100)  # 100 bytes on disk, but DB says 512

        insert_file(db_conn, File(id="F1", message_ts="100", url="https://files.slack.com/F1",
                                  local_path=dest, size_bytes=512))

        with patch("main.ATTACHMENTS_DIR", str(tmp_path)):
            with patch("os.path.getsize", return_value=100):
                download_attachments(mock_slack, db_conn)

        mock_slack.download_file.assert_called_once()

    def test_continues_on_download_failure(self, db_conn, mock_slack, tmp_path):
        """A failing download does not prevent subsequent files from downloading."""
        from db import insert_file
        insert_file(db_conn, File(id="F1", message_ts="100", url="https://files.slack.com/F1"))
        insert_file(db_conn, File(id="F2", message_ts="100", url="https://files.slack.com/F2"))

        mock_slack.download_file.side_effect = [Exception("403 Forbidden"), None]

        with patch("main.ATTACHMENTS_DIR", str(tmp_path)):
            with patch("os.path.getsize", return_value=256):
                download_attachments(mock_slack, db_conn)

        assert mock_slack.download_file.call_count == 2

    def test_notifies_on_failures(self, db_conn, mock_slack, tmp_path):
        """A notification is sent when at least one download fails."""
        from db import insert_file
        insert_file(db_conn, File(id="F1", message_ts="100", url="https://files.slack.com/F1"))

        mock_slack.download_file.side_effect = Exception("timeout")

        with patch("main.ATTACHMENTS_DIR", str(tmp_path)):
            with patch("main.notifier") as mock_notifier:
                download_attachments(mock_slack, db_conn)

        mock_notifier.notify.assert_called_once()
        args = mock_notifier.notify.call_args[0]
        assert "failure" in args[0].lower() or "failed" in args[1].lower()

    def test_no_notification_on_clean_run(self, db_conn, mock_slack, tmp_path):
        """No notification is sent when all downloads succeed."""
        from db import insert_file
        insert_file(db_conn, File(id="F1", message_ts="100", url="https://files.slack.com/F1"))

        with patch("main.ATTACHMENTS_DIR", str(tmp_path)):
            with patch("os.path.getsize", return_value=128):
                with patch("main.notifier") as mock_notifier:
                    download_attachments(mock_slack, db_conn)

        mock_notifier.notify.assert_not_called()

    def test_failed_download_not_recorded_in_db(self, db_conn, mock_slack, tmp_path):
        """A failed download leaves local_path as NULL in the database."""
        from db import insert_file, iter_pending_files
        insert_file(db_conn, File(id="F1", message_ts="100", url="https://files.slack.com/F1"))

        mock_slack.download_file.side_effect = Exception("network error")

        with patch("main.ATTACHMENTS_DIR", str(tmp_path)):
            download_attachments(mock_slack, db_conn)

        pending = list(iter_pending_files(db_conn))
        assert len(pending) == 1
        assert pending[0].id == "F1"
