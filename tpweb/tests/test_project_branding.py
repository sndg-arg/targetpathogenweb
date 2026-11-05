from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.test import TestCase

from tpweb.services.project_branding import branded, branded_choices, is_gates_viewer

User = get_user_model()


class ProjectBrandingTests(TestCase):
    def test_gates_roles_and_admins_see_gates(self):
        collaborator = User.objects.create_user(
            username="b-collab", password="x", role=User.Role.GATES_COLLABORATOR
        )
        consumer = User.objects.create_user(
            username="b-consumer", password="x", role=User.Role.GATES_CONSUMER
        )
        admin = User.objects.create_user(username="b-admin", password="x", is_superuser=True)

        for user in (collaborator, consumer, admin):
            with self.subTest(user=user.username):
                self.assertTrue(is_gates_viewer(user))
                self.assertEqual(branded("Project members", user), "Gates members")
                self.assertEqual(
                    branded("Available to project collaborators.", user),
                    "Available to Gates collaborators.",
                )

    def test_basic_and_anonymous_keep_neutral_wording(self):
        basic = User.objects.create_user(username="b-basic", password="x", role=User.Role.BASIC)

        for user in (basic, AnonymousUser(), None):
            with self.subTest(user=user):
                self.assertFalse(is_gates_viewer(user))
                self.assertEqual(branded("Project members", user), "Project members")

    def test_branded_choices_keeps_values(self):
        admin = User.objects.create_user(username="b-admin2", password="x", is_superuser=True)

        choices = branded_choices([("gates", "Project members"), ("private", "Only me")], admin)

        self.assertEqual(choices, [("gates", "Gates members"), ("private", "Only me")])
