from django.db import migrations


def _clear_formula_defaults(apps, schema_editor):
    ScoreFormula = apps.get_model("tpweb", "ScoreFormula")
    ScoreFormula.objects.filter(name__in=["Druggability", "Localization"]).update(default=False)

    ScoreParam = apps.get_model("tpweb", "ScoreParam")
    new_desc = (
        "FPocket druggability score for the best predicted pocket (0–1). "
        "≥ 0.7 highly druggable · ≥ 0.4 moderately druggable · < 0.4 low druggability."
    )
    ScoreParam.objects.filter(name="Druggability", user__isnull=True).update(description=new_desc)


class Migration(migrations.Migration):

    dependencies = [
        ("tpweb", "0056_experimental_structure_metadata"),
    ]

    operations = [
        migrations.RunPython(_clear_formula_defaults, migrations.RunPython.noop),
    ]
