from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("api", "0010_alter_launchedsession_started_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="cronjob",
            name="backend",
            field=models.CharField(
                choices=[
                    ("auto", "Automatic"),
                    ("internal", "Contexts process"),
                    ("systemd", "systemd user timer"),
                ],
                default="auto",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="cronjob",
            name="effort",
            field=models.CharField(blank=True, default="", max_length=16),
        ),
        migrations.AddField(
            model_name="cronjob",
            name="model",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="cronjob",
            name="runner",
            field=models.CharField(default="claude", max_length=32),
        ),
        migrations.AddField(
            model_name="cronjobrun",
            name="error",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="cronjobrun",
            name="status",
            field=models.CharField(default="started", max_length=16),
        ),
    ]
