from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views import View

from tpweb.forms.UserForms import ProfileForm
from tpweb.services.agent_chat_quota import quota_for


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
        # don't have access to see exists at all (Human Targets, restricted
        # genomes).
        quota = quota_for(user)
        if not user.has_perm("tpweb.can_use_agent_chat"):
            chat_quota_label = ""
        elif quota is None:
            chat_quota_label = "Unlimited"
        else:
            chat_quota_label = f"{quota} messages/day"
        return {
            "role_display": "Owner" if user.is_superuser else user.get_role_display(),
            "can_upload_genome": user.has_perm("tpweb.can_upload_genome"),
            "can_run_blast": user.has_perm("tpweb.can_run_blast"),
            "can_manage_formulas": user.has_perm("tpweb.can_manage_formulas"),
            "can_manage_custom_params": user.has_perm("tpweb.can_manage_custom_params"),
            "can_use_agent_chat": user.has_perm("tpweb.can_use_agent_chat"),
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
