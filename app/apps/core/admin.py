from functools import reduce

from django.contrib import admin
from django.db import models, transaction
from django.http import Http404

from .permissions import Action, can_access_project, check_project_permission, get_user_project, local_project_relations, visible_projects
from .widgets import PrivateFileInput


class ProjectOwnedAdmin(admin.ModelAdmin):
    """Django model permissions never imply access to another author's project."""
    project_lookup = "project"
    formfield_overrides = {models.FileField: {"widget": PrivateFileInput}}

    def project_for(self, obj):
        return reduce(getattr, self.project_lookup.split("__"), obj) if self.project_lookup else obj

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        lookup = self.project_lookup or "pk"
        queryset = queryset.filter(**{f"{lookup}__in": visible_projects(request.user)})
        return local_project_relations(queryset, self.project_lookup) if self.project_lookup else queryset

    def get_object(self, request, object_id, from_field=None):
        obj = super().get_object(request, object_id, from_field)
        if obj is None:
            raise Http404
        return obj

    def has_view_permission(self, request, obj=None):
        return super().has_view_permission(request, obj) and (
            obj is None or can_access_project(request.user, self.project_for(obj), Action.VIEW)
        )

    def has_change_permission(self, request, obj=None):
        return super().has_change_permission(request, obj) and (
            obj is None or can_access_project(request.user, self.project_for(obj), Action.EDIT)
        )

    def has_delete_permission(self, request, obj=None):
        return super().has_delete_permission(request, obj) and (
            obj is None or can_access_project(request.user, self.project_for(obj), Action.DELETE)
        )

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        model = db_field.remote_field.model
        fields = {field.name for field in model._meta.fields}
        projects = visible_projects(request.user).filter(status="ACTIVE")
        if model._meta.label_lower == "projects.project":
            kwargs["queryset"] = projects
        elif "project" in fields:
            kwargs["queryset"] = model.objects.filter(project__in=projects)
        elif model._meta.label_lower == "accounts.user":
            kwargs["queryset"] = model.objects.filter(pk=request.user.pk)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def get_readonly_fields(self, request, obj=None):
        fields = list(super().get_readonly_fields(request, obj))
        if obj:
            identity_field = self.project_lookup.split("__")[0] if self.project_lookup else "user"
            fields.append(identity_field)
        return fields

    def save_model(self, request, obj, form, change):
        if not self.project_lookup and not change:
            obj.user = request.user
        else:
            project = get_user_project(
                request.user, self.project_for(obj).pk,
                Action.EDIT if change else Action.CREATE, for_update=True,
            )
            check_project_permission(request.user, project, Action.EDIT)
        super().save_model(request, obj, form, change)

    def delete_model(self, request, obj):
        get_user_project(request.user, self.project_for(obj).pk, Action.DELETE, for_update=True)
        super().delete_model(request, obj)

    def delete_queryset(self, request, queryset):
        with transaction.atomic():
            project_ids = sorted({self.project_for(obj).pk for obj in queryset})
            for pk in project_ids:
                get_user_project(request.user, pk, Action.DELETE, for_update=True)
            super().delete_queryset(request, queryset)
