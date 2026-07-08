# ♻️ EcoSort-BOX

Application web d'aide au tri sélectif : l'utilisateur cherche un produit (ou envoie sa propre photo), le sélectionne parmi les résultats Jumia, et l'IA lui indique la bonne poubelle — l'écran se colore aux couleurs de la consigne. Il peut ensuite confirmer ou contester le verdict pour aider le modèle à s'améliorer.

Interface façon chat (Django + JavaScript vanilla) avec trois thèmes d'affichage (jour, nuit, dégradé de gris), scraping Jumia et classification deep learning intégrés en modules Python internes.

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
DEBUG=1 python manage.py runserver                   # -> http://127.0.0.1:8000
```

## Fonctionnalités de l'interface

- **Trois thèmes** (sélecteur dans l'en-tête, mémorisé dans le navigateur) : jour ☀️, nuit 🌙, dégradé de gris ◐. Les 5 couleurs de poubelles restent identiques dans tous les thèmes : la couleur est l'information.
- **Recherche Jumia** avec carousel de 3 à 5 produits, et bouton **« Voir d'autres produits »** si aucun ne correspond (pagination du scraping).
- **Photo personnelle** : bouton appareil photo dans la barre de saisie (et sous chaque carousel) pour analyser une image de la galerie / des fichiers, sans passer par la recherche.
- **Verdict coloré** plein écran + **retour utilisateur** : 👍 confirme la prédiction, 👎 permet de proposer la bonne poubelle (voir « Amélioration du modèle » plus bas).
- **Logo maison** : `webapp/static/webapp/img/v1.png` (déposer le fichier ; repli automatique sur la pastille ♻ s'il est absent).

## État actuel : modules simulés (mock)

Les modules `scraper/` et `ml_model/` sont pour l'instant des **bouchons** qui respectent strictement les contrats d'équipe. La partie web est donc développable et testable de bout en bout, hors-ligne.

Mots-clés utiles pour la démo et les tests :

| Mot-clé | Comportement simulé |
| --- | --- |
| `bouteille`, `canette`, `confiture`, `journal`, `écouteurs`, `sachet`, `carton`… | résultats ciblés et verdict cohérent |
| n'importe quel autre mot | sélection générique de 4 produits |
| `introuvable` (ou `aucun`, `rien`) | **liste vide** — teste le message « aucun résultat » |
| `erreur` | **panne simulée du scraper** — teste la gestion d'erreur |
| bouton « Voir d'autres produits » | pages suivantes du catalogue, puis épuisement |

La confiance du mock varie entre ~70 % et ~97 %, ce qui permet de tester les trois issues d'un signalement d'erreur (correction acceptée, rejetée, prédiction verrouillée).

## Amélioration du modèle au fil des utilisations

Réentraîner un CNN « en direct » à chaque clic serait dangereux (oubli catastrophique, vandalisme). Le projet suit donc le schéma standard **human-in-the-loop** :

1. **Collecte** : après chaque verdict, l'utilisateur confirme (👍) ou conteste (👎) en proposant la bonne poubelle.
2. **Filtrage anti-vandalisme** (`ml_model/feedback.py`) : une correction n'est marquée `acceptee` que si le modèle donnait lui-même une probabilité **≥ 0,15** à la poubelle proposée (avec 5 classes, le hasard vaut 0,20 : à 0,15 le modèle hésitait réellement). Si le modèle était quasi certain (confiance **≥ 0,95**), la correction est archivée `rejetee` pour revue humaine — jamais acceptée automatiquement.
3. **Archivage** : image + métadonnées dans `var/feedback/` (`feedback.jsonl` + `images/`). Tout est conservé, y compris les rejets.
4. **Réentraînement périodique** : un script du coéquipier IA consomme les entrées `acceptee` (et `confirmee` comme exemples positifs) pour affiner le modèle et régénérer `modele_eco_sort.h5`.

Les seuils (0,15 et 0,95) sont des constantes documentées dans `ml_model/feedback.py`, à ajuster en équipe si besoin.

## Intégration du vrai code des coéquipiers

La vue Django ne changera pas : il suffit de remplacer le contenu des deux modules en conservant les signatures publiques.

**`scraper/jumia_scraper.py`** (format de sortie **confirmé** ; paramètre `page` = **extension à valider**) :

```python
def rechercher_produits(mot_cle: str, page: int = 1) -> list[dict]:
    # 3 à 5 éléments : {"titre": str, "image_url": str, "produit_url": str}
    # liste vide si aucun résultat ; page=2, 3... pour « Voir d'autres produits »
```

Si le vrai module garde la signature d'origine (sans `page`), tout continue de fonctionner : la vue détecte la signature et n'envoie `page` que si elle est acceptée.

**`ml_model/classifier.py`** (format de sortie = **proposition à valider** ; clé `probabilites` = **extension à valider**) :

```python
def charger_modele() -> None:
    # idempotent ; appelé UNE fois au démarrage (webapp/apps.py -> ready())

def predire_categorie(image_bytes: bytes) -> dict:
    # {"categorie": str, "couleur": str, "confiance": float,
    #  "probabilites": {slug: float}}   # sortie softmax agrégée par catégorie
    # "couleur" ∈ {"jaune", "verte", "bleue", "grise", "marron"}
```

La clé `probabilites` alimente le garde-fou du feedback ; côté Keras, c'est le vecteur `model.predict()` déjà calculé, sommé par catégorie officielle. C'est la **vue Django** qui télécharge l'image depuis `image_url` (`webapp/utils.py`) : le module IA reçoit des octets, il ne fait aucun réseau. Penser à décommenter `tensorflow-cpu` dans `requirements.txt` au moment de l'intégration, et à déposer `modele_eco_sort.h5` dans `ml_model/` (le `.gitignore` exclut les `.h5` — passer par Git LFS ou une release GitHub).

## API interne

`POST /api/search` — entrée `{"mot_cle": str, "page": int (optionnel, défaut 1)}` → sortie `{"resultats": [{"titre", "image_url", "produit_url"}, ...], "page": int}` (liste éventuellement vide). Erreurs : `{"erreur": str}` avec statut 400/502.

`POST /api/classify` — deux modes d'entrée : JSON `{"image_url": str}` (produit du carousel) **ou** multipart `image_file` (photo de l'utilisateur, actif dans l'interface). Sortie `{"categorie", "couleur", "confiance", "detail", "prediction_id"}`. Erreurs : `{"erreur": str}` avec statut 400/500/502.

`POST /api/feedback` — entrée `{"prediction_id": str, "correcte": bool, "couleur_correcte": str (si correcte=false)}` → sortie `{"statut": "confirmee"|"acceptee"|"rejetee", "message": str}`. Erreurs : 400 (poubelle invalide), 404 (prédiction expirée), 500.

## Structure

```
ecosort-box/
├── config/              # settings, urls, wsgi (pas de base de données)
├── webapp/              # app Django : vues, template, static (JS/CSS), images mock
│   └── predictions.py   # registre en mémoire des prédictions récentes (feedback)
├── scraper/             # module scraping Jumia (mock -> code du coéquipier)
├── ml_model/            # module deep learning (mock -> code + .h5 du coéquipier)
│   └── feedback.py      # seuils d'acceptation + archivage des retours utilisateurs
├── var/feedback/        # créé à l'exécution : feedback.jsonl + images/ (gitignoré)
├── requirements.txt
├── Dockerfile           # gunicorn sur :8501, 1 worker (modèle chargé une seule fois)
├── docker-compose.yml
├── MODIFICATIONS.md     # journal détaillé de la V2 (thèmes, photo, feedback...)
└── README.md
```

## Règles d'équipe

Aucun push direct sur `main` : chaque contribution passe par une **Pull Request** relue par au moins un coéquipier, chacun sur sa branche (`web`, `scraping`, `ml`). Le dataset Kaggle, les environnements virtuels, les fichiers `.h5` et le dossier `var/` ne sont jamais commités (voir `.gitignore`).
