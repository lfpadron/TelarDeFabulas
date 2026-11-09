from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import redirect
from django.urls import reverse

from apps.core.admin import ProjectOwnedAdmin
from apps.core.permissions import local_project_relations

from .models import CharacterOrganizationMembership, Organization
from .services import deletion_blockers


@admin.register(Organization)
class OrganizationAdmin(ProjectOwnedAdmin):
    actions = None
    list_display = ("name", "project", "organization_type", "parent", "headquarters", "position", "updated_at")
    list_filter = ("organization_type", "created_at", "updated_at")
    search_fields = ("name", "short_description", "project__name", "project__user__email")
    list_select_related = ("project", "parent", "headquarters")
    readonly_fields = ("position", "created_at", "updated_at")

    def get_readonly_fields(self, request, obj=None):
        return (*super().get_readonly_fields(request, obj), *(("parent",) if obj else ()))

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        project_id = obj.project_id if obj else request.POST.get("project") or request.GET.get("project")
        for key in ("parent", "headquarters"):
            if key in form.base_fields:
                queryset = local_project_relations(form.base_fields[key].queryset)
                form.base_fields[key].queryset = queryset.filter(project_id=project_id).only("id", "name") if str(project_id).isdigit() else queryset.none()
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
            return redirect(reverse("admin:organizations_organization_change", args=[object_id]))


@admin.register(CharacterOrganizationMembership)
class MembershipAdmin(ProjectOwnedAdmin):
    project_lookup = "organization__project"
    actions = None
    list_display = ("character", "organization", "position_title", "membership_status", "joined_at_text", "left_at_text")
    list_filter = ("membership_status", "created_at", "updated_at")
    search_fields = ("character__name", "organization__name", "organization__project__name", "position_title")
    list_select_related = ("character", "organization", "organization__project")
    readonly_fields = ("created_at", "updated_at")

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        project_id = obj.organization.project_id if obj else None
        if project_id is None and "organization" in form.base_fields:
            raw = request.POST.get("organization") or request.GET.get("organization")
            if str(raw).isdigit():
                organization = form.base_fields["organization"].queryset.filter(pk=raw).first()
                project_id = organization.project_id if organization else None
        for key in ("character", "organization"):
            if key in form.base_fields:
                queryset = local_project_relations(form.base_fields[key].queryset)
                if project_id is not None:
                    queryset = queryset.filter(project_id=project_id)
                form.base_fields[key].queryset = queryset.only("id", "name")
        return form

    def delete_queryset(self, request, queryset):
        raise PermissionDenied
