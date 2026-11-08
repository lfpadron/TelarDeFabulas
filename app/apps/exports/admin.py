from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from apps.core.admin import ProjectOwnedAdmin

from .models import ExportJob


@admin.register(ExportJob)
class ExportJobAdmin(ProjectOwnedAdmin):
    exclude = ("file",)
    list_display = (
        "id",
        "project",
        "user",
        "format",
        "export_mode",
        "status",
        "style_template",
        "root_node",
        "created_at",
        "finished_at",
        "attempt_count",
        "expires_at",
        "notification_sent_at",
    )
    list_filter = ("format", "export_mode", "status", "created_at", "started_at", "finished_at")
    search_fields = (
        "project__name",
        "user__email",
        "root_node__title",
        "style_template__name",
        "error_message",
    )
    readonly_fields = ("private_download", "created_at", "started_at", "finished_at")

    def get_queryset(self, request):
        return super().get_queryset(request).filter(user=request.user)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description=_("archivo privado"))
    def private_download(self, obj):
        if not obj.downloadable:
            return "-"
        url = reverse("exports:download", args=[obj.project_id, obj.pk])
        return format_html('<a href="{}">{}</a>', url, _("Descargar"))
