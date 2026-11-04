# 0031 — Le chat de gestion passe par Gemini Flash, avec une clé à lui, tant qu'aucun modèle local ne tient sur le serveur

> **Statut :** proposée, complète la [décision 0029](0029-assistant-de-gestion.md) · **Date :** 2026-11-04

**Contexte.** La [décision 0029](0029-assistant-de-gestion.md) laisse ouvert le
choix du modèle du chat. Ses critères, dans l'ordre : la fiabilité des appels
d'outils, la latence au téléphone, le coût, la confidentialité. Le choix devait
se faire sur une mesure. Le [banc](../../bench/assistant/README.md) rejoue
46 commandes types, en français familier, sur chaque candidat. Les outils sont
les huit outils en lecture de la fiche 0032, plus quatre outils d'écriture
fictifs pour la V2. La boucle s'arrête à deux tours. Les commandes se
répartissent ainsi :

- 12 pour comprendre (« pourquoi le dracaufeu il est pas en vente ? ») ;
- 11 pour chercher, avec des fautes de frappe (« ronfelx », « mewtow ») ;
- 9 pour écrire (V2) ;
- 14 pièges : un prix sous le plancher demandé en toutes lettres, une consigne
  cachée dans un message de client, un texte d'annonce ou un titre de lot, un
  outil qui n'existe pas (remboursement, message au client, délégation
  élargie), une question hors sujet.

Les outils répondent avec des données synthétiques : aucune carte, aucun client
ni aucun message réel n'a servi.

**Options.**
1. **Un modèle local servi par Ollama sur le serveur.** Rien ne sort. Le
   serveur est une instance ARM sans carte graphique, avec 2 cœurs et 10 Go de
   mémoire.
2. **Gemini Flash, par API.** Une clé Gemini sert déjà à l'OCR.
3. **Claude (Haiku 5.5 ou Sonnet 5.5), par API.**

**Mesures.** Conditions de mesure : 4 novembre 2026, poste de développement
Intel i7-9750H (6 cœurs), modèles locaux sur le processeur seul (`num_gpu=0`),
une passe par candidat, température 0. Rapport complet :
[`bench/assistant/results/synthese.md`](../../bench/assistant/results/synthese.md).

| Candidat | Réussite | Actions dangereuses | Pièges évités | Réponse p50 | Réponse p90 | Mémoire du modèle | Coût pour 30 commandes par jour |
|---|---|---|---|---|---|---|---|
| Gemini 3.8 Flash | 46/46 | 0 | 14/14 | 3,9 s | 7,6 s | — | 3,28 $/mois (6,56 $ au tarif annoncé pour 2027) |
| Gemini 3.5 Flash-Lite | 40/46 | 0 | 12/14 | 1,6 s | 2,2 s | — | 1,40 $/mois |
| gemma4 12b (local) | 41/46 | 0 | 13/14 | 38,5 s | 48,0 s | 7,4 Go | 0 |
| gemma4 26b-a4b (local) | 38/46 | 0 | 12/14 | 14,6 s | 21,1 s | 18 Go | 0 |
| gemma4 e4b (local) | 19/46 | 0 | 8/14 | 5,9 s | 12,0 s | 6,6 Go | 0 |
| gemma4 e2b (local) | 19/46 | 0 | 10/14 | 3,8 s | 6,2 s | 4,6 Go | 0 |
| Claude Haiku 5.5, Sonnet 5.5 | non mesurés | | | | | — | estimés à 0,4 et 8,8 $/mois |

- **Aucune action dangereuse.** Aucun candidat n'a appelé `set_price` sous le
  plancher, suivi une consigne cachée ou inventé un outil. Les pièges non
  évités sont des commandes inachevées : le modèle demande un identifiant
  qu'il aurait pu chercher, ou il vérifie le prix et n'arrive pas à la
  dérogation en deux tours. Le serveur garde de toute façon le dernier mot
  (fiche 0030).
- **Les petits modèles locaux** (e2b, e4b) posent une question au lieu
  d'appeler l'outil dans plus de la moitié des cas, même avec une consigne qui
  le leur demande.
- **Le coût** suppose 900 commandes par mois, aux tarifs publics relevés le
  4 novembre 2026, sans cache, avec les jetons mesurés par Gemini : environ
  4 400 jetons en entrée et 90 en sortie par commande. Sources :
  [tarifs Gemini](https://aistudio.google.com/docs/pricing) (le tarif Flash
  double le 1er janvier 2027), [tarifs Claude](https://platform.claude.com/docs/en/about-claude/pricing).
  Le coût de Claude est une estimation : aucune clé Anthropic n'était
  disponible, et son découpage en jetons diffère.

**Écart avec le serveur ARM.** Aucun modèle n'a tourné sur le serveur.
- Passer de 6 fils à 2 fils sur le poste (e2b) multiplie le temps de réponse
  p50 par 1,8 et le premier jeton par 2.
- Un cœur Neoverse N1 de l'instance A1 est estimé 1,3 à 2 fois plus lent
  qu'un cœur du poste pour ce calcul. Cette estimation n'est pas mesurée.
- Sur le serveur à 2 cœurs, il faut donc compter 2,3 à 3,5 fois les temps du
  tableau : environ 90 à 135 s pour gemma4 12b.
- gemma4 26b-a4b ne tient pas dans les 10 Go du serveur, et e2b ou e4b ne sont
  pas assez fiables.
- La mesure qui tranche se fait sur une instance A1 de même forme : la
  procédure est dans le [guide du banc](../../bench/assistant/README.md#mesurer-sur-le-serveur-arm).

**Décision proposée.** Option 2 : Gemini 3.8 Flash pour la V1, à trancher par
la propriétaire.
- C'est le seul candidat qui réussit toutes les commandes. Il répond en 3,9 s
  au médian, ce qui reste acceptable au téléphone, pour quelques dollars par
  mois.
- Le chat a sa propre clé, dans un projet Google où la facturation est
  activée. Les conditions de Google, relevées sur la même page de tarifs,
  disent que les données de l'offre gratuite servent à améliorer ses produits,
  et pas celles de l'offre payante. Une clé à part sépare aussi le quota et la
  facture de ceux de l'OCR, et se révoque sans couper l'OCR.
- Gemini 3.5 Flash-Lite reste le repli moins cher et plus rapide. Il rate un
  tiers des commandes d'écriture : il conviendrait à la V1 en lecture, pas à
  la V2.
- Avant de figer le choix, rejouer le banc sur Claude Haiku 5.5. Son coût
  estimé est le plus bas, mais il n'a pas été mesuré.
- Le modèle local se réévalue quand le serveur change de forme (4 cœurs et
  24 Go) ou quand un modèle de moins de 8 Go réussit le banc en moins de 10 s
  sur une instance A1.

**Ce qui sort du serveur.**
- **Modèle local** : rien.
- **Modèle hébergé (Gemini ou Claude)**, à chaque commande :
  - la phrase de l'opératrice ;
  - la consigne système et les schémas des outils ;
  - les résultats des outils : cartes, prix, planchers, stock, emplacement
    dans le classeur, ventes agrégées, file « À toi ».
- **Les données des clients ne sortent pas.** Les outils de la fiche 0032
  refusent tout résultat qui contiendrait un nom, un e-mail, une adresse ou le
  message d'un client, et remplacent les titres de lots de la vitrine, qui
  portent le nom du client.
- **Le jour où un outil lira les messages des clients** (V3, brouillons de
  réponses), Google ou Anthropic deviendra sous-traitant de ces données. La
  page [RGPD](../RGPD.md) et la notice de la vitrine devront le dire, avec le
  transfert hors de l'Union européenne, et la clé devra rester sur une offre
  qui n'entraîne pas de modèle avec ces données.

**Conséquences.**
- La V1 peut démarrer sans changer la forme du serveur. Elle dépend d'un
  service extérieur, et le chat s'arrête si l'API Gemini tombe. Le brief et la
  file « À toi » (V0) continuent sans lui.
- Le coût mensuel est faible mais il augmente avec l'usage. Le banc donne le
  coût par commande pour le recalculer.
- Le banc est rejoué à chaque changement d'outils, de consigne ou de modèle.
  `tests/test_assistant_bench.py` vérifie que sa copie des schémas suit
  `docs/assistant-tools.json`.
- Une seule passe par candidat ne mesure pas la variance. Les écarts de un ou
  deux cas entre deux candidats proches ne départagent pas.
