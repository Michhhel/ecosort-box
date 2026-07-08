"""Configuration de l'app webapp : chargement du modèle au démarrage."""
import sys

from django.apps import AppConfig


class WebappConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "webapp"

    def ready(self):
        """
        Charge le modèle de deep learning UNE SEULE FOIS au démarrage du
        serveur, jamais à chaque requête (bonne pratique imposée).
        """
        commandes_sans_modele = {"collectstatic", "makemigrations", "migrate", "check"}
        if any(cmd in sys.argv for cmd in commandes_sans_modele):
            return

        from ml_model import classifier

        classifier.charger_modele()
