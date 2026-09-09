# Changelog

What someone already running contexts should know, newest first. Grouped by
date; under each date, anything needing action comes before new features. See
git history for the full list of fixes and smaller changes.

## 2026-09-09

### Action required

- New migration, and a full reindex (`d825996`): conversations now come from
  pluggable harness adapters.
  - **Breaks:** the server refuses to start with unapplied migrations. The index
    cache key changed, so every conversation is reparsed once.
  - **Cope:** `make migrate && make reindex` (`-<name>` per extra instance).
- Cost is now attributed per conversation, excluding subagents (`d825996`).
  - **Breaks:** totals on the stats screen drop slightly. They previously counted
    Claude subagent spend twice, once in the subagent and once in its parent.
  - **Cope:** nothing; the new numbers are the correct ones. A single
    conversation still shows the with-subagents rollup in its header.

### New features

- Conversations from other agents, opencode first (`d825996`). Set
  `HARNESSES = ["claude", "opencode"]` in `settings_local.py` to mix them into one
  list, still grouped by directory and sorted by date. **Optional:** opencode's
  database at `~/.local/share/opencode/opencode.db` (`OPENCODE_DB`), read-only,
  safe to read while opencode is running; absent means the harness is skipped.
- Subagents are listed as well as nested (`d825996`): they appear under their parent
  in the sidebar and can be opened on their own.

## 2026-09-08

### New features

- The viewer works with the terminal you actually have (`f4978da`). With
  `$TERMINAL` unset it now searches the known terminals on `PATH` — Ptyxis,
  ghostty, kitty, foot, GNOME Terminal, konsole, urxvt, xterm and friends —
  instead of only `rxvt-unicode` then `xterm`, and launches each with the flag
  it wants rather than assuming `-e`. A wrong flag meant a viewer window that
  never opened. Pin a specific one with `$TERMINAL` or `TERMINAL_CMD`.

## 2026-09-01

### New features

- Cron runs pair to their conversation in the background (`3f13aae`): the link
  now appears while a run is live and survives an app restart, instead of only
  resolving while the cronjob detail page was open.

## 2026-08-31

### New features

- Download any rendered diagram as SVG or PNG from the block toolbar
  (`0e5d122`, `a254b3f`).

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
