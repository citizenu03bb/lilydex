# 0004 — Gemini seul lecteur de texte

> **Statut :** en vigueur · **Date :** 2026-10-13

**Contexte.** Les contrôles automatiques (jalon M2) demandaient un lecteur de
photo fiable, et peut-être un second avis indépendant.

**Options, mesurées au [banc d'essai](../BANC-RECONNAISSANCE.md).**
1. **Gemini seul** : numéro 25/31, holo ou mate 21/21 ; 2 fausses alertes de
   contrefaçon sur 30 vraies cartes.
2. **Un agent Claude Sonnet en second avis**, lancé à la demande sur la file
   d'un classeur : lecture comparable (numéro 24/31), aucune fausse alerte de
   contrefaçon, moins bon sur le holo (7/9) ; environ 74 000 jetons pour 31
   cartes.
3. **Claude Sonnet par l'API** : environ 0,5 à 1 centime par carte, mais un
   compte et des crédits à ouvrir.
4. **L'agent Antigravity** (la CLI `agy`, sur un abonnement Google) : 69 à 117 s et plus de 50 000 jetons pour une
   seule photo, et aucune réponse sans l'autoriser à exécuter des commandes.
5. L'agent Claude Haiku : numéro 5/31.

**Décision.** Gemini seul, derrière une interface de vérification commune : un
lecteur est un simple appelable qui déclare sa source, son modèle et son
protocole.

**Conséquences.**
- Un second lecteur se branche par configuration, sans changer le service.
- Sans seconde source indépendante, aucune alerte de contrefaçon n'est
  produite.
- Les contrôles de finition et de langue reposent sur le même modèle : ils ne
  sont pas présentés comme indépendants.
