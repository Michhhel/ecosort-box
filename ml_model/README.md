# ml_model — Partie Deep Learning

Auteur : **CISSE Aly** — branche `ml`

Ce package fournit le vrai modèle de classification (remplace le mock initial,
**contrat public inchangé** : `charger_modele()` + `predire_categorie(image_bytes)`,
avec la clé `probabilites` agrégée par catégorie, utilisée par `feedback.py`).

## Contenu

| Fichier | Rôle |
| :--- | :--- |
| `classifier.py` | Module d'inférence appelé par la webapp (contrat du mock respecté) |
| `modele_eco_sort.h5` | Modèle entraîné (MobileNetV2, 7 classes) — 22 Mo, livrable Docker |
| `classes.json` | Ordre des 7 classes du modèle |
| `feedback.py` | (coéquipier web) Collecte filtrée des retours utilisateurs |
| `entrainement/` | Scripts reproductibles : préparation, entraînement, évaluation |

## Modèle

- **Transfer Learning MobileNetV2** en 2 phases (tête de décision, puis
  fine-tuning des 40 dernières couches).
- **7 classes** : cardboard, glass, metal, paper, plastic, trash
  ([Garbage Classification](https://www.kaggle.com/datasets/asdasdasasdas/garbage-classification))
  \+ `electronic` (~500 images sous-échantillonnées du dataset
  [E-Waste](https://www.kaggle.com/datasets/akshat103/e-waste-image-dataset)).
- Déséquilibre corrigé par poids de classe ; découpage reproductible 80/10/10.

### Résultats (jeu de test : 302 images jamais vues)

| Version | Configuration | Précision test |
| :--- | :--- | :--- |
| v1 | base gelée | 86,4 % |
| **v2** | **fine-tuning 40 couches** | **87,7 %** ✅ retenue |
| v3 | fine-tuning 100 couches | 85,4 % (sur-apprentissage) |

`electronic` : 100 %. Point faible connu : `trash` (f1 0,58 — classe hétérogène,
137 images seulement dans le dataset source). Voir `entrainement/matrice_confusion.png`.

## Reproduire l'entraînement

```bash
# 1. Télécharger les 2 datasets Kaggle (liens ci-dessus), les dézipper dans :
#    data/raw/garbage_tmp/  et  data/raw/ewaste_tmp/   (racine du dépôt)
python ml_model/entrainement/prepare_data.py
python ml_model/entrainement/train_model.py     # régénère ml_model/modele_eco_sort.h5
python ml_model/entrainement/evaluate_model.py
```

## Prédiction 7 matières → 5 poubelles

Le modèle prédit une **matière** ; `classifier.py` agrège les probabilités par
catégorie officielle : plastic/metal/cardboard → jaune, glass → verte,
paper → bleue, electronic → grise (D3E), trash → marron. La détection D3E par
**mots-clés sur le nom du produit** (exigée par le sujet) reste à appliquer
côté webapp/scraper AVANT l'appel au modèle, en filet de sécurité.
