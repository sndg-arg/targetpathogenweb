from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("tpweb", "0066_metabolicimportrun"),
    ]

    operations = [
        migrations.CreateModel(
            name="MetabolicSpecies",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("genome_accession", models.CharField(db_index=True, max_length=128)),
                ("species_id", models.CharField(max_length=255)),
                ("display_name", models.CharField(blank=True, default="", max_length=255)),
                ("compartment", models.CharField(blank=True, default="", max_length=32)),
                ("is_currency", models.BooleanField(default=False)),
            ],
            options={
                "verbose_name_plural": "metabolic species",
                "unique_together": {("genome_accession", "species_id")},
            },
        ),
        migrations.CreateModel(
            name="ReactionParticipant",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("role", models.CharField(choices=[("reactant", "Reactant"), ("product", "Product")], max_length=16)),
                ("stoichiometry", models.FloatField(default=1.0)),
                (
                    "reaction",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="participants",
                        to="tpweb.metabolicreaction",
                    ),
                ),
                (
                    "species",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="reactions",
                        to="tpweb.metabolicspecies",
                    ),
                ),
            ],
            options={
                "unique_together": {("reaction", "species", "role")},
            },
        ),
    ]
