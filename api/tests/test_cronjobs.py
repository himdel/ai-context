from datetime import timedelta
from types import SimpleNamespace

from django.test import SimpleTestCase
from django.utils import timezone

from api import cronjobs
from api.croncalendar import CronCalendarError, calendar_expressions


class CronjobBackendTests(SimpleTestCase):
    def make_job(self, **values):
        defaults = {
            "id": 7,
            "backend": "systemd",
            "runner": "claude",
            "model": "",
            "effort": "",
            "skill_name": "daily-check",
            "repo": "/tmp/repo",
            "params": "",
            "cron_expression": "0 9 * * *",
            "created_at": timezone.now() - timedelta(days=1),
            "last_run_at": None,
        }
        defaults.update(values)
        return SimpleNamespace(**defaults)

    def test_backend_is_explicit(self):
        self.assertEqual(
            cronjobs.effective_backend(self.make_job(backend="systemd")),
            "systemd",
        )
        self.assertEqual(
            cronjobs.effective_backend(self.make_job(backend="internal")),
            "internal",
        )

    def test_systemd_timer_is_persistent_exact_calendar(self):
        job = self.make_job()
        text = cronjobs._timer_text(job)
        self.assertIn("OnCalendar=*-*-* 09:00:00", text)
        self.assertIn("Persistent=true", text)
        self.assertIn("AccuracySec=1s", text)

    def test_calendar_preserves_cron_day_or_semantics(self):
        self.assertEqual(
            calendar_expressions("0 9 1 * 1"),
            ("*-*-01 09:00:00", "Mon *-*-* 09:00:00"),
        )

    def test_calendar_expands_steps(self):
        self.assertEqual(
            calendar_expressions("22 */4 * * *"),
            ("*-*-* 00,04,08,12,16,20:22:00",),
        )

    def test_calendar_rejects_reboot(self):
        with self.assertRaises(CronCalendarError):
            calendar_expressions("@reboot")
