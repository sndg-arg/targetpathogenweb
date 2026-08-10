from django.db import migrations


LOCALIZATION_OPTION_FIXES = {
    "Cytoplasmic": "Protein located in the cytoplasm",
    "CytoplasmicMembrane": "Protein located in the cytoplasmic membrane",
    "Extracellular": "Protein located in the extracellular matrix",
}


def _fix_localization_option_typos(apps, schema_editor):
    ScoreParam = apps.get_model("tpweb", "ScoreParam")
    ScoreParamOptions = apps.get_model("tpweb", "ScoreParamOptions")

    for score_param in ScoreParam.objects.filter(name="Localization", user__isnull=True):
        for option_name, description in LOCALIZATION_OPTION_FIXES.items():
            ScoreParamOptions.objects.filter(
                score_param=score_param, name=option_name
            ).update(description=description)


class Migration(migrations.Migration):

    dependencies = [
        ("tpweb", "0067_metabolic_species_participants"),
    ]

    operations = [
        migrations.RunPython(_fix_localization_option_typos, migrations.RunPython.noop),
    ]
