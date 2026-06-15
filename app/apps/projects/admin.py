from django.contrib import admin

from .models import Project


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ("name", "user", "status", "locale", "created_at", "scheduled_deletion_at")
    list_filter = ("status", "language", "locale", "created_at")
    search_fields = ("name", "description", "user__email")
    readonly_fields = (
        "created_at",
        "updated_at",
        "frozen_at",
        "deletion_requested_at",
        "scheduled_deletion_at",
        "deleted_at",
    )
