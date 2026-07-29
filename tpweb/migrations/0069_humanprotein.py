from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("bioseq", "0009_alter_term_identifier_alter_term_name"),
        ("tpweb", "0068_fix_localization_option_typos"),
    ]

    operations = [
        migrations.CreateModel(
            name="HumanProtein",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("uniprot_accession", models.CharField(db_index=True, max_length=32, unique=True)),
                ("protein_name", models.CharField(blank=True, default="", max_length=512)),
                ("gene_symbol", models.CharField(blank=True, default="", max_length=64)),
                ("organism_name", models.CharField(blank=True, default="", max_length=255)),
                ("taxon_id", models.IntegerField(blank=True, null=True)),
                ("sequence_length", models.IntegerField(blank=True, null=True)),
                ("mass_da", models.IntegerField(blank=True, null=True)),
                ("annotation_score", models.FloatField(blank=True, null=True)),
                ("entry_version", models.IntegerField(blank=True, null=True)),
                ("is_reviewed", models.BooleanField(default=True)),
                ("chromosome", models.CharField(blank=True, default="", max_length=64)),
                ("lineage", models.JSONField(blank=True, default=list)),
                ("keywords", models.JSONField(blank=True, default=list)),
                ("subcellular_locations", models.JSONField(blank=True, default=list)),
                ("function_text", models.TextField(blank=True, default="")),
                ("caution_text", models.TextField(blank=True, default="")),
                ("subunit_text", models.TextField(blank=True, default="")),
                ("polymorphism_text", models.TextField(blank=True, default="")),
                ("disease_comments", models.JSONField(blank=True, default=list)),
                ("catalytic_activity", models.JSONField(blank=True, default=list)),
                ("go_terms", models.JSONField(blank=True, default=list)),
                ("publications", models.JSONField(blank=True, default=list)),
                ("features_raw", models.JSONField(blank=True, default=list)),
                ("cross_references_raw", models.JSONField(blank=True, default=list)),
                ("sequence", models.TextField(blank=True, default="")),
                ("uniprot_raw", models.JSONField(blank=True, default=dict)),
                ("ingest_source_path", models.CharField(blank=True, default="", max_length=1024)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "bioentry",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="human_protein",
                        to="bioseq.bioentry",
                    ),
                ),
            ],
            options={
                "ordering": ["gene_symbol", "uniprot_accession"],
            },
        ),
    ]
