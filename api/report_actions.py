"""Local report proposals: reading is inert, confirmation claims once before forking."""

import ipaddress
import logging
import os
from datetime import timedelta
from pathlib import Path
from urllib.parse import quote, urlsplit

from django.conf import settings
from django.db import transaction
from django.http import FileResponse, HttpResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.decorators import api_view
from rest_framework.response import Response

from api import harness
from api.models import ReportAction, ReportActionGroup

logger = logging.getLogger(__name__)
STATIC = Path(__file__).resolve().parent.parent / "static"


def _local(request):
    """Use the socket peer, never forwarded headers or a caller's claimed address."""
    try:
        peer = ipaddress.ip_address(request.META.get("REMOTE_ADDR", ""))
        peer = getattr(peer, "ipv4_mapped", None) or peer
        return peer.is_loopback
    except ValueError:
        return False


def _guard(request):
    if not _local(request):
        return Response(
            {
                "error": "Report actions are local-only. Open this link on the Contexts host using localhost."
            },
            status=403,
        )
    return None


def _url(request, action):
    return request.build_absolute_uri(f"/actions/{action.id}")


def _conversation_path(conversation_id):
    return f"/conversations/{quote(conversation_id, safe='')}"


def report_url(report_path, project):
    """Link to the current file without reading it or resolving symlinks."""
    base = settings.MDVIEW_URL
    if not report_path or not isinstance(base, str) or not base:
        return None
    try:
        origin = urlsplit(base)
        if (
            origin.scheme not in ("http", "https")
            or not origin.hostname
            or origin.username
            or origin.password
            or origin.query
            or origin.fragment
            or origin.path not in ("", "/")
        ):
            return None
        origin.port  # Reject malformed configured ports.
        path = Path(report_path).expanduser()
        if not path.is_absolute():
            if not Path(project).is_absolute():
                return None
            path = Path(project) / path
        relative = Path(os.path.normpath(path)).relative_to(Path.home())
    except (ValueError, RuntimeError):
        # mdview only addresses paths beneath home. Keep other paths as text.
        return None
    suffix = "/" + quote(relative.as_posix(), safe="/") if relative.parts else ""
    return f"{base.rstrip('/')}/~{suffix}"


def freshness(created_at, now=None):
    age = max(0, int(((now or timezone.now()) - created_at).total_seconds() // 86400))
    level = (
        "recent" if age < 3 else "aging" if age < 7 else "stale" if age < 30 else "old"
    )
    return {"days": age, "level": level, "requires_acknowledgement": age >= 7}


def _target(group):
    adapter = harness.get(group.source)
    conv = harness.load(group.conversation_id, group.source) if adapter else None
    if conv is None:
        return (
            adapter,
            None,
            "The source conversation is missing or its harness is unavailable.",
        )
    if not Path(group.project).is_dir():
        return (
            adapter,
            conv,
            "The original project directory no longer exists. No fallback directory will be used.",
        )
    if not harness.can_launch(group.source):
        return adapter, conv, "This harness cannot launch a follow-up."
    return adapter, conv, ""


def _detail(request, action):
    group = action.group
    adapter, conv, problem = _target(group)
    selected = str(group.selected_action) if group.selected_action else None
    return {
        "id": str(action.id),
        "label": action.label,
        "text": action.text,
        "status": action.status,
        "submitted_text": action.submitted_text,
        "submitted_at": action.submitted_at,
        "result": action.result,
        "url": _url(request, action),
        "title": group.title,
        "report_path": group.report_path,
        "report_url": report_url(group.report_path, group.project),
        "report_created_at": group.report_created_at,
        "freshness": freshness(group.report_created_at),
        "mode": group.mode,
        "selected_action": selected,
        "choices": [
            {
                "id": str(a.id),
                "label": a.label,
                "status": a.status,
                "url": _url(request, a),
            }
            for a in group.actions.order_by("id")
        ],
        "source": group.source,
        "project": group.project,
        "conversation_id": group.conversation_id,
        "conversation_url": _conversation_path(group.conversation_id),
        "source_active": bool(
            adapter and group.conversation_id in adapter.active_ids()
        ),
        "source_changed": bool(
            conv
            and (
                len(conv.messages) != group.message_count
                or conv.last_timestamp != group.last_timestamp
            )
        ),
        "problem": problem,
        "can_submit": not problem
        and action.status == "pending"
        and (not selected or selected == str(action.id)),
    }


@api_view(["POST"])
def register(request):
    denied = _guard(request)
    if denied is not None:
        return denied
    data = request.data
    if not isinstance(data, dict):
        return Response({"error": "Expected a JSON object."}, status=400)
    title = data.get("title")
    source = data.get("source")
    conversation_id = data.get("conversation_id")
    report_path = data.get("report_path", "")
    mode = data.get("mode", "independent")
    actions = data.get("actions")
    if not all(
        isinstance(v, str) and 0 < len(v.strip()) <= limit
        for v, limit in ((title, 255), (source, 32), (conversation_id, 64))
    ):
        return Response(
            {"error": "title, source and conversation_id are required strings."},
            status=400,
        )
    if not isinstance(report_path, str) or len(report_path) > 1024:
        return Response(
            {"error": "report_path must be a string of at most 1024 characters."},
            status=400,
        )
    if mode not in ("independent", "exclusive"):
        return Response({"error": "mode must be independent or exclusive."}, status=400)
    if not isinstance(actions, list) or not 1 <= len(actions) <= 30:
        return Response(
            {"error": "actions must contain 1 to 30 proposals."}, status=400
        )
    for action in actions:
        if not isinstance(action, dict) or not all(
            isinstance(action.get(k), str) and 0 < len(action[k].strip()) <= limit
            for k, limit in (("label", 255), ("text", 30000))
        ):
            return Response(
                {
                    "error": "Each action needs a label (1-255 characters) and text (1-30000)."
                },
                status=400,
            )
    created_at = timezone.now()
    if "report_created_at" in data:
        try:
            created_at = parse_datetime(data["report_created_at"])
        except (ValueError, TypeError):
            created_at = None
        if (
            created_at is None
            or timezone.is_naive(created_at)
            or created_at > timezone.now() + timedelta(minutes=5)
        ):
            return Response(
                {
                    "error": "report_created_at must be an ISO timestamp with timezone, not in the future."
                },
                status=400,
            )
    conv = harness.load(conversation_id, source)
    if conv is None or conv.source != source:
        return Response(
            {"error": "Source conversation not found in this Contexts instance."},
            status=404,
        )
    if not conv.cwd or not Path(conv.cwd).is_dir() or not harness.can_launch(source):
        return Response(
            {"error": "The original project or launch-capable harness is unavailable."},
            status=409,
        )
    with transaction.atomic():
        group = ReportActionGroup.objects.create(
            mode=mode,
            title=title,
            report_path=report_path,
            report_created_at=created_at,
            conversation_id=conversation_id,
            source=source,
            project=conv.cwd,
            message_count=len(conv.messages),
            last_timestamp=conv.last_timestamp,
        )
        saved = [
            ReportAction.objects.create(group=group, label=a["label"], text=a["text"])
            for a in actions
        ]
    return Response(
        {
            "group_id": str(group.id),
            "mode": mode,
            "conversation_id": group.conversation_id,
            "conversation_url": request.build_absolute_uri(
                _conversation_path(group.conversation_id)
            ),
            "actions": [
                {"id": str(a.id), "label": a.label, "url": _url(request, a)}
                for a in saved
            ],
        },
        status=201,
    )


@api_view(["GET"])
def detail(request, action_id):
    denied = _guard(request)
    if denied is not None:
        return denied
    action = ReportAction.objects.select_related("group").filter(pk=action_id).first()
    if action is None:
        return Response(
            {
                "error": "This saved action is missing. It may belong to another Contexts instance, or its database was removed. Nothing was submitted."
            },
            status=404,
        )
    response = Response(_detail(request, action))
    response["Cache-Control"] = "no-store"
    return response


@api_view(["POST"])
def submit(request, action_id):
    denied = _guard(request)
    if denied is not None:
        return denied
    # No form or navigation can confirm; only an explicit JSON request from the page/CLI.
    if request.content_type != "application/json" or not isinstance(request.data, dict):
        return Response({"error": "Confirmation requires JSON."}, status=415)
    origin = request.headers.get("Origin")
    if origin and origin != f"{request.scheme}://{request.get_host()}":
        return Response(
            {"error": "Open the confirmation page directly in Contexts."}, status=403
        )
    action = ReportAction.objects.select_related("group").filter(pk=action_id).first()
    if action is None:
        return Response(
            {"error": "Saved action not found. Nothing was submitted."}, status=404
        )
    group = action.group
    text = request.data.get("text", action.text)
    if not isinstance(text, str) or not 0 < len(text.strip()) <= 30000:
        return Response({"error": "text must contain 1-30000 characters."}, status=400)
    if request.data.get("confirm") != "fork":
        return Response({"error": "Explicit confirm: fork is required."}, status=400)
    if (
        freshness(group.report_created_at)["requires_acknowledgement"]
        and request.data.get("acknowledge_stale") is not True
    ):
        return Response(
            {"error": "Review and acknowledge this stale report before submitting."},
            status=409,
        )
    adapter, conv, problem = _target(group)
    if problem:
        return Response({"error": problem}, status=409)
    # Write first, in a short transaction. No external effects under a DB lock.
    # Conditional updates serialize concurrent requests even on SQLite.
    with transaction.atomic():
        if group.mode == "exclusive":
            claimed = ReportActionGroup.objects.filter(
                pk=group.pk, selected_action__isnull=True
            ).update(selected_action=action.id)
            if not claimed:
                return Response(
                    {
                        "error": "A choice in this group has already been submitted. Nothing else was launched."
                    },
                    status=409,
                )
        claimed = ReportAction.objects.filter(pk=action.pk, status="pending").update(
            status="submitting", submitted_text=text, submitted_at=timezone.now()
        )
        if not claimed:
            return Response(
                {
                    "error": "This action has already been submitted. Nothing else was launched."
                },
                status=409,
            )
    result = {}
    try:
        # Always fork. Never resume the source, send keys to it, or reuse its tmux.
        from api.views import _spawn_session

        fork_id = adapter.fork_session(group.conversation_id)
        if fork_id:
            if fork_id == group.conversation_id:
                raise RuntimeError(
                    "The harness returned the original conversation as its fork."
                )
            result["conversation_id"] = fork_id
        argv = harness.launch_argv(
            group.source,
            conversation_id=fork_id or group.conversation_id,
            fork=not bool(fork_id),
            prompt=text,
        )
        if argv is None:
            raise RuntimeError("The harness could not prepare a fork launch.")
        response = _spawn_session(
            argv,
            group.project,
            source=group.source,
            conversation_id=fork_id or "",
            view=False,
        )
        result.update(response.data)
        if response.status_code >= 400:
            raise RuntimeError(str(response.data.get("error", "Launch failed.")))
    except Exception as exc:
        logger.exception(
            "report action %s launch failed; no automatic retry", action.id
        )
        result["error"] = str(exc)
        ReportAction.objects.filter(pk=action.pk).update(
            status="uncertain", result=result
        )
        return Response(
            {
                "error": "Submission was claimed, but launch could not be confirmed. Inspect the session before doing anything manually; this action cannot run again.",
                "result": result,
            },
            status=502,
        )
    ReportAction.objects.filter(pk=action.pk).update(status="submitted", result=result)
    return Response({"status": "submitted", "result": result})


def page(request, action_id):
    if not _local(request):
        return HttpResponse(
            "Report actions are local-only. Open this link on the Contexts host using localhost.",
            status=403,
            content_type="text/plain",
        )
    response = FileResponse(
        (STATIC / "actions.html").open("rb"), content_type="text/html"
    )
    response["Cache-Control"] = "no-store"
    response["X-Frame-Options"] = "DENY"
    return response
