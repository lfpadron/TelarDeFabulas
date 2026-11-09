from django.urls import path
from . import views

app_name = "references"
prefix = "projects/<int:project_pk>/references/"
urlpatterns = [
    path(prefix, views.reference_list, name="list"),
    path(prefix + "create/", views.create, name="create"),
    path(prefix + "associations/create/", views.attach, name="associate"),
    path(prefix + "associations/<int:association_pk>/delete/", views.detach, name="detach"),
    path(prefix + "<int:reference_pk>/", views.detail, name="detail"),
    path(prefix + "<int:reference_pk>/edit/", views.edit, name="edit"),
    path(prefix + "<int:reference_pk>/delete/", views.delete, name="delete"),
    path(prefix + "<int:reference_pk>/download/", views.download, name="download"),
    path(prefix + "<int:reference_pk>/attach/", views.attach, name="attach"),
]
