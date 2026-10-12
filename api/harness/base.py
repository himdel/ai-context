"""The canonical conversation model every harness adapter normalizes into.

The wire vocabulary here is deliberately the one `static/js/render.js` already
speaks - `text`, `thinking` and `tool_use` blocks, with the result merged into
the call and Claude's CamelCase tool names. Adapters translate *into* it; the
renderer never learns a second dialect. See `docs/HARNESSES.md`.
"""

import os
from dataclasses import dataclass, field


def pid_alive(pid):
    """Cross-platform check whether a process is running (replaces /proc)."""
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except (OSError, TypeError, ValueError):
        return False
    return True


# Canonical tool names. Claude's own names are the vocabulary, because the
# renderer already has a per-tool view for each of them; other harnesses map
# onto these. A name not listed here passes through and renders generically.
READ = "Read"
WRITE = "Write"
EDIT = "Edit"
BASH = "Bash"
GREP = "Grep"
GLOB = "Glob"
AGENT = "Agent"
SKILL = "Skill"
WEB_FETCH = "WebFetch"
WEB_SEARCH = "WebSearch"
ASK_USER_QUESTION = "AskUserQuestion"
TODO_WRITE = "TodoWrite"
TASK_CREATE = "TaskCreate"
TASK_UPDATE = "TaskUpdate"
EXIT_PLAN_MODE = "ExitPlanMode"
ENTER_PLAN_MODE = "EnterPlanMode"


@dataclass
class ConvRef:
    """A conversation the adapter can load, cheap to produce - no parsing.

    `revision` is an opaque staleness token compared against the cached copy in
    `ConversationIndex`. Any value that changes when the conversation changes
    will do: a size+mtime pair for a file, an updated-at plus row count for a
    database.
    """

    id: str
    revision: str
    parent_id: str = ""
    agent_type: str = ""


@dataclass
class Message:
    role: str  # "user" or "assistant"
    blocks: list = field(default_factory=list)
    timestamp: str = ""

    def as_dict(self):
        return {
            "role": self.role,
            "content": self.blocks,
            "timestamp": self.timestamp,
        }


@dataclass
class Conversation:
    """One conversation, normalized. `source` is the owning adapter's key.

    `cost_usd` and the token counts are *own* cost - what this conversation
    itself spent, never including its subagents. The with-descendants rollup is
    computed at read time from the index, so that `stats` can sum every row
    without double-counting. See `docs/DECISIONS.md`.
    """

    id: str
    source: str
    # The harness's display name, for the conversation header. The version
    # string is the *harness's* version, so it has to be labelled with the
    # harness that produced it.
    source_label: str = ""
    messages: list = field(default_factory=list)
    parent_id: str = ""
    agent_type: str = ""
    cwd: str = ""
    branch: str = ""
    model: str = ""
    version: str = ""
    blurb: str = ""
    first_timestamp: str = ""
    last_timestamp: str = ""
    searchable_text: str = ""
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    # Derived harness state the UI used to reconstruct in JS.
    todos: list = field(default_factory=list)  # [{id, subject, status, current?}]
    running_agents: list = field(default_factory=list)  # [{description, type}]

    def usage(self):
        return {
            "cost_usd": round(self.cost_usd, 6),
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_write_tokens": self.cache_write_tokens,
        }

    def summary(self):
        """The shape `GET /api/conversations/` returns for one entry."""
        return {
            "id": self.id,
            "source": self.source,
            "parent_id": self.parent_id,
            "agent_type": self.agent_type,
            "project": self.cwd,
            "date": self.first_timestamp,
            "blurb": self.blurb,
            "branch": self.branch,
            "message_count": len(self.messages),
            "last_timestamp": self.last_timestamp,
            **self.usage(),
        }

    def detail(self):
        """The shape `GET /api/conversations/<id>/` returns."""
        return {
            "id": self.id,
            "source": self.source,
            "source_label": self.source_label or self.source,
            "parent_id": self.parent_id,
            "agent_type": self.agent_type,
            "cwd": self.cwd,
            "branch": self.branch,
            "model": self.model,
            "version": self.version,
            "message_count": len(self.messages),
            "first_timestamp": self.first_timestamp,
            "last_timestamp": self.last_timestamp,
            "messages": [m.as_dict() for m in self.messages],
            "todos": self.todos,
            "running_agents": self.running_agents,
            **self.usage(),
        }


def text_block(text):
    return {"type": "text", "text": text}


def thinking_block(text):
    return {"type": "thinking", "text": text}


def tool_block(name, input_, result=None, subagent=None):
    """A tool call with its result already merged in.

    Harnesses that log the call and its result separately (Claude) stitch them
    together in their adapter; harnesses that already store them together
    (opencode) hand them straight over.
    """
    block = {"type": "tool_use", "name": name, "input": input_ or {}}
    if result is not None:
        block["result"] = result
    if subagent is not None:
        block["subagent"] = subagent
    return block


class Harness:
    """Interface every adapter implements.

    Adapters are stateless and cheap to construct; the registry holds one of
    each. Nothing here may raise on missing or unreadable data - report
    `available() is False`, or return nothing, so one broken harness cannot take
    down the conversation list.
    """

    key = ""
    label = ""

    def available(self):
        """Whether this harness's data is present and readable."""
        raise NotImplementedError

    def list_refs(self):
        """Yield a ConvRef per conversation, subagents included."""
        raise NotImplementedError

    def load(self, conversation_id):
        """Return a fully parsed Conversation, or None."""
        raise NotImplementedError

    def owns(self, conversation_id):
        """Whether this id belongs to this harness. Must be cheap."""
        raise NotImplementedError

    def active_ids(self):
        """Ids whose session is currently live. Empty when not detectable."""
        return set()

    # -- launching ---------------------------------------------------------
    #
    # Optional: a harness we can only read still works, it just gets no
    # session buttons in the UI. `launch_argv` returning None is the signal.

    def launch_argv(
        self,
        *,
        conversation_id="",
        prompt="",
        fork=False,
        agent="",
        model="",
        effort="",
    ):
        """Argv that starts this harness, optionally resuming or forking.

        Return None when this harness cannot be launched. The first element is
        a command name; the caller resolves it against PATH.
        """
        return None

    def fork_session(self, conversation_id):
        """Create a fork ahead of launching, returning its ID, or None for CLI forks.

        Harnesses whose CLI forks on launch leave this unimplemented. An error
        creating the fork must raise, not silently start a different session.
        """
        return None

    def identify(self, cwd, since_ms):
        """Id of the session a just-launched process in `cwd` is working in.

        Called only for a launch whose id we could not know up front (a new
        session, or a fork). Return "" while it cannot be told yet - the caller
        retries, so guessing early is worse than answering later.
        """
        return ""
