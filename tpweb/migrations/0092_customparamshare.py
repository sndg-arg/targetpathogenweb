import django.db.models.deletion
from django.db import migrations, models

PROT_POSTFIX = "_prots"


def share_previously_shared_params(apps, schema_editor):
    # Columns shared before sharing went per genome (ScoreParam.shared_with_gates)
    # stay shared with project members on every genome they have values in.
    ScoreParam = apps.get_model("tpweb", "ScoreParam")
    ScoreParamValue = apps.get_model("tpweb", "ScoreParamValue")
    CustomParamShare = apps.get_model("tpweb", "CustomParamShare")
    for param in ScoreParam.objects.filter(category="Custom", shared_with_gates=True):
        proteome_names = (
            ScoreParamValue.objects.filter(score_param=param)
            .values_list("bioentry__biodatabase__name", flat=True)
            .distinct()
        )
        for proteome_name in proteome_names:
            genome_name = proteome_name.removesuffix(PROT_POSTFIX)
            CustomParamShare.objects.get_or_create(
                score_param=param, genome_name=genome_name, defaults={"visibility": "project"}
            )


class Migration(migrations.Migration):
    dependencies = [
        ("tpweb", "0091_fix_localization_descriptions"),
    ]

    operations = [
        migrations.CreateModel(
            name="CustomParamShare",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("genome_name", models.CharField(max_length=255)),
                (
                    "visibility",
                    models.CharField(
                        choices=[
                            ("project", "Project members"),
                            ("public", "Everyone who can see this genome"),
                        ],
                        max_length=16,
                    ),
                ),
                ("shared_at", models.DateTimeField(auto_now=True)),
                (
                    "score_param",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="genome_shares",
                        to="tpweb.scoreparam",
                    ),
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name="customparamshare",
            constraint=models.UniqueConstraint(
                fields=("score_param", "genome_name"),
                name="tpweb_customparamshare_param_genome_unique",
            ),
        ),
        migrations.RunPython(share_previously_shared_params, migrations.RunPython.noop),
    ]
