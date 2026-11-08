from django.urls import path

from . import views, version_views


app_name = "manuscripts"

urlpatterns = [
    path("projects/<int:project_pk>/manuscript/<int:node_pk>/versions/", version_views.version_history, name="version_history"),
    path("projects/<int:project_pk>/manuscript/<int:node_pk>/versions/create/", version_views.version_create, name="version_create"),
    path("projects/<int:project_pk>/manuscript/<int:node_pk>/versions/<int:version_pk>/", version_views.version_detail, name="version_detail"),
    path("projects/<int:project_pk>/manuscript/<int:node_pk>/versions/<int:version_pk>/edit/", version_views.version_edit, name="version_edit"),
    path("projects/<int:project_pk>/manuscript/<int:node_pk>/versions/<int:version_pk>/review/", version_views.version_review, name="version_review"),
    path("projects/<int:project_pk>/manuscript/<int:node_pk>/versions/<int:version_pk>/finalize/", version_views.version_finalize, name="version_finalize"),
    path("projects/<int:project_pk>/manuscript/<int:node_pk>/versions/<int:version_pk>/restore/", version_views.version_restore, name="version_restore"),
    path("projects/<int:project_pk>/manuscript/", views.manuscript_tree, name="tree"),
    path("projects/<int:project_pk>/manuscript/create/", views.node_create, name="create"),
    path("projects/<int:project_pk>/manuscript/<int:node_pk>/", views.node_detail, name="detail"),
    path("projects/<int:project_pk>/manuscript/<int:node_pk>/edit/", views.node_edit, name="edit"),
    path("projects/<int:project_pk>/manuscript/<int:node_pk>/move/", views.node_move, name="move"),
    path("projects/<int:project_pk>/manuscript/<int:node_pk>/move-up/", views.node_move_up, name="move_up"),
    path("projects/<int:project_pk>/manuscript/<int:node_pk>/move-down/", views.node_move_down, name="move_down"),
    path("projects/<int:project_pk>/manuscript/<int:node_pk>/delete/", views.node_delete, name="delete"),
]
