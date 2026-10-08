from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse

User = get_user_model()


class HumanTargetsPermissionGateTests(TestCase):
    """Access to the whole Human Targets section is gated by
    tpweb.can_view_human_targets (granted by default on approval, see
    tpweb.services.user_approval, revocable per user from the /users
    "Edit" modal) -- covers the same admin-controlled-per-user visibility
    as tpweb.can_view_restricted_genomes, just for this sister app."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="human-targets-user", password="x", is_active=True
        )
        self.client.force_login(self.user)

    def test_list_view_forbidden_without_permission(self):
        response = self.client.get(reverse("human_target:human_protein_list"))
        self.assertEqual(response.status_code, 403)

    def test_detail_view_forbidden_without_permission(self):
        response = self.client.get(
            reverse("human_target:human_protein", kwargs={"accession": "P10721"})
        )
        self.assertEqual(response.status_code, 403)

    def test_list_view_allowed_with_permission(self):
        self.user.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="tpweb", codename="can_view_human_targets"
            )
        )

        response = self.client.get(reverse("human_target:human_protein_list"))

        self.assertEqual(response.status_code, 200)
