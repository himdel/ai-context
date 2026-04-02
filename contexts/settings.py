from pathlib import Path

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

# Terminal emulator command for launching Claude Code sessions from the UI.
# The prompt or --resume args are appended to this list.
TERMINAL_CMD = ["rxvt-unicode", "-e"]
TERMINAL_DISPLAY = ":0"
