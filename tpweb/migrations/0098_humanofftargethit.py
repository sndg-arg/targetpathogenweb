import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("bioseq", "0009_alter_term_identifier_alter_term_name"),
        ("tpweb", "0097_tpuser_role_gr_adi_labels"),
    ]

    operations = [
        migrations.CreateModel(
            name="HumanOfftargetHit",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("human_accession", models.CharField(max_length=32)),
                ("human_entry_name", models.CharField(blank=True, default="", max_length=64)),
                ("identity", models.FloatField()),
                ("evalue", models.FloatField()),
                ("bitscore", models.FloatField(blank=True, null=True)),
                ("alignment_length", models.IntegerField(blank=True, null=True)),
                ("query_start", models.IntegerField(blank=True, null=True)),
                ("query_end", models.IntegerField(blank=True, null=True)),
                ("subject_start", models.IntegerField(blank=True, null=True)),
                ("subject_end", models.IntegerField(blank=True, null=True)),
                ("query_coverage", models.FloatField(blank=True, null=True)),
                (
                    "bioentry",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="human_offtarget_hits",
                        to="bioseq.bioentry",
                    ),
                ),
            ],
            options={
                "indexes": [models.Index(fields=["bioentry"], name="tpweb_humhit_bioentry_idx")],
                "unique_together": {("bioentry", "human_accession")},
            },
        ),
    ]
