from django.contrib import admin
from django.db.models import Q
from django.http import Http404

from apps.core.permissions import user_can_manage_personal_styles

from .models import StyleTemplate


@admin.register(StyleTemplate)
class StyleTemplateAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "user",
        "is_system",
        "font_category",
        "font_heading",
        "font_body",
        "text_alignment",
        "updated_at",
    )
    list_filter = ("is_system", "font_category", "text_alignment", "created_at", "updated_at")
    search_fields = ("name", "description", "user__email", "font_heading", "font_body")
    readonly_fields = ("user", "is_system", "created_at", "updated_at")

    def get_queryset(self, request):
        return super().get_queryset(request).filter(Q(is_system=True) | Q(user=request.user))

    def get_object(self, request, object_id, from_field=None):
        obj = super().get_object(request, object_id, from_field)
        if obj is None:
            raise Http404
        return obj

    def has_add_permission(self, request):
        return super().has_add_permission(request) and user_can_manage_personal_styles(request.user)

    def has_change_permission(self, request, obj=None):
        if not super().has_change_permission(request, obj):
            return False
        if obj and obj.is_system:
            return request.user.is_superuser
        return user_can_manage_personal_styles(request.user) and (obj is None or obj.user_id == request.user.pk)

    def has_delete_permission(self, request, obj=None):
        return super().has_delete_permission(request, obj) and user_can_manage_personal_styles(request.user) and (
            obj is None or (obj.user_id == request.user.pk and not obj.is_system)
        )

    def get_form(self, request, obj=None, **kwargs):
        base_form = super().get_form(request, obj, **kwargs)

        class OwnedStyleForm(base_form):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                if not self.instance.pk:
                    self.instance.user = request.user
                    self.instance.is_system = False

        return OwnedStyleForm

    def delete_queryset(self, request, queryset):
        if queryset.exclude(user=request.user, is_system=False).exists():
            raise Http404
        super().delete_queryset(request, queryset)
