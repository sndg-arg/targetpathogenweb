# Generated by Django 4.2.4 on 2024-04-13 17:06

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('tpweb', '0032_accessionligand'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='accessionligand',
            name='origin',
        ),
    ]