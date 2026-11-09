from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.db import router, transaction
from django.http import Http404
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect

from apps.core.admin import ProjectOwnedAdmin
from apps.core.permissions import Action, get_user_project

from .forms import AdminEntryForm
from .models import WorldbuildingEntry
from .services import EDITABLE_FIELDS, save_entry, update_entry


@admin.register(WorldbuildingEntry)
class WorldbuildingEntryAdmin(ProjectOwnedAdmin):
    form = AdminEntryForm
    actions = None
    list_display = ("title", "project", "category", "position", "revision", "updated_at")
    list_filter = ("category",)
    search_fields = ("title", "short_description", "project__name")
    list_select_related = ("project",)
    readonly_fields = ("position", "revision", "created_at", "updated_at")

    def get_queryset(self, request):
        return super().get_queryset(request).defer("content")

    @method_decorator(csrf_protect)
    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        if request.method != "POST":
            return super().changeform_view(request, object_id, form_url, extra_context)
        using = router.db_for_write(self.model)
        with transaction.atomic(using=using):
            project_pk = self.get_object(request, object_id).project_id if object_id else request.POST.get("project", "")
            if not str(project_pk).isascii() or not str(project_pk).isdigit() or len(str(project_pk)) > 18:
                raise Http404
            # Hold the project lock across form validation AND save_model; validation alone is not a CAS.
            get_user_project(request.user, project_pk, Action.EDIT if object_id else Action.CREATE, for_update=True)
            response = super().changeform_view(request, object_id, form_url, extra_context)
            adminform = getattr(response, "context_data", {}).get("adminform")
            if adminform and adminform.form.revision_conflict:
                response.status_code = 409
            return response

    def save_model(self, request, obj, form, change):
        if not change:
            save_entry(obj, user=request.user)
        else:
            current = update_entry(obj, user=request.user, expected_revision=form.cleaned_data["expected_revision"],
                                   **{key: form.cleaned_data[key] for key in EDITABLE_FIELDS})
            obj.revision, obj.position, obj.updated_at = current.revision, current.position, current.updated_at
            obj._loaded_revision = current.revision

    def has_delete_permission(self, request, obj=None):
        # Use the author's revision-aware confirmation view for individual deletion.
        return False

    def delete_queryset(self, request, queryset):
        raise PermissionDenied
