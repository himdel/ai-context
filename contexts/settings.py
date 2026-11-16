import importlib
from pathlib import Path
import os
import re

from contexts import capabilities


BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = "dev-only-not-secret"

DEBUG = True

ALLOWED_HOSTS = ["localhost", "127.0.0.1"]

# Address `make run` listens on. Loopback by default; set "0.0.0.0" in
# settings_local to reach contexts from other machines. There is no auth, and
# the API launches agents that run commands, so only do that on a network you
# trust. Any other address also turns off the Host header check (ALLOWED_HOSTS
# becomes ["*"]) unless settings_local sets ALLOWED_HOSTS itself.
BIND = "127.0.0.1"

# "api" before staticfiles: its runserver (which honors BIND) must win.
INSTALLED_APPS = [
    "api",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.staticfiles",
    "rest_framework",
]

MIDDLEWARE = [
    "django.middleware.common.CommonMiddleware",
]

ROOT_URLCONF = "contexts.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
    },
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
        # Several persistent cron services can catch up together after resume.
        # Let short writer contention clear before reporting a lock error.
        "OPTIONS": {"timeout": 30},
    }
}

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]

APPEND_SLASH = True

# Autolink patterns: list of (prefix, url_template) tuples.
# "AAP-123" in text becomes a link to url_template with {id} replaced.
AUTOLINKS = [
    ("AAP-", "https://redhat.atlassian.net/browse/AAP-{id}"),
    ("ANSTRAT-", "https://redhat.atlassian.net/browse/ANSTRAT-{id}"),
    (
        "ansible/metrics-utility#",
        "https://github.com/ansible/metrics-utility/pull/{id}",
    ),
    (
        "ansible/metrics-service#",
        "https://github.com/ansible/metrics-service/pull/{id}",
    ),
]

# Additional forge domain mappings for self-hosted instances.
# Maps hostname to forge type: "github", "gitlab", or "gitea".
# Example: {"gitlab.corp.com": "gitlab", "git.example.org": "gitea"}
FORGE_DOMAINS = {}

_localtime = os.readlink("/etc/localtime") if os.path.islink("/etc/localtime") else ""
_match = re.search(r"zoneinfo/(.+)$", _localtime)
TIME_ZONE = _match.group(1) if _match else "UTC"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
        },
    },
    "loggers": {
        "api": {
            "handlers": ["console"],
            "level": "INFO",
        },
    },
}

# Path to the Claude Code data directory (~/.claude).
CLAUDE_DIR = Path.home() / ".claude"
CLAUDE_CMD = "claude"

# Which harness adapters to read conversations from, in order. Conversations
# from all of them land in one list, grouped by directory and sorted by date -
# this is not the work/personal split, which is CONTEXTS_INSTANCE. An adapter
# whose data is absent is skipped silently, so listing one costs nothing.
# See docs/HARNESSES.md.
HARNESSES = ["claude"]

# opencode's database. Read-only and never written; see api/harness/opencode.py.
OPENCODE_DB = Path.home() / ".local/share/opencode/opencode.db"
OPENCODE_CMD = "opencode"
# Optional metadata written by the contexts opencode plugin. Read-only; when
# absent, the adapter falls back to the current checkout branch.
OPENCODE_CONTEXT_CACHE_DIR = Path.home() / ".cache/opencode-contexts"

# Session substrate + viewer defaults, autodetected for the current machine.
# All of these can be overridden in settings_local (see below).
#
#   USE_TMUX        - run Claude inside a headless tmux session (default when
#                     tmux is installed); falls back to a plain terminal spawn.
#   TERMINAL_VIEWER - also pop a terminal window attached to the session.
#   TERMINAL_KIND   - "prefix" (Linux, TERMINAL_CMD + argv) or "mac" (osascript).
#   TERMINAL_CMD    - Linux viewer prefix, e.g. ["ptyxis", "--"].
#   TERMINAL_ESCAPE_DOLLARS - the terminal eats `$VAR` in the command; double it.
#   TERMINAL_APP    - macOS terminal app name (e.g. "Terminal", "iTerm").
#   TERMINAL_DISPLAY- X11/Wayland display for the viewer (Linux).
#   NOTIFIER        - "notify-send" (Linux), "osascript" (macOS), or None.
USE_TMUX = capabilities.HAS_TMUX
TERMINAL_VIEWER = capabilities.HAS_GUI
TERMINAL_KIND = capabilities.TERMINAL_KIND
TERMINAL_CMD = capabilities.TERMINAL_CMD
TERMINAL_ESCAPE_DOLLARS = capabilities.TERMINAL_ESCAPE_DOLLARS
TERMINAL_APP = capabilities.TERMINAL_APP
TERMINAL_DISPLAY = capabilities.TERMINAL_DISPLAY
NOTIFIER = capabilities.NOTIFIER

# Prefix for tmux session names created from the UI.
TMUX_SESSION_PREFIX = "ctx"

_instance = os.environ.get("CONTEXTS_INSTANCE", "")
if _instance:
    DATABASES["default"]["NAME"] = BASE_DIR / f"db_{_instance}.sqlite3"

_local_module = (
    f"contexts.settings_local_{_instance}" if _instance else "contexts.settings_local"
)
try:
    _mod = importlib.import_module(_local_module)
    for _k in dir(_mod):
        if _k.isupper():
            globals()[_k] = getattr(_mod, _k)
except ImportError:
    _mod = None

if BIND not in ("127.0.0.1", "localhost") and not hasattr(_mod, "ALLOWED_HOSTS"):
    ALLOWED_HOSTS = ["*"]
