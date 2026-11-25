from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from api.views import _spawn_session


class SessionLaunchTests(SimpleTestCase):
    @override_settings(USE_TMUX=True)
    def test_new_session_race_never_reuses_or_sends_to_live_session(self):
        with (
            patch("api.views._resolve_cmd", return_value=["opencode"]),
            patch("api.views._tmux_session_name", return_value="ctx-claimed"),
            patch("api.views._clean_env", return_value={}),
            patch("api.views._tmux_sessions", return_value={"ctx-claimed": 1}),
            patch("api.views._tmux_send") as send,
        ):
            response = _spawn_session(
                ["opencode"], "/work", prompt="must not reach live session"
            )
            self.assertEqual(response.status_code, 409)
            send.assert_not_called()
