from django.urls import path

from . import views


app_name = "characters"

urlpatterns = [
    path("projects/<int:project_pk>/characters/", views.character_list, name="list"),
    path("projects/<int:project_pk>/characters/create/", views.character_create, name="create"),
    path("projects/<int:project_pk>/characters/<int:character_pk>/", views.character_detail, name="detail"),
    path("projects/<int:project_pk>/characters/<int:character_pk>/edit/", views.character_edit, name="edit"),
    path("projects/<int:project_pk>/characters/<int:character_pk>/delete/", views.character_delete, name="delete"),
]
