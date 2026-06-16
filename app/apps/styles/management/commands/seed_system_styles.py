from decimal import Decimal

from django.core.management.base import BaseCommand

from apps.styles.models import StyleTemplate


SYSTEM_STYLES = [
    {
        "name": "Sobrio",
        "description": "Estilo claro y funcional para exportaciones sobrias.",
        "font_category": StyleTemplate.FontCategory.SANS_SERIF,
        "font_heading": "Inter",
        "font_body": "Inter",
        "text_alignment": StyleTemplate.TextAlignment.LEFT,
        "scene_separator": "***",
    },
    {
        "name": "Creativo",
        "description": "Estilo moderno para manuscritos con tono expresivo.",
        "font_category": StyleTemplate.FontCategory.SANS_SERIF,
        "font_heading": "Montserrat",
        "font_body": "Lato",
        "text_alignment": StyleTemplate.TextAlignment.JUSTIFY,
        "scene_separator": "✦ ✦ ✦",
    },
    {
        "name": "Elegante",
        "description": "Estilo literario con composición clásica.",
        "font_category": StyleTemplate.FontCategory.SERIF,
        "font_heading": "Libre Baskerville",
        "font_body": "Merriweather",
        "text_alignment": StyleTemplate.TextAlignment.JUSTIFY,
        "scene_separator": "❦",
    },
    {
        "name": "Medio loco",
        "description": "Estilo más ornamental para textos con una voz peculiar.",
        "font_category": StyleTemplate.FontCategory.SERIF,
        "font_heading": "Cinzel",
        "font_body": "EB Garamond",
        "text_alignment": StyleTemplate.TextAlignment.JUSTIFY,
        "scene_separator": "☽ ✦ ☾",
    },
]


DEFAULT_LAYOUT = {
    "heading_size": Decimal("18.00"),
    "body_size": Decimal("12.00"),
    "line_spacing": Decimal("1.50"),
    "paragraph_spacing": Decimal("8.00"),
    "margin_top": Decimal("25.00"),
    "margin_bottom": Decimal("25.00"),
    "margin_left": Decimal("25.00"),
    "margin_right": Decimal("25.00"),
    "first_line_indent": Decimal("0.00"),
    "include_page_numbers": True,
    "include_table_of_contents": False,
    "config_json": {},
}


class Command(BaseCommand):
    help = "Crea o actualiza los estilos de sistema iniciales."

    def handle(self, *args, **options):
        created_count = 0
        updated_count = 0
        for style_data in SYSTEM_STYLES:
            defaults = {
                **DEFAULT_LAYOUT,
                **style_data,
                "user": None,
                "is_system": True,
            }
            style, created = StyleTemplate.objects.update_or_create(
                name=style_data["name"],
                is_system=True,
                defaults=defaults,
            )
            if created:
                created_count += 1
            else:
                updated_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Estilos de sistema listos. Creados: {created_count}. Actualizados: {updated_count}."
            )
        )
