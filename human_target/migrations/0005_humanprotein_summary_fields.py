from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("human_target", "0004_humanprotein_gene_symbol_index"),
    ]

    operations = [
        migrations.AddField(
            model_name="humanprotein",
            name="structure_count",
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name="humanprotein",
            name="experimental_structure_count",
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name="humanprotein",
            name="ligand_count",
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name="humanprotein",
            name="direct_ligand_count",
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name="humanprotein",
            name="drugbank_count",
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name="humanprotein",
            name="disease_count",
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name="humanprotein",
            name="pathway_count",
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name="humanprotein",
            name="tissue_specificity",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="humanprotein",
            name="peak_tissue",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="humanprotein",
            name="surface_accessible",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="humanprotein",
            name="summary_updated_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
