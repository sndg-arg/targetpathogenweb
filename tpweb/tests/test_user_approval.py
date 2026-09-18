"""Signup -> instant activation -> optional role elevation pipeline: the
adapter activating new accounts immediately, the collaborator-access-request
notification, the owner-only admin action and in-app screen, and the allauth
login-blocking behavior for a revoked (inactive) account.
"""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from tpweb.adapters.AccountAdapters import SocialAccountAdapter
from tpweb.services.user_approval import (
    activate_new_signup,
    reactivate_user,
    reject_signup,
    revoke_access,
)

User = get_user_model()


class UserApprovalServiceTests(TestCase):
    def test_activate_new_signup_activates_as_basic_with_no_email_by_default(self):
        new_user = User.objects.create_user(
            username="newbie", password="x", email="newbie@example.com"
        )

        with self.captureOnCommitCallbacks(execute=True):
            activate_new_signup(new_user)

        new_user.refresh_from_db()
        self.assertTrue(new_user.is_active)
        self.assertEqual(new_user.role, User.Role.BASIC)
        self.assertFalse(new_user.wants_collaborator_access)
        self.assertFalse(new_user.is_staff)
        self.assertEqual(len(mail.outbox), 0)

    def test_activate_new_signup_with_collaborator_request_notifies_superusers(self):
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
            activate_new_signup(new_user, wants_collaborator_access=True)

        new_user.refresh_from_db()
        self.assertTrue(new_user.is_active)
        self.assertTrue(new_user.wants_collaborator_access)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(owner.email, mail.outbox[0].to)
        self.assertIn("newbie", mail.outbox[0].body)
        html_body, mimetype = mail.outbox[0].alternatives[0]
        self.assertEqual(mimetype, "text/html")
        self.assertIn("newbie@example.com", html_body)

    def test_activate_new_signup_with_collaborator_request_and_no_superusers_does_not_crash(self):
        new_user = User.objects.create_user(username="newbie2", password="x")

        with self.captureOnCommitCallbacks(execute=True):
            activate_new_signup(new_user, wants_collaborator_access=True)

        self.assertTrue(User.objects.get(pk=new_user.pk).is_active)
        self.assertEqual(len(mail.outbox), 0)

    def test_reactivate_user_activates_and_notifies_user_but_does_not_grant_staff(self):
        user = User.objects.create_user(
            username="pending", password="x", is_active=False, email="pending@example.com"
        )

        with self.captureOnCommitCallbacks(execute=True):
            reactivate_user(user)

        user.refresh_from_db()
        self.assertTrue(user.is_active)
        self.assertFalse(user.is_staff)
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
            is_active=False,
        )

        with self.captureOnCommitCallbacks(execute=True):
            activate_new_signup(new_user, wants_collaborator_access=True)
        self.assertIn("Ana Gutson", mail.outbox[0].body)
        self.assertNotIn("autouser123", mail.outbox[0].body)
        mail.outbox.clear()

        revoke_access(new_user)
        with self.captureOnCommitCallbacks(execute=True):
            reactivate_user(new_user)
        self.assertIn("Ana Gutson", mail.outbox[0].body)
        self.assertNotIn("autouser123", mail.outbox[0].body)

    def test_reactivate_user_email_carries_a_styled_html_alternative(self):
        user = User.objects.create_user(
            username="html-approved",
            password="x",
            is_active=False,
            name="Grace Hopper",
            email="grace@example.com",
        )

        with self.captureOnCommitCallbacks(execute=True):
            reactivate_user(user)

        self.assertEqual(len(mail.outbox[0].alternatives), 1)
        html_body, mimetype = mail.outbox[0].alternatives[0]
        self.assertEqual(mimetype, "text/html")
        self.assertIn("Grace Hopper", html_body)
        self.assertIn("TARGET PATHOGEN", html_body)

    @override_settings(SITE_URL="https://targetpathogen.example.org")
    def test_reactivate_user_email_includes_a_login_link_when_site_url_is_set(self):
        user = User.objects.create_user(
            username="linked-approved", password="x", is_active=False, email="linked@example.com"
        )

        with self.captureOnCommitCallbacks(execute=True):
            reactivate_user(user)

        login_url = "https://targetpathogen.example.org" + reverse("account_login")
        self.assertIn(login_url, mail.outbox[0].body)
        html_body = mail.outbox[0].alternatives[0][0]
        self.assertIn(login_url, html_body)

    @override_settings(SITE_URL="")
    def test_reactivate_user_email_omits_login_link_when_site_url_is_unset(self):
        user = User.objects.create_user(
            username="unlinked-approved",
            password="x",
            is_active=False,
            email="unlinked@example.com",
        )

        with self.captureOnCommitCallbacks(execute=True):
            reactivate_user(user)

        self.assertNotIn("http", mail.outbox[0].body)

    def test_activate_new_signup_grants_the_baseline_permissions(self):
        user = User.objects.create_user(
            username="pending2", password="x", is_active=False, email="pending2@example.com"
        )

        with self.captureOnCommitCallbacks(execute=True):
            activate_new_signup(user)

        user.refresh_from_db()
        self.assertTrue(user.has_perm("tpweb.can_manage_formulas"))
        self.assertTrue(user.has_perm("tpweb.can_run_blast"))
        self.assertTrue(user.has_perm("tpweb.can_manage_custom_params"))
        self.assertTrue(user.has_perm("tpweb.can_use_agent_chat"))
        # A Basic self-serve signup gets none of the content-gating or
        # resource-consuming permissions -- those are Gates-role-only now,
        # granted manually from /users, same as the two always-individual
        # ones below.
        self.assertFalse(user.has_perm("tpweb.can_upload_genome"))
        self.assertFalse(user.has_perm("tpweb.can_view_restricted_genomes"))
        self.assertFalse(user.has_perm("tpweb.can_view_human_targets"))
        self.assertFalse(user.has_perm("tpweb.can_view_activity"))
        self.assertFalse(user.has_perm("tpweb.can_curated_import"))

    def test_reactivate_user_is_idempotent_no_duplicate_email(self):
        user = User.objects.create_user(
            username="already", password="x", is_active=True, is_staff=True, email="a@example.com"
        )

        with self.captureOnCommitCallbacks(execute=True):
            reactivate_user(user)

        self.assertEqual(len(mail.outbox), 0)

    def test_revoke_access_deactivates_a_regular_user_without_touching_is_staff(self):
        # is_staff is a manual-only Django-admin toggle now -- neither
        # granted nor revoked by any of this app-level access code.
        user = User.objects.create_user(
            username="onceapproved", password="x", is_active=True, is_staff=True
        )

        revoke_access(user)

        user.refresh_from_db()
        self.assertFalse(user.is_active)
        self.assertTrue(user.is_staff)

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

    def test_reject_signup_deletes_an_inactive_account(self):
        pending = User.objects.create_user(username="unwanted", password="x", is_active=False)

        result = reject_signup(pending)

        self.assertTrue(result)
        self.assertFalse(User.objects.filter(pk=pending.pk).exists())

    def test_reject_signup_refuses_an_active_account(self):
        approved = User.objects.create_user(
            username="already-in", password="x", is_active=True, is_staff=True
        )

        result = reject_signup(approved)

        self.assertFalse(result)
        self.assertTrue(User.objects.filter(pk=approved.pk).exists())


class InactiveUserLoginTests(TestCase):
    def test_inactive_user_login_attempt_shows_account_inactive(self):
        User.objects.create_user(username="blocked", password="correct-pass", is_active=False)

        response = self.client.post(
            reverse("account_login"),
            {"login": "blocked", "password": "correct-pass"},
            follow=True,
        )

        self.assertContains(response, "Account inactive")


class SignupAdapterTests(TestCase):
    @override_settings(ACCOUNT_ALLOW_REGISTRATION=True)
    def test_signup_activates_immediately_as_basic(self):
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
        self.assertTrue(user.is_active)
        self.assertEqual(user.role, User.Role.BASIC)
        self.assertFalse(user.wants_collaborator_access)
        self.assertFalse(user.is_staff)
        self.assertEqual(user.name, "Fresh Signup")
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(ACCOUNT_ALLOW_REGISTRATION=True)
    def test_signup_with_collaborator_checkbox_notifies_superusers(self):
        User.objects.create_user(
            username="notify-owner",
            password="x",
            is_superuser=True,
            is_active=True,
            email="notify-owner@example.com",
        )

        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(
                reverse("account_signup"),
                {
                    "first_name": "Wants",
                    "last_name": "Access",
                    "email": "wants-access@example.com",
                    "wants_collaborator_access": "on",
                    "password1": "S0me-Strong-Pass!23",
                    "password2": "S0me-Strong-Pass!23",
                },
            )

        user = User.objects.get(email="wants-access@example.com")
        self.assertTrue(user.is_active)
        self.assertTrue(user.wants_collaborator_access)
        self.assertEqual(len(mail.outbox), 1)

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
    def test_social_signup_activates_immediately_without_a_collaborator_request(self):
        # SOCIALACCOUNT_AUTO_SIGNUP is unset (defaults True), so the live
        # path for orcid/google today is DefaultSocialAccountAdapter.save_user()
        # with form=None -- there's no "solicitar acceso de colaborador"
        # checkbox in that path, so it always activates as a plain Basic
        # account.
        adapter = SocialAccountAdapter()
        user = User.objects.create_user(
            username="social-user", password="x", email="social@example.com", is_active=False
        )

        with patch(
            "allauth.socialaccount.adapter.DefaultSocialAccountAdapter.save_user",
            return_value=user,
        ):
            with self.captureOnCommitCallbacks(execute=True):
                result = adapter.save_user(request=None, sociallogin=None, form=None)

        result.refresh_from_db()
        self.assertTrue(result.is_active)
        self.assertFalse(result.wants_collaborator_access)


class UserManagementViewTests(TestCase):
    def test_anonymous_user_sees_the_locked_page_with_a_login_cta(self):
        response = self.client.get(reverse("tpwebapp:user_management"))

        self.assertEqual(response.status_code, 403)
        self.assertContains(response, "Manage users", status_code=403)
        self.assertContains(response, "Log in", status_code=403)

    def test_staff_non_superuser_is_forbidden(self):
        staff_user = User.objects.create_user(username="mgmt-staff", password="x", is_staff=True)
        self.client.force_login(staff_user)

        response = self.client.get(reverse("tpwebapp:user_management"))

        self.assertEqual(response.status_code, 403)

    def test_superuser_can_view_and_sees_revoked_accounts(self):
        owner = User.objects.create_user(
            username="mgmt-owner", password="x", is_staff=True, is_superuser=True
        )
        User.objects.create_user(username="mgmt-revoked", password="x", is_active=False)
        self.client.force_login(owner)

        response = self.client.get(reverse("tpwebapp:user_management"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "mgmt-revoked")

    def test_approved_row_carries_granted_permissions_for_the_edit_modal(self):
        from django.contrib.auth.models import Permission

        owner = User.objects.create_user(
            username="mgmt-owner9", password="x", is_staff=True, is_superuser=True
        )
        approved = User.objects.create_user(
            username="mgmt-approved4", password="x", is_active=True, is_staff=True
        )
        approved.user_permissions.add(
            Permission.objects.get(content_type__app_label="tpweb", codename="can_run_blast")
        )
        self.client.force_login(owner)

        response = self.client.get(reverse("tpwebapp:user_management"))

        self.assertEqual(response.status_code, 200)
        # Django auto-escapes the JSON's double quotes to &quot; in the
        # rendered attribute -- browsers decode that back to a literal
        # quote when JS reads the attribute, so this is still valid JSON
        # by the time user-management.js calls JSON.parse() on it.
        self.assertContains(response, "data-granted='[&quot;can_run_blast&quot;]'")
        # The full toggleable set is offered in the modal's checkbox list,
        # not just whatever this one user happens to have.
        self.assertContains(response, "can_manage_formulas")
        self.assertContains(response, "can_use_agent_chat")

    def test_page_offers_profile_presets_role_select_and_a_revoke_confirmation_trigger(self):
        owner = User.objects.create_user(
            username="mgmt-owner11", password="x", is_staff=True, is_superuser=True
        )
        approved = User.objects.create_user(
            username="mgmt-approved5", password="x", is_active=True, is_staff=True
        )
        self.client.force_login(owner)

        response = self.client.get(reverse("tpwebapp:user_management"))

        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        # Profile presets ship as a json_script tag for the modal's <select>
        # to read, not baked into inline JS.
        self.assertIn('id="user-mgmt-profile-presets"', body)
        self.assertIn("Gates collaborator", body)
        self.assertIn("Alumnos / testers", body)
        # The persisted-role select is separate from the profile-fill preset.
        self.assertIn('id="user-permissions-role-select"', body)
        self.assertIn(f'data-role="{approved.role}"', body)
        # Revoke is a modal trigger now, not a form with a native confirm().
        self.assertIn("user-mgmt-revoke-trigger", body)
        self.assertIn(f'data-user-id="{approved.pk}"', body)
        self.assertNotIn("Revoke this user's access?", body)

    def test_wants_collaborator_access_shows_a_badge_and_sorts_first(self):
        owner = User.objects.create_user(
            username="mgmt-owner12", password="x", is_staff=True, is_superuser=True
        )
        # Created before mgmt-plain, so -date_joined ordering alone would
        # put it *second* -- only the wants_collaborator_access-first sort
        # moves it back to the top.
        User.objects.create_user(
            username="mgmt-requester",
            password="x",
            is_active=True,
            wants_collaborator_access=True,
        )
        User.objects.create_user(username="mgmt-plain", password="x", is_active=True)
        self.client.force_login(owner)

        response = self.client.get(reverse("tpwebapp:user_management"))
        body = response.content.decode()

        self.assertContains(response, "Requested collaborator access")
        self.assertLess(body.index("mgmt-requester"), body.index("mgmt-plain"))

    def test_superuser_row_has_no_edit_permissions_button(self):
        owner = User.objects.create_user(
            username="mgmt-owner10", password="x", is_staff=True, is_superuser=True
        )
        self.client.force_login(owner)

        response = self.client.get(reverse("tpwebapp:user_management"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "mgmt-owner10")
        self.assertNotContains(response, f'data-user-id="{owner.pk}"')

    def test_post_reactivate_activates_revoked_user_without_granting_staff(self):
        owner = User.objects.create_user(
            username="mgmt-owner2", password="x", is_staff=True, is_superuser=True
        )
        revoked = User.objects.create_user(
            username="mgmt-revoked2", password="x", is_active=False, email="p2@example.com"
        )
        self.client.force_login(owner)

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                reverse("tpwebapp:user_management"), {"user_id": revoked.pk}
            )

        self.assertEqual(response.status_code, 302)
        revoked.refresh_from_db()
        self.assertTrue(revoked.is_active)
        self.assertFalse(revoked.is_staff)

    def test_post_reject_deletes_revoked_user(self):
        owner = User.objects.create_user(
            username="mgmt-owner5", password="x", is_staff=True, is_superuser=True
        )
        revoked = User.objects.create_user(username="mgmt-revoked5", password="x", is_active=False)
        self.client.force_login(owner)

        response = self.client.post(
            reverse("tpwebapp:user_management"),
            {"user_id": revoked.pk, "action": "reject"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(User.objects.filter(pk=revoked.pk).exists())

    def test_post_reject_refuses_an_active_user(self):
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

    def test_post_revoke_deactivates_approved_user_without_touching_is_staff(self):
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
        self.assertTrue(approved.is_staff)

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

    def test_post_update_permissions_role_admin_grants_superuser_only(self):
        owner = User.objects.create_user(
            username="mgmt-owner7", password="x", is_staff=True, is_superuser=True
        )
        approved = User.objects.create_user(
            username="mgmt-approved3",
            password="x",
            is_active=True,
            wants_collaborator_access=True,
        )
        self.client.force_login(owner)

        response = self.client.post(
            reverse("tpwebapp:user_management"),
            {"user_id": approved.pk, "action": "update_permissions", "role": "admin"},
        )

        self.assertEqual(response.status_code, 302)
        approved.refresh_from_db()
        self.assertTrue(approved.is_superuser)
        self.assertFalse(approved.is_staff)
        self.assertFalse(approved.wants_collaborator_access)

    def test_post_update_permissions_rejects_an_unknown_role(self):
        owner = User.objects.create_user(
            username="mgmt-owner15", password="x", is_staff=True, is_superuser=True
        )
        approved = User.objects.create_user(username="mgmt-approved7", password="x", is_active=True)
        self.client.force_login(owner)

        self.client.post(
            reverse("tpwebapp:user_management"),
            {"user_id": approved.pk, "action": "update_permissions", "role": "custom"},
        )

        approved.refresh_from_db()
        self.assertFalse(approved.is_superuser)
        self.assertEqual(approved.role, "basic")

    def test_post_update_permissions_with_a_named_role_ignores_submitted_checkboxes(self):
        # The server re-derives a named role's codenames itself -- a
        # tampered/stale "permissions" list in the POST body must not be
        # able to desync a role from its real permission set.
        owner = User.objects.create_user(
            username="mgmt-owner14", password="x", is_staff=True, is_superuser=True
        )
        approved = User.objects.create_user(
            username="mgmt-approved6", password="x", is_active=True, is_staff=True
        )
        self.client.force_login(owner)

        self.client.post(
            reverse("tpwebapp:user_management"),
            {
                "user_id": approved.pk,
                "action": "update_permissions",
                "role": "student",
                "permissions": ["can_upload_genome", "can_view_activity"],
            },
        )

        approved.refresh_from_db()
        self.assertEqual(approved.role, "student")
        codenames = set(approved.user_permissions.values_list("codename", flat=True))
        self.assertEqual(codenames, {"can_run_blast", "can_use_agent_chat"})

    def test_post_update_permissions_sets_role_and_clears_the_collaborator_request(self):
        owner = User.objects.create_user(
            username="mgmt-owner13", password="x", is_staff=True, is_superuser=True
        )
        requester = User.objects.create_user(
            username="mgmt-requester2",
            password="x",
            is_active=True,
            wants_collaborator_access=True,
        )
        self.client.force_login(owner)

        response = self.client.post(
            reverse("tpwebapp:user_management"),
            {
                "user_id": requester.pk,
                "action": "update_permissions",
                "role": "gates_collaborator",
                "permissions": [],
            },
        )

        self.assertEqual(response.status_code, 302)
        requester.refresh_from_db()
        self.assertEqual(requester.role, "gates_collaborator")
        self.assertFalse(requester.wants_collaborator_access)

    def test_post_update_permissions_refuses_for_superuser(self):
        owner = User.objects.create_user(
            username="mgmt-owner8", password="x", is_staff=True, is_superuser=True
        )
        other_owner = User.objects.create_user(
            username="mgmt-other-owner2",
            password="x",
            is_active=True,
            is_staff=True,
            is_superuser=True,
        )
        self.client.force_login(owner)

        self.client.post(
            reverse("tpwebapp:user_management"),
            {
                "user_id": other_owner.pk,
                "action": "update_permissions",
                "permissions": ["can_view_activity"],
            },
        )

        self.assertEqual(other_owner.user_permissions.count(), 0)


class ProfileViewTests(TestCase):
    def test_anonymous_user_sees_the_locked_page_with_a_login_cta(self):
        response = self.client.get(reverse("tpwebapp:profile"))

        self.assertEqual(response.status_code, 403)
        self.assertContains(response, "My profile", status_code=403)
        self.assertContains(response, "Log in", status_code=403)

    def test_capability_list_reflects_actual_permissions_and_never_names_gated_features(self):
        from django.contrib.auth.models import Permission

        user = User.objects.create_user(
            username="profile-capabilities", password="x", role=User.Role.BASIC
        )
        user.user_permissions.add(
            Permission.objects.get(content_type__app_label="tpweb", codename="can_run_blast")
        )
        self.client.force_login(user)

        response = self.client.get(reverse("tpwebapp:profile"))
        body = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertIn("Basic", body)
        self.assertIn("Run BLAST searches", body)
        self.assertIn("Upload your own genomes", body)
        # Never revealed on this page regardless of role or permission
        # state -- mentioning them at all would tip off that these gated
        # features exist.
        self.assertNotIn("Human Targets", body)
        self.assertNotIn("restricted", body.lower())

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


class UserAdminReactivateActionTests(TestCase):
    def test_reactivate_selected_users_action(self):
        owner = User.objects.create_user(
            username="admin-owner", password="x", is_staff=True, is_superuser=True
        )
        revoked = User.objects.create_user(
            username="admin-revoked", password="x", is_active=False, email="ap@example.com"
        )
        self.client.force_login(owner)

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                reverse("admin:tpweb_tpuser_changelist"),
                {"action": "reactivate_selected_users", "_selected_action": [revoked.pk]},
                follow=True,
            )

        self.assertEqual(response.status_code, 200)
        revoked.refresh_from_db()
        self.assertTrue(revoked.is_active)
        self.assertFalse(revoked.is_staff)
