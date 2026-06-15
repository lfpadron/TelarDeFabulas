from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import UserChangeForm, UserCreationForm
from django.utils.translation import gettext_lazy as _

from .models import User


class AdminUserCreationForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("email",)


class AdminUserChangeForm(UserChangeForm):
    class Meta:
        model = User
        fields = "__all__"


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    form = AdminUserChangeForm
    add_form = AdminUserCreationForm
    model = User

    list_display = ("email", "name", "display_alias", "user_type", "status", "preferred_locale", "is_staff")
    list_filter = ("user_type", "status", "preferred_locale", "is_staff", "is_superuser")
    search_fields = ("email", "name", "display_alias")
    ordering = ("email",)
    readonly_fields = ("last_login", "created_at", "updated_at")

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        (
            _("Perfil"),
            {
                "fields": (
                    "secondary_email",
                    "name",
                    "display_alias",
                    "preferred_locale",
                    "timezone",
                )
            },
        ),
        (_("Negocio"), {"fields": ("user_type", "status")}),
        (
            _("Permisos"),
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                )
            },
        ),
        (_("Fechas"), {"fields": ("last_login", "created_at", "updated_at")}),
    )

    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "email",
                    "password1",
                    "password2",
                    "user_type",
                    "status",
                    "is_staff",
                    "is_superuser",
                ),
            },
        ),
    )
