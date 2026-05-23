from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tpweb", "0052_binders_source_score_notes"),
    ]

    operations = [
        migrations.AlterField(
            model_name="binders",
            name="source",
            field=models.CharField(
                choices=[("pdb", "PDB"), ("chembl", "ChEMBL"), ("proposed", "ZINC")],
                db_index=True,
                default="pdb",
                max_length=16,
            ),
        ),
    ]
