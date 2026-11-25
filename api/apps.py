import logging
import os
import threading
import time

from django.apps import AppConfig

logger = logging.getLogger(__name__)


class ApiConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "api"

    def ready(self):
        if os.environ.get("RUN_MAIN") != "true":
            return
        _start_scheduler()


def _start_scheduler():
    t = threading.Thread(target=_scheduler_loop, daemon=True)
    t.start()
    logger.info("cronjob scheduler started")


def _scheduler_loop():
    time.sleep(10)
    from api.cronjobs import reconcile_persistent_jobs, systemd_available

    systemd = systemd_available()
    try:
        reconcile_persistent_jobs()
    except Exception:
        logger.exception("systemd cron reconciliation error")
    while True:
        try:
            _check_cronjobs(systemd)
        except Exception:
            logger.exception("scheduler error")
        try:
            _resolve_cron_conversations()
        except Exception:
            logger.exception("cron pairing error")
        time.sleep(60)


def _resolve_cron_conversations():
    from api.views import _resolve_all_unresolved_runs

    _resolve_all_unresolved_runs()


def _check_cronjobs(systemd=None):
    from datetime import datetime, timezone

    from api.cronjobs import (
        effective_backend,
        execute_cronjob,
        next_run_at,
        systemd_available,
    )
    from api.models import CronJob

    if systemd is None:
        systemd = systemd_available()
    for cj in CronJob.objects.filter(enabled=True):
        if effective_backend(cj, available=systemd) != CronJob.BACKEND_INTERNAL:
            continue
        try:
            now = datetime.now(timezone.utc)
            next_run = next_run_at(cj, now)
            if next_run <= now:
                if (now - next_run).total_seconds() > 60:
                    logger.info(
                        "skipping missed cronjob %d (/%s), advancing to next",
                        cj.id,
                        cj.skill_name,
                    )
                    cj.last_run_at = now
                    cj.save(update_fields=["last_run_at"])
                    continue
                logger.info(
                    "triggering cronjob %d (/%s in %s)",
                    cj.id,
                    cj.skill_name,
                    cj.repo,
                )
                execute_cronjob(cj, trigger_type="scheduled")
        except Exception:
            logger.exception("error checking cronjob %d", cj.id)
