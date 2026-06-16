from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST

from apps.accounts.models import User

from .forms import StyleTemplateForm
from .models import StyleTemplate


def user_can_manage_personal_styles(user):
    return getattr(user, "user_type", None) in (
        User.UserType.PREMIUM,
        User.UserType.BUSINESS_ADMIN,
        User.UserType.TECH_ADMIN,
    )


def visible_styles_for_user(user):
    return StyleTemplate.objects.filter(Q(is_system=True) | Q(user=user)).order_by("-is_system", "name")


def get_visible_style(user, style_pk):
    return get_object_or_404(visible_styles_for_user(user), pk=style_pk)


def get_owned_personal_style(user, style_pk):
    return get_object_or_404(StyleTemplate, pk=style_pk, user=user, is_system=False)


@login_required
def style_list(request):
    return render(
        request,
        "styles/style_list.html",
        {
            "styles": visible_styles_for_user(request.user),
            "can_manage_styles": user_can_manage_personal_styles(request.user),
        },
    )


@login_required
def style_create(request):
    if not user_can_manage_personal_styles(request.user):
        messages.error(request, _("Tu cuenta actual puede usar estilos del sistema, pero no crear estilos personalizados."))
        return redirect("styles:list")

    if request.method == "POST":
        form = StyleTemplateForm(request.POST, user=request.user)
        if form.is_valid():
            style = form.save(commit=False)
            style.user = request.user
            style.is_system = False
            style.save()
            messages.success(request, _("Estilo creado correctamente."))
            return redirect("styles:detail", style_pk=style.pk)
    else:
        form = StyleTemplateForm(user=request.user)

    return render(
        request,
        "styles/style_form.html",
        {
            "form": form,
            "title": _("Crear estilo"),
            "submit_label": _("Crear estilo"),
        },
    )


@login_required
def style_detail(request, style_pk):
    style = get_visible_style(request.user, style_pk)
    return render(
        request,
        "styles/style_detail.html",
        {
            "style": style,
            "can_edit_style": user_can_manage_personal_styles(request.user) and style.user_id == request.user.id and not style.is_system,
            "can_duplicate_style": user_can_manage_personal_styles(request.user),
            "can_delete_style": style.user_id == request.user.id and not style.is_system,
        },
    )


@login_required
def style_edit(request, style_pk):
    if not user_can_manage_personal_styles(request.user):
        messages.error(request, _("Tu cuenta actual no puede editar estilos personalizados."))
        return redirect("styles:list")

    style = get_owned_personal_style(request.user, style_pk)

    if request.method == "POST":
        form = StyleTemplateForm(request.POST, instance=style, user=request.user)
        if form.is_valid():
            style = form.save(commit=False)
            style.user = request.user
            style.is_system = False
            style.save()
            messages.success(request, _("Estilo actualizado correctamente."))
            return redirect("styles:detail", style_pk=style.pk)
    else:
        form = StyleTemplateForm(instance=style, user=request.user)

    return render(
        request,
        "styles/style_form.html",
        {
            "form": form,
            "style": style,
            "title": _("Editar estilo"),
            "submit_label": _("Guardar estilo"),
        },
    )


@login_required
@require_POST
def style_duplicate(request, style_pk):
    if not user_can_manage_personal_styles(request.user):
        messages.error(request, _("Tu cuenta actual no puede duplicar estilos."))
        return redirect("styles:list")

    source = get_visible_style(request.user, style_pk)
    duplicate = StyleTemplate.objects.create(
        user=request.user,
        name=_("Copia de %(name)s") % {"name": source.name},
        description=source.description,
        is_system=False,
        font_category=source.font_category,
        font_heading=source.font_heading,
        font_body=source.font_body,
        heading_size=source.heading_size,
        body_size=source.body_size,
        line_spacing=source.line_spacing,
        paragraph_spacing=source.paragraph_spacing,
        margin_top=source.margin_top,
        margin_bottom=source.margin_bottom,
        margin_left=source.margin_left,
        margin_right=source.margin_right,
        text_alignment=source.text_alignment,
        first_line_indent=source.first_line_indent,
        scene_separator=source.scene_separator,
        include_page_numbers=source.include_page_numbers,
        include_table_of_contents=source.include_table_of_contents,
        config_json=dict(source.config_json or {}),
    )
    messages.success(request, _("Estilo duplicado correctamente."))
    return redirect("styles:detail", style_pk=duplicate.pk)


@login_required
def style_delete(request, style_pk):
    style = get_visible_style(request.user, style_pk)
    if style.is_system:
        messages.error(request, _("No se pueden borrar estilos del sistema desde la interfaz normal."))
        return redirect("styles:detail", style_pk=style.pk)
    if style.user_id != request.user.id:
        raise Http404(_("No puedes borrar estilos ajenos."))

    if request.method == "POST":
        style.delete()
        messages.success(request, _("Estilo borrado correctamente."))
        return redirect("styles:list")

    return render(request, "styles/style_confirm_delete.html", {"style": style})
