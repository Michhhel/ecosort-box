#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
jumia_image_scraper.py
=======================

Prend en entrée une phrase libre en français décrivant un article
(ex: "j'ai une motre casio"), corrige les fautes de frappe probables,
scrape Jumia CI pour trouver les articles correspondants (15 maximum),
et affiche les résultats par pages de 5 (avec navigation dans le reste).

La fonction scrape_jumia_images() renvoie une liste de dictionnaires
au format [{"nom": ..., "image": ...}, ...], directement exploitable
par une interface web.

Installation : pip install -r requirements.txt
Utilisation  :
    python jumia_image_scraper.py "j'ai une motre casio"
    python jumia_image_scraper.py "je cherche un telefone samsung" --download
"""

import argparse
import os
import re
import time
import unicodedata
from dataclasses import dataclass, field
from typing import List, Optional
from urllib.parse import quote_plus, urljoin

import requests
from bs4 import BeautifulSoup

try:
    from rapidfuzz import fuzz, process as rf_process
    HAS_RAPIDFUZZ = True
except ImportError:
    HAS_RAPIDFUZZ = False

try:
    from spellchecker import SpellChecker
    HAS_SPELLCHECKER = True
except ImportError:
    HAS_SPELLCHECKER = False


# ============================================================================
# 1) CONFIGURATION
# ============================================================================

JUMIA_BASE_URL = "https://www.jumia.ci"
# Point d'entrée standard de la recherche sur les sites Jumia
JUMIA_SEARCH_URL = JUMIA_BASE_URL + "/catalog/?q={query}"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
}

# Mots à retirer d'une phrase du type "j'ai une montre casio"
# pour ne garder que les mots "produit" utiles à la recherche.
STOPWORDS_FR = {
    "j'ai", "jai", "j", "ai", "je", "veux", "voudrais", "cherche",
    "recherche", "voici", "voila", "il", "me", "faut", "un", "une",
    "des", "de", "du", "la", "le", "les", "et", "avec", "pour",
    "svp", "sil", "vous", "plait", "plaît", "acheter", "achete",
    "acheté", "trouve", "trouver", "moi",
}
# NB : "montre" n'est PAS un stopword — c'est aussi un produit (montre Casio) !
# Les tournures impératives ("montre-moi", "me montrer"...) sont retirées en
# bloc par _TOURNURES_IMPERATIVES avant le filtrage : on supprime le VERBE
# montrer sans jamais supprimer le PRODUIT montre.

# Categories frequentes egalement toutes les categories frequentes sur Jumia
PRODUCT_VOCAB = [
    "montre", "telephone", "smartphone", "ordinateur", "laptop",
    "tablette", "ecouteur", "casque", "chargeur", "cable", "television",
    "televiseur", "tele", "frigo", "refrigerateur", "congelateur", "climatiseur",
    "ventilateur", "cuisiniere", "micro-onde", "mixeur", "blender",
    "chaussure", "sandale", "basket", "vetement", "robe", "chemise",
    "pantalon", "jean", "veste", "sac", "sac a main", "parfum",
    "creme", "maquillage", "rouge a levre", "bijou", "collier",
    "bague", "bracelet", "lunette", "casio", "samsung", "iphone",
    "tecno", "infinix", "xiaomi", "hisense", "nasco", "lg", "sony",
    "matelas", "canape", "table", "chaise", "lit", "armoire",
    "imprimante", "clavier", "souris", "manette", "console", "jeu",
    "batterie", "powerbank", "haut-parleur", "enceinte", "fer a repasser",
    "aspirateur", "moto", "velo", "pneu", "jouet", "couche", "biberon",
]

# Nombre maximum d'articles recherchés sur Jumia à chaque requête.
# Ce nombre est fixe : on ne le demande plus à l'utilisateur.
MAX_ITEMS = 15

# Nombre d'articles affichés par page dans le mode CLI (les 5 premiers,
# puis l'utilisateur peut parcourir le reste par lots de 5).
DISPLAY_PAGE_SIZE = 5


# ============================================================================
# 2) NETTOYAGE + COMPRÉHENSION / CORRECTION ORTHOGRAPHIQUE
# ============================================================================

def strip_accents(text: str) -> str:
    """Retire les accents pour faciliter les comparaisons (motre/montre...)."""
    return "".join(
        c for c in unicodedata.normalize("NFD", text)
        if unicodedata.category(c) != "Mn"
    )


def tokenize(text: str) -> List[str]:
    """Découpe la phrase en mots simples (lettres/chiffres uniquement)."""
    text = text.lower().replace("’", "'")
    # Sépare "j'ai" en gardant l'apostrophe pour le filtrage stopwords
    tokens = re.findall(r"[a-zàâäéèêëîïôöùûüç0-9']+", text)
    return tokens


# Tournures impératives du verbe "montrer" ("montre-moi une tele",
# "tu peux me montrer un frigo"). Retirées AVANT la découpe en mots pour ne
# pas confondre le verbe avec le produit "montre".
_TOURNURES_IMPERATIVES = re.compile(
    r"\b(?:montre[sz]?[- ]+moi|me\s+montrer?|montrer)\b"
)


def clean_query(raw_text: str) -> List[str]:
    """
    Extrait de la phrase brute la ou les mots-clés "produit" utiles,
    en retirant les mots de liaison usuels.

    Exemple : "j'ai une montre casio" -> ["montre", "casio"]
    """
    texte = _TOURNURES_IMPERATIVES.sub(" ", raw_text.lower().replace("’", "'"))
    tokens = tokenize(texte)
    keywords = []
    for tok in tokens:
        tok_norm = strip_accents(tok)
        if tok in STOPWORDS_FR or tok_norm in STOPWORDS_FR:
            continue
        if len(tok) <= 1:
            continue
        keywords.append(tok)
    return keywords


@dataclass
class SpellSuggestion:
    original: str
    corrected: str
    confidence: float          # 0 à 100
    source: str                # "vocab_metier" | "dictionnaire_fr" | "inchange"
    was_corrected: bool = field(init=False)

    def __post_init__(self):
        self.was_corrected = self.original.lower() != self.corrected.lower()


# Dictionnaire français chargé UNE seule fois (None si indisponible).
_SPELL_FR = None
_SPELL_FR_ECHEC = False


def _dictionnaire_francais():
    """Renvoie le SpellChecker français partagé, ou None s'il est indisponible."""
    global _SPELL_FR, _SPELL_FR_ECHEC
    if _SPELL_FR is None and not _SPELL_FR_ECHEC and HAS_SPELLCHECKER:
        try:
            _SPELL_FR = SpellChecker(language="fr")
        except Exception:
            _SPELL_FR_ECHEC = True  # pas de dictionnaire fr local -> on ignore
    return _SPELL_FR


def correct_word(word: str, vocab: List[str] = PRODUCT_VOCAB) -> SpellSuggestion:
    """
    Tente de corriger un mot potentiellement mal orthographié.

    Stratégie (le "petit volet de compréhension" demandé) :
      1. Si le mot existe déjà tel quel dans le vocabulaire métier -> OK.
      2. Sinon on cherche le mot du vocabulaire métier le plus proche
         (similarité de chaînes de caractères, tolère 1-2 lettres
         d'erreur, ex: motre -> montre, telefone -> telephone).
      3. Si rien de suffisamment proche dans le vocabulaire métier,
         on retombe sur un correcteur orthographique français général
         (utile pour les marques ou mots hors vocabulaire connu).
      4. Si aucune correction fiable n'est trouvée, on garde le mot
         d'origine (ce peut être un nom de marque, ex: "casio").
    """
    word_l = word.lower()
    word_norm = strip_accents(word_l)

    vocab_norm = {strip_accents(v): v for v in vocab}

    # 1) Mot déjà correct
    if word_norm in vocab_norm:
        return SpellSuggestion(word, vocab_norm[word_norm], 100.0, "vocab_metier")

    # 1 bis) GARDE-FOU : un mot français parfaitement valide (pomme, canette,
    # bocal, verre...) n'est JAMAIS "corrigé" vers le vocabulaire métier.
    # Sans cette barrière, la similarité de chaînes transformait par exemple
    # "canette" en "manette" (85 % de ressemblance) et la recherche renvoyait
    # n'importe quoi. Un mot correct est gardé tel quel.
    spell = _dictionnaire_francais()
    if spell is not None and word_l in spell:
        return SpellSuggestion(word, word, 100.0, "inchange")

    # 2) Correction via le vocabulaire métier (rapidfuzz si dispo,
    #    sinon un fallback maison avec difflib)
    best_match, best_score = None, 0.0
    if HAS_RAPIDFUZZ:
        result = rf_process.extractOne(
            word_norm, list(vocab_norm.keys()), scorer=fuzz.ratio
        )
        if result:
            match_norm, score, _ = result
            best_match, best_score = vocab_norm[match_norm], score
    else:
        import difflib
        matches = difflib.get_close_matches(
            word_norm, list(vocab_norm.keys()), n=1, cutoff=0.6
        )
        if matches:
            best_match = vocab_norm[matches[0]]
            best_score = difflib.SequenceMatcher(
                None, word_norm, matches[0]
            ).ratio() * 100

    # Seuil de confiance : en dessous, on considère que ce n'est
    # probablement pas une faute de frappe sur ce mot-clé métier
    if best_match and best_score >= 75:
        return SpellSuggestion(word, best_match, round(best_score, 1), "vocab_metier")

    # 3) Repli sur un correcteur orthographique français généraliste.
    # (Si on arrive ici, le mot n'est ni dans le vocabulaire métier, ni un
    # mot français valide — le dictionnaire partagé a déjà été consulté.)
    if spell is not None:
        try:
            suggestion = spell.correction(word_l)
            if suggestion and suggestion != word_l:
                return SpellSuggestion(word, suggestion, 60.0, "dictionnaire_fr")
        except Exception:
            pass  # pas de dictionnaire fr dispo localement -> on ignore

    # 4) Rien de fiable -> on ne touche pas au mot (probablement une marque)
    return SpellSuggestion(word, word, 100.0, "inchange")


def understand_and_correct(raw_text: str) -> (List[SpellSuggestion], str):
    """
    Le "volet de compréhension" : à partir de la phrase brute de
    l'utilisateur, renvoie :
      - la liste des suggestions de correction mot par mot
      - la requête finale corrigée, prête à être envoyée à Jumia
    """
    keywords = clean_query(raw_text)
    suggestions = [correct_word(k) for k in keywords]
    corrected_query = " ".join(s.corrected for s in suggestions)

    # GARDE-FOU : ne JAMAIS renvoyer une requête vide. Une recherche Jumia
    # sans mot-clé renvoie le catalogue par défaut, donc des produits sans
    # aucun rapport. Si le nettoyage a tout supprimé, on retombe sur les
    # mots bruts de la phrase (sans ponctuation).
    if not corrected_query.strip():
        corrected_query = " ".join(tokenize(raw_text)).strip()

    return suggestions, corrected_query


def print_understanding_report(raw_text: str, suggestions: List[SpellSuggestion]):
    print("—" * 60)
    print(f"Phrase d'entrée         : {raw_text}")
    print("Analyse mot par mot :")
    for s in suggestions:
        if s.was_corrected:
            print(f"  • '{s.original}' -> compris comme '{s.corrected}' "
                  f"(confiance {s.confidence}%, source: {s.source})")
        else:
            print(f"  • '{s.original}' -> gardé tel quel")
    print("—" * 60)


# ============================================================================
# 3) SCRAPING JUMIA
# ============================================================================

@dataclass
class Produit:
    """Représentation interne d'un produit trouvé (usage interne)."""
    nom: str
    lien: str
    images: List[str]


def build_search_url(query: str) -> str:
    return JUMIA_SEARCH_URL.format(query=quote_plus(query))


def _extract_image_url(img_tag) -> Optional[str]:
    """
    Les images de produits sur les sites Jumia sont très souvent
    chargées en 'lazy loading' : l'attribut src pointe parfois vers un
    minuscule placeholder, et la vraie image est dans data-src (ou
    parfois data-srcset / srcset). On essaie plusieurs attributs.
    """
    for attr in ("data-src", "data-srcset", "srcset", "src"):
        val = img_tag.get(attr)
        if val:
            # srcset peut contenir plusieurs URLs séparées par des virgules
            first_url = val.split(",")[0].strip().split(" ")[0]
            if first_url.startswith("//"):
                first_url = "https:" + first_url
            if first_url.startswith("http"):
                return first_url
    return None


def scrape_with_requests(query: str, max_items: int = MAX_ITEMS) -> List[Produit]:
    """
    Scraping "classique" via requests + BeautifulSoup.
    Fonctionne si la page de résultats est pré-rendue côté serveur
    (c'est généralement le cas pour les pages catalogue/mlp/slp Jumia).
    """
    url = build_search_url(query)
    produits: List[Produit] = []

    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"[!] Erreur réseau lors de la requête vers Jumia : {e}")
        return produits

    soup = BeautifulSoup(resp.text, "html.parser")

    # Les cartes produits Jumia sont en général des balises <article class="prd ...">
    # contenant un lien <a class="core"> et une image <img>.
    cards = soup.select("article.prd") or soup.select("a.core")

    for card in cards[:max_items]:
        link_tag = card if card.name == "a" else card.select_one("a.core, a[href]")
        img_tag = card.select_one("img")

        if not link_tag or not img_tag:
            continue

        lien = link_tag.get("href", "")
        if lien and not lien.startswith("http"):
            lien = urljoin(JUMIA_BASE_URL, lien)

        nom_tag = card.select_one("h3.name, .name")
        nom = nom_tag.get_text(strip=True) if nom_tag else query

        image_url = _extract_image_url(img_tag)
        images = [image_url] if image_url else []

        produits.append(Produit(nom=nom, lien=lien, images=images))

    return produits


def scrape_with_selenium(query: str, max_items: int = MAX_ITEMS) -> List[Produit]:
    """
    Mode de secours : si scrape_with_requests() ne renvoie rien
    (page rendue en JavaScript, contenu chargé dynamiquement, etc.),
    on ouvre un vrai navigateur headless pour laisser le JS s'exécuter
    avant de récupérer le HTML final.

    Nécessite : pip install selenium webdriver-manager
    """
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service
        from webdriver_manager.chrome import ChromeDriverManager
    except ImportError:
        print("[!] Selenium/webdriver-manager non installés. "
              "Faites : pip install selenium webdriver-manager")
        return []

    url = build_search_url(query)
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument(f"user-agent={HEADERS['User-Agent']}")

    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()), options=options
    )
    produits: List[Produit] = []
    try:
        driver.get(url)
        time.sleep(3)  # laisser le temps au JS de charger les produits
        soup = BeautifulSoup(driver.page_source, "html.parser")
        cards = soup.select("article.prd") or soup.select("a.core")

        for card in cards[:max_items]:
            link_tag = card if card.name == "a" else card.select_one("a.core, a[href]")
            img_tag = card.select_one("img")
            if not link_tag or not img_tag:
                continue

            lien = link_tag.get("href", "")
            if lien and not lien.startswith("http"):
                lien = urljoin(JUMIA_BASE_URL, lien)

            nom_tag = card.select_one("h3.name, .name")
            nom = nom_tag.get_text(strip=True) if nom_tag else query

            image_url = _extract_image_url(img_tag)
            images = [image_url] if image_url else []

            produits.append(Produit(nom=nom, lien=lien, images=images))
    finally:
        driver.quit()

    return produits


def _produits_vers_dicts(produits: List[Produit]) -> List[dict]:
    """
    Convertit la liste interne de Produit en liste de dictionnaires
    simples, au format attendu par l'interface web :
        {"nom": "...", "image": "... ou None"}
    """
    return [
        {"nom": p.nom, "image": (p.images[0] if p.images else None)}
        for p in produits
    ]


def scrape_jumia_images(query: str, max_items: int = MAX_ITEMS) -> List[dict]:
    """
    Point d'entrée principal du scraping : essaie d'abord requests,
    puis bascule automatiquement sur Selenium si rien n'est trouvé.

    Recherche toujours au maximum `max_items` articles (15 par défaut).

    Retourne une LISTE DE DICTIONNAIRES au format :
        [{"nom": "Montre Casio ...", "image": "https://..."}, ...]
    """
    produits = scrape_with_requests(query, max_items=max_items)
    if not produits:
        print("[i] Aucun résultat via requests seul, tentative avec "
              "un navigateur headless (Selenium)...")
        produits = scrape_with_selenium(query, max_items=max_items)
    return _produits_vers_dicts(produits)


# ============================================================================
# 4) TÉLÉCHARGEMENT DES IMAGES (OPTIONNEL)
# ============================================================================

def download_images(articles: List[dict], dossier: str = "images_jumia"):
    """
    Télécharge localement les images des articles fournis.
    `articles` est la liste de dictionnaires {"nom": ..., "image": ...}
    renvoyée par scrape_jumia_images().
    """
    os.makedirs(dossier, exist_ok=True)
    compteur = 0
    for article in articles:
        img_url = article.get("image")
        if not img_url:
            continue
        try:
            resp = requests.get(img_url, headers=HEADERS, timeout=15)
            resp.raise_for_status()
            ext = os.path.splitext(img_url.split("?")[0])[1] or ".jpg"
            nom_fichier = re.sub(r"[^a-zA-Z0-9_-]", "_", article.get("nom", "article"))[:50]
            chemin = os.path.join(dossier, f"{nom_fichier}_{compteur}{ext}")
            with open(chemin, "wb") as f:
                f.write(resp.content)
            print(f"  ✓ Image téléchargée : {chemin}")
            compteur += 1
        except requests.RequestException as e:
            print(f"  ✗ Échec du téléchargement de {img_url} : {e}")


# ============================================================================
# 5) ADAPTATEUR POUR LE SITE WEB — appelé par webapp/views.py (/api/search)
# ============================================================================
#
# La vue Django attend une fonction `rechercher_produits(mot_cle, page)` qui
# renvoie une liste de dictionnaires {"titre", "image_url", "produit_url"}.
# Cette section fait le pont entre ce contrat web et le scraper ci-dessus :
#
#   1. la phrase de l'utilisateur est d'abord corrigée (understand_and_correct),
#   2. Jumia est scrapé UNE SEULE FOIS (15 articles max) et la liste complète
#      est CONSOLIDÉE en cache mémoire,
#   3. chaque "page" sert ensuite une tranche de 5 produits de cette liste :
#      page 1 -> produits 1 à 5, page 2 -> 6 à 10, page 3 -> 11 à 15 ;
#   4. quand la liste est épuisée, on renvoie [] : l'interface web propose
#      alors automatiquement à l'utilisateur d'envoyer sa propre photo.

import threading
from collections import OrderedDict

# Nombre de produits servis au site web à chaque page.
PAGE_SIZE_WEB = DISPLAY_PAGE_SIZE  # = 5

# Cache mémoire des recherches récentes : {requête corrigée: [produits...]}.
# Borné (LRU) pour ne pas grossir indéfiniment ; protégé par un verrou car
# gunicorn sert les requêtes avec plusieurs threads.
_CACHE_MAX_RECHERCHES = 20
_cache_recherches: "OrderedDict[str, List[dict]]" = OrderedDict()
_verrou_cache = threading.Lock()


def _scraper_produits_complets(query: str, max_items: int = MAX_ITEMS) -> List[Produit]:
    """
    Scrape Jumia : d'abord via requests (rapide), puis repli Selenium si rien.
    Le repli est enveloppé dans un try/except : si Selenium n'est pas
    utilisable (ex. pas de Chrome dans le conteneur Docker), on renvoie
    simplement une liste vide au lieu de faire planter la requête web.
    """
    produits = scrape_with_requests(query, max_items=max_items)
    if not produits:
        try:
            produits = scrape_with_selenium(query, max_items=max_items)
        except Exception as e:
            print(f"[!] Repli Selenium indisponible : {e}")
            produits = []
    return produits


def rechercher_produits(mot_cle: str, page: int = 1) -> List[dict]:
    """
    Point d'entrée officiel pour le site web (contrat de webapp/views.py).

    Entrée  : phrase libre de l'utilisateur (ex. "j'ai une motre casio")
              + numéro de page (1 = cinq premiers produits, 2 = les 5
              suivants de la MÊME liste déjà scrapée, etc.).
    Sortie  : [{"titre": ..., "image_url": ..., "produit_url": ...}, ...]
              (au plus PAGE_SIZE_WEB éléments ; [] quand il n'y a plus rien).
    """
    # 1) Compréhension + correction orthographique de la phrase saisie.
    _, requete_corrigee = understand_and_correct(mot_cle)
    if not requete_corrigee:
        # Tous les mots étaient des mots de liaison : on garde la phrase brute.
        requete_corrigee = mot_cle.strip()

    cle_cache = strip_accents(requete_corrigee.lower())

    # 2) Liste consolidée : reprise du cache si la recherche a déjà eu lieu,
    #    sinon scraping unique de 15 articles maximum.
    with _verrou_cache:
        resultats = _cache_recherches.get(cle_cache)

    if resultats is None:
        produits = _scraper_produits_complets(requete_corrigee)
        resultats = [
            {
                "titre": p.nom,
                "image_url": p.images[0],
                "produit_url": p.lien,
            }
            for p in produits
            if p.images  # un produit sans image ne peut pas être affiché
        ]
        with _verrou_cache:
            _cache_recherches[cle_cache] = resultats
            _cache_recherches.move_to_end(cle_cache)
            while len(_cache_recherches) > _CACHE_MAX_RECHERCHES:
                _cache_recherches.popitem(last=False)  # évince la plus ancienne

    # 3) Tranche de 5 correspondant à la page demandée.
    page = max(1, int(page))
    debut = (page - 1) * PAGE_SIZE_WEB
    return resultats[debut:debut + PAGE_SIZE_WEB]


# ============================================================================
# 6) PROGRAMME PRINCIPAL (CLI + pagination)
# ============================================================================

def display_articles_paginated(articles, page_size=DISPLAY_PAGE_SIZE):
    """
    Affiche les articles par pages de `page_size` (5 par défaut).
    Après chaque page, demande à l'utilisateur s'il veut voir la suite.
    """
    total = len(articles)
    index = 0
    while index < total:
        page = articles[index:index + page_size]
        for i, article in enumerate(page, start=index + 1):
            print(f"{i}. {article['nom']}")
            print(f"   Image : {article['image']}")
            print()
        index += page_size

        if index < total:
            reste = total - index
            reponse = input(
                f"Afficher les {min(page_size, reste)} articles suivants "
                f"({reste} restants) ? (o/n) : "
            ).strip().lower()
            if reponse != "o":
                break


def run(raw_text: str, do_download: bool = False):
    """
    Exécute le pipeline complet :
      1. Compréhension + correction orthographique de la phrase saisie
         (en silence, sans affichage du rapport).
      2. Scraping de Jumia CI (toujours 15 articles maximum) avec la
         requête corrigée.
      3. Téléchargement optionnel des images.

    La SEULE sortie du script est la liste des articles trouvés, au
    format [{"nom": ..., "image": ...}, ...] — utile pour l'interface
    web comme pour un usage en ligne de commande.
    """
    _, corrected_query = understand_and_correct(raw_text)

    # Scraping (toujours 15 articles maximum)
    articles = scrape_jumia_images(corrected_query, max_items=MAX_ITEMS)

    if do_download:
        download_images(articles)

    print(articles)
    return articles


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Trouve des images d'articles sur Jumia CI à partir "
                    "d'une phrase en français (avec correction des fautes)."
    )
    parser.add_argument(
        "phrase", nargs="*",
        help="Phrase décrivant l'article, ex: \"j'ai une motre casio\""
    )
    parser.add_argument("--download", action="store_true", help="Télécharger les images trouvées")
    args = parser.parse_args()

    if args.phrase:
        texte = " ".join(args.phrase)
    else:
        texte = input("Décrivez l'article recherché : ")

    run(texte, do_download=args.download)
