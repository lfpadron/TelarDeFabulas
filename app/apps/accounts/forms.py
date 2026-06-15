from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.utils.translation import gettext_lazy as _

from .models import User


class EmailAuthenticationForm(AuthenticationForm):
    username = forms.EmailField(
        label=_("Email"),
        widget=forms.EmailInput(attrs={"autocomplete": "email"}),
    )


class UserRegistrationForm(UserCreationForm):
    field_order = (
        "email",
        "secondary_email",
        "name",
        "display_alias",
        "preferred_locale",
        "password1",
        "password2",
    )

    class Meta:
        model = User
        fields = (
            "email",
            "secondary_email",
            "name",
            "display_alias",
            "preferred_locale",
        )
        labels = {
            "email": _("Email"),
            "secondary_email": _("Email secundario"),
            "name": _("Nombre"),
            "display_alias": _("Alias visible"),
            "preferred_locale": _("Idioma preferido"),
        }
        widgets = {
            "email": forms.EmailInput(attrs={"autocomplete": "email"}),
            "secondary_email": forms.EmailInput(attrs={"autocomplete": "email"}),
            "name": forms.TextInput(attrs={"autocomplete": "name"}),
            "display_alias": forms.TextInput(attrs={"autocomplete": "nickname"}),
        }


class UserProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = (
            "secondary_email",
            "name",
            "display_alias",
            "preferred_locale",
            "timezone",
        )
        labels = {
            "secondary_email": _("Email secundario"),
            "name": _("Nombre"),
            "display_alias": _("Alias visible"),
            "preferred_locale": _("Idioma preferido"),
            "timezone": _("Zona horaria"),
        }
        widgets = {
            "secondary_email": forms.EmailInput(attrs={"autocomplete": "email"}),
            "name": forms.TextInput(attrs={"autocomplete": "name"}),
            "display_alias": forms.TextInput(attrs={"autocomplete": "nickname"}),
        }
