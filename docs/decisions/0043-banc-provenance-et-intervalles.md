# 0043 — Le banc d'essai publie ses intervalles et la provenance de sa vérité

> **Statut :** en vigueur · **Date :** 2026-11-10

**Contexte.** Une relecture extérieure a jugé le banc d'essai trop petit pour
l'autonomie accordée aux agents ([fiche 0021](0021-autonomie-maximale.md)) :
22 éditions confirmées par l'image sur 27 donnent un intervalle à 95 % de 63 à
92 %, et aucune variante fausse sur une vingtaine de cartes borne seulement le
taux d'erreur sous 12 à 14 %. Or le plancher anti-bradage dépend du prix de
référence, qui dépend d'une identification juste. Le banc compte 31 cartes,
aucune japonaise, deux reverses. La collection, elle, contient 301 variantes
déjà confirmées par une personne, dont 106 avec un motif qui dit que la carte a
été observée en main.

**Options.**
1. Laisser un modèle fournir la vérité des nouvelles cartes : rapide, mais le
   banc mesurerait alors l'accord entre modèles, pas leur justesse.
2. Verser telles quelles les confirmations existantes dans le banc : 301 cartes
   d'un coup, mais confirmées par une personne qui voyait l'identité proposée
   (biais d'ancrage), et pour 195 d'entre elles sans trace que la carte ait été
   observée en main plutôt que sur sa photo.
3. Garder la vérité humaine et automatiser tout le reste : compter ce qui est
   récoltable, choisir les cartes à vérifier ensuite, calculer les intervalles ;
   marquer la provenance de chaque vérité et publier les résultats séparément.

**Décision.** Option 3.

- Un modèle ne fournit jamais la vérité du banc. Une confirmation faite par un
  agent ou un automate n'y entre pas, ni celle dont la fiche n'enregistre pas
  l'auteur.
- Chaque carte du banc porte la provenance de sa vérité : *vérifiée à
  l'aveugle* (observée sur la carte physique à partir d'une feuille sans
  lecture, enregistrée avec le motif « Vérification à l'aveugle (banc) », sans
  lecture de finition antérieure), *récoltée* (confirmation déjà présente dans
  la collection) ou *banc initial*. Les résultats sont publiés par provenance ;
  seule la première mesure sans biais d'ancrage.
- Chaque taux publié porte son compte et son intervalle de confiance à 95 % :
  Wilson quand il y a des réussites et des échecs, borne exacte de
  Clopper–Pearson (unilatérale) quand toutes les réponses concordent.
- La cible est de 200 cartes vérifiées et plus, dont 60 par strate : reverses,
  holos, autres langues que le français, éditions voisines, cartes de valeur.
  `pokeprice-manage bench-sample` propose les prochaines cartes dans l'ordre
  du classeur ; `bench-harvest` compte ce que la collection contient déjà. Les
  deux commandes ouvrent la base en lecture seule.

**Conséquences.**
- Les chiffres publiés s'écrivent « 22/27 (IC 95 % : 63,3–91,9 %) » dans le
  README, [IA et vision](../IA-VISION.md) et le
  [banc d'essai](../BANC-RECONNAISSANCE.md).
- La mesure de sécurité « aucune variante fausse proposée au-dessus du seuil »
  porte sur les 24 cartes du banc dont une personne a vérifié la catégorie de
  prix : 0/24, soit un taux sous 12 %. La borne passe sous 5 % à 59 cartes sans
  erreur, sous 2 % à 149.
- Le japonais reste hors de portée : la collection n'en contient que deux
  cartes.
- Les cartes récoltées n'entrent dans les mesures qu'après un passage réel du
  banc sur leurs photos (un appel Gemini par carte et par passage) ; ce passage
  reste à faire.
- Les seuils de non-régression du banc ne changent pas : ils restent exprimés
  en parts, sur le pire passage ([fiche 0007](0007-seuils-confort-securite.md)).
