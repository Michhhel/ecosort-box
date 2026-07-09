"""
Registre en mémoire des prédictions récentes.

Quand /api/classify rend un verdict, on garde quelques instants l'image et la
sortie complète du modèle (distribution incluse) sous un identifiant court.
Si l'utilisateur conteste ensuite le verdict, /api/feedback retrouve ici tout
le contexte nécessaire — sans re-télécharger l'image ni re-prédire.

Choix d'implémentation : un simple dict LRU protégé par un verrou. C'est
suffisant et fiable parce que gunicorn tourne avec UN seul worker (voir
Dockerfile) ; si un jour l'app passe en multi-workers, remplacer ce module
par un stockage partagé (fichiers temporaires, Redis...).
"""
from __future__ import annotations

import threading
import time
import uuid
from collections import OrderedDict

# Nombre maximal de prédictions gardées en mémoire (les images uploadées
# peuvent peser jusqu'à 8 Mo : on borne strictement).
_CAPACITE = 30

_registre: OrderedDict[str, dict] = OrderedDict()
_verrou = threading.Lock()


def enregistrer(image_bytes: bytes, prediction: dict) -> str:
    """Mémorise une prédiction et renvoie son identifiant court."""
    identifiant = uuid.uuid4().hex[:12]
    with _verrou:
        _registre[identifiant] = {
            "image_bytes": image_bytes,
            "prediction": prediction,
            "cree_le": time.time(),
        }
        _registre.move_to_end(identifiant)
        while len(_registre) > _CAPACITE:
            _registre.popitem(last=False)  # évince la plus ancienne
    return identifiant


def recuperer(identifiant: str) -> dict | None:
    """Renvoie l'entrée {image_bytes, prediction, cree_le} ou None si évincée."""
    with _verrou:
        return _registre.get(identifiant)
