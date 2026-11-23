from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tpweb", "0088_fix_site_domain"),
    ]

    operations = [
        migrations.AddField(
            model_name="scoreformula",
            name="shared_with_gates",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="scoreparam",
            name="shared_with_gates",
            field=models.BooleanField(default=False),
        ),
    ]
