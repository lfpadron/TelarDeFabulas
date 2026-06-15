from django.urls import path

from . import views


app_name = "notes"

urlpatterns = [
    path("projects/<int:project_pk>/notes/", views.note_list, name="list"),
    path("projects/<int:project_pk>/notes/create/", views.note_create, name="create"),
    path("projects/<int:project_pk>/notes/<int:note_pk>/", views.note_detail, name="detail"),
    path("projects/<int:project_pk>/notes/<int:note_pk>/edit/", views.note_edit, name="edit"),
    path("projects/<int:project_pk>/notes/<int:note_pk>/delete/", views.note_delete, name="delete"),
]
