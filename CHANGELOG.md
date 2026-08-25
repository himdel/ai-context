# Changelog

What someone already running contexts should know, newest first. Grouped by
date; under each date, anything needing action comes before new features. See
git history for the full list of fixes and smaller changes.

## 2026-08-24

### New features

- Live session controls in the conversation view (`871463d`): queue a prompt,
  answer tool/permission prompts inline, open an attached terminal, and see live
  idle/busy/waiting status.

## 2026-08-22

### Action required

- New migration (`4d6d2a0`): cron/session pairing added a column.
  - **Breaks:** the server refuses to start with unapplied migrations.
  - **Cope:** run `make migrate` (`make migrate-<name>` per extra instance).

### New features

- Cronjobs run headless in tmux, paired to a conversation, with a notification
  to open the live terminal (`a451e61`).

## 2026-08-21

### Action required

- tmux is now the default session substrate (`c67ddb5`, `774a859`). New optional
  dependency; sessions launch inside a headless tmux session so they can be
  named, reused, and paired to conversations.
  - **Breaks:** nothing if tmux is missing - it falls back to launching a
    terminal directly, but you lose session reuse and reliable pairing. With
    tmux on, Shift+Enter stops inserting newlines until tmux passes modified
    keys.
  - **Cope:** install tmux (`brew install tmux` on macOS). For Shift+Enter,
    enable `extended-keys` in `~/.tmux.conf` (see README).

## 2026-08-20

### Action required

- New migration (`0f3b803`): per-conversation cost estimation added token
  columns.
  - **Breaks:** the server refuses to start with unapplied migrations.
  - **Cope:** run `make migrate` (`make migrate-<name>` per extra instance).

### New features

- Per-conversation cost estimation and a Costs tab, derived from transcript
  token usage (`0f3b803`).
- Activity & Costs time range picker (`32a828f`).

## 2026-07-24

### Action required

- Default ports changed to 8062/8063 (`f405400`).
  - **Breaks:** the app no longer serves on 8042/8043; old bookmarks and scripts
    pointing there fail.
  - **Cope:** use http://localhost:8062 (default) or 8063 (second instance).
    Override with `PORT=8042 make run` to keep the old port.

### New features

- Configurable `claude` binary via the `CLAUDE_CMD` setting (`842e4ba`).

## 2026-07-16

### New features

- Multi-instance support via `CONTEXTS_INSTANCE`, with a separate DB and settings
  per instance (`9a0aed0`).
- Inline image previews for Read actions (`a152418`).
