from django.urls import path

from . import views

app_name = "geography"
prefix = "projects/<int:project_pk>/geography/"
urlpatterns = [
    path(prefix, views.tree, name="tree"),
    path(prefix + "create/", views.create, name="create"),
    path(prefix + "<int:location_pk>/", views.detail, name="detail"),
    path(prefix + "<int:location_pk>/edit/", views.edit, name="edit"),
    path(prefix + "<int:location_pk>/delete/", views.delete, name="delete"),
    path(prefix + "<int:location_pk>/move/", views.move, name="move"),
    path(prefix + "<int:location_pk>/move-up/", views.reorder, {"direction": "up"}, name="move_up"),
    path(prefix + "<int:location_pk>/move-down/", views.reorder, {"direction": "down"}, name="move_down"),
]
