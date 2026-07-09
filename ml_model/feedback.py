"""
Retours utilisateurs sur les prédictions — collecte filtrée pour améliorer
le modèle au fil des utilisations.

POURQUOI PAS DU "VRAI" APPRENTISSAGE EN LIGNE ?
Réentraîner un CNN à chaud, clic par clic, est dangereux : oubli catastrophique,
empoisonnement par des utilisateurs malveillants, dérive silencieuse. Le schéma
standard (et celui retenu ici) est un apprentissage "human-in-the-loop" :

    1. COLLECTE  : l'interface permet de confirmer ou contester chaque verdict ;
    2. FILTRAGE  : une correction n'est marquée "acceptee" que si le modèle
                   lui-même hésitait déjà vers la poubelle proposée (seuils
                   ci-dessous) — c'est le garde-fou anti-vandalisme demandé ;
    3. ARCHIVAGE : image + métadonnées sont stockées dans var/feedback/
                   (feedback.jsonl + images/) ;
    4. RÉENTRAÎNEMENT PÉRIODIQUE : un script du coéquipier IA (à créer côté
                   ml_model, ex. reentrainer.py) consomme les entrées
                   "acceptee" pour affiner le modèle (fine-tuning), régénère
                   modele_eco_sort.h5, et l'app le recharge au redéploiement.

Le module est volontairement indépendant de Django : le coéquipier IA peut
importer et tester `evaluer_correction` et lire var/feedback/ sans lancer le site.

RÈGLE D'ACCEPTATION D'UNE CORRECTION (seuils proposés, à discuter en équipe) :
  - REJET si le modèle était quasi certain : confiance >= 0.95. Une prédiction
    à 95 %+ n'est jamais contredite par un seul clic utilisateur ; le
    signalement est archivé "rejetee" pour vérification humaine.
  - ACCEPTATION si la poubelle proposée par l'utilisateur avait une
    probabilité >= 0.15 dans la sortie du modèle. Justification : avec
    5 classes, le hasard uniforme vaut 0.20 ; à 0.15 le modèle hésitait
    donc réellement vers cette poubelle — la correction est plausible.
  - REJET sinon (probabilité négligeable) : archivé "rejetee".

Tout est archivé, y compris les rejets : rien n'est perdu, un humain peut
requalifier plus tard, mais seules les entrées "acceptee" nourrissent le
réentraînement automatique.
"""
from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

# --- Seuils du garde-fou (à valider en équipe) ----------------------------
SEUIL_PROBA_MIN = 0.15        # proba minimale de la poubelle proposée par l'utilisateur
SEUIL_CONFIANCE_VERROU = 0.95  # au-delà, la prédiction est verrouillée

# --- Stockage --------------------------------------------------------------
# <racine du projet>/var/feedback/{feedback.jsonl, images/}
DOSSIER_FEEDBACK = Path(__file__).resolve().parent.parent / "var" / "feedback"
FICHIER_JOURNAL = DOSSIER_FEEDBACK / "feedback.jsonl"
DOSSIER_IMAGES = DOSSIER_FEEDBACK / "images"

_verrou_ecriture = threading.Lock()


def evaluer_correction(prediction: dict, couleur_correcte: str) -> tuple[bool, str]:
    """
    Décide si la correction proposée par l'utilisateur est plausible.

    `prediction` est la sortie complète de predire_categorie() (avec
    "confiance" et "probabilites"). Renvoie (acceptee, raison).
    """
    confiance = float(prediction.get("confiance") or 0.0)
    probabilites = prediction.get("probabilites") or {}
    proba_correction = float(probabilites.get(couleur_correcte, 0.0))

    if confiance >= SEUIL_CONFIANCE_VERROU:
        return False, (
            f"prédiction quasi certaine (confiance {confiance:.2f} >= "
            f"{SEUIL_CONFIANCE_VERROU:.2f}) : correction archivée pour revue humaine"
        )
    if proba_correction >= SEUIL_PROBA_MIN:
        return True, (
            f"le modèle hésitait vers cette poubelle "
            f"(p = {proba_correction:.2f} >= {SEUIL_PROBA_MIN:.2f})"
        )
    return False, (
        f"probabilité jugée négligeable pour cette poubelle "
        f"(p = {proba_correction:.2f} < {SEUIL_PROBA_MIN:.2f}) : archivée pour revue humaine"
    )


def _extension_image(image_bytes: bytes) -> str:
    """Devine l'extension du fichier image à partir des octets (magic bytes)."""
    if image_bytes.startswith(b"\x89PNG"):
        return ".png"
    if image_bytes.startswith(b"\xff\xd8"):
        return ".jpg"
    if image_bytes.startswith(b"RIFF") and image_bytes[8:12] == b"WEBP":
        return ".webp"
    if image_bytes.startswith(b"GIF8"):
        return ".gif"
    debut = image_bytes[:512].lstrip().lower()
    if debut.startswith(b"<svg") or debut.startswith(b"<?xml"):
        return ".svg"
    return ".bin"


def enregistrer_feedback(
    image_bytes: bytes,
    prediction: dict,
    statut: str,
    couleur_correcte: str | None,
    raison: str,
) -> dict:
    """
    Archive un retour utilisateur : sauvegarde l'image dans images/ et ajoute
    une ligne JSON au journal feedback.jsonl. Renvoie l'enregistrement.

    `statut` ∈ {"confirmee", "acceptee", "rejetee"} :
      - confirmee : l'utilisateur valide la prédiction (exemple positif) ;
      - acceptee  : correction plausible -> utilisable pour le réentraînement ;
      - rejetee   : correction non plausible -> revue humaine uniquement.
    """
    DOSSIER_IMAGES.mkdir(parents=True, exist_ok=True)

    identifiant = uuid.uuid4().hex[:12]
    nom_image = f"{identifiant}{_extension_image(image_bytes)}"
    (DOSSIER_IMAGES / nom_image).write_bytes(image_bytes)

    enregistrement = {
        "id": identifiant,
        "horodatage": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "statut": statut,
        "couleur_predite": prediction.get("couleur"),
        "confiance": prediction.get("confiance"),
        "probabilites": prediction.get("probabilites"),
        "couleur_correcte": couleur_correcte,
        "raison": raison,
        "image": f"images/{nom_image}",
    }

    ligne = json.dumps(enregistrement, ensure_ascii=False)
    with _verrou_ecriture:
        with open(FICHIER_JOURNAL, "a", encoding="utf-8") as journal:
            journal.write(ligne + "\n")

    return enregistrement
