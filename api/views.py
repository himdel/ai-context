import base64
import json
import os
import re
import subprocess
from datetime import datetime
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


def _find_pr_for_branch(repo, branch):
    if not repo or not branch or branch in ("main", "master"):
        return None
    try:
        out = subprocess.check_output(
            [
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
            ],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        prs = json.loads(out)
        if prs:
            return prs[0]
    except (subprocess.CalledProcessError, FileNotFoundError, json.JSONDecodeError):
        pass
    return None


@api_view(["GET"])
def github_repo(request):
    path = request.query_params.get("path", "")
    branch = request.query_params.get("branch", "")
    if not path:
        return Response({"upstream": None, "origin": None, "pr": None})

    cache_key = f"{path}:{branch}"
    if cache_key in _github_repo_cache:
        return Response(_github_repo_cache[cache_key])

    upstream = _parse_github_remote(path, "upstream")
    origin = _parse_github_remote(path, "origin")
    pr = _find_pr_for_branch(upstream or origin, branch)

    result = {
        "upstream": upstream,
        "origin": origin,
        "pr": pr,
    }

    _github_repo_cache[cache_key] = result
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

    results.sort(key=lambda x: x["date"], reverse=True)
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

    # Load subagents
    subagents = _load_subagents(jsonl_file.parent / conversation_id / "subagents")

    # Match subagents to Agent tool_use blocks by timestamp proximity
    agent_tool_uses = {}  # tool_use_id -> timestamp
    for m in messages:
        for block in m.get("content", []):
            if block.get("type") == "tool_use" and block.get("name") == "Agent":
                agent_tool_uses[block.get("_id")] = m.get("timestamp", "")

    # For each tool_result of an Agent call, find the closest subagent by timestamp
    for m in messages:
        for block in m.get("content", []):
            if (
                block.get("type") == "tool_result"
                and block.get("name") == "Agent"
                and subagents
            ):
                tool_ts = agent_tool_uses.get(block.get("_tool_use_id"), "")
                best = _find_closest_subagent(subagents, tool_ts)
                if best:
                    block["subagent"] = best
                    subagents = [s for s in subagents if s is not best]

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


def _spawn_terminal(args, cwd):
    """Spawn a terminal running claude with the given args and cwd."""
    cmd = settings.TERMINAL_CMD + ["claude"] + args
    env = _clean_env()
    try:
        proc = subprocess.Popen(cmd, cwd=cwd, env=env, start_new_session=True)
        return Response({"status": "ok", "pid": proc.pid})
    except FileNotFoundError:
        return Response(
            {"error": "terminal emulator not found, check TERMINAL_CMD in settings"},
            status=500,
        )


@api_view(["POST"])
def terminal_run(request):
    """Spawn a terminal running an arbitrary command in a given cwd."""
    cmd = request.data.get("cmd", [])
    if not cmd or not isinstance(cmd, list):
        return Response({"error": "cmd must be a non-empty list"}, status=400)

    cwd = request.data.get("cwd", "")
    if not cwd or not Path(cwd).is_dir():
        return Response({"error": "cwd is not a valid directory"}, status=400)

    full_cmd = settings.TERMINAL_CMD + cmd
    env = _clean_env()
    try:
        proc = subprocess.Popen(full_cmd, cwd=cwd, env=env, start_new_session=True)
        return Response({"status": "ok", "pid": proc.pid})
    except FileNotFoundError:
        return Response({"error": "terminal emulator not found"}, status=500)


@api_view(["POST"])
def session_new(request):
    prompt = request.data.get("prompt", "").strip()

    cwd = request.data.get("cwd", "")
    if cwd:
        if not Path(cwd).is_dir():
            return Response({"error": "cwd is not a valid directory"}, status=400)
    else:
        cwd = str(Path.home())

    return _spawn_terminal([prompt] if prompt else [], cwd)


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

    return _spawn_terminal(["--resume", conversation_id], cwd)


def _build_plan_conversation_map():
    """Scan all JSONL files to map plan filenames to originating conversations."""
    plan_map = {}  # plan_stem -> {conversation_id, cwd, branch, timestamp}
    projects_dir = CLAUDE_DIR / "projects"
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
    plans_dir = CLAUDE_DIR / "plans"
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
    plan_file = CLAUDE_DIR / "plans" / f"{plan_id}.md"
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
    plan_file = CLAUDE_DIR / "plans" / f"{plan_id}.md"
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
    return _spawn_terminal([prompt], cwd)


def _skill_id(path):
    """Encode a filesystem path as a URL-safe base64 identifier."""
    return base64.urlsafe_b64encode(str(path).encode()).decode().rstrip("=")


def _skill_path(skill_id):
    """Decode a skill ID back to a filesystem path."""
    padded = skill_id + "=" * (-len(skill_id) % 4)
    return Path(base64.urlsafe_b64decode(padded).decode())


def _is_valid_skill_path(path):
    """Ensure path is under ~/.claude/commands/ or <repo>/.claude/commands/."""
    try:
        resolved = path.resolve()
    except (OSError, ValueError):
        return False
    global_commands = (CLAUDE_DIR / "commands").resolve()
    if str(resolved).startswith(str(global_commands) + "/"):
        return True
    # Allow any <dir>/.claude/commands/ path
    parts = resolved.parts
    for i, part in enumerate(parts):
        if part == ".claude" and i + 1 < len(parts) and parts[i + 1] == "commands":
            return True
    return False


def _discover_repos():
    """Scan ~/.claude/projects/*/ to find repo paths from JSONL first lines."""
    projects_dir = CLAUDE_DIR / "projects"
    if not projects_dir.is_dir():
        return []
    repos = set()
    for project_dir in projects_dir.iterdir():
        if not project_dir.is_dir():
            continue
        for jsonl_file in project_dir.glob("*.jsonl"):
            try:
                with open(jsonl_file) as f:
                    first_line = f.readline()
                    if first_line:
                        data = json.loads(first_line)
                        cwd = data.get("cwd", "")
                        if cwd:
                            repos.add(cwd)
            except (json.JSONDecodeError, OSError):
                continue
    return sorted(repos)


@api_view(["GET", "POST"])
def skills_list(request):
    if request.method == "POST":
        name = request.data.get("name", "").strip()
        scope = request.data.get("scope", "global")
        content = request.data.get("content", "")

        if not name or not re.match(r"^[a-z0-9]+(-[a-z0-9]+)*$", name):
            return Response(
                {"error": "name must be kebab-case (e.g. my-skill)"}, status=400
            )

        if scope == "global":
            commands_dir = CLAUDE_DIR / "commands"
        else:
            repo_path = Path(scope)
            if not repo_path.is_dir():
                return Response({"error": "invalid repo path"}, status=400)
            commands_dir = repo_path / ".claude" / "commands"

        commands_dir.mkdir(parents=True, exist_ok=True)
        skill_file = commands_dir / f"{name}.md"
        if skill_file.exists():
            return Response({"error": "skill already exists"}, status=409)

        skill_file.write_text(content)
        sid = _skill_id(skill_file)
        return Response(
            {
                "id": sid,
                "name": name,
                "path": str(skill_file),
                "scope": "global" if scope == "global" else scope,
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
                    "id": _skill_id(md_file),
                    "name": md_file.stem,
                    "path": str(md_file),
                    "scope": scope,
                    "modified": datetime.fromtimestamp(mtime).isoformat(),
                }
            )

    # Global skills
    _scan_commands_dir(CLAUDE_DIR / "commands", "global")

    # Per-repo skills
    for repo in _discover_repos():
        repo_commands = Path(repo) / ".claude" / "commands"
        _scan_commands_dir(repo_commands, repo)

    results.sort(key=lambda x: x["modified"], reverse=True)
    return Response(results)


@api_view(["GET", "PUT", "DELETE"])
def skill_detail(request, skill_id):
    path = _skill_path(skill_id)
    if not _is_valid_skill_path(path) or not path.is_file():
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
        content = path.read_text()
        mtime = path.stat().st_mtime
    except OSError:
        return Response({"error": "failed to read"}, status=500)

    # Determine scope
    global_commands = (CLAUDE_DIR / "commands").resolve()
    resolved = path.resolve()
    if str(resolved).startswith(str(global_commands) + "/"):
        scope = "global"
    else:
        # Find the repo root (parent of .claude/commands/)
        parts = resolved.parts
        scope = ""
        for i, part in enumerate(parts):
            if part == ".claude" and i + 1 < len(parts) and parts[i + 1] == "commands":
                scope = str(Path(*parts[:i]))
                break

    return Response(
        {
            "id": skill_id,
            "name": path.stem,
            "path": str(path),
            "scope": scope,
            "content": content,
            "modified": datetime.fromtimestamp(mtime).isoformat(),
        }
    )


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
