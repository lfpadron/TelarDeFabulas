from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Case, CharField, Value, When
from django.http import Http404
from django.utils.decorators import method_decorator
from django.utils.translation import gettext_lazy as _
from django.views.decorators.csrf import csrf_protect

from apps.core.admin import ProjectOwnedAdmin
from apps.core.permissions import Action, get_user_project

from .models import ManuscriptNode, SceneVersion
from .hierarchy import CURRENT_TYPES, editable_node_ids, load_structure
from .visibility import hidden_node_ids


class TrashStateFilter(admin.SimpleListFilter):
    title = _("Papelera")
    parameter_name = "trash_state"

    def lookups(self, request, model_admin):
        return (("ACTIVE", _("Activo")), ("DELETED", _("Eliminado")), ("HIDDEN", _("Oculto por ancestro")))

    def queryset(self, request, queryset):
        if self.value() in ("ACTIVE", "DELETED", "HIDDEN"):
            return queryset.filter(trash_state=self.value())
        return queryset


@admin.register(ManuscriptNode)
class ManuscriptNodeAdmin(ProjectOwnedAdmin):
    actions = None
    list_display = (
        "title",
        "project",
        "parent",
        "node_type",
        "trash_status",
        "legacy_status",
        "position",
        "legacy_word_count",
        "legacy_publishable",
        "updated_at",
    )
    list_filter = (TrashStateFilter, "node_type", "status", "is_publishable", "created_at")
    search_fields = ("title", "versions__content", "project__name", "project__user__email")
    readonly_fields = ("word_count", "created_at", "updated_at", "current_draft_version", "deleted_at", "deleted_by")

    @method_decorator(csrf_protect)
    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        if request.method != "POST":
            return super().changeform_view(request, object_id, form_url, extra_context)
        with transaction.atomic():
            pk = self.get_object(request, object_id).project_id if object_id else request.POST.get("project", "")
            if not str(pk).isascii() or not str(pk).isdigit() or len(str(pk)) > 18:
                raise Http404
            get_user_project(request.user, pk, Action.EDIT if object_id else Action.CREATE, for_update=True)
            return super().changeform_view(request, object_id, form_url, extra_context)

    def get_queryset(self, request):
        query = super().get_queryset(request)
        hidden = hidden_node_ids(query.order_by().values("project_id"), query.db)
        return query.annotate(trash_state=Case(
            When(deleted_at__isnull=False, then=Value("DELETED")),
            When(pk__in=hidden, then=Value("HIDDEN")), default=Value("ACTIVE"), output_field=CharField()))

    @admin.display(description=_("Papelera"))
    def trash_status(self, obj):
        return {"ACTIVE": _("Activo"), "DELETED": _("Eliminado"), "HIDDEN": _("Oculto por ancestro")}[obj.trash_state]

    def get_search_results(self, request, queryset, search_term):
        if search_term and not request.GET.get("trash_state"):
            queryset = queryset.filter(trash_state="ACTIVE")
        return super().get_search_results(request, queryset, search_term)

    @admin.display(description=_("Estado legado"))
    def legacy_status(self, obj):
        return obj.get_status_display()

    @admin.display(description=_("Palabras legadas"))
    def legacy_word_count(self, obj):
        return obj.word_count

    @admin.display(description=_("Publicable legado"), boolean=True)
    def legacy_publishable(self, obj):
        return obj.is_publishable

    def get_fieldsets(self, request, obj=None):
        if obj and obj.node_type == "SCENE":
            return (
                (None, {"fields": ("project", "parent", "node_type", "title", "short_description", "position", "current_draft_version", "created_at", "updated_at", "deleted_at", "deleted_by")}),
                (_("Datos legados de la escena"), {"fields": ("content", "status", "word_count", "is_publishable"), "classes": ("collapse",)}),
            )
        return super().get_fieldsets(request, obj)

    def get_readonly_fields(self, request, obj=None):
        fields = list(super().get_readonly_fields(request, obj))
        if obj:
            fields.extend(("parent", "node_type", "position"))
            if obj.node_type == "SCENE":
                fields.extend(("content", "status", "is_publishable"))
        return fields

    def has_change_permission(self, request, obj=None):
        return super().has_change_permission(request, obj) and (
            obj is None or (ManuscriptNode.objects.filter(project_id=obj.project_id).visible().filter(pk=obj.pk).exists()
                            and obj.pk in editable_node_ids(load_structure(obj.project_id)))
        )

    def has_delete_permission(self, request, obj=None):
        return False

    def delete_model(self, request, obj):
        raise PermissionDenied

    def formfield_for_choice_field(self, db_field, request, **kwargs):
        if db_field.name == "node_type":
            kwargs["choices"] = [(value, label) for value, label in ManuscriptNode.NodeType.choices if value in CURRENT_TYPES]
        return super().formfield_for_choice_field(db_field, request, **kwargs)

    def delete_queryset(self, request, queryset):
        raise PermissionDenied


@admin.register(SceneVersion)
class SceneVersionAdmin(ProjectOwnedAdmin):
    project_lookup = "scene__project"
    actions = None
    list_display = ("scene", "version_number", "editorial_stage", "is_current_final", "revision", "word_count", "created_at", "updated_at", "finalized_at")
    search_fields = ("scene__title", "scene__project__name", "scene__project__user__email")
    list_filter = ("editorial_stage", "created_at", "finalized_at")
    readonly_fields = tuple(field.name for field in SceneVersion._meta.fields)

    def get_queryset(self, request):
        query = super().get_queryset(request)
        nodes = ManuscriptNode.objects.filter(project__user=request.user).visible()
        return query.filter(scene__in=nodes)

    def get_readonly_fields(self, request, obj=None):
        return self.readonly_fields

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
