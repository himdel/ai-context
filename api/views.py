import base64
import json
import logging
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from django.conf import settings
from croniter import croniter
from rest_framework.decorators import api_view
from rest_framework.response import Response

from api.models import CronJob, CronJobRun

logger = logging.getLogger(__name__)

_forge_repo_cache = {}
_forge_remote_cache = {}

_KNOWN_FORGE_DOMAINS = {
    "github.com": "github",
    "gitlab.com": "gitlab",
    "codeberg.org": "gitea",
}


def _active_session_ids():
    """Return set of session IDs that have a running process."""
    ids = set()
    sessions_dir = settings.CLAUDE_DIR / "sessions"
    if not sessions_dir.is_dir():
        return ids
    for f in sessions_dir.glob("*.json"):
        try:
            data = json.loads(f.read_text())
            pid = data.get("pid")
            if pid and Path(f"/proc/{pid}").exists():
                ids.add(data.get("sessionId", ""))
        except (json.JSONDecodeError, OSError):
            pass
    return ids


@api_view(["GET"])
def index(request):
    return Response({"status": "ok"})


@api_view(["GET"])
def autolinks(request):
    return Response(
        [
            {"prefix": prefix, "url": url}
            for prefix, url in getattr(settings, "AUTOLINKS", [])
        ]
    )


def _detect_forge_type(hostname):
    custom = getattr(settings, "FORGE_DOMAINS", {})
    return custom.get(hostname) or _KNOWN_FORGE_DOMAINS.get(hostname)


def _parse_forge_remote(path, remote):
    cache_key = f"{path}:{remote}"
    if cache_key in _forge_remote_cache:
        return _forge_remote_cache[cache_key]

    result = None
    cmd = ["git", "-C", path, "remote", "get-url", remote]
    try:
        url = subprocess.check_output(
            cmd,
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        logger.info("ran %s, exit 0", cmd)

        m = re.match(r"git@([^:]+):(.+?)(?:\.git)?$", url)
        if not m:
            m = re.match(r"https?://([^/]+)/(.+?)(?:\.git)?$", url)
        if m:
            hostname = m.group(1)
            repo = m.group(2)
            forge_type = _detect_forge_type(hostname)
            if forge_type:
                result = {
                    "type": forge_type,
                    "base_url": f"https://{hostname}",
                    "repo": repo,
                }
    except subprocess.CalledProcessError as e:
        logger.info("ran %s, exit %d", cmd, e.returncode)
    except FileNotFoundError:
        logger.info("ran %s, command not found", cmd)

    _forge_remote_cache[cache_key] = result
    return result


def _find_pr_for_branch(forge, branch, path):
    if not forge or not branch or branch in ("main", "master", "HEAD"):
        return None

    repo = forge["repo"]
    forge_type = forge["type"]

    from api.models import ForgePR

    cached = ForgePR.objects.filter(repo=repo, branch=branch).first()
    if cached:
        if cached.number is None:
            return None
        return {"number": cached.number, "url": cached.url, "state": cached.state}

    try:
        remote_branches = subprocess.check_output(
            ["git", "-C", path, "branch", "-r", "--list", f"*/{branch}"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        if not remote_branches:
            logger.info("no remote-tracking branch for %s, skipping PR lookup", branch)
            return None
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    pr = None
    if forge_type == "github":
        pr = _find_pr_github(repo, branch)
    elif forge_type == "gitlab":
        pr = _find_mr_gitlab(repo, branch, forge["base_url"])

    if pr:
        ForgePR.objects.create(
            repo=repo,
            branch=branch,
            number=pr["number"],
            url=pr["url"],
            state=pr["state"],
        )

    return pr


def _find_pr_github(repo, branch):
    cmd = [
        "gh",
        "pr",
        "list",
        "--repo",
        repo,
        "--head",
        branch,
        "--json",
        "number,url,state",
        "--limit",
        "1",
    ]
    try:
        out = subprocess.check_output(
            cmd,
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        logger.info("ran %s, exit 0", cmd)
        prs = json.loads(out)
        if prs:
            return prs[0]
    except subprocess.CalledProcessError as e:
        logger.info("ran %s, exit %d", cmd, e.returncode)
    except FileNotFoundError:
        logger.info("ran %s, command not found", cmd)
    except json.JSONDecodeError:
        pass
    return None


def _find_mr_gitlab(repo, branch, base_url):
    cmd = [
        "glab",
        "mr",
        "list",
        "--repo",
        repo,
        "--source-branch",
        branch,
        "-F",
        "json",
    ]
    try:
        out = subprocess.check_output(
            cmd,
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        logger.info("ran %s, exit 0", cmd)
        mrs = json.loads(out)
        if mrs:
            mr = mrs[0]
            return {
                "number": mr.get("iid", mr.get("number")),
                "url": mr.get("web_url", mr.get("url", "")),
                "state": mr.get("state", ""),
            }
    except subprocess.CalledProcessError as e:
        logger.info("ran %s, exit %d", cmd, e.returncode)
    except FileNotFoundError:
        logger.info("ran %s, command not found", cmd)
    except json.JSONDecodeError:
        pass
    return None


@api_view(["GET"])
def github_repo(request):
    path = request.query_params.get("path", "")
    branch = request.query_params.get("branch", "")
    if not path:
        return Response({"upstream": None, "origin": None, "pr": None})

    cache_key = f"{path}:{branch}"
    if cache_key in _forge_repo_cache:
        return Response(_forge_repo_cache[cache_key])

    upstream = _parse_forge_remote(path, "upstream")
    origin = _parse_forge_remote(path, "origin")
    pr = _find_pr_for_branch(upstream or origin, branch, path)

    result = {
        "upstream": upstream,
        "origin": origin,
        "pr": pr,
    }

    _forge_repo_cache[cache_key] = result
    return Response(result)


@api_view(["GET"])
def conversations(request):
    projects_dir = settings.CLAUDE_DIR / "projects"
    if not projects_dir.is_dir():
        return Response([])

    results = []
    for project_dir in projects_dir.iterdir():
        if not project_dir.is_dir():
            continue
        project_name = project_dir.name

        for jsonl_file in project_dir.glob("*.jsonl"):
            conversation_id = jsonl_file.stem
            entry = _ensure_index(jsonl_file, conversation_id, project_name)
            if entry:
                entry["url"] = request.build_absolute_uri(
                    f"/api/conversations/{conversation_id}/"
                )
                results.append(entry)

    # Merge in DB-only entries (files deleted but index remains)
    from api.models import ConversationIndex

    seen_ids = {r["id"] for r in results}
    for ci in ConversationIndex.objects.exclude(conversation_id__in=seen_ids):
        results.append(
            {
                "id": ci.conversation_id,
                "project": ci.project,
                "date": ci.first_timestamp,
                "blurb": ci.blurb,
                "branch": ci.branch,
                "message_count": ci.message_count,
                "last_timestamp": ci.last_timestamp,
                "url": request.build_absolute_uri(
                    f"/api/conversations/{ci.conversation_id}/"
                ),
                "file_missing": True,
            }
        )

    active_ids = _active_session_ids()
    for r in results:
        r["active"] = r["id"] in active_ids

    # Full-text search: each space-separated term must match in text or metadata
    search_query = request.query_params.get("q", "").strip()
    if search_query:
        from django.db.models import Q

        qs = ConversationIndex.objects.all()
        for term in search_query.split():
            qs = qs.filter(
                Q(searchable_text__icontains=term)
                | Q(project__icontains=term)
                | Q(branch__icontains=term)
                | Q(blurb__icontains=term)
            )
        matching_ids = set(qs.values_list("conversation_id", flat=True))
        results = [r for r in results if r["id"] in matching_ids]

    # Filter by repo (matches project/cwd path substring)
    repo_filter = request.query_params.get("repo", "")
    if repo_filter:
        results = [r for r in results if repo_filter in r.get("project", "")]

    # Filter by active status
    active_filter = request.query_params.get("active", "")
    if active_filter == "true":
        results = [r for r in results if r["active"]]
    elif active_filter == "false":
        results = [r for r in results if not r["active"]]

    results.sort(key=lambda x: x["last_timestamp"], reverse=True)
    return Response(results)


def _load_subagents(subagents_dir):
    if not subagents_dir.is_dir():
        return []
    subagents = []
    for meta_file in subagents_dir.glob("*.meta.json"):
        agent_id = meta_file.stem.replace(".meta", "")
        jsonl_file = subagents_dir / f"{agent_id}.jsonl"
        if not jsonl_file.is_file():
            continue
        try:
            meta = json.loads(meta_file.read_text())
        except (json.JSONDecodeError, OSError):
            meta = {}

        messages = []
        first_ts = None
        tool_use_ids = {}
        try:
            with open(jsonl_file) as f:
                for line in f:
                    data = json.loads(line)
                    ts = data.get("timestamp", "")
                    if ts and not first_ts:
                        first_ts = ts
                    msg = data.get("message", {})
                    role = msg.get("role")
                    if role not in ("user", "assistant"):
                        continue
                    content = msg.get("content", "")
                    if isinstance(content, str) and content.strip():
                        messages.append(
                            {
                                "role": role,
                                "content": [{"type": "text", "text": content}],
                            }
                        )
                    elif isinstance(content, list):
                        blocks = []
                        for block in content:
                            if not isinstance(block, dict):
                                continue
                            btype = block.get("type")
                            if btype == "text" and block.get("text", "").strip():
                                blocks.append({"type": "text", "text": block["text"]})
                            elif btype == "tool_use":
                                tool_use_ids[block.get("id")] = block.get("name", "")
                                blocks.append(
                                    {
                                        "type": "tool_use",
                                        "name": block.get("name", ""),
                                        "input": block.get("input", {}),
                                    }
                                )
                            elif btype == "tool_result":
                                tool_name = tool_use_ids.get(
                                    block.get("tool_use_id"), ""
                                )
                                result_content = block.get("content", "")
                                if isinstance(result_content, list):
                                    result_content = "\n".join(
                                        b.get("text", "")
                                        for b in result_content
                                        if isinstance(b, dict)
                                    )
                                blocks.append(
                                    {
                                        "type": "tool_result",
                                        "name": tool_name,
                                        "output": str(result_content),
                                    }
                                )
                        if blocks:
                            messages.append({"role": role, "content": blocks})
        except (json.JSONDecodeError, OSError):
            continue

        if messages:
            subagents.append(
                {
                    "agent_type": meta.get("agentType", ""),
                    "description": meta.get("description", ""),
                    "timestamp": first_ts,
                    "tool_use_id": meta.get("toolUseId", ""),
                    "messages": messages,
                }
            )
    return subagents


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


_TASK_NOTIFICATION_RE = re.compile(
    r"<task-notification>.*?"
    r"<tool-use-id>(.*?)</tool-use-id>.*?"
    r"<result>(.*?)</result>.*?"
    r"</task-notification>",
    re.DOTALL,
)


def _parse_task_notification(text):
    m = _TASK_NOTIFICATION_RE.search(text)
    if m:
        return m.group(1), m.group(2).strip()
    return None, None


@api_view(["GET"])
def conversation_detail(request, conversation_id):
    jsonl_file = _find_conversation(conversation_id)
    if not jsonl_file:
        from api.models import ConversationIndex

        try:
            ci = ConversationIndex.objects.get(conversation_id=conversation_id)
        except ConversationIndex.DoesNotExist:
            return Response({"error": "not found"}, status=404)
        return Response(
            {
                "id": conversation_id,
                "cwd": ci.project,
                "branch": ci.branch,
                "model": "",
                "version": "",
                "message_count": ci.message_count,
                "first_timestamp": ci.first_timestamp,
                "last_timestamp": ci.last_timestamp,
                "active": False,
                "messages": [],
                "file_missing": True,
            }
        )

    messages = []
    cwd = None
    branch = None
    model = None
    version = None
    first_ts = None
    last_ts = None
    tool_use_ids = {}  # id -> name, for labeling tool_results
    task_notifications = {}  # tool_use_id -> result text from async agents
    try:
        with open(jsonl_file) as f:
            for line in f:
                data = json.loads(line)
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
                msg = data.get("message", {})
                if not model:
                    model = msg.get("model", "")
                role = msg.get("role")
                if role not in ("user", "assistant"):
                    continue

                content = msg.get("content", "")
                timestamp = data.get("timestamp", "")

                if role == "user" and isinstance(content, str) and content.strip():
                    tuid, result = _parse_task_notification(content)
                    if tuid:
                        task_notifications[tuid] = result
                        continue
                    messages.append(
                        {
                            "role": "user",
                            "content": [{"type": "text", "text": content}],
                            "timestamp": timestamp,
                        }
                    )

                elif isinstance(content, list):
                    blocks = []
                    for block in content:
                        if not isinstance(block, dict):
                            continue
                        btype = block.get("type")
                        if btype == "text" and block.get("text", "").strip():
                            blocks.append({"type": "text", "text": block["text"]})
                        elif btype == "thinking" and block.get("thinking", "").strip():
                            blocks.append(
                                {"type": "thinking", "text": block["thinking"]}
                            )
                        elif btype == "tool_use":
                            tool_use_ids[block.get("id")] = block.get("name", "")
                            blocks.append(
                                {
                                    "type": "tool_use",
                                    "name": block.get("name", ""),
                                    "input": block.get("input", {}),
                                    "_id": block.get("id", ""),
                                }
                            )
                        elif btype == "tool_result":
                            tool_name = tool_use_ids.get(block.get("tool_use_id"), "")
                            result_content = block.get("content", "")
                            if isinstance(result_content, list):
                                result_content = "\n".join(
                                    b.get("text", "")
                                    for b in result_content
                                    if isinstance(b, dict)
                                )
                            blocks.append(
                                {
                                    "type": "tool_result",
                                    "name": tool_name,
                                    "output": str(result_content),
                                    "_tool_use_id": block.get("tool_use_id", ""),
                                }
                            )
                    if blocks:
                        messages.append(
                            {"role": role, "content": blocks, "timestamp": timestamp}
                        )

    except (json.JSONDecodeError, OSError):
        return Response({"error": "failed to read conversation"}, status=500)

    # Replace async agent boilerplate with actual completion results
    if task_notifications:
        for m in messages:
            for block in m.get("content", []):
                if (
                    block.get("type") == "tool_result"
                    and block.get("name") == "Agent"
                    and block.get("output", "").startswith("Async agent launched")
                ):
                    tuid = block.get("_tool_use_id", "")
                    if tuid in task_notifications:
                        block["output"] = task_notifications[tuid]

    # Load subagents
    subagents = _load_subagents(jsonl_file.parent / conversation_id / "subagents")

    # Match subagents to Agent tool_use blocks by toolUseId, falling back
    # to timestamp proximity for older conversations
    subagent_by_tuid = {s["tool_use_id"]: s for s in subagents if s.get("tool_use_id")}
    unmatched_subagents = [s for s in subagents if not s.get("tool_use_id")]

    agent_tool_uses = {}  # tool_use_id -> timestamp (for fallback matching)
    for m in messages:
        for block in m.get("content", []):
            if block.get("type") == "tool_use" and block.get("name") == "Agent":
                agent_tool_uses[block.get("_id")] = m.get("timestamp", "")

    for m in messages:
        for block in m.get("content", []):
            if block.get("type") != "tool_result":
                continue
            if (
                block.get("name") != "Agent"
                and block.get("_tool_use_id", "") not in subagent_by_tuid
            ):
                continue
            tuid = block.get("_tool_use_id", "")
            best = subagent_by_tuid.pop(tuid, None)
            if not best and unmatched_subagents:
                tool_ts = agent_tool_uses.get(tuid, "")
                best = _find_closest_subagent(unmatched_subagents, tool_ts)
                if best:
                    unmatched_subagents = [
                        s for s in unmatched_subagents if s is not best
                    ]
            if best:
                block["subagent"] = best

    # Merge tool_result into corresponding tool_use blocks
    tool_use_map = {}
    for m in messages:
        for block in m.get("content", []):
            if block.get("type") == "tool_use":
                tool_use_map[block.get("_id")] = block

    def _merge_result(result_block):
        tool_use = tool_use_map.get(result_block.get("_tool_use_id"))
        if tool_use:
            tool_use["result"] = result_block.get("output", "")
            if "subagent" in result_block:
                tool_use["subagent"] = result_block["subagent"]
            return True
        return False

    for m in messages:
        m["content"] = [
            b
            for b in m["content"]
            if not (b.get("type") == "tool_result" and _merge_result(b))
        ]
    messages = [m for m in messages if m.get("content")]

    # Clean internal fields
    for m in messages:
        for block in m.get("content", []):
            block.pop("_id", None)
            block.pop("_tool_use_id", None)

    msg_count = len(messages)
    active_ids = _active_session_ids()
    return Response(
        {
            "id": conversation_id,
            "cwd": cwd,
            "branch": branch,
            "model": model,
            "version": version,
            "message_count": msg_count,
            "first_timestamp": first_ts,
            "last_timestamp": last_ts,
            "active": conversation_id in active_ids,
            "messages": messages,
        }
    )


def _find_conversation(conversation_id):
    projects_dir = settings.CLAUDE_DIR / "projects"
    if not projects_dir.is_dir():
        return None
    for project_dir in projects_dir.iterdir():
        if not project_dir.is_dir():
            continue
        candidate = project_dir / f"{conversation_id}.jsonl"
        if candidate.is_file():
            return candidate
    return None


def _clean_env():
    """Return os.environ without virtualenv pollution, plus DISPLAY."""
    strip = {"VIRTUAL_ENV", "DJANGO_SETTINGS_MODULE"}
    env = {k: v for k, v in os.environ.items() if k not in strip}
    # Strip the venv bin dir from PATH
    venv = os.environ.get("VIRTUAL_ENV")
    if venv and "PATH" in env:
        venv_bin = os.path.join(venv, "bin")
        env["PATH"] = os.pathsep.join(
            p for p in env["PATH"].split(os.pathsep) if p != venv_bin
        )
    env["DISPLAY"] = settings.TERMINAL_DISPLAY
    return env


def _spawn_in_terminal(cmd, cwd):
    """Spawn a command in a terminal with a clean env."""
    full_cmd = settings.TERMINAL_CMD + cmd
    env = _clean_env()
    try:
        proc = subprocess.Popen(full_cmd, cwd=cwd, env=env, start_new_session=True)
        logger.info("spawned %s, pid %d", full_cmd, proc.pid)
        return Response({"status": "ok", "pid": proc.pid})
    except FileNotFoundError:
        return Response({"error": "terminal emulator not found"}, status=500)


@api_view(["POST"])
def terminal_run(request):
    """Spawn a terminal running an arbitrary command in a given cwd."""
    cmd = request.data.get("cmd", [])
    if not cmd or not isinstance(cmd, list):
        return Response({"error": "cmd must be a non-empty list"}, status=400)

    cwd = request.data.get("cwd", "")
    if not cwd or not Path(cwd).is_dir():
        return Response({"error": "cwd is not a valid directory"}, status=400)

    return _spawn_in_terminal(cmd, cwd)


@api_view(["POST"])
def session_new(request):
    prompt = request.data.get("prompt", "").strip()

    cwd = request.data.get("cwd", "")
    if cwd:
        if not Path(cwd).is_dir():
            return Response({"error": "cwd is not a valid directory"}, status=400)
    else:
        cwd = str(Path.home())

    return _spawn_in_terminal(["claude", prompt] if prompt else ["claude"], cwd)


@api_view(["POST"])
def session_resume(request):
    conversation_id = request.data.get("conversation_id", "").strip()
    if not conversation_id:
        return Response({"error": "conversation_id is required"}, status=400)

    if conversation_id in _active_session_ids():
        return Response({"error": "session is already active"}, status=409)

    jsonl_file = _find_conversation(conversation_id)
    if not jsonl_file:
        return Response({"error": "conversation not found"}, status=404)

    cwd = request.data.get("cwd", "")
    if not cwd:
        try:
            with open(jsonl_file) as f:
                first_line = json.loads(f.readline())
                cwd = first_line.get("cwd", "")
        except (json.JSONDecodeError, OSError):
            pass

    if not cwd or not Path(cwd).is_dir():
        cwd = str(Path.home())

    return _spawn_in_terminal(["claude", "--resume", conversation_id], cwd)


@api_view(["POST"])
def session_fork(request):
    conversation_id = request.data.get("conversation_id", "").strip()
    if not conversation_id:
        return Response({"error": "conversation_id is required"}, status=400)

    jsonl_file = _find_conversation(conversation_id)
    if not jsonl_file:
        return Response({"error": "conversation not found"}, status=404)

    cwd = request.data.get("cwd", "")
    if not cwd:
        try:
            with open(jsonl_file) as f:
                first_line = json.loads(f.readline())
                cwd = first_line.get("cwd", "")
        except (json.JSONDecodeError, OSError):
            pass

    if not cwd or not Path(cwd).is_dir():
        cwd = str(Path.home())

    return _spawn_in_terminal(
        ["claude", "--resume", conversation_id, "--fork-session"], cwd
    )


# --- Cronjobs ---


def _cron_summary(expr):
    parts = expr.split()
    if len(parts) != 5:
        return expr
    minute, hour, dom, month, dow = parts
    day_names = {
        "0": "Sun",
        "1": "Mon",
        "2": "Tue",
        "3": "Wed",
        "4": "Thu",
        "5": "Fri",
        "6": "Sat",
        "7": "Sun",
    }
    if dom == "*" and month == "*" and dow == "*":
        if hour == "*":
            return f"Every hour at :{minute.zfill(2)}"
        return f"Daily at {hour}:{minute.zfill(2)}"
    if dom == "*" and month == "*" and dow != "*":
        if "-" in dow:
            start, end = dow.split("-", 1)
            days = f"{day_names.get(start, start)}-{day_names.get(end, end)}"
        else:
            days = ", ".join(day_names.get(d, d) for d in dow.split(","))
        return f"{days} at {hour}:{minute.zfill(2)}"
    return expr


def _conversation_skill(conversation_id):
    """Return the skill name from a conversation's first user message, or ''."""
    jsonl_file = _find_conversation(conversation_id)
    if not jsonl_file:
        return ""
    try:
        with open(jsonl_file) as f:
            for line in f:
                data = json.loads(line)
                msg = data.get("message", {})
                if msg.get("role") != "user":
                    continue
                content = msg.get("content", "")
                if isinstance(content, str):
                    m = re.search(
                        r"<command-message>([\w-]+)</command-message>", content
                    )
                    return m.group(1) if m else ""
                return ""
    except (json.JSONDecodeError, OSError):
        pass
    return ""


def _resolve_run_conversations(runs):
    sessions_dir = settings.CLAUDE_DIR / "sessions"
    if not sessions_dir.is_dir():
        return
    unresolved = [r for r in runs if r.pid and not r.conversation_id]
    if not unresolved:
        return

    sessions = []
    for f in sessions_dir.glob("*.json"):
        try:
            data = json.loads(f.read_text())
            sessions.append(data)
        except (json.JSONDecodeError, OSError):
            pass

    # Build PID lookup (direct match for claude processes)
    pid_to_session = {s.get("pid"): s.get("sessionId", "") for s in sessions}

    for run in unresolved:
        session_id = pid_to_session.get(run.pid, "")
        if not session_id:
            # The stored PID is the terminal wrapper; claude runs as a child
            # with a different PID. Match by cwd + startedAt timestamp instead.
            run_ts = run.triggered_at.timestamp() * 1000
            repo = run.cronjob.repo if run.cronjob_id else ""
            skill = run.cronjob.skill_name if run.cronjob_id else ""
            for s in sessions:
                started = s.get("startedAt", 0)
                cwd = s.get("cwd", "")
                sid = s.get("sessionId", "")
                if (
                    cwd == repo
                    and abs(started - run_ts) < 10_000
                    and (not skill or _conversation_skill(sid) == skill)
                ):
                    session_id = sid
                    break
        if session_id:
            run.conversation_id = session_id
            run.save(update_fields=["conversation_id"])


def _next_run_at(cj):
    if not cj.enabled:
        return None
    try:
        base = cj.last_run_at or cj.created_at
        if base.tzinfo is None:
            base = base.replace(tzinfo=timezone.utc)
        cron = croniter(cj.cron_expression, base)
        nxt = cron.get_next(datetime)
        if nxt.tzinfo is None:
            nxt = nxt.replace(tzinfo=timezone.utc)
        return nxt.isoformat()
    except (ValueError, KeyError):
        return None


def _serialize_cronjob(cj):
    return {
        "id": cj.id,
        "skill_name": cj.skill_name,
        "repo": cj.repo,
        "cron_expression": cj.cron_expression,
        "params": cj.params,
        "enabled": cj.enabled,
        "last_run_at": cj.last_run_at.isoformat() if cj.last_run_at else None,
        "next_run_at": _next_run_at(cj),
        "created_at": cj.created_at.isoformat(),
        "schedule_summary": _cron_summary(cj.cron_expression),
    }


def _execute_cronjob(cj, trigger_type="scheduled"):
    prompt = "/" + cj.skill_name
    if cj.params.strip():
        prompt += " " + cj.params

    if not Path(cj.repo).is_dir():
        return Response({"error": "repo directory not found"}, status=400)

    result = _spawn_in_terminal(["claude", prompt], cj.repo)

    pid = result.data.get("pid") if result.status_code == 200 else None
    CronJobRun.objects.create(cronjob=cj, trigger_type=trigger_type, pid=pid)
    cj.last_run_at = datetime.now(timezone.utc)
    cj.save(update_fields=["last_run_at"])

    return result


@api_view(["GET", "POST"])
def cronjobs_list(request):
    if request.method == "POST":
        skill_name = request.data.get("skill_name", "").strip()
        repo = request.data.get("repo", "").strip()
        cron_expression = request.data.get("cron_expression", "").strip()
        params = request.data.get("params", "")

        if not skill_name or not repo or not cron_expression:
            return Response(
                {"error": "skill_name, repo, and cron_expression are required"},
                status=400,
            )
        if not Path(repo).is_dir():
            return Response({"error": "repo is not a valid directory"}, status=400)
        if not croniter.is_valid(cron_expression):
            return Response({"error": "invalid cron expression"}, status=400)

        cj = CronJob.objects.create(
            skill_name=skill_name,
            repo=repo,
            cron_expression=cron_expression,
            params=params,
        )
        return Response(_serialize_cronjob(cj), status=201)

    cronjobs = CronJob.objects.all().order_by("-created_at")
    return Response([_serialize_cronjob(cj) for cj in cronjobs])


@api_view(["GET", "PUT", "DELETE"])
def cronjob_detail(request, cronjob_id):
    try:
        cj = CronJob.objects.get(id=cronjob_id)
    except CronJob.DoesNotExist:
        return Response({"error": "not found"}, status=404)

    if request.method == "DELETE":
        cj.delete()
        return Response({"status": "deleted"})

    if request.method == "PUT":
        for field in ("skill_name", "repo", "cron_expression", "params"):
            if field in request.data:
                setattr(cj, field, request.data[field])
        if "enabled" in request.data:
            cj.enabled = request.data["enabled"]
        if cj.cron_expression and not croniter.is_valid(cj.cron_expression):
            return Response({"error": "invalid cron expression"}, status=400)
        if cj.repo and not Path(cj.repo).is_dir():
            return Response({"error": "repo is not a valid directory"}, status=400)
        cj.save()

    runs = list(CronJobRun.objects.filter(cronjob=cj).order_by("-triggered_at")[:20])
    _resolve_run_conversations(runs)

    data = _serialize_cronjob(cj)
    data["runs"] = [
        {
            "id": r.id,
            "conversation_id": r.conversation_id,
            "triggered_at": r.triggered_at.isoformat(),
            "trigger_type": r.trigger_type,
            "pid": r.pid,
        }
        for r in runs
    ]
    return Response(data)


@api_view(["POST"])
def cronjob_run(request, cronjob_id):
    try:
        cj = CronJob.objects.get(id=cronjob_id)
    except CronJob.DoesNotExist:
        return Response({"error": "not found"}, status=404)
    return _execute_cronjob(cj, trigger_type="manual")


@api_view(["GET"])
def repos_list(request):
    from django.db.models import Max
    from api.models import ConversationIndex

    repo_activity = dict(
        ConversationIndex.objects.exclude(project="")
        .values_list("project")
        .annotate(latest=Max("last_timestamp"))
        .values_list("project", "latest")
    )

    repos = _discover_repos()
    result = []
    for repo in repos:
        exists = Path(repo).is_dir()
        result.append(
            {
                "path": repo,
                "exists": exists,
                "last_active": repo_activity.get(repo, ""),
            }
        )
    result.sort(key=lambda r: (r["exists"], r["last_active"]), reverse=True)
    return Response(result)


@api_view(["GET"])
def repo_claude_files(request):
    repo = request.query_params.get("repo", "")
    if not repo or not Path(repo).is_dir():
        return Response({"error": "invalid repo path"}, status=400)

    repo_path = Path(repo).resolve()
    seen = set()
    files = []

    def add_file(p, d, name, group):
        key = str(p)
        if key in seen:
            return
        seen.add(key)
        stat = p.stat()
        files.append(
            {
                "path": key,
                "dir": str(d),
                "name": name,
                "group": group,
                "size": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                "content": p.read_text(errors="replace"),
            }
        )

    # Global CLAUDE.md
    global_dir = settings.CLAUDE_DIR
    for name in ("CLAUDE.md",):
        p = global_dir / name
        if p.is_file():
            add_file(p, global_dir, name, "global")

    # Walk from root through ancestors to the repo dir
    parts = repo_path.parts
    for i in range(1, len(parts) + 1):
        d = Path(*parts[:i])
        group = "repo" if d == repo_path else "parent"
        for name in ("CLAUDE.md", "CLAUDE.local.md"):
            p = d / name
            if p.is_file():
                add_file(p, d, name, group)

    # Check immediate subdirectories
    try:
        for child in sorted(repo_path.iterdir()):
            if not child.is_dir() or child.name.startswith("."):
                continue
            for name in ("CLAUDE.md", "CLAUDE.local.md"):
                p = child / name
                if p.is_file():
                    add_file(p, child, name, "subdir")
    except PermissionError:
        pass

    return Response(files)


def _detect_default_branch(path):
    for remote in ("upstream", "origin"):
        try:
            ref = subprocess.check_output(
                ["git", "-C", path, "symbolic-ref", f"refs/remotes/{remote}/HEAD"],
                stderr=subprocess.DEVNULL,
                text=True,
            ).strip()
            return ref.split("/")[-1]
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass
    for name in ("main", "master", "devel"):
        try:
            subprocess.check_output(
                ["git", "-C", path, "rev-parse", "--verify", name],
                stderr=subprocess.DEVNULL,
                text=True,
            )
            return name
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass
    return None


def _get_head_info(path, default_branch):
    try:
        branch = subprocess.check_output(
            ["git", "-C", path, "rev-parse", "--abbrev-ref", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None

    try:
        sha = subprocess.check_output(
            ["git", "-C", path, "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        sha = ""

    try:
        status_output = subprocess.check_output(
            ["git", "-C", path, "status", "--porcelain"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        status_output = ""
    dirty_lines = (
        [line for line in status_output.splitlines() if line.strip()]
        if status_output
        else []
    )

    tracking = None
    if branch != "HEAD":
        try:
            tracking = (
                subprocess.check_output(
                    [
                        "git",
                        "-C",
                        path,
                        "for-each-ref",
                        "--format=%(upstream:short)",
                        f"refs/heads/{branch}",
                    ],
                    stderr=subprocess.DEVNULL,
                    text=True,
                ).strip()
                or None
            )
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass

    compare_ref = tracking
    if not compare_ref and branch != "HEAD" and branch == default_branch:
        for remote in ("upstream", "origin"):
            ref = f"{remote}/{branch}"
            try:
                subprocess.check_output(
                    ["git", "-C", path, "rev-parse", "--verify", ref],
                    stderr=subprocess.DEVNULL,
                    text=True,
                )
                compare_ref = ref
                tracking = ref
                break
            except (subprocess.CalledProcessError, FileNotFoundError):
                pass

    remote_status = None
    if compare_ref:
        try:
            counts = subprocess.check_output(
                [
                    "git",
                    "-C",
                    path,
                    "rev-list",
                    "--left-right",
                    "--count",
                    f"{branch}...{compare_ref}",
                ],
                stderr=subprocess.DEVNULL,
                text=True,
            ).strip()
            ahead, behind = counts.split()
            ahead, behind = int(ahead), int(behind)
            if ahead == 0 and behind == 0:
                remote_status = "up to date"
            elif ahead > 0 and behind > 0:
                remote_status = f"diverged (ahead {ahead}, behind {behind})"
            elif ahead > 0:
                remote_status = f"ahead {ahead}"
            else:
                remote_status = f"behind {behind}"
        except (subprocess.CalledProcessError, FileNotFoundError, ValueError):
            pass

    is_default = branch == default_branch

    return {
        "branch": branch,
        "sha": sha,
        "dirty_count": len(dirty_lines),
        "dirty_files": dirty_lines,
        "default_branch": default_branch,
        "is_default": is_default,
        "remote_status": remote_status,
        "tracking": tracking,
    }


def _list_worktrees(path):
    worktrees = []
    seen_paths = set()
    main_path = None

    try:
        output = subprocess.check_output(
            ["git", "-C", path, "worktree", "list", "--porcelain"],
            stderr=subprocess.DEVNULL,
            text=True,
        )
        current = {}
        for line in output.splitlines():
            if line.startswith("worktree "):
                if current and current.get("path"):
                    if main_path is None:
                        main_path = current["path"]
                    elif current["path"] != main_path:
                        current["source"] = "git"
                        worktrees.append(current)
                        seen_paths.add(current["path"])
                current = {"path": line[9:]}
            elif line.startswith("HEAD "):
                current["sha"] = line[5:][:7]
            elif line.startswith("branch "):
                current["branch"] = line[7:].split("/")[-1]
            elif line == "detached":
                current["branch"] = "(detached)"
            elif not line.strip() and current:
                pass
        if current and current.get("path"):
            if main_path is None:
                main_path = current["path"]
            elif current["path"] != main_path:
                current["source"] = "git"
                worktrees.append(current)
                seen_paths.add(current["path"])
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    claude_wt_dir = Path(path) / ".claude" / "worktrees"
    if claude_wt_dir.is_dir():
        for child in sorted(claude_wt_dir.iterdir()):
            if child.is_dir() and str(child) not in seen_paths:
                wt = {"path": str(child), "source": "claude"}
                try:
                    wt["branch"] = subprocess.check_output(
                        ["git", "-C", str(child), "rev-parse", "--abbrev-ref", "HEAD"],
                        stderr=subprocess.DEVNULL,
                        text=True,
                    ).strip()
                    wt["sha"] = subprocess.check_output(
                        ["git", "-C", str(child), "rev-parse", "--short", "HEAD"],
                        stderr=subprocess.DEVNULL,
                        text=True,
                    ).strip()
                except (subprocess.CalledProcessError, FileNotFoundError):
                    wt["branch"] = child.name
                    wt["sha"] = ""
                worktrees.append(wt)
            elif child.is_dir():
                for wt in worktrees:
                    if wt["path"] == str(child):
                        wt["source"] = "claude"
                        break

    for wt in worktrees:
        try:
            status = subprocess.check_output(
                ["git", "-C", wt["path"], "status", "--porcelain"],
                stderr=subprocess.DEVNULL,
                text=True,
            ).strip()
            dirty_lines = (
                [line for line in status.splitlines() if line.strip()] if status else []
            )
            wt["dirty_count"] = len(dirty_lines)
            wt["dirty_files"] = dirty_lines
        except (subprocess.CalledProcessError, FileNotFoundError):
            wt["dirty_count"] = -1
            wt["dirty_files"] = []

        try:
            branch = wt.get("branch", "")
            if branch and branch != "(detached)":
                wt["tracking"] = (
                    subprocess.check_output(
                        [
                            "git",
                            "-C",
                            wt["path"],
                            "for-each-ref",
                            "--format=%(upstream:short)",
                            f"refs/heads/{branch}",
                        ],
                        stderr=subprocess.DEVNULL,
                        text=True,
                    ).strip()
                    or None
                )
            else:
                wt["tracking"] = None
        except (subprocess.CalledProcessError, FileNotFoundError):
            wt["tracking"] = None

    return worktrees


def _list_branches(path):
    fmt = "%(refname:short)|%(objectname:short)|%(upstream:short)|%(upstream:track)|%(HEAD)|%(committerdate:iso)"
    try:
        output = subprocess.check_output(
            [
                "git",
                "-C",
                path,
                "for-each-ref",
                "--sort=-committerdate",
                "--format",
                fmt,
                "refs/heads/",
            ],
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []

    remote_refs = set()
    try:
        remote_output = subprocess.check_output(
            [
                "git",
                "-C",
                path,
                "for-each-ref",
                "--format=%(refname:short)",
                "refs/remotes/",
            ],
            stderr=subprocess.DEVNULL,
            text=True,
        )
        remote_refs = {r.strip() for r in remote_output.splitlines() if r.strip()}
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    branches = []
    for line in output.strip().splitlines():
        parts = line.split("|", 5)
        if len(parts) < 6:
            continue
        name, sha, tracking, track_status, head_marker, date = parts
        tracking = tracking or None

        if not tracking:
            for remote in ("origin", "upstream"):
                candidate = f"{remote}/{name}"
                if candidate in remote_refs:
                    tracking = candidate
                    break

        if tracking and not track_status.strip():
            try:
                counts = subprocess.check_output(
                    [
                        "git",
                        "-C",
                        path,
                        "rev-list",
                        "--left-right",
                        "--count",
                        f"{name}...{tracking}",
                    ],
                    stderr=subprocess.DEVNULL,
                    text=True,
                ).strip()
                ahead, behind = counts.split()
                ahead, behind = int(ahead), int(behind)
                if ahead > 0 and behind > 0:
                    track_status = f"[ahead {ahead}, behind {behind}]"
                elif ahead > 0:
                    track_status = f"[ahead {ahead}]"
                elif behind > 0:
                    track_status = f"[behind {behind}]"
            except (subprocess.CalledProcessError, FileNotFoundError, ValueError):
                pass

        branches.append(
            {
                "name": name,
                "sha": sha,
                "tracking": tracking,
                "track_status": track_status.strip() or None,
                "is_head": head_marker.strip() == "*",
                "is_default": False,
                "last_commit_date": date.strip(),
                "pr": None,
                "issues": [],
            }
        )
    return branches


def _detect_branch_issues(path, branch, default_branch, autolinks):
    issues = []
    seen = set()

    prefix_patterns = []
    for prefix, url_template in autolinks:
        if "/" not in prefix:
            escaped = re.escape(prefix)
            prefix_patterns.append(
                (prefix, url_template, re.compile(escaped + r"(\d+)", re.IGNORECASE))
            )

    for prefix, url_template, pattern in prefix_patterns:
        for m in pattern.finditer(branch):
            key = prefix.upper() + m.group(1)
            if key not in seen:
                seen.add(key)
                issues.append(
                    {
                        "key": key,
                        "url": url_template.replace("{id}", m.group(1)),
                        "source": "branch_name",
                    }
                )

    branch_squashed = re.sub(r"[-_]", "", branch.lower())
    for prefix, url_template, pattern in prefix_patterns:
        prefix_squashed = re.sub(r"[-_]", "", prefix.lower())
        for m in re.finditer(re.escape(prefix_squashed) + r"(\d+)", branch_squashed):
            key = prefix.upper() + m.group(1)
            if key not in seen:
                seen.add(key)
                issues.append(
                    {
                        "key": key,
                        "url": url_template.replace("{id}", m.group(1)),
                        "source": "branch_name",
                    }
                )

    if default_branch:
        try:
            log_output = subprocess.check_output(
                [
                    "git",
                    "-C",
                    path,
                    "log",
                    f"{default_branch}..{branch}",
                    "--format=%s%n%b",
                    "-n",
                    "20",
                ],
                stderr=subprocess.DEVNULL,
                text=True,
            )
            for prefix, url_template, pattern in prefix_patterns:
                for m in pattern.finditer(log_output):
                    key = prefix.upper() + m.group(1)
                    if key not in seen:
                        seen.add(key)
                        issues.append(
                            {
                                "key": key,
                                "url": url_template.replace("{id}", m.group(1)),
                                "source": "commit",
                            }
                        )
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass

    return issues


@api_view(["GET"])
def repo_git_info(request):
    repo = request.query_params.get("repo", "")
    if not repo or not Path(repo).is_dir():
        return Response({"error": "invalid repo path"}, status=400)

    path = str(Path(repo).resolve())

    try:
        subprocess.check_output(
            ["git", "-C", path, "rev-parse", "--git-dir"],
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return Response({"error": "not a git repository"}, status=400)

    default_branch = _detect_default_branch(path)
    head = _get_head_info(path, default_branch)
    worktrees = _list_worktrees(path)
    branches = _list_branches(path)

    for b in branches:
        b["is_default"] = b["name"] == default_branch

    upstream = _parse_forge_remote(path, "upstream")
    origin = _parse_forge_remote(path, "origin")

    autolinks = getattr(settings, "AUTOLINKS", [])
    for i, b in enumerate(branches):
        if not b["is_default"] and i < 20:
            b["issues"] = _detect_branch_issues(
                path, b["name"], default_branch, autolinks
            )

    forge_info = upstream or origin
    if forge_info:
        from api.models import ForgePR

        repo_slug = forge_info["repo"]
        cached_prs = {
            pr.branch: {"number": pr.number, "url": pr.url, "state": pr.state}
            for pr in ForgePR.objects.filter(repo=repo_slug)
            if pr.number is not None
        }
        for b in branches:
            if b["name"] in cached_prs:
                b["pr"] = cached_prs[b["name"]]

    pr_branch_re = re.compile(r"^pr[/-]?(\d+)$", re.IGNORECASE)
    for b in branches:
        if not b["pr"]:
            m = pr_branch_re.match(b["name"])
            if m and forge_info:
                pr_num = int(m.group(1))
                pr_type = forge_info["type"]
                if pr_type == "gitlab":
                    pr_path = "/-/merge_requests/"
                elif pr_type == "gitea":
                    pr_path = "/pulls/"
                else:
                    pr_path = "/pull/"
                b["pr"] = {
                    "number": pr_num,
                    "url": forge_info["base_url"]
                    + "/"
                    + forge_info["repo"]
                    + pr_path
                    + str(pr_num),
                    "state": None,
                }

    return Response(
        {
            "head": head,
            "worktrees": worktrees,
            "branches": branches,
            "forge": {"upstream": upstream, "origin": origin},
            "default_branch": default_branch,
        }
    )


def _find_pr_by_number(forge, pr_number):
    if not forge:
        return None

    repo = forge["repo"]
    forge_type = forge["type"]

    if forge_type == "github":
        cmd = [
            "gh",
            "pr",
            "view",
            str(pr_number),
            "--repo",
            repo,
            "--json",
            "number,url,state",
        ]
        try:
            out = subprocess.check_output(
                cmd, stderr=subprocess.DEVNULL, text=True
            ).strip()
            logger.info("ran %s, exit 0", cmd)
            data = json.loads(out)
            if data:
                return {
                    "number": data["number"],
                    "url": data["url"],
                    "state": data["state"],
                }
        except subprocess.CalledProcessError as e:
            logger.info("ran %s, exit %d", cmd, e.returncode)
        except (FileNotFoundError, json.JSONDecodeError):
            pass
    elif forge_type == "gitlab":
        cmd = [
            "glab",
            "mr",
            "view",
            str(pr_number),
            "--repo",
            repo,
            "-F",
            "json",
        ]
        try:
            out = subprocess.check_output(
                cmd, stderr=subprocess.DEVNULL, text=True
            ).strip()
            logger.info("ran %s, exit 0", cmd)
            data = json.loads(out)
            if data:
                return {
                    "number": data.get("iid", data.get("number", pr_number)),
                    "url": data.get("web_url", data.get("url", "")),
                    "state": data.get("state", ""),
                }
        except subprocess.CalledProcessError as e:
            logger.info("ran %s, exit %d", cmd, e.returncode)
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    return None


@api_view(["GET"])
def repo_branch_pr(request):
    repo = request.query_params.get("repo", "")
    branch = request.query_params.get("branch", "")
    pr_number = request.query_params.get("pr_number", "")
    if not repo or not branch:
        return Response({"error": "repo and branch required"}, status=400)

    path = str(Path(repo).resolve())
    upstream = _parse_forge_remote(path, "upstream")
    origin = _parse_forge_remote(path, "origin")
    forge = upstream or origin

    if pr_number:
        pr = _find_pr_by_number(forge, pr_number)
        if pr:
            from api.models import ForgePR

            ForgePR.objects.update_or_create(
                repo=forge["repo"] if forge else "",
                branch=branch,
                defaults={
                    "number": pr["number"],
                    "url": pr["url"],
                    "state": pr["state"],
                },
            )
    else:
        pr = _find_pr_for_branch(forge, branch, path)

    return Response({"branch": branch, "pr": pr})


def _build_plan_conversation_map():
    """Scan all JSONL files to map plan filenames to originating conversations."""
    plan_map = {}  # plan_stem -> {conversation_id, cwd, branch, timestamp}
    projects_dir = settings.CLAUDE_DIR / "projects"
    if not projects_dir.is_dir():
        return plan_map
    for project_dir in projects_dir.iterdir():
        if not project_dir.is_dir():
            continue
        for jsonl_file in project_dir.glob("*.jsonl"):
            conversation_id = jsonl_file.stem
            cwd = ""
            branch = ""
            try:
                with open(jsonl_file) as f:
                    for line in f:
                        data = json.loads(line)
                        if not cwd:
                            cwd = data.get("cwd", "")
                        if not branch:
                            branch = data.get("gitBranch", "")
                        msg = data.get("message", {})
                        content = msg.get("content")
                        if not isinstance(content, list):
                            continue
                        for block in content:
                            if (
                                isinstance(block, dict)
                                and block.get("type") == "tool_use"
                                and block.get("name") == "ExitPlanMode"
                            ):
                                plan_path = block.get("input", {}).get(
                                    "planFilePath", ""
                                )
                                if plan_path:
                                    stem = Path(plan_path).stem
                                    ts = data.get("timestamp", "")
                                    if stem not in plan_map or (
                                        ts and ts > plan_map[stem].get("timestamp", "")
                                    ):
                                        plan_map[stem] = {
                                            "conversation_id": conversation_id,
                                            "cwd": cwd,
                                            "branch": branch,
                                            "timestamp": ts,
                                        }
            except (json.JSONDecodeError, OSError):
                pass
    return plan_map


@api_view(["GET"])
def plans(request):
    plans_dir = settings.CLAUDE_DIR / "plans"
    if not plans_dir.is_dir():
        return Response([])

    plan_map = _build_plan_conversation_map()
    results = []

    for plan_file in plans_dir.glob("*.md"):
        plan_id = plan_file.stem
        try:
            text = plan_file.read_text()
        except OSError:
            continue

        # Extract title from first # line
        title = plan_id
        blurb = ""
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("# "):
                title = line[2:].strip()
                break

        # Extract blurb: first non-empty, non-heading line after title
        past_title = False
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("# "):
                past_title = True
                continue
            if past_title and line and not line.startswith("#"):
                blurb = line[:200]
                break

        entry = {
            "id": plan_id,
            "title": title,
            "blurb": blurb,
            "file_path": str(plan_file),
        }

        conv_info = plan_map.get(plan_id)
        if conv_info:
            entry["conversation_id"] = conv_info["conversation_id"]
            entry["project"] = conv_info["cwd"]
            entry["branch"] = conv_info["branch"]
            entry["date"] = conv_info["timestamp"]
        else:
            entry["conversation_id"] = None
            entry["project"] = ""
            entry["branch"] = ""
            # Fall back to file mtime
            try:
                mtime = plan_file.stat().st_mtime
                entry["date"] = datetime.fromtimestamp(mtime).isoformat()
            except OSError:
                entry["date"] = ""

        results.append(entry)

    results.sort(key=lambda x: x.get("date", ""), reverse=True)
    return Response(results)


@api_view(["GET"])
def plan_detail(request, plan_id):
    plan_file = settings.CLAUDE_DIR / "plans" / f"{plan_id}.md"
    if not plan_file.is_file():
        return Response({"error": "not found"}, status=404)

    try:
        content = plan_file.read_text()
    except OSError:
        return Response({"error": "failed to read plan"}, status=500)

    title = plan_id
    for line in content.splitlines():
        line = line.strip()
        if line.startswith("# "):
            title = line[2:].strip()
            break

    plan_map = _build_plan_conversation_map()
    conv_info = plan_map.get(plan_id)

    result = {
        "id": plan_id,
        "title": title,
        "content": content,
        "file_path": str(plan_file),
    }

    if conv_info:
        result["conversation_id"] = conv_info["conversation_id"]
        result["cwd"] = conv_info["cwd"]
        result["branch"] = conv_info["branch"]
        result["date"] = conv_info["timestamp"]
    else:
        result["conversation_id"] = None
        result["cwd"] = ""
        result["branch"] = ""
        result["date"] = ""

    return Response(result)


@api_view(["POST"])
def plan_execute(request, plan_id):
    plan_file = settings.CLAUDE_DIR / "plans" / f"{plan_id}.md"
    if not plan_file.is_file():
        return Response({"error": "not found"}, status=404)

    cwd = request.data.get("cwd", "")
    if not cwd:
        plan_map = _build_plan_conversation_map()
        conv_info = plan_map.get(plan_id)
        if conv_info:
            cwd = conv_info["cwd"]

    if not cwd or not Path(cwd).is_dir():
        cwd = str(Path.home())

    prompt = f"Execute the plan in {plan_file}"
    return _spawn_in_terminal(["claude", prompt], cwd)


def _path_id(path):
    """Encode a filesystem path as a URL-safe base64 identifier."""
    return base64.urlsafe_b64encode(str(path).encode()).decode().rstrip("=")


def _id_to_path(encoded_id):
    """Decode a base64 ID back to a filesystem path."""
    padded = encoded_id + "=" * (-len(encoded_id) % 4)
    return Path(base64.urlsafe_b64decode(padded).decode())


def _is_valid_skill_path(path):
    """Ensure path is under ~/.claude/{commands,skills}/ or <repo>/.claude/{commands,skills}/."""
    try:
        path.resolve()
    except (OSError, ValueError):
        return False
    # Use unresolved path so symlinks (e.g. .claude/skills -> ../.agents/skills) still match
    parts = path.parts
    for subdir in ("commands", "skills", "workflows"):
        global_dir = settings.CLAUDE_DIR / subdir
        if str(path).startswith(str(global_dir) + "/"):
            return True
    for i, part in enumerate(parts):
        if (
            part == ".claude"
            and i + 1 < len(parts)
            and parts[i + 1] in ("commands", "skills", "workflows")
        ):
            return True
    return False


def _discover_repos():
    """Return deduplicated repo paths from all known conversations."""
    from api.models import ConversationIndex

    repos = set(
        ConversationIndex.objects.exclude(project="")
        .values_list("project", flat=True)
        .distinct()
    )

    # Fall back to scanning files if the index is empty
    if not repos:
        projects_dir = settings.CLAUDE_DIR / "projects"
        if not projects_dir.is_dir():
            return []
        for project_dir in projects_dir.iterdir():
            if not project_dir.is_dir():
                continue
            for jsonl_file in project_dir.glob("*.jsonl"):
                entry = _ensure_index(jsonl_file, jsonl_file.stem, project_dir.name)
                if entry and entry.get("project"):
                    repos.add(entry["project"])

    return sorted(repos)


@api_view(["GET", "POST"])
def skills_list(request):
    if request.method == "POST":
        name = request.data.get("name", "").strip()
        scope = request.data.get("scope", "global")
        kind = request.data.get("kind", "command")
        content = request.data.get("content", "")

        if not name or not re.match(r"^[a-z0-9]+(-[a-z0-9]+)*$", name):
            return Response(
                {"error": "name must be kebab-case (e.g. my-skill)"}, status=400
            )

        if scope == "global":
            base_dir = settings.CLAUDE_DIR
        else:
            repo_path = Path(scope)
            if not repo_path.is_dir():
                return Response({"error": "invalid repo path"}, status=400)
            base_dir = repo_path / ".claude"

        if kind == "skill":
            skill_dir = base_dir / "skills" / name
            skill_dir.mkdir(parents=True, exist_ok=True)
            skill_file = skill_dir / "SKILL.md"
        else:
            commands_dir = base_dir / "commands"
            commands_dir.mkdir(parents=True, exist_ok=True)
            skill_file = commands_dir / f"{name}.md"

        if skill_file.exists():
            return Response({"error": "skill already exists"}, status=409)

        skill_file.write_text(content)
        sid = _path_id(skill_file)
        return Response(
            {
                "id": sid,
                "name": name,
                "path": str(skill_file),
                "scope": "global" if scope == "global" else scope,
                "kind": kind,
                "content": content,
                "modified": datetime.fromtimestamp(
                    skill_file.stat().st_mtime
                ).isoformat(),
            },
            status=201,
        )

    # GET: list all skills
    results = []

    def _scan_commands_dir(commands_dir, scope):
        if not commands_dir.is_dir():
            return
        for md_file in sorted(commands_dir.glob("*.md")):
            try:
                mtime = md_file.stat().st_mtime
            except OSError:
                continue
            results.append(
                {
                    "id": _path_id(md_file),
                    "name": md_file.stem,
                    "path": str(md_file),
                    "scope": scope,
                    "kind": "command",
                    "modified": datetime.fromtimestamp(mtime).isoformat(),
                }
            )

    def _scan_skills_dir(skills_dir, scope):
        if not skills_dir.is_dir():
            return
        for skill_md in sorted(skills_dir.glob("*/SKILL.md")):
            try:
                mtime = skill_md.stat().st_mtime
            except OSError:
                continue
            results.append(
                {
                    "id": _path_id(skill_md),
                    "name": skill_md.parent.name,
                    "path": str(skill_md),
                    "scope": scope,
                    "kind": "skill",
                    "modified": datetime.fromtimestamp(mtime).isoformat(),
                }
            )

    def _scan_workflows_dir(workflows_dir, scope):
        if not workflows_dir.is_dir():
            return
        for js_file in sorted(workflows_dir.glob("*.js")):
            try:
                mtime = js_file.stat().st_mtime
            except OSError:
                continue
            results.append(
                {
                    "id": _path_id(js_file),
                    "name": js_file.stem,
                    "path": str(js_file),
                    "scope": scope,
                    "kind": "workflow",
                    "modified": datetime.fromtimestamp(mtime).isoformat(),
                }
            )

    # Global
    _scan_commands_dir(settings.CLAUDE_DIR / "commands", "global")
    _scan_skills_dir(settings.CLAUDE_DIR / "skills", "global")
    _scan_workflows_dir(settings.CLAUDE_DIR / "workflows", "global")

    # Per-repo
    for repo in _discover_repos():
        _scan_commands_dir(Path(repo) / ".claude" / "commands", repo)
        _scan_skills_dir(Path(repo) / ".claude" / "skills", repo)

    results.sort(key=lambda x: x["name"])
    return Response(results)


@api_view(["GET", "PUT", "DELETE"])
def skill_detail(request, skill_id):
    path = _id_to_path(skill_id)
    if not _is_valid_skill_path(path) or not path.is_file():
        return Response({"error": "not found"}, status=404)

    if request.method == "DELETE":
        try:
            path.unlink()
            # Clean up empty skill directory for skills-type entries
            if path.name == "SKILL.md" and not any(path.parent.iterdir()):
                path.parent.rmdir()
        except OSError:
            return Response({"error": "failed to delete"}, status=500)
        return Response({"status": "deleted"})

    if request.method == "PUT":
        content = request.data.get("content", "")
        try:
            path.write_text(content)
        except OSError:
            return Response({"error": "failed to write"}, status=500)

    try:
        content = path.read_text()
        mtime = path.stat().st_mtime
    except OSError:
        return Response({"error": "failed to read"}, status=500)

    # Determine scope and kind (use unresolved path for symlink compat)
    scope = "global"
    kind = "command"
    kind_map = {"commands": "command", "skills": "skill", "workflows": "workflow"}
    for subdir in ("commands", "skills", "workflows"):
        global_dir = settings.CLAUDE_DIR / subdir
        if str(path).startswith(str(global_dir) + "/"):
            kind = kind_map[subdir]
            scope = "global"
            break
    else:
        parts = path.parts
        for i, part in enumerate(parts):
            if (
                part == ".claude"
                and i + 1 < len(parts)
                and parts[i + 1] in ("commands", "skills", "workflows")
            ):
                scope = str(Path(*parts[:i]))
                kind = kind_map.get(parts[i + 1], "command")
                break

    name = path.parent.name if kind == "skill" else path.stem

    return Response(
        {
            "id": skill_id,
            "name": name,
            "path": str(path),
            "scope": scope,
            "kind": kind,
            "content": content,
            "modified": datetime.fromtimestamp(mtime).isoformat(),
        }
    )


def _skill_summary(entries, start_idx):
    """Find the last assistant text line after a Skill tool_use."""
    last_text = ""
    for j in range(start_idx + 1, len(entries)):
        msg = entries[j].get("message", {})
        role = msg.get("role", "")
        content = msg.get("content", "")
        if role == "user" and isinstance(content, str) and content.strip():
            clean = re.sub(r"<[^>]+>[^<]*</[^>]+>", "", content).strip()
            if clean:
                break
        if role == "assistant" and isinstance(content, list):
            for bl in content:
                if not isinstance(bl, dict):
                    continue
                if bl.get("type") == "tool_use" and bl.get("name") == "Skill":
                    return last_text
                if bl.get("type") == "text" and bl.get("text", "").strip():
                    last_text = bl["text"].strip()
    return last_text


@api_view(["GET"])
def skill_invocations(request, skill_id):
    path = _id_to_path(skill_id)
    if not _is_valid_skill_path(path) or not path.is_file():
        return Response({"error": "not found"}, status=404)

    skill_name = path.stem
    projects_dir = settings.CLAUDE_DIR / "projects"
    if not projects_dir.is_dir():
        return Response([])

    invocations = []
    for project_dir in projects_dir.iterdir():
        if not project_dir.is_dir():
            continue
        for jsonl_file in project_dir.glob("*.jsonl"):
            conversation_id = jsonl_file.stem
            try:
                with open(jsonl_file) as f:
                    entries = [json.loads(line) for line in f]
            except (json.JSONDecodeError, OSError):
                continue

            cwd = ""
            for i, data in enumerate(entries):
                if not cwd:
                    cwd = data.get("cwd", "")
                msg = data.get("message", {})
                content = msg.get("content", [])
                if not isinstance(content, list):
                    continue
                for block in content:
                    if (
                        isinstance(block, dict)
                        and block.get("type") == "tool_use"
                        and block.get("name") == "Skill"
                        and isinstance(block.get("input"), dict)
                        and block["input"].get("skill") == skill_name
                    ):
                        summary = _skill_summary(entries, i)
                        last_line = summary.split("\n")[-1].strip() if summary else ""
                        invocations.append(
                            {
                                "timestamp": data.get("timestamp", ""),
                                "conversation_id": conversation_id,
                                "cwd": cwd,
                                "summary": last_line,
                            }
                        )

    invocations.sort(key=lambda x: x["timestamp"], reverse=True)
    return Response(invocations)


_project_dir_cwd_cache = {}


def _project_dir_to_cwd(project_dir):
    """Resolve a project dir name to its real filesystem path via JSONL cwd."""
    name = project_dir.name
    if name in _project_dir_cwd_cache:
        return _project_dir_cwd_cache[name]

    from api.models import ConversationIndex

    ci = (
        ConversationIndex.objects.filter(
            conversation_id__in=[f.stem for f in project_dir.glob("*.jsonl")]
        )
        .exclude(project="")
        .first()
    )
    if ci:
        _project_dir_cwd_cache[name] = ci.project
        return ci.project

    for jsonl_file in project_dir.glob("*.jsonl"):
        try:
            with open(jsonl_file) as f:
                for line in f:
                    cwd = json.loads(line).get("cwd", "")
                    if cwd:
                        _project_dir_cwd_cache[name] = cwd
                        return cwd
        except (json.JSONDecodeError, OSError):
            pass

    _project_dir_cwd_cache[name] = ""
    return ""


def _parse_memory_frontmatter(text):
    """Extract YAML frontmatter fields from a memory markdown file."""
    result = {"name": "", "description": "", "type": "", "originSessionId": ""}
    if not text.startswith("---"):
        return result
    end = text.find("\n---", 3)
    if end == -1:
        return result
    for line in text[3:end].splitlines():
        line = line.strip()
        for key in ("name", "description", "type", "originSessionId"):
            prefix = key + ":"
            if line.startswith(prefix):
                result[key] = line[len(prefix) :].strip().strip("\"'")
    return result


def _is_valid_memory_path(path):
    """Ensure path is under a memory/ dir within CLAUDE_DIR/projects/ or CLAUDE_DIR/memory/."""
    try:
        resolved = path.resolve()
    except (OSError, ValueError):
        return False
    global_memory = (settings.CLAUDE_DIR / "memory").resolve()
    if str(resolved).startswith(str(global_memory) + "/"):
        return True
    projects = (settings.CLAUDE_DIR / "projects").resolve()
    if not str(resolved).startswith(str(projects) + "/"):
        return False
    return "/memory/" in str(resolved)


def _scan_memory_dir(memory_dir, project_label):
    """Scan a memory directory and return a list of memory dicts."""
    results = []
    if not memory_dir.is_dir():
        return results
    for md_file in sorted(memory_dir.glob("*.md")):
        try:
            text = md_file.read_text()
            mtime = md_file.stat().st_mtime
        except OSError:
            continue
        fm = _parse_memory_frontmatter(text)
        is_index = md_file.name == "MEMORY.md"
        body = text
        if body.startswith("---"):
            end = body.find("\n---", 3)
            if end != -1:
                body = body[end + 4 :]
        entry = {
            "id": _path_id(md_file),
            "name": "Memory Index" if is_index else (fm["name"] or md_file.stem),
            "type": "index" if is_index else fm["type"],
            "description": fm["description"],
            "conversation_id": fm["originSessionId"],
            "project": project_label,
            "path": str(md_file),
            "modified": datetime.fromtimestamp(mtime).isoformat(),
        }
        if is_index:
            entry["empty"] = not body.strip()
        results.append(entry)
    return results


@api_view(["GET"])
def memories_list(request):
    results = []

    # Global memories (~/.claude/memory/)
    global_memory_dir = settings.CLAUDE_DIR / "memory"
    results.extend(_scan_memory_dir(global_memory_dir, "(global)"))

    # Per-project memories (~/.claude/projects/*/memory/)
    projects_dir = settings.CLAUDE_DIR / "projects"
    if projects_dir.is_dir():
        for project_dir in projects_dir.iterdir():
            if not project_dir.is_dir():
                continue
            memory_dir = project_dir / "memory"
            project_path = _project_dir_to_cwd(project_dir)
            results.extend(
                _scan_memory_dir(memory_dir, project_path or project_dir.name)
            )

    results.sort(key=lambda x: x["modified"], reverse=True)
    return Response(results)


@api_view(["GET", "PUT", "DELETE"])
def memory_detail(request, memory_id):
    path = _id_to_path(memory_id)
    if not _is_valid_memory_path(path) or not path.is_file():
        return Response({"error": "not found"}, status=404)

    if request.method == "DELETE":
        try:
            path.unlink()
        except OSError:
            return Response({"error": "failed to delete"}, status=500)
        return Response({"status": "deleted"})

    if request.method == "PUT":
        content = request.data.get("content", "")
        try:
            path.write_text(content)
        except OSError:
            return Response({"error": "failed to write"}, status=500)

    try:
        text = path.read_text()
        mtime = path.stat().st_mtime
    except OSError:
        return Response({"error": "failed to read"}, status=500)

    fm = _parse_memory_frontmatter(text)
    is_index = path.name == "MEMORY.md"

    global_memory = (settings.CLAUDE_DIR / "memory").resolve()
    if str(path.resolve()).startswith(str(global_memory) + "/"):
        project_label = "(global)"
    else:
        project_dir = path.parent.parent
        project_path = _project_dir_to_cwd(project_dir)
        project_label = project_path or project_dir.name

    return Response(
        {
            "id": memory_id,
            "name": "Memory Index" if is_index else (fm["name"] or path.stem),
            "type": "index" if is_index else fm["type"],
            "description": fm["description"],
            "conversation_id": fm["originSessionId"],
            "project": project_label,
            "content": text,
            "path": str(path),
            "modified": datetime.fromtimestamp(mtime).isoformat(),
        }
    )


@api_view(["GET"])
def stats(request):
    from django.db.models import Sum
    from django.db.models.functions import Substr

    from api.models import ConversationIndex

    qs = ConversationIndex.objects.exclude(first_timestamp="")

    repo = request.query_params.get("repo", "")
    if repo:
        qs = qs.filter(project=repo)

    rows = (
        qs.annotate(date=Substr("first_timestamp", 1, 10))
        .values("date")
        .annotate(count=Sum("message_count"))
        .order_by("date")
    )

    projects = sorted(
        ConversationIndex.objects.exclude(project="")
        .values_list("project", flat=True)
        .distinct()
    )

    return Response(
        {
            "days": [{"date": r["date"], "count": r["count"]} for r in rows],
            "projects": projects,
        }
    )


def _parse_conversation(jsonl_file, conversation_id, project_name):
    # If you change what gets extracted here, run `make reindex` to rebuild the cache.
    try:
        blurb = ""
        cwd = ""
        first_ts = ""
        last_ts = ""
        branch = ""
        msg_count = 0
        text_parts = []

        with open(jsonl_file) as f:
            for line in f:
                data = json.loads(line)
                ts = data.get("timestamp", "")
                if ts:
                    if not first_ts:
                        first_ts = ts
                    last_ts = ts
                if not cwd:
                    cwd = data.get("cwd", "")
                if not branch:
                    branch = data.get("gitBranch", "")

                msg = data.get("message", {})
                role = msg.get("role")
                if role not in ("user", "assistant"):
                    continue
                msg_count += 1

                content = msg.get("content", "")
                if isinstance(content, str) and content.strip():
                    if "<task-notification>" in content:
                        continue
                    cleaned = re.sub(r"<([\w-]+)>[^<]*</\1>", "", content).strip()
                    if not blurb and role == "user":
                        if cleaned:
                            blurb = cleaned[:200]
                        else:
                            # Skill/cronjob invocations: extract command name from XML tag
                            m = re.search(
                                r"<command-message>([\w-]+)</command-message>", content
                            )
                            if m:
                                blurb = f"/{m.group(1)}"
                    if not cleaned:
                        continue
                    text_parts.append(cleaned)
                elif isinstance(content, list):
                    for block in content:
                        if (
                            isinstance(block, dict)
                            and block.get("type") == "text"
                            and block.get("text", "").strip()
                        ):
                            text_parts.append(block["text"])

        if not blurb:
            return None

        return {
            "id": conversation_id,
            "project": cwd or project_name,
            "date": first_ts,
            "blurb": blurb,
            "branch": branch,
            "message_count": msg_count,
            "last_timestamp": last_ts,
            "searchable_text": "\n".join(text_parts),
        }
    except (json.JSONDecodeError, OSError):
        pass
    return None


def _ensure_index(jsonl_file, conversation_id, project_name):
    from api.models import ConversationIndex

    try:
        stat = jsonl_file.stat()
    except OSError:
        return None

    try:
        cached = ConversationIndex.objects.get(conversation_id=conversation_id)
        if cached.file_size == stat.st_size and cached.file_mtime == stat.st_mtime:
            return {
                "id": conversation_id,
                "project": cached.project,
                "date": cached.first_timestamp,
                "blurb": cached.blurb,
                "branch": cached.branch,
                "message_count": cached.message_count,
                "last_timestamp": cached.last_timestamp,
            }
    except ConversationIndex.DoesNotExist:
        pass

    parsed = _parse_conversation(jsonl_file, conversation_id, project_name)
    if not parsed:
        return None

    ConversationIndex.objects.update_or_create(
        conversation_id=conversation_id,
        defaults={
            "project": parsed["project"],
            "branch": parsed["branch"],
            "blurb": parsed["blurb"],
            "first_timestamp": parsed["date"],
            "last_timestamp": parsed["last_timestamp"],
            "message_count": parsed["message_count"],
            "searchable_text": parsed.get("searchable_text", ""),
            "file_size": stat.st_size,
            "file_mtime": stat.st_mtime,
        },
    )

    parsed.pop("searchable_text", None)
    return parsed
