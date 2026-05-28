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
    while True:
        try:
            _check_cronjobs()
        except Exception:
            logger.exception("scheduler error")
        time.sleep(60)


def _check_cronjobs():
    from datetime import datetime, timezone

    from croniter import croniter

    from api.models import CronJob

    now = datetime.now(timezone.utc)
    for cj in CronJob.objects.filter(enabled=True):
        try:
            base = cj.last_run_at or cj.created_at
            if base.tzinfo is None:
                base = base.replace(tzinfo=timezone.utc)
            cron = croniter(cj.cron_expression, base)
            next_run = cron.get_next(datetime)
            if next_run.tzinfo is None:
                next_run = next_run.replace(tzinfo=timezone.utc)
            if next_run <= now:
                from api.views import _execute_cronjob

                logger.info(
                    "triggering cronjob %d (/%s in %s)",
                    cj.id,
                    cj.skill_name,
                    cj.repo,
                )
                _execute_cronjob(cj, trigger_type="scheduled")
        except Exception:
            logger.exception("error checking cronjob %d", cj.id)
