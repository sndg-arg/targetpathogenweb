from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tpweb", "0051_alter_binders_smiles"),
    ]

    operations = [
        migrations.AlterField(
            model_name="binders",
            name="pdb_id",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AlterField(
            model_name="binders",
            name="uniprot",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="binders",
            name="source",
            field=models.CharField(
                choices=[("pdb", "PDB"), ("proposed", "Proposed")],
                db_index=True,
                default="pdb",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="binders",
            name="score",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="binders",
            name="notes",
            field=models.TextField(blank=True, default=""),
        ),
    ]
