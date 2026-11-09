from django.core.exceptions import ValidationError
from django.db import models, router, transaction
from django.utils.translation import gettext_lazy as _

from apps.characters.models import Character
from apps.core.permissions import Action

from .models import CharacterOrganizationMembership, Organization
from .services import lock_project


def _project_id(membership, using):
    if membership.pk and not membership._state.adding:
        project_id = CharacterOrganizationMembership.objects.using(using).filter(pk=membership.pk).values_list("organization__project_id", flat=True).first()
    else:
        project_id = Organization.objects.using(using).filter(pk=membership.organization_id).values_list("project_id", flat=True).first()
    if project_id is None:
        raise ValidationError(_("La organización o afiliación ya no existe."))
    return project_id


def save_membership(membership, *args, user=None, **kwargs):
    using = kwargs.get("using") or router.db_for_write(CharacterOrganizationMembership, instance=membership)
    fields = kwargs.get("update_fields")
    if fields is not None and not fields:
        return
    with transaction.atomic(using=using):
        project = lock_project(_project_id(membership, using), using=using, user=user)
        if membership.pk:
            current = CharacterOrganizationMembership.objects.using(using).select_for_update().filter(pk=membership.pk).first()
            if current is not None and membership._state.adding:
                raise ValidationError(_("El identificador de afiliación ya existe."))
            if current is None and not membership._state.adding:
                raise ValidationError(_("La afiliación ya no existe."))
            if fields is not None and current is not None:
                for field in membership._meta.concrete_fields:
                    if field.name not in fields and field.attname not in fields:
                        setattr(membership, field.attname, getattr(current, field.attname))
        organization = Organization.objects.using(using).filter(pk=membership.organization_id, project=project).first()
        character = Character.objects.using(using).filter(pk=membership.character_id, project=project).first()
        if organization is None or character is None:
            raise ValidationError(_("El personaje y la organización deben pertenecer al mismo proyecto."))
        organization.project = project
        membership.organization = organization
        membership.character = character
        membership.full_clean()
        return models.Model.save(membership, *args, **kwargs)


def delete_membership(membership, *, user=None, using=None, keep_parents=False):
    using = using or membership._state.db or "default"
    with transaction.atomic(using=using):
        project = lock_project(_project_id(membership, using), using=using, user=user, action=Action.DELETE)
        current = CharacterOrganizationMembership.objects.using(using).select_for_update().get(
            pk=membership.pk, organization__project=project, character__project=project)
        result = models.Model.delete(current, using=using, keep_parents=keep_parents)
        membership.pk = None
        return result
