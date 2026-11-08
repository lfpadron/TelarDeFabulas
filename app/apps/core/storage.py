from pathlib import Path

from django.core.exceptions import SuspiciousFileOperation
from django.core.files.storage import FileSystemStorage


def validate_private_name(name):
    if not name or any(char in name for char in ("\\", ":", "\x00")) or any(
        part in ("", ".", "..") for part in name.split("/")
    ):
        raise SuspiciousFileOperation("Invalid private file reference.")


class PrivateMediaStorage(FileSystemStorage):
    def url(self, name):
        raise ValueError("Private files require an authorized view.")

    def path(self, name):
        validate_private_name(name)
        path = Path(super().path(name)).resolve()
        if not path.is_relative_to(Path(self.location).resolve()):
            raise SuspiciousFileOperation("Invalid private file reference.")
        return str(path)
