from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch
from uuid import uuid4

from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.test import APIClient

from api.harness.base import Conversation, Message
from api.models import ReportAction, ReportActionGroup
from api.report_actions import freshness, report_url


@override_settings(ALLOWED_HOSTS=["testserver", "localhost"])
class ReportActionsTests(TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.conv = Conversation(
            id="ses_source",
            source="opencode",
            cwd=self.directory.name,
            messages=[Message(role="user")],
            last_timestamp="2026-11-24T10:00:00Z",
        )
        self.adapter = Mock()
        self.adapter.active_ids.return_value = {"ses_source"}
        self.adapter.fork_session.return_value = "ses_forked"
        for name, value in (
            ("api.report_actions.harness.load", self.conv),
            ("api.report_actions.harness.get", self.adapter),
            ("api.report_actions.harness.can_launch", True),
            (
                "api.report_actions.harness.launch_argv",
                ["opencode", "--session", "ses_forked"],
            ),
            (
                "api.views._spawn_session",
                Response({"status": "ok", "session": "ctx-test"}),
            ),
        ):
            p = patch(name, return_value=value)
            setattr(self, name.rsplit(".", 1)[-1], p.start())
            self.addCleanup(p.stop)
        self.client = APIClient(REMOTE_ADDR="127.0.0.1")

    def register(self, mode="independent", **extra):
        body = {
            "title": "Weekly review",
            "source": "opencode",
            "conversation_id": "ses_source",
            "report_path": "~/reports/weekly.md",
            "mode": mode,
            "actions": [
                {"label": "Investigate", "text": "Investigate the reported failures."},
                {"label": "Defer", "text": "Record the reason for deferral."},
            ],
            **extra,
        }
        return self.client.post("/api/report-actions", body, format="json")

    def actions(self, mode="independent", **extra):
        response = self.register(mode, **extra)
        self.assertEqual(response.status_code, 201, response.data)
        return list(
            ReportAction.objects.filter(group_id=response.data["group_id"]).order_by(
                "label"
            )
        )

    def submit(self, action, **extra):
        return self.client.post(
            f"/api/report-actions/{action.id}/submit",
            {"confirm": "fork", **extra},
            format="json",
        )

    def test_registration_and_preview_are_inert_and_durable(self):
        action = self.actions()[0]
        for suffix in ("", "/"):
            response = self.client.get(f"/api/report-actions/{action.id}{suffix}")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data["text"], action.text)
            self.assertEqual(response.data["project"], self.directory.name)
            self.assertEqual(
                response.data["conversation_url"], "/conversations/ses_source"
            )
            self.assertEqual(
                response.data["report_url"], "http://localhost:6821/~/reports/weekly.md"
            )
            self.assertTrue(response.data["source_active"])
            self.assertFalse(response.data["source_changed"])
            self.assertEqual(response["Cache-Control"], "no-store")
            page = self.client.get(f"/actions/{action.id}{suffix}")
            self.assertEqual(page.status_code, 200)
            page.close()
        self.adapter.fork_session.assert_not_called()
        self._spawn_session.assert_not_called()
        self.assertEqual(ReportActionGroup.objects.count(), 1)

    def test_registration_returns_absolute_source_session_link(self):
        response = self.register()
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["conversation_id"], "ses_source")
        self.assertEqual(
            response.data["conversation_url"],
            "http://testserver/conversations/ses_source",
        )

    def test_local_only_including_forwarded_header_spoofing(self):
        action = self.actions()[0]
        for ip in ("192.168.1.8", "10.0.0.4", "100.90.47.2", "::ffff:192.168.1.8", ""):
            with self.subTest(ip=ip):
                remote = APIClient(REMOTE_ADDR=ip, HTTP_X_FORWARDED_FOR="127.0.0.1")
                for method, url, data in (
                    ("post", "/api/report-actions", {}),
                    ("get", f"/api/report-actions/{action.id}", None),
                    (
                        "post",
                        f"/api/report-actions/{action.id}/submit",
                        {"confirm": "fork"},
                    ),
                    ("get", f"/actions/{action.id}", None),
                ):
                    response = getattr(remote, method)(url, data, format="json")
                    self.assertEqual(response.status_code, 403)
        self.adapter.fork_session.assert_not_called()
        for ip in ("::1", "::ffff:127.0.0.1"):
            self.assertEqual(
                APIClient(REMOTE_ADDR=ip)
                .get(f"/api/report-actions/{action.id}")
                .status_code,
                200,
            )

    def test_independent_actions_each_claim_once_and_preserve_edited_message(self):
        a, b = self.actions()
        self.assertEqual(
            self.submit(a, text="Use this edited message.").status_code, 200
        )
        self.assertEqual(self.submit(a).status_code, 409)
        self.assertEqual(self.submit(b).status_code, 200)
        self.assertEqual(self._spawn_session.call_count, 2)
        self.launch_argv.assert_any_call(
            "opencode",
            conversation_id="ses_forked",
            fork=False,
            prompt="Use this edited message.",
        )
        self._spawn_session.assert_called_with(
            ["opencode", "--session", "ses_forked"],
            self.directory.name,
            source="opencode",
            conversation_id="ses_forked",
            view=False,
        )
        a.refresh_from_db()
        self.assertEqual(a.submitted_text, "Use this edited message.")
        self.assertEqual(a.status, "submitted")
        self.assertIsNotNone(a.submitted_at)

    def test_exclusive_group_consumes_all_alternatives(self):
        a, b = self.actions("exclusive")
        self.assertEqual(self.submit(a).status_code, 200)
        self.assertEqual(self.submit(a).status_code, 409)
        self.assertEqual(self.submit(b).status_code, 409)
        detail = self.client.get(f"/api/report-actions/{b.id}").data
        self.assertEqual(detail["selected_action"], str(a.id))
        self.assertFalse(detail["can_submit"])
        self._spawn_session.assert_called_once()

    def test_inflight_duplicate_or_sibling_cannot_launch(self):
        for mode in ("independent", "exclusive"):
            with self.subTest(mode=mode):
                a, b = self.actions(mode)

                def fork(_):
                    self.assertEqual(self.submit(a).status_code, 409)
                    if mode == "exclusive":
                        self.assertEqual(self.submit(b).status_code, 409)
                    return "ses_forked"

                self.adapter.fork_session.side_effect = fork
                self.assertEqual(self.submit(a).status_code, 200)
        self.assertEqual(self._spawn_session.call_count, 2)

    def test_stale_acknowledgement_is_enforced_on_server(self):
        action = self.actions(
            report_created_at=(timezone.now() - timedelta(days=8)).isoformat()
        )[0]
        self.assertEqual(self.submit(action).status_code, 409)
        self.adapter.fork_session.assert_not_called()
        self.assertEqual(self.submit(action, acknowledge_stale=True).status_code, 200)

    def test_launch_failure_consumes_choice_and_records_uncertain_outcome(self):
        a, b = self.actions("exclusive")
        self.adapter.fork_session.side_effect = RuntimeError("service unavailable")
        with self.assertLogs("api.report_actions", level="ERROR"):
            self.assertEqual(self.submit(a).status_code, 502)
        self.assertEqual(self.submit(a).status_code, 409)
        self.assertEqual(self.submit(b).status_code, 409)
        a.refresh_from_db()
        self.assertEqual(a.status, "uncertain")
        self.assertIn("service unavailable", a.result["error"])
        self._spawn_session.assert_not_called()

    def test_failed_spawn_retains_fork_id_without_retry(self):
        action = self.actions()[0]
        self._spawn_session.return_value = Response(
            {"error": "launch exited"}, status=500
        )
        with self.assertLogs("api.report_actions", level="ERROR"):
            self.assertEqual(self.submit(action).status_code, 502)
        action.refresh_from_db()
        self.assertEqual(action.result["conversation_id"], "ses_forked")
        self.assertEqual(action.status, "uncertain")
        self.assertEqual(self.submit(action).status_code, 409)

    def test_cli_fork_passes_prompt_and_never_resumes_source(self):
        action = self.actions()[0]
        self.adapter.fork_session.return_value = None
        self.assertEqual(self.submit(action).status_code, 200)
        self.launch_argv.assert_called_once_with(
            "opencode", conversation_id="ses_source", fork=True, prompt=action.text
        )
        self.assertEqual(self._spawn_session.call_args.kwargs["conversation_id"], "")

    def test_fork_cannot_return_original_session(self):
        action = self.actions()[0]
        self.adapter.fork_session.return_value = "ses_source"
        with self.assertLogs("api.report_actions", level="ERROR"):
            self.assertEqual(self.submit(action).status_code, 502)
        self._spawn_session.assert_not_called()

    def test_missing_source_project_or_harness_never_falls_back(self):
        action = self.actions()[0]
        self.load.return_value = None
        self.assertEqual(self.submit(action).status_code, 409)
        self.assertFalse(
            self.client.get(f"/api/report-actions/{action.id}").data["can_submit"]
        )
        self.load.return_value = self.conv
        ReportActionGroup.objects.filter(pk=action.group_id).update(
            project=str(Path(self.directory.name) / "gone")
        )
        self.assertEqual(self.submit(action).status_code, 409)
        self._spawn_session.assert_not_called()
        self.adapter.fork_session.assert_not_called()

    def test_source_changed_warning(self):
        action = self.actions()[0]
        self.conv.messages.append(Message(role="assistant"))
        self.assertTrue(
            self.client.get(f"/api/report-actions/{action.id}").data["source_changed"]
        )

    def test_bad_input_and_missing_links_are_explanatory(self):
        for extra in (
            {"mode": "both"},
            {"actions": []},
            {"actions": ["bad"]},
            {"title": None},
            {"actions": [{"label": "x", "text": 5}]},
            {"report_created_at": "not a date"},
            {"report_created_at": "2026-01-01"},
            {"report_created_at": 12},
            {"report_created_at": (timezone.now() + timedelta(days=1)).isoformat()},
        ):
            with self.subTest(extra=extra):
                self.assertEqual(self.register(**extra).status_code, 400)
        missing = self.client.get(f"/api/report-actions/{uuid4()}")
        self.assertEqual(missing.status_code, 404)
        self.assertIn("Nothing was submitted", missing.data["error"])
        self.assertEqual(ReportAction.objects.count(), 0)

    def test_explicit_json_confirmation_only(self):
        action = self.actions()[0]
        path = f"/api/report-actions/{action.id}/submit"
        self.assertEqual(self.client.get(path).status_code, 405)
        self.assertEqual(self.client.post(path, {"confirm": "fork"}).status_code, 415)
        self.assertEqual(self.client.post(path, {}, format="json").status_code, 400)
        self.assertEqual(self.submit(action, text="").status_code, 400)
        response = self.client.post(
            path,
            {"confirm": "fork"},
            format="json",
            HTTP_ORIGIN="http://example.invalid",
        )
        self.assertEqual(response.status_code, 403)
        self.adapter.fork_session.assert_not_called()


class ReportMetadataTests(SimpleTestCase):
    @override_settings(MDVIEW_URL="http://localhost:7689/")
    def test_report_links_encode_paths_without_reading_files(self):
        home = Path.home()
        for path, project, expected in (
            ("~/reports/a b#x?.md", str(home), "/~/reports/a%20b%23x%3F.md"),
            (str(home / "reports/x%.md"), str(home), "/~/reports/x%25.md"),
            ("out/report.md", str(home / "work"), "/~/work/out/report.md"),
            ("../report.md", str(home / "work"), "/~/report.md"),
        ):
            with (
                self.subTest(path=path),
                patch(
                    "pathlib.Path.resolve",
                    side_effect=AssertionError("No symlink resolution"),
                ),
                patch(
                    "pathlib.Path.exists", side_effect=AssertionError("No file probes")
                ),
            ):
                self.assertEqual(
                    report_url(path, project), f"http://localhost:7689{expected}"
                )
        self.assertIsNone(report_url("", str(home)))
        self.assertIsNone(
            report_url(str(home.parent / "outside-home/report.md"), str(home))
        )
        self.assertIsNone(report_url("report.md", "relative-project"))

    def test_disabled_or_invalid_mdview_origin_keeps_path_as_text(self):
        for base in (
            "",
            None,
            "javascript:alert(1)",
            "http://localhost:bad",
            "http://localhost:6821?x=1",
            "http://localhost:6821/view",
            "http://user@localhost:6821",
        ):
            with self.subTest(base=base), override_settings(MDVIEW_URL=base):
                self.assertIsNone(report_url("~/reports/file.md", str(Path.home())))

    def test_progressively_stronger_age_bands(self):
        now = timezone.now()
        for days, level, ack in (
            (0, "recent", False),
            (2, "recent", False),
            (3, "aging", False),
            (6, "aging", False),
            (7, "stale", True),
            (29, "stale", True),
            (30, "old", True),
            (365, "old", True),
        ):
            with self.subTest(days=days):
                self.assertEqual(
                    freshness(now - timedelta(days=days), now),
                    {"days": days, "level": level, "requires_acknowledgement": ack},
                )
