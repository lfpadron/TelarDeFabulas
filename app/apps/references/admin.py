from django.contrib import admin
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import Http404
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from django.views.decorators.csrf import csrf_protect

from apps.core.admin import ProjectOwnedAdmin
from apps.core.permissions import Action, get_user_project
from .forms import AdminReferenceForm
from .models import ReferenceAssociation, ReferenceMaterial, TARGETS
from .selectors import local_associations
from .services import save_association


@admin.register(ReferenceMaterial)
class ReferenceMaterialAdmin(ProjectOwnedAdmin):
    form = AdminReferenceForm
    actions = None
    list_display = ("title", "project", "material_type", "author", "file_size", "updated_at")
    list_filter = ("material_type",)
    search_fields = ("title", "short_description", "author", "project__name")
    list_select_related = ("project",)
    readonly_fields = ("file_size", "mime_type", "original_filename", "revision", "private_download", "created_at", "updated_at")

    def get_queryset(self, request):
        return super().get_queryset(request).defer("notes")

    def get_exclude(self, request, obj=None):
        return ("file",) if obj and not self.has_change_permission(request, obj) else ()

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        error = getattr(request, "reference_save_error", None)
        if error:
            class FailedUploadForm(form):
                def clean(self):
                    super().clean()
                    raise error
            return FailedUploadForm
        return form

    @admin.display(description=_("Archivo privado"))
    def private_download(self, obj):
        if not obj or not obj.pk or not obj.file:
            return "-"
        return format_html('<a href="{}">{}</a>', reverse("references:download", args=[obj.project_id, obj.pk]), _("Descargar"))

    @method_decorator(csrf_protect)
    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        if request.method != "POST":
            return super().changeform_view(request, object_id, form_url, extra_context)
        try:
            with transaction.atomic():
                pk = self.get_object(request, object_id).project_id if object_id else request.POST.get("project", "")
                if not str(pk).isascii() or not str(pk).isdigit() or len(str(pk)) > 18:
                    raise Http404
                get_user_project(request.user, pk, Action.EDIT if object_id else Action.CREATE, for_update=True)
                response = super().changeform_view(request, object_id, form_url, extra_context)
                adminform = getattr(response, "context_data", {}).get("adminform")
                if adminform and adminform.form.revision_conflict:
                    response.status_code = 409
                return response
        except ValidationError as exc:
            # Render the submitted form after rolling back a failed filesystem write.
            request.reference_save_error = ValidationError(exc.messages)
            return super().changeform_view(request, object_id, form_url, extra_context)

    def save_model(self, request, obj, form, change):
        saved = form.save(user=request.user)
        for field in obj._meta.concrete_fields:
            setattr(obj, field.attname, getattr(saved, field.attname))
        obj._state.adding, obj._state.db = False, saved._state.db

    def has_delete_permission(self, request, obj=None):
        return False

    def delete_queryset(self, request, queryset):
        raise PermissionDenied


@admin.register(ReferenceAssociation)
class ReferenceAssociationAdmin(ProjectOwnedAdmin):
    project_lookup = "reference__project"
    actions = None
    list_display = ("reference", *TARGETS, "description", "created_at")
    list_select_related = ("reference", "reference__project", *TARGETS)
    search_fields = ("reference__title", "description")
    readonly_fields = ("created_at",)

    def get_queryset(self, request):
        return local_associations(super().get_queryset(request)).defer(
            "reference__notes", "manuscript_node__content", "character__biography", "geographic_location__detailed_description",
            "organization__detailed_description", "worldbuilding_entry__content")

    @method_decorator(csrf_protect)
    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        if request.method != "POST":
            return super().changeform_view(request, object_id, form_url, extra_context)
        with transaction.atomic():
            if object_id:
                project_id = self.get_object(request, object_id).reference.project_id
            else:
                pk = request.POST.get("reference", "")
                if not pk.isascii() or not pk.isdigit() or len(pk) > 18:
                    raise Http404
                project_id = ReferenceMaterial.objects.filter(pk=pk).values_list("project_id", flat=True).first()
                if project_id is None:
                    raise Http404
            get_user_project(request.user, project_id, Action.EDIT, for_update=True)
            return super().changeform_view(request, object_id, form_url, extra_context)

    def get_readonly_fields(self, request, obj=None):
        return (*super().get_readonly_fields(request, obj), *(TARGETS if obj else ()))

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        reference = obj.reference if obj else None
        if reference is None and "reference" in form.base_fields:
            pk = request.POST.get("reference") or request.GET.get("reference", "")
            if str(pk).isascii() and str(pk).isdigit() and len(str(pk)) <= 18:
                reference = form.base_fields["reference"].queryset.filter(pk=pk).first()
        if reference:
            for key in TARGETS:
                if key in form.base_fields:
                    form.base_fields[key].queryset = form.base_fields[key].queryset.filter(project_id=reference.project_id)
        return form

    def save_model(self, request, obj, form, change):
        save_association(obj, user=request.user)

    def delete_queryset(self, request, queryset):
        raise PermissionDenied
