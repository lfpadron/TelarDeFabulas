from django.urls import path

from . import views, world_views


app_name = "exports"

urlpatterns = [
    path("projects/<int:project_pk>/exports/", views.export_list, name="list"),
    path("projects/<int:project_pk>/exports/create/", views.export_create, name="create"),
    path("projects/<int:project_pk>/exports/world/", world_views.create, name="world_create"),
    path("projects/<int:project_pk>/exports/preview/", views.export_preview, name="preview"),
    path("projects/<int:project_pk>/exports/<int:export_pk>/download/", views.export_download, name="download"),
    path("projects/<int:project_pk>/exports/<int:export_pk>/retry/", views.export_retry, name="retry"),
    path("projects/<int:project_pk>/exports/<int:export_pk>/delete/", views.export_delete, name="delete"),
    path("projects/<int:project_pk>/exports/<int:export_pk>/", views.export_detail, name="detail"),
]
