import logging
import time
from typing import Iterator, Optional

import requests
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

# ============================================================================
# Constants
# ============================================================================

PAGE_SIZE = 200          # items per paginated request
MAX_RETRIES = 10         # max attempts per call before giving up
DOWNLOAD_CHUNK = 8192    # bytes per chunk when streaming files


# ============================================================================
# SlackClient
# ============================================================================


class SlackClient:
    """Wrapper around slack_sdk WebClient with rate-limit handling and pagination."""

    def __init__(self, token: str) -> None:
        """Initialize with Slack user token."""
        self._client = WebClient(token=token)
        self._token = token  # needed for raw HTTP file downloads
        self._logger = logging.getLogger(__name__)

    def _call_with_retry(self, fn, **kwargs):
        """
        Call fn(**kwargs), automatically sleeping on 429s.
        Raises SlackApiError if max retries exhausted or other error occurs.
        """
        for attempt in range(MAX_RETRIES):
            try:
                return fn(**kwargs)
            except SlackApiError as e:
                if e.response.get("error") == "ratelimited":
                    wait = int(e.response.get("headers", {}).get("Retry-After", 1))
                    self._logger.warning(
                        "Rate limited; sleeping %ds (attempt %d/%d)",
                        wait, attempt + 1, MAX_RETRIES
                    )
                    time.sleep(wait)
                else:
                    # Non-429 errors propagate immediately
                    raise

        # Exhausted retries
        raise SlackApiError(f"Max retries ({MAX_RETRIES}) exhausted for rate-limited endpoint")

    def iter_users(self) -> Iterator[dict]:
        """
        Yield every user (non-deleted, non-bot).
        Yields dicts with: id, name, real_name
        """
        cursor = None
        while True:
            resp = self._call_with_retry(
                self._client.users_list,
                cursor=cursor,
                limit=PAGE_SIZE
            )
            for member in resp.get("members", []):
                # Skip deleted or bot accounts
                if member.get("deleted") or member.get("is_bot"):
                    continue
                yield {
                    "id": member.get("id"),
                    "name": member.get("name"),
                    "real_name": member.get("real_name"),
                }

            cursor = resp.get("response_metadata", {}).get("next_cursor")
            if not cursor:
                break

    def iter_channels(self) -> Iterator[dict]:
        """
        Yield every channel (non-archived, public + private).
        Yields dicts with: id, name, is_private
        """
        cursor = None
        while True:
            resp = self._call_with_retry(
                self._client.conversations_list,
                cursor=cursor,
                limit=PAGE_SIZE,
                types="public_channel,private_channel",
                exclude_archived=True
            )
            for ch in resp.get("channels", []):
                yield {
                    "id": ch.get("id"),
                    "name": ch.get("name"),
                    "is_private": ch.get("is_private"),
                }

            cursor = resp.get("response_metadata", {}).get("next_cursor")
            if not cursor:
                break

    def iter_history(self, channel_id: str, oldest: Optional[str] = None) -> Iterator[dict]:
        """
        Yield messages from a channel (newest to oldest, then reverse to yield oldest first).
        oldest is an exclusive lower bound (pass last_fetched_ts from sync_state).

        Yields dicts with: ts, user, text, thread_ts, files
        """
        cursor = None
        while True:
            resp = self._call_with_retry(
                self._client.conversations_history,
                channel=channel_id,
                cursor=cursor,
                limit=PAGE_SIZE,
                oldest=oldest
            )
            # conversations.history returns newest-first; collect and reverse for chronological order
            messages = resp.get("messages", [])
            for msg in reversed(messages):
                yield {
                    "ts": msg.get("ts"),
                    "user": msg.get("user"),
                    "text": msg.get("text"),
                    "thread_ts": msg.get("thread_ts"),
                    "files": msg.get("files", []),
                }

            cursor = resp.get("response_metadata", {}).get("next_cursor")
            if not cursor:
                break

    def iter_replies(self, channel_id: str, thread_ts: str) -> Iterator[dict]:
        """
        Yield reply messages in a thread (skips parent at index 0).
        Yields dicts with: ts, user, text, thread_ts, files
        """
        cursor = None
        first_page = True
        while True:
            resp = self._call_with_retry(
                self._client.conversations_replies,
                channel=channel_id,
                ts=thread_ts,
                cursor=cursor,
                limit=PAGE_SIZE
            )
            messages = resp.get("messages", [])

            # Skip parent (index 0) on first page only
            start_idx = 1 if first_page else 0
            for msg in messages[start_idx:]:
                yield {
                    "ts": msg.get("ts"),
                    "user": msg.get("user"),
                    "text": msg.get("text"),
                    "thread_ts": msg.get("thread_ts"),
                    "files": msg.get("files", []),
                }

            first_page = False
            cursor = resp.get("response_metadata", {}).get("next_cursor")
            if not cursor:
                break

    def download_file(self, url: str, dest_path: str) -> None:
        """
        Stream url_private_download to dest_path using Authorization header.
        Raises if HTTP request fails.
        """
        headers = {"Authorization": f"Bearer {self._token}"}
        try:
            resp = requests.get(url, headers=headers, stream=True, timeout=30)
            resp.raise_for_status()
            with open(dest_path, "wb") as f:
                for chunk in resp.iter_content(DOWNLOAD_CHUNK):
                    if chunk:
                        f.write(chunk)
            self._logger.debug("Downloaded file to %s", dest_path)
        except requests.RequestException as e:
            self._logger.error("Failed to download %s: %s", url, e)
            raise
