# 0050 — L'agent de revue enregistre chaque facette établie, sauf si une photo demandée l'effacerait

> **Statut :** en vigueur, modifie la décision [0022](0022-agent-confirme-ou-demande-photo.md) · **Date :** 2026-11-25

**Contexte.** L'agent de revue juge séparément l'identité d'une carte
importée, sa variante et son état. Jusqu'ici, il n'enregistrait rien tant
qu'une seule facette restait en suspens. Une identité établie sans ambiguïté
attendait donc que les coins soient lisibles, et une variante sûre attendait
un état que les photos ne trancheront jamais. Depuis la décision
[0049](0049-etat-sans-manipulation.md), une carte dont le recto ne tranche pas
l'état reste « en l'état ». Le tout ou rien gardait aussi sa variante en
attente pour toujours. Le code justifiait ce couplage ainsi : une nouvelle
photo efface les confirmations. C'est vrai pour la variante et l'état
(nouveau recto), et pour l'état seul (nouveau verso). L'identité n'est jamais
effacée par une photo.

**Options.**
1. **Garder le tout ou rien** : simple, mais le travail sûr est jeté à chaque
   passage.
2. **Écrire toute facette confirmable** : une variante confirmée serait
   effacée par la photo du recto demandée dans le même passage, et la
   personne la reconfirmerait.
3. **Écrire toute facette confirmable qu'aucune photo demandée dans le même
   passage n'effacerait.**

**Décision.** Option 3.
- L'identité confirmable est écrite, même si une photo est demandée.
- La variante confirmable est écrite si aucune photo du recto n'est demandée
  (recto, reflet, coins).
- L'état confirmable est écrit si aucune photo n'est demandée.
- Une carte encore « à vérifier » dont l'identité ne se confirme pas ne
  reçoit aucune écriture : sa variante a été jugée sur une identité que
  personne n'a confirmée.
- Le réglage `agent_review_apply` garde la main sur l'identité d'une carte
  importée ([0047](0047-import-de-classeur-sur-le-serveur.md)). Tant qu'il est
  faux, rien n'est écrit sur la carte, et les photos sont tout de même
  demandées.
- Une vue déjà reprise ne sera pas redemandée : elle ne retient aucune
  facette, et la carte reste en l'état pour le reste.
- Le rapport et l'événement du passage marquent `partial` une carte
  confirmée en partie. Le rapport dit aussi ce qui reste : photo demandée,
  `kept` ou `skipped`. L'annulation d'un passage reprend les confirmations
  partielles comme les autres.

**Conséquences.**
- Une carte importée lisible sort de « À vérifier » dès le premier passage,
  même si ses coins sont demandés.
- Une carte « en l'état » garde un état non confirmé, mais sa variante
  confirmée compte pour le prix.
- La porte de mesure avant `--apply` ne change pas avec cette fiche.

**Preuve.** `tests/test_agent_review.py` (identité écrite pendant la demande
des coins, variante écrite quand l'état reste en l'état, identité seule
retenue par le réglage, vue déjà reprise), `tests/test_closeups.py`.
