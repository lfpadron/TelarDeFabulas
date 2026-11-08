import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError

from apps.manuscripts.audit import build_audit_report, render_markdown, render_summary


class Command(BaseCommand):
    help = "Inventario de integridad de solo lectura, sin texto ni datos personales."

    def add_arguments(self, parser):
        parser.add_argument("--format", choices=("summary", "json", "markdown"), default=None)
        parser.add_argument("--output", help="Archivo NUEVO .json, .md o .txt; no sobrescribe archivos existentes.")

    def handle(self, *args, **options):
        destination = None
        output_format = options["format"]
        if options["output"]:
            original = Path(options["output"]).expanduser()
            if original.is_symlink():
                raise CommandError("El destino no puede ser un enlace simbolico.")
            destination = original.resolve()
            formats = {".json": "json", ".md": "markdown", ".txt": "summary"}
            inferred = formats.get(destination.suffix.lower())
            if not inferred:
                raise CommandError("El informe debe usar extension .json, .md o .txt.")
            output_format = output_format or inferred
            if output_format != inferred:
                raise CommandError("El formato y la extension del informe deben coincidir.")
            if destination.exists():
                raise CommandError("El archivo de destino ya existe; no se sobrescribe.")
            for root in (settings.MEDIA_ROOT, settings.STATIC_ROOT):
                if root and destination.is_relative_to(Path(root).resolve()):
                    raise CommandError("El informe no puede escribirse en media ni staticfiles.")
        try:
            report = build_audit_report()
        except DatabaseError:
            raise CommandError("No se pudo leer la base de datos. No se genero un inventario ni se modificaron registros.") from None
        output_format = output_format or "summary"
        content = json.dumps(report, ensure_ascii=True, indent=2) if output_format == "json" else (
            render_markdown(report) if output_format == "markdown" else render_summary(report)
        )
        if destination:
            try:
                with destination.open("x", encoding="utf-8", newline="\n") as output:
                    output.write(content.rstrip() + "\n")
            except OSError:
                raise CommandError("No se pudo crear el informe. Use una ruta nueva y accesible fuera de media.") from None
            self.stdout.write("Informe creado. No se modificaron registros.")
        else:
            self.stdout.write(content)
