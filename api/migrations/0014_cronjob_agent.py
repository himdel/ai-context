from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("api", "0013_cronjob_natural_language"),
    ]

    operations = [
        migrations.AddField(
            model_name="cronjob",
            name="agent",
            field=models.CharField(blank=True, default="", max_length=128),
        ),
    ]
