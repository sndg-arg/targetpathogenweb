from django.db import migrations


BINARY_SYSTEM_OPTIONS = {
    "human_offtarget": ("hit", "no_hit"),
    "gut_microbiome_offtarget": ("hit", "no_hit"),
    "hit_in_deg": ("Y", "N"),
}


def _prune_binary_system_filter_options(apps, schema_editor):
    ScoreParam = apps.get_model("tpweb", "ScoreParam")
    ScoreParamOptions = apps.get_model("tpweb", "ScoreParamOptions")

    for score_param_name, allowed_options in BINARY_SYSTEM_OPTIONS.items():
        score_params = ScoreParam.objects.filter(name=score_param_name, user__isnull=True)
        for score_param in score_params:
            ScoreParamOptions.objects.filter(score_param=score_param).exclude(
                name__in=allowed_options
            ).delete()
            for option_name in allowed_options:
                ScoreParamOptions.objects.get_or_create(
                    score_param=score_param,
                    name=option_name,
                    defaults={"description": ""},
                )


class Migration(migrations.Migration):

    dependencies = [
        ("tpweb", "0057_druggability_formula_not_default"),
    ]

    operations = [
        migrations.RunPython(_prune_binary_system_filter_options, migrations.RunPython.noop),
    ]
