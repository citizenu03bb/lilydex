# Pilotage par agent — plan révisé

Révision du 19 octobre 2026, sur le code à `8e6a36d` (schéma 17).
**Statut : recommandation de mise en œuvre, non implémentée.** Elle remplace
l’ordre et les prérequis proposés le 18 octobre. Les jalons A1–A5 de
[l’archive](archive/ROADMAP-2026-10-05.md#pilotage-par-agents-ia--ajouté-le-5-octobre-2026)
restent des capacités possibles, pas une liste à développer intégralement.

## Ce que l’agent apporte à la personne

L’agent aide à passer d’une intention à un résultat : comprendre une demande
exprimée normalement, retrouver les informations utiles, les rapprocher,
expliquer les points incertains et préparer le travail suivant. Il permet de
demander « prépare-moi un lot de mes doublons » sans devoir connaître chaque
filtre, ouvrir chaque fiche et recopier les informations à la main.

Les exemples suivants décrivent la valeur visée. Ils ne sont pas tous inclus
dans le premier pilote et ne décrivent pas des fonctions déjà disponibles.

| Personne | Compétences apportées par l’agent | Exemple concret |
|---|---|---|
| **Administrateur** | Aide au diagnostic et à l’organisation : résumer la situation, repérer les points à contrôler, expliquer leurs conséquences et préparer un ordre de travail. | « Qu’est-ce qui mérite mon attention dans la collection cette semaine, et pourquoi ? » L’agent prépare une synthèse à partir des informations auxquelles ce compte a accès. |
| **Gestionnaire** | Aide à la préparation : rapprocher les exemplaires, signaler les incohérences, composer des lots selon des critères et rédiger des annonces à relire. | « Prépare un lot de doublons français disponibles, en gardant un exemplaire de chaque référence et en écartant les cartes qui demandent une vérification. » |
| **Utilisateur en consultation** | Aide à la recherche et à la compréhension : poser des questions, retrouver des cartes, comparer leurs caractéristiques et comprendre les prix ou les incertitudes affichés. | « Montre-moi les Pikachu de cette collection et explique pourquoi leur valeur de référence diffère. » Les informations restent celles autorisées à la consultation. |

Pour un **client de la vitrine**, l’aide serait différente : chercher et
comparer les cartes publiées selon ses critères, puis préparer une sélection.
Elle utiliserait exclusivement le catalogue public et les données propres à
ce client. Ce parcours n’est pas inclus dans le pilote de gestion ; son
identité ne donne aucun accès à l’inventaire privé.

Les compétences communes sont donc la recherche en langage courant, la
synthèse, le rapprochement, l’explication et la rédaction. La personne apporte
son objectif, ses préférences et les observations physiques nécessaires.
L’application reste la référence pour les quantités, les prix enregistrés et
les droits. L’agent doit dire quand une information manque plutôt que compléter
un état ou un prix par supposition.

Le rôle de la personne et sa délégation déterminent ce que l’agent peut
consulter et exécuter. Un administrateur peut recevoir une aide plus large ;
un gestionnaire, une aide sur les opérations de gestion ; un lecteur, une aide
à la consultation. Créer une suggestion ou un brouillon peut être autorisé
directement. Confirmer un examen physique, publier ou engager une opération
de vente demande les droits et décisions prévus pour cette action.

Le premier bénéfice à mesurer est concret : **obtenir une préparation utile
en passant moins de temps à chercher, comparer et recopier, sans augmenter le
temps de vérification.** Le nombre d’outils exposés ne mesure pas cette valeur.

## Ce que la revue remet en question

Le premier plan détaillait une plateforme avant de démontrer un gain pour le
propriétaire. Il transformait plusieurs extensions en prérequis et durcissait
la règle originelle « décision humaine lorsque requise » en approbation de
presque toute application. La séparation des droits reste nécessaire ; elle
ne justifie pas ce périmètre initial.

| Choix du premier plan | Révision recommandée et raison |
|---|---|
| A1 complet avant la lecture | Séparer l’identité/portée des jetons de la refonte des confirmations. Une route de lecture ne passe pas par les écritures à corriger. |
| Lecture seule = livraison utile | La lecture est un moyen. La réception doit montrer un lot préparé correctement et du temps de relecture économisé. |
| Plans génériques avant le premier brouillon | Commencer par une commande métier bornée. Ne pas construire un moteur de plans, décisions et compensation sans plusieurs cas réels. |
| Approbation de chaque application | Une délégation peut autoriser directement la création de suggestions ou brouillons privés. Réserver la décision unitaire aux effets qui l’exigent. |
| Registre général d’idempotence avant toute création | Une clé unique et une empreinte de contenu, liées à la transaction du seul objet créé, suffisent au premier cas. Généraliser après réutilisation démontrée. |
| Worker, reprise et budgets au programme initial | L’agent client orchestre déjà la tâche. Aucun nouvel appel modèle côté serveur n’est nécessaire pour préparer un lot depuis les données existantes. |
| MCP après toute l’API | Essayer le vrai client dès le début. Un petit pont MCP peut être nécessaire tôt ; il peut aussi être inutile si HTTP/CLI suffit. |
| Sauvegarde complète restaurée avant chaque lot | Disproportionné pour ajouter un brouillon sans modifier le stock. Conserver sauvegarde avant migration, test de restauration et protections adaptées aux futures mutations de masse. |
| `analysis:external` comme séparation des flux | Ce droit ne contrôle que les appels fournisseurs du serveur. Une photo remise au client agent peut déjà être envoyée à son modèle. Le client et ses flux doivent être connus dès le pilote. |
| 11–17 jours comme engagement global | Cette somme portait sur un ensemble de capacités non justifiées. Estimer le pilote seul, puis décider des extensions sur les résultats. |

Le plan initial mélangeait aussi adaptateur MCP et opérations locales
sensibles (import/restauration). Ces opérations restent des chantiers distincts ;
les exposer n’est pas une condition de réussite du pilotage.

## Premier usage proposé

**« Dans cet album, prépare un lot de doublons candidats disponibles, conserve
un exemplaire de chaque référence retenue, explique les exclusions et rédige
un brouillon d’annonce. Ne réserve et ne publie rien. »**

C’est une hypothèse de pilote à éprouver, pas une nouvelle priorité produit
considérée comme déjà validée. Elle peut soutenir le travail de lots de M4
sans attendre l’ensemble du MVP. Son coût doit être comparé aux besoins encore
ouverts de la [roadmap](ROADMAP.md).

Le résultat attendu contient :

- les UUID des exemplaires retenus, les versions examinées et le motif de la
  sélection ; aucun exemplaire physique n’est fusionné avec un autre ;
- les cartes exclues et pourquoi : réservées/vendues, déjà publiées si le
  scénario l’exclut, identité incertaine, examen nécessaire, valeur importante
  ou information insuffisante ;
- les prix disponibles avec source, date et métrique, sans transformer une
  référence catalogue en prix de vente ni une absence de prix en zéro ;
- un texte relisible, les éléments à compléter et les liens vers les fiches.
  Une estimation d’état ou de variante ne devient pas une affirmation vérifiée.

La définition des doublons et la sélection ne reposent pas sur le seul nom.
Référence, langue, finition et marques pertinentes doivent être compatibles ;
une observation inconnue ne vaut pas égalité confirmée. Réutiliser les calculs
serveur de valeur en jeu et de contrôle, sans réimplémentation dans le prompt.
L’agent explique et compose à partir de ces faits. Il ne certifie pas les
reverses, l’état ou les prix par son raisonnement.

### Mesurer l’utilité avant d’étendre

Sur deux sélections comparables de 10 à 20 cartes, relever le temps de travail
habituel puis le temps complet avec l’agent, **relecture et corrections comprises**.
Proposition de seuil pour poursuivre : environ 30 % de temps gagné, aucune
inclusion critique erronée et aucune affirmation physique ou marchande inventée.
Ce seuil est une hypothèse de produit à valider, pas une performance acquise.

Les tests synthétiques couvrent les invariants ; un essai observé sur l’usage
réel doit ensuite vérifier le gain humain. Deux essais n’établissent pas une
fiabilité générale. Si la préparation ne fait que reformuler les filtres
existants, ou si sa correction coûte autant que le parcours actuel, arrêter ce
pilote ou changer de tâche avant de construire davantage d’infrastructure.

## Livraison 1 — Lecture bornée et essai dans le vrai client

Définir d’abord le client utilisé, la tâche et les flux de données autorisés.
L’agent doit parvenir à produire le résultat métier ci-dessus, pas seulement
obtenir une réponse HTTP 200.

### Contrat et identité nécessaires

- Un jeton propre à l’agent, de forte entropie, conservé sous forme de condensat,
  avec expiration, révocation, délégant actif, un album et des droits explicites.
  Commencer par émission/révocation via la CLI de gestion ; aucune nouvelle
  interface d’administration n’est nécessaire au pilote.
- Un routeur `/api/agent/v1` avec authentification Bearer dédiée. Ne jamais
  convertir ce jeton en session humaine ni revenir au cookie après un refus.
  Refuser les requêtes qui mélangent ces deux identifiants.
- Deux droits initiaux : lecture des données métier et, séparément, lecture des
  photos. Le client et le fournisseur auquel il peut transmettre les photos
  sont précisés dans la délégation d’usage. Le serveur ne peut pas empêcher
  leur retransmission après les avoir fournies.
- Quelques opérations typées : rechercher les exemplaires de l’album, lire une
  fiche projetée et éventuellement une photo. Ajouter un regroupement métier
  si nécessaire pour éviter que le client télécharge et retraite tout l’inventaire.
  Pas de route SQL, shell, URL ou chemin de fichier arbitraire.
- Réutiliser les lectures/calculs métier existants ; filtrer au serveur les
  ressources et champs renvoyés. Pas de données clients/acheteurs, notes privées,
  finances ou historique brut. Les comptages éventuels respectent aussi l’album.
- Schémas stricts, tailles et débit bornés, tri stable, versions, provenance et
  erreurs identifiables. Documenter ce petit contrat et ses exemples fictifs ;
  ne pas concevoir maintenant toutes les futures routes ni changer la
  pagination existante sans besoin démontré.

### Ce qui ne bloque pas cette livraison

`current_user` de `webapp.py` lit actuellement le cookie, pas le Bearer. Les
écritures de gestion peuvent donc rester fermées à l’agent sans refondre
`Store.patch`, `create_copy`, intake et capture. La provenance historiquement
classée humaine reste une limite réelle, à traiter avant d’exposer une commande
qui peut modifier ces observations ; elle n’est pas un prérequis à un GET isolé.

Le modèle de menace est explicite : l’agent utilise seulement ses outils et son
jeton ; le serveur, les comptes de gestion et les accès aux fichiers sont
considérés fiables. Le serveur peut garantir qu’un jeton agent ne confirme pas
un examen physique. Un cookie ne prouve ni la présence d’une personne ni la
réalité de son examen : il attribue une déclaration à un compte.

### Client et MCP

Tester le client réel dès cette livraison. S’il accepte HTTP ou une CLI bornée,
utiliser ce chemin. S’il nécessite MCP, livrer seulement les quelques outils
nécessaires, dans un adaptateur appelant la même API. Ne pas attendre un worker
ou un moteur de plans pour vérifier que le client sait lire une photo et
exploiter les réponses. Le protocole ne décide d’aucun droit métier.

**Réception :** jeton sans cookie, résultat métier relisible dans le client,
autre album et routes humaines refusés, secret absent des journaux, photos
accessibles seulement sur permission. Les données courantes ne changent pas.

## Livraison 2 — Une seule écriture déléguée, choisie après l’essai

Si la première livraison est utile, ajouter **soit** un dépôt de suggestion,
**soit** la création d’un lot en brouillon. Ne pas construire les deux parcours
et une abstraction générale avant de connaître le besoin dominant.

| Besoin constaté | Implémentation minimale |
|---|---|
| Conserver une proposition pour la revoir | Table de suggestions ajoutées séparément : agent imposé par le serveur, exemplaires et versions, valeurs proposées, preuves, motif. Aucun appel aux écritures de fiches ou de prix. Affichage simple, sans bouton d’application automatique. |
| Retrouver le lot dans le parcours Ventes | Commande `create_sale_draft` strictement typée, réutilisant `Store.create_sale(..., _db=...)` et l’affichage existant. Ajouter versions attendues, sélection bornée et attribution structurée sur cette commande. Aucun passage à un statut autre que `draft`. |

Pour les brouillons, vérifier les conventions actuelles des montants de vente
avant réutilisation : un prix demandé peut rester inconnu ; ne pas présenter
un montant technique par défaut comme une estimation ou un prix convenu.
Ne pas réutiliser `/api/listings` : ces routes publient dans la vitrine.

### Garanties proportionnées

- `suggestions:create` ou `drafts:create` autorise directement l’objet privé
  correspondant. Pas de confirmation supplémentaire à chaque création déjà
  couverte par la délégation. La relecture précède les futurs effets métier.
- Une clé client unique par agent et opération, avec empreinte du contenu :
  réessai identique → même objet ; contenu différent → conflit. Objet et reçu
  sont enregistrés dans la même transaction SQLite. Vérifier l’autorisation
  actuelle avant de restituer un résultat existant ; dans ce cas, ne pas
  réexiger les anciennes versions des fiches ni recréer l’objet.
- Vérifier la portée et toutes les versions sous transaction ; recontrôler la
  disponibilité de chaque carte pour le brouillon. Dans cette même transaction,
  revérifier jeton, délégation et droits actuels du délégant, y compris après
  un changement de rôle. Aucun mouvement de stock, attestation, prix courant
  ou publication n’est autorisé par cette commande.
- Garder les suggestions séparées des valeurs confirmées. Une insertion dans
  leur table ne doit jamais être interprétée comme une observation humaine
  par le moteur de référence.
- Un brouillon mentionne les versions examinées ; une modification ultérieure
  le signale comme à revoir. Le paquet d’annonce porte un état et une date
  explicites : figer le contenu ou annoncer une régénération. Ne pas promettre
  un contenu approuvé immuable si le générateur relit les fiches vivantes.
  L’accès aux images embarquées demande aussi le droit de lecture des photos
  et la portée sur chaque exemplaire ; créer un brouillon ne donne pas ce droit.
- Pour une suggestion, tester que les tables métier sont inchangées. Pour un
  lot, seules les tables de brouillons, liens et audit autorisés changent.
  Une réponse perdue ou deux créations concurrentes ne créent pas deux lots.

### Sauvegarde et retour arrière

Sauvegarder avant migration et tester la restauration des nouveaux objets sur
une base temporaire. La sauvegarde SQLite inclut les nouvelles tables ; tout
nouveau fichier durable entre dans le manifeste et son validateur. Neutraliser
les jetons dans l’archive et à la restauration. Aucun travail payant ne doit
être relancé depuis une archive.

Ne pas archiver puis restaurer toutes les photos avant chaque suggestion ou
création de brouillon : ces opérations ajoutent des objets sans remplacer les
fiches. Conserver les sauvegardes quotidiennes et les règles existantes pour
les mutations importantes. `backup()` charge actuellement la base et les
photos en mémoire : le coût d’une archive complète n’est pas constant par lot.

## Extensions conditionnelles après le pilote

| Signal observé | Extension à concevoir | Garanties à conserver |
|---|---|---|
| La recopie des corrections approuvées est le vrai coût | Une commande de correction précise, puis éventuellement plans de masse | Liste positive de champs, provenance distincte, effets sur prix/attestations, versions, décision selon l’effet, transaction et idempotence. |
| Plusieurs opérations ont réellement besoin d’une décision et d’une application communes | Généralisation du mécanisme de propositions/plans | Contenu exact et preuves liés à la décision, droits actuels revérifiés, aucune application partielle. |
| Un traitement serveur nécessaire dépasse la requête ou doit continuer sans le client | Travaux persistants, baux, reprise et annulation | Tentatives identifiées, générations de bail, résultat incertain après coupure, absence de double effet. |
| De nouveaux appels modèles sont nécessaires côté serveur | Permission d’appel fournisseur et budget réservé par délégation | Délais, limites, plafond, usage observé ; pas de relance aveugle d’un appel au résultat inconnu. |
| Plusieurs clients ou exploitants ont besoin de gérer leurs accès | Interface de délégation et permissions plus fines | Révocation, expiration et contrôle des ressources appliqués au serveur. |
| Le client choisi bénéficie de MCP | Étendre le petit adaptateur déjà essayé ou l’ajouter | Même API et mêmes refus ; pas d’accès direct aux fichiers, à SQLite ou au shell. |

L’approbation dépend de l’effet. Une suggestion ou un brouillon peut être créé
sous délégation ; un examen physique ne peut pas être déclaré par le jeton
agent. Une correction d’identité peut changer le prix et demande une politique
plus stricte qu’une simple création de texte. La réversibilité seule ne suffit
pas à qualifier une action de peu risquée.

Avant toute mutation de fiche accessible à l’agent, traiter les chemins de
confirmation concernés et les appels partagés susceptibles de créer une
provenance humaine. Refuser les attestations dans les payloads agent. Une
approbation générale de plan ne vaut pas déclaration d’examen physique.
Ne généraliser le contexte structuré à toutes les commandes locales que si
cela est nécessaire à ces garanties, sans réattribuer l’historique existant.

Import, restauration complète, comptes, corbeille, publication, réservation,
vente, paiements et messages restent hors de ce pilote. Leurs futures
permissions et procédures ne sont pas implicitement accordées par le succès
d’une préparation de lot.

## Effort, arrêt et réception

Estimations initiales, à réévaluer après le premier essai client :

| Étape | Ordre de grandeur | Décision de sortie |
|---|---|---|
| Fixer scénario, client et données de réception | ½–1 jour | Le résultat attendu et les flux sont clairs. |
| Livraison 1 : accès borné, outils et essai métier | 2–4 jours | Le résultat est correct et économise du travail, ou le pilote est arrêté/recentré. |
| Livraison 2 : une écriture bornée et ses tests | 1–3 jours supplémentaires | Un objet utile rejoint le parcours de gestion sans effet non autorisé. |

Prévoir un premier essai au bout d’environ **3–5 jours**, puis décider de la
suite. Ces ordres de grandeur ne constituent pas une réduction démontrée de
l’ancien total ; ils portent sur un périmètre plus petit. Ne pas annoncer de
budget global pour les extensions avant que l’usage les justifie.

La réception automatisée utilise bases temporaires, photos synthétiques et
sources injectées, sans nouvel appel modèle payant côté serveur. Vérifier :

1. Portée, expiration, révocation, état du délégant et refus de toutes les routes
   humaines avec le seul jeton agent, y compris les confirmations.
2. Projection des champs, photos privées et absence d’accès par identifiant
   d’un autre album ; limites de lecture et de création.
3. Cas de doublons trompeurs : même nom mais référence/langue/finition différente,
   observation inconnue, prix absent, valeur importante, carte déjà réservée.
4. À la livraison 2, suggestions isolées ou brouillons sans effet sur les
   fiches, prix, attestations, stock et vitrine ; auteur imposé par le serveur.
5. Versions périmées, réponse perdue, redémarrage, double requête et même clé
   avec un autre contenu ; aucun deuxième objet ni effet métier imprévu.
6. Migration et restauration : objets présents, anciens jetons inutilisables,
   fichiers et preuves cohérents si le périmètre en ajoute.
7. Un parcours complet dans le vrai client, puis la mesure du temps humain et
   des corrections. L’essai d’usage reste distinct des tests synthétiques.

Réutiliser les suites de contrôle des routes et rôles, inventaire, workflows,
réservations, annonces et sauvegardes. Ajouter seulement les tests nécessaires
aux nouveaux accès et à la commande retenue. L’inventaire des routes distingue
explicitement les dépendances humaines et agents, sans exemption générale du
nouveau préfixe. Aucun déploiement ni changement de données réelles n’a été
réalisé par cette révision du plan.
