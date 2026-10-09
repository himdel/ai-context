"""Claude Code adapter: `CLAUDE_DIR/projects/<dashed-cwd>/<uuid>.jsonl`.

Everything peculiar to Claude's transcripts lives here and stops at this
boundary: tool calls and their results arriving in separate messages, the
`<task-notification>` boilerplate an async agent leaves behind, subagents in
sibling files matched by `toolUseId`, and cost that has to be summed from
`usage` blocks rather than read off a row.
"""

import json
import re
from datetime import datetime

from django.conf import settings

from api.harness import base
from api.harness.base import Conversation, ConvRef, Message


# Model pricing in USD per token as (input, output). Cache read costs 0.1x the
# input rate, 5-minute cache writes 1.25x, 1-hour cache writes 2x. Web search is
# billed per request. These are Anthropic/Vertex list rates and match the vendor's
# own estimate to within ~1% on this env - edit here if your billing differs.
_MODEL_PRICING = {
    "opus": (5e-6, 25e-6),
    "sonnet": (3e-6, 15e-6),
    "haiku": (1e-6, 5e-6),
}
_WEB_SEARCH_COST = 10.0 / 1000  # USD per web_search request

_TASK_NOTIFICATION_RE = re.compile(
    r"<task-notification>.*?"
    r"<tool-use-id>(.*?)</tool-use-id>.*?"
    r"<result>(.*?)</result>.*?"
    r"</task-notification>",
    re.DOTALL,
)

_TASK_CREATED_RE = re.compile(r"Task #(\d+) created successfully: (.+)")

# What an Agent tool_result says while the agent is still running.
_ASYNC_AGENT_PREFIX = "Async agent launched"


def _pricing_for_model(model):
    m = (model or "").lower()
    for family, rates in _MODEL_PRICING.items():
        if family in m:
            return rates
    return None


def _cost_for_usage(model, usage):
    """USD cost for a single API response's usage block."""
    rates = _pricing_for_model(model)
    if not rates:
        return 0.0
    in_rate, out_rate = rates
    cache = usage.get("cache_creation") or {}
    server = usage.get("server_tool_use") or {}
    return (
        usage.get("output_tokens", 0) * out_rate
        + usage.get("input_tokens", 0) * in_rate
        + usage.get("cache_read_input_tokens", 0) * in_rate * 0.1
        + cache.get("ephemeral_5m_input_tokens", 0) * in_rate * 1.25
        + cache.get("ephemeral_1h_input_tokens", 0) * in_rate * 2.0
        + (server.get("web_search_requests", 0) or 0) * _WEB_SEARCH_COST
    )


def _parse_task_notification(text):
    m = _TASK_NOTIFICATION_RE.search(text)
    if m:
        return m.group(1), m.group(2).strip()
    return None, None


def _find_closest_subagent(subagents, target_ts):
    if not target_ts or not subagents:
        return None
    best = None
    best_diff = None
    for s in subagents:
        if not s.get("timestamp"):
            continue
        try:
            diff = abs(
                datetime.fromisoformat(
                    s["timestamp"].replace("Z", "+00:00")
                ).timestamp()
                - datetime.fromisoformat(target_ts.replace("Z", "+00:00")).timestamp()
            )
            if best_diff is None or diff < best_diff:
                best = s
                best_diff = diff
        except (ValueError, TypeError):
            continue
    return best


def _blocks_from_content(content, tool_use_ids):
    """Claude's content list -> canonical blocks, results still separate."""
    blocks = []
    for block in content:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        if btype == "text" and block.get("text", "").strip():
            blocks.append(base.text_block(block["text"]))
        elif btype == "thinking" and block.get("thinking", "").strip():
            blocks.append(base.thinking_block(block["thinking"]))
        elif btype == "tool_use":
            tool_use_ids[block.get("id")] = block.get("name", "")
            b = base.tool_block(block.get("name", ""), block.get("input", {}))
            b["_id"] = block.get("id", "")
            blocks.append(b)
        elif btype == "tool_result":
            result_content = block.get("content", "")
            if isinstance(result_content, list):
                result_content = "\n".join(
                    x.get("text", "") for x in result_content if isinstance(x, dict)
                )
            blocks.append(
                {
                    "type": "tool_result",
                    "name": tool_use_ids.get(block.get("tool_use_id"), ""),
                    "output": str(result_content),
                    "_tool_use_id": block.get("tool_use_id", ""),
                }
            )
    return blocks


def _merge_tool_results(messages, task_notifications, subagents):
    """Fold tool_result blocks into their tool_use, attaching subagents.

    Claude writes a tool call and its result into two different messages, and an
    async agent's result arrives later still, as a `<task-notification>` user
    message referring back to the original tool-use id. Both are stitched here
    so nothing downstream has to know.
    """
    # Async agent boilerplate -> the real completion result.
    if task_notifications:
        for m in messages:
            for block in m.blocks:
                if (
                    block.get("type") == "tool_result"
                    and block.get("name") == base.AGENT
                    and block.get("output", "").startswith(_ASYNC_AGENT_PREFIX)
                ):
                    tuid = block.get("_tool_use_id", "")
                    if tuid in task_notifications:
                        block["output"] = task_notifications[tuid]

    # Match subagents to Agent tool_use blocks by toolUseId, falling back
    # to timestamp proximity for older conversations.
    subagent_by_tuid = {s["tool_use_id"]: s for s in subagents if s.get("tool_use_id")}
    unmatched = [s for s in subagents if not s.get("tool_use_id")]

    agent_tool_uses = {}  # tool_use_id -> timestamp (for fallback matching)
    for m in messages:
        for block in m.blocks:
            if block.get("type") == "tool_use" and block.get("name") == base.AGENT:
                agent_tool_uses[block.get("_id")] = m.timestamp

    for m in messages:
        for block in m.blocks:
            if block.get("type") != "tool_result":
                continue
            if (
                block.get("name") != base.AGENT
                and block.get("_tool_use_id", "") not in subagent_by_tuid
            ):
                continue
            tuid = block.get("_tool_use_id", "")
            best = subagent_by_tuid.pop(tuid, None)
            if not best and unmatched:
                best = _find_closest_subagent(unmatched, agent_tool_uses.get(tuid, ""))
                if best:
                    unmatched = [s for s in unmatched if s is not best]
            if best:
                block["subagent"] = best

    tool_use_map = {}
    for m in messages:
        for block in m.blocks:
            if block.get("type") == "tool_use":
                tool_use_map[block.get("_id")] = block

    def _merge(result_block):
        tool_use = tool_use_map.get(result_block.get("_tool_use_id"))
        if tool_use is None:
            return False
        tool_use["result"] = result_block.get("output", "")
        if "subagent" in result_block:
            tool_use["subagent"] = result_block["subagent"]
        return True

    for m in messages:
        m.blocks = [
            b for b in m.blocks if not (b.get("type") == "tool_result" and _merge(b))
        ]
    messages = [m for m in messages if m.blocks]

    for m in messages:
        for block in m.blocks:
            block.pop("_id", None)
            block.pop("_tool_use_id", None)
    return messages


def _derive_todos(messages):
    """Replay TaskCreate/TaskUpdate into the current todo list.

    Claude has no snapshot of the task list; it only logs the mutations, so the
    state has to be rebuilt by replaying them in order.
    """
    tasks = {}
    for m in messages:
        for block in m.blocks:
            if block.get("type") != "tool_use":
                continue
            name = block.get("name")
            input_ = block.get("input") or {}
            if name == base.TASK_CREATE and block.get("result"):
                match = _TASK_CREATED_RE.search(block["result"])
                if match:
                    tasks[match.group(1)] = {
                        "id": match.group(1),
                        "subject": input_.get("subject") or match.group(2),
                        "status": "pending",
                    }
            elif name == base.TASK_UPDATE and input_.get("taskId"):
                task = tasks.get(str(input_["taskId"]))
                if task:
                    if input_.get("status"):
                        task["status"] = input_["status"]
                    if input_.get("subject"):
                        task["subject"] = input_["subject"]
    return [t for t in tasks.values() if t["status"] != "deleted"]


def _derive_running_agents(messages):
    """Agent calls with no result yet, or still showing the launch placeholder."""
    running = []
    for m in messages:
        for block in m.blocks:
            if block.get("type") != "tool_use" or block.get("name") != base.AGENT:
                continue
            if block.get("subagent"):
                continue
            result = block.get("result")
            if result is None or (
                isinstance(result, str) and result.startswith(_ASYNC_AGENT_PREFIX)
            ):
                input_ = block.get("input") or {}
                running.append(
                    {
                        "description": input_.get("description", ""),
                        "type": input_.get("subagent_type", ""),
                    }
                )
    return running


class ClaudeHarness(base.Harness):
    key = "claude"
    label = "claude-code"  # shown beside the version in the conversation header

    @property
    def projects_dir(self):
        return settings.CLAUDE_DIR / "projects"

    def available(self):
        return self.projects_dir.is_dir()

    # -- discovery ---------------------------------------------------------

    def _conversation_files(self):
        """Yield (jsonl_file, parent_id, agent_type) for transcripts and subagents."""
        if not self.available():
            return
        for project_dir in self.projects_dir.iterdir():
            if not project_dir.is_dir():
                continue
            for jsonl_file in project_dir.glob("*.jsonl"):
                yield jsonl_file, "", ""
                subagents_dir = project_dir / jsonl_file.stem / "subagents"
                if not subagents_dir.is_dir():
                    continue
                for meta_file in subagents_dir.glob("*.meta.json"):
                    agent_id = meta_file.stem.replace(".meta", "")
                    sub_file = subagents_dir / f"{agent_id}.jsonl"
                    if not sub_file.is_file():
                        continue
                    meta = _read_json(meta_file) or {}
                    yield sub_file, jsonl_file.stem, meta.get("agentType", "")

    def list_refs(self):
        for path, parent_id, agent_type in self._conversation_files():
            try:
                stat = path.stat()
            except OSError:
                continue
            yield ConvRef(
                id=path.stem,
                revision=f"{stat.st_size}:{stat.st_mtime}",
                parent_id=parent_id,
                agent_type=agent_type,
            )

    def _find_file(self, conversation_id):
        """Locate a transcript, or a subagent one level down. (path, parent_id)."""
        if not self.available():
            return None, ""
        for project_dir in self.projects_dir.iterdir():
            if not project_dir.is_dir():
                continue
            candidate = project_dir / f"{conversation_id}.jsonl"
            if candidate.is_file():
                return candidate, ""
        for candidate in self.projects_dir.glob(
            f"*/*/subagents/{conversation_id}.jsonl"
        ):
            if candidate.is_file():
                return candidate, candidate.parent.parent.name
        return None, ""

    def owns(self, conversation_id):
        path, _ = self._find_file(conversation_id)
        return path is not None

    def active_ids(self):
        ids = set()
        sessions_dir = settings.CLAUDE_DIR / "sessions"
        if not sessions_dir.is_dir():
            return ids
        for f in sessions_dir.glob("*.json"):
            data = _read_json(f)
            if data and base.pid_alive(data.get("pid")):
                ids.add(data.get("sessionId", ""))
        return ids

    # -- launching ---------------------------------------------------------

    supports_cron_model = True
    supports_cron_agent = True
    supports_cron_effort = True
    cron_model_choices = ["sonnet", "opus", "haiku", "fable"]

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
        argv = [settings.CLAUDE_CMD]
        if agent:
            argv += ["--agent", agent]
        if model:
            argv += ["--model", model]
        if effort:
            argv += ["--effort", effort]
        if conversation_id:
            argv += ["--resume", conversation_id]
            if fork:
                argv.append("--fork-session")
        if prompt:
            argv.append(prompt)
        return argv

    # `identify` stays the base no-op: Claude writes its own session file
    # keyed by pid, which `active_ids` above already reads and is exact.

    # -- loading -----------------------------------------------------------

    def load(self, conversation_id):
        path, parent_id = self._find_file(conversation_id)
        if path is None:
            return None
        conv = self._load_file(path, conversation_id, parent_id)
        if conv is None:
            return None
        if parent_id:
            meta = _read_json(path.parent / f"{conversation_id}.meta.json") or {}
            conv.agent_type = meta.get("agentType", "")
            conv.blurb = meta.get("description", "") or conv.blurb
            # A subagent's transcript has no cwd of its own; it ran where its
            # parent did, and the list groups by directory.
            parent_path, _ = self._find_file(parent_id)
            if parent_path is not None:
                conv.cwd, conv.branch = _first_cwd_branch(parent_path)
        return conv

    def _load_file(self, path, conversation_id, parent_id):
        messages = []
        cwd = branch = model = version = ""
        first_ts = last_ts = ""
        blurb = ""
        text_parts = []
        tool_use_ids = {}
        task_notifications = {}
        totals = _empty_totals()
        seen_request_ids = set()

        try:
            with open(path) as f:
                for line in f:
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    if not cwd:
                        cwd = data.get("cwd", "")
                    if not branch:
                        branch = data.get("gitBranch", "")
                    if not version:
                        version = data.get("version", "")
                    ts = data.get("timestamp", "")
                    if ts:
                        if not first_ts:
                            first_ts = ts
                        last_ts = ts

                    _accumulate_usage(data, totals, seen_request_ids)

                    msg = data.get("message", {}) or {}
                    if not model:
                        model = msg.get("model", "") or ""
                    role = msg.get("role")
                    if role not in ("user", "assistant"):
                        continue

                    content = msg.get("content", "")
                    if role == "user" and isinstance(content, str) and content.strip():
                        tuid, result = _parse_task_notification(content)
                        if tuid:
                            task_notifications[tuid] = result
                            continue
                        blurb = blurb or _blurb_from(content)
                        cleaned = _strip_tags(content)
                        if cleaned:
                            text_parts.append(cleaned)
                        messages.append(Message("user", [base.text_block(content)], ts))
                    elif isinstance(content, list):
                        blocks = _blocks_from_content(content, tool_use_ids)
                        for b in blocks:
                            if b.get("type") == "text":
                                text_parts.append(b["text"])
                        if blocks:
                            messages.append(Message(role, blocks, ts))
        except OSError:
            return None

        subagents = self._load_subagents(path.parent / conversation_id / "subagents")
        messages = _merge_tool_results(messages, task_notifications, subagents)

        return Conversation(
            id=conversation_id,
            source=self.key,
            source_label=self.label,
            parent_id=parent_id,
            messages=messages,
            cwd=cwd,
            branch=branch,
            model=model,
            version=version,
            blurb=blurb,
            first_timestamp=first_ts,
            last_timestamp=last_ts,
            searchable_text="\n".join(text_parts),
            todos=_derive_todos(messages),
            running_agents=_derive_running_agents(messages),
            **totals,
        )

    def _load_subagents(self, subagents_dir):
        """Subagent transcripts, for embedding inline in the parent's Agent block."""
        if not subagents_dir.is_dir():
            return []
        subagents = []
        for meta_file in sorted(subagents_dir.glob("*.meta.json")):
            agent_id = meta_file.stem.replace(".meta", "")
            jsonl_file = subagents_dir / f"{agent_id}.jsonl"
            if not jsonl_file.is_file():
                continue
            meta = _read_json(meta_file) or {}
            conv = self._load_file(jsonl_file, agent_id, subagents_dir.parent.name)
            if conv is None or not conv.messages:
                continue
            subagents.append(
                {
                    "id": agent_id,
                    "agent_type": meta.get("agentType", ""),
                    "description": meta.get("description", ""),
                    "timestamp": conv.first_timestamp,
                    "tool_use_id": meta.get("toolUseId", ""),
                    "messages": [m.as_dict() for m in conv.messages],
                }
            )
        return subagents


def _empty_totals():
    return {
        "cost_usd": 0.0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
    }


def _accumulate_usage(data, totals, seen_request_ids):
    """Add one JSONL line's usage into totals, deduped by requestId.

    Each assistant turn is written as several JSONL lines sharing one requestId
    and an identical usage block, so we count each request only once.
    """
    if data.get("type") != "assistant":
        return
    rid = data.get("requestId")
    if not rid or rid in seen_request_ids:
        return
    seen_request_ids.add(rid)
    msg = data.get("message", {}) or {}
    usage = msg.get("usage") or {}
    cache = usage.get("cache_creation") or {}
    totals["cost_usd"] += _cost_for_usage(msg.get("model", ""), usage)
    totals["input_tokens"] += usage.get("input_tokens", 0)
    totals["output_tokens"] += usage.get("output_tokens", 0)
    totals["cache_read_tokens"] += usage.get("cache_read_input_tokens", 0)
    totals["cache_write_tokens"] += cache.get(
        "ephemeral_5m_input_tokens", 0
    ) + cache.get("ephemeral_1h_input_tokens", 0)


def _strip_tags(content):
    return re.sub(r"<([\w-]+)>[^<]*</\1>", "", content).strip()


def _blurb_from(content):
    """First user message -> list blurb, or the slash command that started it."""
    cleaned = _strip_tags(content)
    if cleaned:
        return cleaned[:200]
    m = re.search(r"<command-message>([\w-]+)</command-message>", content)
    return f"/{m.group(1)}" if m else ""


def _first_cwd_branch(path):
    try:
        with open(path) as f:
            for line in f:
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if data.get("cwd"):
                    return data.get("cwd", ""), data.get("gitBranch", "")
    except OSError:
        pass
    return "", ""


def _read_json(path):
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None
