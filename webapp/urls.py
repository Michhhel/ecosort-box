"""Routes de l'app webapp — les chemins API suivent le contrat à la lettre."""
from django.urls import path

from . import views

urlpatterns = [
    path("", views.index, name="index"),
    path("api/search", views.api_search, name="api_search"),
    path("api/classify", views.api_classify, name="api_classify"),
    path("api/feedback", views.api_feedback, name="api_feedback"),
]
