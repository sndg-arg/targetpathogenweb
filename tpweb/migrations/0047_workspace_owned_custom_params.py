# Generated manually for workspace-scoped custom parameters.

from django.conf import settings
from django.db import migrations, models


PUBLIC_WORKSPACE_USERNAME = "public"


def assign_public_workspace_to_existing_custom_data(apps, schema_editor):
    TPUser = apps.get_model("tpweb", "TPUser")
    ScoreParam = apps.get_model("tpweb", "ScoreParam")
    CustomParam = apps.get_model("tpweb", "CustomParam")

    public_user, created = TPUser.objects.get_or_create(
        username=PUBLIC_WORKSPACE_USERNAME,
        defaults={
            "name": "Public workspace",
            "is_active": True,
            "password": "!",
        },
    )
    if not created and not public_user.password:
        public_user.password = "!"
        public_user.save(update_fields=["password"])

    ScoreParam.objects.filter(category="Custom", user__isnull=True).update(user=public_user)
    CustomParam.objects.filter(owner__isnull=True).update(owner=public_user)


def noop(apps, schema_editor):
    return


class Migration(migrations.Migration):

    dependencies = [
        ("tpweb", "0046_alter_scoreformulaparam_value_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="customparam",
            name="owner",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.CASCADE,
                related_name="custom_params",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="scoreparam",
            name="user",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.CASCADE,
                related_name="owned_score_params",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name="scoreparam",
            name="name",
            field=models.CharField(max_length=255),
        ),
        migrations.AlterUniqueTogether(
            name="scoreparam",
            unique_together=set(),
        ),
        migrations.RunPython(
            assign_public_workspace_to_existing_custom_data,
            reverse_code=noop,
        ),
        migrations.AddConstraint(
            model_name="scoreparam",
            constraint=models.UniqueConstraint(
                fields=("category", "name", "user"),
                name="tpweb_scoreparam_category_name_user_unique",
            ),
        ),
        migrations.AddConstraint(
            model_name="scoreparam",
            constraint=models.UniqueConstraint(
                condition=models.Q(user__isnull=True),
                fields=("category", "name"),
                name="tpweb_scoreparam_category_name_global_unique",
            ),
        ),
    ]
