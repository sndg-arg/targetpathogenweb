from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("human_target", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="humanprotein",
            name="expression_json",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
