from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("human_target", "0003_humanpathway_humanproteinpathway"),
    ]

    operations = [
        migrations.AlterField(
            model_name="humanprotein",
            name="gene_symbol",
            field=models.CharField(blank=True, db_index=True, default="", max_length=64),
        ),
    ]
