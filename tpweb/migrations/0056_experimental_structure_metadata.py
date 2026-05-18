from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("tpweb", "0055_binders_is_direct"),
    ]

    operations = [
        migrations.AddField(
            model_name="bioentrystructure",
            name="chain",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AddField(
            model_name="bioentrystructure",
            name="resolution",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="bioentrystructure",
            name="uniprot_end",
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="bioentrystructure",
            name="uniprot_start",
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.CreateModel(
            name="ExperimentalStructureXref",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("pdb_id", models.CharField(max_length=16)),
                ("method", models.CharField(blank=True, default="", max_length=100)),
                ("resolution", models.FloatField(blank=True, null=True)),
                ("chains", models.CharField(blank=True, default="", max_length=128)),
                ("uniprot_start", models.IntegerField(blank=True, null=True)),
                ("uniprot_end", models.IntegerField(blank=True, null=True)),
                (
                    "bioentry",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="experimental_structure_xrefs",
                        to="bioseq.bioentry",
                    ),
                ),
            ],
        ),
        migrations.AddIndex(
            model_name="experimentalstructurexref",
            index=models.Index(fields=["bioentry", "resolution"], name="tpweb_exper_bioentr_c9a28a_idx"),
        ),
        migrations.AddIndex(
            model_name="experimentalstructurexref",
            index=models.Index(fields=["pdb_id"], name="tpweb_exper_pdb_id_3db47c_idx"),
        ),
        migrations.AlterUniqueTogether(
            name="experimentalstructurexref",
            unique_together={("bioentry", "pdb_id")},
        ),
    ]
