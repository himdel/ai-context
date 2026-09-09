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

## Repo maps (aider-style)

Tree-sitter symbol extraction, ranked by a reference graph, fitted to a token budget - a
compact "where things live" map.

Value ranking for scoping: UI-for-user is about equal to primer-for-fresh-agents, and
both beat live help for an already-equipped agent, since grep and Explore already cover
that case well.

So: build the generator once, surface it in the UI first for the visible payoff, then
wire it in as an optional session primer.
