from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tpweb", "0069_humanprotein"),
    ]

    operations = [
        migrations.AlterField(
            model_name="residue",
            name="resname",
            field=models.CharField(max_length=10),
        ),
    ]
