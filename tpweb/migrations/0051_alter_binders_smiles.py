from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tpweb", "0050_alter_genomeupload_status"),
    ]

    operations = [
        migrations.AlterField(
            model_name="binders",
            name="smiles",
            field=models.TextField(),
        ),
    ]
