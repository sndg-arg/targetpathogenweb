from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tpweb", "0064_metabolic_reaction_id_length"),
    ]

    operations = [
        migrations.AddField(
            model_name="metabolicreaction",
            name="isoenzyme_count",
            field=models.PositiveSmallIntegerField(default=0),
        ),
    ]
