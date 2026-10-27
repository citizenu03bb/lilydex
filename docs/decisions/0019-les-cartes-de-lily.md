# 0019 — Le produit s'appelle Les cartes de Lily

> **Statut :** en vigueur · **Date :** 2026-10-27

**Contexte.** Le produit s'appelait Lilydex. Une application iOS de suivi de
collection Pokémon GO porte un nom très proche, « lily dex ». La vitrine
s'affichait déjà sous le nom « Les cartes de Lily », alors que la gestion, la
page À propos et la documentation disaient encore Lilydex. Le site pourrait
changer d'adresse pour un domaine à ce nom.

**Options.**
1. Garder Lilydex.
2. Renommer le texte visible et la documentation, et laisser les noms
   techniques : dépôt `lilydex`, paquet `pokeprice`, adresse actuelle,
   balises et clés de stockage `lilydex-…`.
3. Tout renommer, noms techniques compris, avec une migration des sélections
   et thèmes enregistrés dans les navigateurs.

**Décision.** Option 2. Les pages prennent le nom à un seul endroit,
`SITE_NAME` dans `src/pokeprice/brand.py` : le serveur le substitue à
`{{site_name}}` dans chaque page, et le fichier d'export des données
personnelles en dérive son nom (`les-cartes-de-lily-mes-donnees.json`).

**Conséquences.**
- Les pages vivantes de la documentation disent Les cartes de Lily, ou « le
  site », « l'application », « le projet » quand le nom, pluriel, rendrait la
  phrase bancale. Le journal, les fiches de décision, les archives et les
  rapports datés gardent l'ancien nom.
- Le dépôt GitHub, l'adresse `lilydex.duckdns.org` et les identifiants
  techniques gardent `lilydex` : les renommer ne changerait rien pour un
  visiteur, et les clés de stockage lui feraient perdre sa sélection.
- Le logotype de la vitrine (« Les cartes » au-dessus de « de Lily ») est un
  dessin : il ne suit pas `SITE_NAME` et se modifie à la main.
