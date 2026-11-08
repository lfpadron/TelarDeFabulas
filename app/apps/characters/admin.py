from django.contrib import admin
from django.utils.translation import gettext_lazy as _
from django.urls import reverse
from django.utils.html import format_html

from apps.core.admin import ProjectOwnedAdmin
from apps.core.permissions import can_edit_project, visible_projects

from .models import Character, CharacterDramaticRole, CharacterMention


class CharacterDramaticRoleInline(admin.TabularInline):
    model = CharacterDramaticRole
    extra = 0

    def get_queryset(self, request):
        return super().get_queryset(request).filter(character__project__in=visible_projects(request.user))

    def has_add_permission(self, request, obj=None):
        return super().has_add_permission(request, obj) and (obj is None or can_edit_project(request.user, obj.project))

    def has_change_permission(self, request, obj=None):
        return super().has_change_permission(request, obj) and (obj is None or can_edit_project(request.user, obj.project))

    def has_delete_permission(self, request, obj=None):
        return super().has_delete_permission(request, obj) and (obj is None or can_edit_project(request.user, obj.project))


@admin.register(Character)
class CharacterAdmin(ProjectOwnedAdmin):
    list_display = (
        "name",
        "project",
        "importance",
        "narrative_role",
        "completion_status",
        "completion_percentage_display",
        "updated_at",
    )
    list_filter = ("importance", "narrative_role", "completion_status", "created_at")
    search_fields = ("name", "alias", "project__name", "project__user__email")
    readonly_fields = ("private_image", "completion_percentage_display", "created_at", "updated_at")
    inlines = (CharacterDramaticRoleInline,)

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        project_id = obj.project_id if obj else request.POST.get("project") or request.GET.get("project")
        if "residence" in form.base_fields:
            queryset = form.base_fields["residence"].queryset
            form.base_fields["residence"].queryset = (
                queryset.filter(project_id=project_id).only("id", "name")
                if str(project_id).isdigit() else queryset.none()
            )
        return form

    @admin.display(description=_("completitud"))
    def completion_percentage_display(self, obj):
        return f"{obj.completion_percentage}%"

    def get_exclude(self, request, obj=None):
        return ("image",) if obj and not can_edit_project(request.user, obj.project) else ()

    @admin.display(description=_("imagen privada"))
    def private_image(self, obj):
        if not obj or not obj.image:
            return "-"
        url = reverse("characters:image", args=[obj.project_id, obj.pk])
        return format_html('<a href="{}">{}</a>', url, _("Ver imagen"))


@admin.register(CharacterDramaticRole)
class CharacterDramaticRoleAdmin(ProjectOwnedAdmin):
    project_lookup = "character__project"
    list_display = ("character", "role", "custom_role", "updated_at")
    list_filter = ("role", "created_at")
    search_fields = ("character__name", "character__project__name", "character__project__user__email")


@admin.register(CharacterMention)
class CharacterMentionAdmin(ProjectOwnedAdmin):
    project_lookup = "character__project"
    list_display = ("character", "node", "mention_type", "project", "created_at")
    list_filter = ("mention_type", "created_at", "updated_at")
    search_fields = (
        "character__name",
        "node__title",
        "character__project__name",
        "character__project__user__email",
    )

    @admin.display(description=_("proyecto"))
    def project(self, obj):
        return obj.character.project
