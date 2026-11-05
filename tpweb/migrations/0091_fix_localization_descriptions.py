from django.db import migrations

OLD_PARAM_DESCRIPTION = "Celular localization of the protein"
NEW_PARAM_DESCRIPTION = "Cellular localization of the protein"
OLD_PERIPLASMIC = "Protein located in periplasmatic space"
NEW_PERIPLASMIC = "Protein located in the periplasmic space"


def fix_typos(apps, schema_editor):
    # Typos shown in the Scoring drawer's Localization formula tooltip. The
    # seed in tpweb/models/ScoreParam.py uses the description as part of its
    # get_or_create lookup, so it is updated in the same change to the new
    # text -- otherwise the next seed run would create a duplicate param.
    ScoreParam = apps.get_model("tpweb", "ScoreParam")
    ScoreParamOptions = apps.get_model("tpweb", "ScoreParamOptions")
    ScoreParam.objects.filter(
        name="Localization", user__isnull=True, description=OLD_PARAM_DESCRIPTION
    ).update(description=NEW_PARAM_DESCRIPTION)
    ScoreParamOptions.objects.filter(
        score_param__name="Localization", name="Periplasmic", description=OLD_PERIPLASMIC
    ).update(description=NEW_PERIPLASMIC)


def restore_typos(apps, schema_editor):
    ScoreParam = apps.get_model("tpweb", "ScoreParam")
    ScoreParamOptions = apps.get_model("tpweb", "ScoreParamOptions")
    ScoreParam.objects.filter(
        name="Localization", user__isnull=True, description=NEW_PARAM_DESCRIPTION
    ).update(description=OLD_PARAM_DESCRIPTION)
    ScoreParamOptions.objects.filter(
        score_param__name="Localization", name="Periplasmic", description=NEW_PERIPLASMIC
    ).update(description=OLD_PERIPLASMIC)


class Migration(migrations.Migration):
    dependencies = [
        ("tpweb", "0090_identicalsequencegroup_identicalsequencemember"),
    ]

    operations = [
        migrations.RunPython(fix_typos, restore_typos),
    ]
