# Decisions

Newest first. Dated. The choice, the alternatives, and the why. When a decision
supersedes or conflicts with an earlier one, say so rather than editing the old entry.

`CHANGELOG.md` is a different thing - it is for people already running contexts and
records what breaks. This file records why anything was chosen.

---

## 2026-08-22 - tmux is the session substrate; the terminal emulator is an optional viewer

Reworked so **tmux owns the claude process headlessly** and the terminal emulator is
decoupled into an optional "attach" viewer. One substrate unlocked Mac support, a real
session registry, queued prompts, and prompt detection.

Decisions taken at the time, all confirmed:

- **Headless tmux plus an optional viewer.** Linux still auto-pops a window by default,
  so nothing was lost.
- **One singleton session per context**, named from the cwd path, reused and attached if
  live. An opt-in "new" mode gets a numeric suffix.
- **Prompts are detected, surfaced and answerable from the UI.**
- **Build the substrate first**; Mac, queued prompts and prompt detection layer on after.

Foundation-first was the explicit ordering choice.

**Capability autodetection is lean, with a platform split.** Resolve at startup - platform
from `sys.platform`, tmux via `which`, GUI via `$DISPLAY`/`$WAYLAND_DISPLAY`, then display,
emulator, notifier. `settings_local` overrides win. Emulator detection stays lean: Linux
honours `$TERMINAL` then rxvt/xterm; **Mac must not use `which`** - iTerm and Terminal have
no command-taking CLI on PATH, so detect via `/Applications/*.app` and launch through
`open -a` / `osascript`, Terminal.app by default and iTerm if present.

All four phases landed: 1 substrate, 2 Mac, 3 queued prompts and registry, 4 polling plus
answerable prompts. See `STATE.md` for what that means today.

## 2026-08-22 - iTerm2 needs its own AppleScript, not `do script`

iTerm2 dropped Terminal's `do script` terminology and fails with osacompile error -2740.
`_viewer_argv` emits iTerm's own
`tell (create window with default profile) to tell current session to write text "..."`
for iTerm and keeps `do script` for Terminal.app.

Found on real hardware (varda, macOS 26, tmux 3.7c, iTerm2), not reasoned about. The
macOS Automation permission prompt fires on first viewer launch - allow once, remembered -
and that is documented in the README.

## 2026-08-22 - Cron runs spawn their own tmux session

`_execute_cronjob` spawns with `mode="new"` so multiple jobs on the same repo, and
repeated runs of one job, each get their own tmux session and actually execute.

**Supersedes** the previous default of `mode="singleton"`, which collapsed them onto one
session and silently skipped all but the first as "reused", with no prompt sent.

Cron pairing resolves deterministically: `CronJobRun.tmux_session` (migration 0007) then
`tmux_session` -> `pane_pid` -> `sessionId` in `_resolve_run_conversations`, with the old
timestamp heuristics kept only as a fallback. The previous timestamp guesswork fired too
soon - see `docs/CLAUDE-SESSION-FILES.md` for why.

**Known consequence, not yet fixed:** those headless sessions are interactive and stay
open, so every cron run leaves an idle session behind. See `IDEAS.md`.

## 2026-08-21 - Track external tool dependencies explicitly, not just Python packages

`pyproject.toml` only records Python deps. The app shells out to tmux, a terminal
emulator, `notify-send`, the `claude` binary and git - all invisible there and easy to
forget.

**How to apply:** when adding a feature that shells out to a tool, document it in the
README and the deps list as **required or optional**, and prefer graceful fallback when
an optional tool is absent (tmux is the default but falls back). Do this without being
reminded.

## 2026-07-16 - Multi-instance support

`CONTEXTS_INSTANCE` selects a per-instance database and settings, so personal and work
Claude data can be browsed side by side in separate tabs. Work runs on :8062, personal on
:8063.

`settings_local_personal.py` is gitignored and exists only on himdel's machine. When
touching settings loading, DB paths or Makefile targets, keep the instance-aware pattern.
