"""Cronjob execution and systemd integration.

The database remains the source of truth. For systemd-backed jobs, an exact
calendar timer wakes a direct Django worker; the stored cron expression is
translated to systemd calendar syntax when units are reconciled.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from croniter import croniter
from django.conf import settings
from django.db import OperationalError

from api import harness
from api.croncalendar import CronCalendarError, calendar_expressions
from api.models import CronJob, CronJobRun

logger = logging.getLogger(__name__)

_UNIT_PREFIX = "contexts-cron-"
_EFFORTS = ("", "low", "medium", "high", "xhigh", "max")


def _systemctl(*args, check=False):
    return subprocess.run(
        ["systemctl", "--user", *args],
        capture_output=True,
        text=True,
        check=check,
    )


def systemd_available():
    try:
        return _systemctl("show-environment").returncode == 0
    except OSError:
        return False


def effective_backend(job, available=None):
    return job.backend


def runner_options():
    result = []
    for key in getattr(settings, "HARNESSES", ["claude"]):
        adapter = harness.get(key)
        if adapter is None:
            continue
        result.append(
            {
                "key": adapter.key,
                "label": getattr(adapter, "label", adapter.key),
                "supports_model": bool(getattr(adapter, "supports_cron_model", False)),
                "models": list(getattr(adapter, "cron_model_choices", [])),
                "supports_effort": bool(
                    getattr(adapter, "supports_cron_effort", False)
                ),
                "efforts": list(_EFFORTS)
                if getattr(adapter, "supports_cron_effort", False)
                else [""],
            }
        )
    return result


def backend_options():
    return [{"key": key, "label": label} for key, label in CronJob.BACKEND_CHOICES]


def validate_job_config(backend, runner, model, effort, cron_expression=""):
    valid_backends = {key for key, _ in CronJob.BACKEND_CHOICES}
    if backend not in valid_backends:
        return f"invalid backend: {backend}"
    adapter = harness.get(runner or "claude")
    if adapter is None:
        return f"runner is unavailable: {runner}"
    if model and not getattr(adapter, "supports_cron_model", False):
        return f"runner does not support model selection: {runner}"
    if effort and not getattr(adapter, "supports_cron_effort", False):
        return f"runner does not support effort selection: {runner}"
    if effort and effort not in _EFFORTS:
        return f"invalid effort: {effort}"
    if backend == CronJob.BACKEND_SYSTEMD and not systemd_available():
        return "systemd user manager is unavailable"
    if backend == CronJob.BACKEND_SYSTEMD:
        try:
            expressions = calendar_expressions(cron_expression)
        except CronCalendarError as exc:
            return str(exc)
        for expression in expressions:
            result = subprocess.run(
                ["systemd-analyze", "calendar", expression],
                capture_output=True,
                text=True,
            )
            if result.returncode:
                return (
                    result.stderr.strip() or f"invalid systemd calendar: {expression}"
                )
    return ""


def _prompt(job):
    prompt = "/" + job.skill_name
    if job.params.strip():
        prompt += " " + job.params
    return prompt


def _launch_argv(job):
    adapter = harness.get(job.runner or "claude")
    if adapter is None:
        raise ValueError(f"runner is unavailable: {job.runner}")
    if job.effort and not getattr(adapter, "supports_cron_effort", False):
        raise ValueError(f"runner does not support effort: {job.runner}")
    argv = harness.launch_argv(
        job.runner or "claude",
        prompt=_prompt(job),
        model=job.model,
        effort=job.effort,
    )
    if argv is None:
        raise ValueError(f"runner cannot launch sessions: {job.runner}")
    return argv


def execute_cronjob(job, trigger_type="scheduled"):
    """Launch one job and return a JSON-serializable result dictionary."""
    from api.views import _notify_session, _spawn_session

    error = ""
    result = None
    try:
        if not Path(job.repo).is_dir():
            raise ValueError("repo directory not found")
        result = _spawn_session(
            _launch_argv(job),
            job.repo,
            mode="new",
            source=job.runner or "claude",
            view=False,
        )
        ok = result.status_code == 200
        data = result.data if isinstance(result.data, dict) else {}
        if not ok:
            error = data.get("error", "session failed to start")
    except (OSError, ValueError) as exc:
        ok = False
        error = str(exc)
        data = {}
    except Exception as exc:
        logger.exception("cronjob %d failed to launch", job.id)
        ok = False
        error = str(exc)
        data = {}

    pid = data.get("pid") if ok else None
    tmux_session = data.get("session", "") if ok else ""
    run = CronJobRun.objects.create(
        cronjob=job,
        trigger_type=trigger_type,
        pid=pid,
        tmux_session=tmux_session,
        status="started" if ok else "failed",
        error=error,
    )
    job.last_run_at = datetime.now(timezone.utc)
    job.save(update_fields=["last_run_at"])

    if ok and tmux_session:
        _notify_session(
            tmux_session,
            f"Cron: /{job.skill_name}",
            f"Started in {job.repo}",
        )

    return {
        "status": "started" if ok else "failed",
        "error": error,
        "run_id": run.id,
        "pid": pid,
        "session": tmux_session,
    }


def queue_systemd_manual(job):
    """Queue a manual run through the user manager without blocking the API."""
    if not systemd_available():
        return {"status": "failed", "error": "systemd user manager is unavailable"}
    manage = Path(settings.BASE_DIR) / "manage.py"
    unit = f"{_unit_prefix()}{_job_slug(job)}-manual-{int(time.time() * 1000)}"
    command = [
        "systemd-run",
        "--user",
        "--unit",
        unit,
        "--collect",
        "--working-directory",
        str(settings.BASE_DIR),
        "--",
        sys.executable,
        str(manage),
        "run_cronjob",
        str(job.id),
        "--manual",
    ]
    try:
        _systemctl("show-environment", check=True)
        subprocess.run(command, check=True, capture_output=True, text=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "stderr", "") or str(exc)
        return {"status": "failed", "error": detail.strip()}
    return {"status": "queued", "unit": unit}


def next_run_at(job, now=None):
    now = now or datetime.now(timezone.utc)
    base = job.last_run_at or job.created_at
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    value = croniter(job.cron_expression, base).get_next(datetime)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value


def _instance_key():
    value = os.environ.get("CONTEXTS_INSTANCE", "default") or "default"
    return re.sub(r"[^A-Za-z0-9_-]+", "-", value)


def _unit_prefix():
    return f"{_UNIT_PREFIX}{_instance_key()}-"


def _unit_dir():
    config = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return config / "systemd" / "user"


def _unit_quote(value):
    if re.fullmatch(r"[A-Za-z0-9_./:=+-]+", value):
        return value
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _job_slug(job):
    skill = re.sub(r"[^A-Za-z0-9]+", "-", job.skill_name).strip("-").lower()
    skill = skill[:48] or "job"
    return f"{skill}-{job.id}"


def _service_name(job):
    return f"{_unit_prefix()}{_job_slug(job)}.service"


def _timer_name(job):
    return f"{_unit_prefix()}{_job_slug(job)}.timer"


def _service_text(job):
    manage = Path(settings.BASE_DIR) / "manage.py"
    command = [
        sys.executable,
        str(manage),
        "run_cronjob",
        str(job.id),
        "--scheduled",
    ]
    argv = " ".join(_unit_quote(value) for value in command)
    instance = os.environ.get("CONTEXTS_INSTANCE", "")
    return f"""[Unit]
Description=Contexts cronjob /{job.skill_name} ({job.id})

[Service]
Type=oneshot
WorkingDirectory={_unit_quote(str(settings.BASE_DIR))}
Environment=CONTEXTS_INSTANCE={_unit_quote(instance)}
Environment=PYTHONUNBUFFERED=1
TimeoutStartSec=infinity
StandardOutput=journal
StandardError=journal
ExecStart={argv}
"""


def _timer_text(job):
    expressions = calendar_expressions(job.cron_expression)
    calendars = "\n".join(f"OnCalendar={expression}" for expression in expressions)
    return f"""[Unit]
Description=Contexts persistent cron wakeup /{job.skill_name} ({job.id})

[Timer]
{calendars}
Persistent=true
AccuracySec=1s
Unit={_service_name(job)}

[Install]
WantedBy=timers.target
"""


def _write(path, content):
    old = path.read_text() if path.exists() else None
    if old == content:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False) as stream:
        stream.write(content)
        temporary = Path(stream.name)
    temporary.chmod(0o644)
    os.replace(temporary, path)
    return True


def reconcile_systemd_jobs():
    """Make contexts-owned systemd units match the database.

    Returns False when the user systemd manager is unavailable. Explicitly
    internal jobs remain owned by the in-process scheduler.
    """
    if not systemd_available():
        return False
    try:
        jobs = list(CronJob.objects.all())
    except OperationalError:
        return False

    destination = _unit_dir()
    prefix = _unit_prefix()
    existing_paths = set(destination.glob(f"{prefix}*.service")) | set(
        destination.glob(f"{prefix}*.timer")
    )
    desired_jobs = [
        job
        for job in jobs
        if effective_backend(job, available=True) == CronJob.BACKEND_SYSTEMD
        and job.enabled
    ]
    desired_paths = {destination / _service_name(job) for job in desired_jobs}
    desired_paths |= {
        destination / _timer_name(job) for job in desired_jobs if job.enabled
    }
    old_timer_names = {path.name for path in existing_paths if path.suffix == ".timer"}
    changed_timers = set()

    for path in existing_paths - desired_paths:
        if path.suffix == ".timer":
            _systemctl("disable", "--now", path.name)
        path.unlink(missing_ok=True)

    for job in desired_jobs:
        service = destination / _service_name(job)
        timer = destination / _timer_name(job)
        _write(service, _service_text(job))
        if _write(timer, _timer_text(job)):
            changed_timers.add(timer.name)

    _systemctl("daemon-reload", check=True)
    for job in desired_jobs:
        if not job.enabled:
            continue
        timer = _timer_name(job)
        _systemctl("enable", "--now", timer, check=True)
        if timer in changed_timers and timer in old_timer_names:
            _systemctl("restart", timer, check=True)
    return True
