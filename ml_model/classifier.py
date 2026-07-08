"""
MOCK du module de classification deep learning.

⚠️ Ce fichier est un bouchon de développement. Il sera remplacé par le vrai
module du coéquipier "IA", qui devra exposer les deux fonctions publiques :

    charger_modele() -> None        # idempotent, appelée UNE fois au démarrage
    predire_categorie(image_bytes: bytes) -> dict

Contrat de sortie (PROPOSITION à valider avec le coéquipier IA) :
    {
        "categorie": str,       # ex. "Poubelle JAUNE"
        "couleur": str,         # slug parmi "jaune", "verte", "bleue", "grise", "marron"
        "confiance": float,     # probabilité de la classe prédite
        "probabilites": {slug: float, ...}   # distribution sur les 5 catégories
    }

⚠️ EXTENSION DE CONTRAT À VALIDER avec le coéquipier IA : la clé
`probabilites` (sortie softmax agrégée par catégorie de tri). Elle est
indispensable au mécanisme de retour utilisateur : quand un utilisateur
conteste une prédiction, on n'accepte sa correction que si le modèle
lui-même donnait une probabilité non négligeable à la poubelle proposée
(voir ml_model/feedback.py). Côté Keras c'est gratuit : c'est le vecteur
model.predict() déjà calculé, sommé par catégorie officielle.

Côté vrai module, charger_modele() fera typiquement :
    keras.models.load_model(Path(__file__).parent / "modele_eco_sort.h5")
et predire_categorie() : décodage image -> resize 224x224 -> normalisation
-> model.predict -> mapping matière -> catégorie officielle + distribution.

Comportement du mock :
  1. Si les octets de l'image contiennent un marqueur "materiau:<classe>"
     (présent dans les SVG factices du scraper mock), la catégorie est déduite
     de la matière -> démo parfaitement cohérente et déterministe.
  2. Sinon (vraie image Jumia, photo uploadée...), choix pseudo-aléatoire mais
     DÉTERMINISTE (seedé par le hash des octets) : la même image donne
     toujours le même verdict.
La confiance du mock varie entre ~0,70 et ~0,97 pour permettre de tester les
trois issues du feedback (correction acceptée, rejetée, prédiction verrouillée).
"""
from __future__ import annotations

import hashlib
import random
import re
import time

# --- Référentiel officiel des 5 catégories (cf. projet_ISE2.md) ----------
# matière du dataset Kaggle -> catégorie de tri
MATIERE_VERS_CATEGORIE = {
    "plastic": "jaune",
    "metal": "jaune",
    "cardboard": "jaune",
    "glass": "verte",
    "paper": "bleue",
    "electronique": "grise",   # D3E : classe dédiée / mots-clés (hors Kaggle)
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

_ORDRE_SLUGS = list(CATEGORIES)

# Le "modèle" chargé. Dans le vrai module : l'objet Keras.
_model = None


def charger_modele() -> None:
    """
    Charge le modèle en mémoire. Idempotent : les appels suivants sont no-op.

    Cette fonction est appelée UNE SEULE FOIS au démarrage du serveur, dans
    webapp.apps.WebappConfig.ready() — jamais à chaque requête.
    """
    global _model
    if _model is not None:
        return
    # Vrai module : _model = keras.models.load_model(".../modele_eco_sort.h5")
    time.sleep(0.2)  # simule le temps de chargement d'un .h5
    _model = "MOCK-MODEL-v1"
    print("[ml_model] Modèle (mock) chargé en mémoire — chargement unique au démarrage.")


def modele_est_charge() -> bool:
    return _model is not None


def _distribution(slug_pred: str, confiance: float, graine: str) -> dict:
    """
    Fabrique une distribution de probabilités plausible sur les 5 catégories :
    la classe prédite reçoit `confiance`, le reste est réparti de façon
    déterministe (la 2e classe concentre l'essentiel de l'hésitation).
    """
    rng = random.Random(graine)
    autres = [s for s in _ORDRE_SLUGS if s != slug_pred]
    rng.shuffle(autres)

    reste = max(0.0, 1.0 - confiance)
    poids = [0.75, 0.15, 0.07, 0.03]

    probabilites = {slug_pred: round(confiance, 3)}
    for slug, poids_relatif in zip(autres, poids):
        probabilites[slug] = round(reste * poids_relatif, 3)

    # Corrige l'erreur d'arrondi pour que la somme fasse exactement 1.
    ecart = round(1.0 - sum(probabilites.values()), 3)
    probabilites[slug_pred] = round(probabilites[slug_pred] + ecart, 3)
    return probabilites


def predire_categorie(image_bytes: bytes) -> dict:
    """
    Classifie une image (octets bruts) et renvoie la consigne de tri.

    Signature identique à celle du futur vrai module : la vue Django reste
    inchangée le jour où le vrai modèle arrive.
    """
    if _model is None:
        # Filet de sécurité si ready() n'a pas tourné (ex. certains tests).
        charger_modele()

    if not image_bytes:
        raise ValueError("Aucune donnée d'image reçue par le modèle.")

    time.sleep(random.uniform(0.7, 1.4))  # simule l'inférence

    empreinte = hashlib.md5(image_bytes).hexdigest()

    # 1) Marqueur "materiau:xxx" dans les images factices du scraper mock.
    texte = image_bytes[:4096].decode("utf-8", errors="ignore")
    m = re.search(r"materiau:([a-z]+)", texte)
    if m and m.group(1) in MATIERE_VERS_CATEGORIE:
        slug = MATIERE_VERS_CATEGORIE[m.group(1)]
        # Confiance déterministe entre 0,70 et 0,95 (permet de tester les
        # différents chemins du feedback utilisateur).
        confiance = 0.70 + (int(empreinte, 16) % 26) / 100
    else:
        # 2) Image inconnue : verdict déterministe seedé par le contenu.
        rng = random.Random(empreinte)
        slug = rng.choice(_ORDRE_SLUGS)
        confiance = round(rng.uniform(0.72, 0.97), 2)

    resultat = dict(CATEGORIES[slug])
    resultat["confiance"] = round(float(confiance), 2)
    resultat["probabilites"] = _distribution(slug, resultat["confiance"], empreinte)
    return resultat
