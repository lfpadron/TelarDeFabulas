from django.apps import apps
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import SuspiciousFileOperation, ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, IntegerField, OuterRef, Q, Subquery
from django.db.models.functions import Coalesce
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_http_methods, require_safe

from apps.core.decorators import project_access
from apps.core.files import private_file_response
from apps.core.permissions import Action, get_user_project, local_project_relations
from .files import reference_path
from .forms import AssociationForm, ReferenceFilterForm, ReferenceForm, RevisionForm
from .models import ReferenceMaterial, TARGETS
from .selectors import project_associations
from .services import ReferenceConflict, delete_reference, detach_reference, project_storage_bytes, save_association
from .validators import safe_original_filename, validate_source_url


def selected_entity(request):
    selected = [(key, request.GET.get(param)) for key, (_, param, *_) in TARGETS.items() if param in request.GET]
    if not selected:
        return None
    if len(selected) != 1:
        raise Http404
    key, value = selected[0]
    if not value or not value.isascii() or not value.isdigit() or len(value) > 18:
        raise Http404
    query = local_project_relations(apps.get_model(TARGETS[key][0]).objects.filter(project=request.project))
    if key == "manuscript_node":
        query = query.visible()
    return get_object_or_404(query, pk=value)


def get_reference(request, pk):
    return get_object_or_404(ReferenceMaterial, pk=pk, project=request.project)


@login_required
@require_safe
@project_access()
def reference_list(request, project_pk):
    form = ReferenceFilterForm(request.GET)
    valid = form.is_valid()
    counts = project_associations(request.project).filter(reference_id=OuterRef("pk")).order_by().values("reference_id").annotate(total=Count("pk")).values("total")
    query = ReferenceMaterial.objects.filter(project=request.project).defer("notes").annotate(association_count=Coalesce(Subquery(counts, output_field=IntegerField()), 0))
    if valid:
        if form.cleaned_data["q"]:
            term = form.cleaned_data["q"]
            query = query.filter(Q(title__icontains=term) | Q(short_description__icontains=term) | Q(author__icontains=term) | Q(publisher__icontains=term))
        if form.cleaned_data["material_type"]:
            query = query.filter(material_type=form.cleaned_data["material_type"])
    return render(request, "references/list.html", {"project": request.project, "filter_form": form,
        "page": Paginator(query if valid else query.none(), 50).get_page(request.GET.get("page")),
        "storage_bytes": project_storage_bytes(request.project)}, status=200 if valid else 400)


@login_required
@require_safe
@project_access()
def detail(request, project_pk, reference_pk):
    reference = get_reference(request, reference_pk)
    external_url = ""
    if reference.source_url:
        try:
            validate_source_url(reference.source_url)
            external_url = reference.source_url
        except ValidationError:
            pass
    return render(request, "references/detail.html", {"project": request.project, "reference": reference, "external_url": external_url,
        "associations": Paginator(project_associations(request.project).filter(reference=reference), 50).get_page(request.GET.get("page"))})


def _form(request, reference=None):
    entity = selected_entity(request)
    form = ReferenceForm(request.POST if request.method == "POST" else None, request.FILES or None, instance=reference, project=request.project)
    if request.method == "POST" and form.is_valid():
        try:
            reference = form.save(user=request.user, entity=entity if reference is None else None)
        except ReferenceConflict as exc:
            form.revision_conflict = True
            form.add_error(None, exc)
        except ValidationError as exc:
            form.add_error(None, ValidationError(exc.messages))
        else:
            messages.success(request, _("Referencia guardada correctamente."))
            return redirect("references:detail", project_pk=request.project.pk, reference_pk=reference.pk)
    return render(request, "references/form.html", {"project": request.project, "reference": reference, "form": form,
        "entity": entity, "title": _("Editar referencia") if reference else _("Nueva referencia"), "conflict": form.revision_conflict},
        status=409 if form.revision_conflict else 200)


@login_required
@require_http_methods(["GET", "POST"])
@project_access(Action.CREATE)
def create(request, project_pk):
    return _form(request)


@login_required
@require_http_methods(["GET", "POST"])
@project_access(Action.EDIT)
def edit(request, project_pk, reference_pk):
    return _form(request, get_reference(request, reference_pk))


@login_required
@require_http_methods(["GET", "POST"])
@project_access(Action.DELETE)
def delete(request, project_pk, reference_pk):
    reference = get_reference(request, reference_pk)
    form = RevisionForm(request.POST if request.method == "POST" else None, initial={"expected_revision": reference.revision})
    status = 200
    if request.method == "POST" and form.is_valid():
        try:
            delete_reference(reference, expected_revision=form.cleaned_data["expected_revision"], user=request.user)
        except ValidationError as exc:
            form.add_error(None, ValidationError(exc.messages))
            status = 409
        else:
            messages.success(request, _("Referencia eliminada. Su archivo se limpia de forma segura; un fallo físico se reintentará."))
            return redirect("references:list", project_pk=project_pk)
    return render(request, "references/confirm_delete.html", {"project": request.project, "reference": reference, "form": form}, status=status)


@login_required
@require_safe
@project_access(Action.DOWNLOAD)
def download(request, project_pk, reference_pk):
    with transaction.atomic():
        get_user_project(request.user, project_pk, Action.DOWNLOAD, for_update=True)
        reference = get_reference(request, reference_pk)
        try:
            filename = safe_original_filename(reference.original_filename)
            stream = reference_path(project_pk, reference.file.name).open("rb")
        except (OSError, ValueError, ValidationError, SuspiciousFileOperation):
            raise Http404(_("Archivo no disponible.")) from None
    return private_file_response(stream, content_type=reference.mime_type or "application/octet-stream", filename=filename, as_attachment=True)


@login_required
@require_http_methods(["GET", "POST"])
@project_access(Action.EDIT)
def attach(request, project_pk, reference_pk=None):
    reference = get_reference(request, reference_pk) if reference_pk is not None else None
    entity = selected_entity(request)
    form = AssociationForm(request.POST if request.method == "POST" else None, project=request.project, reference=reference, entity=entity)
    if request.method == "POST" and form.is_valid():
        try:
            association = form.save(commit=False)
            save_association(association, user=request.user)
        except ValidationError as exc:
            form.add_error(None, ValidationError(exc.messages))
        else:
            messages.success(request, _("Referencia asociada correctamente."))
            return redirect(association.entity_url if entity else reverse("references:detail", args=[project_pk, association.reference_id]))
    return render(request, "references/form.html", {"project": request.project, "reference": reference, "entity": entity,
        "form": form, "title": _("Asociar referencia existente")})


@login_required
@require_http_methods(["GET", "POST"])
@project_access(Action.DELETE)
def detach(request, project_pk, association_pk):
    association = get_object_or_404(project_associations(request.project), pk=association_pk)
    return_url = association.entity_url if request.GET.get("return_to") == "entity" else reverse("references:detail", args=[project_pk, association.reference_id])
    if request.method == "POST":
        detach_reference(association, user=request.user)
        messages.success(request, _("Asociación eliminada. La referencia y su archivo se conservan."))
        return redirect(return_url)
    return render(request, "references/association_confirm_delete.html", {"project": request.project, "association": association, "return_url": return_url})
