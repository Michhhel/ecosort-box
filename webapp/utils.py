"""Utilitaires de la partie web."""
from __future__ import annotations

from urllib.parse import urlparse

import requests
from django.conf import settings
from django.contrib.staticfiles import finders


class ImageIntrouvable(Exception):
    """L'image du produit n'a pas pu être récupérée."""


def telecharger_image(image_url: str, timeout: float = 10.0) -> bytes:
    """
    Récupère les octets d'une image à partir de son URL.

    Deux cas gérés :
      - URL http(s) classique (vraie image Jumia) : téléchargement `requests`.
        C'est bien la vue Django qui télécharge l'image avant de la passer au
        modèle (le module IA ne fait pas de réseau).
      - Chemin statique local ("/static/...") : images factices du scraper
        mock, lues directement sur disque -> la démo fonctionne hors-ligne.
    """
    image_url = (image_url or "").strip()
    if not image_url:
        raise ImageIntrouvable("URL d'image vide.")

    static_url = settings.STATIC_URL if settings.STATIC_URL.startswith("/") else "/" + settings.STATIC_URL
    if image_url.startswith(static_url):
        chemin_relatif = image_url[len(static_url):]
        chemin = finders.find(chemin_relatif)
        if chemin is None:
            raise ImageIntrouvable(f"Fichier statique introuvable : {chemin_relatif}")
        with open(chemin, "rb") as f:
            return f.read()

    schema = urlparse(image_url).scheme
    if schema not in ("http", "https"):
        raise ImageIntrouvable(f"URL d'image invalide : {image_url!r}")

    try:
        reponse = requests.get(image_url, timeout=timeout)
        reponse.raise_for_status()
    except requests.RequestException as exc:
        raise ImageIntrouvable(f"Téléchargement impossible ({exc}).") from exc

    return reponse.content
