"""Signup -> pending approval -> approve pipeline: adapters forcing new
accounts inactive, the notification emails, the owner-only admin action and
in-app screen, and the allauth login-blocking behavior for inactive users.
"""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from tpweb.adapters.AccountAdapters import SocialAccountAdapter
from tpweb.services.user_approval import approve_user, mark_pending_approval

User = get_user_model()


class UserApprovalServiceTests(TestCase):
    def test_mark_pending_approval_deactivates_and_notifies_superusers(self):
        owner = User.objects.create_user(
            username="owner",
            password="x",
            is_superuser=True,
            is_active=True,
            email="owner@example.com",
        )
        new_user = User.objects.create_user(
            username="newbie", password="x", email="newbie@example.com"
        )

        with self.captureOnCommitCallbacks(execute=True):
            mark_pending_approval(new_user)

        new_user.refresh_from_db()
        self.assertFalse(new_user.is_active)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(owner.email, mail.outbox[0].to)
        self.assertIn("newbie", mail.outbox[0].body)

    def test_mark_pending_approval_with_no_superusers_does_not_crash(self):
        new_user = User.objects.create_user(username="newbie2", password="x")

        with self.captureOnCommitCallbacks(execute=True):
            mark_pending_approval(new_user)

        self.assertFalse(User.objects.get(pk=new_user.pk).is_active)
        self.assertEqual(len(mail.outbox), 0)

    def test_approve_user_grants_staff_and_notifies_user(self):
        user = User.objects.create_user(
            username="pending", password="x", is_active=False, email="pending@example.com"
        )

        with self.captureOnCommitCallbacks(execute=True):
            approve_user(user)

        user.refresh_from_db()
        self.assertTrue(user.is_active)
        self.assertTrue(user.is_staff)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("pending@example.com", mail.outbox[0].to)

    def test_approve_user_is_idempotent_no_duplicate_email(self):
        user = User.objects.create_user(
            username="already", password="x", is_active=True, is_staff=True, email="a@example.com"
        )

        with self.captureOnCommitCallbacks(execute=True):
            approve_user(user)

        self.assertEqual(len(mail.outbox), 0)


class InactiveUserLoginTests(TestCase):
    def test_inactive_user_login_attempt_shows_awaiting_approval(self):
        User.objects.create_user(username="blocked", password="correct-pass", is_active=False)

        response = self.client.post(
            reverse("account_login"),
            {"login": "blocked", "password": "correct-pass"},
            follow=True,
        )

        self.assertContains(response, "Awaiting approval")


class SignupAdapterTests(TestCase):
    @override_settings(ACCOUNT_ALLOW_REGISTRATION=True)
    def test_signup_creates_inactive_user(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(
                reverse("account_signup"),
                {
                    "username": "freshsignup",
                    "email": "fresh@example.com",
                    "password1": "S0me-Strong-Pass!23",
                    "password2": "S0me-Strong-Pass!23",
                },
            )

        user = User.objects.get(username="freshsignup")
        self.assertFalse(user.is_active)


class SocialSignupAdapterTests(TestCase):
    def test_social_signup_without_form_still_requires_approval(self):
        # SOCIALACCOUNT_AUTO_SIGNUP is unset (defaults True), so the live
        # path for orcid/google today is DefaultSocialAccountAdapter.save_user()
        # with form=None -- it never calls AccountAdapter.save_user(), so the
        # override here is the only thing standing between a social signup
        # and bypassing approval entirely.
        adapter = SocialAccountAdapter()
        user = User.objects.create_user(
            username="social-user", password="x", email="social@example.com", is_active=True
        )

        with patch(
            "allauth.socialaccount.adapter.DefaultSocialAccountAdapter.save_user",
            return_value=user,
        ):
            with self.captureOnCommitCallbacks(execute=True):
                result = adapter.save_user(request=None, sociallogin=None, form=None)

        result.refresh_from_db()
        self.assertFalse(result.is_active)


class UserManagementViewTests(TestCase):
    def test_anonymous_user_is_redirected_to_login(self):
        response = self.client.get(reverse("tpwebapp:user_management"))

        self.assertEqual(response.status_code, 302)

    def test_staff_non_superuser_is_forbidden(self):
        staff_user = User.objects.create_user(username="mgmt-staff", password="x", is_staff=True)
        self.client.force_login(staff_user)

        response = self.client.get(reverse("tpwebapp:user_management"))

        self.assertEqual(response.status_code, 403)

    def test_superuser_can_view_and_sees_pending_users(self):
        owner = User.objects.create_user(
            username="mgmt-owner", password="x", is_staff=True, is_superuser=True
        )
        User.objects.create_user(username="mgmt-pending", password="x", is_active=False)
        self.client.force_login(owner)

        response = self.client.get(reverse("tpwebapp:user_management"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "mgmt-pending")

    def test_post_approve_activates_pending_user(self):
        owner = User.objects.create_user(
            username="mgmt-owner2", password="x", is_staff=True, is_superuser=True
        )
        pending = User.objects.create_user(
            username="mgmt-pending2", password="x", is_active=False, email="p2@example.com"
        )
        self.client.force_login(owner)

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                reverse("tpwebapp:user_management"), {"user_id": pending.pk}
            )

        self.assertEqual(response.status_code, 302)
        pending.refresh_from_db()
        self.assertTrue(pending.is_active)
        self.assertTrue(pending.is_staff)


class UserAdminApproveActionTests(TestCase):
    def test_approve_selected_users_action(self):
        owner = User.objects.create_user(
            username="admin-owner", password="x", is_staff=True, is_superuser=True
        )
        pending = User.objects.create_user(
            username="admin-pending", password="x", is_active=False, email="ap@example.com"
        )
        self.client.force_login(owner)

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                reverse("admin:tpweb_tpuser_changelist"),
                {"action": "approve_selected_users", "_selected_action": [pending.pk]},
                follow=True,
            )

        self.assertEqual(response.status_code, 200)
        pending.refresh_from_db()
        self.assertTrue(pending.is_active)
        self.assertTrue(pending.is_staff)
