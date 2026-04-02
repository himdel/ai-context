from django.db import models


class GitHubPR(models.Model):
    repo = models.CharField(max_length=255)
    branch = models.CharField(max_length=255)
    number = models.IntegerField(null=True)
    url = models.URLField(null=True)
    state = models.CharField(max_length=20, null=True)

    class Meta:
        unique_together = ("repo", "branch")
