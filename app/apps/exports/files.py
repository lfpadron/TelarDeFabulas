"""Private export files and download leases shared with the cleaner."""
import os
from pathlib import Path

import psycopg
from django.core.exceptions import SuspiciousFileOperation
from django.db import connection

from apps.core.storage import validate_private_name


EXTENSIONS = {"MARKDOWN": "md", "HTML": "html", "DOCX": "docx", "PDF": "pdf", "EPUB": "epub"}


def file_lock_key(job_id):
    return f"telar-export-file:{job_id}"


def try_cleanup_lock(job_id):
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_try_advisory_xact_lock(hashtextextended(%s, 0))", [file_lock_key(job_id)])
        return cursor.fetchone()[0]


def acquire_download_lock(job_id):
    params = connection.get_connection_params()
    params["autocommit"] = True
    lease = psycopg.connect(**params)
    try:
        lease.execute("SELECT pg_advisory_lock_shared(hashtextextended(%s, 0))", [file_lock_key(job_id)])
    except BaseException:
        lease.close()
        raise
    return lease


class DownloadFile:
    def __init__(self, stream, lease):
        self.stream = stream
        self.lease = lease

    def __getattr__(self, name):
        return getattr(self.stream, name)

    def close(self):
        try:
            self.stream.close()
        finally:
            self.lease.close()


def private_path(job, name):
    validate_private_name(name)
    prefix = f"exports/{job.user_id}/{job.project_id}/"
    if not name.startswith(prefix):
        raise SuspiciousFileOperation("Invalid export file scope.")
    storage = job.file.storage
    root = Path(storage.location).resolve()
    candidate = root.joinpath(*name.split("/"))
    # Reject even internal symlinks: a different owner's file is still private.
    if any(path.is_symlink() for path in (candidate, *candidate.parents) if path != root and root in path.parents):
        raise SuspiciousFileOperation("Export symlinks are not supported.")
    result = Path(storage.path(name))
    result.resolve().relative_to(root / prefix)
    return result


def attempt_names(job, token):
    base = f"exports/{job.user_id}/{job.project_id}/{job.pk}/{token}"
    return base + ".part", base + "." + EXTENSIONS.get(job.format, "bin")


def remove_artifacts(job):
    from .models import ExportJob

    names = {job.file.name} if job.file else set()
    for token in job.attempts.values_list("token", flat=True):
        names.update(attempt_names(job, token))
    # Validate the complete set before touching any files.
    paths = []
    for name in names:
        if ExportJob.objects.exclude(pk=job.pk).filter(file=name).exists():
            raise SuspiciousFileOperation("Export file has another owner.")
        paths.append(private_path(job, name))
    for path in paths:
        path.unlink(missing_ok=True)


def publish_bytes(job, token, content):
    """Called only while holding the job row lock and a valid execution token."""
    temporary, final = attempt_names(job, token)
    temp_path, final_path = private_path(job, temporary), private_path(job, final)
    temp_path.parent.mkdir(parents=True, exist_ok=True)
    with temp_path.open("xb") as output:
        output.write(content)
        output.flush()
        os.fsync(output.fileno())
    os.replace(temp_path, final_path)
    return final
