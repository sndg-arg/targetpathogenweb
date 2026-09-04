from allauth.account.forms import SignupForm
from allauth.socialaccount.forms import SignupForm as SocialSignupForm
from django import forms
from django.contrib.auth import forms as admin_forms
from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _

User = get_user_model()


class UserAdminChangeForm(admin_forms.UserChangeForm):
    class Meta(admin_forms.UserChangeForm.Meta):
        model = User


class UserAdminCreationForm(admin_forms.UserCreationForm):
    """
    Form for User Creation in the Admin Area.
    To change user signup, see UserSignupForm and UserSocialSignupForm.
    """

    class Meta(admin_forms.UserCreationForm.Meta):
        model = User

        error_messages = {"username": {"unique": _("This username has already been taken.")}}


class UserSignupForm(SignupForm):
    """
    Form that will be rendered on a user sign up section/screen.
    Default fields will be added automatically.
    Check UserSocialSignupForm for accounts created from social.

    No username field is shown -- ACCOUNT_USERNAME_REQUIRED=False (settings.py)
    tells allauth's SignupForm to omit it and auto-generate one from the
    email instead (DefaultAccountAdapter.populate_username(), unchanged).
    first_name/last_name are the only addition, joined into TPUser.name
    (the model's only name field -- AbstractUser's first_name/last_name are
    removed, see tpweb/models/__init__.py) via custom_signup() (allauth's
    own hook for extra signup fields).
    """

    first_name = forms.CharField(label=_("First name"), max_length=150)
    last_name = forms.CharField(label=_("Last name"), max_length=150)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.order_fields(["first_name", "last_name", "email", "password1", "password2"])

    def custom_signup(self, request, user):
        user.name = f"{self.cleaned_data['first_name']} {self.cleaned_data['last_name']}".strip()
        user.save(update_fields=["name"])


class UserSocialSignupForm(SocialSignupForm):
    """
    Renders the form when user has signed up using social accounts.
    Default fields will be added automatically.
    See UserSignupForm otherwise.
    """


class ProfileForm(forms.ModelForm):
    """Self-service "my profile" form -- any logged-in user editing their
    own name/email (tpweb/views/ProfileView.py). first_name/last_name
    aren't real model fields (TPUser only has a single "name" field) --
    pre-split from it for editing, rejoined into "name" on save()."""

    first_name = forms.CharField(label=_("First name"), max_length=150)
    last_name = forms.CharField(label=_("Last name"), max_length=150)

    class Meta:
        model = User
        fields = ["email"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk and not self.is_bound:
            first, _sep, last = (self.instance.name or "").partition(" ")
            self.fields["first_name"].initial = first
            self.fields["last_name"].initial = last
        self.order_fields(["first_name", "last_name", "email"])

    def clean_email(self):
        email = self.cleaned_data["email"]
        if User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError(_("This email is already in use."))
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        first = self.cleaned_data["first_name"].strip()
        last = self.cleaned_data["last_name"].strip()
        user.name = f"{first} {last}".strip()
        if commit:
            user.save()
        return user
