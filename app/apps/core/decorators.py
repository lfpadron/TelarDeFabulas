from contextlib import nullcontext
from functools import wraps

from django.db import transaction
from django.utils.cache import patch_cache_control, patch_vary_headers

from .permissions import Action, get_user_project


def project_access(action=Action.VIEW, *, key="project_pk"):
    """Recheck state under a project lock for narrative writes and restoration."""
    def decorate(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            writing = request.method == "POST" and action in (
                Action.CREATE, Action.EDIT, Action.DELETE, Action.RESTORE,
            )
            with transaction.atomic() if writing else nullcontext():
                request.project = get_user_project(
                    request.user, kwargs[key], action, for_update=writing,
                )
                response = view(request, *args, **kwargs)
            patch_cache_control(response, private=True, no_store=True, no_cache=True, max_age=0)
            patch_vary_headers(response, ("Cookie",))
            return response
        return wrapped
    return decorate
