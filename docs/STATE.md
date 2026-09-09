# State

_Last updated: 2026-09-09_

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
- `opencode.py` - reads opencode's live SQLite database read-only. Subagent links are
  exact (`state.metadata.sessionId`), cost is a column, tool results arrive merged.
- `__init__.py` - the registry, driven by `settings.HARNESSES`.

Subagents are first-class: nested inline in the conversation *and* listed under their
parent in the sidebar, openable on their own. Cost is own-cost per row, with the rollup
computed at read time.

The tmux substrate (2026-08-22..24) is unchanged and remains Claude-only, as do plans,
skills and memories - they reach `CLAUDE_DIR` through `harness.claude_adapter()`.

Multi-instance (2026-07-16) is in use: work on :8062, personal on :8063. opencode is
enabled on work only.

## Known gaps

- **`POST /api/sessions/new` cannot force a new session** - see the Known gaps section in
  `../CLAUDE.md` for the full trap and the workaround.
- **opencode conversations never show as active.** Its lock files carry a pid but hash to
  a project, not a session, so `active_ids()` returns empty rather than guessing.
- **Sessions can only be launched for Claude.** `_spawn_session` and the session bar are
  Claude-only; opencode conversations are read-only in the UI.
- **Cron runs leave idle tmux sessions behind.** See `IDEAS.md`.
- `/api/sessions` lists *all* tmux sessions, including non-claude ones with an empty
  `conversation_id`; the frontend filters by `conversation_id` so they are ignored. The
  endpoint also doubles as the fast path for cron run pairing (`_resolve_all_unresolved_runs`).
- Session-file `status`/`waitingFor` can get stuck - see `CLAUDE-SESSION-FILES.md`.
- `x-terminal-emulator` can hide which terminal is really launched - see `IDEAS.md`.

## Next

Nothing scheduled. The obvious follow-ons are a codex adapter and a goose adapter, now
that the contract has been proven against two very different formats. `IDEAS.md` holds
the rest of the backlog.
