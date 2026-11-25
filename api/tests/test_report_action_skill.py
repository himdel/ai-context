import argparse
import importlib.util
import json
import os
from contextlib import redirect_stdout
from io import BytesIO, StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

HELPER = (
    Path(__file__).resolve().parents[2] / "contrib/skills/report-actions/register.py"
)
spec = importlib.util.spec_from_file_location("register_report_action", HELPER)
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)


class RegistrationHelperTests(SimpleTestCase):
    def test_only_loopback_origins(self):
        for value in (
            "http://localhost:8062",
            "http://127.0.0.1:8063/",
            "http://[::1]:8062",
        ):
            self.assertEqual(helper.local_base(value), value.rstrip("/"))
        for value in (
            "http://192.168.0.8:8062",
            "http://example.invalid",
            "file:///etc/passwd",
            "http://localhost:8062/actions/anything",
            "http://localhost:bad",
            "http://user@localhost:8062",
            "http://localhost:8062?x=1",
            "http://localhost:8062#x",
        ):
            with (
                self.subTest(value=value),
                self.assertRaises(argparse.ArgumentTypeError),
            ):
                helper.local_base(value)

    def test_register_only_and_print_markdown(self):
        with TemporaryDirectory() as directory:
            payload = Path(directory) / "proposals.json"
            payload.write_text(
                json.dumps(
                    {
                        "title": "Review",
                        "actions": [{"label": "Review", "text": "Review only."}],
                    }
                )
            )
            response = BytesIO(
                json.dumps(
                    {
                        "mode": "independent",
                        "conversation_url": "http://localhost:8062/conversations/ses_current",
                        "actions": [
                            {
                                "label": "Review [carefully]",
                                "url": "http://localhost:8062/actions/inert",
                            }
                        ],
                    }
                ).encode()
            )
            opener = Mock()
            opener.open.return_value = response
            out = StringIO()
            with (
                patch.dict(
                    os.environ, {"OPENCODE_SESSION_ID": "ses_current"}, clear=True
                ),
                patch("sys.argv", ["register.py", str(payload)]),
                patch.object(
                    helper.urllib.request, "build_opener", return_value=opener
                ),
                redirect_stdout(out),
            ):
                self.assertEqual(helper.main(), 0)
            request = opener.open.call_args.args[0]
            self.assertEqual(
                request.full_url, "http://localhost:8062/api/report-actions"
            )
            self.assertNotIn("submit", request.full_url)
            data = json.loads(request.data)
            self.assertEqual(data["conversation_id"], "ses_current")
            self.assertEqual(data["source"], "opencode")
            self.assertIn(r"Review \[carefully\]", out.getvalue())
            self.assertIn(
                "Originating session: [ses_current](<http://localhost:8062/conversations/ses_current>)",
                out.getvalue(),
            )
            opener.open.assert_called_once()

    def test_provenance_without_actions_makes_no_http_requests(self):
        out = StringIO()
        with (
            patch.dict(os.environ, {}, clear=True),
            patch(
                "sys.argv",
                [
                    "register.py",
                    "--provenance-only",
                    "--source",
                    "claude",
                    "--conversation",
                    "exact-session",
                    "--base-url",
                    "http://localhost:8063",
                ],
            ),
            patch.object(helper.urllib.request, "build_opener") as opener,
            redirect_stdout(out),
        ):
            self.assertEqual(helper.main(), 0)
        self.assertEqual(
            out.getvalue().strip(),
            "Originating session: [exact-session](<http://localhost:8063/conversations/exact-session>)",
        )
        opener.assert_not_called()
