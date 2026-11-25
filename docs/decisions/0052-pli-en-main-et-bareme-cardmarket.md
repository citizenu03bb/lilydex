# 0052 — L'état se note sur le barème écrit de Cardmarket, et un pli signalé en main plafonne la note à LP

> **Statut :** en vigueur, complète les décisions [0049](0049-etat-sans-manipulation.md) et [0051](0051-porte-sur-les-erreurs-graves.md) · **Date :** 2026-11-25

**Contexte.** Sur les 60 cartes de la vérification à l'aveugle, l'agent
confirmerait 5 états trop optimistes de deux crans ou plus. Le propriétaire
rappelle que sa note en main n'est pas celle d'un expert. Les deux juges ont
donc été comparés au barème écrit de Cardmarket, là où se font les prix et
les litiges : les défauts notés en main (coins, bords, surface, pli) donnent
la meilleure note que ce barème autorise. La note en main ne dépasse ce
plafond que sur 3 cartes sur 60, d'un cran. Celle du modèle le dépasse sur 11
cartes sur 57, et sur 3 confirmations de deux crans ou plus. Deux de ces trois
cartes ont un pli. Sur une photo à plat en lumière diffuse, un pli ne se voit
pas : interrogé seulement sur les plis, le modèle en trouve 7 sur 16, sans
aucune fausse alerte sur 44 cartes. Le barème est sans appel : aucune pliure
à partir de GD, donc LP au mieux.

**Options.**
1. **Exiger une photo en lumière rasante** : la seule photo qui montre un pli,
   mais un geste et un éclairage de plus pour chaque carte.
2. **Poser la question en main pendant la série**, quand la carte est déjà
   sortie pour une photo, et faire suivre la consigne d'état sur le barème
   écrit.
3. **Ne rien changer** : la porte reste hors d'atteinte.

**Décision.** Option 2.
- La lecture d'état passe au protocole `card-condition-v3`. La consigne
  reprend les définitions de Cardmarket : NM, très peu de points blancs
  minuscules et aucune rayure ; EX, quelques points blancs et des rayures
  fines visibles de près, aucun pli visible au premier coup d'œil ; GD, usure
  forte et rayures, mais aucune pliure ; LP, pliure admise. Le modèle note
  d'après le défaut le plus pénalisant et, dans le doute, prend la note
  inférieure. Il dit aussi s'il voit un pli : oui, non ou incertain.
- La série **Prises de près** pose, à chaque carte, la question « Pli, cassure
  ou marque enfoncée ? » : non, pli, enfoncement ou doute. La réponse est un
  événement de la carte (`crease-observation`) ; la dernière fait foi.
- L'agent de revue plafonne à LP l'état qu'il confirme si la réponse en
  main est « pli » ou « enfoncement », ou, sans réponse en main, si la
  lecture voit un pli. Une note pire que LP n'est pas relevée. Une carte
  qu'il ne confirme pas garde son état enregistré. « Doute » laisse l'état tel
  qu'enregistré. Une réponse en main l'emporte sur la lecture ; elle ne
  relance aucune lecture et ne ferme pas une photo de la série en attente.

**Conséquences.**
- Une évaluation `card-condition-v2` est relue au passage suivant de
  l'agent : environ 0,8 € pour 100 cartes.
- La question n'atteint que les cartes qui passent par la série. Avec elle,
  l'échantillon actuel compterait 1 erreur grave sur 50 confirmations (borne
  haute 10,6 %) : la porte de la fiche 0051 devient atteignable, à mesurer sur
  un nouvel échantillon à l'aveugle.
- Le modèle ne voit que le recto : l'usure du verso lui échappe toujours.

**Preuve.** `tests/test_agent_review.py` (plafond LP, doute, réponse en main
contre lecture), `tests/test_closeups.py` (question pendant la série).
