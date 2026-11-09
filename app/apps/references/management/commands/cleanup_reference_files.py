from django.core.management.base import BaseCommand

from apps.references.files import reconcile_orphans, retry_cleanup


class Command(BaseCommand):
    help = "Retry queued reference file cleanup; optionally reconcile UUID orphans older than 24 hours."

    def add_arguments(self, parser):
        parser.add_argument("--orphans", action="store_true")

    def handle(self, *args, **options):
        if options["orphans"]:
            self.stdout.write(f"Orphans queued: {reconcile_orphans()}")
        self.stdout.write(f"Queued files removed: {retry_cleanup()}")
