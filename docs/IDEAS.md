# Ideas

Record now, do later. Not committed work. Move an item into a plan or `DECISIONS.md` when
it is picked up or settled.

---

## Restore OpenCode V2 fork launching

OpenCode V2.0.26 does not accept the V1 CLI `--fork` flag, although the V2
server exposes `POST /api/session/{sessionID}/fork`. The existing fork button
still launches with that old flag. Integrate the API fork with the tmux launch
and identity flow, or hide the button for V2 until that path works. Discovered
2026-10-11 while restoring V2 conversation visibility; separate from reading
the new SQLite schema.


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

## Keep what an agent prints on the way out

Both Claude and opencode print their parting text - how to resume, what the session cost -
and it is gone before it can be read, because the tmux session dies with the process and
takes the screen with it. Measured 2026-09-11 against the real binaries; none of this is
from the manual.

- **`remain-on-exit on` does not do it, and is not wanted anyway.** Both agents run in the
  alternate screen, and leaving it discards everything they drew - the frozen pane ends up
  showing literally just `Pane is dead (status 0, ...)`. It also keeps the session in tmux
  after the agent exits, which is the opposite of what we want.
- **`alternate-screen off` is the half that matters.** With no alt screen to restore, the
  TUI draws on the normal screen and the final frame survives the process. Verified with
  both agents, in combination with `remain-on-exit`.
- **On its own it still loses everything at exit**, because the session dies with the
  process and the scrollback goes with it (verified: opencode killed with ctrl-c, session
  gone). So `alternate-screen off` only pays off if something reads the pane *before* the
  process exits, or if the viewer terminal is made to hold the window open.
- Both are **window** options, settable per session (`set-option -t <session> -w ...`), so
  any of this can be scoped to `ctx-` sessions without touching global tmux config.

The cost of `alternate-screen off` looked smaller than expected - a short Claude session
left 25 lines of scrollback, since it redraws in place rather than appending - but that
was a session with no real work in it.

**Wants a hands-on test before anything is built**: run a real session with
`alternate-screen off` and see whether the churn is tolerable over hours, and confirm what
the agents actually print on exit (opencode printed *nothing* on `/exit`, and a Claude
session with nothing worth resuming printed no resume hint either).

If it turns out to be worth it, the shape is a setting defaulting off, applied by
`_spawn_session` and by the shell wrappers, plus somewhere for the last frame to land that
is not a pane about to be destroyed.

## Let the other launchers pick a harness

The conversation toolbar now launches whichever harness the conversation belongs to, but
the launchers that start from nothing still assume Claude: the new-session screen and the
repos `+ New` button. Both want a harness picker, defaulting to Claude. The plans `/plan`
picker and the skills launchers are correctly Claude-only - those are Claude features.

## Repo maps (aider-style)

Tree-sitter symbol extraction, ranked by a reference graph, fitted to a token budget - a
compact "where things live" map.

Value ranking for scoping: UI-for-user is about equal to primer-for-fresh-agents, and
both beat live help for an already-equipped agent, since grep and Explore already cover
that case well.

So: build the generator once, surface it in the UI first for the visible payoff, then
wire it in as an optional session primer.
