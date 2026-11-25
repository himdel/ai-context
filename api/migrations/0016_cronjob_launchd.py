import api.models
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("api", "0015_report_actions"),
    ]

    operations = [
        migrations.AlterField(
            model_name="cronjob",
            name="backend",
            field=models.CharField(
                choices=[
                    ("internal", "Contexts process"),
                    ("systemd", "systemd user timer"),
                    ("launchd", "launchd user agent"),
                ],
                default=api.models.default_cron_backend,
                max_length=16,
            ),
        ),
    ]
