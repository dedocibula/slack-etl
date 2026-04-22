import pytest
from unittest.mock import Mock, patch
from slack_sdk.errors import SlackApiError

from models import Channel, File, Message, User
from slack_client import SlackClient


@pytest.fixture
def mock_webclient():
    """Mock WebClient for testing."""
    with patch("slack_client.WebClient") as mock_wc:
        yield mock_wc.return_value


class TestCallWithRetry:
    """Test rate-limit retry logic."""

    def test_call_with_retry_success(self, mock_webclient):
        """_call_with_retry returns on first success."""
        mock_fn = Mock(return_value={"ok": True})

        client = SlackClient("test-token")
        result = client._call_with_retry(mock_fn, param1="value")

        assert result == {"ok": True}
        mock_fn.assert_called_once_with(param1="value")

    def test_call_with_retry_propagates_non_429_error(self, mock_webclient):
        """_call_with_retry re-raises non-429 errors immediately."""
        error_resp = {"error": "invalid_token"}
        mock_fn = Mock(side_effect=SlackApiError(message="Invalid token", response=error_resp))

        client = SlackClient("test-token")

        with pytest.raises(SlackApiError) as exc_info:
            client._call_with_retry(mock_fn)

        assert "invalid_token" in str(exc_info.value)
        assert mock_fn.call_count == 1

    def test_call_with_retry_sleeps_on_429(self, mock_webclient):
        """_call_with_retry sleeps on rate limit and retries."""
        error_resp = {"error": "ratelimited", "headers": {"Retry-After": "1"}}
        mock_fn = Mock(
            side_effect=[
                SlackApiError(message="Rate limited", response=error_resp),
                {"ok": True}
            ]
        )

        client = SlackClient("test-token")

        with patch("slack_client.time.sleep") as mock_sleep:
            result = client._call_with_retry(mock_fn)

        assert result == {"ok": True}
        mock_sleep.assert_called_once_with(1)
        assert mock_fn.call_count == 2

    def test_call_with_retry_max_retries_exhausted(self, mock_webclient):
        """_call_with_retry raises after exhausting retries."""
        error_resp = {"error": "ratelimited", "headers": {"Retry-After": "0"}}
        mock_fn = Mock(
            side_effect=SlackApiError(message="Rate limited", response=error_resp)
        )

        client = SlackClient("test-token")

        with patch("slack_client.time.sleep"):
            with pytest.raises(SlackApiError) as exc_info:
                client._call_with_retry(mock_fn)

        assert "Max retries" in str(exc_info.value)
        assert mock_fn.call_count == 10  # MAX_RETRIES = 10

    def test_call_with_retry_default_retry_after(self, mock_webclient):
        """_call_with_retry defaults to 1 second if Retry-After missing."""
        error_resp = {"error": "ratelimited"}
        mock_fn = Mock(
            side_effect=[
                SlackApiError(message="Rate limited", response=error_resp),
                {"ok": True}
            ]
        )

        client = SlackClient("test-token")

        with patch("slack_client.time.sleep") as mock_sleep:
            client._call_with_retry(mock_fn)

        mock_sleep.assert_called_once_with(1)


class TestIterUsers:
    """Test user iteration."""

    def test_iter_users_yields_user_dataclasses(self, mock_webclient):
        """iter_users yields User dataclass instances."""
        mock_webclient.users_list.return_value = {
            "members": [
                {"id": "U123", "name": "john", "real_name": "John Doe", "deleted": False, "is_bot": False},
            ],
            "response_metadata": {"next_cursor": ""}
        }

        client = SlackClient("test-token")
        users = list(client.iter_users())

        assert len(users) == 1
        assert isinstance(users[0], User)
        assert users[0].id == "U123"
        assert users[0].name == "john"
        assert users[0].real_name == "John Doe"

    def test_iter_users_skips_deleted(self, mock_webclient):
        """iter_users filters deleted users."""
        mock_webclient.users_list.return_value = {
            "members": [
                {"id": "U123", "name": "john", "deleted": False, "is_bot": False},
                {"id": "U456", "name": "deleted-user", "deleted": True, "is_bot": False},
                {"id": "U789", "name": "jane", "deleted": False, "is_bot": False},
            ],
            "response_metadata": {"next_cursor": ""}
        }

        client = SlackClient("test-token")
        users = list(client.iter_users())

        assert len(users) == 2
        assert all(u.id != "U456" for u in users)

    def test_iter_users_skips_bots(self, mock_webclient):
        """iter_users filters bot users."""
        mock_webclient.users_list.return_value = {
            "members": [
                {"id": "U123", "name": "john", "deleted": False, "is_bot": False},
                {"id": "B456", "name": "bot-user", "deleted": False, "is_bot": True},
                {"id": "U789", "name": "jane", "deleted": False, "is_bot": False},
            ],
            "response_metadata": {"next_cursor": ""}
        }

        client = SlackClient("test-token")
        users = list(client.iter_users())

        assert len(users) == 2
        assert all(u.id != "B456" for u in users)

    def test_iter_users_pagination(self, mock_webclient):
        """iter_users handles pagination."""
        mock_webclient.users_list.side_effect = [
            {
                "members": [{"id": "U1", "name": "u1", "deleted": False, "is_bot": False}],
                "response_metadata": {"next_cursor": "cursor123"}
            },
            {
                "members": [{"id": "U2", "name": "u2", "deleted": False, "is_bot": False}],
                "response_metadata": {"next_cursor": ""}
            }
        ]

        client = SlackClient("test-token")
        users = list(client.iter_users())

        assert len(users) == 2
        assert users[0].id == "U1"
        assert users[1].id == "U2"
        assert mock_webclient.users_list.call_count == 2


class TestIterChannels:
    """Test channel iteration."""

    def test_iter_channels_yields_channel_dataclasses(self, mock_webclient):
        """iter_channels yields Channel dataclass instances."""
        mock_webclient.conversations_list.return_value = {
            "channels": [
                {"id": "C123", "name": "general", "is_private": False},
                {"id": "C456", "name": "random", "is_private": False},
            ],
            "response_metadata": {"next_cursor": ""}
        }

        client = SlackClient("test-token")
        channels = list(client.iter_channels())

        assert len(channels) == 2
        assert isinstance(channels[0], Channel)
        assert channels[0].id == "C123"
        assert channels[0].name == "general"
        assert channels[0].is_private is False

    def test_iter_channels_requests_exclude_archived(self, mock_webclient):
        """iter_channels requests exclude_archived=True."""
        mock_webclient.conversations_list.return_value = {
            "channels": [],
            "response_metadata": {"next_cursor": ""}
        }

        client = SlackClient("test-token")
        list(client.iter_channels())

        call_kwargs = mock_webclient.conversations_list.call_args[1]
        assert call_kwargs["exclude_archived"] is True

    def test_iter_channels_includes_private(self, mock_webclient):
        """iter_channels includes private channels."""
        mock_webclient.conversations_list.return_value = {
            "channels": [
                {"id": "C123", "name": "general", "is_private": False},
                {"id": "C456", "name": "secret", "is_private": True},
            ],
            "response_metadata": {"next_cursor": ""}
        }

        client = SlackClient("test-token")
        channels = list(client.iter_channels())

        assert len(channels) == 2
        assert any(c.is_private is False for c in channels)
        assert any(c.is_private is True for c in channels)

    def test_iter_channels_requests_correct_types(self, mock_webclient):
        """iter_channels requests public_channel,private_channel."""
        mock_webclient.conversations_list.return_value = {
            "channels": [],
            "response_metadata": {"next_cursor": ""}
        }

        client = SlackClient("test-token")
        list(client.iter_channels())

        call_kwargs = mock_webclient.conversations_list.call_args[1]
        assert call_kwargs["types"] == "public_channel,private_channel"


class TestIterHistory:
    """Test message history iteration."""

    def test_iter_history_yields_message_dataclasses(self, mock_webclient):
        """iter_history yields Message dataclass instances."""
        mock_webclient.conversations_history.return_value = {
            "messages": [
                {"ts": "100", "user": "U1", "text": "Hello", "files": []},
            ],
            "response_metadata": {"next_cursor": ""}
        }

        client = SlackClient("test-token")
        messages = list(client.iter_history("C123"))

        assert len(messages) == 1
        assert isinstance(messages[0], Message)
        assert messages[0].ts == "100"
        assert messages[0].text == "Hello"

    def test_iter_history_reverses_message_order(self, mock_webclient):
        """iter_history reverses API's newest-first order."""
        mock_webclient.conversations_history.return_value = {
            "messages": [
                {"ts": "300", "user": "U1", "text": "Latest"},
                {"ts": "200", "user": "U1", "text": "Middle"},
                {"ts": "100", "user": "U1", "text": "Oldest"},
            ],
            "response_metadata": {"next_cursor": ""}
        }

        client = SlackClient("test-token")
        messages = list(client.iter_history("C123"))

        assert messages[0].ts == "100"
        assert messages[1].ts == "200"
        assert messages[2].ts == "300"

    def test_iter_history_passes_oldest_parameter(self, mock_webclient):
        """iter_history passes oldest as exclusive lower bound."""
        mock_webclient.conversations_history.return_value = {
            "messages": [],
            "response_metadata": {"next_cursor": ""}
        }

        client = SlackClient("test-token")
        list(client.iter_history("C123", oldest="1234567890.000100"))

        call_kwargs = mock_webclient.conversations_history.call_args[1]
        assert call_kwargs["oldest"] == "1234567890.000100"

    def test_iter_history_pagination(self, mock_webclient):
        """iter_history handles pagination."""
        mock_webclient.conversations_history.side_effect = [
            {
                "messages": [{"ts": "100", "user": "U1", "text": "Page 1"}],
                "response_metadata": {"next_cursor": "cursor123"}
            },
            {
                "messages": [{"ts": "50", "user": "U1", "text": "Page 2"}],
                "response_metadata": {"next_cursor": ""}
            }
        ]

        client = SlackClient("test-token")
        messages = list(client.iter_history("C123"))

        assert len(messages) == 2
        assert mock_webclient.conversations_history.call_count == 2

    def test_iter_history_parses_files_into_dataclasses(self, mock_webclient):
        """iter_history yields File dataclasses nested in Message."""
        mock_webclient.conversations_history.return_value = {
            "messages": [
                {
                    "ts": "100",
                    "user": "U1",
                    "text": "With file",
                    "files": [{"id": "F123", "url_private_download": "https://..."}]
                }
            ],
            "response_metadata": {"next_cursor": ""}
        }

        client = SlackClient("test-token")
        messages = list(client.iter_history("C123"))

        assert len(messages[0].files) == 1
        assert isinstance(messages[0].files[0], File)
        assert messages[0].files[0].id == "F123"
        assert messages[0].files[0].message_ts == "100"
        assert messages[0].files[0].url == "https://..."

    def test_iter_history_with_thread_ts(self, mock_webclient):
        """iter_history yields thread_ts for replies."""
        mock_webclient.conversations_history.return_value = {
            "messages": [
                {"ts": "200", "user": "U1", "text": "Reply", "thread_ts": "100"}
            ],
            "response_metadata": {"next_cursor": ""}
        }

        client = SlackClient("test-token")
        messages = list(client.iter_history("C123"))

        assert messages[0].thread_ts == "100"


class TestIterReplies:
    """Test thread reply iteration."""

    def test_iter_replies_yields_message_dataclasses(self, mock_webclient):
        """iter_replies yields Message dataclass instances."""
        mock_webclient.conversations_replies.return_value = {
            "messages": [
                {"ts": "100", "user": "U1", "text": "Parent"},
                {"ts": "110", "user": "U2", "text": "Reply 1"},
            ],
            "response_metadata": {"next_cursor": ""}
        }

        client = SlackClient("test-token")
        replies = list(client.iter_replies("C123", "100"))

        assert len(replies) == 1
        assert isinstance(replies[0], Message)
        assert replies[0].ts == "110"

    def test_iter_replies_skips_parent_first_page_only(self, mock_webclient):
        """iter_replies skips parent only on first page."""
        mock_webclient.conversations_replies.side_effect = [
            {
                "messages": [
                    {"ts": "100", "user": "U1", "text": "Parent"},
                    {"ts": "110", "user": "U2", "text": "Reply 1"},
                ],
                "response_metadata": {"next_cursor": "cursor123"}
            },
            {
                "messages": [
                    {"ts": "120", "user": "U3", "text": "Reply 2"},
                    {"ts": "130", "user": "U4", "text": "Reply 3"},
                ],
                "response_metadata": {"next_cursor": ""}
            }
        ]

        client = SlackClient("test-token")
        replies = list(client.iter_replies("C123", "100"))

        assert len(replies) == 3
        assert replies[0].ts == "110"
        assert replies[1].ts == "120"
        assert replies[2].ts == "130"

    def test_iter_replies_passes_thread_ts(self, mock_webclient):
        """iter_replies passes thread_ts to API."""
        mock_webclient.conversations_replies.return_value = {
            "messages": [{"ts": "100", "user": "U1", "text": "Parent"}],
            "response_metadata": {"next_cursor": ""}
        }

        client = SlackClient("test-token")
        list(client.iter_replies("C123", "100"))

        call_kwargs = mock_webclient.conversations_replies.call_args[1]
        assert call_kwargs["ts"] == "100"


class TestDownloadFile:
    """Test file download."""

    def test_download_file_streams_to_path(self, mock_webclient):
        """download_file streams content to destination."""
        mock_response = Mock()
        mock_response.iter_content.return_value = [b"chunk1", b"chunk2"]

        with patch("slack_client.requests.get") as mock_get:
            mock_get.return_value = mock_response

            client = SlackClient("test-token")
            with patch("builtins.open", create=True) as mock_open:
                mock_file = Mock()
                mock_open.return_value.__enter__.return_value = mock_file

                client.download_file("https://files.slack.com/...", "/tmp/file.txt")

                mock_file.write.assert_any_call(b"chunk1")
                mock_file.write.assert_any_call(b"chunk2")

    def test_download_file_uses_authorization_header(self, mock_webclient):
        """download_file includes Bearer token in Authorization header."""
        mock_response = Mock()
        mock_response.iter_content.return_value = []

        with patch("slack_client.requests.get") as mock_get:
            mock_get.return_value = mock_response

            client = SlackClient("test-token")
            with patch("builtins.open", create=True):
                client.download_file("https://files.slack.com/...", "/tmp/file.txt")

                call_kwargs = mock_get.call_args[1]
                assert call_kwargs["headers"]["Authorization"] == "Bearer test-token"

    def test_download_file_raises_on_http_error(self, mock_webclient):
        """download_file raises on HTTP error."""
        mock_response = Mock()
        mock_response.raise_for_status.side_effect = Exception("404 Not Found")

        with patch("slack_client.requests.get") as mock_get:
            mock_get.return_value = mock_response

            client = SlackClient("test-token")
            with pytest.raises(Exception):
                client.download_file("https://files.slack.com/...", "/tmp/file.txt")


class TestSlackClientInit:
    """Test SlackClient initialization."""

    def test_init_stores_token(self, mock_webclient):
        """SlackClient stores token for file downloads."""
        client = SlackClient("test-token")
        assert client._token == "test-token"

    def test_init_creates_logger(self, mock_webclient):
        """SlackClient creates logger."""
        client = SlackClient("test-token")
        assert client._logger is not None
