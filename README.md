# ♻️ EcoSort-BOX

Application web d'aide au tri sélectif : l'utilisateur cherche un produit (ou envoie sa propre photo), le sélectionne parmi les résultats Jumia, et l'IA lui indique la bonne poubelle — l'écran se colore aux couleurs de la consigne. Il peut ensuite confirmer ou contester le verdict pour aider le modèle à s'améliorer.

Interface façon chat (Django + JavaScript vanilla) avec trois thèmes d'affichage (jour, nuit, dégradé de gris), **scraping Jumia en direct** et **classification par deep learning (MobileNetV2)** intégrés en modules Python internes.

**Équipe** — chaque module a son responsable et sa branche : partie web (`web`), scraping Jumia (`scraper`), deep learning (`ml` / `Cisse_Aly`).

## Lancer l'application

Avec Docker (recommandé — c'est le mode d'évaluation) :

```bash
docker build -t ecosort . && docker run -p 8501:8501 ecosort
```

ou

```bash
docker-compose up -d --build
```

puis ouvrir **http://localhost:8501**.

En développement local, sans Docker :

```bash
python -m venv .venv && source .venv/bin/activate   # Windows : .venv\Scripts\activate
pip install -r requirements.txt
python manage.py collectstatic --noinput             # fichiers statiques (une fois)
DEBUG=1 python manage.py runserver                   # -> http://127.0.0.1:8000
```

## Fonctionnalités de l'interface

- **Trois thèmes** (sélecteur dans l'en-tête, mémorisé dans le navigateur) : jour ☀️, nuit 🌙, dégradé de gris ◐. Les 5 couleurs de poubelles restent identiques dans tous les thèmes : la couleur est l'information.
- **Recherche Jumia en direct** avec carousel de 3 à 5 produits, et bouton **« Voir d'autres produits »** si aucun ne correspond (pagination du scraping).
- **Photo personnelle** : bouton appareil photo dans la barre de saisie (et sous chaque carousel) pour analyser une image de la galerie / des fichiers, sans passer par la recherche.
- **Verdict coloré** plein écran avec niveau de confiance + **retour utilisateur** : 👍 confirme la prédiction, 👎 permet de proposer la bonne poubelle (voir « Amélioration du modèle » plus bas).

## Les trois modules réels

### `scraper/` — recherche Jumia en direct

Interroge le moteur de recherche de Jumia (requests + BeautifulSoup) à partir du mot-clé saisi, avec **compréhension du texte** en amont : nettoyage de la phrase (« j'ai une bouteille à jeter » → « bouteille »), correction orthographique (« motre » → « montre ») via un vocabulaire métier (rapidfuzz + pyspellchecker). Renvoie 3 à 5 produits (titre, image, lien) avec pagination. Un repli Selenium est prévu pour le contenu rendu en JavaScript (optionnel, absent de l'image Docker : le scraper bascule proprement sur une liste vide).

### `ml_model/` — classification deep learning

Modèle **MobileNetV2 en Transfer Learning** (2 phases : tête de décision, puis fine-tuning des 40 dernières couches), entraîné sur **7 classes** : les 6 matières du dataset Kaggle [Garbage Classification](https://www.kaggle.com/datasets/asdasdasasdas/garbage-classification) + une classe `electronic` construite à partir du dataset [E-Waste](https://www.kaggle.com/datasets/akshat103/e-waste-image-dataset) (sous-échantillonnage équilibré). Déséquilibre corrigé par poids de classe ; découpage reproductible 80/10/10.

**Résultats sur le jeu de test (302 images jamais vues) : 87,7 %** de précision — `electronic` 100 %, `cardboard` f1 0,94, `paper` f1 0,91 ; point faible connu : `trash` (f1 0,58, classe hétérogène de 137 images dans le dataset source). Détails, matrice de confusion et comparaison des configurations (v1/v2/v3) dans `ml_model/README.md`.

Le modèle prédit une **matière** ; `classifier.py` agrège les probabilités par catégorie officielle du sujet : plastic/metal/cardboard → jaune, glass → verte, paper → bleue, electronic → grise (D3E), trash → marron. Les scripts d'entraînement reproductibles (préparation des données, entraînement, évaluation) sont dans `ml_model/entrainement/`.

Le modèle entraîné `ml_model/modele_eco_sort.h5` (22 Mo) **est inclus dans le dépôt** via une exception ciblée du `.gitignore` : le Dockerfile fait `COPY . .`, l'évaluateur doit pouvoir cloner puis construire sans étape manuelle. La règle `*.h5` continue de bloquer tout autre modèle d'expérimentation.

### `webapp/` — interface et API

Vues Django classiques (pas de base de données) : c'est la vue qui télécharge l'image du produit depuis Jumia (`webapp/utils.py`) — le module IA reçoit des octets, il ne fait aucun réseau. Le modèle est chargé **une seule fois** au démarrage du serveur (`webapp/apps.py` → `ready()`).

## Amélioration du modèle au fil des utilisations

Réentraîner un CNN « en direct » à chaque clic serait dangereux (oubli catastrophique, vandalisme). Le projet suit donc le schéma standard **human-in-the-loop** :

1. **Collecte** : après chaque verdict, l'utilisateur confirme (👍) ou conteste (👎) en proposant la bonne poubelle.
2. **Filtrage anti-vandalisme** (`ml_model/feedback.py`) : une correction n'est marquée `acceptee` que si le modèle donnait lui-même une probabilité **≥ 0,15** à la poubelle proposée (avec 5 classes, le hasard vaut 0,20 : à 0,15 le modèle hésitait réellement). Si le modèle était quasi certain (confiance **≥ 0,95**), la correction est archivée `rejetee` pour revue humaine — jamais acceptée automatiquement. Le garde-fou s'appuie sur la clé `probabilites` renvoyée par le classifieur (sortie softmax agrégée par catégorie).
3. **Archivage** : image + métadonnées dans `var/feedback/` (`feedback.jsonl` + `images/`). Tout est conservé, y compris les rejets.
4. **Réentraînement périodique** : les entrées `acceptee` (et `confirmee` comme exemples positifs) pourront alimenter un affinage du modèle via les scripts de `ml_model/entrainement/`, qui régénèrent `modele_eco_sort.h5`.

Les seuils (0,15 et 0,95) sont des constantes documentées dans `ml_model/feedback.py`, à ajuster en équipe si besoin.

## Contrats internes des modules

La vue Django ne dépend que de ces signatures publiques :

**`scraper/jumia_scraper.py`** :

```python
def rechercher_produits(mot_cle: str, page: int = 1) -> list[dict]:
    # 3 à 5 éléments : {"titre": str, "image_url": str, "produit_url": str}
    # liste vide si aucun résultat ; page=2, 3... pour « Voir d'autres produits »
```

**`ml_model/classifier.py`** :

```python
def charger_modele() -> None:
    # idempotent ; appelé UNE fois au démarrage (webapp/apps.py -> ready())

def predire_categorie(image_bytes: bytes) -> dict:
    # {"categorie": str, "couleur": str, "detail": str, "confiance": float,
    #  "probabilites": {slug: float}}   # sortie softmax agrégée par catégorie
    # "couleur" ∈ {"jaune", "verte", "bleue", "grise", "marron"}
```

## API interne

`POST /api/search` — entrée `{"mot_cle": str, "page": int (optionnel, défaut 1)}` → sortie `{"resultats": [{"titre", "image_url", "produit_url"}, ...], "page": int}` (liste éventuellement vide). Erreurs : `{"erreur": str}` avec statut 400/502.

`POST /api/classify` — deux modes d'entrée : JSON `{"image_url": str}` (produit du carousel) **ou** multipart `image_file` (photo de l'utilisateur). Sortie `{"categorie", "couleur", "confiance", "detail", "prediction_id"}`. Erreurs : `{"erreur": str}` avec statut 400/500/502.

`POST /api/feedback` — entrée `{"prediction_id": str, "correcte": bool, "couleur_correcte": str (si correcte=false)}` → sortie `{"statut": "confirmee"|"acceptee"|"rejetee", "message": str}`. Erreurs : 400 (poubelle invalide), 404 (prédiction expirée), 500.

## Structure

```
ecosort-box/
├── config/                  # settings, urls, wsgi (pas de base de données)
├── webapp/                  # app Django : vues, template, static (JS/CSS)
│   └── predictions.py       # registre en mémoire des prédictions récentes (feedback)
├── scraper/                 # scraping Jumia en direct + compréhension du texte
├── ml_model/                # classification deep learning (module réel)
│   ├── classifier.py        # inférence : predire_categorie(image_bytes)
│   ├── modele_eco_sort.h5   # modèle entraîné (MobileNetV2, 7 classes) — livrable
│   ├── classes.json         # ordre des classes du modèle
│   ├── feedback.py          # seuils d'acceptation + archivage des retours
│   ├── entrainement/        # scripts reproductibles : préparation, entraînement, évaluation
│   └── README.md            # documentation détaillée de la partie IA
├── var/feedback/            # créé à l'exécution : feedback.jsonl + images/ (gitignoré)
├── requirements.txt
├── Dockerfile               # gunicorn sur :8501, 1 worker (modèle chargé une seule fois)
├── docker-compose.yml
└── README.md
```

## Règles d'équipe

Aucun push direct sur `main` : chaque contribution passe par une **Pull Request** relue et validée par au moins un coéquipier, chacun travaillant sur sa branche. Le dataset Kaggle (`data/`, `*.zip`), les environnements virtuels, le dossier `var/` et les fichiers `.h5` ne sont jamais commités (voir `.gitignore`) — à l'exception du modèle final `ml_model/modele_eco_sort.h5`, livrable nécessaire au `docker build`.

Pour reproduire l'entraînement du modèle : voir `ml_model/README.md` (datasets à décompresser dans `data/` à la racine, puis les trois scripts de `ml_model/entrainement/`).
