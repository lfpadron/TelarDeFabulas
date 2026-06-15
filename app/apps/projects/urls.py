from django.urls import path

from . import views


app_name = "projects"

urlpatterns = [
    path("projects/", views.project_list, name="list"),
    path("projects/create/", views.project_create, name="create"),
    path("projects/<int:pk>/", views.project_detail, name="detail"),
    path("projects/<int:pk>/edit/", views.project_edit, name="edit"),
    path("projects/<int:pk>/delete/", views.project_delete, name="delete"),
    path("projects/<int:pk>/restore/", views.project_restore, name="restore"),
]
