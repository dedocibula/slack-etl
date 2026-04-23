# Slack ETL

Automated ETL pipeline that extracts your Slack workspace history and renders it as readable Markdown files on your local machine. Runs daily via macOS `launchd`, keeping a permanent archive of messages that Slack's free tier would eventually delete.

## How it works

The pipeline runs three stages on each execution:

```
Slack API → extract → SQLite DB → download_attachments → _attachments/ → export_markdown → data/
```

1. **Extract** — fetches all channels, users, and messages (with thread replies) from the Slack API into a local SQLite database. Incremental: only fetches messages newer than the last successful run.
2. **Download attachments** — downloads every file attachment to `_attachments/<file-id>`. Verifies already-downloaded files by size; re-queues any that are missing or truncated.
3. **Export** — renders every channel's messages into per-month Markdown files under `data/<channel-name>/YYYY-MM.md`. Regenerates all months on every run so the archive is always consistent with the database.

All three stages are crash-safe: a failed run leaves the database intact and the next run resumes where it left off.

## Data structure

By default, all output is written relative to the project directory. Set `SLACK_ETL_DATA_ROOT` (see Configuration) to store data separately from the code.

```
<data-root>/
├── database.sqlite          # SQLite database (all messages, users, channels, files)
├── _attachments/            # Downloaded file attachments, keyed by Slack file ID
│   ├── F123ABC              # raw file bytes (original filename recorded in DB)
│   └── ...
└── data/
    ├── general/
    │   ├── 2026-03.md
    │   └── 2026-04.md
    ├── engineering/
    │   └── 2026-04.md
    └── ...
```

### Markdown format

Each `.md` file contains one calendar month of messages for one channel:

```markdown
# #general - April 2026

**[2026-04-15 09:00:00] <@alice>:** hello <@bob> how are you?
![report.pdf](../../_attachments/F123ABC)

**[2026-04-15 09:05:00] <@bob>:** great thanks, see this thread
> **[2026-04-15 09:06:00] <@alice>:** > nice work!
>
> **[2026-04-15 09:07:00] <@bob>:** > agreed
```

- Author names and inline `<@mentions>` are resolved to display names.
- Thread replies are blockquoted under their parent message.
- Downloaded attachments are rendered as relative image/file links.

### Database schema

| Table | Purpose |
|---|---|
| `channels` | Channel metadata (id, name, is_private) |
| `users` | User metadata (id, name, real_name) |
| `messages` | All messages and replies (ts, channel_id, user_id, text, thread_ts) |
| `files` | File attachment records (id, message_ts, url, local_path, size_bytes) |
| `sync_state` | Last successfully fetched timestamp per channel (crash recovery) |

## Installation

### Prerequisites

- Python 3.12+ managed via [uv](https://docs.astral.sh/uv/)
- A Slack user token (`xoxp-...`) with the following OAuth scopes:
  - `channels:history`, `channels:read`
  - `groups:history`, `groups:read` (private channels)
  - `users:read`
  - `files:read`

### Setup

1. **Clone the repo and install dependencies:**
   ```bash
   git clone <repo-url>
   cd slack-etl
   uv sync
   ```

2. **Add your credentials to `~/.env`:**
   ```
   SLACK_USER_TOKEN=xoxp-your-token-here
   ```

3. **Optionally set a data root** (to keep data separate from code):
   ```
   SLACK_ETL_DATA_ROOT=/path/to/your/data-directory
   ```
   The directory will be created automatically on first run.

4. **Run the pipeline once to verify:**
   ```bash
   make run-now
   ```

### Schedule with launchd (daily at 3 AM)

```bash
# Generate and install the .plist
make gen-plist > ~/Library/LaunchAgents/com.slack-etl.daily.plist
launchctl load ~/Library/LaunchAgents/com.slack-etl.daily.plist
```

macOS launchd catches up on missed runs when the machine wakes from sleep, so a 3 AM job that fires at 9 AM is normal and expected.

## Configuration

All configuration is read from `~/.env` (key=value format):

| Variable | Required | Description |
|---|---|---|
| `SLACK_USER_TOKEN` | Yes | Slack user token (`xoxp-...`) |
| `SLACK_ETL_DATA_ROOT` | No | Absolute path for database, attachments, and exported data. Defaults to the project directory. |

## Makefile targets

| Target | Description |
|---|---|
| `make run-now` | Run the full pipeline immediately |
| `make status` | Show launchd job status and last 20 log lines |
| `make logs` | Tail the live log file |
| `make pause` | Unload the launchd job (stop scheduling) |
| `make resume` | Load the launchd job (resume scheduling) |
| `make gen-plist` | Print the `.plist` to stdout |
| `make clean` | Remove generated `.md` files and log files |

## Development

```bash
# Run the test suite
uv run pytest tests/ -q

# Run a specific test file
uv run pytest tests/test_e2e.py -v
```

Tests use an in-memory SQLite database and a real temporary filesystem — no network calls and no dependency on `SLACK_ETL_DATA_ROOT`.
