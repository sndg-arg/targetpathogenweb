# Generated by Django 4.2.4 on 2024-04-13 17:05

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('tpweb', '0030_alter_accessionligand_unique_together'),
    ]

    operations = [
        migrations.DeleteModel(
            name='AccessionLigand',
        ),
    ]
