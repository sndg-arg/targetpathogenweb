# Generated by Django 4.2.4 on 2023-08-31 21:05

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('tpweb', '0011_alter_scoreformula_user'),
    ]

    operations = [
        migrations.AlterUniqueTogether(
            name='scoreformulaparam',
            unique_together={('formula', 'score_param', 'value')},
        ),
    ]
