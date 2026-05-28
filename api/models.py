from django.db import models


class ForgePR(models.Model):
    repo = models.CharField(max_length=255)
    branch = models.CharField(max_length=255)
    number = models.IntegerField(null=True)
    url = models.URLField(null=True)
    state = models.CharField(max_length=20, null=True)

    class Meta:
        unique_together = ("repo", "branch")


class ConversationIndex(models.Model):
    conversation_id = models.CharField(max_length=64, unique=True)
    project = models.CharField(max_length=512, default="")
    branch = models.CharField(max_length=255, default="")
    blurb = models.CharField(max_length=200, default="")
    first_timestamp = models.CharField(max_length=64, default="")
    last_timestamp = models.CharField(max_length=64, default="")
    message_count = models.IntegerField(default=0)
    searchable_text = models.TextField(default="")
    file_size = models.BigIntegerField(default=0)
    file_mtime = models.FloatField(default=0)


class CronJob(models.Model):
    skill_name = models.CharField(max_length=255)
    repo = models.CharField(max_length=512)
    cron_expression = models.CharField(max_length=100)
    params = models.TextField(default="", blank=True)
    enabled = models.BooleanField(default=True)
    last_run_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class CronJobRun(models.Model):
    cronjob = models.ForeignKey(CronJob, on_delete=models.CASCADE, related_name="runs")
    conversation_id = models.CharField(max_length=64, blank=True, default="")
    triggered_at = models.DateTimeField(auto_now_add=True)
    trigger_type = models.CharField(max_length=10, default="scheduled")
    pid = models.IntegerField(null=True, blank=True)
