from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import redirect
from django.urls import reverse

from apps.core.admin import ProjectOwnedAdmin

from .models import GeographicLocation
from .services import deletion_blockers, get_valid_parent_queryset


@admin.register(GeographicLocation)
class GeographicLocationAdmin(ProjectOwnedAdmin):
    actions = None
    list_display = ("name", "project", "location_type", "parent", "position", "updated_at")
    list_filter = ("location_type", "created_at", "updated_at")
    search_fields = ("name", "short_description", "project__name", "project__user__email")
    readonly_fields = ("position", "created_at", "updated_at")
    list_select_related = ("project", "parent")

    def get_readonly_fields(self, request, obj=None):
        return (*super().get_readonly_fields(request, obj), *(("parent",) if obj else ()))

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        if "parent" in form.base_fields:
            project_id = request.POST.get("project") or request.GET.get("project")
            projects = form.base_fields["project"].queryset
            project = projects.filter(pk=project_id).first() if str(project_id).isdigit() else None
            form.base_fields["parent"].queryset = get_valid_parent_queryset(project) if project else GeographicLocation.objects.none()
        return form

    def has_delete_permission(self, request, obj=None):
        return super().has_delete_permission(request, obj) and (obj is None or not deletion_blockers(obj))

    def delete_queryset(self, request, queryset):
        raise PermissionDenied

    def delete_view(self, request, object_id, extra_context=None):
        try:
            return super().delete_view(request, object_id, extra_context)
        except ValidationError as exc:
            self.message_user(request, " ".join(exc.messages), level=messages.ERROR)
            return redirect(reverse("admin:geography_geographiclocation_change", args=[object_id]))
