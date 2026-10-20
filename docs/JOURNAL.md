# Journal

> **Pour qui :** toute personne qui veut savoir ce qui a changé, et quand.
> **Vous y trouverez :** les changements notables, du plus récent au plus ancien, une à quatre lignes chacun, avec leur preuve.
> **Statut :** tenu à jour. Le détail complet est dans `git log` ; les raisons des choix sont dans les [fiches de décision](decisions/README.md).

Une page qui décrit le fonctionnement ne porte pas de date : quand un passage
daté la quitte, il est versé ici dans le même commit.

## 2026-10-20

- Refonte de la documentation : pages au présent, journal unique, fiches de
  décision, glossaire, contrôle automatique des liens et des dates
  (`scripts/check_docs.py`). La documentation d'avant la refonte reste lisible
  au commit `fecf90e`.

## 2026-10-19

- Pilote agent livré : un agent IA prépare des brouillons de lots sur un album
  délégué, avec une clé révocable ([pilote agent](AGENT_CONTROL.md)).
- Synchronisation portable ↔ serveur explorée, non retenue
  ([proposition archivée](archive/SYNC_PROPOSAL-2026-10-19.md)).

## 2026-10-18

- Les copies Drive sont chiffrées avec age avant l'envoi
  ([sauvegardes](DAILY-BACKUPS.md)).
- Données personnelles : espace « Mon compte », registre des traitements,
  durées de conservation et procédures ([RGPD](RGPD.md)).
- Option vision installée sur le serveur ARM, avec torch pour processeur seul ;
  empreinte mémoire et disque mesurée ([hébergement](DEPLOYMENT.md)).

## 2026-10-17

- Le portable rapatrie chaque nuit l'archive vérifiée du serveur et l'envoie
  sur Drive ; il ne sauvegarde plus sa propre base, devenue une copie.
- Rétention des archives sur Drive : les plus anciennes vont à la corbeille.

## 2026-10-16

- Le serveur Oracle Cloud devient la référence de la collection : la journée
  de travail faite sur le portable y est reportée, puis le portable ne sert
  plus qu'aux essais et aux sauvegardes.
- Code publié sous licence MIT, après un [audit de sécurité](AUDIT-SECURITE.md),
  dans un dépôt neuf sans l'historique d'avant la réécriture du 12 octobre.
- Vitrine publique livrée en quatre tranches : rôle client, publication et
  prix affiché, vitrine sans compte, inscription et demandes de réservation.
  La vitrine passe à la racine du site, la gestion sur `/gestion`.
- Porte énergie dans le pipeline d'albums ([IA et vision](IA-VISION.md)).
- Audit des photos des classeurs : 680 photos redécoupées, 140 corrections,
  22 cartes à retourner dans le classeur ([audit des photos](AUDIT-PHOTOS.md)).

## 2026-10-14

- Six nouveaux classeurs numérisés et importés.
- Tesseract écarté sur mesure ; la langue est contrôlée par cohérence
  ([fiche 0005](decisions/0005-langue-sans-tesseract.md)).

## 2026-10-13

- Contrôles indépendants (jalon M2), tranches 1 à 3 : lecture de la finition
  et proposition de variante, lecture à la saisie avec le banc d'essai en
  test de non-régression, contrôle de l'édition par l'image (DINOv2).
- Référentiel des impressions en mode audit (jalon M1.1) : contrat, socle, et
  premier cas de bout en bout, EX Fantômes Holon 78 en français
  ([guide du référentiel](PRINT_REFERENCE_GUIDE.md)).
- Audit des variantes Foil clos : toutes les Foil confirmées à l'œil.

## 2026-10-12

- Valeur prudente et file « À examiner » (jalon M1) ([valeur en jeu](VALUATION.md)).
- Premier relevé TCGdex de toute la collection.
- Restauration de l'instantané initial depuis Drive, vérifiée
  ([instantané](RECOVERY.md)).
- Historique git réécrit pour en retirer les données personnelles.
- Feuille de route du MVP ([ROADMAP](ROADMAP.md)), qui remplace la
  [feuille de route d'origine](archive/ROADMAP-2026-10-05.md).

## 2026-10-07

- Banc d'essai de reconnaissance : Gemini, Tesseract, DINOv2, CLIP et des
  agents Claude mesurés sur des cartes vérifiées
  ([banc d'essai](BANC-RECONNAISSANCE.md)).

## 2026-10-06

- Copie Drive des sauvegardes par rclone, retéléchargée et restaurée pour
  contrôle ([sauvegardes](DAILY-BACKUPS.md)).

## 2026-10-05

- Accès HTTPS temporaire par un tunnel Cloudflare
  ([document archivé](archive/TUNNEL-2026-10-05.md)).
- Verso et aide à l'évaluation de l'état ([aide à l'état](CONDITION-ASSESSMENT.md)).
- Améliorations pour les six classeurs suivants
  ([document archivé](archive/IMPROVEMENTS-2026-10-05.md)).
- Sauvegardes quotidiennes et copie externe de l'instantané initial sur Drive.

## 2026-10-04

- Instantané initial de la collection : 368 fichiers, dont les 80 photos
  originales ([instantané](RECOVERY.md)).
- Trois logiciels existants évalués ; une application maison est retenue
  ([évaluation](EVALUATION.md), [fiche 0001](decisions/0001-application-maison.md)).
- Première application de gestion locale (FastAPI et SQLite) et premier import
  de trois classeurs, réimport sans doublon.

## 2026-10-03

- Premier pipeline d'albums : découpe des pages, lecture locale par Gemma via
  Ollama, rapprochement TCGdex.
