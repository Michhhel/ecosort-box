# -*- coding: utf-8 -*-
"""
EcoSort-Search - Evaluation finale du modele sur le jeu de test
================================================================
Le jeu de test (data/processed/test/) contient 302 images que le modele
n'a JAMAIS vues, ni pour apprendre, ni pour se surveiller. C'est son
examen final : le resultat obtenu ici est la performance "officielle"
qu'on peut annoncer.

Ce script produit :
  1. La precision globale sur le test.
  2. Un rapport detaille PAR CLASSE (precision, rappel, f1-score)
     -> indispensable avec des classes desequilibrees comme "trash".
  3. La matrice de confusion (image PNG) : ce que le modele confond
     avec quoi.

Usage (depuis la racine du projet, environnement virtuel active) :
    python ml_model/entrainement/evaluate_model.py
"""

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import tensorflow as tf
from tensorflow import keras
from sklearn.metrics import classification_report, confusion_matrix

# ---------------------------------------------------------------------------
# 1. PARAMETRES ET CHARGEMENTS
# ---------------------------------------------------------------------------

RACINE = Path(__file__).resolve().parent.parent.parent   # racine du depot
DOSSIER_TEST = RACINE / "data" / "processed" / "test"
DOSSIER_SORTIE = Path(__file__).resolve().parent          # graphiques
DOSSIER_MODELE = DOSSIER_SORTIE.parent                     # ml_model/ (modele + classes)

TAILLE_IMAGE = (224, 224)
TAILLE_LOT = 32

print(">>> Chargement du modele et des classes...")
modele = keras.models.load_model(DOSSIER_MODELE / "modele_eco_sort.h5")
with open(DOSSIER_MODELE / "classes.json", encoding="utf-8") as f:
    NOMS_CLASSES = json.load(f)

print(">>> Chargement du jeu de test...")
# shuffle=False : l'ordre des images doit rester fixe pour pouvoir
# comparer chaque prediction a la bonne reponse correspondante.
jeu_test = keras.utils.image_dataset_from_directory(
    DOSSIER_TEST,
    image_size=TAILLE_IMAGE,
    batch_size=TAILLE_LOT,
    shuffle=False,
)
assert jeu_test.class_names == NOMS_CLASSES, (
    "L'ordre des classes du test ne correspond pas a classes.json !")

# ---------------------------------------------------------------------------
# 2. PREDICTIONS SUR LES 302 IMAGES DE TEST
# ---------------------------------------------------------------------------

print(">>> Predictions en cours...")
probabilites = modele.predict(jeu_test, verbose=1)
# Pour chaque image, le modele donne 7 probabilites ;
# argmax = l'indice de la plus forte = la classe predite.
predictions = np.argmax(probabilites, axis=1)

# Les bonnes reponses, dans le meme ordre que les predictions
vraies_classes = np.concatenate([y.numpy() for _, y in jeu_test])

# ---------------------------------------------------------------------------
# 3. RESULTATS
# ---------------------------------------------------------------------------

precision_globale = float(np.mean(predictions == vraies_classes))
print(f"\n===== PRECISION GLOBALE SUR LE TEST : {precision_globale:.1%} =====\n")

# Rapport par classe :
#  - precision : quand le modele dit "glass", a-t-il raison ?
#  - rappel (recall) : parmi les vrais "glass", combien retrouve-t-il ?
#  - f1-score : moyenne equilibree des deux (la note de la classe)
print(classification_report(
    vraies_classes, predictions, target_names=NOMS_CLASSES, digits=2))

# ---------------------------------------------------------------------------
# 4. MATRICE DE CONFUSION
# ---------------------------------------------------------------------------
# Lecture : chaque LIGNE est la vraie classe, chaque COLONNE la prediction.
# La diagonale = les bonnes reponses. Tout ce qui est hors diagonale
# est une confusion (ex : ligne "glass", colonne "plastic" = des verres
# pris pour du plastique).

matrice = confusion_matrix(vraies_classes, predictions)

fig, ax = plt.subplots(figsize=(8, 7))
im = ax.imshow(matrice, cmap="Blues")
ax.set_xticks(range(len(NOMS_CLASSES)))
ax.set_yticks(range(len(NOMS_CLASSES)))
ax.set_xticklabels(NOMS_CLASSES, rotation=45, ha="right")
ax.set_yticklabels(NOMS_CLASSES)
ax.set_xlabel("Classe predite par le modele")
ax.set_ylabel("Vraie classe")
ax.set_title(f"Matrice de confusion - test ({precision_globale:.1%} global)")
# Ecrit le nombre dans chaque case
for i in range(len(NOMS_CLASSES)):
    for j in range(len(NOMS_CLASSES)):
        couleur = "white" if matrice[i, j] > matrice.max() / 2 else "black"
        ax.text(j, i, matrice[i, j], ha="center", va="center", color=couleur)
fig.colorbar(im, shrink=0.8)
fig.tight_layout()
chemin_matrice = DOSSIER_SORTIE / "matrice_confusion.png"
fig.savefig(chemin_matrice, dpi=120)
print(f"Matrice de confusion sauvegardee : {chemin_matrice}")
