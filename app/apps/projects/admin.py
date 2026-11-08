from django.contrib import admin

from apps.core.admin import ProjectOwnedAdmin

from .models import Project


@admin.register(Project)
class ProjectAdmin(ProjectOwnedAdmin):
    project_lookup = ""
    exclude = ("user",)
    list_display = ("name", "user", "status", "locale", "created_at", "scheduled_deletion_at")
    list_filter = ("status", "language", "locale", "created_at")
    search_fields = ("name", "description", "user__email")
    readonly_fields = (
        "status",
        "created_at",
        "updated_at",
        "frozen_at",
        "deletion_requested_at",
        "scheduled_deletion_at",
        "deleted_at",
    )

    def has_delete_permission(self, request, obj=None):
        # Project deletion retains the existing 90-day workflow in the application.
        return False
