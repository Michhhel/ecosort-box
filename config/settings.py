"""
Configuration Django du projet EcoSort-BOX.

Application volontairement minimale : pas de base de données, pas d'admin,
pas de sessions. Le périmètre est une interface web + trois endpoints JSON.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# --- Sécurité -----------------------------------------------------------
# En production réelle, injecter une vraie clé via la variable d'environnement.
SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    "dev-only-ecosort-box-remplacer-en-production",
)

# DEBUG=1 pour le développement local, 0 (défaut) dans Docker.
DEBUG = os.environ.get("DEBUG", "0") == "1"

ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "*").split(",")

# Nécessaire pour que les POST fetch() passent la vérification CSRF
# quand on accède à l'app via localhost:8501 (Docker).
CSRF_TRUSTED_ORIGINS = os.environ.get(
    "CSRF_TRUSTED_ORIGINS",
    "http://localhost:8501,http://127.0.0.1:8501,http://localhost:8000,http://127.0.0.1:8000",
).split(",")

# --- Applications -------------------------------------------------------
INSTALLED_APPS = [
    "django.contrib.staticfiles",
    "webapp.apps.WebappConfig",  # forme explicite pour garantir ready() -> chargement du modèle
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",  # sert les fichiers statiques sans nginx
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# --- Base de données ----------------------------------------------------
# Aucun modèle persistant dans ce projet : pas de base de données.
DATABASES = {}

# --- Internationalisation ----------------------------------------------
LANGUAGE_CODE = "fr-fr"
TIME_ZONE = "Africa/Lagos"
USE_I18N = True
USE_TZ = True

# --- Fichiers statiques -------------------------------------------------
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

STORAGES = {
    "staticfiles": {
        # Version compressée (gzip/brotli) mais sans manifest : plus robuste
        # pour un projet étudiant (pas d'erreur si une référence manque).
        "BACKEND": "whitenoise.storage.CompressedStaticFilesStorage",
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Retours utilisateurs (feedback modèle) ------------------------------
# Dossier où sont archivés les signalements d'erreur de prédiction,
# consommé plus tard par le script de réentraînement du coéquipier IA.
FEEDBACK_DIR = BASE_DIR / "var" / "feedback"
