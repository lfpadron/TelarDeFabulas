from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import redirect, render
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_http_methods, require_safe

from apps.core.decorators import project_access
from apps.core.permissions import Action

from .services import get_valid_parent_queryset
from .trash import get_trash_items, restore_node


class RestoreNodeForm(forms.Form):
    parent = forms.ModelChoiceField(label=_("Destino"), queryset=None, required=False)
    position = forms.IntegerField(label=_("Posición"), min_value=1, required=False)

    def __init__(self, *args, node, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["parent"].queryset = get_valid_parent_queryset(node.project, node)
        self.fields["parent"].required = node.node_type != "BOOK"
        self.fields["parent"].empty_label = _("Raíz del proyecto") if node.node_type == "BOOK" else _("Selecciona un destino")
        self.initial.update(parent=node.parent_id, position=node.position)


def trash_item(request, node_pk):
    for item in get_trash_items(request.project, user=request.user):
        if item["node"].pk == node_pk:
            item["node"].project = request.project
            return item
    raise Http404


@login_required
@require_safe
@project_access()
def trash_list(request, project_pk):
    items = get_trash_items(request.project, user=request.user)
    return render(request, "manuscripts/trash_list.html", {"project": request.project,
        "page": Paginator(items, 50).get_page(request.GET.get("page"))})


@login_required
@require_safe
@project_access()
def trash_detail(request, project_pk, node_pk):
    return render(request, "manuscripts/trash_detail.html", {"project": request.project,
        "item": trash_item(request, node_pk)})


@login_required
@require_http_methods(["GET", "POST"])
@project_access(Action.EDIT)
def trash_restore(request, project_pk, node_pk):
    item = trash_item(request, node_pk)
    form = RestoreNodeForm(request.POST if request.method == "POST" else None, node=item["node"])
    if request.method == "POST" and form.is_valid():
        try:
            node = restore_node(item["node"], user=request.user, new_parent=form.cleaned_data["parent"],
                                position=form.cleaned_data["position"])
        except ValidationError as error:
            form.add_error(None, " ".join(error.messages))
        else:
            messages.success(request, _("Nodo restaurado con sus versiones y vínculos originales."))
            return redirect("manuscripts:detail", project_pk=project_pk, node_pk=node.pk)
    return render(request, "manuscripts/trash_restore.html", {"project": request.project, "item": item, "form": form})
