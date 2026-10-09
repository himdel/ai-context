from django.db import models
from django.utils import timezone


class ForgePR(models.Model):
    repo = models.CharField(max_length=255)
    branch = models.CharField(max_length=255)
    number = models.IntegerField(null=True)
    url = models.URLField(null=True)
    state = models.CharField(max_length=20, null=True)
    cached_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("repo", "branch")


class ConversationIndex(models.Model):
    conversation_id = models.CharField(max_length=64, unique=True)
    # Which harness adapter owns this conversation, and - for a subagent - the
    # conversation it ran under. cost_usd and the token counts are this
    # conversation's OWN spend; a parent never includes its children, so summing
    # every row (see the stats view) counts each once.
    source = models.CharField(max_length=32, default="claude")
    parent_id = models.CharField(max_length=64, default="", db_index=True)
    agent_type = models.CharField(max_length=64, default="")
    # Opaque staleness token from the adapter - size+mtime for a file, an
    # updated-at plus row count for a database.
    revision = models.CharField(max_length=64, default="")
    project = models.CharField(max_length=512, default="")
    branch = models.CharField(max_length=255, default="")
    blurb = models.CharField(max_length=200, default="")
    first_timestamp = models.CharField(max_length=64, default="")
    last_timestamp = models.CharField(max_length=64, default="")
    message_count = models.IntegerField(default=0)
    searchable_text = models.TextField(default="")
    cost_usd = models.FloatField(default=0.0)
    input_tokens = models.BigIntegerField(default=0)
    output_tokens = models.BigIntegerField(default=0)
    cache_read_tokens = models.BigIntegerField(default=0)
    cache_write_tokens = models.BigIntegerField(default=0)


class CronJob(models.Model):
    BACKEND_INTERNAL = "internal"
    BACKEND_SYSTEMD = "systemd"
    BACKEND_CHOICES = (
        (BACKEND_INTERNAL, "Contexts process"),
        (BACKEND_SYSTEMD, "systemd user timer"),
    )

    skill_name = models.CharField(max_length=255)
    repo = models.CharField(max_length=512)
    cron_expression = models.CharField(max_length=100)
    params = models.TextField(default="", blank=True)
    natural_language = models.BooleanField(default=False)
    enabled = models.BooleanField(default=True)
    backend = models.CharField(
        max_length=16, choices=BACKEND_CHOICES, default=BACKEND_SYSTEMD
    )
    runner = models.CharField(max_length=32, default="claude")
    agent = models.CharField(max_length=128, default="", blank=True)
    model = models.CharField(max_length=255, default="", blank=True)
    effort = models.CharField(max_length=16, default="", blank=True)
    last_run_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class CronJobRun(models.Model):
    cronjob = models.ForeignKey(CronJob, on_delete=models.CASCADE, related_name="runs")
    conversation_id = models.CharField(max_length=64, blank=True, default="")
    triggered_at = models.DateTimeField(auto_now_add=True)
    trigger_type = models.CharField(max_length=10, default="scheduled")
    pid = models.IntegerField(null=True, blank=True)
    tmux_session = models.CharField(max_length=128, blank=True, default="")
    status = models.CharField(max_length=16, default="started")
    error = models.TextField(blank=True, default="")


class LaunchedSession(models.Model):
    """A tmux session this app started, and the conversation it works in.

    Claude writes a session file keyed by pid, so its conversation can be read
    off the process itself. No other harness does, and opencode has nothing we
    can read at all - so for those, the link only exists because we recorded
    the launch. `conversation_id` is blank until the harness commits one; see
    `_resolve_launched_sessions` in views.

    Rows are pruned when their tmux session dies, so this stays small.

    A session started from a shell rather than from here is adopted on sight
    (`_adopt_tmux_sessions`), which is why `started_at` is settable rather than
    `auto_now_add` - an adopted row takes tmux's own creation time, not the
    moment we noticed it.
    """

    tmux_session = models.CharField(max_length=128, unique=True)
    source = models.CharField(max_length=32, default="claude")
    cwd = models.CharField(max_length=512, default="")
    conversation_id = models.CharField(max_length=64, blank=True, default="")
    started_at = models.DateTimeField(default=timezone.now)
