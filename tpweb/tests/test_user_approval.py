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
from tpweb.services.user_approval import (
    approve_user,
    mark_pending_approval,
    reject_signup,
    revoke_access,
)

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
        html_body, mimetype = mail.outbox[0].alternatives[0]
        self.assertEqual(mimetype, "text/html")
        self.assertIn("newbie@example.com", html_body)

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

    def test_notification_emails_greet_by_real_name_when_set(self):
        User.objects.create_user(
            username="owner2",
            password="x",
            is_superuser=True,
            is_active=True,
            email="o2@example.com",
        )
        new_user = User.objects.create_user(
            username="autouser123",
            password="x",
            name="Ana Gutson",
            email="ana@example.com",
        )

        with self.captureOnCommitCallbacks(execute=True):
            mark_pending_approval(new_user)
        self.assertIn("Ana Gutson", mail.outbox[0].body)
        self.assertNotIn("autouser123", mail.outbox[0].body)
        mail.outbox.clear()

        with self.captureOnCommitCallbacks(execute=True):
            approve_user(new_user)
        self.assertIn("Ana Gutson", mail.outbox[0].body)
        self.assertNotIn("autouser123", mail.outbox[0].body)

    def test_approve_user_email_carries_a_styled_html_alternative(self):
        user = User.objects.create_user(
            username="html-approved",
            password="x",
            is_active=False,
            name="Grace Hopper",
            email="grace@example.com",
        )

        with self.captureOnCommitCallbacks(execute=True):
            approve_user(user)

        self.assertEqual(len(mail.outbox[0].alternatives), 1)
        html_body, mimetype = mail.outbox[0].alternatives[0]
        self.assertEqual(mimetype, "text/html")
        self.assertIn("Grace Hopper", html_body)
        self.assertIn("TARGET PATHOGEN", html_body)

    def test_approve_user_grants_can_upload_genome_permission(self):
        user = User.objects.create_user(
            username="pending2", password="x", is_active=False, email="pending2@example.com"
        )

        with self.captureOnCommitCallbacks(execute=True):
            approve_user(user)

        user.refresh_from_db()
        self.assertTrue(user.has_perm("tpweb.can_upload_genome"))
        # Approval is a baseline grant only -- it must not hand out any of
        # the other, individually-toggled permissions.
        self.assertFalse(user.has_perm("tpweb.can_view_activity"))

    def test_approve_user_is_idempotent_no_duplicate_email(self):
        user = User.objects.create_user(
            username="already", password="x", is_active=True, is_staff=True, email="a@example.com"
        )

        with self.captureOnCommitCallbacks(execute=True):
            approve_user(user)

        self.assertEqual(len(mail.outbox), 0)

    def test_revoke_access_deactivates_and_unstaffs_a_regular_user(self):
        user = User.objects.create_user(
            username="onceapproved", password="x", is_active=True, is_staff=True
        )

        revoke_access(user)

        user.refresh_from_db()
        self.assertFalse(user.is_active)
        self.assertFalse(user.is_staff)

    def test_revoke_access_clears_granted_permissions(self):
        from django.contrib.auth.models import Permission

        user = User.objects.create_user(
            username="revoke-with-perms", password="x", is_active=True, is_staff=True
        )
        user.user_permissions.add(
            *Permission.objects.filter(content_type__app_label="tpweb", codename__startswith="can_")
        )

        revoke_access(user)

        user.refresh_from_db()
        self.assertEqual(user.user_permissions.count(), 0)

    def test_revoke_access_refuses_a_superuser(self):
        owner = User.objects.create_user(
            username="theowner", password="x", is_active=True, is_staff=True, is_superuser=True
        )

        revoke_access(owner)

        owner.refresh_from_db()
        self.assertTrue(owner.is_active)
        self.assertTrue(owner.is_staff)

    def test_reject_signup_deletes_a_pending_account(self):
        pending = User.objects.create_user(username="unwanted", password="x", is_active=False)

        result = reject_signup(pending)

        self.assertTrue(result)
        self.assertFalse(User.objects.filter(pk=pending.pk).exists())

    def test_reject_signup_refuses_an_already_approved_account(self):
        approved = User.objects.create_user(
            username="already-in", password="x", is_active=True, is_staff=True
        )

        result = reject_signup(approved)

        self.assertFalse(result)
        self.assertTrue(User.objects.filter(pk=approved.pk).exists())


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
        # No "username" field -- ACCOUNT_USERNAME_REQUIRED=False, allauth
        # generates one from the email instead. first_name/last_name are
        # required and get joined into TPUser.name.
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(
                reverse("account_signup"),
                {
                    "first_name": "Fresh",
                    "last_name": "Signup",
                    "email": "fresh@example.com",
                    "password1": "S0me-Strong-Pass!23",
                    "password2": "S0me-Strong-Pass!23",
                },
            )

        user = User.objects.get(email="fresh@example.com")
        self.assertFalse(user.is_active)
        self.assertEqual(user.name, "Fresh Signup")

    @override_settings(ACCOUNT_ALLOW_REGISTRATION=True)
    def test_signup_capitalizes_the_name_regardless_of_input_casing(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(
                reverse("account_signup"),
                {
                    "first_name": "ana",
                    "last_name": "GUTSON",
                    "email": "casing@example.com",
                    "password1": "S0me-Strong-Pass!23",
                    "password2": "S0me-Strong-Pass!23",
                },
            )

        user = User.objects.get(email="casing@example.com")
        self.assertEqual(user.name, "Ana Gutson")


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

    def test_post_reject_deletes_pending_user(self):
        owner = User.objects.create_user(
            username="mgmt-owner5", password="x", is_staff=True, is_superuser=True
        )
        pending = User.objects.create_user(username="mgmt-pending5", password="x", is_active=False)
        self.client.force_login(owner)

        response = self.client.post(
            reverse("tpwebapp:user_management"),
            {"user_id": pending.pk, "action": "reject"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(User.objects.filter(pk=pending.pk).exists())

    def test_post_reject_refuses_an_approved_user(self):
        owner = User.objects.create_user(
            username="mgmt-owner6", password="x", is_staff=True, is_superuser=True
        )
        approved = User.objects.create_user(
            username="mgmt-approved2", password="x", is_active=True, is_staff=True
        )
        self.client.force_login(owner)

        self.client.post(
            reverse("tpwebapp:user_management"),
            {"user_id": approved.pk, "action": "reject"},
        )

        self.assertTrue(User.objects.filter(pk=approved.pk).exists())

    def test_post_revoke_deactivates_approved_user(self):
        owner = User.objects.create_user(
            username="mgmt-owner3", password="x", is_staff=True, is_superuser=True
        )
        approved = User.objects.create_user(
            username="mgmt-approved", password="x", is_active=True, is_staff=True
        )
        self.client.force_login(owner)

        response = self.client.post(
            reverse("tpwebapp:user_management"),
            {"user_id": approved.pk, "action": "revoke"},
        )

        self.assertEqual(response.status_code, 302)
        approved.refresh_from_db()
        self.assertFalse(approved.is_active)
        self.assertFalse(approved.is_staff)

    def test_post_revoke_refuses_a_superuser(self):
        owner = User.objects.create_user(
            username="mgmt-owner4", password="x", is_staff=True, is_superuser=True
        )
        other_owner = User.objects.create_user(
            username="mgmt-other-owner",
            password="x",
            is_active=True,
            is_staff=True,
            is_superuser=True,
        )
        self.client.force_login(owner)

        self.client.post(
            reverse("tpwebapp:user_management"),
            {"user_id": other_owner.pk, "action": "revoke"},
        )

        other_owner.refresh_from_db()
        self.assertTrue(other_owner.is_active)


class ProfileViewTests(TestCase):
    def test_anonymous_user_is_redirected_to_login(self):
        response = self.client.get(reverse("tpwebapp:profile"))

        self.assertEqual(response.status_code, 302)

    def test_logged_in_user_can_view_and_update_profile(self):
        user = User.objects.create_user(
            username="profile-user", password="x", name="Old Name", email="old@example.com"
        )
        self.client.force_login(user)

        response = self.client.get(reverse("tpwebapp:profile"))
        self.assertEqual(response.status_code, 200)

        response = self.client.post(
            reverse("tpwebapp:profile"),
            {"first_name": "New", "last_name": "Name", "email": "new@example.com"},
        )

        self.assertEqual(response.status_code, 302)
        user.refresh_from_db()
        self.assertEqual(user.name, "New Name")
        self.assertEqual(user.email, "new@example.com")

    def test_profile_update_capitalizes_the_name_regardless_of_input_casing(self):
        user = User.objects.create_user(username="casing-user", password="x")
        self.client.force_login(user)

        self.client.post(
            reverse("tpwebapp:profile"),
            {"first_name": "ana", "last_name": "GUTSON", "email": "casing2@example.com"},
        )

        user.refresh_from_db()
        self.assertEqual(user.name, "Ana Gutson")

    def test_cannot_take_another_users_email(self):
        User.objects.create_user(username="taken", password="x", email="taken@example.com")
        user = User.objects.create_user(username="wants-it", password="x", email="mine@example.com")
        self.client.force_login(user)

        response = self.client.post(
            reverse("tpwebapp:profile"),
            {"first_name": "First", "last_name": "Last", "email": "taken@example.com"},
        )

        self.assertEqual(response.status_code, 200)
        user.refresh_from_db()
        self.assertEqual(user.email, "mine@example.com")


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
