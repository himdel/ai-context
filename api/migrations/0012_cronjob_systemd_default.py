from django.db import migrations, models


def move_auto_jobs_to_systemd(apps, schema_editor):
    CronJob = apps.get_model("api", "CronJob")
    CronJob.objects.filter(backend="auto").update(backend="systemd")


class Migration(migrations.Migration):
    dependencies = [
        ("api", "0011_cronjob_systemd_runner"),
    ]

    operations = [
        migrations.RunPython(move_auto_jobs_to_systemd, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="cronjob",
            name="backend",
            field=models.CharField(
                choices=[
                    ("internal", "Contexts process"),
                    ("systemd", "systemd user timer"),
                ],
                default="systemd",
                max_length=16,
            ),
        ),
    ]
