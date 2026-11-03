# 0023 — Une photo de page de classeur 3×3 se dépose dans la gestion comme un lot de photos annulable

> **Statut :** en vigueur · **Date :** 2026-11-03

**Contexte.** Lily ajoute ou rephotographie régulièrement une page entière de
classeur (grille 3×3, 9 pochettes) dans un album déjà référencé. Deux chemins
existaient, tous deux lourds pour une page isolée prise au téléphone :

- en ligne de commande, `pokeprice scan` puis `pokeprice-manage import` via un
  manifeste JSON : quatre étapes hors de l'interface web, conçues pour un
  classeur neuf et qui ignorent les clés déjà importées sans mettre à jour les
  photos des cartes déjà présentes ;
- dans la gestion web, la saisie unitaire ou en série (neuf prises de vue et
  neuf validations successives, avec alerte de doublon dès qu'une pochette est
  déjà occupée) ou le remplacement de photo fiche par fiche (ouvrir chacune des
  neuf fiches, téléverser une photo déjà recadrée à la carte, enregistrer).

**Options.**
1. Étendre `pokeprice-manage import` pour mettre à jour les emplacements
   existants : impose toujours le terminal, un dossier local et un manifeste,
   sans aperçu dans l'application ni usage direct sur téléphone.
2. Ouvrir neuf brouillons de saisie (`intake`) à la suite après la découpe :
   oblige encore à valider neuf formulaires l'un après l'autre et mélange la
   mise à jour d'une carte déjà connue avec la création d'une carte inconnue.
3. Étendre le patron `photo_batches`
   ([`src/pokeprice/photo_batches.py`](../../src/pokeprice/photo_batches.py)) à
   une simulation de page 3×3 découpée par
   [`src/pokeprice/slicer.py`](../../src/pokeprice/slicer.py), avec aperçu case
   par case, application atomique précédée d'une sauvegarde et annulation
   protégée par numéro de version.

**Décision.** Option 3.

- Depuis la gestion (ordinateur et téléphone), l'éditeur choisit un album
  existant et un numéro de page, puis prend ou téléverse la photo de la page
  complète.
- Le serveur redresse la page (`normalize_orientation`), la découpe en 9 cases
  (`slice_grid` en 3×3 avec marge intérieure de 2 %) et prépare chaque vignette
  localement (`prepare_photo`).
- L'aperçu présente les pochettes 1 à 9 dans l'ordre de la grille :
  - si un seul exemplaire actif occupe `(album_id, page, position)`, la case
    propose de remplacer sa photo de recto en montrant l'ancienne et la
    nouvelle ;
  - si la pochette est vide, la case propose de créer une fiche
    « À identifier » (`identification_status="unresolved"`) à cet emplacement
    avec la photo découpée ;
  - si plusieurs exemplaires actifs partagent déjà la même pochette, la case
    signale l'ambiguïté d'emplacement et ne s'applique pas automatiquement.
- L'application vérifie les versions et la vacance des pochettes vides, crée
  une sauvegarde `before-photo-batch-…zip`, puis met à jour les exemplaires
  existants (`condition_confirmed=False`) et crée les fiches « À identifier »
  dans une même transaction SQLite.
- L'annulation restaure la photo antérieure des exemplaires mis à jour et met
  à la corbeille (`deleted_at`) les fiches « À identifier » créées par le lot,
  seulement si aucune des fiches concernées n'a changé de version depuis
  l'application.

**Conséquences.**
- Photographier et ranger une page de 9 cartes dans la gestion demande un seul
  dépôt et une validation groupée au lieu de neuf saisies individuelles.
- Le dépôt de page reste purement local et immédiat : il n'appelle aucun modèle
  de vision pendant la découpe ; l'identification et la revue passent ensuite
  par les parcours habituels.
- Comme la collection ne supprime jamais définitivement un exemplaire, annuler
  la création d'une pochette vide la place dans la corbeille avec son motif et
  son historique.
