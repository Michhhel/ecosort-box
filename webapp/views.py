"""
Vues de l'interface EcoSort-BOX.

Quatre vues, conformément au périmètre :
  - index        : sert la page unique (interface façon chat) ;
  - api_search   : POST /api/search   -> délègue au module `scraper` ;
  - api_classify : POST /api/classify -> télécharge/reçoit l'image puis
                   délègue au module `ml_model` ;
  - api_feedback : POST /api/feedback -> confirme ou conteste un verdict
                   (garde-fou dans ml_model/feedback.py).

Vues Django classiques avec JsonResponse — pas de Django REST Framework.
Toutes les erreurs renvoient {"erreur": "..."} avec un code HTTP adapté ;
le front affiche ce message tel quel dans le fil de discussion.
"""
from __future__ import annotations

import inspect
import json
import logging

from django.http import HttpRequest, JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST

from ml_model import classifier, feedback
from scraper import jumia_scraper

from . import predictions
from .utils import ImageIntrouvable, telecharger_image

logger = logging.getLogger(__name__)


def index(request: HttpRequest):
    """Page unique de l'application (fil de discussion + barre de recherche)."""
    return render(request, "webapp/index.html")


def _corps_json(request: HttpRequest) -> dict:
    """Décode le corps JSON d'une requête ; {} si invalide."""
    try:
        return json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}


@require_POST
def api_search(request: HttpRequest) -> JsonResponse:
    """
    POST /api/search
    Entrée : {"mot_cle": str, "page": int (optionnel, défaut 1)}
    Sortie : {"resultats": [{"titre", "image_url", "produit_url"}, ...]}
             (liste vide si aucun produit trouvé — le front gère ce cas)

    Le paramètre "page" alimente le bouton « Voir d'autres produits ». Il
    n'est transmis au scraper QUE si sa signature l'accepte : compatibilité
    totale avec le contrat d'origine du coéquipier scraping.
    """
    donnees = _corps_json(request)
    mot_cle = str(donnees.get("mot_cle", "")).strip()

    try:
        page = max(1, int(donnees.get("page", 1)))
    except (TypeError, ValueError):
        page = 1

    if not mot_cle:
        return JsonResponse(
            {"erreur": "Indique un mot-clé à rechercher (ex. « bouteille d'eau »)."},
            status=400,
        )
    if len(mot_cle) > 100:
        return JsonResponse({"erreur": "Le mot-clé est trop long (100 caractères max)."}, status=400)

    try:
        parametres = inspect.signature(jumia_scraper.rechercher_produits).parameters
        if "page" in parametres:
            resultats = jumia_scraper.rechercher_produits(mot_cle, page=page)
        else:  # contrat d'origine : pas de pagination
            resultats = jumia_scraper.rechercher_produits(mot_cle)
    except Exception:
        logger.exception("Échec du scraping pour le mot-clé %r (page %s)", mot_cle, page)
        return JsonResponse(
            {"erreur": "La recherche sur Jumia est indisponible pour le moment. Réessaie dans un instant."},
            status=502,
        )

    return JsonResponse({"resultats": resultats, "page": page})


@require_POST
def api_classify(request: HttpRequest) -> JsonResponse:
    """
    POST /api/classify
    Entrée, deux modes :
      - JSON {"image_url": str}  : produit sélectionné dans le carousel ;
      - multipart "image_file"   : photo envoyée depuis la galerie / les
        fichiers de l'utilisateur (désormais actif côté interface).
    Sortie : {"categorie", "couleur", "confiance", "detail", "prediction_id"}

    "prediction_id" permet de rattacher un éventuel retour utilisateur
    (/api/feedback) à cette prédiction. La distribution complète des
    probabilités reste côté serveur (registre en mémoire), le client n'en a
    pas besoin.
    """
    image_bytes: bytes | None = None

    # Mode photo : fichier uploadé en multipart.
    fichier = request.FILES.get("image_file")
    if fichier is not None:
        if fichier.size > 8 * 1024 * 1024:
            return JsonResponse({"erreur": "Image trop lourde (8 Mo max)."}, status=400)
        if fichier.size == 0:
            return JsonResponse({"erreur": "Le fichier envoyé est vide."}, status=400)
        image_bytes = fichier.read()
    else:
        # Mode nominal : URL de l'image sélectionnée dans le carousel.
        donnees = _corps_json(request)
        image_url = str(donnees.get("image_url", "")).strip()
        if not image_url:
            return JsonResponse(
                {"erreur": "Fournis « image_url » (JSON) ou « image_file » (multipart)."},
                status=400,
            )
        try:
            # C'est la vue qui télécharge l'image avant de la passer au modèle.
            image_bytes = telecharger_image(image_url)
        except ImageIntrouvable:
            logger.warning("Image introuvable : %s", image_url)
            return JsonResponse(
                {"erreur": "Impossible de récupérer l'image de ce produit. Choisis-en un autre."},
                status=502,
            )

    try:
        resultat = classifier.predire_categorie(image_bytes)
    except Exception:
        logger.exception("Échec de la classification")
        return JsonResponse(
            {"erreur": "Le modèle de classification a rencontré un problème. Réessaie avec un autre produit."},
            status=500,
        )

    # Mémorise la prédiction complète pour un éventuel retour utilisateur.
    prediction_id = predictions.enregistrer(image_bytes, resultat)

    reponse = {cle: valeur for cle, valeur in resultat.items() if cle != "probabilites"}
    reponse["prediction_id"] = prediction_id
    return JsonResponse(reponse)


@require_POST
def api_feedback(request: HttpRequest) -> JsonResponse:
    """
    POST /api/feedback
    Entrée : {"prediction_id": str,
              "correcte": bool,
              "couleur_correcte": str (requis si correcte est false)}
    Sortie : {"statut": "confirmee" | "acceptee" | "rejetee", "message": str}

    Garde-fou anti-vandalisme : la décision d'accepter ou non une correction
    est déléguée à ml_model.feedback.evaluer_correction (seuils documentés
    là-bas). Tout est archivé dans var/feedback/ pour le réentraînement
    périodique du modèle par le coéquipier IA.
    """
    donnees = _corps_json(request)
    prediction_id = str(donnees.get("prediction_id", "")).strip()

    entree = predictions.recuperer(prediction_id)
    if entree is None:
        return JsonResponse(
            {"erreur": "Cette prédiction a expiré. Relance une analyse avant de donner ton avis."},
            status=404,
        )

    prediction = entree["prediction"]
    image_bytes = entree["image_bytes"]

    # --- Cas 1 : l'utilisateur confirme la prédiction (exemple positif) ----
    if bool(donnees.get("correcte", False)):
        try:
            feedback.enregistrer_feedback(
                image_bytes, prediction,
                statut="confirmee", couleur_correcte=None,
                raison="confirmation utilisateur",
            )
        except OSError:
            logger.exception("Échec de l'archivage d'une confirmation")
            return JsonResponse({"erreur": "Impossible d'enregistrer ton retour pour le moment."}, status=500)
        return JsonResponse({
            "statut": "confirmee",
            "message": "Merci pour la confirmation ! Elle renforcera le modèle sur ce type de produit.",
        })

    # --- Cas 2 : l'utilisateur conteste et propose une autre poubelle ------
    couleur_correcte = str(donnees.get("couleur_correcte", "")).strip().lower()
    if couleur_correcte not in classifier.CATEGORIES:
        return JsonResponse(
            {"erreur": "Indique la bonne poubelle parmi : " + ", ".join(classifier.CATEGORIES) + "."},
            status=400,
        )
    if couleur_correcte == prediction.get("couleur"):
        return JsonResponse(
            {"erreur": "C'est déjà la poubelle prédite par le modèle — rien à corriger !"},
            status=400,
        )

    acceptee, raison = feedback.evaluer_correction(prediction, couleur_correcte)
    try:
        feedback.enregistrer_feedback(
            image_bytes, prediction,
            statut="acceptee" if acceptee else "rejetee",
            couleur_correcte=couleur_correcte,
            raison=raison,
        )
    except OSError:
        logger.exception("Échec de l'archivage d'un signalement")
        return JsonResponse({"erreur": "Impossible d'enregistrer ton retour pour le moment."}, status=500)

    if acceptee:
        message = (
            "Ta remarque a bien été prise en compte : le modèle sera optimisé "
            "dans ce sens lors de son prochain réentraînement. Merci pour ton aide !"
        )
    else:
        message = (
            "Merci pour ta remarque ! Le modèle est toutefois très confiant sur "
            "cette prédiction : ton signalement est archivé et sera vérifié par "
            "l'équipe avant toute correction du modèle."
        )
    return JsonResponse({"statut": "acceptee" if acceptee else "rejetee", "message": message})
