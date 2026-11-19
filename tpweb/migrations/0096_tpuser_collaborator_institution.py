from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tpweb", "0095_ligandrouteplan"),
    ]

    operations = [
        migrations.AddField(
            model_name="tpuser",
            name="collaborator_institution",
            field=models.CharField(blank=True, max_length=255, verbose_name="Institution"),
        ),
    ]
