from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tpweb", "0063_metabolism_big_auto_fields"),
    ]

    operations = [
        migrations.AlterField(
            model_name="metabolicreaction",
            name="reaction_id",
            field=models.CharField(max_length=255),
        ),
    ]
