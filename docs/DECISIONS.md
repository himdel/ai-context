# Decisions

Newest first. Dated. The choice, the alternatives, and the why. When a decision
supersedes or conflicts with an earlier one, say so rather than editing the old entry.

`CHANGELOG.md` is a different thing - it is for people already running contexts and
records what breaks. This file records why anything was chosen.

---

## 2026-09-09 - conversations come from a harness adapter, not from a JSONL file

Claude's on-disk format had stopped being merely the *source* of conversations and had
become the *interchange* format: the API handed the frontend Claude's own
`tool_use`/`tool_result` blocks and Claude's tool names, and `render.js` string-matched
Claude quirks (`"Async agent launched"`) to paper over them. Adding opencode with himdel
using both for the same work made that untenable.

**opencode is a SQLite database, not files.** So are codex (`~/.codex/state_5.sqlite`)
and goose (`~/.local/share/goose/sessions/sessions.db`). Claude is the odd one out, and
any abstraction assuming "one file per conversation" would have been wrong immediately -
which is why `ConvRef.revision` is an opaque staleness token rather than the
`(file_size, file_mtime)` pair it replaced.

The canonical model (`api/harness/base.py`) deliberately **keeps Claude's wire vocabulary**
- `text`/`thinking`/`tool_use`, CamelCase tool names - rather than inventing a neutral
one. Not because it is the better shape (opencode's already-merged tool part is), but
because `render.js` has a per-tool view for each of those names and a new dialect would
have meant porting all ~1100 lines for no user-visible gain. Adapters normalize *into*
the renderer's language; the renderer never learns a second one.

What moved server-side is the part that was never presentation: `extractTaskStates`
replayed Claude's `TaskCreate`/`TaskUpdate` protocol in JS to rebuild a todo list, and
`extractRunningAgents` sniffed a magic string. Those are harness semantics. They are now
`Conversation.todos` and `.running_agents`, derived by whichever adapter knows how its own
logs record them - Claude replays mutations, opencode reads the last `todowrite` snapshot,
and the status bar just reads a list.

**Ids stay native; a `source` column says who owns one.** Prefixing everything
(`claude:<uuid>`) would have been unambiguous by construction but needed a data migration
for `ConversationIndex` and `CronJobRun` and would have invalidated bookmarked
`/conversations/<uuid>` URLs. Claude UUIDs and opencode `ses_*` ids do not collide, and
`owner_of()` falls back to probing adapters when `source` is unknown.

**Cost is now own-cost, per row.** It had to change: subagents became index rows of their
own (so they can be opened standalone), and a Claude parent's `cost_usd` used to include
its subagents, so `stats` would have double-counted. opencode already attributes this way
- `session.cost` is the sum of that session's own messages, children excluded, verified
against the data. The with-descendants rollup the detail header shows is rebuilt at read
time from the `parent_id` tree as `cost_usd_total` (and a `_total` for every token bucket
beside it, since the header prints tokens next to the cost and the two have to agree).
The conversation header shows the rollup, the sidebar and the stats screens show own
spend. Consequence: `stats` totals shift
slightly, because they were previously counting Claude subagent spend twice.

**Subagents are both nested and listed.** himdel wanted them expandable where they
happened *and* openable on their own; making them first-class conversations with a
`parent_id` gives both from one change.

The sidebar nesting went through a `<details>` disclosure first and lost it. A sidebar
entry is now a *container*, not a leaf: the conversation's own content sits in a
`.conv-main` child and the subagents are nested items beside it. That fixes two things a
sibling disclosure could not - the parent's coloured left rule runs the full height of the
group, so the block visibly hangs off the conversation rather than separating two of them,
and the click target stays on `.conv-main`, so a click on a child cannot reach the parent's
handler without `stopPropagation`. Expand/collapse went with it: subagents are few and
compact, and a control nobody needs to touch is not worth the state.

Two traps found while wiring opencode up. The conversation header hardcoded `claude-code`
beside the version - but the version *is* the harness's, so it now comes from
`Conversation.source_label`. And opencode keeps **`tokens_reasoning` in a bucket of its
own, outside `tokens_output`**, where it is routinely the larger of the two (768 vs 55 in
one real session); reading `tokens_output` alone silently dropped most of the generated
tokens from the header. Providers bill reasoning at the output rate and `session.cost`
already includes it, so the adapter folds it into `output_tokens` and the token count
stays consistent with the cost printed next to it.

Two things not solved. opencode has **no per-session liveness signal** - the pid in
`~/.local/state/opencode/locks/*/meta.json` hashes to a *project*, not a session, so
`active_ids()` returns empty rather than guessing, and opencode conversations never show
the green dot. And `todowrite` is the one genuine format mismatch: opencode writes a whole
list per call where Claude logs only mutations, so the ids in the status bar are
positional for opencode and real task numbers for Claude.

## 2026-09-08 - the terminal flag is a per-terminal fact, and Ptyxis eats dollars

Found on Fedora + GNOME, where `$TERMINAL` is `ptyxis`. Two separate things were wrong
and both were silent, because everything they break happens inside a window that never
opens.

`_terminal_cmd()` assumed every terminal takes `-e`. That is an rxvt/xterm convention,
not a standard: Ptyxis wants `--`, xfce4-terminal `-x`, wezterm `start --`, kitty and
foot nothing at all. So there is a small table now, `TERMINAL_EXEC`, mapping name to
flag - and it doubles as the PATH search order, replacing the old
`rxvt-unicode`-then-`xterm` fallback with something that finds the terminal a modern
desktop actually has.

Ptyxis then *expands* `$VAR` in the argv it is handed, before the child sees it. An
undefined name becomes the empty string and the empty argument is dropped from the argv
entirely - so `tmux attach -t $3` arrives as `tmux attach -t`, and tmux says `-t expects
an argument`. Session names here are `[a-z0-9-]` so the viewer was safe, but
`terminal/run` passes a command straight through from the UI, and that is not.
`TERMINAL_EXPANDS_VARS` names the terminals that do this (one, so far),
`TERMINAL_ESCAPE_DOLLARS` says whether the resolved terminal is one of them, and
`_viewer_argv` doubles the dollars when it is. `$$` is Ptyxis's own escape.

Worth keeping: the *general* lesson is that the argv handed to a terminal emulator is
not necessarily the argv the child gets. Anything with a `$`, a backslash or a quote in
it is the terminal's to reinterpret, and only the terminal knows how.

The same fix landed in tmuxtray the same day, for the same reason - every tmux id starts
with `$`, so there it was not an edge case at all.

## 2026-09-01 - Cron run pairing resolves eagerly in the background, keyed on pane_pid

Cron runs now get their conversation link resolved by the scheduler thread (every tick)
and opportunistically on the `/api/sessions` poll (`_resolve_all_unresolved_runs`), not
only when the cronjob detail page is opened.

**Supersedes** the view-time-only resolution from the 2026-08-22 cron pairing decision.
That version paired only in `cronjob_detail`, so a run's link appeared only if someone had
that exact page open at the right moment. It missed **prompt-first runs**: Claude writes
its `sessions/<pid>.json` lazily on first output, so a run that blocks on a trust or
permission prompt writes the file late - long after the 10s/30s timestamp-fallback windows
expired - and nothing ever retried. Reply-first runs paired because their file and JSONL
appeared immediately.

Making resolution run continuously exposed a correctness bug in the old deterministic
tier and forced two changes:

- **Identity is `run.pid` (the claude pane_pid at spawn), not the tmux session name.**
  The old tier mapped `tmux_session name -> current pane_pid -> session file`. But cron
  session names are reused across runs (`mode="new"` only suffixes while a name is *live*,
  then reuses the base), so a stale run would grab whatever session now holds its name -
  e.g. four old `/anstrat-daily` runs all resolved to a session running *today*. The
  pane_pid keys `<pid>.json` directly and is stable; a `cwd == repo` guard stops a
  recycled pid from masquerading. The name-based lookup is gone.
- **`_jsonl_first_timestamp` scans past the metadata prefix.** Conversations now open with
  untimestamped `mode` / `permission-mode` / `file-history-snapshot` lines; the helper
  read only line one and returned 0, silently defeating the JSONL fallback for every
  modern conversation.

The JSONL fallback was also widened (15 min window, closest-match at/after trigger) and
every tier now refuses a conversation already claimed by another run, so two runs never
collapse onto one conversation. A one-time clear-and-re-resolve repaired the historical
mislinks (no new model field or migration - it reuses `CronJobRun.conversation_id`).
The background resolver retries until it succeeds, so it survives an app crash: tmux keeps
the cron session alive and the first scheduler iteration after restart pairs the run.

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
