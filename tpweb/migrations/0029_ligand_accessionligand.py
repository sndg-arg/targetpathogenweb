# Generated by Django 4.2.4 on 2024-04-10 20:28

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('bioseq', '0009_alter_term_identifier_alter_term_name'),
        ('tpweb', '0028_delete_accessionligand_delete_ligand'),
    ]

    operations = [
        migrations.CreateModel(
            name='Ligand',
            fields=[
                ('ligand_id', models.AutoField(primary_key=True, serialize=False)),
                ('ligand_from_key', models.CharField(max_length=255, unique=True)),
                ('ligand_smiles', models.CharField(max_length=10000)),
            ],
        ),
        migrations.CreateModel(
            name='AccessionLigand',
            fields=[
                ('relation_id', models.AutoField(primary_key=True, serialize=False)),
                ('origin', models.CharField(max_length=255)),
                ('ligand', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='tpweb.ligand', to_field='ligand_from_key')),
                ('locus_tag', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='bioseq.bioentry', to_field='accession')),
            ],
        ),
    ]
