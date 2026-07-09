/* ==========================================================================
   EcoSort-BOX — logique du chat (JavaScript vanilla, aucun framework)

   Le « chat » est une mise en scène d'interface : une machine à états simple
   pilotée en JS, pas un moteur conversationnel.

   Parcours nominal : mot-clé -> /api/search -> carousel -> sélection
   -> /api/classify -> verdict coloré -> retour utilisateur (/api/feedback).
   Parcours photo   : bouton appareil photo -> fichier de la galerie
   -> /api/classify (multipart) -> verdict -> retour utilisateur.
   ========================================================================== */
(function () {
  "use strict";

  // --- Références DOM ------------------------------------------------------
  const fil = document.getElementById("fil");
  const formulaire = document.getElementById("form-recherche");
  const champ = document.getElementById("champ-mot-cle");
  const boutonEnvoyer = document.getElementById("bouton-envoyer");
  const boutonPhoto = document.getElementById("bouton-photo");
  const champPhoto = document.getElementById("champ-photo");
  const suggestions = document.getElementById("suggestions");

  const gabaritCarousel = document.getElementById("gabarit-carousel");
  const gabaritProduit = document.getElementById("gabarit-produit");
  const gabaritVerdict = document.getElementById("gabarit-verdict");

  const CSRF = document.querySelector('meta[name="csrf-token"]').content;

  // Référentiel des 5 poubelles (pour le sélecteur de correction).
  const POUBELLES = [
    { slug: "jaune",  libelle: "JAUNE" },
    { slug: "verte",  libelle: "VERTE" },
    { slug: "bleue",  libelle: "BLEUE" },
    { slug: "grise",  libelle: "D3E (grise)" },
    { slug: "marron", libelle: "MARRON / NOIRE" },
  ];

  // `occupe` verrouille la saisie pendant qu'un appel réseau est en cours.
  let occupe = false;

  // ==========================================================================
  // Thèmes d'affichage (jour / nuit / gris)
  // ==========================================================================

  const CLE_THEME = "ecosort-theme";
  const boutonsTheme = document.querySelectorAll(".theme-btn");

  function appliquerTheme(theme) {
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem(CLE_THEME, theme); } catch (e) { /* navigation privée */ }
    boutonsTheme.forEach((bouton) => {
      bouton.setAttribute("aria-pressed", String(bouton.dataset.theme === theme));
    });
  }

  boutonsTheme.forEach((bouton) => {
    bouton.addEventListener("click", () => appliquerTheme(bouton.dataset.theme));
  });
  // Synchronise l'état des boutons avec le thème appliqué avant le rendu
  // (script inline du <head>).
  appliquerTheme(document.documentElement.dataset.theme || "jour");

  // ==========================================================================
  // Aides génériques
  // ==========================================================================

  function defiler() {
    // Laisse le navigateur peindre le nouveau message avant de défiler.
    requestAnimationFrame(() => {
      window.scrollTo({ top: document.body.scrollHeight, behavior: "smooth" });
    });
  }

  function verrouillerSaisie(etat) {
    occupe = etat;
    champ.disabled = etat;
    boutonEnvoyer.disabled = etat;
    boutonPhoto.disabled = etat;
    if (!etat) champ.focus();
  }

  /** Ajoute une bulle utilisateur (à droite). */
  function ajouterMessageUtilisateur(texte) {
    const li = document.createElement("li");
    li.className = "message message--utilisateur";
    const bulle = document.createElement("div");
    bulle.className = "bulle";
    const p = document.createElement("p");
    p.textContent = texte;
    bulle.appendChild(p);
    li.appendChild(bulle);
    fil.appendChild(li);
    defiler();
  }

  /** Bulle utilisateur contenant l'aperçu de la photo envoyée. */
  function ajouterMessagePhoto(fichier) {
    const li = document.createElement("li");
    li.className = "message message--utilisateur";
    const bulle = document.createElement("div");
    bulle.className = "bulle";

    const img = document.createElement("img");
    img.className = "apercu-photo";
    img.alt = "Photo envoyée";
    const urlLocale = URL.createObjectURL(fichier);
    img.src = urlLocale;
    img.addEventListener("load", () => {
      URL.revokeObjectURL(urlLocale);
      defiler();
    });

    const p = document.createElement("p");
    p.textContent = "Voici ma photo du produit.";

    bulle.appendChild(img);
    bulle.appendChild(p);
    li.appendChild(bulle);
    fil.appendChild(li);
    defiler();
  }

  /** Ajoute une bulle bot (à gauche). estErreur ajoute le style d'alerte. */
  function ajouterMessageBot(texte, estErreur = false) {
    const li = document.createElement("li");
    li.className = "message message--bot";
    li.innerHTML =
      '<span class="avatar" aria-hidden="true">♻</span>' +
      '<div class="bulle' + (estErreur ? " bulle--erreur" : "") + '"><p></p></div>';
    li.querySelector("p").textContent = texte;
    fil.appendChild(li);
    defiler();
    return li;
  }

  /**
   * Indicateur de chargement « le bot écrit… » — OBLIGATOIRE pendant les
   * appels au scraping et au modèle, sinon l'utilisateur croit à un plantage.
   * Renvoie une fonction qui retire l'indicateur.
   */
  function afficherFrappe(libelle) {
    const li = document.createElement("li");
    li.className = "message message--bot";
    li.setAttribute("role", "status");
    li.innerHTML =
      '<span class="avatar" aria-hidden="true">♻</span>' +
      '<div class="bulle"><p class="frappe">' +
      '<span class="frappe-points"><i></i><i></i><i></i></span>' +
      '<span class="frappe-libelle"></span></p></div>';
    li.querySelector(".frappe-libelle").textContent = libelle;
    fil.appendChild(li);
    defiler();
    return () => li.remove();
  }

  /** Lit et normalise une réponse de nos endpoints Django. */
  async function lireReponse(reponse) {
    let donnees = {};
    try {
      donnees = await reponse.json();
    } catch (e) {
      /* corps non-JSON : on garde {} */
    }
    if (!reponse.ok) {
      throw new Error(donnees.erreur || "Le serveur a répondu avec une erreur inattendue.");
    }
    return donnees;
  }

  /** POST JSON vers nos endpoints Django. */
  async function appelerApi(url, corps) {
    const reponse = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": CSRF,
      },
      body: JSON.stringify(corps),
    });
    return lireReponse(reponse);
  }

  /** POST multipart (photo) — le navigateur fixe lui-même le Content-Type. */
  async function appelerApiFichier(url, formData) {
    const reponse = await fetch(url, {
      method: "POST",
      headers: { "X-CSRFToken": CSRF },
      body: formData,
    });
    return lireReponse(reponse);
  }

  // ==========================================================================
  // Étape 1 — recherche du produit (paginée)
  // ==========================================================================

  async function lancerRecherche(motCle, page = 1) {
    if (occupe) return;
    motCle = motCle.trim();
    if (!motCle) return;

    suggestions.hidden = true;
    if (page === 1) {
      ajouterMessageUtilisateur(motCle);
      champ.value = "";
    } else {
      ajouterMessageUtilisateur("Montre-moi d'autres produits pour « " + motCle + " »");
    }
    verrouillerSaisie(true);

    const retirerFrappe = afficherFrappe(
      page === 1
        ? "Je cherche « " + motCle + " » sur Jumia…"
        : "Je cherche d'autres produits sur Jumia…"
    );
    try {
      const donnees = await appelerApi("/api/search", { mot_cle: motCle, page: page });
      retirerFrappe();

      const resultats = donnees.resultats || [];
      if (resultats.length === 0) {
        ajouterMessageBot(
          page === 1
            ? "Je n'ai trouvé aucun produit pour « " + motCle + " » sur Jumia. " +
              "Essaie un autre mot-clé, ou envoie ta propre photo avec le bouton appareil photo."
            : "Je n'ai plus d'autres produits pour « " + motCle + " ». " +
              "Tu peux analyser ta propre photo avec le bouton appareil photo."
        );
        return;
      }

      afficherCarousel(motCle, page, resultats);
    } catch (erreur) {
      retirerFrappe();
      ajouterMessageBot(erreur.message, true);
    } finally {
      verrouillerSaisie(false);
    }
  }

  // ==========================================================================
  // Étape 2 — carousel de sélection
  // ==========================================================================

  function afficherCarousel(motCle, page, resultats) {
    const fragment = gabaritCarousel.content.cloneNode(true);
    const message = fragment.querySelector(".message");
    fragment.querySelector(".carousel-intro").textContent =
      (page === 1 ? "Voici " : "Voici encore ") +
      resultats.length + " produits trouvés pour « " + motCle + " » :";

    const liste = fragment.querySelector(".splide__list");
    for (const produit of resultats) {
      const slide = gabaritProduit.content.cloneNode(true);
      const bouton = slide.querySelector(".produit");
      const image = slide.querySelector("img");

      image.src = produit.image_url;
      image.alt = produit.titre;
      slide.querySelector(".produit-titre").textContent = produit.titre;
      bouton.addEventListener("click", () => choisirProduit(produit, bouton, message));

      liste.appendChild(slide);
    }

    // Bouton « Voir d'autres produits » : recharge la page suivante du
    // scraping pour une meilleure correspondance. Usage unique par carousel
    // (le carousel suivant aura son propre bouton pour la page d'après).
    const boutonAutres = fragment.querySelector(".action-autres");
    boutonAutres.addEventListener("click", () => {
      if (occupe) return;
      boutonAutres.disabled = true;
      lancerRecherche(motCle, page + 1);
    });

    // Bouton « Analyser ma photo » : bascule sur l'envoi d'une photo perso.
    fragment.querySelector(".action-photo").addEventListener("click", () => {
      if (!occupe) champPhoto.click();
    });

    fil.appendChild(fragment);

    // Montage du carousel Splide (librairie CDN — flèches natives).
    new Splide(message.querySelector(".splide"), {
      perPage: 3,
      gap: "14px",
      pagination: false,
      arrows: true,
      breakpoints: {
        900: { perPage: 2 },
        560: { perPage: 1, padding: { right: "18%" } },
      },
      reducedMotion: { speed: 0 },
    }).mount();

    defiler();
  }

  // ==========================================================================
  // Étape 3 — classification (produit du carousel OU photo de l'utilisateur)
  // ==========================================================================

  async function choisirProduit(produit, bouton, messageCarousel) {
    if (occupe || bouton.disabled) return;

    // Fige le carousel : le choix est fait (réactivé en cas d'erreur).
    const boutons = messageCarousel.querySelectorAll(".produit");
    boutons.forEach((b) => (b.disabled = true));
    bouton.classList.add("est-choisi");

    ajouterMessageUtilisateur("J'ai choisi : " + produit.titre);
    verrouillerSaisie(true);

    const retirerFrappe = afficherFrappe("J'analyse le produit pour trouver la bonne poubelle…");
    try {
      const verdict = await appelerApi("/api/classify", { image_url: produit.image_url });
      retirerFrappe();
      afficherVerdict(verdict);
    } catch (erreur) {
      retirerFrappe();
      ajouterMessageBot(erreur.message, true);
      // On rend la main : l'utilisateur peut choisir un autre produit.
      boutons.forEach((b) => (b.disabled = false));
      bouton.classList.remove("est-choisi");
    } finally {
      verrouillerSaisie(false);
    }
  }

  async function analyserPhoto(fichier) {
    if (occupe) return;
    if (!fichier.type.startsWith("image/")) {
      ajouterMessageBot("Ce fichier n'est pas une image. Choisis une photo (JPG, PNG…).", true);
      return;
    }
    if (fichier.size > 8 * 1024 * 1024) {
      ajouterMessageBot("Cette image dépasse 8 Mo. Choisis une photo plus légère.", true);
      return;
    }

    suggestions.hidden = true;
    ajouterMessagePhoto(fichier);
    verrouillerSaisie(true);

    const retirerFrappe = afficherFrappe("J'analyse ta photo pour trouver la bonne poubelle…");
    try {
      const formData = new FormData();
      formData.append("image_file", fichier);
      const verdict = await appelerApiFichier("/api/classify", formData);
      retirerFrappe();
      afficherVerdict(verdict);
    } catch (erreur) {
      retirerFrappe();
      ajouterMessageBot(erreur.message, true);
    } finally {
      verrouillerSaisie(false);
    }
  }

  // ==========================================================================
  // Étape 4 — verdict + retour utilisateur
  // ==========================================================================

  function afficherVerdict(verdict) {
    const fragment = gabaritVerdict.content.cloneNode(true);
    const carte = fragment.querySelector(".verdict");

    const couleur = String(verdict.couleur || "").toLowerCase();
    const couleursConnues = POUBELLES.map((p) => p.slug);
    carte.dataset.c = couleursConnues.includes(couleur) ? couleur : "grise";

    carte.querySelector(".verdict-categorie").textContent =
      verdict.categorie || "Catégorie inconnue";
    carte.querySelector(".verdict-detail").textContent = verdict.detail || "";

    const confiance = Math.max(0, Math.min(1, Number(verdict.confiance) || 0));
    carte.querySelector(".jauge-libelle").textContent =
      "Confiance du modèle : " + Math.round(confiance * 100) + " %";

    carte.querySelector(".verdict-rejouer").addEventListener("click", () => {
      document.body.removeAttribute("data-verdict");
      ajouterMessageBot("Avec plaisir ! Quel autre produit veux-tu trier ?");
      champ.focus();
    });

    installerRetour(carte, verdict.prediction_id);

    fil.appendChild(fragment);

    // Signature visuelle : tout l'écran se teinte à la couleur de la poubelle.
    document.body.dataset.verdict = carte.dataset.c;

    // Anime la jauge après insertion dans le DOM.
    requestAnimationFrame(() => {
      const jauge = fil.querySelector(".message:last-child .jauge-remplissage");
      if (jauge) jauge.style.width = Math.round(confiance * 100) + "%";
    });

    defiler();
  }

  /** Branche le bloc « cette consigne est-elle correcte ? » du verdict. */
  function installerRetour(carte, predictionId) {
    const bloc = carte.querySelector(".verdict-retour");
    if (!predictionId) {
      // Pas d'identifiant (ex. futur module IA sans registre) : pas de retour.
      bloc.hidden = true;
      return;
    }

    const boutonOui = bloc.querySelector(".retour-oui");
    const boutonNon = bloc.querySelector(".retour-non");
    const choix = bloc.querySelector(".retour-choix");
    const conteneur = bloc.querySelector(".retour-poubelles");

    boutonOui.addEventListener("click", () => {
      envoyerRetour(bloc, predictionId, { correcte: true });
    });

    boutonNon.addEventListener("click", () => {
      boutonNon.disabled = true;
      choix.hidden = false;
      defiler();
    });

    // Propose les 4 autres poubelles (pas celle déjà prédite).
    POUBELLES
      .filter((poubelle) => poubelle.slug !== carte.dataset.c)
      .forEach((poubelle) => {
        const bouton = document.createElement("button");
        bouton.type = "button";
        bouton.className = "retour-poubelle";

        const pastille = document.createElement("span");
        pastille.className = "pastille-mini pastille-mini--" + poubelle.slug;
        bouton.appendChild(pastille);
        bouton.appendChild(document.createTextNode(poubelle.libelle));

        bouton.addEventListener("click", () => {
          envoyerRetour(bloc, predictionId, {
            correcte: false,
            couleur_correcte: poubelle.slug,
          });
        });
        conteneur.appendChild(bouton);
      });
  }

  async function envoyerRetour(bloc, predictionId, corps) {
    if (bloc.classList.contains("est-envoye")) return;
    bloc.classList.add("est-envoye");
    bloc.querySelectorAll("button").forEach((b) => (b.disabled = true));

    const retirerFrappe = afficherFrappe("J'enregistre ton retour…");
    try {
      const donnees = await appelerApi("/api/feedback", {
        prediction_id: predictionId,
        ...corps,
      });
      retirerFrappe();
      bloc.querySelector(".retour-question").textContent = "Merci pour ton retour !";
      ajouterMessageBot(donnees.message || "Ton retour a bien été enregistré.");
    } catch (erreur) {
      retirerFrappe();
      // On rend la main pour permettre un nouvel essai.
      bloc.classList.remove("est-envoye");
      bloc.querySelectorAll("button").forEach((b) => (b.disabled = false));
      ajouterMessageBot(erreur.message, true);
    }
  }

  // ==========================================================================
  // Écouteurs
  // ==========================================================================

  formulaire.addEventListener("submit", (evenement) => {
    evenement.preventDefault();
    lancerRecherche(champ.value);
  });

  suggestions.addEventListener("click", (evenement) => {
    const puce = evenement.target.closest(".puce");
    if (puce) lancerRecherche(puce.dataset.mot);
  });

  boutonPhoto.addEventListener("click", () => {
    if (!occupe) champPhoto.click();
  });

  champPhoto.addEventListener("change", () => {
    const fichier = champPhoto.files && champPhoto.files[0];
    champPhoto.value = ""; // permet de re-sélectionner le même fichier ensuite
    if (fichier) analyserPhoto(fichier);
  });

  champ.focus();
})();
