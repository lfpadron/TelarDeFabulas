from celery import shared_task

from .files import retry_cleanup


@shared_task(name="apps.references.cleanup_files", ignore_result=True)
def cleanup_files():
    retry_cleanup()
