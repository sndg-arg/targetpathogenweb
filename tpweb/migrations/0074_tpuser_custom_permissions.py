from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("tpweb", "0073_requestlog"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="tpuser",
            options={
                "verbose_name": "user",
                "verbose_name_plural": "users",
                "permissions": [
                    ("can_upload_genome", "Can upload a new genome"),
                    ("can_view_activity", "Can view the Activity dashboard"),
                    (
                        "can_curated_import",
                        "Can run curated external imports and upload large files",
                    ),
                    ("can_manage_formulas", "Can create, edit, and delete scoring formulas"),
                    ("can_run_blast", "Can run BLAST searches"),
                    (
                        "can_manage_custom_params",
                        "Can create and edit custom evidence parameters",
                    ),
                    ("can_use_agent_chat", "Can use the AI assistant"),
                ],
            },
        ),
    ]
