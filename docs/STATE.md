# State

_Last updated: 2026-09-01_

## Where we are

**The tmux-substrate project is complete** - all four phases landed and are committed on
main. tmux owns the claude process headlessly; the terminal emulator is an optional
"attach" viewer.

- **Phase 1, substrate** (2026-08-22). `contexts/capabilities.py` autodetects and feeds
  settings (`USE_TMUX`, `TERMINAL_VIEWER`, `TERMINAL_KIND`, `TERMINAL_CMD`,
  `TERMINAL_APP`, `NOTIFIER`, `TMUX_SESSION_PREFIX`). In `api/views.py`: `_pid_alive`
  (via `os.kill`, replaced `/proc`), the `_tmux*` helpers, `_viewer_argv`/`_open_viewer`,
  `_spawn_terminal`, and `_spawn_session` (tmux-first; used by session new/resume/fork,
  plan execute and cron).
- **Phase 2, Mac** (2026-08-22, verified on varda: macOS 26, tmux 3.7c, iTerm2).
  Capabilities resolve correctly on real darwin; tmux spawn, list-panes, send-keys,
  capture-pane, has-session and kill all work. `osascript display notification` works
  over ssh. **Caveat:** the claude CLI is not installed on varda, so the `<pid>.json`
  pairing itself is Linux-validated only - it is claude's own logic plus POSIX
  `pane_pid`, so it is expected to carry over, but it has not been observed there.
- **Phase 3, queued prompts and registry** (2026-08-22). `_tmux_send`, `_session_files`,
  `_session_registry`; `GET /api/sessions`, `POST /api/sessions/send`,
  `POST /api/sessions/attach`. Cron runs headless with `_notify_session`. The frontend
  gained the `.session-bar`.
- **Phase 4, polling and answerable prompts** (2026-08-24, `871463d`). The session-bar
  polls `/api/sessions` every 3s; on `waiting` it fetches `/api/sessions/capture` and
  renders clickable answer buttons. Static chrome is built once by `buildBar()` so the
  queue-prompt input keeps value and focus across polls.

Multi-instance (2026-07-16) is in use: work on :8062, personal on :8063.

## Known gaps

- **`POST /api/sessions/new` cannot force a new session** - see the Known gaps section in
  `../CLAUDE.md` for the full trap and the workaround.
- **Cron runs leave idle tmux sessions behind.** See `IDEAS.md`.
- `/api/sessions` lists *all* tmux sessions, including non-claude ones with an empty
  `conversation_id`; the frontend filters by `conversation_id` so they are ignored. The
  endpoint also doubles as the fast path for cron run pairing (`_resolve_all_unresolved_runs`).
- Session-file `status`/`waitingFor` can get stuck - see `CLAUDE-SESSION-FILES.md`.

## Next

Nothing scheduled. `IDEAS.md` holds the backlog: closing idle cron sessions is the
concrete one, ACP and repo maps are both spikes.
