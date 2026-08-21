"""Autodetect platform capabilities for launching Claude sessions.

Resolves sensible defaults for the terminal/session substrate so the app works
zero-config on the current machine. Every value here can be overridden in
contexts/settings_local[_<instance>].py (explicit overrides always win).
"""

import os
import shutil
import sys


def _platform():
    if sys.platform == "darwin":
        return "mac"
    if sys.platform.startswith("linux"):
        return "linux"
    return "other"


PLATFORM = _platform()

# tmux is the default session substrate; the app falls back to launching the
# terminal directly when it is missing.
HAS_TMUX = shutil.which("tmux") is not None

# X11/Wayland display (Linux only), used solely by the viewer terminal.
TERMINAL_DISPLAY = os.environ.get("DISPLAY", "" if PLATFORM == "mac" else ":0")

# Whether a GUI is available to pop a viewer window.
if PLATFORM == "mac":
    HAS_GUI = True
elif PLATFORM == "linux":
    HAS_GUI = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
else:
    HAS_GUI = False


def _terminal_cmd():
    """Linux viewer prefix, appended with the command to run (e.g. `-e cmd`)."""
    term = os.environ.get("TERMINAL")
    if term and shutil.which(term):
        return [term, "-e"]
    for cand in ("rxvt-unicode", "xterm"):
        if shutil.which(cand):
            return [cand, "-e"]
    return None


def _mac_app():
    for app in ("iTerm", "Terminal"):
        if os.path.isdir(f"/Applications/{app}.app"):
            return app
    return "Terminal"


def _notifier():
    if PLATFORM == "mac":
        return "osascript" if shutil.which("osascript") else None
    return "notify-send" if shutil.which("notify-send") else None


if PLATFORM == "mac":
    # macOS terminals have no command-taking CLI on PATH, so the viewer is
    # launched via osascript against the app instead of a `-e` style prefix.
    TERMINAL_KIND = "mac"
    TERMINAL_CMD = None
    TERMINAL_APP = _mac_app()
else:
    TERMINAL_KIND = "prefix"
    TERMINAL_CMD = _terminal_cmd()
    TERMINAL_APP = None

NOTIFIER = _notifier()
