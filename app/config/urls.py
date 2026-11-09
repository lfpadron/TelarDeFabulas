from django.contrib import admin
from django.shortcuts import render
from django.urls import include, path


def home(request):
    return render(request, "home.html")


urlpatterns = [
    path("", home, name="home"),
    path("", include("apps.accounts.urls")),
    path("", include("apps.projects.urls")),
    path("", include("apps.manuscripts.urls")),
    path("", include("apps.characters.urls")),
    path("", include("apps.geography.urls")),
    path("", include("apps.organizations.urls")),
    path("", include("apps.worldbuilding.urls")),
    path("", include("apps.references.urls")),
    path("", include("apps.notes.urls")),
    path("", include("apps.styles.urls")),
    path("", include("apps.exports.urls")),
    path("admin/", admin.site.urls),
]
