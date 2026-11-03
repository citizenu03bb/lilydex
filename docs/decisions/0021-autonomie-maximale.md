# 0021 — Les agents agissent seuls, sauf l'argent, l'irréversible et le bradage

> **Statut :** en vigueur · **Date :** 2026-11-03

**Contexte.** Lily a peu de temps pour la gestion et le suivi des ventes, et
tout le stock est à vendre : vitrine, Vinted, Leboncoin et Cardmarket. La règle
« la machine propose, l'humain décide » était lue par les agents comme « ne
rien faire sans clic ». Le code allait déjà plus loin : corrections
préautorisées ([décision 0014](0014-corrections-agent-autorisees.md)), rotation
et publication de lots par `scripts/pokeprice_lots.py`. Cette décision complète
les décisions [0012](0012-agent-brouillons.md) et 0014 sans les réécrire : la
délégation par album, le serveur qui décide des droits et les plans immuables
restent en vigueur.

**Options.**
1. Garder la règle absolue : chaque identification, prix ou publication attend
   un clic. Sûr, mais le stock ne se vend pas faute de temps.
2. Une autonomie au cas par cas, accordée parcours par parcours. Chaque agent
   redemande ce qu'il a le droit de faire.
3. L'autonomie par défaut, avec une liste fermée de décisions humaines et un
   garde-fou chiffré contre le bradage.

**Décision.** Option 3. L'IA agit seule : elle identifie, cote, range, compose
les lots et publie, puis journalise et rend chaque action annulable. L'humain
fournit les photos que l'IA demande, et tranche l'argent qui sort,
l'irréversible et tout prix sous le plancher anti-bradage.

*(a) Ce qui reste humain*, et seulement cela :

- tout paiement et tout remboursement ;
- toute suppression définitive (exemplaire, photo, historique, client) ;
- tout message libre à un client ; les messages types de l'application ne sont
  pas des messages libres ;
- tout prix sous le plancher anti-bradage ;
- le plafond de délégation : la portée d'une clé d'agent, ses droits et leur
  révocation.

Le reste ne demande aucun clic : identification, choix de la variante,
évaluation de l'état, cotation, rangement, composition, publication,
dépublication et rotation des lots, dans les droits de la délégation.

*(b) Le garde-fou anti-bradage.* Aucune vente sous le prix de référence
diminué d'une marge configurable, lots compris : le prix d'un lot se compare à
la somme des prix de référence de ses exemplaires. La marge vaut 15 % par
défaut. Le contrôle porte sur le prix final, arrondi compris. Un exemplaire
sans prix de référence n'a pas de plancher : il ne se vend pas seul tant que
son prix n'est pas relevé ou fixé. Le plancher absolu de 0,50 € par carte et
par lot reste en vigueur. L'outil de lots compose en outre ses lots à 2 € au
moins ; c'est un minimum de composition, pas un contrôle à la publication. Un
prix sous le plancher anti-bradage est présenté à l'humain, avec sa raison ; il
n'est jamais appliqué d'office.

*(c) La demande de nouvelle photo.* Quand l'IA ne tranche pas une variante ou
un état, elle ne publie pas avec une mention « non vérifiée » et ne devine pas.
Elle demande à l'humain une autre photo et dit laquelle : face, angle,
lumière rasante pour une reverse, gros plan d'un coin ou d'un tampon. La carte
reste hors vente jusqu'à la nouvelle photo, puis l'IA relit et tranche.

**Conséquences.**

- Une annonce publiée porte une variante et un état établis ; la mention
  « variante ou état non vérifiés » n'existe pas.
- Chaque action d'un agent garde son auteur, sa raison et l'état antérieur, et
  s'annule sans perte. Une action qui ne s'annule pas tombe dans les décisions
  humaines.
- Les seuils de sécurité de la vision ([décision 0007](0007-seuils-confort-securite.md))
  ne baissent pas : un agent qui doute demande une photo au lieu de forcer une
  lecture. Les reverses de valeur gardent leur examen
  ([décision 0008](0008-reverses-examen-physique.md)), qu'une photo ciblée peut
  rendre possible.
- Une part de cette autonomie est une cible, pas un acquis. Livré : lectures
  automatiques à la saisie, corrections préautorisées, brouillons par l'API
  déléguée, composition, rotation et publication de lots en vitrine par
  `scripts/pokeprice_lots.py`, qui refuse tout lot sous le plancher
  anti-bradage. À livrer : confirmation de l'identité, de la variante et de
  l'état par un agent, plancher anti-bradage pour le « Mode lot » de la gestion
  et pour un prix unitaire fixé à la main (seul le plancher absolu de 0,50 €
  y est contrôlé), file des demandes de photo, publication sur Vinted,
  Leboncoin et Cardmarket, annulation de chaque action. D'ici là, un agent
  applique lui-même la marge de 15 % hors de l'outil de lots et formule
  lui-même ses demandes de photo.
- Le pilote scellé de la décision 0012 reste un périmètre d'évaluation : ses
  résultats ne bornent pas l'autonomie des autres parcours.

**Pour aller plus loin.** [IA et vision](../IA-VISION.md),
[pilote agent](../AGENT_CONTROL.md),
[guide d'autonomie](../../skills/pokeprice-autonome/SKILL.md).
