"""Routage racine : tout est délégué à l'app webapp."""
from django.urls import include, path

urlpatterns = [
    path("", include("webapp.urls")),
]
