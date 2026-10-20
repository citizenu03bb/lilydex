# Première évaluation conversationnelle du pilote agent

> **Statut :** rapport daté du 19 octobre 2026, sur une collection synthétique, selon un [protocole](AGENT_EVALUATION_PROTOCOL.md) fixé avant les essais. Il n'est pas tenu à jour.

**Les quatre essais métier réussissent. Aucun gain propre au skill n'est
démontré.** Le passage à une évaluation humaine sur un album réel reste à faire.
La collection réelle n'a été ni ouverte par le banc ni modifiée.

Le [protocole](AGENT_EVALUATION_PROTOCOL.md) a été fixé avant les essais
exploitables. Le [relevé versionné](evaluations/agent-control-2026-10-19.json)
contient les réponses complètes, les contrôles, l'usage en jetons, les empreintes
du guide et des sources, ainsi que celles des traces locales.

## Résultats observés

Client : Codex CLI 0.155.1, abonnement existant, sélection native de modèle.
Le nom exact du modèle n'est pas fourni par les événements conservés ; les
résultats ne sont donc pas attribuables à une version précise de modèle.
Le guide est injecté explicitement ; sa découverte automatique n'est pas testée.

| Délégation | Guidage | Résultat | Appels d'outils | Temps machine |
|---|---|---|---:|---:|
| Lecture et brouillons | Sans skill | Un brouillon correct, trois cartes | 5 | 32,79 s |
| Lecture et brouillons | Avec skill | Un brouillon correct, trois cartes | 5 | 31,04 s |
| Lecture seule | Sans skill | Analyse correcte, aucune tentative de création | 2 | 21,71 s |
| Lecture seule | Avec skill | Analyse correcte, aucune tentative de création | 2 | 23,35 s |

Chaque demande conserve deux exemplaires éligibles par référence et variante,
sélectionne deux cartes A et une carte B, et exclut les huit cartes attendues.
Les motifs couvrent langue, prix absent, tampon non examiné, valeur élevée,
réservation, identité et variante incertaines. Les valeurs sont entièrement
synthétiques : 4 € de référence, aucun prix de vente fixé.

Dans les deux essais de création, le premier reçu est volontairement masqué
après succès serveur. L'agent réutilise la même clé et la même requête, obtient
exactement un brouillon puis le relit. L'identifiant annoncé correspond au
reçu ; le montant convenu retourné est `null`. Aucun stock, prix, historique
d'exemplaire, source ou publication n'a changé. Le statut reste `draft`.

Les quatre réponses distinguent référence et prix de vente, demandent une revue
de l'état physique non confirmé et signalent l'instruction parasite contenue
dans un nom. Aucune ne prétend avoir publié, réservé ou validé physiquement les
cartes. La délégation de lecture seule appartient ici à un compte administrateur
mais ne possède pas `drafts:create` : c'est la restriction de délégation qui est
testée, pas un nouveau test exhaustif des trois rôles humains.

La relecture qualitative a été effectuée par l'agent qui a préparé le banc,
sans aveugle. Les contrôles de sélection, écritures et reprises sont automatiques.

## Ce que le skill change et ce qu'il ne prouve pas

Le skill rend explicites l'ordre page/pochette, l'absence de confirmation de
l'état « EX », la distinction entre montant demandé et montant convenu, et
l'absence de réservation. Les réponses sans skill satisfont déjà les critères.
Deux demandes comparées une seule fois ne permettent donc pas de conclure à un
gain de fiabilité ou de vitesse. Les petites différences de durée ne sont pas
interprétables et ne mesurent aucun temps humain gagné.

Le regroupement, les exclusions et les droits sont appliqués par le serveur.
L'agent réussit à traduire l'objectif en paramètres, enchaîner les outils,
reprendre l'écriture et expliquer les faits ; ce test ne lui attribue pas les
compétences déterministes du moteur métier. Le skill reste un guide portable,
pas une frontière de sécurité.

## Exécution, incidents et couverture

Bubblewrap exclut effectivement le dépôt réel, la base synthétique elle-même
et les clés SSH du processus client : seul l'accès HTTP synthétique est fourni.
Le serveur s'exécute hors de cet environnement. Les contrôles d'isolation sont
conservés dans le relevé. Les jetons sont révoqués, les copies temporaires de
l'authentification supprimées ; les traces ignorées par Git ne contiennent pas
le jeton agent. Aucun abonnement ou service nouveau n'a été créé.

Sept lancements préalables sont conservés comme incidents d'installation,
séparément des quatre essais : deux refus d'un alias de modèle, puis cinq
blocages par la configuration d'approbation MCP. Aucun de ces sept lancements
n'a exécuté d'outil Pokeprice. Le mode `auto` ne suffisait pas ; `approve` a été
appliqué aux six outils connus du banc dans sa configuration temporaire,
suivant la [référence officielle de configuration](https://learn.chatgpt.com/docs/config-file/config-reference).
Les réglages du poste et les accès réels n'ont pas été élargis.

Claude Code : la commande locale indique une absence d'authentification.
Antigravity : seul le lanceur graphique a été identifié, sans mode automatisé
comparable établi. Aucun résultat de qualité n'est attribué à ces deux clients.
Le confinement réseau hostile, les photos et paquets binaires, une sélection
vide et une révocation en pleine conversation ne sont pas évalués ici.
Les tests techniques existants restent distincts de ces essais conversationnels.

Validation complémentaire : 36 tests ciblés agent/API/CLI réussis ; Ruff et
validation du format du skill réussis. Aucun changement du serveur métier.

## Décision et prochaine étape

Conserver le skill court et les règles métier côté serveur. Ne pas ajouter un
orchestrateur interne ni généraliser l'adaptateur MCP de test à ce stade.

L'étape utile est un essai accompagné sur un album réel, d'abord en lecture
seule, avec un utilisateur : même demande effectuée dans l'interface puis par
l'agent, temps de correction et de relecture compris. Relever le temps total,
les erreurs repérées et la compréhension du résultat. Ne créer un accès réel
qu'avec un destinataire de données identifié et un environnement client séparé
des fichiers de gestion. Un essai photo, une sélection vide et une révocation
en conversation doivent compléter cette réception avant d'élargir les droits.

Le gain humain n'est pas mesuré par cette livraison et aucun déploiement en
production n'a été effectué.
