import importlib
from pathlib import Path
import os
import re


BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = "dev-only-not-secret"

DEBUG = True

ALLOWED_HOSTS = ["localhost", "127.0.0.1"]

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.staticfiles",
    "rest_framework",
    "api",
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

# Terminal emulator command for launching Claude Code sessions from the UI.
# The prompt or --resume args are appended to this list.
TERMINAL_CMD = ["rxvt-unicode", "-e"]
TERMINAL_DISPLAY = ":0"

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
    pass
