# Évaluation des logiciels de collection existants

> **Pour qui :** toute personne qui se demande pourquoi Lilydex n'est pas construit sur un logiciel libre existant.
> **Vous y trouverez :** la recommandation, ce qui a été testé, la comparaison avec les besoins de Lilydex, les constats par logiciel et la façon de reprendre les essais.
> **Statut :** rapport daté du 4 octobre 2026, fait sur des copies de données, après l'[instantané initial](RECOVERY.md) et sa restauration. Il n'est pas tenu à jour ; la décision qui en découle est la [fiche 0001](decisions/0001-application-maison.md). Le projet s'appelait alors pokeprice.

**Recommandation : compléter pokeprice avec une application de gestion légère,
FastAPI et SQLite. Aucun des trois candidats n'est directement adapté à nos
exemplaires physiques, à leurs corrections et au suivi de leur vente.**
PokéCollect serait le candidat le plus intéressant à adapter s'il fallait
reprendre une interface et un scan existants, mais le fork resterait conséquent.
Cette recommandation ne constitue pas une mise en œuvre de l'étape 2.

## Périmètre réellement testé

| Candidat | Version figée | Vérification effectuée |
| --- | --- | --- |
| [Bindarr](https://github.com/thenotoriousJeremy/bindarr/tree/b9c2c4ad4985c532ac00dfbf067e45b4c69b95a0) | 1.8.6 — `b9c2c4ad4985c532ac00dfbf067e45b4c69b95a0` | Installation, compilation, API, import, rangement, photos, export, sauvegarde SQLite et interface ordinateur |
| [PokéCollect](https://github.com/Trust1509/pokecollect/tree/b6ab4570291995466d4580ba884c9e3fbe114878) | Version applicative 1.9.2 — `b6ab4570291995466d4580ba884c9e3fbe114878` | Installation, compilation, API, création, photos, collections, export, sauvegarde/restauration et interface mobile simulée |
| [PokéCollector](https://github.com/Git-Romer/pokecollector/tree/d18db13770cebf6cc800ea9569bec3f37b9df533) | `d18db13770cebf6cc800ea9569bec3f37b9df533` | Lecture du modèle, des routes de collection, des photos et du journal de transactions ; pas d'installation ni de test d'interface |

Les deux installations utilisent Node 22.22.3. PokéCollect utilise Python
3.12.9 et PostgreSQL 18.6 dans un répertoire isolé ; son Compose prévoit
PostgreSQL 16.3. L'essai ne valide donc pas son déploiement Docker officiel.
Le service Docker de la machine était inactif ; aucun service système n'a été
installé ou démarré. Les serveurs d'essai écoutaient uniquement sur `127.0.0.1`.

L'échantillon comprend **20 exemplaires**, avec trois Pikachu 5/12, deux Zarbi L,
deux variantes d'Arbok, des cartes FR/EN/JA, cinq prix absents, des références et
PV corrigés et une identité non résolue. Les exclusions sont dans un fichier
séparé ; aucune carte au verso n'a été ajoutée au stock d'essai.

Aucun nouvel OCR, appel Gemini payant ou envoi de photo à un fournisseur n'a été
effectué. Au premier démarrage, Bindarr a téléchargé des catalogues publics ;
les appels aux fournisseurs ont ensuite été désactivés par les wrappers d'essai.
Les adaptations d'import sont des scripts autour des API existantes, sans
modification fonctionnelle du code des candidats.

Les 368 fichiers de l'instantané, dont les 80 photos, étaient inchangés après
les essais : contrôle d'intégrité (`outputs/evaluation/source_integrity.json`, hors du dépôt public).
Les mises à jour de documentation postérieures sont naturellement hors de cet
instantané. Les données et preuves des essais restent dans `outputs/evaluation/`.
Un contrôle final (`outputs/evaluation/final-source-integrity.json`, hors du dépôt public) confirme
que seuls le README et la roadmap archivés ont changé, pour documenter ces
résultats ; les autres fichiers et les 80 photos restent identiques.

## Comparaison avec les besoins de Lilydex

| Critère | Bindarr | PokéCollect | PokéCollector, lecture du code uniquement |
| --- | --- | --- | --- |
| Exemplaire durable et provenance des corrections | Entrées distinctes, mais import/export incomplet et pas d'historique adapté | Fiche distincte par carte ; import de provenance et historique à ajouter | Quantités regroupées selon les attributs ; modèle à compléter pour chaque exemplaire |
| Photo personnelle propre à chaque exemplaire | Photo commune à l'édition | 20 chemins de photos distincts ; affichage actuellement défectueux | Photo commune à une édition pour un utilisateur |
| Langues, états, variantes et emplacement | Langues/variantes possibles ; grades à remapper ; placement par API supplémentaire | Langues/états/variantes possibles ; positions en collection conservées | Modèle riche ; fidélité aux données de la collection non testée |
| Hors catalogue et prix réellement inconnu | Références locales possibles ; prix absent converti en zéro dans l'import essayé | Référence manuelle possible ; cinq prix absents conservés | Cartes personnalisées possibles ; import/prix non testés |
| Consultation privée et plusieurs rôles | API authentifiée ; illustrations accessibles sans connexion ; rôles à adapter | API authentifiée ; images accessibles sans connexion ; compte de gestion unique | Photos protégées côté API ; rôles et déploiement non testés |
| Sauvegarde complète et export HTML autonome | SQLite vérifié ; fichiers photo à sauvegarder séparément ; export HTML de pokeprice à intégrer | ZIP restauré avec toutes les tables et 40 images ; export HTML de pokeprice à intégrer | Non testé |
| Réservations, vente par exemplaire, frais et retours | À développer | À développer | Journal d'échanges/transactions utile ; parcours complet et réservation non validés |

Une API qui exige une connexion n'assure pas à elle seule la confidentialité des
photos. Les URL d'images de Bindarr et PokéCollect ont répondu **HTTP 200 sans
authentification** dans l'essai. Pour un usage privé, ces chemins doivent eux
aussi être protégés, dans l'application ou dans un proxy configuré pour cela.
Il s'agit d'un constat sur les configurations locales testées, pas d'un audit
de sécurité exhaustif.

## Bindarr : bon rangement, migration insuffisante

L'import JSON adapté à son format accepte les 20 entrées. Le même import relancé
porte le total à **40** : il faut ajouter la correspondance d'identifiants
et un import relançable sans doublons. Les emplacements et notes fournis dans
ce payload ne sont pas repris : **0/20** pour chacun. Des appels supplémentaires
ont permis de placer les 20 entrées dans leurs albums, pages et pochettes.
Cela distingue une limite de l'import natif d'une impossibilité de rangement.

L'export JSON contient les références et emplacements, mais ne restitue ni
l'identifiant de l'entrée physique, ni les notes, ni la devise. Un aller-retour
par cet export ne suffit donc pas à conserver la source de vérité de la collection.
L'édition de Kirlia par la route de modification d'un exemplaire a répondu
HTTP 200 tout en conservant l'ancien identifiant catalogue et l'ancien numéro :
cette route ne permet pas la correction d'identité essayée.

Les cinq valeurs absentes deviennent `0`, affiché comme un prix. Les montants
EUR importés ont pris la devise USD par défaut. Deux Arbok de variantes
différentes ont également partagé la valeur de la première édition mise en
cache. Ces défauts concernent le parcours de migration essayé ; ils ne prouvent
pas que tous les fournisseurs ou tous les parcours de prix de Bindarr se
comportent ainsi. La provenance, date, métrique, devise et variante devront
être conservées explicitement.

La photo personnelle est attachée à l'identifiant de l'édition. Charger une
deuxième photo de Pikachu remplace la première pour les trois exemplaires.
Cela demande une évolution du modèle pour documenter séparément leur état
et les vendre avec leur propre photo.

La sauvegarde SQLite téléchargée contient 20 exemplaires et passe
`PRAGMA integrity_check`. Les fichiers d'illustrations restent hors de cette
sauvegarde. La recherche « Pikachu » dans l'interface française donne une
édition et **3 exemplaires**, ce qui convient à la consultation des doublons.
L'interface de Bindarr n'a été validée que sur ordinateur pendant cet essai.

Preuve : bindarr-results.json (`outputs/evaluation/bindarr-results.json`, hors du dépôt public).
Code examiné : `backend/src/routes/importExport.js`,
`backend/src/routes/collection.js`, `backend/src/backup.js` dans la version figée.

## PokéCollect : meilleur point de départ, plusieurs adaptations

La création des 20 cartes par API et leur rangement en trois collections ont
fonctionné. Chaque carte conserve sa propre photo ; les cinq prix absents
restent `NULL`. Une correction de numéro peut conserver la même fiche.
La recherche « Pikachu » affiche les trois exemplaires séparément.

Le schéma de création ignore cependant les identifiants TCGdex fournis :
**0 conservé sur 18 transmis**. Un enrichissement ultérieur pourrait retrouver
un identifiant en ligne, mais ne remplace pas une migration fidèle de nos
références déjà vérifiées. Les identifiants d'origine, statut de validation,
PV et historique de corrections n'ont pas de champs dédiés dans ce parcours.
Les notes de correction sont conservées, ce qui ne constitue pas un historique
structuré. Un adaptateur et une évolution du schéma restent nécessaires.

Les applications ne connaissent pas le statut `unresolved`. L'énergie
encore à vérifier possède une référence et un prix candidats dans les sources :
les transmettre comme une fiche ordinaire rend cette incertitude invisible.
L'import de production devra garder le statut et exclure le prix candidat des
valeurs confirmées, pour les deux logiciels.

L'export CSV restitue les champs des cartes, mais pas leur disposition dans les
collections. Le **ZIP complet** inclut celle-ci. Une restauration réelle dans
l'installation jetable a conservé **toutes les tables et les 40 fichiers
d'images à l'identique**, vérifiés par comparaison après restauration.

Le défaut de photos dans l'interface est reproductible : `imageUrl()` ajoute
`?v=…`, tandis que le `remotePatterns` des images locales impose `search: ""`.
La photo répond directement HTTP 200 ; l'optimiseur Next répond 200 sans ce
paramètre et **400 avec le paramètre**, avec le message
`"url" parameter is not allowed`. C'est un bug circonscrit et réparable,
distinct des adaptations de stock et de provenance.
Sources figées : [imageUrl](https://github.com/Trust1509/pokecollect/blob/b6ab4570291995466d4580ba884c9e3fbe114878/web/src/lib/utils.ts#L90-L99),
[configuration des images](https://github.com/Trust1509/pokecollect/blob/b6ab4570291995466d4580ba884c9e3fbe114878/web/next.config.js#L73-L83).

Le rendu étroit a été observé dans le navigateur, sans débordement horizontal,
avec les photos défectueuses. Ce n'est pas une validation sur Android physique.
L'interface est en allemand/anglais ; une traduction française reste à faire.
Le compte de gestion est unique dans la configuration standard. Les rôles
lecteur/gestionnaire, le cycle de vente et l'export HTML autonome sont à ajouter.

Preuves : pokecollect-results.json (`outputs/evaluation/pokecollect-results.json`, hors du dépôt public),
diagnostic des images (`outputs/evaluation/pokecollect-image-regression.json`, hors du dépôt public),
capture en largeur mobile (`outputs/evaluation/screenshots/pokecollect-owned-mobile.png`, hors du dépôt public).

## PokéCollector : journal intéressant, photos trop regroupées

La collection regroupe les quantités par utilisateur, édition, variante,
langue, état et autres attributs. Une nouvelle acquisition compatible augmente
une quantité. Cela diffère du besoin d'un identifiant durable pour chaque
carte physique, même si deux cartes ont les mêmes attributs.

`CollectionCardPhoto` impose une photo par couple utilisateur/édition : deux
exemplaires de la même édition partagent cette photo. Le journal `Trade` /
`TradeItem` apporte des mouvements entrants/sortants, quantités, valeurs, notes
et références à l'origine. Il serait utile pour les échanges et ventes simples,
mais ne démontre pas à lui seul la réservation, les frais, l'expédition et
les retours nécessaires.
Source : [modèles de la version examinée](https://github.com/Git-Romer/pokecollector/blob/d18db13770cebf6cc800ea9569bec3f37b9df533/backend/models.py).

Ces écarts de modèle sont visibles sans installation. Ils ne justifient pas
un troisième essai complet dans la limite prévue. Les possibilités de cet
outil n'ont donc pas été vérifiées en fonctionnement.

## Réutilisation et effort restant

Bindarr contient une licence MIT vérifiée. PokéCollect annonce MIT dans son
README, mais aucun fichier LICENSE/COPYING n'a été trouvé dans le checkout :
clarifier la licence avant de reprendre son code. PokéCollector contient une
licence AGPL-3.0 ; ses conditions doivent être prises en compte pour un fork
hébergé. Ce contrôle porte sur les versions figées, sans analyse juridique.

| Direction | Travail restant déterminant | Avis |
| --- | --- | --- |
| Adapter Bindarr | Migration fidèle, photos par exemplaire, corrections d'identité, prix/provenance, rôles privés et ventes | Le gain du rangement et de SQLite compense mal les changements de modèle nécessaires |
| Adapter PokéCollect | Import fidèle, historique, rôles/photos privés, français, ventes, export autonome ; bug photo et licence à résoudre | Meilleur candidat si son scan et son interface deviennent prioritaires ; PostgreSQL reste une dépendance |
| Adapter PokéCollector | Exemplaires et photos distincts, migration/historique, parcours de vente à compléter ; exploitation PostgreSQL et AGPL | Journal utile, mais pas de raccourci démontré pour l'inventaire de la collection |
| Compléter pokeprice | Backend, interface de gestion, comptes et ventes ; réutiliser les données, corrections, photos et export autonome | Direction recommandée pour le périmètre de l'époque |

Il reste du développement dans toutes les options. L'essai n'établit pas
qu'un fork serait plus rapide qu'une application ciblée. L'estimation initiale
de la roadmap reste un ordre de grandeur à préciser par jalon, sans engagement
de délai. Aucun tarif d'hébergement n'a été arrêté : la comparaison couvre les
dépendances à exploiter, pas un devis fournisseur.

SQLite reste cohérent avec un seul serveur et quelques utilisateurs écrivant
peu simultanément, avec stockage persistant et sauvegardes. PostgreSQL deviendra
pertinent si les contraintes évoluent. Voir les
[usages recommandés par SQLite](https://www.sqlite.org/whentouse.html).

## Prochain jalon proposé à l'époque

*Cette section décrit la suite telle qu'elle était prévue le 4 octobre 2026 ;
elle a été réalisée depuis (voir le [journal](JOURNAL.md)).*

Étape 2 de la [roadmap](ROADMAP.md) : définir les éditions, exemplaires durables,
corrections, prix sourcés et mouvements de stock, puis importer les **401 cartes**
dans une base SQLite avec correspondance vers les sources. Vérifier une seconde
importation sans doublons, les 22 prix absents, l'identité non résolue, les
variantes, corrections et photos. Livrer le rapprochement avant d'étendre
l'interface ou de choisir l'hébergement.

La copie externe de l'instantané reste à effectuer. Les essais n'incluent ni
audit de sécurité complet, ni caméra/OCR, ni fonctionnement hors connexion des
candidats, ni déploiement Internet, ni test sur Android physique. L'export
HTML autonome existant reste conservé et sa régénération hors réseau est validée.

## Reprendre ou auditer les essais

Les clones sont sous `outputs/evaluation/solutions/`, les runtimes et données
sous `outputs/evaluation/runtime/`. Les scripts `run_bindarr.cjs` et
`run_pokecollect.py` fixent les chemins isolés et désactivent les fournisseurs.
`probe_solutions.py` couvre les API ; `probe_restore_and_identity.py` compare
la restauration et teste la modification d'identité. Ces probes **modifient les
bases jetables** et ne doivent pas être lancées contre la collection réelle.
Ils sont des preuves d'essai local, pas un importateur de production.

L'échantillon et ses hashes sont dans
step0/recovery-check/sample/ (`outputs/evaluation/step0/recovery-check/sample/`, hors du dépôt public).
Les résultats JSON et sauvegardes permettent d'examiner les constats sans
relancer les applications. Les serveurs temporaires sont arrêtés à la fin de
l'évaluation ; aucune application n'est publiée sur Internet.
