# Harnesses

Conversations come from more than one coding agent. Each one gets an adapter under
`api/harness/`, and everything that knows a log format stops there - `api/views.py` sees
only the canonical model.

Conversations from every enabled harness land in **one list**, grouped by directory and
sorted by date. That is not the work/personal split, which is `CONTEXTS_INSTANCE` and a
separate database.

| File | Holds |
|---|---|
| `api/harness/base.py` | `Conversation`, `Message`, `ConvRef`, block builders, canonical tool names, `Harness` |
| `api/harness/__init__.py` | The registry: `enabled()`, `get()`, `owner_of()`, `load()`, `active_ids()`, `claude_adapter()` |
| `api/harness/claude.py` | Claude Code - `CLAUDE_DIR/projects/<dashed-cwd>/<uuid>.jsonl` |
| `api/harness/opencode.py` | opencode - `~/.local/share/opencode/opencode.db` (SQLite, read-only) |

## Configuration

`settings.HARNESSES` lists which adapters to read, in order; `settings.OPENCODE_DB` points
at opencode's database. An adapter whose data is absent reports `available() is False` and
is skipped silently, so naming one costs nothing on a machine that does not have it.

`CLAUDE_CMD` and `OPENCODE_CMD` name the binaries to launch. Bare names are fine - they
are resolved against PATH and the usual per-user install dirs - but an override in
`settings_local` can point at an absolute path.

## The contract

```python
class Harness:
    key   = "opencode"     # stored in ConversationIndex.source
    label = "opencode"

    def available(self)            -> bool          # data present and readable
    def list_refs(self)            -> Iterator[ConvRef]   # cheap, no parsing
    def load(self, conversation_id) -> Conversation | None
    def owns(self, conversation_id) -> bool         # must be cheap
    def active_ids(self)           -> set[str]      # empty when not detectable

    # optional - a read-only harness just gets no session buttons
    def launch_argv(self, *, conversation_id="", prompt="", fork=False) -> list | None
    def identify(self, cwd, since_ms) -> str        # "" until it can be told
```

Nothing here may raise on missing or unreadable data. One broken harness must not take
down the conversation list.

`ConvRef.revision` is an **opaque staleness token** compared against the cached copy in
`ConversationIndex`. Anything that changes when the conversation changes will do - Claude
uses `size:mtime`, opencode uses `time_updated:message_count`. Do not assume a file.

## The canonical model

`Conversation` carries the metadata (`cwd`, `branch`, `model`, `blurb`, timestamps, usage)
plus `messages`, and two fields of derived state the UI used to rebuild in JS:

- **`todos`** - `[{id, subject, status}]`. Claude replays `TaskCreate`/`TaskUpdate`;
  opencode reads the last `todowrite` call's list. The status bar just renders it.
- **`running_agents`** - `[{description, type}]`, for agents still in flight.

Blocks are `text`, `thinking`, or `tool_use`. A `tool_use` block carries its **merged
result** and, for a subagent, the child transcript inline under `subagent`. Harnesses that
log a call and its result separately stitch them in their own adapter.

Tool names are canonicalized to Claude's CamelCase spellings (`Read`, `Bash`, `Agent`, ...)
because `static/js/render.js` has a per-tool view keyed on them. Map onto an existing name
where the shape matches; an unmapped name passes through and renders generically, which is
the right outcome for a tool nobody has taught the UI about yet. Input keys are renamed to
match too - see `_TOOL_NAMES` and `_INPUT_KEYS` in `opencode.py`.

## Cost and tokens

Each adapter reports cost in **USD, under its own provider's pricing** - there is no shared
rate table. Claude sums `usage` blocks against the Anthropic list rates in
`_MODEL_PRICING` (`claude.py`, and nothing outside that adapter can reach it); opencode
reads `session.cost`, which opencode itself computed from whichever provider served the
session. Do not apply one harness's rates to another's transcripts.

Report tokens in the four canonical buckets, and **check where reasoning tokens live**
before mapping them. opencode keeps `tokens_reasoning` separate from `tokens_output`, and
it is often the bigger number, so the adapter folds it into `output_tokens` - that is both
how it is billed and what keeps the token count consistent with the cost beside it.

`source_label` is the harness's display name, shown next to `version` in the conversation
header. The version belongs to the harness, so it must never be labelled with a hardcoded
product name.

## Subagents

A subagent is an ordinary conversation with `parent_id` set. It gets its own index row, so
it appears as a nested entry in the sidebar and opens standalone; the parent additionally
embeds it inline in the `Agent` tool block that spawned it. Both come from the same
`parent_id`, so an adapter only has to report the relationship once.

On the sidebar side that makes a `.conversation-item` a container: its own content lives in
a `.conv-main` child, with nested items beside it for the subagents. Padding, hover and the
click handler all belong on `.conv-main` - putting them on the item itself would give a
child the parent's hit area.

**Usage is own-usage.** A parent's `cost_usd` and token counts never include its children,
so `stats` can sum every row and count each once. The rollup is rebuilt at read time by
`_usage_with_descendants` (`views.py`), which walks the `parent_id` tree and returns a
`<field>_total` alongside every usage field.

Which number the UI shows, and why:

| Where | Shows | Because |
|---|---|---|
| Conversation header | `*_total` | what this conversation actually cost to run, subagents included |
| Sidebar entry | own | each row is one row's spend; the subagents are listed right below it |
| Stats / costs screens | own (summed from the index) | summing every row must not count a subagent twice |

The header's tooltip breaks the two apart when they differ. Both harnesses attribute the
same way, so this holds regardless of source.

## Reading a live database

opencode's database belongs to a program that may be running. `_connect` in `opencode.py`
opens it read-only, autocommit, and short-lived, and the docstring there explains why each
of those matters - read it before changing how it opens. In particular: **never pass
`immutable=1`**, which silently ignores the WAL and returns stale or torn data.

## Launching

`launch_argv` is the only place that knows an agent's flags. They do not rhyme - Claude
resumes with `--resume <id>` and forks with `--fork-session`; opencode resumes with
`--session <id>`, forks with `--fork`, and takes a starting prompt as `--prompt` rather
than a positional. Returning None means "readable but not launchable", and the UI drops
the session buttons for that conversation (`can_launch` in the detail payload).

Three rules the substrate enforces around it:

- **The harness key is part of the tmux session name** for everything but Claude. Without
  it, an opencode launch in a directory that already has a live Claude session looks like
  a reuse, and its prompt gets typed into Claude.
- **argv[0] is resolved before tmux sees it.** A tmux server keeps the environment it
  started with, and this server's own PATH depends on how it was launched - neither
  reliably has `~/.opencode/bin`. `_resolve_cmd` tries our PATH, then the usual per-user
  install dirs, and fails loudly rather than handing tmux a name it cannot find.
- **A session that dies on startup is an error**, not `{"status": "ok", "pid": null}`.

Sessions are started with `mode="new"`. The `singleton` mode - one live session per
directory, with a prompt delivered by send-keys - is only right for a caller that
explicitly wants that, and nothing does.

## Knowing which conversation a session is in

Claude writes `CLAUDE_DIR/sessions/<pid>.json` naming its own conversation, so its live
sessions are knowable without our help - that is what `active_ids` reads.

Nothing else does. opencode has no liveness signal at all: its lock directories under
`~/.local/state/opencode/locks/` are transient, hash a project rather than a session, and
are gone seconds after startup; the database has no column for it; and a session row does
not exist until the first message is sent.

So the link exists because we recorded the launch. `LaunchedSession` stores the tmux
session, harness, cwd and start time, and `_resolve_launched_sessions` (`views.py`) fills
in the conversation:

- A **resume** was handed an id, so it is paired from the start - exact, no guessing.
- A **new session or a fork** gets its id from the harness, via `identify(cwd, since_ms)`:
  the newest top-level session in that directory started after we launched. It is asked on
  every poll and answers "" until there is something to answer with, so a TUI sitting open
  and untouched simply has no conversation yet.

Rows are pruned when their tmux session dies. `_active_session_ids` is the union of what
the harnesses report and what these records pair, which is what makes an opencode
conversation show as live and makes the "already active" guard on resume work for it.

### Adopting sessions started from a shell

A session started in a terminal is recorded the same way, as long as its tmux session is
named the way we name ours: `_adopt_tmux_sessions` claims any live `ctx-` session it has
no row for, reading the harness back out of the name and taking the start directory and
creation time from tmux itself. From there it is indistinguishable from one we launched.

That makes a shell wrapper the whole integration. `~/bin/claude` and `~/bin/opencode` on
lorien re-exec the real binary inside `tmux new-session -s ctx-<dir>-<hash>[-<harness>]`,
which is all it takes for a terminal-started session to appear in the UI with a working
session bar. Anything that names its session that way gets adopted; nothing else is
touched.

The catch is what `identify` can then say. A session created after the process started is
found outright. A *resumed* one is not - its row predates the process - so the fallback
matches on `time_updated` instead, which only becomes true once the user sends something.
An adopted TUI sitting at an empty prompt therefore shows as a live session with no
conversation attached, which is the truth.

## Claude-only features

Plans, skills and memories read `CLAUDE_DIR` directly and are not part of this
abstraction. They reach it through `harness.claude_adapter()` so those paths stay in one
module.
