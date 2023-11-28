# Generated by Django 4.2.4 on 2023-11-06 22:09

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('tpweb', '0013_pdbresidueset_description_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='UserScoreFormula',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('default', models.BooleanField(default=False)),
                ('scoreformula', models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='userscoreformulas', to='tpweb.scoreformula')),
                ('user', models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='userscoreformulas', to=settings.AUTH_USER_MODEL)),
            ],
        ),
    ]