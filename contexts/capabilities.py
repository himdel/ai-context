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


# How each terminal we know about wants a command handed to it: the flag that
# goes last, before the command. "" means "just append the argv". They do not
# agree, and `-e` is not the safe guess it looks like - Ptyxis wants `--`,
# xfce4-terminal wants `-x`, kitty and foot want nothing at all. A wrong flag
# is a viewer window that never opens, with the error inside the window that
# never opened.
#
# Order is the PATH search order too. Debian's `x-terminal-emulator` answers
# for whichever terminal is actually installed, so it goes first; xterm is the
# last resort it usually resolves to anyway.
TERMINAL_EXEC = {
    "x-terminal-emulator": "-e",
    "ptyxis": "--",
    "ghostty": "-e",
    "kitty": "",
    "foot": "",
    "wezterm": "start --",
    "alacritty": "-e",
    "kgx": "--",  # GNOME Console
    "gnome-terminal": "--",
    "konsole": "-e",
    "xfce4-terminal": "-x",
    "rxvt-unicode": "-e",
    "urxvt": "-e",
    "xterm": "-e",
}

# Terminals that expand `$VAR` in the command line they are handed, before the
# child ever sees it. Ptyxis does: an undefined name becomes the empty string,
# and the empty argument is then dropped from the argv entirely. `terminal/run`
# passes a command through from the UI, so a `$` in one would arrive mangled or
# not arrive at all. Doubling the dollar is Ptyxis's own escape.
TERMINAL_EXPANDS_VARS = frozenset({"ptyxis"})


def _terminal_cmd():
    """Linux viewer prefix, appended with the command to run (e.g. `-e cmd`)."""
    term = os.environ.get("TERMINAL")
    for cand in ([term] if term else []) + list(TERMINAL_EXEC):
        if shutil.which(cand):
            return [cand, *TERMINAL_EXEC.get(os.path.basename(cand), "-e").split()]
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

# Whether the command handed to the viewer needs its dollars doubled first.
TERMINAL_ESCAPE_DOLLARS = bool(
    TERMINAL_CMD and os.path.basename(TERMINAL_CMD[0]) in TERMINAL_EXPANDS_VARS
)

NOTIFIER = _notifier()
