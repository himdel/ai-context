import base64
import hashlib
import json
import logging
import mimetypes
import os
import re
import shlex
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from django.conf import settings
from django.http import FileResponse
from croniter import croniter
from rest_framework.decorators import api_view
from rest_framework.response import Response

from api import harness
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
    """Return set of session IDs that have a running process.

    Two sources, unioned: what each harness can tell about its own processes
    (Claude's session files; nothing at all from opencode), plus the tmux
    sessions we started ourselves. The second is what makes an opencode
    conversation ever show as live - see `_resolve_launched_sessions`.
    """
    ids = harness.active_ids()
    ids |= {r["conversation_id"] for r in _session_registry() if r["conversation_id"]}
    ids.discard("")
    return ids


@api_view(["GET"])
def index(request):
    instance = os.environ.get("CONTEXTS_INSTANCE", "")
    return Response(
        {
            "status": "ok",
            "instance": instance,
            "claude_dir": str(settings.CLAUDE_DIR),
        }
    )


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
        age = datetime.now(timezone.utc) - cached.cached_at
        if age.total_seconds() < 2 * 86400:
            if cached.number is None:
                return None
            return {
                "number": cached.number,
                "url": cached.url,
                "state": cached.state,
                "cached_at": cached.cached_at.isoformat(),
            }
        cached.delete()

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
        ForgePR.objects.update_or_create(
            repo=repo,
            branch=branch,
            defaults={
                "number": pr["number"],
                "url": pr["url"],
                "state": pr["state"],
            },
        )
        pr["cached_at"] = datetime.now(timezone.utc).isoformat()

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
    results = []
    for adapter in harness.enabled():
        try:
            refs = list(adapter.list_refs())
        except Exception:
            logger.exception("harness %s failed to list conversations", adapter.key)
            continue
        for ref in refs:
            entry = _ensure_index(adapter, ref)
            if entry:
                entry["url"] = request.build_absolute_uri(
                    f"/api/conversations/{ref.id}/"
                )
                results.append(entry)

    # Merge in DB-only entries (logs deleted but index remains)
    from api.models import ConversationIndex

    seen_ids = {r["id"] for r in results}
    for ci in ConversationIndex.objects.exclude(conversation_id__in=seen_ids):
        results.append(
            {
                "id": ci.conversation_id,
                "source": ci.source,
                "parent_id": ci.parent_id,
                "agent_type": ci.agent_type,
                "project": ci.project,
                "date": ci.first_timestamp,
                "blurb": ci.blurb,
                "branch": ci.branch,
                "message_count": ci.message_count,
                "last_timestamp": ci.last_timestamp,
                "cost_usd": ci.cost_usd,
                "input_tokens": ci.input_tokens,
                "output_tokens": ci.output_tokens,
                "cache_read_tokens": ci.cache_read_tokens,
                "cache_write_tokens": ci.cache_write_tokens,
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


@api_view(["GET"])
def conversation_detail(request, conversation_id):
    from api.models import ConversationIndex

    ci = ConversationIndex.objects.filter(conversation_id=conversation_id).first()
    conv = harness.load(conversation_id, ci.source if ci else "")

    if conv is None:
        # Indexed once, but the harness can no longer produce it - the log was
        # deleted. Serve what the index remembers rather than 404ing.
        if ci is None:
            return Response({"error": "not found"}, status=404)
        return Response(
            {
                "id": conversation_id,
                "source": ci.source,
                "parent_id": ci.parent_id,
                "agent_type": ci.agent_type,
                "cwd": ci.project,
                "branch": ci.branch,
                "model": "",
                "version": "",
                "message_count": ci.message_count,
                "first_timestamp": ci.first_timestamp,
                "last_timestamp": ci.last_timestamp,
                "active": False,
                "messages": [],
                "todos": [],
                "running_agents": [],
                "cost_usd": ci.cost_usd,
                "input_tokens": ci.input_tokens,
                "output_tokens": ci.output_tokens,
                "cache_read_tokens": ci.cache_read_tokens,
                "cache_write_tokens": ci.cache_write_tokens,
                **_usage_with_descendants(conversation_id, _cached_summary(ci)),
                "can_launch": harness.can_launch(ci.source),
                "file_missing": True,
            }
        )

    data = conv.detail()
    data["active"] = conversation_id in _active_session_ids()
    # Whether the session buttons do anything, rather than the UI inferring it
    # from a source name it would have to keep a list of.
    data["can_launch"] = harness.can_launch(conv.source)
    data.update(_usage_with_descendants(conv.id, conv.usage()))
    return Response(data)


_USAGE_FIELDS = (
    "cost_usd",
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
)


def _usage_with_descendants(conversation_id, own):
    """Own usage plus every subagent underneath, as `<field>_total` keys.

    Index rows carry own usage only, so `stats` can sum them all without
    double-counting. The rollup a reader expects to see on one conversation is
    rebuilt here by walking the parent_id tree, which also handles subagents
    that spawned subagents.

    This reads the index rather than the loaded transcript, so a subagent that
    appeared since the last conversation-list refresh is not counted yet. It
    corrects itself on the next refresh.
    """
    from api.models import ConversationIndex

    totals = {k: own.get(k, 0) for k in _USAGE_FIELDS}
    frontier = [conversation_id]
    seen = {conversation_id}
    while frontier:
        rows = ConversationIndex.objects.filter(parent_id__in=frontier).values(
            "conversation_id", *_USAGE_FIELDS
        )
        frontier = []
        for row in rows:
            cid = row["conversation_id"]
            if cid in seen:
                continue
            seen.add(cid)
            frontier.append(cid)
            for k in _USAGE_FIELDS:
                totals[k] += row[k] or 0
    totals["cost_usd"] = round(totals["cost_usd"], 6)
    return {f"{k}_total": v for k, v in totals.items()}


def _find_conversation(conversation_id):
    """Path to a Claude transcript. Claude-only: used by cron skill pairing."""
    path, _ = harness.claude_adapter()._find_file(conversation_id)
    return path


def _clean_env():
    """Return os.environ without virtualenv/Claude-child pollution."""
    strip = {
        "VIRTUAL_ENV",
        "DJANGO_SETTINGS_MODULE",
        # Prevent spawned Claude from thinking it's a child/subagent session —
        # without this it skips creating session files and conversation logs.
        "CLAUDE_CODE_CHILD_SESSION",
        "CLAUDE_CODE_SESSION_ID",
        "CLAUDE_CODE_ENTRYPOINT",
        "CLAUDECODE",
        "AI_AGENT",
    }
    env = {k: v for k, v in os.environ.items() if k not in strip}
    # Strip the venv bin dir from PATH
    venv = os.environ.get("VIRTUAL_ENV")
    if venv and "PATH" in env:
        venv_bin = os.path.join(venv, "bin")
        env["PATH"] = os.pathsep.join(
            p for p in env["PATH"].split(os.pathsep) if p != venv_bin
        )
    return env


def _tmux(*args, env=None):
    """Run a tmux command. Return (returncode, stdout). Never raises."""
    try:
        p = subprocess.run(["tmux", *args], capture_output=True, text=True, env=env)
        return p.returncode, p.stdout
    except FileNotFoundError:
        return 127, ""


def _tmux_sessions():
    """Return {session_name: pane_pid} for all live tmux sessions."""
    rc, out = _tmux("list-panes", "-a", "-F", "#{session_name} #{pane_pid}")
    result = {}
    if rc != 0:
        return result
    for line in out.splitlines():
        name, _, pid = line.partition(" ")
        pid = pid.strip()
        # First pane seen for a session runs the session's main process.
        if name and pid.isdigit() and name not in result:
            result[name] = int(pid)
    return result


def _tmux_session_details():
    """Return {session_name: (start_dir, created_unixtime)}.

    Separate from `_tmux_sessions` because only session adoption needs it, and
    that runs far less often than the pid lookup does.
    """
    rc, out = _tmux(
        "list-sessions", "-F", "#{session_name}\t#{session_path}\t#{session_created}"
    )
    result = {}
    if rc != 0:
        return result
    for line in out.splitlines():
        name, _, rest = line.partition("\t")
        path, _, created = rest.partition("\t")
        if name and path:
            result[name] = (path, int(created) if created.isdigit() else 0)
    return result


def _tmux_send(name, text, submit=True):
    """Type ``text`` into a tmux session, optionally submitting with Enter."""
    rc, _ = _tmux("send-keys", "-t", name, "-l", "--", text)
    if rc != 0:
        return False
    if submit:
        _tmux("send-keys", "-t", name, "Enter")
    return True


def _capture_pane(name):
    """Return the visible text of a tmux session's pane."""
    rc, out = _tmux("capture-pane", "-p", "-t", name)
    return out if rc == 0 else ""


_OPTION_RE = re.compile(r"^[\s│|>❯»*]*(\d+)[.)]\s+(.+?)\s*$")


def _parse_prompt(text):
    """Best-effort parse of a Claude prompt box into {question, options}.

    Version-sensitive (reads the TUI); returns None when no numbered options
    are visible. Options let the UI answer via send-keys.
    """
    lines = text.splitlines()
    options = []
    first_idx = None
    for i, line in enumerate(lines):
        m = _OPTION_RE.match(line)
        if m:
            if first_idx is None:
                first_idx = i
            options.append({"key": m.group(1), "label": m.group(2).strip()})
    if not options:
        return None
    # Question: the text lines above the options, up to a box border or a few
    # lines back (blank lines within the box are skipped).
    block = []
    for line in reversed(lines[:first_idx]):
        if re.search(r"[─—]{3,}", line):
            break
        clean = re.sub(r"[─—_]{2,}", "", line).strip("│|╭╮╰╯ ").strip()
        if clean:
            block.append(clean)
        if len(block) >= 6:
            break
    question = " ".join(reversed(block))
    return {"question": question, "options": options}


# The selection cursor (❯) sits directly on the highlighted option row, e.g.
# " ❯ 1. Yes". Note ❯ is also the normal input-prompt marker ("❯ some text"),
# so it only signals a live prompt when it lands on a numbered option line.
_ACTIVE_OPTION_RE = re.compile(r"^[\s│|]*[❯➤▶►▸]\s*\d+[.)]\s")


def _prompt_is_active(text):
    """True if a selection prompt is awaiting input, not just a numbered list.

    Requires the TUI selection cursor to sit on an option row, so neither a
    plain numbered list in Claude's output nor the ordinary input prompt counts.
    """
    return any(_ACTIVE_OPTION_RE.match(ln) for ln in text.splitlines())


def _session_files():
    """Return {pid: session-file-dict} for all Claude session files."""
    result = {}
    sessions_dir = settings.CLAUDE_DIR / "sessions"
    if not sessions_dir.is_dir():
        return result
    for f in sessions_dir.glob("*.json"):
        try:
            data = json.loads(f.read_text())
            if data.get("pid"):
                result[data["pid"]] = data
        except (json.JSONDecodeError, OSError):
            pass
    return result


def _record_launch(name, source, cwd, conversation_id="", started_at=None):
    """Remember that we started `name`, so its conversation stays knowable."""
    from api.models import LaunchedSession

    defaults = {
        "source": source,
        "cwd": os.path.abspath(cwd),
        "conversation_id": conversation_id,
    }
    if started_at is not None:
        defaults["started_at"] = started_at
    try:
        LaunchedSession.objects.update_or_create(tmux_session=name, defaults=defaults)
    except Exception:
        logger.exception("could not record launch of %s", name)


def _source_from_session_name(name):
    """The harness a `ctx-...` tmux session belongs to, or "" if not one of ours.

    Reads back what `_tmux_session_name` writes: `<prefix>-<dir>-<hash>`, then
    the harness key for everything but Claude, then a numeric suffix when the
    name was already taken. Claude is the default precisely because its own
    sessions carry no key - both ours and the ones its shell wrapper starts.
    """
    prefix = f"{settings.TMUX_SESSION_PREFIX}-"
    if not name.startswith(prefix):
        return ""
    parts = name[len(prefix) :].split("-")
    if parts and parts[-1].isdigit():
        parts.pop()
    if len(parts) < 2:
        return ""
    return parts[-1] if harness.get(parts[-1]) is not None else "claude"


def _adopt_tmux_sessions(live):
    """Record `ctx-` tmux sessions we did not start, so they count as live.

    A session started from a shell wrapper (`~/bin/claude`, `~/bin/opencode`)
    names itself the way we do, which is the whole point: adopting it here
    means a terminal-started session is paired to its conversation by exactly
    the same path as one launched from the UI. Claude does not need this - its
    own session file names its conversation - but it costs nothing and covers
    the gap before that file is written.
    """
    from api.models import LaunchedSession

    try:
        known = set(LaunchedSession.objects.values_list("tmux_session", flat=True))
    except Exception:
        logger.exception("could not read launched sessions")
        return
    unknown = [n for n in live if n not in known and _source_from_session_name(n)]
    if not unknown:
        return
    details = _tmux_session_details()
    for name in unknown:
        path, created = details.get(name, ("", 0))
        if not path or not created:
            # Without a real start time `identify` would be free to match any
            # session ever created in that directory. Rather not guess.
            continue
        started = datetime.fromtimestamp(created, timezone.utc)
        logger.info("adopting tmux session %s (%s)", name, path)
        _record_launch(name, _source_from_session_name(name), path, started_at=started)


def _resolve_launched_sessions(live):
    """Pair our launches to conversations, and forget the dead ones.

    Returns {tmux_session: row} for live sessions we know about. A launch we
    handed a session id to is already paired; the rest - a new session, a fork,
    or an adopted one, where the harness picks the id - are asked about on every
    call until the harness has one to give, which for opencode is the moment the
    first message lands.
    """
    from api.models import LaunchedSession

    _adopt_tmux_sessions(live)
    try:
        rows = list(LaunchedSession.objects.all())
    except Exception:
        logger.exception("could not read launched sessions")
        return {}

    paired = {}
    dead = []
    # Two sessions in one directory must not resolve to the same conversation:
    # the first to claim an id keeps it, and the other stays unpaired rather
    # than showing the wrong transcript.
    claimed = {r.conversation_id for r in rows if r.conversation_id}
    for row in rows:
        if row.tmux_session not in live:
            dead.append(row.pk)
            continue
        if not row.conversation_id:
            adapter = harness.get(row.source)
            if adapter is not None:
                try:
                    found = adapter.identify(row.cwd, row.started_at.timestamp() * 1000)
                except Exception:
                    logger.exception("harness %s failed identify()", row.source)
                    found = ""
                if found and found not in claimed:
                    row.conversation_id = found
                    row.save(update_fields=["conversation_id"])
                    claimed.add(found)
        paired[row.tmux_session] = row
    if dead:
        LaunchedSession.objects.filter(pk__in=dead).delete()
    return paired


def _session_registry():
    """Merge live tmux sessions with per-harness session state into UI records.

    Claude's own session file wins where there is one - it is written by the
    process itself and survives a restart of this app. Our launch records cover
    everything else, and the gap before Claude writes its file.
    """
    if not settings.USE_TMUX:
        return []
    files = _session_files()
    live = _tmux_sessions()
    try:
        launched = _resolve_launched_sessions(live)
    except Exception:
        logger.exception("launch pairing error")
        launched = {}
    records = []
    for name, pid in sorted(live.items()):
        data = files.get(pid, {})
        row = launched.get(name)
        records.append(
            {
                "session": name,
                "pid": pid,
                "conversation_id": data.get("sessionId", "")
                or (row.conversation_id if row else ""),
                "cwd": data.get("cwd", "") or (row.cwd if row else ""),
                "source": row.source if row else "claude",
                "status": data.get("status", ""),
                "waiting_for": data.get("waitingFor", ""),
                "claude_name": data.get("name", ""),
            }
        )
    return records


def _tmux_session_name(cwd, mode="singleton", source="claude"):
    """Derive a tmux session name from a context path.

    ``singleton`` returns the stable per-context name; ``new`` appends the
    lowest free numeric suffix so a fresh session never collides.

    The harness key is part of the name for everything but Claude. Without it
    an opencode launch in a directory that already has a live Claude session
    would look ``reused`` and its prompt would be typed into Claude. Claude
    keeps the bare name so existing sessions stay addressable.

    **Session-name registry on this box** (2026-09-11): ``ctx-`` is ours - both
    what we launch and what ``~/bin/claude`` / ``~/bin/opencode`` start, which
    is what makes adoption work. ``panel-<id>`` belongs to controlpanel, which
    now runs its dev services in tmux too; those are services, not
    conversations, and ``_source_from_session_name`` ignores them because they
    do not carry our prefix. Keep it that way.
    """
    cwd = os.path.abspath(cwd)
    base = os.path.basename(cwd.rstrip("/")) or "root"
    base = re.sub(r"[^a-zA-Z0-9]+", "-", base).strip("-").lower() or "ctx"
    short = hashlib.sha1(cwd.encode()).hexdigest()[:4]
    name = f"{settings.TMUX_SESSION_PREFIX}-{base}-{short}"
    if source and source != "claude":
        name = f"{name}-{source}"
    if mode != "new":
        return name
    live = _tmux_sessions()
    if name not in live:
        return name
    n = 2
    while f"{name}-{n}" in live:
        n += 1
    return f"{name}-{n}"


def _viewer_argv(inner):
    """Build the argv that runs ``inner`` (a list) in a new terminal window."""
    if settings.TERMINAL_KIND == "mac":
        app = settings.TERMINAL_APP or "Terminal"
        script = " ".join(shlex.quote(a) for a in inner)
        if app == "iTerm":
            # iTerm2 dropped Terminal's `do script` terminology; drive its own
            # scripting API to open a window and run the command instead.
            applescript = (
                'tell application "iTerm" to tell '
                "(create window with default profile) to tell current session "
                f'to write text "{script}"'
            )
        else:
            applescript = f'tell application "{app}" to do script "{script}"'
        return ["osascript", "-e", applescript]
    prefix = settings.TERMINAL_CMD
    if not prefix:
        return None
    if settings.TERMINAL_ESCAPE_DOLLARS:
        # This terminal expands `$VAR` itself before the child sees the argv;
        # `$$` is its escape. See capabilities.TERMINAL_EXPANDS_VARS.
        inner = [a.replace("$", "$$") for a in inner]
    return [*prefix, *inner]


def _open_viewer(inner, env):
    """Pop a terminal window running ``inner``. Return True on success."""
    argv = _viewer_argv(inner)
    if not argv:
        logger.warning("no terminal emulator configured; skipping viewer")
        return False
    venv = dict(env)
    if settings.TERMINAL_KIND != "mac" and settings.TERMINAL_DISPLAY:
        venv["DISPLAY"] = settings.TERMINAL_DISPLAY
    try:
        subprocess.Popen(argv, env=venv, start_new_session=True)
        return True
    except (FileNotFoundError, OSError):
        logger.warning("viewer launch failed: %s", argv)
        return False


def _notify_session(name, summary, body):
    """Best-effort desktop notification whose action opens the session viewer."""
    notifier = settings.NOTIFIER
    if not notifier:
        return
    env = _clean_env()
    if settings.TERMINAL_KIND != "mac" and settings.TERMINAL_DISPLAY:
        env["DISPLAY"] = settings.TERMINAL_DISPLAY
    try:
        if notifier == "notify-send":
            viewer = _viewer_argv(["tmux", "attach", "-t", name])
            script = (
                f"act=$(notify-send --wait --action=open=Open "
                f"{shlex.quote(summary)} {shlex.quote(body)}); "
                f'[ "$act" = open ]'
            )
            if viewer:
                script += " && exec " + " ".join(shlex.quote(a) for a in viewer)
            subprocess.Popen(["sh", "-c", script], env=env, start_new_session=True)
        elif notifier == "osascript":
            subprocess.Popen(
                [
                    "osascript",
                    "-e",
                    f"display notification {json.dumps(body)} "
                    f"with title {json.dumps(summary)}",
                ],
                env=env,
                start_new_session=True,
            )
    except (OSError, FileNotFoundError):
        logger.warning("notification failed for session %s", name)


def _spawn_terminal(cmd, cwd):
    """Spawn a command directly in a terminal window (no tmux)."""
    argv = _viewer_argv(cmd)
    if not argv:
        return Response({"error": "no terminal emulator available"}, status=500)
    env = _clean_env()
    if settings.TERMINAL_KIND != "mac" and settings.TERMINAL_DISPLAY:
        env["DISPLAY"] = settings.TERMINAL_DISPLAY
    try:
        proc = subprocess.Popen(argv, cwd=cwd, env=env, start_new_session=True)
        logger.info("spawned %s, pid %d", argv, proc.pid)
        return Response({"status": "ok", "pid": proc.pid})
    except FileNotFoundError:
        return Response({"error": "terminal emulator not found"}, status=500)


# Per-user install dirs to check when a command is not on PATH. An agent
# installed by its own one-line installer lands in one of these, and neither a
# desktop-launched dev server nor a long-lived tmux server necessarily has them.
_EXTRA_BIN_DIRS = (".opencode/bin", ".local/bin", "bin")


def _resolve_cmd(cmd):
    """Absolutize argv[0], or return None when the binary cannot be found.

    Two different stale environments make this necessary. A tmux server keeps
    whatever PATH it was started with - possibly weeks ago - so handing it a
    bare name is a coin flip. And this server's own PATH depends on how it was
    launched; the one running here came up from a node toolchain and has no
    ~/.opencode/bin either. So: our PATH first, then the usual install dirs.
    """
    if not cmd:
        return None
    found = shutil.which(cmd[0])
    if not found and not os.path.isabs(cmd[0]):
        for d in _EXTRA_BIN_DIRS:
            candidate = Path.home() / d / cmd[0]
            if os.access(candidate, os.X_OK):
                found = str(candidate)
                break
    if not found:
        return None
    return [found, *cmd[1:]]


def _spawn_session(
    cmd, cwd, *, mode="new", source="claude", view=None, prompt=None, conversation_id=""
):
    """Launch a coding-agent session, preferring a headless tmux session with
    an optional attached viewer terminal. Falls back to a plain terminal spawn
    when tmux is unavailable.

    ``mode`` defaults to ``new``: a new session means a new session. The
    ``singleton`` mode - reuse the live session for this directory, delivering
    ``prompt`` to it via send-keys - is only right for a caller that explicitly
    wants one conversation per repo, and nothing does today.

    Returns a DRF Response with {status, pid, session, reused, attached}.
    """
    wanted = cmd[0] if cmd else ""
    cmd = _resolve_cmd(cmd)
    if cmd is None:
        logger.error("%r not found on PATH", wanted)
        return Response(
            {"error": f"{wanted} not found - set its *_CMD to an absolute path"},
            status=500,
        )
    if not settings.USE_TMUX:
        return _spawn_terminal(cmd, cwd)

    name = _tmux_session_name(cwd, mode, source)
    env = _clean_env()
    reused = name in _tmux_sessions()
    if reused:
        if prompt:
            _tmux_send(name, prompt)
            logger.info("sent prompt to live tmux session %s", name)
        else:
            logger.info("reusing live tmux session %s", name)
    else:
        # `env=env` reaches the tmux *client*, and a new session gets the tmux
        # *server's* environment - only tmux's `update-environment` list crosses
        # over from us. That server can be days old and carry the environment of
        # whatever started it, so nothing here can be relied on to arrive; it is
        # why the shell wrappers source their keys file *inside* the command.
        rc, out = _tmux("new-session", "-d", "-s", name, "-c", cwd, "--", *cmd, env=env)
        if rc != 0:
            logger.error("tmux new-session failed (%d): %s", rc, out)
            return Response({"error": "tmux failed to start session"}, status=500)
        logger.info("started tmux session %s: %s", name, cmd)
        # tmux reports success for a command that starts and immediately dies -
        # the pane goes with it, so an unlaunchable agent used to come back as
        # {"status": "ok", "pid": null} and look like it worked. Whatever the
        # process managed to print is the only diagnosis available, so say it.
        if name not in _tmux_sessions():
            out = out.strip() or "the command exited immediately"
            logger.error("session %s died on startup: %s", name, out)
            return Response({"error": f"session did not start: {out}"}, status=500)
        _record_launch(name, source, cwd, conversation_id)

    want_view = settings.TERMINAL_VIEWER if view is None else view
    attached = _open_viewer(["tmux", "attach", "-t", name], env) if want_view else False

    pid = _tmux_sessions().get(name)
    return Response(
        {
            "status": "ok",
            "session": name,
            "pid": pid,
            "reused": reused,
            "attached": attached,
        }
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

    return _spawn_terminal(cmd, cwd)


@api_view(["POST"])
def session_new(request):
    prompt = request.data.get("prompt", "").strip()
    source = request.data.get("source", "").strip() or "claude"

    cwd = request.data.get("cwd", "")
    if cwd:
        if not Path(cwd).is_dir():
            return Response({"error": "cwd is not a valid directory"}, status=400)
    else:
        cwd = str(Path.home())

    argv = harness.launch_argv(source, prompt=prompt)
    if argv is None:
        return Response({"error": f"{source} cannot be launched"}, status=400)
    return _spawn_session(argv, cwd, source=source)


def _resume_target(request):
    """(adapter, conversation_id, cwd) for a resume/fork, or an error Response."""
    from api.models import ConversationIndex

    conversation_id = request.data.get("conversation_id", "").strip()
    if not conversation_id:
        return Response({"error": "conversation_id is required"}, status=400)

    ci = ConversationIndex.objects.filter(conversation_id=conversation_id).first()
    adapter = harness.owner_of(conversation_id, ci.source if ci else "")
    if adapter is None:
        return Response({"error": "conversation not found"}, status=404)

    cwd = request.data.get("cwd", "") or (ci.project if ci else "")
    if not cwd or not Path(cwd).is_dir():
        cwd = str(Path.home())
    return adapter, conversation_id, cwd


@api_view(["POST"])
def session_resume(request):
    target = _resume_target(request)
    if isinstance(target, Response):
        return target
    adapter, conversation_id, cwd = target

    if conversation_id in _active_session_ids():
        return Response({"error": "session is already active"}, status=409)

    argv = harness.launch_argv(adapter.key, conversation_id=conversation_id)
    if argv is None:
        return Response({"error": f"{adapter.key} cannot be launched"}, status=400)
    return _spawn_session(
        argv, cwd, source=adapter.key, conversation_id=conversation_id
    )


@api_view(["POST"])
def session_fork(request):
    target = _resume_target(request)
    if isinstance(target, Response):
        return target
    adapter, conversation_id, cwd = target

    argv = harness.launch_argv(adapter.key, conversation_id=conversation_id, fork=True)
    if argv is None:
        return Response({"error": f"{adapter.key} cannot be launched"}, status=400)
    # No conversation_id on the launch: a fork works in a *new* conversation
    # whose id only the harness knows, so it gets resolved like a fresh one.
    return _spawn_session(argv, cwd, source=adapter.key)


@api_view(["GET"])
def sessions_list(request):
    """List live tmux-backed Claude sessions, merged with session-file state.

    Doubles as the fast path for cron run pairing: this endpoint is polled every
    few seconds while a tab is open, so resolving here links a run within seconds
    of Claude writing its session file. Best-effort - never break the listing.
    """
    try:
        _resolve_all_unresolved_runs()
    except Exception:
        logger.exception("cron pairing error")
    return Response(_session_registry())


def _resolve_session_name(request):
    """Resolve a session name from a request body: explicit name or cwd."""
    name = request.data.get("session", "").strip()
    if name:
        return name
    cwd = request.data.get("cwd", "").strip()
    if cwd:
        return _tmux_session_name(cwd)
    return ""


@api_view(["POST"])
def session_send(request):
    """Queue a prompt into a live session via tmux send-keys."""
    if not settings.USE_TMUX:
        return Response({"error": "tmux is not enabled"}, status=400)

    name = _resolve_session_name(request)
    if not name:
        return Response({"error": "session or cwd is required"}, status=400)

    text = request.data.get("text", "")
    if not text.strip():
        return Response({"error": "text is required"}, status=400)

    if name not in _tmux_sessions():
        return Response({"error": "session is not live"}, status=404)

    submit = request.data.get("submit", True)
    answer = request.data.get("answer", False)

    # Reconcile against the live pane at send time: the client's view can be a
    # few seconds stale, so a free-text prompt must not land on (and Enter
    # through) a selection box, and an option answer must still match the
    # prompt it was rendered from. This closes the window to the send instant
    # rather than the last poll.
    pane = _capture_pane(name)
    if answer:
        prompt = _parse_prompt(pane) if _prompt_is_active(pane) else None
        expect_key = str(request.data.get("expect_key", "")).strip()
        expect_label = str(request.data.get("expect_label", "")).strip()
        current = None
        for o in (prompt or {}).get("options", []):
            if o["key"] == expect_key:
                current = o
                break
        if not current or (expect_label and current["label"] != expect_label):
            return Response({"error": "prompt changed", "prompt": prompt}, status=409)
    elif _prompt_is_active(pane):
        # A selection prompt is on screen; typing free text would corrupt it
        # and the trailing Enter would confirm its default option.
        return Response(
            {"error": "session is waiting on a prompt", "prompt": _parse_prompt(pane)},
            status=409,
        )

    if not _tmux_send(name, text, submit=submit):
        return Response({"error": "failed to send keys"}, status=500)
    return Response({"status": "ok", "session": name})


@api_view(["POST"])
def session_attach(request):
    """Pop a terminal viewer attached to a live session."""
    if not settings.USE_TMUX:
        return Response({"error": "tmux is not enabled"}, status=400)

    name = _resolve_session_name(request)
    if not name:
        return Response({"error": "session or cwd is required"}, status=400)
    if name not in _tmux_sessions():
        return Response({"error": "session is not live"}, status=404)

    attached = _open_viewer(["tmux", "attach", "-t", name], _clean_env())
    if not attached:
        return Response({"error": "no viewer available"}, status=500)
    return Response({"status": "ok", "session": name, "attached": True})


@api_view(["GET"])
def session_capture(request):
    """Return a live session's pane text plus any parsed prompt options."""
    if not settings.USE_TMUX:
        return Response({"error": "tmux is not enabled"}, status=400)

    name = request.GET.get("session", "").strip()
    if not name:
        cwd = request.GET.get("cwd", "").strip()
        if cwd:
            name = _tmux_session_name(cwd)
    if not name:
        return Response({"error": "session or cwd is required"}, status=400)
    if name not in _tmux_sessions():
        return Response({"error": "session is not live"}, status=404)

    text = _capture_pane(name)
    # Only surface a prompt when a selection is actually awaiting input; a
    # numbered list in Claude's output must not render as answer buttons.
    prompt = _parse_prompt(text) if _prompt_is_active(text) else None
    return Response({"session": name, "text": text, "prompt": prompt})


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


def _jsonl_first_timestamp(jsonl_file):
    """Return the first timestamp (ms epoch) from a JSONL conversation file.

    The file opens with a few metadata lines (mode, permission-mode,
    file-history-snapshot) that carry no timestamp, so scan past them to the
    first timestamped entry rather than giving up on line one.
    """
    try:
        with open(jsonl_file) as f:
            for line in f:
                try:
                    ts = json.loads(line).get("timestamp", "")
                except json.JSONDecodeError:
                    continue
                if ts:
                    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    return dt.timestamp() * 1000
    except (OSError, ValueError):
        pass
    return 0


def _resolve_run_conversations(runs):
    sessions_dir = settings.CLAUDE_DIR / "sessions"
    unresolved = [
        r for r in runs if (r.pid or r.tmux_session) and not r.conversation_id
    ]
    if not unresolved:
        return

    sessions = []
    if sessions_dir.is_dir():
        for f in sessions_dir.glob("*.json"):
            try:
                data = json.loads(f.read_text())
                sessions.append(data)
            except (json.JSONDecodeError, OSError):
                pass

    # Full session-file lookup keyed by the claude pane_pid.
    pid_to_data = {s.get("pid"): s for s in sessions}

    # Conversations already claimed by a run, so no two runs ever collapse onto
    # one conversation (whether via the deterministic or heuristic tiers).
    used_ids = set(
        CronJobRun.objects.exclude(conversation_id="").values_list(
            "conversation_id", flat=True
        )
    )

    for run in unresolved:
        session_id = ""
        repo = run.cronjob.repo if run.cronjob_id else ""
        skill = run.cronjob.skill_name if run.cronjob_id else ""
        run_ts = run.triggered_at.timestamp() * 1000

        # Deterministic pairing: the pane_pid we recorded at spawn keys Claude's
        # session file directly (the pane runs claude with no shell wrapper, so
        # pane_pid == claude pid == <pid>.json). We deliberately do NOT map the
        # tmux session *name* -> current pane_pid: names are reused across cron
        # runs, so a stale run would grab whatever session now holds its name.
        # The cwd guard stops a recycled pid from masquerading as our run.
        data = pid_to_data.get(run.pid)
        if data:
            sid = data.get("sessionId", "")
            if sid and sid not in used_ids and (not repo or data.get("cwd") == repo):
                session_id = sid

        if not session_id:
            # Session file present but not under our pid: match live files by
            # cwd + startedAt (close to the trigger) + skill.
            for s in sessions:
                sid = s.get("sessionId", "")
                if not sid or sid in used_ids:
                    continue
                if (
                    s.get("cwd", "") == repo
                    and abs(s.get("startedAt", 0) - run_ts) < 10_000
                    and (not skill or _conversation_skill(sid) == skill)
                ):
                    session_id = sid
                    break

        if not session_id:
            # Session files are ephemeral — fall back to scanning persisted
            # JSONL conversation files by timestamp + skill match. This is the
            # backfill path for old runs whose tmux session is long gone. A
            # trust prompt can delay Claude's first message well past the run
            # trigger, so the window is generous; the skill match keeps it
            # precise, and we pick the closest conversation that started at or
            # after the trigger, skipping ids already claimed by another run.
            if repo:
                project_dir_name = repo.replace("/", "-").lstrip("-")
                project_dir = settings.CLAUDE_DIR / "projects" / f"-{project_dir_name}"
                if project_dir.is_dir():
                    best_delta = None
                    for jsonl_file in project_dir.glob("*.jsonl"):
                        cid = jsonl_file.stem
                        if cid in used_ids:
                            continue
                        first_ts = _jsonl_first_timestamp(jsonl_file)
                        if not first_ts:
                            continue
                        # Prefer conversations at/after the trigger; allow a
                        # small negative slack for clock skew.
                        delta = first_ts - run_ts
                        if delta < -30_000 or delta > 900_000:
                            continue
                        if best_delta is not None and abs(delta) >= abs(best_delta):
                            continue
                        if skill and _conversation_skill(cid) != skill:
                            continue
                        session_id = cid
                        best_delta = delta

        if session_id:
            run.conversation_id = session_id
            used_ids.add(session_id)
            run.save(update_fields=["conversation_id"])


def _resolve_all_unresolved_runs():
    """Resolve conversation links for every unpaired cron run.

    Safe to call repeatedly and from background threads; a cheap no-op when
    nothing is pending, so the 3s sessions poll stays fast once all runs pair.
    """
    qs = CronJobRun.objects.filter(conversation_id="").exclude(
        pid__isnull=True, tmux_session=""
    )
    if not qs.exists():
        return
    _resolve_run_conversations(
        list(qs.select_related("cronjob").order_by("-triggered_at"))
    )


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

    # Cron sessions run headless (no auto-opened window); a notification lets
    # the user open the terminal on demand. Each run gets its own session
    # (mode="new") so multiple cron jobs on the same repo don't collapse onto a
    # single singleton where all but the first are silently skipped as "reused".
    result = _spawn_session(
        [settings.CLAUDE_CMD, prompt], cj.repo, mode="new", view=False
    )

    ok = result.status_code == 200
    pid = result.data.get("pid") if ok else None
    tmux_session = result.data.get("session", "") if ok else ""
    CronJobRun.objects.create(
        cronjob=cj, trigger_type=trigger_type, pid=pid, tmux_session=tmux_session
    )
    cj.last_run_at = datetime.now(timezone.utc)
    cj.save(update_fields=["last_run_at"])

    if ok and tmux_session:
        _notify_session(
            tmux_session,
            f"Cron: /{cj.skill_name}",
            f"Started in {cj.repo}",
        )

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

    from api.models import ConversationIndex

    for wt in worktrees:
        convos = ConversationIndex.objects.filter(
            project__startswith=wt["path"]
        ).order_by("-last_timestamp")[:5]
        wt["conversations"] = [
            {"id": c.conversation_id, "blurb": c.blurb, "date": c.last_timestamp}
            for c in convos
        ]

    return worktrees


def _list_branches(path, default_branch=None):
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

    merged_names = set()
    if default_branch:
        remote_default = None
        for remote in ("upstream", "origin"):
            candidate = f"{remote}/{default_branch}"
            if candidate in remote_refs:
                remote_default = candidate
                break
        if remote_default:
            try:
                merged_output = subprocess.check_output(
                    ["git", "-C", path, "branch", "--merged", remote_default],
                    stderr=subprocess.DEVNULL,
                    text=True,
                )
                merged_names = {
                    line.strip().lstrip("* ")
                    for line in merged_output.splitlines()
                    if line.strip()
                }
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
                "merged": name in merged_names,
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
    branches = _list_branches(path, default_branch)

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
            pr.branch: {
                "number": pr.number,
                "url": pr.url,
                "state": pr.state,
                "cached_at": pr.cached_at.isoformat() if pr.cached_at else None,
            }
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
            pr["cached_at"] = datetime.now(timezone.utc).isoformat()
    else:
        pr = _find_pr_for_branch(forge, branch, path)

    return Response({"branch": branch, "pr": pr})


@api_view(["POST"])
def repo_git_fetch(request):
    repo = request.data.get("repo", "")
    if not repo or not Path(repo).is_dir():
        return Response({"error": "invalid repo path"}, status=400)

    path = str(Path(repo).resolve())
    try:
        subprocess.check_output(
            ["git", "-C", path, "fetch", "--all", "--prune"],
            stderr=subprocess.STDOUT,
            text=True,
            timeout=30,
        )
        return Response({"status": "ok"})
    except subprocess.TimeoutExpired:
        return Response({"error": "fetch timed out"}, status=504)
    except subprocess.CalledProcessError as e:
        return Response({"error": e.output or "fetch failed"}, status=500)
    except FileNotFoundError:
        return Response({"error": "git not found"}, status=500)


@api_view(["POST"])
def repo_delete_branch(request):
    repo = request.data.get("repo", "")
    branch = request.data.get("branch", "")
    force = request.data.get("force", False)
    if not repo or not branch:
        return Response({"error": "repo and branch required"}, status=400)

    path = str(Path(repo).resolve())

    try:
        head = subprocess.check_output(
            ["git", "-C", path, "rev-parse", "--abbrev-ref", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return Response({"error": "not a git repo"}, status=400)

    if branch == head:
        return Response({"error": "cannot delete current branch"}, status=400)

    default = _detect_default_branch(path)
    if branch == default:
        return Response({"error": "cannot delete default branch"}, status=400)

    flag = "-D" if force else "-d"
    try:
        subprocess.check_output(
            ["git", "-C", path, "branch", flag, branch],
            stderr=subprocess.STDOUT,
            text=True,
        )
        return Response({"status": "ok", "branch": branch})
    except subprocess.CalledProcessError as e:
        return Response({"error": e.output.strip() or "delete failed"}, status=400)


@api_view(["POST"])
def repo_cleanup_branches(request):
    repo = request.data.get("repo", "")
    if not repo or not Path(repo).is_dir():
        return Response({"error": "invalid repo path"}, status=400)

    path = str(Path(repo).resolve())

    try:
        subprocess.check_output(
            ["git", "-C", path, "fetch", "--all", "--prune"],
            stderr=subprocess.STDOUT,
            text=True,
            timeout=30,
        )
    except (
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        FileNotFoundError,
    ):
        pass

    default = _detect_default_branch(path)

    remote_default = None
    for remote in ("upstream", "origin"):
        candidate = f"refs/remotes/{remote}/{default}"
        try:
            subprocess.check_output(
                ["git", "-C", path, "rev-parse", "--verify", candidate],
                stderr=subprocess.DEVNULL,
                text=True,
            )
            remote_default = f"{remote}/{default}"
            break
        except (subprocess.CalledProcessError, FileNotFoundError):
            continue

    if not remote_default:
        return Response({"error": f"no remote ref for {default}"}, status=400)

    try:
        merged_output = subprocess.check_output(
            ["git", "-C", path, "branch", "--merged", remote_default],
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return Response({"error": "failed to list merged branches"}, status=500)

    try:
        head = subprocess.check_output(
            ["git", "-C", path, "rev-parse", "--abbrev-ref", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        head = ""

    deleted = []
    skipped = []
    for line in merged_output.splitlines():
        name = line.strip().lstrip("* ")
        if not name or name == head or name == default:
            continue
        try:
            subprocess.check_output(
                ["git", "-C", path, "branch", "-d", name],
                stderr=subprocess.STDOUT,
                text=True,
            )
            deleted.append(name)
        except subprocess.CalledProcessError:
            skipped.append(name)

    return Response({"deleted": deleted, "skipped": skipped})


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
    return _spawn_session([settings.CLAUDE_CMD, prompt], cwd)


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

    base = ConversationIndex.objects.exclude(first_timestamp="")

    # Optional inclusive date range (YYYY-MM-DD). first_timestamp is an ISO
    # string, so "T99" sorts after any real time-of-day on the `to` day.
    date_from = request.query_params.get("from", "")
    date_to = request.query_params.get("to", "")
    if date_from:
        base = base.filter(first_timestamp__gte=date_from)
    if date_to:
        base = base.filter(first_timestamp__lt=date_to + "T99")

    qs = base
    repo = request.query_params.get("repo", "")
    if repo:
        qs = qs.filter(project=repo)

    rows = (
        qs.annotate(date=Substr("first_timestamp", 1, 10))
        .values("date")
        .annotate(count=Sum("message_count"), cost=Sum("cost_usd"))
        .order_by("date")
    )

    # Repo dropdown lists every project regardless of range, so it stays stable.
    projects = sorted(
        ConversationIndex.objects.exclude(project="")
        .values_list("project", flat=True)
        .distinct()
    )

    # Per-repo cost breakdown honours the date range but ignores the repo filter
    # so the whole picture is always available, most expensive first.
    repo_costs = (
        base.exclude(project="")
        .values("project")
        .annotate(cost=Sum("cost_usd"), count=Sum("message_count"))
        .order_by("-cost")
    )

    total_cost = qs.aggregate(total=Sum("cost_usd"))["total"] or 0.0

    return Response(
        {
            "days": [
                {
                    "date": r["date"],
                    "count": r["count"],
                    "cost": round(r["cost"] or 0.0, 6),
                }
                for r in rows
            ],
            "projects": projects,
            "total_cost": round(total_cost, 6),
            "repo_costs": [
                {
                    "project": r["project"],
                    "cost": round(r["cost"] or 0.0, 6),
                    "count": r["count"],
                }
                for r in repo_costs
            ],
        }
    )


def _cached_summary(ci):
    """The list entry for an index row, matching Conversation.summary()."""
    return {
        "id": ci.conversation_id,
        "source": ci.source,
        "parent_id": ci.parent_id,
        "agent_type": ci.agent_type,
        "project": ci.project,
        "date": ci.first_timestamp,
        "blurb": ci.blurb,
        "branch": ci.branch,
        "message_count": ci.message_count,
        "last_timestamp": ci.last_timestamp,
        "cost_usd": ci.cost_usd,
        "input_tokens": ci.input_tokens,
        "output_tokens": ci.output_tokens,
        "cache_read_tokens": ci.cache_read_tokens,
        "cache_write_tokens": ci.cache_write_tokens,
    }


def _ensure_index(adapter, ref):
    """Return a list entry for one conversation, reparsing only if it changed."""
    from api.models import ConversationIndex

    try:
        cached = ConversationIndex.objects.get(conversation_id=ref.id)
        if cached.revision and cached.revision == ref.revision:
            return _cached_summary(cached)
    except ConversationIndex.DoesNotExist:
        pass

    try:
        conv = adapter.load(ref.id)
    except Exception:
        logger.exception("harness %s failed to index %s", adapter.key, ref.id)
        return None
    if conv is None or not (conv.blurb or conv.messages):
        return None

    ConversationIndex.objects.update_or_create(
        conversation_id=conv.id,
        defaults={
            "source": conv.source,
            "parent_id": conv.parent_id,
            "agent_type": conv.agent_type,
            "revision": ref.revision,
            "project": conv.cwd,
            "branch": conv.branch,
            "blurb": conv.blurb,
            "first_timestamp": conv.first_timestamp,
            "last_timestamp": conv.last_timestamp,
            "message_count": len(conv.messages),
            "searchable_text": conv.searchable_text,
            **conv.usage(),
        },
    )
    return conv.summary()


_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp", ".ico"}


@api_view(["GET"])
def local_file(request):
    file_path = request.query_params.get("path", "")
    if not file_path:
        return Response({"error": "path is required"}, status=400)

    p = Path(file_path)
    if p.suffix.lower() not in _IMAGE_EXTENSIONS:
        return Response({"error": "only image files are supported"}, status=400)

    if not p.is_file():
        return Response({"error": "file not found"}, status=404)

    content_type = mimetypes.guess_type(str(p))[0] or "application/octet-stream"
    return FileResponse(open(p, "rb"), content_type=content_type)
