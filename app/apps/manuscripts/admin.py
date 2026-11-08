from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.utils.translation import gettext_lazy as _

from apps.core.admin import ProjectOwnedAdmin

from .models import ManuscriptNode, SceneVersion
from .hierarchy import CURRENT_TYPES, editable_node_ids, load_structure


@admin.register(ManuscriptNode)
class ManuscriptNodeAdmin(ProjectOwnedAdmin):
    actions = None
    list_display = (
        "title",
        "project",
        "parent",
        "node_type",
        "legacy_status",
        "position",
        "legacy_word_count",
        "legacy_publishable",
        "updated_at",
    )
    list_filter = ("node_type", "status", "is_publishable", "created_at")
    search_fields = ("title", "versions__content", "project__name", "project__user__email")
    readonly_fields = ("word_count", "created_at", "updated_at", "current_draft_version")

    @admin.display(description=_("Estado legado"))
    def legacy_status(self, obj):
        return obj.get_status_display()

    @admin.display(description=_("Palabras legadas"))
    def legacy_word_count(self, obj):
        return obj.word_count

    @admin.display(description=_("Publicable legado"), boolean=True)
    def legacy_publishable(self, obj):
        return obj.is_publishable

    def get_fieldsets(self, request, obj=None):
        if obj and obj.node_type == "SCENE":
            return (
                (None, {"fields": ("project", "parent", "node_type", "title", "short_description", "position", "current_draft_version", "created_at", "updated_at")}),
                (_("Datos legados de la escena"), {"fields": ("content", "status", "word_count", "is_publishable"), "classes": ("collapse",)}),
            )
        return super().get_fieldsets(request, obj)

    def get_readonly_fields(self, request, obj=None):
        fields = list(super().get_readonly_fields(request, obj))
        if obj:
            fields.extend(("parent", "node_type", "position"))
            if obj.node_type == "SCENE":
                fields.extend(("content", "status", "is_publishable"))
        return fields

    def has_change_permission(self, request, obj=None):
        return super().has_change_permission(request, obj) and (
            obj is None or obj.pk in editable_node_ids(load_structure(obj.project_id))
        )

    def has_delete_permission(self, request, obj=None):
        if not super().has_delete_permission(request, obj):
            return False
        if obj is None:
            return True
        structure = load_structure(obj.project_id)
        siblings = {pk for pk, row in structure.items() if row["parent_id"] == obj.parent_id}
        return siblings <= editable_node_ids(structure) and not obj.children.exists()

    def formfield_for_choice_field(self, db_field, request, **kwargs):
        if db_field.name == "node_type":
            kwargs["choices"] = [(value, label) for value, label in ManuscriptNode.NodeType.choices if value in CURRENT_TYPES]
        return super().formfield_for_choice_field(db_field, request, **kwargs)

    def delete_queryset(self, request, queryset):
        raise PermissionDenied


@admin.register(SceneVersion)
class SceneVersionAdmin(ProjectOwnedAdmin):
    project_lookup = "scene__project"
    actions = None
    list_display = ("scene", "version_number", "editorial_stage", "is_current_final", "revision", "word_count", "created_at", "updated_at", "finalized_at")
    search_fields = ("scene__title", "scene__project__name", "scene__project__user__email")
    list_filter = ("editorial_stage", "created_at", "finalized_at")
    readonly_fields = tuple(field.name for field in SceneVersion._meta.fields)

    def get_readonly_fields(self, request, obj=None):
        return self.readonly_fields

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
