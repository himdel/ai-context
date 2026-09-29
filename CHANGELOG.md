# Changelog

What someone already running contexts should know, newest first. Grouped by
date; under each date, anything needing action comes before new features. See
git history for the full list of fixes and smaller changes.

## 2026-09-29

### Action required

- New migration: `make migrate` (or `make migrate-<name>` for an extra instance).

### New features

- Cronjobs can send a selected skill as a natural-language request, which helps
  opencode use skills already listed in its context instead of treating `/skill`
  as an unknown command (`5062aed`).

## 2026-09-24

### Action required

- New migration: `make migrate` (or `make migrate-<name>` for an extra instance).
  Existing cronjobs move to persistent systemd user timers; choose the internal
  scheduler explicitly if systemd is not wanted.

### New features

- Cronjobs can use contexts-owned systemd timers without losing tmux launch or
  conversation pairing. Runner, model, effort, and scheduler backend are now
  configurable per job.

## 2026-09-15

### New features

- `BIND = "0.0.0.0"` in `settings_local.py` makes contexts reachable from
  other machines; see README, Remote access (`ecd3081`).

## 2026-09-11

### Action required

- New migration: `make migrate` (`migrate-<name>` per extra instance).
  - **Breaks:** the server refuses to start with unapplied migrations.
  - **Cope:** run it. The new table records sessions this app launches.
- New sessions no longer reuse the live session for a directory.
  - **Breaks:** `POST /api/sessions/new` and the `+` buttons now always start a
    session instead of typing `prompt` into the one already running there.
  - **Cope:** to talk to a live session, use `POST /api/sessions/send`.

### New features

- Launch, resume and fork opencode sessions from the UI, same buttons as
  Claude. Set `OPENCODE_CMD` in `settings_local.py` if `opencode` is not on
  PATH or in `~/.opencode/bin`.
- opencode conversations show as active while running, and the session bar
  works for them.
- Sessions started from a shell are adopted, if their tmux session is named
  the way contexts names its own (`ctx-<dir>-<hash>`, plus the harness key for
  anything but Claude). Wrap your agent in `tmux new-session -s <that name>`
  and a terminal-started session appears in the UI with a working session bar.
- A session whose command is missing or dies on startup now returns an error
  instead of reporting success with a dead session.

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
