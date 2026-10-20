# 0014 — L’agent applique seulement les corrections déjà autorisées

> **Statut :** en vigueur · **Date :** 2026-10-20

**Contexte.** Le propriétaire demande des rattachements au catalogue et des
relevés pour des cartes sans prix. La délégation initiale ne permet que la
lecture et les brouillons. Cette décision complète la [décision initiale](0012-agent-brouillons.md).

**Options.** Donner un droit général de modification, exécuter les changements
avec les droits de l’opérateur, ou autoriser un plan précis puis laisser
l’agent l’appliquer par son propre accès HTTP.

**Décision.** Le serveur conserve un plan immuable par exemplaire et délégation,
lié à une version examinée et une empreinte. L’opérateur enregistre l’accord
explicite de la personne ; l’agent ne peut ni autoriser ni modifier ce plan.
TCGdex fournit les métadonnées et les cotations natives. Le serveur vérifie les
droits courants, la portée et la version dans la transaction d’application.
Un reçu conservé rend les reprises sans doublon.

**Conséquences.** Les écritures portent l’identité de l’agent et la provenance
du plan. Les confirmations physiques restent distinctes ; une cotation absente
reste inconnue. Une fiche modifiée demande une nouvelle revue. L’extension
nécessite une migration sauvegardée et ne donne aucun droit de publication,
réservation, vente ou paiement. Le [parcours opérateur et agent](../AGENT_CONTROL.md)
décrit les commandes ; le guide scellé de l’évaluation conserve son périmètre.
