import json
import re
import subprocess
from pathlib import Path

from django.conf import settings
from rest_framework.decorators import api_view
from rest_framework.response import Response


CLAUDE_DIR = Path.home() / ".claude"
_github_repo_cache = {}


def _active_session_ids():
    """Return set of session IDs that have a running process."""
    ids = set()
    sessions_dir = CLAUDE_DIR / "sessions"
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


def _parse_github_remote(path, remote):
    try:
        url = subprocess.check_output(
            ["git", "-C", path, "remote", "get-url", remote],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        m = re.match(r"(?:git@github\.com:|https://github\.com/)(.+?)(?:\.git)?$", url)
        if m:
            return m.group(1)
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    return None


@api_view(["GET"])
def github_repo(request):
    path = request.query_params.get("path", "")
    if not path:
        return Response({"upstream": None, "origin": None})
    if path in _github_repo_cache:
        return Response(_github_repo_cache[path])

    result = {
        "upstream": _parse_github_remote(path, "upstream"),
        "origin": _parse_github_remote(path, "origin"),
    }

    _github_repo_cache[path] = result
    return Response(result)


@api_view(["GET"])
def conversations(request):
    projects_dir = CLAUDE_DIR / "projects"
    if not projects_dir.is_dir():
        return Response([])

    results = []
    for project_dir in projects_dir.iterdir():
        if not project_dir.is_dir():
            continue
        project_name = project_dir.name

        for jsonl_file in project_dir.glob("*.jsonl"):
            conversation_id = jsonl_file.stem
            entry = _parse_conversation(jsonl_file, conversation_id, project_name)
            if entry:
                entry["url"] = request.build_absolute_uri(
                    f"/api/conversations/{conversation_id}/"
                )
                results.append(entry)

    active_ids = _active_session_ids()
    for r in results:
        r["active"] = r["id"] in active_ids

    results.sort(key=lambda x: x["date"], reverse=True)
    return Response(results)


@api_view(["GET"])
def conversation_detail(request, conversation_id):
    jsonl_file = _find_conversation(conversation_id)
    if not jsonl_file:
        return Response({"error": "not found"}, status=404)

    messages = []
    cwd = None
    branch = None
    model = None
    version = None
    first_ts = None
    last_ts = None
    tool_use_ids = {}  # id -> name, for labeling tool_results
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
                                }
                            )
                    if blocks:
                        messages.append(
                            {"role": role, "content": blocks, "timestamp": timestamp}
                        )

    except (json.JSONDecodeError, OSError):
        return Response({"error": "failed to read conversation"}, status=500)

    msg_count = len(messages)
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
            "messages": messages,
        }
    )


def _find_conversation(conversation_id):
    projects_dir = CLAUDE_DIR / "projects"
    if not projects_dir.is_dir():
        return None
    for project_dir in projects_dir.iterdir():
        if not project_dir.is_dir():
            continue
        candidate = project_dir / f"{conversation_id}.jsonl"
        if candidate.is_file():
            return candidate
    return None


def _parse_conversation(jsonl_file, conversation_id, project_name):
    try:
        blurb = ""
        cwd = ""
        first_ts = ""
        last_ts = ""
        branch = ""
        msg_count = 0

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
                if role in ("user", "assistant"):
                    msg_count += 1

                if not blurb and role == "user":
                    content = msg.get("content", "")
                    if isinstance(content, str) and content.strip():
                        blurb = content[:200]

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
        }
    except (json.JSONDecodeError, OSError):
        pass
    return None
