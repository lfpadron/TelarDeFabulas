from django.urls import path

from . import views


app_name = "manuscripts"

urlpatterns = [
    path("projects/<int:project_pk>/manuscript/", views.manuscript_tree, name="tree"),
    path("projects/<int:project_pk>/manuscript/create/", views.node_create, name="create"),
    path("projects/<int:project_pk>/manuscript/<int:node_pk>/", views.node_detail, name="detail"),
    path("projects/<int:project_pk>/manuscript/<int:node_pk>/edit/", views.node_edit, name="edit"),
    path("projects/<int:project_pk>/manuscript/<int:node_pk>/delete/", views.node_delete, name="delete"),
]
