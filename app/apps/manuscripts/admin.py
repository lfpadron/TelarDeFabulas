from django.contrib import admin

from .models import ManuscriptNode


@admin.register(ManuscriptNode)
class ManuscriptNodeAdmin(admin.ModelAdmin):
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
