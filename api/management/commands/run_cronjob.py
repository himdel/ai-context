from django.core.management.base import BaseCommand, CommandError

from api.cronjobs import execute_cronjob
from api.models import CronJob


class Command(BaseCommand):
    help = "Run one persisted cronjob from a systemd timer"

    def add_arguments(self, parser):
        parser.add_argument("cronjob_id", type=int)
        parser.add_argument("--scheduled", action="store_true")

    def handle(self, *args, **options):
        try:
            job = CronJob.objects.get(pk=options["cronjob_id"])
        except CronJob.DoesNotExist as exc:
            raise CommandError("cronjob does not exist") from exc

        if options["scheduled"] and not job.enabled:
            return

        result = execute_cronjob(
            job,
            trigger_type="scheduled" if options["scheduled"] else "manual",
        )
        if result["status"] != "started":
            raise CommandError(result["error"] or "cronjob failed to start")
        self.stdout.write(f"started cronjob run {result['run_id']}")
