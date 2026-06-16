from django.urls import path

from . import views


app_name = "styles"

urlpatterns = [
    path("styles/", views.style_list, name="list"),
    path("styles/create/", views.style_create, name="create"),
    path("styles/<int:style_pk>/", views.style_detail, name="detail"),
    path("styles/<int:style_pk>/edit/", views.style_edit, name="edit"),
    path("styles/<int:style_pk>/duplicate/", views.style_duplicate, name="duplicate"),
    path("styles/<int:style_pk>/delete/", views.style_delete, name="delete"),
]
