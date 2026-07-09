# -*- coding: utf-8 -*-
"""
Module de classification deep learning — VRAI modèle (remplace le mock).

Auteur : CISSE Aly (branche ml)

Modèle : MobileNetV2 en Transfer Learning (2 phases), entraîné sur 7 classes :
les 6 matières du dataset Kaggle "Garbage Classification" + une classe
"electronic" construite à partir du dataset E-Waste (voir ml_model/entrainement/
pour les scripts reproductibles et le détail des résultats — 87,7 % sur le
jeu de test, classe electronic à 100 %).

Contrat public (défini avec le coéquipier web, inchangé par rapport au mock) :

    charger_modele() -> None        # idempotent, appelée UNE fois au démarrage
    predire_categorie(image_bytes: bytes) -> dict
        {
            "categorie": "Poubelle JAUNE",
            "couleur": "jaune",              # slug parmi les 5 catégories
            "detail": "...",
            "confiance": 0.93,               # probabilité de la catégorie prédite
            "probabilites": {slug: float},   # distribution sur les 5 catégories
        }

Note sur "probabilites" : le modèle prédit 7 matières ; la distribution est
AGRÉGÉE par catégorie de tri (ex. p(jaune) = p(plastic)+p(metal)+p(cardboard)).
C'est cette distribution qu'utilise le garde-fou de ml_model/feedback.py.
"""
from __future__ import annotations

import io
import json
from pathlib import Path

import numpy as np
from PIL import Image, UnidentifiedImageError

# --- Référentiel officiel des 5 catégories (cf. projet_ISE2.md) ----------
# classe prédite par le modèle -> slug de catégorie de tri
MATIERE_VERS_CATEGORIE = {
    "plastic": "jaune",
    "metal": "jaune",
    "cardboard": "jaune",
    "glass": "verte",
    "paper": "bleue",
    "electronic": "grise",   # classe dédiée D3E (dataset E-Waste)
    "trash": "marron",
}

CATEGORIES = {
    "jaune": {
        "categorie": "Poubelle JAUNE",
        "couleur": "jaune",
        "detail": "Emballages légers : plastique, métal, carton",
    },
    "verte": {
        "categorie": "Poubelle VERTE",
        "couleur": "verte",
        "detail": "Verre d'emballage : bouteilles, pots, bocaux",
    },
    "bleue": {
        "categorie": "Poubelle BLEUE",
        "couleur": "bleue",
        "detail": "Papiers graphiques propres : journaux, cahiers",
    },
    "grise": {
        "categorie": "Bac Électronique (D3E)",
        "couleur": "grise",
        "detail": "Piles, batteries, tout ce qui se branche",
    },
    "marron": {
        "categorie": "Poubelle MARRON / NOIRE",
        "couleur": "marron",
        "detail": "Déchets résiduels non recyclables",
    },
}

_TAILLE_IMAGE = (224, 224)   # taille d'entrée du modèle (MobileNetV2)
_DOSSIER = Path(__file__).resolve().parent

# Le modèle Keras et l'ordre de ses 7 classes, chargés une seule fois.
_model = None
_classes = None


def charger_modele() -> None:
    """
    Charge le modèle Keras en mémoire. Idempotent : les appels suivants
    sont no-op. Appelée UNE SEULE FOIS au démarrage du serveur
    (webapp.apps.WebappConfig.ready()), jamais à chaque requête.
    """
    global _model, _classes
    if _model is not None:
        return
    # Import local : TensorFlow est lourd, on ne le charge que si nécessaire
    from tensorflow import keras

    _model = keras.models.load_model(_DOSSIER / "modele_eco_sort.h5")
    with open(_DOSSIER / "classes.json", encoding="utf-8") as f:
        _classes = json.load(f)
    print("[ml_model] Modèle Keras chargé en mémoire (MobileNetV2, "
          f"{len(_classes)} classes) — chargement unique au démarrage.")


def modele_est_charge() -> bool:
    return _model is not None


def predire_categorie(image_bytes: bytes) -> dict:
    """
    Classifie une image (octets bruts) et renvoie la consigne de tri.

    Lève ValueError si les octets ne forment pas une image exploitable
    (la vue Django peut alors afficher un message propre à l'utilisateur).
    """
    if _model is None:
        # Filet de sécurité si ready() n'a pas tourné (ex. certains tests).
        charger_modele()

    if not image_bytes:
        raise ValueError("Aucune donnée d'image reçue par le modèle.")

    # 1) Décodage des octets en image RGB 224x224 (même préparation
    #    qu'à l'entraînement ; la normalisation -1..1 est DANS le modèle,
    #    via sa couche Rescaling).
    try:
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except UnidentifiedImageError as exc:
        raise ValueError(
            "Format d'image non reconnu (formats acceptés : JPEG, PNG, "
            "WEBP, GIF... — les SVG ne sont pas des images matricielles)."
        ) from exc
    image = image.resize(_TAILLE_IMAGE)

    tableau = np.asarray(image, dtype=np.float32)   # (224, 224, 3)
    tableau = np.expand_dims(tableau, axis=0)       # lot de 1 image

    # 2) Prédiction : 7 probabilités (une par matière), somme = 1.
    probas_matieres = _model.predict(tableau, verbose=0)[0]

    # 3) Agrégation par catégorie de tri officielle.
    probabilites = {slug: 0.0 for slug in CATEGORIES}
    for classe, proba in zip(_classes, probas_matieres):
        probabilites[MATIERE_VERS_CATEGORIE[classe]] += float(proba)
    probabilites = {slug: round(p, 3) for slug, p in probabilites.items()}

    # Corrige l'erreur d'arrondi pour que la somme fasse exactement 1.
    slug_pred = max(probabilites, key=probabilites.get)
    ecart = round(1.0 - sum(probabilites.values()), 3)
    probabilites[slug_pred] = round(probabilites[slug_pred] + ecart, 3)

    # 4) Construit la réponse au format du contrat.
    resultat = dict(CATEGORIES[slug_pred])
    resultat["confiance"] = probabilites[slug_pred]
    resultat["probabilites"] = probabilites
    return resultat
