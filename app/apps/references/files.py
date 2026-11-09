from datetime import timedelta
import logging
from pathlib import Path
import re

from django.core.exceptions import SuspiciousFileOperation
from django.core.files.storage import default_storage
from django.db import transaction
from django.utils import timezone

from apps.core.storage import validate_private_name
from apps.projects.models import Project

logger = logging.getLogger(__name__)
FILE_PATTERN = re.compile(r"references/([1-9][0-9]*)/[0-9a-f]{32}\.(jpg|png|webp|pdf|txt|md|docx)\Z")


def reference_path(project_id, name):
    validate_private_name(name)
    match = FILE_PATTERN.fullmatch(name)
    if not match or int(match[1]) != project_id:
        raise SuspiciousFileOperation("Invalid reference scope")
    root = Path(default_storage.location).resolve()
    path = root.joinpath(*name.split("/"))
    if any(p.is_symlink() for p in (path, *path.parents) if p != root and root in p.parents):
        raise SuspiciousFileOperation("Reference symlinks are not supported")
    resolved = Path(default_storage.path(name))
    resolved.relative_to(root / "references" / str(project_id))
    return resolved


def enqueue_cleanup(project_id, name, size=0):
    from .models import ReferenceFileCleanup
    if not name:
        return
    record, _ = ReferenceFileCleanup.objects.get_or_create(name=name, defaults={"project_id": project_id, "file_size": size})
    transaction.on_commit(lambda: cleanup_file(record.pk), robust=True)


def cleanup_file(pk):
    from .models import ReferenceFileCleanup, ReferenceMaterial
    metadata = ReferenceFileCleanup.objects.filter(pk=pk).values("project_id").first()
    if metadata is None:
        return True
    with transaction.atomic():
        Project.objects.select_for_update().filter(pk=metadata["project_id"]).first()
        item = ReferenceFileCleanup.objects.select_for_update().filter(pk=pk).first()
        if item is None:
            return True
        try:
            if ReferenceMaterial.objects.filter(file=item.name).exists():
                raise SuspiciousFileOperation("Reference file still in use")
            reference_path(item.project_id, item.name).unlink(missing_ok=True)
        except (OSError, ValueError, SuspiciousFileOperation) as exc:
            item.attempts += 1
            item.last_error = type(exc).__name__
            item.next_attempt_at = timezone.now() + timedelta(seconds=min(86400, 60 * 2 ** min(item.attempts, 10)))
            item.save(update_fields=["attempts", "last_error", "next_attempt_at"])
            logger.warning("Reference file cleanup pending: record=%s error=%s", item.pk, item.last_error)
            return False
        item.delete()
        return True


def retry_cleanup(*, limit=100):
    from .models import ReferenceFileCleanup
    ids = list(ReferenceFileCleanup.objects.filter(next_attempt_at__lte=timezone.now()).order_by("next_attempt_at", "pk").values_list("pk", flat=True)[:limit])
    return sum(cleanup_file(pk) for pk in ids)


def reconcile_orphans(*, minimum_age_hours=24):
    from .models import ReferenceMaterial
    root = Path(default_storage.location).resolve()
    cutoff = (timezone.now() - timedelta(hours=max(24, minimum_age_hours))).timestamp()
    count = 0
    if (root / "references").is_symlink():
        raise SuspiciousFileOperation("Reference symlinks are not supported")
    for path in (root / "references").glob("*/*"):
        name = path.relative_to(root).as_posix()
        match = FILE_PATTERN.fullmatch(name)
        if not match or path.parent.is_symlink() or path.is_symlink() or not path.is_file() or path.stat().st_mtime >= cutoff:
            continue
        project_id = int(match[1])
        with transaction.atomic():
            Project.objects.select_for_update().filter(pk=project_id).first()
            if not ReferenceMaterial.objects.filter(file=name).exists():
                reference_path(project_id, name)
                enqueue_cleanup(project_id, name, path.stat().st_size)
                count += 1
    return count
