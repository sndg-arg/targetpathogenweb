from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views import View

from tpweb.forms.UserForms import ProfileForm


class ProfileView(LoginRequiredMixin, View):
    template_name = "users/profile.html"

    def get(self, request, *args, **kwargs):
        return render(request, self.template_name, {"form": ProfileForm(instance=request.user)})

    def post(self, request, *args, **kwargs):
        form = ProfileForm(request.POST, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Your profile was updated.")
            return redirect(reverse("tpwebapp:profile"))
        return render(request, self.template_name, {"form": form})
