# 0055 — Une personne note l'état, et l'agent de revue n'écrit une facette que si son propre réglage l'y autorise

> **Statut :** en vigueur, modifie les décisions [0049](0049-etat-sans-manipulation.md) (l'agent ne confirme plus l'état sous 10 €) et [0051](0051-porte-sur-les-erreurs-graves.md) (plus d'écriture hors du réglage) · **Date :** 2026-11-28

**Contexte.** La décision 0049 laissait l'agent de revue confirmer, sous
10 €, l'état lu sur le recto. Trois mesures à l'aveugle disent que cette
lecture ne tient pas :
- sur les 60 cartes du premier échantillon, relues au protocole v2, l'agent
  confirmerait 50 états, dont 5 erreurs graves (deux crans ou plus), toutes
  optimistes (borne haute 21,8 %, [décision 0051](0051-porte-sur-les-erreurs-graves.md)) ;
- sur le second échantillon, au protocole v3 et au barème de Cardmarket, les
  38 états confirmables comptent 6 erreurs graves par rapport à la note en
  main, toutes optimistes. Le modèle juge les 38 photos suffisantes, mais une
  photo de page prise dans la pochette ne montre ni l'usure des coins et des
  tranches, ni la surface. La règle fixée d'avance arrêtait l'essai au-delà de
  deux erreurs ;
- au banc d'état ([décision 0054](0054-modele-gemini-unique.md)), aucun
  modèle n'approche le seuil : 31 notes exactes sur 59 pour le meilleur.

Une erreur grave fait entrer dans un lot ou une annonce une carte jouée
présentée comme excellente. Sur le second échantillon, la variante, elle,
est juste sur les 26 confirmations, mais aucune holo n'y figurait.

Le réglage `agent_review_apply` était un seul interrupteur, et ne gardait que
l'identité des cartes importées : `agent-review --apply`, lancé par
l'opérateur, écrivait variante et état hors du réglage.

**Options.**
1. **Continuer à mesurer la lecture d'état** sur de nouvelles consignes :
   trois essais ont échoué pour la même raison, la pochette.
2. **Ne confirmer l'état que sur des prises de près hors pochette** : chaque
   carte sortirait de sa pochette pour une photo, ce que la décision 0049
   refuse, sans garantie que la porte passe.
3. **Laisser l'état à une personne** et ouvrir l'écriture de l'agent facette
   par facette, pour garder l'identité et la variante, qui se mesurent bien.

**Décision.** Option 3.
- **L'agent ne juge plus l'état**, à aucune valeur : il ne le confirme pas et
  ne demande aucune photo pour lui (plus de « coins de près »). Il lit encore
  l'état, parce que cette lecture dit si le verso est exploitable, ce dont la
  variante d'une carte de valeur a besoin (décision 0049) ; la lecture n'est
  ni écrite ni montrée à la personne qui note.
- **Une personne note l'état**, sur le barème de Cardmarket
  ([décision 0052](0052-pli-en-main-et-bareme-cardmarket.md)), dans une série
  rapide, les cartes de plus forte valeur d'abord, sans la lecture du modèle,
  qui tire la note vers le haut. Comment la personne regarde la carte (à
  travers la pochette ou sortie une fois) se décide avec cette série.
- Tant qu'aucune personne ne l'a notée, une carte garde son état enregistré,
  non confirmé. Sous 10 €, elle peut entrer dans un lot, présentée en l'état
  avec ses photos.
- **Un interrupteur par facette** : `agent_review_apply` devient
  `{identity, variant, condition}`, tout fermé sans réglage. `on` sans facette
  ouvre l'identité et la variante, jamais l'état, qui doit être nommé et
  demanderait une nouvelle mesure à l'aveugle. L'ancien réglage `true` vaut
  identité et variante. Chaque changement reste réservé à un administrateur,
  avec sa raison, et journalisé.
- **Tous les appelants suivent les interrupteurs** : import, série Prises de
  près, photo qui répond à une demande, et `agent-review --apply` de
  l'opérateur. L'exception de la décision 0051 disparaît. La simulation dit
  toujours ce que l'agent confirmerait.

**Conséquences.**
- En production, rien ne change à l'écriture tant qu'aucune facette n'est
  ouverte. La série Prises de près ne demande plus que des reflets et des
  recto nets.
- La variante doit encore passer sa porte (aucune variante fausse) sur un
  échantillon qui contienne des holos, des reverses et des holos parallèles.
- Le temps de notation compte dans le temps humain du critère S5 : une
  centaine de cartes demandent une série courte, pas un examen.
- La lecture d'état continue de coûter sa part des 0,8 € de Gemini pour
  100 cartes, pour servir la variante.
- Pour écrire une variante à la main, l'opérateur ouvre la facette, ou
  confirme dans la fiche : la commande n'a plus de chemin à part.

**Preuve.** `tests/test_agent_review.py`, `tests/test_closeups.py`,
`tests/test_binder_import.py`, `tests/test_binder_routes.py`.
