from django.db import migrations


OFFTARGET_METADATA = {
    "human_offtarget": {
        "description": (
            "BLASTP against the human proteome. Hit means at least one human match "
            "was detected at e-value <= 1e-5. Prefer No hit for pathogen-selective targets."
        ),
        "options": {
            "hit": "At least one human proteome match was detected; potential host off-target risk.",
            "no_hit": "No human proteome match detected under the pipeline cutoff; favorable for selectivity.",
        },
    },
    "gut_microbiome_offtarget": {
        "description": (
            "DIAMOND/BLASTP against gut microbiome reference genomes. Hit means at "
            "least one microbiome match passing identity > 40% and query coverage > 70%."
        ),
        "options": {
            "hit": "At least one gut microbiome match passed identity > 40% and query coverage > 70%; microbiome cross-reactivity risk.",
            "no_hit": "No gut microbiome match passed the identity/coverage cutoff; favorable for microbiome sparing.",
        },
    },
}


def _describe_offtarget_filter_cutoffs(apps, schema_editor):
    ScoreParam = apps.get_model("tpweb", "ScoreParam")
    ScoreParamOptions = apps.get_model("tpweb", "ScoreParamOptions")

    for score_param_name, metadata in OFFTARGET_METADATA.items():
        score_params = ScoreParam.objects.filter(name=score_param_name, user__isnull=True)
        for score_param in score_params:
            score_param.description = metadata["description"]
            score_param.save(update_fields=["description"])
            for option_name, description in metadata["options"].items():
                option, _ = ScoreParamOptions.objects.get_or_create(
                    score_param=score_param,
                    name=option_name,
                    defaults={"description": description},
                )
                if option.description != description:
                    option.description = description
                    option.save(update_fields=["description"])


class Migration(migrations.Migration):

    dependencies = [
        ("tpweb", "0058_prune_binary_system_filter_options"),
    ]

    operations = [
        migrations.RunPython(_describe_offtarget_filter_cutoffs, migrations.RunPython.noop),
    ]
