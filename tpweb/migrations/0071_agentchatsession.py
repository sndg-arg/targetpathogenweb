from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tpweb", "0070_residue_resname_length"),
    ]

    operations = [
        migrations.CreateModel(
            name="AgentChatSession",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("session_key", models.CharField(max_length=40, unique=True, db_index=True)),
                ("history_json", models.JSONField(blank=True, default=list)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True, db_index=True)),
            ],
            options={
                "ordering": ["-updated_at"],
            },
        ),
    ]
