# Ideas

Record now, do later. Not committed work. Move an item into a plan or `DECISIONS.md` when
it is picked up or settled.

---

## `x-terminal-emulator` hides which terminal is really being launched

`TERMINAL_EXEC` in `contexts/capabilities.py` keys the exec flag and
`TERMINAL_EXPANDS_VARS` off the binary name, but on Debian `x-terminal-emulator` is an
alternative that can point at any of them - the `ptyxis` package registers itself for it
at priority 40 (verified 2026-09-09 from `ptyxis_50.1-1_amd64.deb`'s postinst). Since
`x-terminal-emulator` is first in `TERMINAL_EXEC` and hardcoded to `-e`, a Debian box
with Ptyxis selected and `$TERMINAL` unset gets the exact launch `f4978da` set out to
fix, and `TERMINAL_ESCAPE_DOLLARS` stays `False` besides.

Debian Policy 11.8.3 does require an `x-terminal-emulator` to accept `-e`, so the flag
is probably survivable; the dollar-escaping is not covered by any policy. Fix would be
to resolve the symlink (`os.path.realpath`) before looking the name up. Not urgent -
this machine sets `$TERMINAL=rxvt-unicode`, which is matched first and sidesteps it.

## Close idle cron sessions

Cron runs spawn headless `claude /skill` sessions that are interactive and do not exit on
completion, so every run leaves an idle tmux session accumulating. Known since
2026-08-24, not fixed.

Options considered: surface open terminals/sessions somewhere in the UI so they can be
attached or closed, and/or an "end session" button on the conversation detail view next
to the existing session-bar controls, killing the tmux session on demand.

## ACP (Agent Client Protocol)

Zed's JSON-RPC protocol between editor (client) and agent (server); Zed ships a
`claude-code-acp` adapter.

**Appeal:** structured state - permission requests, tool calls, options - instead of
screen-scraping the tmux pane. It would kill the fragile glyph and cursor detection
(commits `0d90cc5`, `abac505`).

**Catch:** ACP is headless machine-to-machine with no TUI to `tmux attach` and take over,
so the substrate's human-takeover value is lost.

**Lean:** pursue as a *structured state channel alongside tmux*, not a replacement. Also
worth comparing against the Claude Agent SDK as a more direct path if editor-agnostic
interop is not needed.

Needs a spike to confirm current claude ACP-server support, and whether tmux and ACP can
share one session. **Noted from memory, not research - verify the specifics before
betting on any of it.**

## Launch opencode sessions from the UI

opencode 1.18.30 has everything the session bar needs (verified 2026-09-11 from
`opencode --help` / `opencode run --help`), only under different flag names than Claude:

| | Claude | opencode |
|---|---|---|
| resume | `--resume <id>` | `-s, --session <ses_...>` (or `-c` for the last one) |
| fork | `--resume <id> --fork-session` | `--session <id> --fork` |
| new with a prompt | `claude "<prompt>"` | `opencode --prompt "<prompt>"` |

Both flag sets exist on the TUI entrypoint and on `opencode run` (headless), so a tmux
session works the same way. Session ids are the `ses_...` ids already stored in the index,
so `harness.owner_of()` is enough to pick the argv.

What is missing is purely on our side - the toolbar and every launcher hardcode Claude:

- `static/index.html:1243` renders `+` / resume / fork unconditionally, ignoring
  `data.source` (which the detail payload already carries). On an opencode conversation
  resume and fork 404 (`_find_conversation` only looks for a Claude `.jsonl`) and show a
  bare "x"; `+` is worse - it succeeds, launching *Claude* in an opencode conversation's
  directory with no hint that it switched harness.
- `session_new` / `session_resume` / `session_fork` (`api/views.py`) hardcode
  `settings.CLAUDE_CMD`. There is no `OPENCODE_CMD`.
- The other launchers - new-session screen (`index.html:521`), plans `/plan` picker
  (`:617`), repos `+ New` (`:778`), skills (`skills.js:333,361`) - are all Claude by
  construction. Some of those should stay Claude-only (skills, plans); the repo and
  new-session ones want a harness choice.

**Trap before any of this ships:** `_tmux_session_name` derives the singleton name from
`cwd` alone, so an opencode launch in a directory that already has a live Claude session
would be treated as `reused` and send-keys the prompt into *Claude*. The harness key has
to be part of the session name (or the launch has to be `mode="new"`).

Related: the "already active" 409 guard in `session_resume` leans on `_active_session_ids()`,
and opencode never reports active (see `STATE.md`), so nothing stops resuming a session that
is open in another opencode TUI.

## Repo maps (aider-style)

Tree-sitter symbol extraction, ranked by a reference graph, fitted to a token budget - a
compact "where things live" map.

Value ranking for scoping: UI-for-user is about equal to primer-for-fresh-agents, and
both beat live help for an already-equipped agent, since grep and Explore already cover
that case well.

So: build the generator once, surface it in the UI first for the visible payoff, then
wire it in as an optional session primer.
