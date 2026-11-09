from django.urls import path

from . import relationship_views, views


app_name = "characters"

urlpatterns = [
    path("projects/<int:project_pk>/characters/<int:character_pk>/relationships/", relationship_views.relationship_list, name="relationship_list"),
    path("projects/<int:project_pk>/characters/<int:character_pk>/relationships/create/", relationship_views.create, name="relationship_create"),
    path("projects/<int:project_pk>/relationships/<int:relationship_pk>/", relationship_views.detail, name="relationship_detail"),
    path("projects/<int:project_pk>/relationships/<int:relationship_pk>/edit/", relationship_views.edit, name="relationship_edit"),
    path("projects/<int:project_pk>/relationships/<int:relationship_pk>/delete/", relationship_views.delete, name="relationship_delete"),
    path("projects/<int:project_pk>/characters/", views.character_list, name="list"),
    path("projects/<int:project_pk>/characters/create/", views.character_create, name="create"),
    path("projects/<int:project_pk>/characters/<int:character_pk>/", views.character_detail, name="detail"),
    path("projects/<int:project_pk>/characters/<int:character_pk>/image/", views.character_image, name="image"),
    path("projects/<int:project_pk>/characters/<int:character_pk>/edit/", views.character_edit, name="edit"),
    path("projects/<int:project_pk>/characters/<int:character_pk>/delete/", views.character_delete, name="delete"),
    path("projects/<int:project_pk>/mentions/create/", views.mention_create, name="mention_create"),
    path("projects/<int:project_pk>/mentions/<int:mention_pk>/edit/", views.mention_edit, name="mention_edit"),
    path("projects/<int:project_pk>/mentions/<int:mention_pk>/delete/", views.mention_delete, name="mention_delete"),
]
