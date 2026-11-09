from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import Http404
from django.utils.decorators import method_decorator
from django.utils.translation import gettext_lazy as _
from django.urls import reverse
from django.utils.html import format_html
from django.views.decorators.csrf import csrf_protect

from apps.core.admin import ProjectOwnedAdmin
from apps.core.permissions import Action, can_edit_project, get_user_project, visible_projects

from .models import Character, CharacterDramaticRole, CharacterMention, CharacterRelationship
from .relationship_forms import AdminCharacterRelationshipForm
from .relationship_selectors import local_relationships


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


@admin.register(CharacterRelationship)
class CharacterRelationshipAdmin(ProjectOwnedAdmin):
    form = AdminCharacterRelationshipForm
    actions = None
    list_display = ("source_character", "target_character", "relationship_type", "is_reciprocal", "project", "updated_at")
    list_filter = ("relationship_type", "is_reciprocal")
    search_fields = ("source_character__name", "target_character__name")
    list_select_related = ("project", "source_character", "target_character")
    readonly_fields = ("created_at", "updated_at")

    def get_queryset(self, request):
        return local_relationships(super().get_queryset(request)).defer("description", *[
            f"{endpoint}__{field.name}" for endpoint in ("source_character", "target_character")
            for field in Character._meta.fields if field.name not in ("id", "name", "project")])

    @method_decorator(csrf_protect)
    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        if request.method != "POST":
            return super().changeform_view(request, object_id, form_url, extra_context)
        with transaction.atomic():
            pk = self.get_object(request, object_id).project_id if object_id else request.POST.get("project", "")
            if not str(pk).isascii() or not str(pk).isdigit() or len(str(pk)) > 18:
                raise Http404
            get_user_project(request.user, pk, Action.EDIT if object_id else Action.CREATE, for_update=True)
            return super().changeform_view(request, object_id, form_url, extra_context)

    def save_model(self, request, obj, form, change):
        saved = form.save(user=request.user)
        for field in obj._meta.concrete_fields:
            setattr(obj, field.attname, getattr(saved, field.attname))
        obj._state.adding, obj._state.db = False, saved._state.db

    @method_decorator(csrf_protect)
    def delete_view(self, request, object_id, extra_context=None):
        if request.method != "POST":
            return super().delete_view(request, object_id, extra_context)
        with transaction.atomic():
            project_id = self.get_object(request, object_id).project_id
            get_user_project(request.user, project_id, Action.DELETE, for_update=True)
            return super().delete_view(request, object_id, extra_context)

    def delete_queryset(self, request, queryset):
        raise PermissionDenied
