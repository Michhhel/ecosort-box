"""
MOCK du module de scraping Jumia.

⚠️ Ce fichier est un bouchon de développement. Il sera remplacé par le vrai
module du coéquipier "scraping", qui devra exposer la même fonction publique :

    rechercher_produits(mot_cle: str, page: int = 1) -> list[dict]

Contrat de sortie (CONFIRMÉ) : une liste de 3 à 5 dictionnaires de la forme
    {"titre": str, "image_url": str, "produit_url": str}
ou une liste vide si aucun produit ne correspond.

⚠️ EXTENSION DE CONTRAT À VALIDER avec le coéquipier scraping : le paramètre
optionnel `page` (défaut 1) alimente le bouton « Voir d'autres produits » de
l'interface. page=1 -> premiers résultats ; page=2, 3... -> résultats suivants
du moteur de recherche Jumia ; liste vide quand il n'y a plus rien.
La vue Django détecte la présence de ce paramètre dans la signature : si le
vrai module ne l'implémente pas (contrat d'origine), tout continue de marcher,
seul le bouton « Voir d'autres produits » renverra les mêmes résultats.

Cas de test intégrés :
  - mots-clés connus ("bouteille", "canette", "téléphone", ...) -> résultats ciblés ;
  - mot-clé inconnu -> sélection générique de 4 produits ;
  - mot-clé "introuvable" ou "aucun" -> liste vide (test du cas sans résultat) ;
  - mot-clé "erreur" -> lève une exception (test de la gestion d'erreur côté vue) ;
  - page=2 -> autres produits ; pages suivantes -> [] quand le stock est épuisé.
"""
from __future__ import annotations

import random
import time
import unicodedata

# Préfixe des images factices servies par l'app Django elle-même.
_IMG = "/static/webapp/img/mock/"


def _produit(titre: str, image: str) -> dict:
    """Fabrique un dict produit conforme au contrat."""
    slug = titre.lower().replace(" ", "-").replace("'", "-")
    return {
        "titre": titre,
        "image_url": f"{_IMG}{image}.svg",
        "produit_url": f"https://www.jumia.com.ng/mock/{slug}.html",
    }


# Petit catalogue factice. Les noms d'images correspondent aux SVG présents
# dans webapp/static/webapp/img/mock/.
_CATALOGUE: dict[str, list[dict]] = {
    "bouteille": [
        _produit("Bouteille d'eau minérale 1,5 L", "bouteille_plastique"),
        _produit("Bouteille de jus en verre 75 cl", "bouteille_verre"),
        _produit("Bouteille de soda 50 cl", "bouteille_plastique"),
        _produit("Bouteille d'huile végétale 1 L", "bouteille_plastique"),
    ],
    "canette": [
        _produit("Canette de soda 33 cl", "canette"),
        _produit("Pack de 6 canettes énergisantes", "canette"),
        _produit("Boîte de conserve de tomates 400 g", "conserve"),
    ],
    "conserve": [
        _produit("Boîte de conserve de tomates 400 g", "conserve"),
        _produit("Boîte de conserve de sardines", "conserve"),
        _produit("Bocal de conserve de haricots", "bocal"),
    ],
    "lait": [
        _produit("Brique de lait entier 1 L", "brique_lait"),
        _produit("Pack de 6 briques de lait", "brique_lait"),
        _produit("Bouteille de lait 1 L", "bouteille_plastique"),
    ],
    "bocal": [
        _produit("Pot de confiture de fraises 370 g", "pot_confiture"),
        _produit("Bocal de conserve en verre 1 L", "bocal"),
        _produit("Bouteille de vin rouge 75 cl", "bouteille_verre"),
    ],
    "confiture": [
        _produit("Pot de confiture de fraises 370 g", "pot_confiture"),
        _produit("Pot de confiture d'orange 250 g", "pot_confiture"),
        _produit("Pot de miel en verre 500 g", "bocal"),
    ],
    "journal": [
        _produit("Journal quotidien national", "journal"),
        _produit("Magazine hebdomadaire", "magazine"),
        _produit("Lot de prospectus publicitaires", "journal"),
    ],
    "cahier": [
        _produit("Cahier grands carreaux 96 pages", "cahier"),
        _produit("Lot de 5 cahiers d'écolier", "cahier"),
        _produit("Bloc-notes A5", "cahier"),
        _produit("Enveloppes blanches x50", "journal"),
    ],
    "telephone": [
        _produit("Smartphone X10 128 Go", "smartphone"),
        _produit("Téléphone à touches basique", "smartphone"),
        _produit("Chargeur USB-C 25 W", "chargeur"),
        _produit("Coque de téléphone silicone", "sachet"),
    ],
    "ecouteurs": [
        _produit("Écouteurs sans fil Bluetooth", "ecouteurs"),
        _produit("Écouteurs filaires jack 3,5 mm", "ecouteurs"),
        _produit("Casque audio pliable", "ecouteurs"),
    ],
    "chargeur": [
        _produit("Chargeur USB-C 25 W", "chargeur"),
        _produit("Batterie externe 10 000 mAh", "chargeur"),
        _produit("Câble USB tressé 2 m", "chargeur"),
    ],
    "sachet": [
        _produit("Sachets plastiques x100", "sachet"),
        _produit("Film alimentaire étirable 50 m", "sachet"),
        _produit("Sacs poubelle 30 L x20", "sachet"),
    ],
    "carton": [
        _produit("Carton de déménagement 60x40", "carton"),
        _produit("Lot de 10 cartons de colis", "carton"),
        _produit("Boîte en carton kraft", "carton"),
    ],
}

# Alias -> clé du catalogue (recherche insensible aux accents).
_ALIAS = {
    "eau": "bouteille", "soda": "canette", "jus": "bouteille",
    "boite": "conserve", "verre": "bocal", "vin": "bocal",
    "pot": "confiture", "miel": "confiture",
    "papier": "journal", "magazine": "journal", "livre": "cahier",
    "smartphone": "telephone", "portable": "telephone", "gsm": "telephone",
    "casque": "ecouteurs", "airpods": "ecouteurs",
    "cable": "chargeur", "batterie": "chargeur", "montre": "telephone",
    "film": "sachet", "sac": "sachet", "plastique": "sachet",
    "colis": "carton", "brique": "lait",
}

_GENERIQUE = [
    _produit("Bouteille d'eau minérale 1,5 L", "bouteille_plastique"),
    _produit("Canette de soda 33 cl", "canette"),
    _produit("Pot de confiture de fraises 370 g", "pot_confiture"),
    _produit("Écouteurs sans fil Bluetooth", "ecouteurs"),
    _produit("Journal quotidien national", "journal"),
    _produit("Carton de colis kraft", "carton"),
    _produit("Sachets plastiques x100", "sachet"),
]


def _normaliser(texte: str) -> str:
    """minuscules + suppression des accents ('Écouteurs' -> 'ecouteurs')."""
    texte = unicodedata.normalize("NFKD", texte.lower().strip())
    return "".join(c for c in texte if not unicodedata.combining(c))


def _premiers_resultats(mot: str) -> list[dict]:
    """Résultats de la page 1 (logique de la V1)."""
    for token in mot.split():
        cle = _ALIAS.get(token, token)
        if cle in _CATALOGUE:
            return list(_CATALOGUE[cle])
    for cle in _CATALOGUE:
        if cle in mot:
            return list(_CATALOGUE[cle])
    # Mot-clé inconnu : sélection générique déterministe (seedée par le mot,
    # pour que la pagination reste cohérente d'un appel à l'autre).
    rng = random.Random(mot)
    return rng.sample(_GENERIQUE, k=4)


def rechercher_produits(mot_cle: str, page: int = 1) -> list[dict]:
    """
    Point d'entrée public — signature identique à celle du futur vrai module
    (le paramètre `page` est l'extension de contrat décrite en tête de fichier).

    Simule la latence réseau du scraping puis renvoie 3 à 5 produits.
    """
    # Simule le temps d'un vrai scraping (rend l'indicateur "le bot cherche..."
    # visible pendant les démos).
    time.sleep(random.uniform(0.8, 1.6))

    mot = _normaliser(mot_cle)
    page = max(1, int(page))

    # Cas de test : aucun résultat.
    if mot in ("introuvable", "aucun", "rien"):
        return []

    # Cas de test : panne du scraper (vérifie la gestion d'erreur de la vue).
    if mot == "erreur":
        raise ConnectionError("MOCK : simulation d'une panne du scraping Jumia")

    premiers = _premiers_resultats(mot)
    if page == 1:
        return premiers

    # Pages suivantes : le reste du "catalogue Jumia", sans doublon avec la
    # page 1, dans un ordre déterministe (seedé par le mot-clé).
    deja_vus = {p["titre"] for p in premiers}
    reservoir, vus = [], set(deja_vus)
    for produits in _CATALOGUE.values():
        for produit in produits:
            if produit["titre"] not in vus:
                reservoir.append(produit)
                vus.add(produit["titre"])

    rng = random.Random(mot)
    rng.shuffle(reservoir)

    taille = 4
    debut = (page - 2) * taille
    return reservoir[debut:debut + taille]  # [] quand le stock est épuisé
