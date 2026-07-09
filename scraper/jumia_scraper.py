

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


STOPWORDS_FR = {
    "j'ai", "jai", "j", "ai", "je", "veux", "voudrais", "cherche",
    "recherche", "voici", "voila", "il", "me", "faut", "un", "une",
    "des", "de", "du", "la", "le", "les", "et", "avec", "pour",
    "svp", "sil", "vous", "plait", "plaît", "acheter", "achete",
    "acheté", "trouve", "trouver", "montre", "moi", 
}

# Categories frequentes egalement toutes les categories frequentes sur Jumia
PRODUCT_VOCAB = [
    "montre", "telephone", "smartphone", "ordinateur", "laptop",
    "tablette", "ecouteur", "casque", "chargeur", "cable", "television",
    "televiseur", "frigo", "refrigerateur", "congelateur", "climatiseur",
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

# -*- coding: utf-8 -*-
"""
text_understanding.py



⚠️ Import à ajouter en haut de CE fichier une fois séparé :
    from config import STOPWORDS_FR, PRODUCT_VOCAB
"""

import re
import unicodedata
from dataclasses import dataclass, field
from typing import List



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


def clean_query(raw_text: str) -> List[str]:
    """
    Extrait de la phrase brute la ou les mots-clés "produit" utiles,
    en retirant les mots de liaison usuels.

    Exemple : "j'ai une montre casio" -> ["montre", "casio"]
    """
    tokens = tokenize(raw_text)
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

    # 3) Repli sur un correcteur orthographique français généraliste
    if HAS_SPELLCHECKER:
        try:
            spell = SpellChecker(language="fr")
            if word_l not in spell:
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




import os
import re
import time
from dataclasses import dataclass
from typing import List, Optional
from urllib.parse import quote_plus, urljoin

import requests
from bs4 import BeautifulSoup






@dataclass
class Produit:
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


def scrape_with_requests(query: str, max_items: int = 10) -> List[Produit]:
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


def scrape_with_selenium(query: str, max_items: int = 10) -> List[Produit]:
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


def scrape_jumia_images(query: str, max_items: int = 10) -> List[Produit]:
    """
    Point d'entrée principal du scraping : essaie d'abord requests,
    puis bascule automatiquement sur Selenium si rien n'est trouvé.
    """
    produits = scrape_with_requests(query, max_items=max_items)
    if not produits:
        print("[i] Aucun résultat via requests seul, tentative avec "
              "un navigateur headless (Selenium)...")
        produits = scrape_with_selenium(query, max_items=max_items)
    return produits



def download_images(produits: List[Produit], dossier: str = "images_jumia"):
    os.makedirs(dossier, exist_ok=True)
    compteur = 0
    for produit in produits:
        for img_url in produit.images:
            try:
                resp = requests.get(img_url, headers=HEADERS, timeout=15)
                resp.raise_for_status()
                ext = os.path.splitext(img_url.split("?")[0])[1] or ".jpg"
                nom_fichier = re.sub(r"[^a-zA-Z0-9_-]", "_", produit.nom)[:50]
                chemin = os.path.join(dossier, f"{nom_fichier}_{compteur}{ext}")
                with open(chemin, "wb") as f:
                    f.write(resp.content)
                print(f"  ✓ Image téléchargée : {chemin}")
                compteur += 1
            except requests.RequestException as e:
                print(f"  ✗ Échec du téléchargement de {img_url} : {e}")


import argparse

def run(raw_text: str, max_items: int = 10, do_download: bool = False):
    # Étape 1 : compréhension + correction orthographique
    suggestions, corrected_query = understand_and_correct(raw_text)
    print_understanding_report(raw_text, suggestions)
    print(f"Requête envoyée à Jumia : '{corrected_query}'\n")

    # Étape 2 : scraping
    produits = scrape_jumia_images(corrected_query, max_items=max_items)

    if not produits:
        print("Aucun produit/image trouvé. Le site a peut-être changé de "
              "structure HTML, ou bloque les requêtes automatiques.\n"
              "Essayez d'installer selenium + webdriver-manager pour le "
              "mode de secours, ou vérifiez l'URL générée manuellement :")
        print(" ", build_search_url(corrected_query))
        return produits

    print(f"{len(produits)} produit(s) trouvé(s) :\n")
    for i, p in enumerate(produits, 1):
        print(f"{i}. {p.nom}")
        print(f"   Lien   : {p.lien}")
        print(f"   Images : {p.images}")
        print()

    if do_download:
        print("Téléchargement des images...")
        download_images(produits)

    return produits


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Trouve des images d'articles sur Jumia CI à partir "
                    "d'une phrase en français (avec correction des fautes)."
    )
    parser.add_argument(
        "phrase", nargs="*",
        help="Phrase décrivant l'article, ex: \"j'ai une motre casio\""
    )
    parser.add_argument("--max", type=int, default=10, help="Nombre max de produits")
    parser.add_argument("--download", action="store_true", help="Télécharger les images trouvées")
    args = parser.parse_args()

    if args.phrase:
        texte = " ".join(args.phrase)
    else:
        texte = input("Décrivez l'article recherché : ")

    # Demande du nombre d'images souhaité
    while True:
        try:
            max_items = int(input("Combien d'images souhaitez-vous récupérer ? (1 à 50) : "))
            if 1 <= max_items <= 50:
                break
            print("Veuillez saisir un nombre compris entre 1 et 50.")
        except ValueError:
            print("Veuillez saisir un nombre valide.")

    run(texte, max_items=max_items, do_download=args.download)
    