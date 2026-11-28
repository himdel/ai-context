"""opencode adapter: a live SQLite database, not files on disk.

V1 uses `session` / `message` / `part`; V2 uses `session_v2` /
`session_message` plus, in newer databases, `session_part` rows for content.
Several things
Claude makes us reconstruct are already right here: a tool call carries its own
result, a subagent names its child session outright, and cost is a column.

The database belongs to a program that may be running. Everything below reads
it through `_connect`, which is read-only and deliberately short-lived - see the
comment there before changing how it opens.
"""

import json
import logging
import sqlite3
import subprocess
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from shutil import which
from urllib.parse import quote

from django.conf import settings

from api.harness import base
from api.harness.base import Conversation, ConvRef, Message

logger = logging.getLogger(__name__)

_MAX_SUBAGENT_DEPTH = 4


# opencode's tool names -> the canonical (Claude-shaped) vocabulary the renderer
# knows. Anything absent passes through under its own name and renders
# generically, which is the right outcome for a tool we have not seen yet.
_TOOL_NAMES = {
    "read": base.READ,
    "write": base.WRITE,
    "edit": base.EDIT,
    "bash": base.BASH,
    "grep": base.GREP,
    "glob": base.GLOB,
    "task": base.AGENT,
    "skill": base.SKILL,
    "webfetch": base.WEB_FETCH,
    "websearch": base.WEB_SEARCH,
    "question": base.ASK_USER_QUESTION,
    "todowrite": base.TODO_WRITE,
    "apply_patch": "ApplyPatch",
}

# Per-tool input key renames, applied after the tool name is canonicalized.
# Only the keys that actually differ; `bash`, `grep`, `glob` and `task` already
# agree with Claude's spelling.
_INPUT_KEYS = {
    base.READ: {"filePath": "file_path"},
    base.WRITE: {"filePath": "file_path"},
    base.EDIT: {
        "filePath": "file_path",
        "oldString": "old_string",
        "newString": "new_string",
        "replaceAll": "replace_all",
    },
    base.SKILL: {"name": "skill"},
}


@contextmanager
def _connect(path):
    """Open opencode's database without getting in its way.

    Read-only, autocommit, short-lived. The database is WAL, so a reader never
    blocks opencode's writer - but a *long-lived* read transaction pins the WAL
    and stops it being checkpointed, so it grows without bound while we hold it.
    Hence `isolation_level=None`: every statement is its own brief read
    transaction. This is a context manager rather than a bare connection because
    sqlite3's own `with` block commits but does not *close*, which is precisely
    the leak that would keep a snapshot alive.

    Never pass `immutable=1` here. It reads like the safe option and is the
    opposite: it tells SQLite the file cannot change, so the WAL is ignored and
    recent writes come back missing or torn.
    """
    conn = sqlite3.connect(
        f"file:{path}?mode=ro", uri=True, isolation_level=None, timeout=5.0
    )
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only = 1")
        yield conn
    finally:
        conn.close()


def _json(text):
    try:
        return json.loads(text) if text else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def _iso(ms):
    """opencode stores epoch milliseconds; the rest of the app sorts ISO strings."""
    if not ms:
        return ""
    return (
        datetime.fromtimestamp(ms / 1000, timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _git_branch(path):
    """Return the checkout's branch; opencode does not store one in SQLite."""
    if not path:
        return ""
    try:
        return subprocess.check_output(
            ["git", "-C", path, "branch", "--show-current"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def _cached_context(conversation_id, directory):
    path = Path(settings.OPENCODE_CONTEXT_CACHE_DIR) / f"{conversation_id}.json"
    try:
        context = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError, TypeError):
        return {}
    if (
        context.get("session_id") != conversation_id
        or context.get("directory") != directory
    ):
        return {}
    return context


def _canonical_tool(name, input_):
    canonical = _TOOL_NAMES.get(name, name)
    renames = _INPUT_KEYS.get(canonical)
    if renames and isinstance(input_, dict):
        input_ = {renames.get(k, k): v for k, v in input_.items()}
    return canonical, input_


class OpencodeHarness(base.Harness):
    key = "opencode"
    label = "opencode"

    @property
    def db_path(self):
        return getattr(settings, "OPENCODE_DB", None)

    def available(self):
        # Deliberately just a file check: this runs several times per request,
        # and probing with a real query would open a connection each time.
        # An unreadable or locked database surfaces as an empty result from
        # list_refs/load instead, which is the same outcome for the caller.
        path = self.db_path
        return bool(path) and path.is_file()

    def owns(self, conversation_id):
        return conversation_id.startswith("ses_")

    # -- launching ---------------------------------------------------------

    supports_cron_model = True
    supports_cron_agent = True
    supports_cron_effort = False
    cron_model_choices = [
        "openai/gpt-6-luna",
        "openai/gpt-6-sol",
        "openai/gpt-6-astra",
    ]

    def launch_argv(
        self,
        *,
        conversation_id="",
        prompt="",
        fork=False,
        agent="",
        model="",
        effort="",
        interactive=True,
    ):
        # Interactive launches use the top-level TUI. Cron and other
        # non-interactive callers use `run`, whose prompt is positional.
        # Resume is `--session`; a CLI fork is only used by the V1 fallback.
        if interactive and not (agent or model or effort or fork):
            argv = [settings.OPENCODE_CMD]
            if conversation_id:
                argv += ["--session", conversation_id]
            if prompt:
                argv += ["--prompt", prompt]
            return argv

        argv = [settings.OPENCODE_CMD, "run"]
        if agent:
            argv += ["--agent", agent]
        if model:
            argv += ["--model", model]
        if conversation_id:
            argv += ["--session", conversation_id]
            if fork:
                argv.append("--fork")
        if prompt:
            argv.append(prompt)
        return argv

    def fork_session(self, conversation_id):
        """V2 forks via the service API; V1 still uses the CLI's --fork flag."""
        try:
            with _connect(self.db_path) as conn:
                if not _has_table(conn, "session_v2"):
                    return None
                if not conn.execute(
                    "select 1 from session_v2 where id = ?", (conversation_id,)
                ).fetchone():
                    raise RuntimeError(
                        "session is not available to the OpenCode V2 fork API"
                    )
        except (sqlite3.Error, TypeError) as exc:
            raise RuntimeError("cannot inspect OpenCode session for forking") from exc

        # The shell wrapper passes administrative subcommands, including
        # `api`, directly to the installed binary. Keep this path consistent
        # with ordinary launches so an absolute wrapper setting works too.
        command = settings.OPENCODE_CMD
        if not Path(command).is_absolute():
            command = which(command) or command
        try:
            result = subprocess.run(
                [
                    command,
                    "api",
                    "post",
                    f"/api/session/{quote(conversation_id, safe='')}/fork",
                    "--data",
                    "{}",
                ],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError("OpenCode fork API could not be reached") from exc
        if result.returncode:
            logger.error("OpenCode fork API failed: %s", result.stderr.strip())
            raise RuntimeError("OpenCode fork API failed")
        try:
            fork_id = json.loads(result.stdout)["data"]["id"]
        except (ValueError, KeyError, TypeError) as exc:
            raise RuntimeError("OpenCode fork API returned no session ID") from exc
        if (
            not isinstance(fork_id, str)
            or not fork_id.startswith("ses_")
            or fork_id == conversation_id
        ):
            raise RuntimeError("OpenCode fork API returned an invalid session ID")
        return fork_id

    def identify(self, cwd, since_ms):
        """The session in `cwd` that a process started at `since_ms` is in, or "".

        opencode has no liveness signal we can read - its lock directories are
        transient and hash a project rather than a session - so a session we
        did not hand an id to has to be recognized by what it writes. A row
        only appears once the first message is sent, so this returns "" for a
        TUI that is open but untouched, which is the honest answer.

        Created-since is tried first and is the strong signal: a session that
        came into existence after the process did belongs to it. Updated-since
        is the fallback, and the only thing that can identify `opencode -c` or
        a resume started from a shell, where the row long predates the process.
        """
        try:
            with _connect(self.db_path) as conn:
                table = _session_table(conn)
                sources = (table, "session") if table == "session_v2" else (table,)
                for column in ("time_created", "time_updated"):
                    for source in sources:
                        if source != table and not _has_table(conn, source):
                            continue
                        row = conn.execute(
                            f"select id from {source}"
                            f" where directory = ? and {column} >= ?"
                            " and parent_id is null"
                            f" order by {column} desc limit 1",
                            (cwd, since_ms),
                        ).fetchone()
                        if row:
                            return row["id"]
        except (sqlite3.Error, TypeError):
            logger.exception("opencode identify failed")
        return ""

    # -- discovery ---------------------------------------------------------

    def list_refs(self):
        try:
            with _connect(self.db_path) as conn:
                table = _session_table(conn)
                rows = []
                for source, messages in (
                    ("session_v2", "session_message"),
                    ("session", "message"),
                ):
                    if source != table and not _has_table(conn, source):
                        continue
                    rows.extend(
                        (source, r)
                        for r in conn.execute(
                            "select s.id, s.parent_id, s.agent, s.time_updated,"
                            f" (select count(*) from {messages} m where m.session_id = s.id) n"
                            f" from {source} s"
                        ).fetchall()
                    )
        except (sqlite3.Error, TypeError):
            logger.exception("opencode list_refs failed")
            return
        seen = set()
        for source, r in rows:
            if r["id"] in seen:
                continue
            seen.add(r["id"])
            yield ConvRef(
                id=r["id"],
                revision=f"{source}:{r['time_updated']}:{r['n']}",
                parent_id=r["parent_id"] or "",
                agent_type=r["agent"] or "",
            )

    # -- loading -----------------------------------------------------------

    def load(self, conversation_id, _depth=0):
        if not self.owns(conversation_id):
            return None
        try:
            with _connect(self.db_path) as conn:
                table = _session_table(conn)
                # During migration both tables may hold the same ID. The V2
                # copy is authoritative; V1 is a fallback for older installs.
                session = conn.execute(
                    f"select * from {table} where id = ?", (conversation_id,)
                ).fetchone()
                if (
                    session is None
                    and table == "session_v2"
                    and _has_table(conn, "session")
                ):
                    table = "session"
                    session = conn.execute(
                        "select * from session where id = ?", (conversation_id,)
                    ).fetchone()
                if session is None:
                    return None
                if table == "session_v2":
                    rows = conn.execute(
                        "select id, type, data from session_message"
                        " where session_id = ? order by seq",
                        (conversation_id,),
                    ).fetchall()
                    parts = {}
                    if _has_table(conn, "session_part"):
                        for part in conn.execute(
                            "select message_id, ordinal, data from session_part"
                            " where session_id = ? order by message_id, ordinal",
                            (conversation_id,),
                        ).fetchall():
                            parts.setdefault(part["message_id"], []).append(
                                _json(part["data"])
                            )
                else:
                    rows = conn.execute(
                        "select m.id mid, m.data mdata, p.data pdata"
                        " from message m left join part p on p.message_id = m.id"
                        " where m.session_id = ?"
                        " order by m.time_created, m.id, p.id",
                        (conversation_id,),
                    ).fetchall()
                children = {
                    r["id"]: r["title"]
                    for r in conn.execute(
                        f"select id, title from {table} where parent_id = ?",
                        (conversation_id,),
                    ).fetchall()
                }
        except (sqlite3.Error, TypeError):
            logger.exception("opencode load %s failed", conversation_id)
            return None

        if table == "session_v2":
            messages, text_parts = self._build_v2_messages(rows, parts)
        else:
            messages, text_parts = self._build_messages(rows)
        for block in _tool_blocks(messages):
            sid = block.pop("_session_id", None)
            # _depth guards against a cycle in parent_id; agents nest a few
            # levels deep at most, so this never truncates a real transcript.
            if not sid or sid not in children or _depth >= _MAX_SUBAGENT_DEPTH:
                continue
            sub = self._load_subagent(sid, children[sid], _depth + 1)
            if sub is not None:
                block["subagent"] = sub

        directory = session["directory"] or ""
        repo_context = _cached_context(conversation_id, directory)
        branch = (
            repo_context.get("branch", "") if repo_context else _git_branch(directory)
        )
        model = _json(session["model"]).get("id", "") or session["agent"] or ""
        cost = session["cost"] or 0.0
        return Conversation(
            id=conversation_id,
            source=self.key,
            source_label=self.label,
            parent_id=session["parent_id"] or "",
            agent_type=session["agent"] or "",
            messages=messages,
            cwd=directory,
            branch=branch,
            model=model,
            version=session["version"] or "",
            blurb=(session["title"] or "")[:200],
            first_timestamp=_iso(session["time_created"]),
            last_timestamp=_iso(session["time_updated"]),
            searchable_text="\n".join(text_parts),
            # session.cost is this session's own spend - a parent's cost does
            # not include its children's, which is exactly the split the index
            # wants. Verified against sum(message.cost) per session.
            cost_usd=cost,
            cost_by_model={model or "unknown": cost},
            input_tokens=session["tokens_input"] or 0,
            # tokens_reasoning is a separate bucket here, NOT part of
            # tokens_output - and it is routinely the larger of the two (768 vs
            # 55 in one real session). Providers bill it at the output rate and
            # session.cost already includes it, so folding it in is what keeps
            # the token count consistent with the cost shown beside it.
            output_tokens=(session["tokens_output"] or 0)
            + (session["tokens_reasoning"] or 0),
            cache_read_tokens=session["tokens_cache_read"] or 0,
            cache_write_tokens=session["tokens_cache_write"] or 0,
            todos=_derive_todos(messages),
            running_agents=_derive_running_agents(messages),
        )

    def _build_messages(self, rows):
        """Rows -> canonical messages, one per turn.

        opencode writes an assistant turn as several `message` rows, one per
        step, all sharing the `parentID` of the user message that triggered
        them. Left as-is that renders as a run of near-empty assistant bubbles,
        so consecutive assistant rows of the same turn are merged.
        """
        messages = []
        text_parts = []
        current_key = None
        for row in rows:
            mdata = _json(row["mdata"])
            role = mdata.get("role")
            if role not in ("user", "assistant"):
                continue
            block = _block_from_part(_json(row["pdata"]))
            if block is None:
                continue
            if block.get("type") == "text" and block.get("text"):
                text_parts.append(block["text"])

            key = (role, mdata.get("parentID") or row["mid"])
            if key != current_key:
                messages.append(
                    Message(role, [], _iso((mdata.get("time") or {}).get("created")))
                )
                current_key = key
            messages[-1].blocks.append(block)
        return [m for m in messages if m.blocks], text_parts

    def _build_v2_messages(self, rows, parts_by_message=None):
        """Build V2 messages from inline or separately stored content."""
        messages, text_parts = [], []
        parts_by_message = parts_by_message or {}
        for row in rows:
            data = _json(row["data"])
            role = row["type"]
            if role == "user":
                blocks = [base.text_block(data["text"])] if data.get("text") else []
            elif role == "assistant":
                content = data.get("content") or parts_by_message.get(row["id"], [])
                blocks = [_v2_block(part) for part in content]
                blocks = [block for block in blocks if block is not None]
            else:
                continue
            if not blocks:
                continue
            text_parts.extend(
                block["text"] for block in blocks if block["type"] == "text"
            )
            if role == "assistant" and messages and messages[-1].role == "assistant":
                messages[-1].blocks.extend(blocks)
            else:
                messages.append(
                    Message(role, blocks, _iso((data.get("time") or {}).get("created")))
                )
        return messages, text_parts

    def _load_subagent(self, session_id, title, depth):
        """A child session, shaped for embedding in the parent's Agent block."""
        conv = self.load(session_id, _depth=depth)
        if conv is None:
            return None
        return {
            "id": session_id,
            "agent_type": conv.agent_type,
            "description": title or conv.blurb,
            "timestamp": conv.first_timestamp,
            "tool_use_id": "",
            "messages": [m.as_dict() for m in conv.messages],
        }


def _block_from_part(part):
    """One `part` row -> a canonical block, or None to drop it."""
    ptype = part.get("type")
    if ptype == "text":
        text = part.get("text") or ""
        return base.text_block(text) if text.strip() else None
    if ptype == "reasoning":
        text = part.get("text") or ""
        return base.thinking_block(text) if text.strip() else None
    if ptype == "patch":
        files = part.get("files") or []
        return base.tool_block("Patch", {"files": files}, result="")
    if ptype == "tool":
        state = part.get("state") or {}
        name, input_ = _canonical_tool(part.get("tool", ""), state.get("input") or {})
        status = state.get("status")
        if status == "error":
            result = state.get("error") or ""
        elif status == "completed":
            result = state.get("output") or ""
        else:
            result = None  # still running
        block = base.tool_block(name, input_, result=result)
        # Carried only until load() swaps it for the embedded child transcript.
        block["_session_id"] = ((state.get("metadata") or {}).get("sessionId")) or ""
        return block
    # step-start / step-finish are turn bookkeeping, not conversation content.
    return None


def _session_table(conn):
    """V2 migrated V1 sessions but does not write new ones to the V1 tables."""
    return "session_v2" if _has_table(conn, "session_v2") else "session"


def _has_table(conn, name):
    return bool(
        conn.execute(
            "select 1 from sqlite_master where type = 'table' and name = ?", (name,)
        ).fetchone()
    )


def _v2_block(part):
    kind = part.get("type")
    if kind == "text":
        text = part.get("text") or ""
        return base.text_block(text) if text.strip() else None
    if kind == "reasoning":
        text = part.get("text") or ""
        return base.thinking_block(text) if text.strip() else None
    if kind != "tool":
        return None
    state = part.get("state") or {}
    name, input_ = _canonical_tool(part.get("name", ""), state.get("input") or {})
    if state.get("status") == "error":
        error = state.get("error") or {}
        result = error.get("message", "") if isinstance(error, dict) else str(error)
    elif state.get("status") == "completed":
        result = "\n".join(
            item.get("text", "")
            for item in state.get("content") or []
            if item.get("type") == "text"
        )
    else:
        result = None
    block = base.tool_block(name, input_, result=result)
    block["_session_id"] = (state.get("metadata") or {}).get("sessionId") or ""
    return block


def _tool_blocks(messages):
    for m in messages:
        for block in m.blocks:
            if block.get("type") == "tool_use":
                yield block


def _derive_todos(messages):
    """Replay opencode's snapshots into a deduplicated task history.

    Unlike Claude's task mutations, opencode writes the whole visible list on
    every call. A later snapshot can therefore hide completed work from the
    conversation history. Task content is the only stable identity opencode
    gives us, so repeated subjects are merged and the final snapshot is marked
    as the current one for the status bar.
    """
    todos = []
    by_subject = {}
    current_subjects = set()
    for block in _tool_blocks(messages):
        if block.get("name") != base.TODO_WRITE:
            continue
        items = (block.get("input") or {}).get("todos") or []
        current_subjects = set()
        for item in items:
            if not isinstance(item, dict):
                continue
            subject = item.get("content", "")
            if not subject:
                continue
            current_subjects.add(subject)
            task = by_subject.get(subject)
            if task is None:
                task = {
                    "id": str(len(todos) + 1),
                    "subject": subject,
                    "status": "pending",
                    "current": False,
                }
                by_subject[subject] = task
                todos.append(task)
            task["status"] = item.get("status", "pending")

    for task in todos:
        task["current"] = task["subject"] in current_subjects
    return [t for t in todos if t["status"] != "deleted"]


def _derive_running_agents(messages):
    running = []
    for block in _tool_blocks(messages):
        if block.get("name") != base.AGENT or block.get("subagent"):
            continue
        if block.get("result") is not None:
            continue
        input_ = block.get("input") or {}
        running.append(
            {
                "description": input_.get("description", ""),
                "type": input_.get("subagent_type", ""),
            }
        )
    return running
