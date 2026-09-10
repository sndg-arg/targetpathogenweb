from typing import Any

from allauth.account.adapter import DefaultAccountAdapter
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.conf import settings
from django.http import HttpRequest

from tpweb.services.user_approval import mark_pending_approval


class AccountAdapter(DefaultAccountAdapter):
    def is_open_for_signup(self, request: HttpRequest):
        return getattr(settings, "ACCOUNT_ALLOW_REGISTRATION", True)

    def save_user(self, request, user, form, commit=True):
        user = super().save_user(request, user, form, commit=False)
        mark_pending_approval(user)
        return user


class SocialAccountAdapter(DefaultSocialAccountAdapter):
    def is_open_for_signup(self, request: HttpRequest, sociallogin: Any):
        return getattr(settings, "ACCOUNT_ALLOW_REGISTRATION", True)

    def save_user(self, request, sociallogin, form=None):
        # DefaultSocialAccountAdapter.save_user() only delegates to
        # AccountAdapter.save_user() when a signup form was actually shown.
        # With SOCIALACCOUNT_AUTO_SIGNUP unset (defaults True), the no-form
        # path is what actually runs for orcid/google today and would
        # otherwise bypass approval entirely.
        user = super().save_user(request, sociallogin, form)
        mark_pending_approval(user)
        return user
