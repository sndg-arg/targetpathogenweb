from typing import Any

from allauth.account.adapter import DefaultAccountAdapter
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.conf import settings
from django.http import HttpRequest

from tpweb.services.user_approval import activate_new_signup


class AccountAdapter(DefaultAccountAdapter):
    def is_open_for_signup(self, request: HttpRequest):
        return getattr(settings, "ACCOUNT_ALLOW_REGISTRATION", True)

    def save_user(self, request, user, form, commit=True):
        user = super().save_user(request, user, form, commit=False)
        wants_collaborator_access = bool(
            getattr(form, "cleaned_data", {}).get("wants_collaborator_access")
        )
        activate_new_signup(user, wants_collaborator_access=wants_collaborator_access)
        return user


class SocialAccountAdapter(DefaultSocialAccountAdapter):
    def is_open_for_signup(self, request: HttpRequest, sociallogin: Any):
        return getattr(settings, "ACCOUNT_ALLOW_REGISTRATION", True)

    def save_user(self, request, sociallogin, form=None):
        # DefaultSocialAccountAdapter.save_user() only delegates to
        # AccountAdapter.save_user() when a signup form was actually shown.
        # With SOCIALACCOUNT_AUTO_SIGNUP unset (defaults True), the no-form
        # path is what actually runs for orcid/google today -- there's no
        # "solicitar acceso de colaborador" checkbox in that path, so it
        # always activates as a plain Basic account.
        user = super().save_user(request, sociallogin, form)
        wants_collaborator_access = (
            bool(getattr(form, "cleaned_data", {}).get("wants_collaborator_access"))
            if form
            else False
        )
        activate_new_signup(user, wants_collaborator_access=wants_collaborator_access)
        return user
