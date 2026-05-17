from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tpweb", "0054_scoreformula_expression"),
    ]

    operations = [
        migrations.AddField(
            model_name="binders",
            name="is_direct",
            field=models.BooleanField(
                default=False,
                db_index=True,
                help_text="True when the template protein's UniProt matches this protein's own UniProt.",
            ),
        ),
    ]
