# Generated by Django 4.2.4 on 2024-05-15 16:15

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('bioseq', '0009_alter_term_identifier_alter_term_name'),
        ('tpweb', '0038_celularlocalization'),
    ]

    operations = [
        migrations.RenameField(
            model_name='celularlocalization',
            old_name='ligand_id',
            new_name='localization_id',
        ),
        migrations.AlterUniqueTogether(
            name='celularlocalization',
            unique_together={('locus_tag', 'localization')},
        ),
    ]
