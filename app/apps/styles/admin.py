from django.contrib import admin

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
    readonly_fields = ("created_at", "updated_at")
