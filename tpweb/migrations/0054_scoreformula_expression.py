from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tpweb', '0053_binders_add_chembl_source'),
    ]

    operations = [
        migrations.AddField(
            model_name='scoreformula',
            name='expression',
            field=models.TextField(blank=True, default=''),
        ),
    ]
