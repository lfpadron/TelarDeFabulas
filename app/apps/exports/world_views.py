from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_http_methods

from apps.core.decorators import project_access
from apps.core.permissions import Action
from .world_forms import WorldExportForm


@login_required
@require_http_methods(["GET", "POST"])
@project_access(Action.EXPORT)
def create(request, project_pk):
    form = WorldExportForm(request.POST if request.method == "POST" else None, user=request.user, project=request.project)
    if request.method == "POST" and form.is_valid():
        try:
            job = form.save()
        except ValidationError as exc:
            form.add_error(None, ValidationError(exc.messages))
        else:
            messages.success(request, _("Solicitud de exportación de consulta conservada."))
            return redirect("exports:detail", project_pk=project_pk, export_pk=job.pk)
    return render(request, "exports/world_export_form.html", {"project": request.project, "form": form})
