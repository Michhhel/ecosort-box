# -*- coding: utf-8 -*-
"""
EcoSort-Search - Preparation des donnees d'entrainement
========================================================
Ce script fusionne les deux datasets Kaggle et construit le dossier
data/processed/ pret pour l'entrainement :

  1. Les 6 classes du dataset "Garbage Classification" sont reprises
     telles quelles : cardboard, glass, metal, paper, plastic, trash.
  2. Une 7e classe "electronic" est creee a partir du dataset E-Waste :
     on tire au hasard IMAGES_PAR_CATEGORIE_EWASTE images dans chacune
     des 10 categories (piles, claviers, telephones...) pour obtenir
     ~500 images variees SANS desequilibrer le dataset final
     (sous-echantillonnage).
  3. Chaque classe est ensuite decoupee en 3 jeux :
     - train (80%) : les images sur lesquelles le modele apprend
     - val   (10%) : pour surveiller l'apprentissage a chaque epoque
     - test  (10%) : mis de cote, utilise UNE SEULE FOIS a la fin
       pour mesurer la performance reelle du modele.

Reproductibilite : le tirage aleatoire est fixe par GRAINE_ALEATOIRE.
Relancer le script produit exactement le meme decoupage.

Usage (depuis la racine du projet, environnement virtuel active) :
    python ml_model/entrainement/prepare_data.py
Option :
    --reprendre   termine une copie interrompue sans repartir de zero
"""

import random
import shutil
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# 1. PARAMETRES (tout ce qui est reglable est ici, en haut du fichier)
# ---------------------------------------------------------------------------

GRAINE_ALEATOIRE = 42          # fige le hasard -> resultats reproductibles

RACINE = Path(__file__).resolve().parent.parent.parent   # racine du depot
DOSSIER_GARBAGE = RACINE / "data" / "raw" / "garbage_tmp" / "Garbage classification" / "Garbage classification"
DOSSIER_EWASTE = RACINE / "data" / "raw" / "ewaste_tmp" / "modified-dataset"
DOSSIER_SORTIE = RACINE / "data" / "processed"

PART_VALIDATION = 0.10         # 10% des images pour la validation
PART_TEST = 0.10               # 10% des images pour le test final

IMAGES_PAR_CATEGORIE_EWASTE = 50   # 50 x 10 categories = 500 images "electronic"

CLASSES_GARBAGE = ["cardboard", "glass", "metal", "paper", "plastic", "trash"]
NOM_CLASSE_ELECTRONIQUE = "electronic"


# ---------------------------------------------------------------------------
# 2. FONCTIONS
# ---------------------------------------------------------------------------

def lister_images(dossier: Path) -> list:
    """Retourne la liste triee des images d'un dossier.
    Le tri est important : il garantit le meme ordre sur tous les PC,
    donc le meme tirage aleatoire (reproductibilite)."""
    extensions = {".jpg", ".jpeg", ".png"}
    return sorted(p for p in dossier.iterdir() if p.suffix.lower() in extensions)


def decouper(images: list) -> dict:
    """Melange une liste d'images puis la decoupe en train/val/test."""
    images = images.copy()
    random.shuffle(images)
    n = len(images)
    n_val = round(n * PART_VALIDATION)
    n_test = round(n * PART_TEST)
    return {
        "test": images[:n_test],
        "val": images[n_test:n_test + n_val],
        "train": images[n_test + n_val:],
    }


def copier(images_par_jeu: dict, nom_classe: str) -> None:
    """Copie les images vers data/processed/<jeu>/<classe>/."""
    for jeu, images in images_par_jeu.items():
        destination = DOSSIER_SORTIE / jeu / nom_classe
        destination.mkdir(parents=True, exist_ok=True)
        for src in images:
            # Prefixer par la classe evite les collisions de noms
            cible = destination / f"{nom_classe}_{src.name}"
            if not cible.exists():   # permet de reprendre une copie interrompue
                shutil.copy2(src, cible)


# ---------------------------------------------------------------------------
# 3. PROGRAMME PRINCIPAL
# ---------------------------------------------------------------------------

def main() -> None:
    random.seed(GRAINE_ALEATOIRE)

    # Securite : on repart d'un dossier vide, SAUF si on relance le script
    # avec l'option --reprendre pour terminer une copie interrompue
    # (le tirage aleatoire etant fige par la graine, le decoupage est identique).
    if DOSSIER_SORTIE.exists() and "--reprendre" not in sys.argv:
        shutil.rmtree(DOSSIER_SORTIE)

    # --- Les 6 classes de matieres -----------------------------------------
    for classe in CLASSES_GARBAGE:
        images = lister_images(DOSSIER_GARBAGE / classe)
        copier(decouper(images), classe)
        print(f"{classe:<12} : {len(images)} images")

    # --- La classe "electronic" (sous-echantillonnage du E-Waste) ----------
    selection = []
    dossier_train = DOSSIER_EWASTE / "train"
    for dossier_categorie in sorted(dossier_train.iterdir()):
        if not dossier_categorie.is_dir():
            continue
        images_categorie = lister_images(dossier_categorie)
        tirage = random.sample(images_categorie, IMAGES_PAR_CATEGORIE_EWASTE)
        selection.extend(tirage)

    copier(decouper(selection), NOM_CLASSE_ELECTRONIQUE)
    print(f"{NOM_CLASSE_ELECTRONIQUE:<12} : {len(selection)} images "
          f"(tirees du dataset E-Waste)")

    # --- Bilan --------------------------------------------------------------
    print("\nBilan du decoupage :")
    for jeu in ["train", "val", "test"]:
        total = sum(1 for f in (DOSSIER_SORTIE / jeu).rglob("*") if f.is_file())
        print(f"  {jeu:<6}: {total} images")
    print(f"\nDonnees pretes dans : {DOSSIER_SORTIE}")


if __name__ == "__main__":
    main()
