from django.urls import path

from . import views

app_name = "organizations"
prefix = "projects/<int:project_pk>/organizations/"
memberships = "projects/<int:project_pk>/memberships/"
urlpatterns = [
    path(prefix, views.tree, name="tree"),
    path(prefix + "create/", views.create, name="create"),
    path(prefix + "<int:organization_pk>/", views.detail, name="detail"),
    path(prefix + "<int:organization_pk>/edit/", views.edit, name="edit"),
    path(prefix + "<int:organization_pk>/delete/", views.delete, name="delete"),
    path(prefix + "<int:organization_pk>/move/", views.move, name="move"),
    path(prefix + "<int:organization_pk>/move-up/", views.reorder, {"direction": "up"}, name="move_up"),
    path(prefix + "<int:organization_pk>/move-down/", views.reorder, {"direction": "down"}, name="move_down"),
    path(memberships + "create/", views.membership_create, name="membership_create"),
    path(memberships + "<int:membership_pk>/edit/", views.membership_edit, name="membership_edit"),
    path(memberships + "<int:membership_pk>/delete/", views.membership_delete, name="membership_delete"),
]
