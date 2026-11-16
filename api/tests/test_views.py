from unittest import mock

from django.db import OperationalError
from django.test import SimpleTestCase

from api.models import LaunchedSession
from api.views import _record_launch, _wait_for_tmux_start


class LaunchRecordTests(SimpleTestCase):
    @mock.patch.object(LaunchedSession.objects, "update_or_create")
    @mock.patch("api.views.close_old_connections")
    @mock.patch("api.views.time.sleep")
    def test_retries_transient_database_lock(
        self, sleep, close_old_connections, update_or_create
    ):
        update_or_create.side_effect = [OperationalError("database is locked"), None]

        _record_launch("ctx-test-opencode", "opencode", "/tmp/repo")

        self.assertEqual(update_or_create.call_count, 2)
        sleep.assert_called_once_with(0.1)
        close_old_connections.assert_called_once_with()

    @mock.patch("api.views._tmux_sessions")
    @mock.patch("api.views.time.sleep")
    @mock.patch("api.views.time.monotonic", side_effect=[0, 0, 0.5])
    def test_rejects_a_pane_that_dies_during_startup(
        self, monotonic, sleep, tmux_sessions
    ):
        tmux_sessions.side_effect = [{"ctx-test": 123}, {"ctx-test": 123}, {}]

        self.assertFalse(_wait_for_tmux_start("ctx-test"))
        self.assertEqual(tmux_sessions.call_count, 3)
        self.assertEqual(sleep.call_count, 2)
