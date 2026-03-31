import json
import re
import subprocess
from pathlib import Path

from django.conf import settings
from rest_framework.decorators import api_view
from rest_framework.response import Response


CLAUDE_DIR = Path.home() / ".claude"
_github_repo_cache = {}


@api_view(["GET"])
def index(request):
    return Response({"status": "ok"})


@api_view(["GET"])
def autolinks(request):
    return Response(
        [
            {"prefix": prefix, "separator": sep, "url": url}
            for prefix, sep, url in getattr(settings, "AUTOLINKS", [])
        ]
    )


@api_view(["GET"])
def github_repo(request):
    path = request.query_params.get("path", "")
    if not path:
        return Response({"repo": None})
    if path in _github_repo_cache:
        return Response({"repo": _github_repo_cache[path]})

    repo = None
    for remote in ("upstream", "origin"):
        try:
            url = subprocess.check_output(
                ["git", "-C", path, "remote", "get-url", remote],
                stderr=subprocess.DEVNULL,
                text=True,
            ).strip()
            m = re.match(
                r"(?:git@github\.com:|https://github\.com/)(.+?)(?:\.git)?$", url
            )
            if m:
                repo = m.group(1)
                break
        except (subprocess.CalledProcessError, FileNotFoundError):
            continue

    _github_repo_cache[path] = repo
    return Response({"repo": repo})


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

    results.sort(key=lambda x: x["date"], reverse=True)
    return Response(results)


@api_view(["GET"])
def conversation_detail(request, conversation_id):
    jsonl_file = _find_conversation(conversation_id)
    if not jsonl_file:
        return Response({"error": "not found"}, status=404)

    messages = []
    cwd = None
    tool_use_ids = {}  # id -> name, for labeling tool_results
    try:
        with open(jsonl_file) as f:
            for line in f:
                data = json.loads(line)
                if not cwd:
                    cwd = data.get("cwd", "")
                msg = data.get("message", {})
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

    return Response({"id": conversation_id, "cwd": cwd, "messages": messages})


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
        with open(jsonl_file) as f:
            for line in f:
                data = json.loads(line)
                msg = data.get("message", {})
                if msg.get("role") != "user":
                    continue
                content = msg.get("content", "")
                if isinstance(content, list):
                    # tool_result messages, skip
                    continue
                if not isinstance(content, str) or not content.strip():
                    continue

                return {
                    "id": conversation_id,
                    "project": data.get("cwd", project_name),
                    "date": data.get("timestamp", ""),
                    "blurb": content[:200],
                }
    except (json.JSONDecodeError, OSError):
        pass
    return None
