"""Regression coverage for OpenCode's two on-disk session formats."""

import json
import sqlite3
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from rest_framework.response import Response
from rest_framework.test import APIRequestFactory
from django.test import SimpleTestCase, override_settings

from api.harness.opencode import OpencodeHarness
from api.views import session_fork


class OpencodeHarnessTests(SimpleTestCase):
    def setUp(self):
        self.tempdir = TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.path = Path(self.tempdir.name) / "opencode.db"
        self.settings = override_settings(OPENCODE_DB=self.path)
        self.settings.enable()
        self.addCleanup(self.settings.disable)
        self.adapter = OpencodeHarness()

    def test_v1_only_database(self):
        with sqlite3.connect(self.path) as conn:
            conn.executescript(
                "create table session (id text, parent_id text, agent text,"
                " time_updated integer, time_created integer, directory text,"
                " title text, version text, model text, cost real,"
                " tokens_input integer, tokens_output integer,"
                " tokens_reasoning integer, tokens_cache_read integer,"
                " tokens_cache_write integer);"
                "create table message (id text, session_id text, data text,"
                " time_created integer);"
                "create table part (id text, message_id text, data text);"
            )
            conn.execute(
                "insert into session values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    "ses_old",
                    None,
                    "build",
                    2000,
                    1000,
                    "/work",
                    "old",
                    "1.18",
                    "{}",
                    1,
                    2,
                    3,
                    4,
                    5,
                    6,
                ),
            )
            conn.execute(
                "insert into message values (?,?,?,?)",
                (
                    "msg_old",
                    "ses_old",
                    json.dumps({"role": "user", "time": {"created": 1000}}),
                    1000,
                ),
            )
            conn.execute(
                "insert into part values (?,?,?)",
                ("part_old", "msg_old", json.dumps({"type": "text", "text": "hello"})),
            )
        refs = list(self.adapter.list_refs())
        self.assertEqual([ref.id for ref in refs], ["ses_old"])
        self.assertEqual(self.adapter.identify("/work", 1000), "ses_old")
        conv = self.adapter.load("ses_old")
        self.assertEqual(conv.messages[0].blocks[0]["text"], "hello")
        self.assertEqual(conv.output_tokens, 7)
        self.assertIsNone(self.adapter.fork_session("ses_old"))

    def test_v2_sessions_and_migrated_v1_ids(self):
        with sqlite3.connect(self.path) as conn:
            conn.executescript(
                "create table session (id text, parent_id text, agent text,"
                " time_updated integer, time_created integer, directory text,"
                " title text, version text, model text, cost real,"
                " tokens_input integer, tokens_output integer,"
                " tokens_reasoning integer, tokens_cache_read integer,"
                " tokens_cache_write integer);"
                "create table message (id text, session_id text, data text,"
                " time_created integer);"
                "create table part (id text, message_id text, data text);"
                "create table session_v2 (id text, parent_id text, agent text,"
                " time_updated integer, time_created integer, directory text,"
                " title text, version text, model text, cost real,"
                " tokens_input integer, tokens_output integer,"
                " tokens_reasoning integer, tokens_cache_read integer,"
                " tokens_cache_write integer);"
                "create table session_message (id text, session_id text, type text,"
                " seq integer, data text);"
            )
            for sid in ("ses_migrated", "ses_unmigrated"):
                conn.execute(
                    "insert into session values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        sid,
                        None,
                        "",
                        1000,
                        1000,
                        "/work",
                        sid,
                        "1.18",
                        "{}",
                        0,
                        0,
                        0,
                        0,
                        0,
                        0,
                    ),
                )
            for sid, parent, agent, created in (
                ("ses_migrated", None, "", 1000),
                ("ses_new", None, "build", 2000),
                ("ses_child", "ses_new", "explore", 2100),
            ):
                conn.execute(
                    "insert into session_v2 values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        sid,
                        parent,
                        agent,
                        created,
                        created,
                        "/work",
                        sid,
                        "2.0.26",
                        '{"id":"model"}',
                        0.5,
                        1,
                        2,
                        3,
                        4,
                        5,
                    ),
                )
            for mid, sid, typ, seq, data in (
                (
                    "u",
                    "ses_new",
                    "user",
                    1,
                    {"text": "question", "time": {"created": 2000}},
                ),
                (
                    "a",
                    "ses_new",
                    "assistant",
                    2,
                    {
                        "time": {"created": 2010},
                        "content": [
                            {"type": "reasoning", "text": "thinking"},
                            {
                                "type": "tool",
                                "name": "task",
                                "state": {
                                    "status": "completed",
                                    "input": {"description": "look"},
                                    "metadata": {"sessionId": "ses_child"},
                                    "content": [{"type": "text", "text": "done"}],
                                },
                            },
                        ],
                    },
                ),
                (
                    "b",
                    "ses_new",
                    "assistant",
                    3,
                    {
                        "time": {"created": 2020},
                        "content": [{"type": "text", "text": "answer"}],
                    },
                ),
                (
                    "c",
                    "ses_child",
                    "assistant",
                    4,
                    {
                        "time": {"created": 2110},
                        "content": [{"type": "text", "text": "child answer"}],
                    },
                ),
            ):
                conn.execute(
                    "insert into session_message values (?,?,?,?,?)",
                    (mid, sid, typ, seq, json.dumps(data)),
                )
        refs = list(self.adapter.list_refs())
        self.assertEqual(
            {ref.id for ref in refs},
            {"ses_migrated", "ses_unmigrated", "ses_new", "ses_child"},
        )
        self.assertEqual(len(refs), 4)
        self.assertTrue(
            next(r for r in refs if r.id == "ses_migrated").revision.startswith(
                "session_v2:"
            )
        )
        self.assertTrue(
            next(r for r in refs if r.id == "ses_unmigrated").revision.startswith(
                "session:"
            )
        )
        self.assertEqual(self.adapter.load("ses_unmigrated").version, "1.18")
        self.assertEqual(self.adapter.identify("/work", 1900), "ses_new")
        conv = self.adapter.load("ses_new")
        self.assertEqual(conv.version, "2.0.26")
        self.assertEqual(len(conv.messages), 2)
        self.assertEqual(conv.messages[0].blocks[0]["text"], "question")
        self.assertEqual(conv.messages[1].blocks[-1]["text"], "answer")
        tool = conv.messages[1].blocks[1]
        self.assertEqual(tool["name"], "Agent")
        self.assertEqual(tool["result"], "done")
        self.assertEqual(
            tool["subagent"]["messages"][0]["content"][0]["text"], "child answer"
        )
        self.assertEqual(conv.output_tokens, 5)

        with patch("api.harness.opencode.subprocess.run") as run:
            run.return_value = subprocess.CompletedProcess(
                [], 0, '{"data":{"id":"ses_forked"}}', ""
            )
            self.assertEqual(self.adapter.fork_session("ses_new"), "ses_forked")
            run.assert_called_once()
            argv = run.call_args.args[0]
            self.assertEqual(
                argv[1:], ["api", "post", "/api/session/ses_new/fork", "--data", "{}"]
            )
            self.assertEqual(
                self.adapter.launch_argv(conversation_id="ses_forked"),
                ["opencode", "run", "--session", "ses_forked"],
            )
            run.return_value = subprocess.CompletedProcess([], 0, '{"data":{}}', "")
            with self.assertRaisesRegex(RuntimeError, "no session ID"):
                self.adapter.fork_session("ses_new")
        with self.assertRaisesRegex(RuntimeError, "not available"):
            self.adapter.fork_session("ses_unmigrated")

    def test_v2_fork_launches_exact_api_id_and_fails_closed(self):
        request = APIRequestFactory().post(
            "/api/sessions/fork", {"conversation_id": "ses_new"}
        )
        with (
            patch(
                "api.views._resume_target",
                return_value=(self.adapter, "ses_new", "/work"),
            ),
            patch(
                "api.views.harness.launch_argv",
                return_value=["opencode", "run", "--session", "ses_forked"],
            ),
            patch.object(self.adapter, "fork_session", return_value="ses_forked"),
            patch(
                "api.views._spawn_session", return_value=Response({"status": "ok"})
            ) as spawn,
        ):
            self.assertEqual(session_fork(request).status_code, 200)
            spawn.assert_called_once_with(
                ["opencode", "run", "--session", "ses_forked"],
                "/work",
                source="opencode",
                conversation_id="ses_forked",
            )

        with (
            patch(
                "api.views._resume_target",
                return_value=(self.adapter, "ses_old", "/work"),
            ),
            patch.object(self.adapter, "fork_session", return_value=None),
            patch(
                "api.views.harness.launch_argv",
                return_value=["opencode", "run", "--session", "ses_old", "--fork"],
            ) as launch,
            patch(
                "api.views._spawn_session", return_value=Response({"status": "ok"})
            ) as spawn,
        ):
            self.assertEqual(session_fork(request).status_code, 200)
            launch.assert_called_once_with(
                "opencode", conversation_id="ses_old", fork=True
            )
            spawn.assert_called_once_with(
                ["opencode", "run", "--session", "ses_old", "--fork"],
                "/work",
                source="opencode",
            )

        with (
            patch(
                "api.views._resume_target",
                return_value=(self.adapter, "ses_new", "/work"),
            ),
            patch.object(
                self.adapter,
                "fork_session",
                side_effect=RuntimeError("service unavailable"),
            ),
            patch("api.views._spawn_session") as spawn,
            self.assertLogs("api.views", level="ERROR"),
        ):
            self.assertEqual(session_fork(request).status_code, 502)
            spawn.assert_not_called()
