---
name: pokeprice-collection
description: Gérer le projet pokeprice du propriétaire, ses imports d’albums Pokémon, corrections, exemplaires, prix, sauvegardes et lots de vente, avec conservation des sources et de la provenance.
---

# Collection Pokémon du propriétaire

Projet : `~/Projects/pokeprice`. Lire `docs/APP.md` pour les commandes et
`docs/ROADMAP.md` pour le jalon courant. La gestion repose sur FastAPI/SQLite ;
les décisions et procédures sont dans le projet, pas dans ce skill.

## Sources et corrections

- La base `data/inventory/collection.sqlite3` est la source de vérité des
  modifications faites dans l'application. Les CSV/checkpoints/corrections et
  pages originales sont les sources archivées. Ne pas les réécrire pour une
  correction de gestion ; utiliser l'API avec version attendue, auteur et motif.
- L'identifiant durable d'un exemplaire ne dépend plus de son emplacement.
  Une carte déplacée conserve son UUID et sa clé d'origine.
- `pokeprice-manage import <manifeste>` ajoute les nouvelles clés uniquement.
  Il ne fusionne pas `source_changed` et n'écrase pas les corrections. Pour un
  album rephotographié ou des fichiers renommés, établir la correspondance avec
  les exemplaires actuels avant import ; ne pas créer du stock en double.
- Sur un nouvel album, conserver les fichiers originaux, les paramètres OCR,
  les réponses et les corrections. Utiliser le backend/modèle choisi par le propriétaire :
  Gemini `gemini-3.8-flash` pour les scans autorisés. Ne pas relancer un OCR ou
  une recherche de prix pour une simple régénération de données déjà disponibles.
- Les versos et couvertures explicitement exclus ne sont pas du stock, mais
  leur photo originale reste dans l'archive. Une identité non résolue reste
  distincte ; son candidat catalogue et son prix ne sont pas des valeurs confirmées.

## Photos et identités lues

Procédure et outils : `docs/AUDIT-PHOTOS.md` (`scripts/audit_photo_crops.py`,
`scripts/audit_photo_identity.py`).

- Une identité lue sur une photo dépend de son découpage. Après un redécoupage
  ou une nouvelle photo, revérifier nom, numéro et PV avant de la tenir pour acquise.
- La correspondance `exact` de l'import ne prouve rien : l'OCR peut lire un
  numéro qui existe au catalogue sans être celui de la carte (Ouisticram
  57/100 enregistré, 97/147 sur la photo).
- Vérification locale sans Gemini : listes d'extensions TCGdex en cache
  (`catalog_lookups`, le numéro lu doit donner le nom lu), DINOv2 contre l'image
  de la référence, revue visuelle sur planches.
- Proposer une référence ne la confirme pas : le statut reste « À vérifier »
  (`review`) jusqu'à la validation du propriétaire. Pas d'`evidence` dont le
  libellé affirmerait une confirmation humaine.
- « À identifier » signifie souvent un dos visible. Signaler à part les cartes
  face cachée ou tête en bas, sans patch : on les corrige dans le classeur.
- La langue s'observe carte par carte : beaucoup d'énergies anglaises étaient
  enregistrées sous un nom français.

## Prix et photos

- Conserver référence, langue, PV, variante, état et validation humaine séparés.
  Un état estimé par IA reste à confirmer. Le prix de référence et celui de la
  vente sont distincts ; aucune décote automatique n'est appliquée.
- Un prix absent reste `NULL`, jamais zéro inventé. Une correction d'identité
  ou de variante invalide le prix courant ; un nouveau relevé demande une source.
- La photo appartient à l'exemplaire, pas seulement à l'édition. Vérifier les
  doublons et langues sans les fusionner. Les photos de gestion exigent la même
  authentification que les fiches.
- Exporter l'état géré avec `pokeprice-manage export html|csv|json <nouveau fichier>`.
  La commande historique `library` relit les rapports d'origine et ne reprend pas
  les nouvelles corrections de la base.

## Sauvegarde et stock

- Avant migration ou opération de masse, utiliser `pokeprice-manage backup` :
  ZIP SQLite cohérent + photos. Ne pas copier/synchroniser le fichier SQLite
  actif seul. Restaurer dans un dossier inexistant et rapprocher les comptes.
  La procédure initiale est dans `docs/RECOVERY.md`.
- Tester les changements sur des bases temporaires. L'audit
  `scripts/verify_inventory_import.py` vise l'import initial, avant modifications.
  Pour le développement web : `uv run --extra web --extra dev pytest`.
- Un brouillon ne réserve pas et ne vend pas. Réserver les exemplaires ensemble
  par une transaction. Une vente, annulation ou retour doit garder le stock et
  l'historique cohérents ; renseigner séparément les paiements, frais et remboursements.
- Préparer les annonces et les lots localement. L'autorisation de gestion ne
  vaut pas publication d'annonce, message à un acheteur, transaction ou achat
  de service. Respecter les autorisations explicites de la session pour ces actions.

Le déploiement est préparé dans `docs/DEPLOYMENT.md`. Confirmer le fournisseur,
le domaine, le coût et la destination de sauvegarde avant la mise en ligne des
données réelles. Le compte Google One n'est pas un hébergement applicatif.
