# Decisions

Newest first. Dated. The choice, the alternatives, and the why. When a decision
supersedes or conflicts with an earlier one, say so rather than editing the old entry.

`CHANGELOG.md` is a different thing - it is for people already running contexts and
records what breaks. This file records why anything was chosen.

---

## 2026-11-25 - saved, explicitly confirmed report follow-ups

Local Markdown reports need optional next steps without turning document viewing
into execution. Save immutable proposals in Contexts and link to inert review
pages; do not encode prompts in query strings or require active report content.

Always fork the exact source session, live or idle, so report choices never abduct
a live conversation. This refines the existing harness launch/fork contract rather
than adding a second agent transport. Forks use current history and shared project
files, not report-time snapshots; disclose that distinction.

Support both independent one-shot actions and exclusive choice groups. Persist the
claim before external effects; ambiguous delivery stays consumed rather than
retrying something potentially already running. Make report age progressively more
prominent after 2, 6 and 29 days, with acknowledgement from day 7, rather than
arbitrarily expiring useful old evidence. Loopback-only access applies even when
the main app serves the LAN; broader security changes are out of scope.

Use continuation violet (`#8B3DFF`, dark-surface text `#B987FF`) consistently in the
confirmation page and recognized links. Keep reusable authoring instructions in
the bundled `report-actions` skill and only a discovery rule in global instructions,
so cronjobs and ad-hoc reports share one procedure. See `REPORT-ACTIONS.md`.

## 2026-11-25 - use launchd for macOS cronjobs

macOS does not provide a user-level systemd manager. Use per-user `launchd`
LaunchAgents under `~/Library/LaunchAgents`, with one plist per enabled
Contexts cronjob and the database still authoritative.

Translate the existing five-field cron syntax into `StartCalendarInterval`
dictionaries, preserving cron's day-of-month/day-of-week OR semantics. Keep the
same direct `manage.py run_cronjob` worker and harness launch path as systemd;
manual runs use a detached worker because launchd calendar agents have fixed
arguments.

Do not claim systemd's `Persistent=true` behavior: launchd can run a missed
calendar job after sleep, but a full shutdown can skip it. Keep the explicit
`internal` backend for machines without a usable per-user launchd or systemd
manager.

## 2026-11-21 - render PlantUML in the browser

The old renderer compressed each PlantUML block and sent it to the public
`plantuml.com` service. That exposed diagram source and made rendering depend on
the network.

Vendor the official `@plantuml/core` JavaScript build instead. It is PlantUML's
own engine compiled with TeaVM, so it avoids Java, a server, and a Graphviz
binary while preserving PlantUML syntax. The no-build frontend keeps the exact
`1.2026.10` browser assets under `static/vendor/plantuml/` and lazy-loads them
only when a PlantUML block appears.

The engine's small theme and icon assets are vendored too, but the optional
heavy standard-library bundles are not. Setting `PLANTUML_STDLIB_BASE` to the
local directory prevents an accidental fallback to a remote renderer.

## 2026-11-16 - let the OpenCode wrapper own all CLI dispatch

Contexts normally launches `~/bin/opencode`, so the wrapper must understand both
agent invocations and administrative commands. Keep `run` inside tmux with a generated
session ID inserted after the subcommand, while passing `api` and other service/config
subcommands directly to the installed binary. This removes a caller-specific raw-binary
escape hatch from the harness and keeps absolute wrapper configurations correct too.

## 2026-11-16 - tolerate simultaneous cron launch bookkeeping

Persistent timers can all catch up immediately after a resume, so four cron workers may
write the SQLite `LaunchedSession` table at once. SQLite serializes writers; one transient
lock only loses pairing metadata and does not prevent the tmux agent from starting.

Keep that metadata write best-effort, but configure a 30-second SQLite busy timeout and
retry only `database is locked` failures with a short exponential backoff. Do not retry
unrelated database errors or add launch serialization: the agent launch itself is already
independent, and the existing adoption path can recover a live session whose bookkeeping
write was interrupted.

## 2026-10-22 - port the repository-context plugin to OpenCode V2

OpenCode V2 does not execute V1 plugin functions. Keep the repository/branch/PR
context behavior by moving it to V2's `setup`, session-context hook, event
subscription, and tool hook, while reading event payloads from `data` and
session directories from the V2 session record. The contexts app still reads
both V1 and V2 conversation storage; this plugin port changes only metadata
capture and injection.

The same optional plugin is enabled on both of Martin's OpenCode machines, but
each global config keeps its own absolute checkout path and model/provider
settings.

## 2026-10-11 - create OpenCode V2 forks before launching the terminal

V2 removed the CLI `--fork` flag, but offers a service API fork operation that
returns the new session ID. Use `opencode api` to reach the same service and
authentication as the TUI, create the fork before launch, then pass that ID to
`--session` and record it as the terminal's conversation. This is exact pairing,
unlike V1's fork-on-launch heuristic. A failed API call must not launch a fresh
session masquerading as a fork. V1 keeps its CLI flag.

The API call prefers OpenCode's installed binary when `OPENCODE_CMD` is bare:
the shell's `opencode` may be a wrapper that starts a tmux TUI for every
invocation, and an API request is not an interactive session.

## 2026-10-11 - read both OpenCode schemas behind one harness

OpenCode V2 migrates V1 sessions into `session_v2`, but keeps the old `session`
table around and only writes new conversations to `session_v2`. V2 message
content lives inline in `session_message`, not in separate `message` and `part`
rows. Reading only the V1 tables silently showed old history but no new sessions.

Keep one opencode harness, with two storage readers: IDs, launching and the
canonical conversation model are shared. Discover both tables to retain any
unmigrated V1 rows, deduplicate IDs in favour of V2, and include the table in
the revision so cached V1 parses refresh. A separate V2 harness would list
migrated sessions twice and duplicate the shared behaviour.

## 2026-10-09 - select a named agent per cronjob

Cronjobs could choose a model, but a named agent can carry its own model and behavior.
Persist an optional agent name per job and let each runner translate it to its native
`--agent` option. Keep the value opaque and runner-owned so hosts can configure agents
independently for Claude Code and OpenCode.

## 2026-09-29 - make cron skill wording selectable

Cronjobs previously always launched a slash command. That is the right native
interface for Claude, but opencode can treat an unknown slash command as a reset
instead of using the skill list already present in its context.

The cron job now stores a natural-language wording choice. The default remains
the existing slash command for compatibility; the UI checks the option when a
job is switched to opencode, and the natural form asks the agent to run the
named skill while preserving the existing params field. This stays harness-
agnostic and leaves room for a future custom prompt without hardcoding one
runner's behavior into the execution layer.

## 2026-09-24 - wait for ordinary network before persistent cron workers

Persistent user timers correctly catch up after suspend, but they can start before
NetworkManager has reconnected Wi-Fi. The shared host helper at
`%h/bin/wait-for-network` now allows a short settling period, then requires both
a default route and ordinary DNS readiness with a bounded timeout. It deliberately
does not wait for a VPN, so contexts workers for Claude and opencode do not race
the resume path while avoiding the DNS-only false positive observed on
November 4, 2026.

Contexts-owned systemd cron services run the helper with `ExecStartPre`. The
dotfiles crontab generator uses the same precondition by default and provides an
explicit `# local-only` opt-out for jobs such as backups, notes, and wallpaper
rotation. Command inspection is intentionally avoided: shell commands do not
reliably reveal whether they need a network.

Contexts workers intentionally do not replace `PATH` or `SHELL`: their user
systemd manager environment carries the per-user tool paths, OpenAI credentials,
SSH agent, and other launch context needed by tmux and the agent wrappers. The
generated unit pins only `HOME`, the runtime directory, and the user D-Bus
address. Claude's Vertex variables remain wrapper-owned: `claude.work` sources
`~/keys/claude.env` inside the tmux command so a stale tmux server cannot lose
them.

## 2026-09-24 - use GitHub coauthor trailers for assistant attribution

GitHub contributor statistics count the standard `Co-Authored-By` trailer, not the local
`Assisted-by` convention used by many earlier commits. Claude therefore appears as 75
contributions even though the commits remain authored and committed by Martin Hradil.

Future assistant commits use `Co-Authored-By` with the assistant's vendor noreply address.
The OpenAI address currently resolves to GitHub's `codex` account, so that is the identity
GitHub will display for this mode. Existing commits are left unchanged; rewriting pushed
history only to change attribution would provide little value.

## 2026-09-24 - refresh opencode repository metadata at session boundaries

The opencode database does not retain the branch or pull request associated with a
session. Reading the current checkout later can therefore show the wrong branch after
the user switches work. A companion plugin now writes one record per session under
`~/.cache/opencode-contexts/<session-id>.json`.

The record is refreshed on session creation and idle, before a new prompt, after a VCS or
PR tool call, and on branch-change events. Refreshes are debounced for five seconds, so
ordinary tool-heavy turns do not run `git`/`gh` once per tool. Missing plugin/cache data
falls back to the current checkout branch.

The cache is metadata, not a conversation message: injecting it with `noReply` would
pollute the transcript and could affect title/topic detection. The plugin's system
transform injects the refreshed snapshot into model context, while contexts reads the
cache read-only.

## 2026-09-24 - derive opencode branch links from the checkout

Opencode's session table records the working directory but not the git branch. Leaving
the canonical branch field empty meant opencode conversation headers could not link to
the branch or its pull request, even when the directory was a forge checkout.

The adapter now asks git for the current branch while loading the conversation and falls
back to an empty branch for missing, detached, or non-git directories. This keeps the
existing graceful behavior without pretending opencode has historical branch metadata it
does not store.

## 2026-09-24 - normalize opencode tool presentation through the existing renderer

The opencode transcript exercised the same canonical block model as Claude, but several
tools still looked like raw JSON because their names and payloads differed. The adapter
already normalizes tool blocks; the remaining choice was to improve the shared renderer
rather than create an opencode-only view layer.

- `TodoWrite` gets a compact task snapshot view and its history pills scroll to the matching
  snapshot item.
- `jira_*` names use the same semantic input view as the older `mcp__*` names.
- `WebFetch` results are rendered as Markdown, like plan and agent results, because the
  tool returns page content rather than a structured response.
- JSON error results are visibly marked as errors instead of ordinary output.
- Large patches collapse by default, and copy-as-Markdown chooses a fence longer than any
  embedded backtick run so copied transcripts remain valid Markdown.

These are presentation changes only: the canonical adapter data remains available in full.

## 2026-09-24 - preserve opencode task history while highlighting the current plan

Opencode's `todowrite` calls contain complete snapshots, not mutations. Treating the
last snapshot as the whole conversation state hid completed work whenever the agent
moved to a new phase, even though Claude's task replay keeps that history visible.

- **Keep one entry per task subject.** Opencode provides no stable task identifier, so
  repeated subjects are the only safe identity available and receive session-local IDs.
- **Keep the latest status.** A repeated subject updates its existing history entry rather
  than creating a duplicate for every snapshot.
- **Mark the final snapshot.** Entries present in the last snapshot get `current: true` so
  the status bar can emphasize the current plan without discarding earlier work.

This preserves the full useful history while avoiding one UI item for every repeated
`todowrite` call.

## 2026-09-24 - systemd owns persistent cron wakeups when available

The original cronjob scheduler lived in the Django process, so a suspended laptop or a
stopped contexts server could miss a run. The separate dotfiles `crontab` wrapper is not a
fit: contexts jobs belong to SQLite and need the existing tmux/conversation integration.

- **Keep the database authoritative.** Contexts generates its own `contexts-cron-*` units;
  it does not write the user's dotfiles crontab and does not manage `user-cron-*` units.
- **Use an exact persistent systemd calendar.** Cron expressions are translated to
  `OnCalendar=` entries when units are reconciled, so weekly jobs do not wake every
  minute. `Persistent=true` provides one catch-up invocation after suspend.
- **Run a direct Django worker.** A timer does not call the HTTP API or require the web
  process to be running. The worker uses the same launch path as manual runs, so tmux and
  conversation pairing remain intact.
- **Make ownership explicit.** Jobs default to `systemd`; `internal` remains available
  as an explicit choice for machines or troubleshooting where the user manager is not
  wanted. There is no runtime auto-switch that could create duplicate ownership.
- **Keep runner options in the harness registry.** Claude and opencode own their model and
  effort flag dialects; cronjobs pass optional overrides through that same adapter rather
  than inventing a second runner configuration.

This intentionally does not promise agent completion tracking: the worker records whether
the tmux session started, while the agent itself remains an independent process.
## 2026-09-15 - remote access is a setting, and opt-in

himdel wanted contexts reachable from other machines. It had been hardwired to
127.0.0.1 in the Makefile, with `ALLOWED_HOSTS` to match.

- **Bind address is `BIND` in settings, not an env var.** controlpanel starts contexts
  with a bare `make run`, and everything else that differs per machine already lives in
  `settings_local.py`. An env var would have meant editing the launcher on every machine.
  runserver has no setting for its address, so `api` overrides the `runserver` command to
  read `default_addr` from `BIND`, and has to sit ahead of staticfiles in
  `INSTALLED_APPS` for its override to win.
- **Opt-in, loopback by default.** The repo is published and there is no auth; the API
  launches agents that run arbitrary commands, so a default of 0.0.0.0 would hand a shell
  to anyone on the network of someone who just cloned it.
- **A non-loopback `BIND` turns the Host check off.** Once reachable by name or IP from
  elsewhere, listing hostnames is busywork (same stance as the Vite dev servers). On
  loopback the check stays: it is what stops a DNS-rebinding page in a local browser from
  reaching the launch endpoints. `ALLOWED_HOSTS` in `settings_local` still wins if set.

## 2026-09-11 - a session is ours if tmux says it is named like ours

Sessions started in a terminal were invisible, and for opencode that was most of them.
Three ways to fix it were on the table:

- **Have the wrapper register with the API** (`POST /api/sessions/adopt`). Rejected: the
  shell would have to know which port and instance to talk to, and would fail silently
  when contexts is not running - which is exactly when you would not notice.
- **Read the agent's own state.** Fine for Claude, impossible for opencode, and it is the
  thing the whole `LaunchedSession` mechanism exists to work around.
- **Adopt by name.** A tmux session named `ctx-<dir>-<hash>[-<harness>]` is claimed on
  sight, with the directory and start time read from tmux itself.

Adoption by name won because it inverts the dependency: the shell wrapper needs to know
nothing about contexts except a naming convention, contexts needs to know nothing about
the wrapper, and either can be absent. It also costs nothing to *not* use - a session not
named that way is left alone - so the convention is the entire contract.

The price is that the name now carries meaning and has to be parsed back
(`_source_from_session_name`), which puts a second reader on a format
`_tmux_session_name` used to own outright. Acceptable: the format is four fields, it is
tested both directions, and an unrecognized key falls back to Claude rather than failing.

## 2026-09-11 - sessions are launched per harness, and a new session is a new session

Reading opencode conversations but only ever launching Claude was worse than it looked.
The `+` button on an opencode conversation *worked* - it started Claude in that directory,
silently switching agent - while resume and fork 404'd on a transcript that was never
going to exist. So launching joins the harness abstraction: `launch_argv` is the only
place that knows an agent's flags, and a harness that declines to implement it just loses
its session buttons (`can_launch`).

**`mode="new"` is now the default.** `singleton` - one live session per directory, with
any prompt delivered to it by send-keys - was the default because reusing a warm session
felt thrifty. It meant an agent asking for a new session in its own directory typed the
prompt into *itself*, with a multi-line prompt collapsed onto one line; and because the
name was derived from `cwd` alone, resuming conversation A in a directory where B was live
reused B's session and never resumed A at all. The one caller with a real reason to want
one-session-per-repo is cron, and it had already opted out for its own reasons. The mode
stays in the signature; nothing passes it.

**Two things had been quietly turning failures into successes**, both found launching
opencode for the first time:

- A tmux server keeps the environment it was started with - on this machine, a PATH from
  weeks ago without `~/.opencode/bin`. This server's own PATH came from a node toolchain
  and lacked it too. Hence `_resolve_cmd`: resolve argv[0] here, against our PATH and the
  usual per-user install dirs, and fail loudly instead of handing tmux a bare name.
- `tmux new-session` returns 0 for a command that starts and immediately dies, so the
  endpoint answered `{"status": "ok", "pid": null}`. A missing pane right after creation
  is now a 500.

**Knowing which conversation an opencode session is in is our job, not opencode's.** It
has no liveness signal worth reading - the lock directories are transient, hash a project
rather than a session, and vanish seconds after startup; there is no column for it; and a
session row does not exist until the first message is sent. Polling the database for
recently-updated sessions was rejected: "updated 30s ago" is not "live", and an open idle
TUI would read as dead. So we record what we launch (`LaunchedSession`) and ask the
adapter to name it (`identify`) until it can. A resume is exact. A fork or a fresh session
is the newest session in that directory started after we launched - a guess, but bounded
by directory and time, and only ever made among sessions we caused.

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
