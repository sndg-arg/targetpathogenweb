from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views import View

from tpweb.forms.UserForms import ProfileForm
from tpweb.services.agent_chat_quota import quota_for


# What a user sees as their own role. Gates roles keep their real names
# ("Gates consumer", "Gates collaborator" -- they're in the project and know
# it); only Basic gets a plainer label.
PROFILE_ROLE_LABELS = {
    "basic": "Basic access",
}


class ProfileView(LoginRequiredMixin, View):
    template_name = "users/profile.html"

    def get(self, request, *args, **kwargs):
        return render(
            request,
            self.template_name,
            {
                "form": ProfileForm(instance=request.user),
                **self._capabilities_context(request.user),
            },
        )

    def _capabilities_context(self, user):
        # Deliberately only the capabilities that are already visible
        # elsewhere in the app regardless of who's looking (Upload/BLAST/
        # Formulas/Custom params nav links, the chat drawer's own button) --
        # never list anything that would tip someone off to a feature they
        # don't have access to see exists at all (Human Targets). Restricted
        # genomes are the exception: the Genomes page already tells everyone
        # how many collaborative-project genomes they can't see.
        quota = quota_for(user)
        if not user.has_perm("tpweb.can_use_agent_chat"):
            chat_quota_label = ""
        elif quota is None:
            chat_quota_label = "Unlimited"
        else:
            chat_quota_label = f"{quota} messages/day"
        capabilities = {
            key: user.has_perm(f"tpweb.{key}")
            for key in (
                "can_upload_genome",
                "can_run_blast",
                "can_manage_formulas",
                "can_manage_custom_params",
                "can_use_agent_chat",
                "can_view_restricted_genomes",
            )
        }
        return {
            "role_display": "Owner"
            if user.is_superuser
            else PROFILE_ROLE_LABELS.get(user.role, user.get_role_display()),
            **capabilities,
            # Nothing left to ask for: the page drops "Request access".
            "has_full_access": all(capabilities.values()),
            "chat_quota_label": chat_quota_label,
        }

    def post(self, request, *args, **kwargs):
        form = ProfileForm(request.POST, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Your profile was updated.")
            return redirect(reverse("tpwebapp:profile"))
        return render(
            request,
            self.template_name,
            {"form": form, **self._capabilities_context(request.user)},
        )
