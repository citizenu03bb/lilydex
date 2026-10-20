# Documentation de Lilydex

> **Pour qui :** toute personne qui cherche une page de la documentation.
> **Vous y trouverez :** chaque page, rangée selon ce que vous venez faire.

Le [glossaire](GLOSSAIRE.md) définit les mots du projet. Ce qui a changé, et
quand, est dans le [journal](JOURNAL.md).

## Découvrir le projet

| Page | Ce que vous y trouvez |
|---|---|
| [IA et vision](IA-VISION.md) | Ce que font les modèles, leurs mesures, leurs limites et leurs garde-fous |
| [Banc d'essai](BANC-RECONNAISSANCE.md) | La méthode et les résultats des mesures de reconnaissance |
| [Fiches de décision](decisions/README.md) | Pourquoi Lilydex est construit ainsi |
| [Feuille de route](ROADMAP.md) | Le MVP, ses jalons et ce qui est prévu ensuite |

## Utiliser l'application

| Page | Ce que vous y trouvez |
|---|---|
| [Guide de l'application](APP.md) | Démarrer, saisir des cartes, photos, variantes, prix, lots, imports et exports |
| [Référence des commandes](COMMANDES.md) | Chaque commande et ses options, générées depuis le code |
| [Valeur en jeu et file d'examen](VALUATION.md) | Comment Lilydex repère les cartes qui méritent une décision humaine |
| [Aide à l'état](CONDITION-ASSESSMENT.md) | Le verso et la proposition d'état |
| [Vitrine](CATALOGUE.md) | La partie publique : publication, prix affiché, clients et réservations |
| [Guide du référentiel](PRINT_REFERENCE_GUIDE.md) | Comment Lilydex décide quelle version d'une carte vous avez, preuves à l'appui |
| [Contrat du référentiel](PRINT_REFERENCE_CONTRACT.md) | Les règles exactes du référentiel et ses scénarios de réception |
| [État du référentiel](PRINT_REFERENCE_IMPLEMENTATION.md) | Ce qui est mis en œuvre et ses limites |
| [Pilote agent](AGENT_CONTROL.md) | Déléguer un album à un agent IA, qui prépare des brouillons de lots |

## Héberger et exploiter

| Page | Ce que vous y trouvez |
|---|---|
| [Héberger Lilydex](DEPLOYMENT.md) | Installer le serveur, HTTPS, l'option vision, vérifier une mise en ligne |
| [Sauvegardes](DAILY-BACKUPS.md) | La sauvegarde quotidienne, la copie chiffrée sur Drive et la restauration |
| [Données personnelles](RGPD.md) | Registre des traitements, demandes des personnes, violation de données |
| [Sécurité](../SECURITY.md) | Signaler une faille et ce que fait l'application |

## Contribuer

| Page | Ce que vous y trouvez |
|---|---|
| [Contribuer](../CONTRIBUTING.md) | Installer, tester, écrire la documentation |
| [Consignes pour les agents](../AGENTS.md) | Les règles que suivent les agents de code |

## Rapports datés

Ces pages consignent une vérification à un moment donné ; elles ne sont pas
tenues à jour.

| Page | Ce que vous y trouvez |
|---|---|
| [Audit de sécurité](AUDIT-SECURITE.md) | L'audit fait avant la publication du code |
| [Évaluation des logiciels existants](EVALUATION.md) | Trois logiciels libres essayés avant d'écrire l'application |
| [Instantané initial](RECOVERY.md) | La copie figée des fichiers d'origine et sa restauration |
| [Audit des photos](AUDIT-PHOTOS.md) | La revue des découpes et des identités lues des classeurs |
| [Plan du pilote agent](AGENT_CONTROL_PLAN.md) | L'apport attendu par rôle et les extensions possibles |
| [Protocole d'évaluation du pilote](AGENT_EVALUATION_PROTOCOL.md) et [résultats](AGENT_EVALUATION_RESULTS.md) | Le pilote évalué sur une collection synthétique |
| [Protocole de la séance de vérification](AGENT_REVIEW_EVALUATION.md) et [résultats](AGENT_REVIEW_RESULTS.md) | Un agent prépare cinq contrôles sur un album réel figé |

## Archive

Les documents qui décrivent un état révolu sont dans [archive/](archive/),
chacun avec un bandeau : la feuille de route d'origine, le tunnel temporaire,
le plan d'améliorations d'origine, la proposition d'origine du référentiel et
l'exploration de synchronisation, non retenue.
