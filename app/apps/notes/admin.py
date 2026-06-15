from django.contrib import admin

from .models import Note


@admin.register(Note)
class NoteAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "project",
        "note_type",
        "status",
        "priority",
        "node",
        "character",
        "updated_at",
        "completed_at",
    )
    list_filter = ("note_type", "status", "priority", "created_at", "updated_at", "completed_at")
    search_fields = (
        "title",
        "content",
        "project__name",
        "project__user__email",
        "node__title",
        "character__name",
    )
    readonly_fields = ("created_at", "updated_at", "completed_at")
