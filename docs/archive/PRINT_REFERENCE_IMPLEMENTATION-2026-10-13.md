# Livraison du socle M1.1 — 13 octobre 2026

> **Archive.** Rapport de la première livraison du référentiel. L'état actuel, ses limites et la procédure de preuve sont dans le [guide du référentiel](../PRINT_REFERENCE_GUIDE.md#ce-qui-est-mis-en-œuvre). Le texte ci-dessous est conservé tel qu'il était ; seuls les liens ont été mis à jour.

**Mode audit. M1.1 reste ouvert.** Le contrat (révision 1.1) reste la cible de
réception. La couverture et la preuve de marché ne sont pas déduites de tests
synthétiques.

## Corrections après revue — 13 octobre 2026

- **Prix manuel conservé.** Après le retrait d’une cotation liée, un prix saisi
  à la main n’est plus effacé par une correction sans rapport (note, album…).
- **Contestation.** Elle inscrit la suspension de la cotation liée au journal
  dans sa propre transaction ; la retirer ne réactive pas le prix, qui exige une
  restauration explicite.
- **Mise à jour des règles.** `pokeprice-manage reference-recheck` liste les
  cotations devenues incompatibles et `--apply` inscrit leur suspension.
  L’audit compte `recheck_needed`.
- **Relevé atomique.** Une acquisition fournit toutes les métriques de sa famille
  depuis la même charge utile native ; un relevé incomplet est refusé. La colonne
  de référence affiche la tendance, plus la dernière métrique relevée.
- **Moteur par décision (schéma 13).** Chaque décision enregistre l’empreinte de
  son moteur dans `reference_engines` ; auparavant, une décision héritait du
  premier moteur enregistré pour son jeu de règles et devenait non reproductible
  dès une modification du moteur. Les décisions existantes reçoivent ce premier
  moteur, seule information disponible. Le rejeu exige une empreinte enregistrée
  comme compatible avec `ENGINE_VERSION`, validée par
  `tests/fixtures/engine_vectors.json`.
- **Moteur version 2.** Une liste partielle donne `candidates` ou `unobserved`
  avec le motif `unknown_remainder`, et non plus `uncovered`. La confirmation
  globale datée atteste la finition seule, marquée `legacy_global`.
- **Preuves.** `pokeprice-manage reference-archive` range une pièce par SHA-256
  dans `reference_documents/`. Une extension FR exige une preuve de périmètre FR.

La base réelle ne contenait aucune décision ni cotation liée : ces changements
n’affectent aucun historique. Migration 12 → 13 vérifiée sur une copie de la
collection (404 exemplaires, mêmes comptes d’audit). 369 tests réussis.

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

## Premier cas de bout en bout — EX Fantômes Holon 78 en français (13 octobre 2026)

Version de contenu `2026-10-13.2`. Règle `ex13-78-fr`, périmètre **français,
n° 78 seul** : une correspondance Cardmarket désigne un produit, donc un numéro.

| Pièce | Type | Statut | Établit |
|---|---|---|---|
| Photo de l’exemplaire (`7ebd7346…`) | impression | vérifiée | Le Pikachu 78/110 français existe en illustration holo avec tampon « EX Fantômes Holon » |
| TCGdex `fr/cards/ex13-78` (`b74023cc…`) | impression, marché | provisoire | Une version mate française ; produit 277048 et ses séries normale et `-holo` |
| Page Cardmarket enregistrée (`faf9c831…`) | marché | vérifiée | Produit 277048 « Pikachu (HP 78) » ; offres françaises « Stamp » sous Reverse ; cadre Info de la série Reverse (tendance, moyenne 30 jours) |

| Impression | Observations | Correspondance |
|---|---|---|
| `parallel-stamped` | holo + tampon présent (quatre graphies) | `cardmarket-277048-reverse`, vérifiée : filtre `isReverseHolo=Y`, métriques `trend-holo`/`avg30-holo`, EUR, toutes langues et tous états |
| `base-matte` | mate + tampon absent | `cardmarket-277048-normal`, provisoire (vue sans filtre Reverse non capturée) |
| reste inconnu | — | `cardmarket-277048-reverse` : la page ne propose que Reverse, Signé, First Edition et Altérée ; toute impression brillante de ce numéro s’y vend en Reverse |

Résultat sur la collection : le Pikachu 78/110 FR (holo, tampon attesté)
passe en `market_status=verified`, éligible au prix, projection Foil. Sans
liste fermée, l’impression reste `candidates` (`unknown_remainder`). Une carte
mate reste provisoire ; une autre langue reste hors périmètre.

**Limite du moteur v2.** Le reste est rattaché à la règle, pas à l’observation.
Une holo **sans** tampon, qui ne correspond à aucune impression documentée,
reçoit donc le prix Reverse avec le motif `observation_uncovered`, et ne
rejoint pas « Référentiel à compléter ». Restreindre le reste aux observations
compatibles demandera un moteur version 3.

**Saisie depuis la fiche.** Quand la résolution est éligible, la fiche
propose « Saisir un relevé Cardmarket lié au référentiel » : les métriques de
la famille (tendance et moyenne à 30 jours) se saisissent ensemble, avec la
date, un motif et, en option, l’empreinte de la capture. Le serveur prend la
correspondance dans sa propre résolution ; la saisie forme une seule
acquisition (`entry: transcription`) passée à `select_acquisition`.
Premier relevé saisi le 13 octobre, décision n° 1 rejouée à l’identique avec
ses pièces. Il a été saisi inversé (tendance 148,50 €, moyenne 402,43 €) :
le formulaire présentait la moyenne avant la tendance. L’ordre suit désormais
le cadre Info de Cardmarket ; le relevé inversé se corrige par une nouvelle
saisie, qui le remplace sans l’effacer.
Les pièces photographiées (JPEG, PNG) s’archivent et se sauvegardent comme
les PDF.

**Coût réel d’une preuve.** Environ une heure de recherche, dont : aucune
carte de cette extension dans l’encyclopédie officielle française de
pokemon.com (l’anglaise les a) ; Poképédia ne décrit pas les versions ;
Cardmarket bloque la capture automatisée (vérification anti-robot), d’où une
page enregistrée par le propriétaire en deux minutes. Pour les éditions
anciennes en français, la photo d’exemplaire et la page Cardmarket filtrée
sont les pièces réalistes.

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

Les [listes officielles de départ](PRINT_REFERENCE_PROPOSAL-2026-10-13.md#sources-de-départ)
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
