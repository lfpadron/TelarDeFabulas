from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from .models import Character, CharacterDramaticRole, CharacterMention


class CharacterDramaticRoleInline(admin.TabularInline):
    model = CharacterDramaticRole
    extra = 0


@admin.register(Character)
class CharacterAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "project",
        "importance",
        "narrative_role",
        "completion_status",
        "completion_percentage_display",
        "updated_at",
    )
    list_filter = ("importance", "narrative_role", "completion_status", "created_at")
    search_fields = ("name", "alias", "project__name", "project__user__email")
    readonly_fields = ("completion_percentage_display", "created_at", "updated_at")
    inlines = (CharacterDramaticRoleInline,)

    @admin.display(description=_("completitud"))
    def completion_percentage_display(self, obj):
        return f"{obj.completion_percentage}%"


@admin.register(CharacterDramaticRole)
class CharacterDramaticRoleAdmin(admin.ModelAdmin):
    list_display = ("character", "role", "custom_role", "updated_at")
    list_filter = ("role", "created_at")
    search_fields = ("character__name", "character__project__name", "character__project__user__email")


@admin.register(CharacterMention)
class CharacterMentionAdmin(admin.ModelAdmin):
    list_display = ("character", "node", "mention_type", "project", "created_at")
    list_filter = ("mention_type", "created_at", "updated_at")
    search_fields = (
        "character__name",
        "node__title",
        "character__project__name",
        "character__project__user__email",
    )

    @admin.display(description=_("proyecto"))
    def project(self, obj):
        return obj.character.project
