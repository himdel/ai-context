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
                results.append(entry)

    results.sort(key=lambda x: x["date"], reverse=True)
    return Response(results)


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
