# -*- coding: utf-8 -*-
"""
Entrainement du modele de classification (Transfer Learning)
==============================================================================
Ce script entraine un reseau de neurones a reconnaitre 7 classes de dechets :
cardboard, electronic, glass, metal, paper, plastic, trash.

Strategie : Transfer Learning avec MobileNetV2, en deux phases.
  - PHASE 1 : MobileNetV2 (pre-entraine par Google sur 1,4 million d'images)
    est entierement GELE ; seule la petite "tete de decision" a 7 sorties
    apprend.
  - PHASE 2 (fine-tuning) : les dernieres couches de la base sont degelees
    et re-entrainees tres doucement pour s'adapter aux textures specifiques
    de nos dechets.

Prerequis : avoir lance prepare_data.py (dossier data/processed/ pret).

Usage (depuis la racine du projet, environnement virtuel active) :
    python ml_model/entrainement/train_model.py

Sorties :
    ml_model/entrainement/modele_eco_sort.h5        le modele entraine (livrable)
    ml_model/entrainement/classes.json              l'ordre des classes du modele
    ml_model/entrainement/courbes_entrainement.png  les courbes d'apprentissage
"""

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")           # trace les graphiques sans ouvrir de fenetre
import matplotlib.pyplot as plt
import tensorflow as tf
from tensorflow import keras
from tensorflow.keras import layers

# ---------------------------------------------------------------------------
# 1. PARAMETRES
# ---------------------------------------------------------------------------

GRAINE_ALEATOIRE = 42

RACINE = Path(__file__).resolve().parent.parent.parent   # racine du depot
DOSSIER_TRAIN = RACINE / "data" / "processed" / "train"
DOSSIER_VAL = RACINE / "data" / "processed" / "val"
DOSSIER_SORTIE = Path(__file__).resolve().parent          # graphiques
DOSSIER_MODELE = DOSSIER_SORTIE.parent                     # ml_model/ (modele + classes)

TAILLE_IMAGE = (224, 224)   # taille d'entree attendue par MobileNetV2
TAILLE_LOT = 32             # nombre d'images traitees a la fois (batch)
NB_EPOQUES_MAX = 15         # nombre maximum de passages (phase 1)
NB_EPOQUES_FINETUNING = 8   # nombre maximum de passages (phase 2)
NB_COUCHES_DEGELEES = 40    # couches de la base a re-entrainer en phase 2

# ---------------------------------------------------------------------------
# 2. CHARGEMENT DES DONNEES
# ---------------------------------------------------------------------------
# Keras lit directement notre arborescence data/processed/<jeu>/<classe>/
# et en deduit les etiquettes a partir des noms de dossiers.

print(">>> Chargement des donnees...")

jeu_train = keras.utils.image_dataset_from_directory(
    DOSSIER_TRAIN,
    image_size=TAILLE_IMAGE,
    batch_size=TAILLE_LOT,
    seed=GRAINE_ALEATOIRE,
    shuffle=True,
)
jeu_val = keras.utils.image_dataset_from_directory(
    DOSSIER_VAL,
    image_size=TAILLE_IMAGE,
    batch_size=TAILLE_LOT,
    shuffle=False,
)

NOMS_CLASSES = jeu_train.class_names   # ordre alphabetique des dossiers
print("Classes :", NOMS_CLASSES)

# Optimisation : precharge les images en memoire tampon pendant le calcul
jeu_train = jeu_train.prefetch(tf.data.AUTOTUNE)
jeu_val = jeu_val.prefetch(tf.data.AUTOTUNE)

# ---------------------------------------------------------------------------
# 3. POIDS DE CLASSE (correction du desequilibre)
# ---------------------------------------------------------------------------
# La classe "trash" n'a que ~109 images d'entrainement contre ~476 pour
# "paper". Sans correction, le modele apprendrait a la negliger.
# Regle classique : poids = total / (nb_classes * effectif_classe).
# -> une erreur sur une classe rare coute plus cher qu'une erreur
#    sur une classe abondante.

effectifs = {}
for i, classe in enumerate(NOMS_CLASSES):
    effectifs[i] = len(list((DOSSIER_TRAIN / classe).glob("*")))
total = sum(effectifs.values())
poids_de_classe = {
    i: total / (len(NOMS_CLASSES) * n) for i, n in effectifs.items()
}
print("Poids de classe :",
      {NOMS_CLASSES[i]: round(p, 2) for i, p in poids_de_classe.items()})

# ---------------------------------------------------------------------------
# 4. CONSTRUCTION DU MODELE
# ---------------------------------------------------------------------------

print(">>> Construction du modele (telechargement des poids MobileNetV2"
      " ~14 Mo au premier lancement)...")

# L'augmentation de donnees : petites transformations aleatoires appliquees
# uniquement pendant l'entrainement. Le modele ne voit jamais deux fois
# exactement la meme image -> il generalise au lieu de memoriser.
augmentation = keras.Sequential([
    layers.RandomFlip("horizontal"),
    layers.RandomRotation(0.10),
    layers.RandomZoom(0.10),
], name="augmentation")

# La base MobileNetV2 pre-entrainee, sans sa derniere couche (include_top=False)
base = keras.applications.MobileNetV2(
    input_shape=TAILLE_IMAGE + (3,),
    include_top=False,
    weights="imagenet",
)
base.trainable = False   # on GELE tout le savoir-faire visuel de Google

entrees = keras.Input(shape=TAILLE_IMAGE + (3,))
x = augmentation(entrees)
# MobileNetV2 attend des pixels entre -1 et 1 (les notres sont entre 0 et 255)
x = layers.Rescaling(1.0 / 127.5, offset=-1)(x)
x = base(x, training=False)
x = layers.GlobalAveragePooling2D()(x)     # resume chaque image en 1280 nombres
x = layers.Dropout(0.2)(x)                 # anti-memorisation supplementaire
sorties = layers.Dense(len(NOMS_CLASSES), activation="softmax")(x)
# softmax -> le modele repond par 7 probabilites qui totalisent 100%

modele = keras.Model(entrees, sorties)
modele.compile(
    optimizer=keras.optimizers.Adam(learning_rate=1e-3),
    loss="sparse_categorical_crossentropy",
    metrics=["accuracy"],
)
modele.summary()

# ---------------------------------------------------------------------------
# 5. ENTRAINEMENT - PHASE 1 (base gelee)
# ---------------------------------------------------------------------------
# EarlyStopping : si la performance en validation ne progresse plus pendant
# 3 epoques d'affilee, on arrete et on garde la meilleure version rencontree.

arret_anticipe = keras.callbacks.EarlyStopping(
    monitor="val_accuracy",
    patience=3,
    restore_best_weights=True,
    verbose=1,
)

print(">>> PHASE 1 : entrainement de la tete de decision (base gelee)...")
historique = modele.fit(
    jeu_train,
    validation_data=jeu_val,
    epochs=NB_EPOQUES_MAX,
    class_weight=poids_de_classe,
    callbacks=[arret_anticipe],
)

# ---------------------------------------------------------------------------
# 5bis. PHASE 2 : FINE-TUNING
# ---------------------------------------------------------------------------
# On degele les dernieres couches de MobileNetV2 (les plus specialisees)
# pour les adapter aux textures propres a NOS dechets. Deux precautions :
#   - taux d'apprentissage divise par 100 (1e-5) : on AFFINE, on ne casse pas
#     le savoir-faire pre-appris ;
#   - seules les NB_COUCHES_DEGELEES dernieres couches apprennent, les
#     premieres (bords, textures universelles) restent gelees.

print(f">>> PHASE 2 : fine-tuning des {NB_COUCHES_DEGELEES} dernieres"
      " couches de la base...")

base.trainable = True
for couche in base.layers[:-NB_COUCHES_DEGELEES]:
    couche.trainable = False

# Recompiler est OBLIGATOIRE apres un changement de trainable
modele.compile(
    optimizer=keras.optimizers.Adam(learning_rate=1e-5),
    loss="sparse_categorical_crossentropy",
    metrics=["accuracy"],
)

arret_anticipe_2 = keras.callbacks.EarlyStopping(
    monitor="val_accuracy",
    patience=3,
    restore_best_weights=True,
    verbose=1,
)

historique_2 = modele.fit(
    jeu_train,
    validation_data=jeu_val,
    epochs=NB_EPOQUES_FINETUNING,
    class_weight=poids_de_classe,
    callbacks=[arret_anticipe_2],
)

# Fusionne les historiques des deux phases pour les courbes
hist = {
    cle: historique.history[cle] + historique_2.history[cle]
    for cle in historique.history
}

# ---------------------------------------------------------------------------
# 6. SAUVEGARDES (les livrables)
# ---------------------------------------------------------------------------

chemin_modele = DOSSIER_MODELE / "modele_eco_sort.h5"
modele.save(chemin_modele)
print(f"Modele sauvegarde : {chemin_modele}")

with open(DOSSIER_MODELE / "classes.json", "w", encoding="utf-8") as f:
    json.dump(NOMS_CLASSES, f)
print("Ordre des classes sauvegarde : classes.json")

# Courbes d'apprentissage : precision et erreur, en train et en validation
# La ligne verticale marque le debut de la phase 2 (fine-tuning)
debut_phase2 = len(historique.history["accuracy"])
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4))
ax1.plot(hist["accuracy"], label="entrainement")
ax1.plot(hist["val_accuracy"], label="validation")
ax1.axvline(debut_phase2 - 0.5, color="gray", linestyle="--", label="fine-tuning")
ax1.set_title("Precision (accuracy)")
ax1.set_xlabel("epoque")
ax1.legend()
ax2.plot(hist["loss"], label="entrainement")
ax2.plot(hist["val_loss"], label="validation")
ax2.axvline(debut_phase2 - 0.5, color="gray", linestyle="--", label="fine-tuning")
ax2.set_title("Erreur (loss)")
ax2.set_xlabel("epoque")
ax2.legend()
fig.tight_layout()
fig.savefig(DOSSIER_SORTIE / "courbes_entrainement.png", dpi=120)
print("Courbes sauvegardees : courbes_entrainement.png")

print("\nTermine ! Meilleure precision en validation : "
      f"{max(hist['val_accuracy']):.1%}")
