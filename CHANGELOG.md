# Changelog

What someone already running contexts should know, newest first. Breaking
changes and anything needing action come first; notable new features follow.
See git history for the full list of fixes and smaller changes.

## Action required

Breaking changes, new/changed dependencies, changed config defaults, and
required migrations.

### 2026-08-22 - new database migrations (`0f3b803`, `4d6d2a0`)

Per-conversation cost estimation and cron/session pairing added new columns.

- **Breaks:** the server refuses to start with unapplied migrations.
- **Cope:** run `make migrate` after pulling (`make migrate-<name>` per extra
  instance).

### 2026-08-21 - tmux is now the default session substrate (`c67ddb5`, `774a859`)

New optional dependency. Sessions launch inside a headless tmux session so they
can be named, reused, and paired to conversations.

- **Breaks:** nothing if tmux is missing - it falls back to launching a terminal
  directly, but you lose session reuse and reliable conversation pairing. With
  tmux on, Shift+Enter stops inserting newlines until tmux passes modified keys.
- **Cope:** install tmux (`brew install tmux` on macOS) for the full experience.
  For Shift+Enter, enable `extended-keys` in `~/.tmux.conf` (see README).

### 2026-07-24 - default ports changed to 8062/8063 (`f405400`)

- **Breaks:** the app no longer serves on 8042/8043; old bookmarks and scripts
  pointing there fail.
- **Cope:** use http://localhost:8062 (default) or 8063 (second instance).
  Override with `PORT=8042 make run` to keep the old port.

## New features

- **2026-08-24 (`871463d`)** - live session controls in the conversation view:
  queue a prompt, answer tool/permission prompts inline, open an attached
  terminal, and see live idle/busy/waiting status.
- **2026-08-22 (`a451e61`)** - cronjobs run headless in tmux, paired to a
  conversation, with a notification to open the live terminal.
- **2026-08-20 (`0f3b803`)** - per-conversation cost estimation and a Costs tab,
  derived from transcript token usage.
- **2026-08-20 (`32a828f`)** - Activity & Costs time range picker.
- **2026-07-24 (`842e4ba`)** - configurable `claude` binary via the `CLAUDE_CMD`
  setting.
- **2026-07-16 (`9a0aed0`)** - multi-instance support via `CONTEXTS_INSTANCE`
  (separate DB and settings per instance).
- **2026-07-16 (`a152418`)** - inline image previews for Read actions.
