from django.conf import settings
from django.contrib.staticfiles.management.commands.runserver import (
    Command as RunserverCommand,
)


class Command(RunserverCommand):
    """runserver, listening on settings.BIND when given only a port.

    Overrides staticfiles' runserver, so "api" must come before
    "django.contrib.staticfiles" in INSTALLED_APPS.
    """

    @property
    def default_addr(self):
        return settings.BIND
