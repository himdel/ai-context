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

## Claude-only features

Plans, skills, memories and the tmux session substrate read `CLAUDE_DIR` directly and are
not part of this abstraction. They reach it through `harness.claude_adapter()` so those
paths stay in one module. Launching a session from the UI is Claude-only too.
