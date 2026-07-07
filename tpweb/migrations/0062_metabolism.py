from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('bioseq', '0009_alter_term_identifier_alter_term_name'),
        ('tpweb', '0061_filterpreset'),
    ]

    operations = [
        migrations.CreateModel(
            name='MetabolicPathway',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('source', models.CharField(choices=[('KEGG', 'KEGG'), ('BIOCYC', 'BioCyc')], max_length=16)),
                ('external_id', models.CharField(max_length=64)),
                ('name', models.CharField(max_length=255)),
            ],
            options={
                'unique_together': {('source', 'external_id')},
            },
        ),
        migrations.CreateModel(
            name='MetabolicReaction',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('genome_accession', models.CharField(db_index=True, max_length=128)),
                ('reaction_id', models.CharField(max_length=128)),
                ('name', models.CharField(blank=True, default='', max_length=255)),
                ('ec_numbers', models.CharField(blank=True, default='', max_length=255)),
                ('kegg_reaction_id', models.CharField(blank=True, default='', max_length=32)),
                ('reversible', models.BooleanField(default=False)),
                ('gpr_expression', models.TextField(blank=True, default='')),
                ('pathways', models.ManyToManyField(blank=True, related_name='reactions', to='tpweb.metabolicpathway')),
            ],
            options={
                'unique_together': {('genome_accession', 'reaction_id')},
            },
        ),
        migrations.CreateModel(
            name='GeneReactionLink',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('chokepoint_role', models.CharField(
                    choices=[
                        ('none', 'Not a chokepoint'),
                        ('producing', 'Producing chokepoint'),
                        ('consuming', 'Consuming chokepoint'),
                        ('both', 'Both producing and consuming chokepoint'),
                    ],
                    default='none', max_length=16,
                )),
                ('bioentry', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='metabolic_reactions', to='bioseq.bioentry')),
                ('reaction', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='genes', to='tpweb.metabolicreaction')),
            ],
            options={
                'unique_together': {('bioentry', 'reaction')},
            },
        ),
        migrations.CreateModel(
            name='MetabolicReactionEdge',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('genome_accession', models.CharField(db_index=True, max_length=128)),
                ('reaction_a', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='edges_a', to='tpweb.metabolicreaction')),
                ('reaction_b', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='edges_b', to='tpweb.metabolicreaction')),
            ],
            options={
                'unique_together': {('genome_accession', 'reaction_a', 'reaction_b')},
            },
        ),
    ]
