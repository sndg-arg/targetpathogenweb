from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("tpweb", "0065_metabolicreaction_isoenzyme_count"),
    ]

    operations = [
        migrations.CreateModel(
            name="MetabolicImportRun",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("genome_accession", models.CharField(db_index=True, max_length=128, unique=True)),
                ("sbml_filename", models.CharField(blank=True, default="", max_length=255)),
                ("results_filename", models.CharField(blank=True, default="", max_length=255)),
                ("sif_filename", models.CharField(blank=True, default="", max_length=255)),
                ("imported_at", models.DateTimeField(auto_now=True)),
                (
                    "imported_by",
                    models.ForeignKey(
                        blank=True, null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
        ),
    ]
