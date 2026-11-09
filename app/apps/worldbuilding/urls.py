from django.urls import path

from . import views

app_name = "worldbuilding"
prefix = "projects/<int:project_pk>/worldbuilding/"

urlpatterns = [
    path(prefix, views.entry_list, name="list"),
    path(prefix + "create/", views.create, name="create"),
    path(prefix + "<int:entry_pk>/", views.detail, name="detail"),
    path(prefix + "<int:entry_pk>/edit/", views.edit, name="edit"),
    path(prefix + "<int:entry_pk>/delete/", views.delete, name="delete"),
    path(prefix + "<int:entry_pk>/change-category/", views.change_category, name="change_category"),
    path(prefix + "<int:entry_pk>/move-up/", views.reorder, {"direction": "up"}, name="move_up"),
    path(prefix + "<int:entry_pk>/move-down/", views.reorder, {"direction": "down"}, name="move_down"),
]
