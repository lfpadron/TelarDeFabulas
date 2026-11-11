from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST

from apps.core.decorators import project_access
from apps.core.permissions import Action

from .forms import SceneVersionActionForm, SceneVersionEditForm
from .models import ManuscriptNode, SceneVersion
from .hierarchy import validate_node_hierarchy
from .version_services import (
    RevisionConflict, create_scene_version, finalize_scene_version,
    get_current_draft_version, get_current_final_version,
    restore_scene_version, update_scene_version,
)
from .views import require_editable_node


def get_scene(request, node_pk, *, writing=False):
    scene = get_object_or_404(ManuscriptNode.objects.filter(project=request.project).visible(), pk=node_pk, node_type="SCENE")
    if writing:
        require_editable_node(scene)
    return scene


def get_version(scene, version_pk):
    return get_object_or_404(SceneVersion, pk=version_pk, scene=scene)


def version_context(scene, **kwargs):
    try:
        validate_node_hierarchy(scene)
        writable = True
    except ValidationError:
        writable = False
    return {"project": scene.project, "scene": scene,
            "version_writable": writable,
            "draft": get_current_draft_version(scene), "final": get_current_final_version(scene), **kwargs}


@login_required
@project_access()
def version_history(request, project_pk, node_pk):
    scene = get_scene(request, node_pk)
    page = Paginator(scene.versions.defer("content").order_by("-version_number"), 30).get_page(request.GET.get("page"))
    return render(request, "manuscripts/version_history.html", version_context(scene, page_obj=page))


@login_required
@project_access()
def version_detail(request, project_pk, node_pk, version_pk):
    scene = get_scene(request, node_pk)
    return render(request, "manuscripts/version_detail.html", version_context(scene, version=get_version(scene, version_pk)))


@login_required
@project_access(Action.EDIT)
def version_edit(request, project_pk, node_pk, version_pk):
    scene = get_scene(request, node_pk, writing=True)
    version = get_version(scene, version_pk)
    status = 200
    if request.method == "POST":
        form = SceneVersionEditForm(request.POST)
        if form.is_valid():
            try:
                update_scene_version(scene, version, user=request.user, expected_revision=form.cleaned_data["revision"], content=form.cleaned_data["content"])
            except RevisionConflict as error:
                form.add_error(None, error)
                status = 409
            except ValidationError as error:
                form.add_error(None, error)
                status = 400
            else:
                messages.success(request, _("Versión guardada correctamente."))
                return redirect("manuscripts:version_detail", project_pk=project_pk, node_pk=node_pk, version_pk=version_pk)
        else:
            status = 400
    else:
        if version.editorial_stage == "FINAL":
            raise PermissionDenied(_("Una versión definitiva no se edita. Crea una nueva versión."))
        form = SceneVersionEditForm(initial={"content": version.content, "revision": version.revision})
    return render(request, "manuscripts/version_edit.html", version_context(scene, version=version, form=form), status=status)


def apply_action(request, scene, version, action):
    form = SceneVersionActionForm(request.POST)
    status = 400
    if form.is_valid():
        try:
            kwargs = {"user": request.user, "expected_revision": form.cleaned_data["revision"]}
            if action == "create":
                result = create_scene_version(scene, source_version=version, **kwargs)
            elif action == "restore":
                result = restore_scene_version(scene, version, **kwargs)
            elif action == "finalize":
                result = finalize_scene_version(scene, version, **kwargs)
            else:
                result = update_scene_version(scene, version, editorial_stage="REVIEW", **kwargs)
        except RevisionConflict as error:
            form.add_error(None, error)
            status = 409
        except ValidationError as error:
            form.add_error(None, error)
        else:
            messages.success(request, _("Historial actualizado correctamente."))
            return redirect("manuscripts:version_detail", project_pk=scene.project_id, node_pk=scene.pk, version_pk=result.pk)
    return render(request, "manuscripts/version_detail.html", version_context(scene, version=version, action_form=form), status=status)


@login_required
@require_POST
@project_access(Action.CREATE)
def version_create(request, project_pk, node_pk):
    scene = get_scene(request, node_pk, writing=True)
    try:
        source_pk = int(request.POST.get("source_version", ""))
    except (TypeError, ValueError):
        raise Http404(_("Versión de origen no encontrada.")) from None
    return apply_action(request, scene, get_version(scene, source_pk), "create")


@login_required
@require_POST
@project_access(Action.EDIT)
def version_review(request, project_pk, node_pk, version_pk):
    scene = get_scene(request, node_pk, writing=True)
    return apply_action(request, scene, get_version(scene, version_pk), "review")


@login_required
@require_POST
@project_access(Action.EDIT)
def version_finalize(request, project_pk, node_pk, version_pk):
    scene = get_scene(request, node_pk, writing=True)
    return apply_action(request, scene, get_version(scene, version_pk), "finalize")


@login_required
@require_POST
@project_access(Action.CREATE)
def version_restore(request, project_pk, node_pk, version_pk):
    scene = get_scene(request, node_pk, writing=True)
    return apply_action(request, scene, get_version(scene, version_pk), "restore")
