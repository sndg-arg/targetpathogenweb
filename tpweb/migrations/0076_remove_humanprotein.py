from django.db import migrations


class Migration(migrations.Migration):
    """`HumanProtein` moved from `tpweb` into its own app, `human_target`
    (see `human_target/migrations/0001_initial.py`). No production data
    existed in this table (the feature was hidden from nav the day after it
    was merged, never populated outside a local dev fixture) -- confirmed
    with the user before choosing drop-and-recreate over a state-only
    app-relabel. Re-run `import_human_curated_proteins` against the pilot
    fixture after this deploys to repopulate under the new app."""

    dependencies = [
        ("tpweb", "0075_blockedip"),
    ]

    operations = [
        migrations.DeleteModel(
            name="HumanProtein",
        ),
    ]
