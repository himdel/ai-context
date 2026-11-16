from unittest import mock

from django.db import OperationalError
from django.test import SimpleTestCase

from api.models import LaunchedSession
from api.views import _record_launch


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
