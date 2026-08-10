from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tpweb", "0071_agentchatsession"),
    ]

    operations = [
        migrations.AlterField(
            model_name="agentchatsession",
            name="session_key",
            field=models.CharField(max_length=40, db_index=True),
        ),
        migrations.AddField(
            model_name="agentchatsession",
            name="title",
            field=models.CharField(max_length=140, blank=True, default=""),
        ),
        migrations.AddIndex(
            model_name="agentchatsession",
            index=models.Index(fields=["session_key", "-updated_at"], name="tpweb_agent_sesskey_upd_idx"),
        ),
    ]
