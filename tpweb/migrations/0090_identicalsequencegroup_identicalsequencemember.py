from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("bioseq", "0009_alter_term_identifier_alter_term_name"),
        ("tpweb", "0089_formula_and_param_sharing"),
    ]

    operations = [
        migrations.CreateModel(
            name="IdenticalSequenceGroup",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("source_note", models.CharField(blank=True, default="", max_length=255)),
            ],
        ),
        migrations.CreateModel(
            name="IdenticalSequenceMember",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("strain_label", models.CharField(max_length=64)),
                ("locus_tag", models.CharField(max_length=128)),
                ("protein_accession", models.CharField(blank=True, default="", max_length=128)),
                (
                    "bioentry",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="identical_sequence_memberships",
                        to="bioseq.bioentry",
                    ),
                ),
                (
                    "group",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="members",
                        to="tpweb.identicalsequencegroup",
                    ),
                ),
            ],
        ),
        migrations.AddIndex(
            model_name="identicalsequencemember",
            index=models.Index(fields=["bioentry"], name="tpweb_ident_bioentr_idx"),
        ),
        migrations.AddConstraint(
            model_name="identicalsequencemember",
            constraint=models.UniqueConstraint(
                fields=("strain_label", "locus_tag"),
                name="tpweb_identicalseqmember_strain_locus_unique",
            ),
        ),
    ]
