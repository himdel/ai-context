import json
from pathlib import Path

from rest_framework.decorators import api_view
from rest_framework.response import Response


CLAUDE_DIR = Path.home() / ".claude"


@api_view(["GET"])
def index(request):
    return Response({"status": "ok"})


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
    try:
        with open(jsonl_file) as f:
            for line in f:
                data = json.loads(line)
                msg = data.get("message", {})
                role = msg.get("role")
                if role not in ("user", "assistant"):
                    continue

                content = msg.get("content", "")

                if role == "user":
                    if isinstance(content, list):
                        # tool_result messages, skip
                        continue
                    if not isinstance(content, str) or not content.strip():
                        continue
                    messages.append(
                        {
                            "role": "user",
                            "text": content,
                            "timestamp": data.get("timestamp", ""),
                        }
                    )

                elif role == "assistant":
                    if isinstance(content, list):
                        texts = [
                            block["text"]
                            for block in content
                            if isinstance(block, dict)
                            and block.get("type") == "text"
                            and block.get("text")
                        ]
                        if texts:
                            messages.append(
                                {
                                    "role": "assistant",
                                    "text": "\n\n".join(texts),
                                    "timestamp": data.get("timestamp", ""),
                                }
                            )
                    elif isinstance(content, str) and content.strip():
                        messages.append(
                            {
                                "role": "assistant",
                                "text": content,
                                "timestamp": data.get("timestamp", ""),
                            }
                        )
    except (json.JSONDecodeError, OSError):
        return Response({"error": "failed to read conversation"}, status=500)

    return Response({"id": conversation_id, "messages": messages})


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
