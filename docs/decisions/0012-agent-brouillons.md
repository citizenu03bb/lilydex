# 0012 — Le pilote agent n'écrit que des brouillons

> **Statut :** en vigueur · **Date :** 2026-10-19

**Contexte.** Un agent IA peut aider à préparer des ventes. Mais une
publication, une réservation, une vente ou une correction de fiche engage le
vendeur ou modifie la collection.

**Options.**
1. Donner à l'agent un accès opérateur à la base.
2. Un accès délégué par l'API HTTP, limité à un album, avec une clé révocable.

**Décision.** Option 2. Le client `pokeprice-agent` n'ouvre jamais la base. Il
peut consulter l'album délégué, préparer un lot prudent de doublons et créer un
brouillon visible dans **Ventes** ; les photos et le paquet d'annonce seulement
si ces accès ont été accordés. Les confirmations physiques, corrections,
réservations, publications, ventes et paiements restent humains.

**Conséquences.** Le serveur décide de ce qui est autorisé et enregistre les
faits ; l'agent ne peut pas dépasser sa délégation. Le gain réel reste à
mesurer à l'usage.

**Pour aller plus loin.** [Pilote agent](../AGENT_CONTROL.md),
[résultats de l'évaluation](../AGENT_EVALUATION_RESULTS.md).
