from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tpweb", "0049_pipelinerun_pipelinestageevent"),
    ]

    operations = [
        migrations.AlterField(
            model_name="genomeupload",
            name="status",
            field=models.CharField(
                choices=[
                    ("submitted", "Queued"),
                    ("running", "Running"),
                    ("finished", "Finished"),
                    ("failed", "Failed"),
                ],
                default="submitted",
                max_length=24,
            ),
        ),
    ]
