# ============================================================================
# EcoSort-BOX — image monolithique (web + scraper + modèle importés en
# packages Python internes, pas en services distants).
#
# Évaluation prof :  docker build -t ecosort . && docker run -p 8501:8501 ecosort
# L'app écoute sur 8501 DANS le conteneur pour que cette commande fonctionne
# telle quelle (8501 est un simple port de bind gunicorn, Django n'est pas
# "forcé" : il reste configurable via la variable PORT et docker-compose).
# ============================================================================
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8501

WORKDIR /app

# Dépendances d'abord (cache Docker : pas de réinstallation à chaque édit).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Collecte des fichiers statiques servis par whitenoise.
RUN python manage.py collectstatic --noinput

EXPOSE 8501

# --workers 1 --threads 8 : UN seul processus, donc le modèle de deep
# learning n'est chargé qu'UNE fois en mémoire (AppConfig.ready()) ET le
# registre en mémoire des prédictions (webapp/predictions.py) reste cohérent ;
# les threads absorbent la concurrence des requêtes.
CMD gunicorn config.wsgi:application --bind 0.0.0.0:${PORT} --workers 1 --threads 8 --timeout 120
