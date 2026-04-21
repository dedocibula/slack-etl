# Project
Slack Ephemeral Data Exporter: Automated ETL pipeline to extract and persist Slack workspace data to local disk.

## Tech Stack
- Python (managed strictly via `uv`. Run scripts via `uv run`. Add dependencies via `uv add`.)
- `slack-sdk` (Official Python library)
- `sqlite3` (Python standard library, no ORMs)
- macOS `launchd` (for execution scheduling)

## Conventions
- Commit often using Conventional Commits (feat:, fix:, refactor:)

## Rules
- Do NOT commit without showing me the diff first
- If a task is complex, plan before implementing
- Respect existing file structure and formatting
- Do not guess Slack SDK methods. Write a quick throwaway script to test the API response shape first.
- Never swallow HTTP 429s. Catch `slack_sdk.errors.SlackApiError`, check `e.response["headers"]["Retry-After"]`, and implement `time.sleep()`.
- SQL writes must be transaction-safe. Commit only after a successful pagination block is processed to prevent data corruption.
- macOS UI Notifications must use `subprocess.run(['osascript', '-e', 'display notification...'])`.
- `launchd` `.plist` files must use `StartCalendarInterval` for reliable scheduling across sleep cycles.

## Before building anything, answer:
- What happens if this crashes halfway through? (Hint: rely on SQLite `sync_state` table)
- What external identifiers (models, APIs, versions) might I hardcode?
- What are the system dependencies and how do I verify them at startup?

## Verification
- (add test/build commands as project evolves)