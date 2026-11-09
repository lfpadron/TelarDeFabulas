from django.db.models.signals import post_delete
from django.dispatch import receiver

from .files import enqueue_cleanup
from .models import ReferenceMaterial


@receiver(post_delete, sender=ReferenceMaterial)
def reference_deleted(sender, instance, **kwargs):
    if instance.file:
        enqueue_cleanup(instance.project_id, instance.file.name, instance.file_size)
