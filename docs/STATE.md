# State

_Last updated: 2026-10-11_

## Where we are

**Conversations are harness-agnostic.** `api/harness/` holds a canonical conversation
model and one adapter per coding agent; `api/views.py` no longer knows any log format.
Claude Code and opencode both work; codex and goose are the expected next two, and both
are SQLite like opencode. The contract is in `docs/HARNESSES.md`, the reasoning in
`DECISIONS.md` (2026-09-09).

- `base.py` - `Conversation`/`Message`/`ConvRef`, block builders, canonical tool names.
- `claude.py` - owns every Claude peculiarity: split tool_use/tool_result, the
  `<task-notification>` async-agent rewrite, subagent matching by `toolUseId` with a
  timestamp fallback, cost summed from `usage` blocks.
- `opencode.py` - reads opencode's live SQLite database read-only, both the V1
  `session`/`message`/`part` schema and V2 `session_v2`/`session_message`.
  Subagent links are exact (`state.metadata.sessionId`), cost is a column,
  tool results arrive merged.
- `__init__.py` - the registry, driven by `settings.HARNESSES`.

Subagents are first-class: nested inline in the conversation *and* listed under their
parent in the sidebar, openable on their own. Cost is own-cost per row, with the rollup
computed at read time.

**Sessions are launched per harness too** (2026-09-11). `launch_argv` on the adapter owns
the flags, `LaunchedSession` records what we started so an opencode conversation can show
as active, and a new session no longer reuses the live one for its directory. Sessions
started from a shell are adopted on sight if their tmux session is named the way we name
ours, which is what the `~/bin/claude` and `~/bin/opencode` wrappers arrange. The tmux
substrate (2026-08-22..24) is otherwise unchanged. Plans, skills and memories stay
Claude-only - they reach `CLAUDE_DIR` through `harness.claude_adapter()`.

Multi-instance (2026-07-16) is in use: default on :8062, personal on :8063. Which
harnesses each one reads is per-instance `settings_local` and differs by machine.

## Known gaps

- **The launchers that start from nothing are still Claude-only** - the new-session screen
  and the repos `+ New` button. See `IDEAS.md`.
- **An adopted session that is resuming shows no conversation until it is used.** opencode
  publishes nothing we can read, so `identify` recognizes a resumed session only once its
  row is touched. A session started in a terminal *outside* a `ctx-` tmux session is
  invisible entirely - that is what the shell wrappers are for.
- **Cron runs leave idle tmux sessions behind.** See `IDEAS.md`.
- `/api/sessions` lists *all* tmux sessions, including non-claude ones with an empty
  `conversation_id`; the frontend filters by `conversation_id` so they are ignored. The
  endpoint also doubles as the fast path for cron run pairing (`_resolve_all_unresolved_runs`).
- Session-file `status`/`waitingFor` can get stuck - see `CLAUDE-SESSION-FILES.md`.
- `x-terminal-emulator` can hide which terminal is really launched - see `IDEAS.md`.

## Next

Nothing scheduled. The obvious follow-ons are a codex adapter and a goose adapter, now
that the contract has been proven against two very different formats - and launching is
part of the contract now, so a third adapter tests both halves. `IDEAS.md` holds the rest
of the backlog.
