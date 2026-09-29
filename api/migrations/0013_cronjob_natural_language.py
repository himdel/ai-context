from django.db import migrations, models


def enable_natural_language_for_opencode(apps, schema_editor):
    CronJob = apps.get_model("api", "CronJob")
    CronJob.objects.filter(runner="opencode").update(natural_language=True)


class Migration(migrations.Migration):
    dependencies = [
        ("api", "0012_cronjob_systemd_default"),
    ]

    operations = [
        migrations.AddField(
            model_name="cronjob",
            name="natural_language",
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(
            enable_natural_language_for_opencode, migrations.RunPython.noop
        ),
    ]
