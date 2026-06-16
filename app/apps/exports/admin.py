from django.contrib import admin

from .models import ExportJob


@admin.register(ExportJob)
class ExportJobAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "project",
        "user",
        "format",
        "status",
        "style_template",
        "root_node",
        "created_at",
        "finished_at",
    )
    list_filter = ("format", "status", "created_at", "started_at", "finished_at")
    search_fields = (
        "project__name",
        "user__email",
        "root_node__title",
        "style_template__name",
        "error_message",
    )
    readonly_fields = ("created_at", "started_at", "finished_at")
