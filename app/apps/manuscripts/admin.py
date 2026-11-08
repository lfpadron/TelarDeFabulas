from django.contrib import admin
from django.core.exceptions import PermissionDenied

from apps.core.admin import ProjectOwnedAdmin

from .models import ManuscriptNode
from .hierarchy import CURRENT_TYPES, editable_node_ids, load_structure


@admin.register(ManuscriptNode)
class ManuscriptNodeAdmin(ProjectOwnedAdmin):
    actions = None
    list_display = (
        "title",
        "project",
        "parent",
        "node_type",
        "status",
        "position",
        "word_count",
        "is_publishable",
        "updated_at",
    )
    list_filter = ("node_type", "status", "is_publishable", "created_at")
    search_fields = ("title", "content", "project__name", "project__user__email")
    readonly_fields = ("word_count", "created_at", "updated_at")

    def get_readonly_fields(self, request, obj=None):
        fields = list(super().get_readonly_fields(request, obj))
        if obj:
            fields.extend(("parent", "node_type", "position"))
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
