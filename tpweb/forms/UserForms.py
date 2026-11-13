from allauth.account.forms import SignupForm
from allauth.socialaccount.forms import SignupForm as SocialSignupForm
from django import forms
from django.contrib.auth import forms as admin_forms
from django.contrib.auth import get_user_model
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

User = get_user_model()


def _capitalize_name_part(value):
    """Normalize a first/last name to Title Case regardless of how it was
    typed (e.g. "ana" or "ANA" -> "Ana") -- str.title() also handles
    hyphenated/multi-word parts reasonably ("maria-jose" -> "Maria-Jose")."""
    return value.strip().title()


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
    wants_collaborator_access = forms.BooleanField(
        label=_("Request a collaborator role"),
        required=False,
        help_text=_(
            "Your account is active either way. Check this only if you work on the project "
            "itself (uploading genomes, editing formulas, Gates data) and we will contact "
            "you to assign the role."
        ),
    )
    collaborator_institution = forms.CharField(
        label=_("Institution"),
        max_length=255,
        # required=False is about Django: the field is only mandatory when
        # the checkbox above it is ticked (see clean), and a field declared
        # required would reject every plain Basic signup. For the person
        # filling the form it is required, so it says so, and signup.js
        # puts the real "required" attribute on the input whenever the
        # field is visible.
        required=False,
        help_text=_("Required. Where you work or study, which is what we review."),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.order_fields(
            [
                "first_name",
                "last_name",
                "email",
                "wants_collaborator_access",
                "collaborator_institution",
                "password1",
                "password2",
            ]
        )
        # crispy marks every required field with an asterisk, and it asks
        # Django, which calls this one optional (it is required only with
        # the checkbox ticked). Without this the one field a person must
        # fill would be the only one on the form looking optional.
        institution = self.fields["collaborator_institution"]
        institution.label = format_html('{}<span class="asteriskField">*</span>', institution.label)

    def clean(self):
        # The field is hidden until the checkbox is ticked (signup.html),
        # so it can only be required conditionally -- declaring it
        # required=True would reject every plain Basic signup.
        cleaned_data = super().clean()
        if (
            cleaned_data.get("wants_collaborator_access")
            and not (cleaned_data.get("collaborator_institution") or "").strip()
        ):
            self.add_error(
                "collaborator_institution",
                _("Tell us which institution you belong to."),
            )
        return cleaned_data

    def custom_signup(self, request, user):
        # wants_collaborator_access is read straight from this form's
        # cleaned_data by AccountAdapter.save_user (tpweb/adapters/
        # AccountAdapters.py) before this hook even runs -- not repeated
        # here to avoid two code paths racing to set the same field.
        first = _capitalize_name_part(self.cleaned_data["first_name"])
        last = _capitalize_name_part(self.cleaned_data["last_name"])
        user.name = f"{first} {last}".strip()
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
        first = _capitalize_name_part(self.cleaned_data["first_name"])
        last = _capitalize_name_part(self.cleaned_data["last_name"])
        user.name = f"{first} {last}".strip()
        if commit:
            user.save()
        return user
