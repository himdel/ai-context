import json
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase, override_settings
from django.utils import timezone

from api import cronjobs
from api.croncalendar import CronCalendarError, calendar_expressions
from api.harness import base
from api.harness.claude import ClaudeHarness
from api.harness.opencode import (
    OpencodeHarness,
    _block_from_part,
    _cached_context,
    _derive_todos,
    _git_branch,
)


class CronjobBackendTests(SimpleTestCase):
    def make_job(self, **values):
        defaults = {
            "id": 7,
            "backend": "systemd",
            "runner": "claude",
            "agent": "",
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

    def test_systemd_service_waits_for_ordinary_network(self):
        text = cronjobs._service_text(self.make_job())
        self.assertIn("ExecStartPre=%h/bin/wait-for-network", text)

    def test_systemd_service_keeps_manager_environment_for_agents(self):
        text = cronjobs._service_text(self.make_job())
        self.assertIn("Environment=HOME=%h", text)
        self.assertIn("Environment=XDG_RUNTIME_DIR=/run/user/%U", text)
        self.assertIn(
            "Environment=DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/%U/bus",
            text,
        )
        self.assertNotIn("Environment=PATH=", text)
        self.assertNotIn("Environment=SHELL=", text)

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

    def test_prompt_uses_slash_command_by_default(self):
        self.assertEqual(
            cronjobs._prompt(self.make_job(params="--full")),
            "/daily-check --full",
        )

    def test_prompt_can_use_natural_language(self):
        self.assertEqual(
            cronjobs._prompt(self.make_job(natural_language=True, params="--full")),
            "Please run the skill daily-check --full",
        )

    def test_launch_argv_passes_the_selected_agent(self):
        job = self.make_job(runner="opencode", agent="sol")
        with (
            mock.patch.object(cronjobs.harness, "get", return_value=SimpleNamespace()),
            mock.patch.object(
                cronjobs.harness, "launch_argv", return_value=["opencode"]
            ) as launch,
        ):
            self.assertEqual(cronjobs._launch_argv(job), ["opencode"])

        launch.assert_called_once_with(
            "opencode",
            prompt="/daily-check",
            agent="sol",
            model="",
            effort="",
        )

    def test_agent_selection_requires_runner_support(self):
        adapter = SimpleNamespace(
            supports_cron_agent=False,
            supports_cron_model=False,
            supports_cron_effort=False,
        )
        with mock.patch.object(cronjobs.harness, "get", return_value=adapter):
            error = cronjobs.validate_job_config(
                "internal", "claude", "", "", "0 9 * * 1", "sol"
            )

        self.assertEqual(error, "runner does not support agent selection: claude")


class OpencodeLaunchTests(SimpleTestCase):
    @override_settings(OPENCODE_CMD="opencode")
    def test_launch_argv_selects_configured_agent(self):
        self.assertEqual(
            OpencodeHarness().launch_argv(agent="sol", prompt="Please run learnings"),
            [
                "opencode",
                "--agent",
                "sol",
                "--prompt",
                "Please run learnings",
            ],
        )


class ClaudeLaunchTests(SimpleTestCase):
    @override_settings(CLAUDE_CMD="claude")
    def test_launch_argv_selects_configured_agent(self):
        self.assertEqual(
            ClaudeHarness().launch_argv(agent="reviewer", prompt="Review this"),
            ["claude", "--agent", "reviewer", "Review this"],
        )


class OpencodeTodoTests(SimpleTestCase):
    def test_reads_matching_cached_context(self):
        with TemporaryDirectory() as tmp:
            cache = Path(tmp) / "ses_test.json"
            cache.write_text(
                json.dumps(
                    {
                        "session_id": "ses_test",
                        "directory": "/tmp/repo",
                        "branch": "feature/demo",
                    }
                )
            )
            with override_settings(OPENCODE_CONTEXT_CACHE_DIR=Path(tmp)):
                self.assertEqual(
                    _cached_context("ses_test", "/tmp/repo")["branch"],
                    "feature/demo",
                )

    @mock.patch("api.harness.opencode.subprocess.check_output")
    def test_reads_branch_from_checkout(self, check_output):
        check_output.return_value = "main\n"

        self.assertEqual(_git_branch("/tmp/repo"), "main")
        check_output.assert_called_once_with(
            ["git", "-C", "/tmp/repo", "branch", "--show-current"],
            stderr=mock.ANY,
            text=True,
        )

    def test_maps_target_tool_parts_to_canonical_blocks(self):
        todo = _block_from_part(
            {
                "type": "tool",
                "tool": "todowrite",
                "state": {
                    "status": "completed",
                    "input": {"todos": [{"content": "inspect", "status": "pending"}]},
                    "output": "ok",
                },
            }
        )
        jira = _block_from_part(
            {
                "type": "tool",
                "tool": "jira_getJiraIssue",
                "state": {
                    "status": "completed",
                    "input": {"issueIdOrKey": "AAP-1"},
                    "output": '{"key":"AAP-1"}',
                },
            }
        )

        self.assertEqual(todo["name"], base.TODO_WRITE)
        self.assertEqual(todo["input"]["todos"][0]["content"], "inspect")
        self.assertEqual(jira["name"], "jira_getJiraIssue")
        self.assertEqual(jira["input"]["issueIdOrKey"], "AAP-1")

    def test_derives_full_history_and_marks_current_snapshot(self):
        messages = [
            SimpleNamespace(
                blocks=[
                    {
                        "type": "tool_use",
                        "name": base.TODO_WRITE,
                        "input": {
                            "todos": [
                                {"content": "first", "status": "pending"},
                                {"content": "second", "status": "in_progress"},
                            ]
                        },
                    }
                ]
            ),
            SimpleNamespace(
                blocks=[
                    {
                        "type": "tool_use",
                        "name": base.TODO_WRITE,
                        "input": {
                            "todos": [
                                {"content": "first", "status": "completed"},
                                {"content": "third", "status": "pending"},
                            ]
                        },
                    }
                ]
            ),
        ]

        self.assertEqual(
            _derive_todos(messages),
            [
                {
                    "id": "1",
                    "subject": "first",
                    "status": "completed",
                    "current": True,
                },
                {
                    "id": "2",
                    "subject": "second",
                    "status": "in_progress",
                    "current": False,
                },
                {
                    "id": "3",
                    "subject": "third",
                    "status": "pending",
                    "current": True,
                },
            ],
        )
