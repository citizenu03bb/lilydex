# Livraison du socle M1.1 — 13 octobre 2026

**Mode audit. M1.1 reste ouvert.** Le contrat v1 reste la cible de réception.
La couverture et la preuve de marché ne sont pas déduites de tests synthétiques.

## Comportement disponible

- Observations explicites pour finition, tampon et marque de distribution.
  Le texte original, l’auteur serveur, la date et le motif sont conservés.
  Une observation partielle peut éliminer un candidat lorsqu’elle a sa propre
  provenance humaine, sans inventer une confirmation globale de la variante.
  Une proposition IA, un aperçu non enregistré et un ancien texte de tampon
  ne reçoivent pas cette attestation.
- Résolution pure et locale par ensemble de candidats, périmètres de langues
  et numéros, reste inconnu, discriminants manquants, preuves, conflits et
  contestation humaine. Une liste partielle ne certifie pas un singleton.
  Plusieurs impressions peuvent partager une correspondance marchande prouvée.
- Clé marchande fondée sur marché, produit natif, variante, filtres, famille
  versionnée de métriques, devise et population. Les libellés et versions de
  règles ne modifient pas cette clé. Une dimension inconnue n’est pas un joker.
- Journal séparé des cotations liées et des sélections. Une correction physique
  compatible conserve montant/source/date ; un changement de produit suspend
  l’ancienne cotation. Une suspension exige une restauration explicite, et un
  retrait interdit la résurrection. L’acquisition et la restauration vérifient
  la version de fiche dans la même transaction que leur journal.
- Valorisation des cotations liées séparée des anciennes hypothèses Foil.
  Tendance et moyenne à 30 jours doivent partager correspondance, devise EUR,
  population et acquisition compatible. Les références manuelles ne deviennent
  pas des tendances. Les liens des correspondances liées utilisent les filtres
  natifs documentés, sans déduire `isReverseHolo` du booléen Foil.
- Audit partagé par fiche, aperçu, exemplaires/éditions, CLI et exports.
  Filtre `review=coverage`, conservé dans l’adresse. Les prix hérités restent
  datés et visibles ; ils ne sont pas certifiés rétroactivement.
- Décisions enregistrables avec entrées, règles exactes, moteur archivé et
  résultat. La sauvegarde/restauration conserve ces éléments et les documents
  sources par empreinte. La reproduction mathématique et la disponibilité des
  pièces sont signalées séparément. Un moteur incompatible est déclaré
  indisponible ; son code archivé n’est pas exécuté automatiquement.

## Paquet initial et preuves

`src/pokeprice/reference/prints-v1.json`, schéma 1, version de contenu
`2026-10-13.1`, contient cinq règles de portée anglaise **partielle** :

| Édition | Numéros | Fait extrait | Limite |
|---|---|---|---|
| EX Deoxys | 16–95 | Versions mate et brillante dans la liste | Tirages/distributions non fermés |
| EX Fantômes Holon | 18–98 | Versions mate et brillante dans la liste | Tirages/distributions non fermés |
| EX Gardiens de Cristal | 14–88 | Versions mate et brillante dans la liste | Tirages/distributions non fermés |
| Indomptable | 81–90 | Une version brillante dans la liste ; 85 = Slowking Prime | Ne décrit pas à elle seule la zone qui brille |
| Destinées Futures | 74 | Scrafty rare Holo dans le jeu de base | Autres distributions non fermées |

Les [listes officielles de départ](PRINT_REFERENCE_PROPOSAL.md#sources-de-départ)
sont archivées hors paquet, une fois par SHA-256. Le JSON contient faits,
localisateurs, dates d’accès, périmètres et empreintes. Il ne prétend pas que
ces documents anglais certifient les impressions françaises ou italiennes,
les tampons particuliers, les produits Cardmarket ou leurs métriques.

Les huit familles de régression sont suivies explicitement. EX Légendes
Oubliées, POP Série 9 et Promo Nintendo restent non couverts dans ce paquet.
**Aucune correspondance marchande réelle n’est marquée vérifiée.** Les objets
de marché vérifiés des tests sont exclusivement des fixtures synthétiques.
Les dimensions de périmètre non prises en charge sont rejetées, jamais ignorées.

Le journal des cotations liées attend un adaptateur d’acquisition natif prouvé.
Il n’est pas alimenté par inférence depuis les anciens snapshots TCGdex et
n’est pas exposé comme contournement de validation dans le formulaire de prix.
Le service de prix actuel garde donc son adaptateur hérité. Le repli de langue
TCGdex trace désormais langue demandée/servie ; les caches anciens gardent une
origine inconnue, sans certification de portée française.

## Vérification et migration

- Tests synthétiques de résolution et transactions : conservation des prix,
  différence de produit avec Foil identique, couverture incomplète, langues,
  conflits/contestations, retrait/restauration, métriques incompatibles et
  concurrence. Les scénarios correspondent aux invariants C01–C20 ; ils ne
  remplacent pas la réception sur les cartes réelles.
  Validation finale : **358 tests Python, dont les sept scénarios Node,
  réussis** ; Ruff et contrôle du diff réussis. Un avertissement préexistant
  Starlette/httpx reste présent.
- Migration 10 → 11 → 12 : nouveaux champs non examinés et provenance vide pour les
  anciens exemplaires. Aucun montant, date, source, photo ou confirmation
  physique n’est modifié par la migration structurelle.
- Répétition sur sauvegarde de la collection : 407 exemplaires, 1 673 prix,
  3 051 événements et 406 sources conservés ; 27 décisions temporaires
  reproduites après une seconde restauration, avec cinq documents sources.
- Audit initial en lecture seule : 404 exemplaires actifs, 379 références
  héritées non liées, une référence manuelle héritée, 24 prix absents. Le
  sous-total vérifié est inconnu. Aucun de ces prix n’est effacé par l’audit.
- Construction d’un wheel, installation dans un répertoire distinct, chargement
  hors checkout avec appels réseau interdits. Un paquet invalide produit un
  diagnostic explicite et ne permet aucune nouvelle décision vérifiée.
- Vérification navigateur sur collection fictive : filtre de couverture et tri
  Classeur, fiche d’observations, saisie partielle avant scan, sans erreur JS.
  Serveurs localhost et LAN redémarrés ; API privée toujours authentifiée.

Le processus de sauvegarde a chargé le schéma intermédiaire 11 pendant le
développement. La migration 11 → 12 accepte à la fois les bases d’observations
seules et celles possédant déjà le journal de cotations, sans recréer les
tables existantes. Ces deux chemins ont leurs tests de migration/restauration.
Après correction, les sauvegardes locale et Drive ont été relancées et vérifiées
par restauration, avec `download-sha256-restore` pour la copie distante.

## Avant réception de M1.1

Il reste à apporter les preuves physiques pour les langues/distributions de
la collection, les correspondances marchandes et leurs métriques sur les huit
familles, raccorder l’acquisition à ces correspondances, puis répéter l’audit
et activer la sélection vérifiée sans perte inexpliquée. Les nouveaux albums
restent saisissables avec observations partielles et périmètre non couvert.
Les états de couverture guident l’enrichissement ; ils ne ferment pas les faits
métier pour satisfaire artificiellement un critère de test.

Changer les sémantiques du moteur exige une nouvelle `ENGINE_VERSION` et un
lecteur compatible testé pour les décisions historiques. Les règles invalides,
pièces absentes et versions non reproductibles restent des diagnostics locaux.
