# State

_Last updated: 2026-11-25_

## 2026-11-25

Local report proposals now register stable confirmation links at `/actions/<UUID>`.
Review shows the exact editable message and original context, with escalating age
warnings and explicit acknowledgement for reports at least seven days old.
Confirmed actions always fork; independent one-shot actions and exclusive choice
groups persist their claims before launch and never automatically retry uncertain
delivery. New action routes are loopback-only even when the main app serves a LAN.

The bundled `contrib/skills/report-actions` skill/helper owns report authoring;
mdview and Contexts recognize ordinary action links in continuation violet.
See `REPORT-ACTIONS.md`. Migration 0015 adds action/group tables.

Report paths now link to their current file in mdview (configurable `MDVIEW_URL`);
source and known follow-up IDs link directly into Contexts, in new tabs to preserve
edits. The shared skill/helper also supplies an originating-session link for reports
without actions through its registration-free `--provenance-only` mode.

Verified:
- On 2026-11-25, the user confirmed the real mdview report -> confirmation ->
  OpenCode fork -> desktop notification flow worked. The first attempt exposed
  terminal cleanup appended to API JSON by a local CLI wrapper; correcting that
  wrapper, rather than weakening Contexts' parser, enabled the successful fresh test.
- 21 focused report/helper tests and the extended browser checks pass for the
  mdview/session backlinks and registration-free provenance output.
- 38 focused backend/harness/cron tests and two registration-helper tests pass.
- `tools/report_actions_smoke.py` against the running :8062 UI passes all mocked
  submission scenarios, including stale acknowledgement, exclusive lockout,
  duplicate clicks and lost-response reconciliation, without launching real agents.
- The companion mdview browser check passes on :6821, including both theme colors
  and no action requests during rendering.

## 2026-11-25 - macOS cron support

Cronjobs now have a platform-native persistent backend on macOS: Contexts
reconciles per-user `launchd` LaunchAgents under `~/Library/LaunchAgents`, while
Linux continues to use systemd user timers. Migration `0016` adds the backend;
new jobs default to launchd on macOS. Launchd calendar intervals preserve the
supported cron syntax and day-of-month/day-of-week OR behavior.

The macOS backend deliberately does not promise systemd's shutdown catch-up
semantics. A launchd agent can run after sleep, but a full shutdown can skip a
calendar occurrence.

## 2026-11-21

PlantUML blocks now render locally in the browser with the official `@plantuml/core`
JavaScript engine. The old public `plantuml.com` request and local URL encoder are gone;
the no-build frontend lazy-loads the vendored engine from `static/vendor/plantuml/`.

Verified with the browser smoke page that the local engine produces SVG without a network
request. `make lint` passes and Django's test runner reports 24 tests passing.

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

Cronjobs now have a backend boundary. Existing and new jobs use contexts-owned
persistent systemd user timers by default; the in-process scheduler remains available
as an explicit backend. The database remains authoritative; units use the
`contexts-cron-*` prefix and invoke the direct Django worker, preserving tmux and
conversation pairing. Skill invocation wording is selectable per job, with
natural-language prompts available for harnesses such as opencode.

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
