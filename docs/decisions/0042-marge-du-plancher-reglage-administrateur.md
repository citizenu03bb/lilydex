# 0042 — La marge du plancher anti-bradage est un réglage de la base, réservé à l'administrateur

> **Statut :** en vigueur, amende la [décision 0026](0026-plancher-anti-bradage-gestion.md) · **Date :** 2026-11-10

**Contexte.** La [décision 0021](0021-autonomie-maximale.md) laisse l'agent
identifier, coter, composer et publier sans attendre de clic, à une condition :
ne jamais vendre sous le plancher anti-bradage. La
[décision 0026](0026-plancher-anti-bradage-gestion.md) donne à ce plancher une
seule formule, mais lit sa marge dans la variable d'environnement
`POKEPRICE_LOT_MAX_MARGIN`. Une revue de code externe relève que ce garde-fou
est plus faible que l'autonomie qu'il encadre : l'outil de lots transmettait la
variable du poste au serveur (`ssh` puis `sudo -u pokeprice env ...`), si bien
qu'un agent côté opérateur pouvait la mettre à 50 et diviser son propre plancher
par deux, sans trace. L'option `--marge` de l'export vers les plateformes
permettait la même chose pour un export.

**Options.**
1. Garder la variable et ne plus la transmettre : le plancher dépend encore de
   l'environnement de chaque processus, et aucun changement n'est tracé.
2. Fixer la marge dans le code : sûr, mais le vendeur ne peut plus la régler
   sans une mise en production.
3. Un réglage dans la base, modifiable seulement par un administrateur
   connecté à la gestion, journalisé.

**Décision.** Option 3.

- La marge (pourcentage entier de 0 à 50, 15 par défaut) est la clé
  `lot_max_margin` de la table `settings`. `lot_max_margin(source)` la lit
  dans la base, et `lot_floor_cents(total, marge)` reçoit la marge lue : la
  gestion, l'audit du plancher, l'assistant, l'outil de lots et l'export
  partagent la même valeur. Une valeur hors bornes dans la base est une erreur,
  jamais une marge plus large.
- Seul un administrateur la change, par `PUT /api/settings/floor-margin`
  (session de la gestion) et le panneau **Réglages → Plancher anti-bradage**.
  Le service vérifie lui aussi que l'auteur est un compte administrateur
  actif : une clé d'agent, l'acteur de l'outil de lots ou un nom inconnu sont
  refusés, quelle que soit la route.
- Chaque changement écrit un événement `floor-margin` au journal (`events`) :
  auteur, date, ancienne et nouvelle valeur. Le panneau affiche les derniers.
- `POKEPRICE_LOT_MAX_MARGIN` n'est plus lue à l'exécution. La migration vers
  le schéma 27 la lit une seule fois, sur une base existante, pour reprendre la
  valeur avec laquelle le serveur tournait (bornée de 0 à 50, 15 si elle est
  absente ou illisible), et journalise cette reprise. Une base neuve part à 15.
- L'outil de lots ne transmet plus rien au serveur et n'a aucune option de
  marge : avec `--remote`, la base du serveur décide.
- `--marge` de l'export (`scripts/export_annonces.py`) ne peut que resserrer :
  une valeur inférieure ou égale à la marge réglée relève le plancher de cet
  export ; une valeur supérieure arrête l'export avec une erreur. Le refus est
  préféré au plafonnement silencieux, qui laisserait croire à l'appelant que le
  plancher a baissé. Resserrer reste permis parce que cela ne peut que protéger
  le vendeur, et que l'export ne publie rien lui-même.

**Conséquences.**
- Baisser le plancher demande une personne, un compte administrateur et laisse
  une trace ; la dérogation au cas par cas reste celle de la
  [décision 0030](0030-derogations-plancher.md).
- Le réglage suit la base : il est sauvegardé et restauré avec elle, et une
  base de développement peut porter une autre marge que le serveur.
- Qui a un accès en écriture au fichier de la base ou au compte système du
  service peut toujours modifier le réglage sans passer par la gestion. Cette
  fiche ferme la voie de l'environnement et des options, pas celle-là ; elle se
  referme quand l'outil de lots passe par l'API des agents.
- Au déploiement, la variable doit être présente dans l'environnement du
  premier processus qui ouvre la base, si le serveur tournait avec une valeur
  autre que 15 ; sinon la valeur se règle ensuite dans la gestion. La variable
  peut ensuite être retirée de la configuration du serveur.
- Les scripts qui appelaient `lot_max_margin()` ou `lot_floor_cents(total)`
  sans base doivent passer la base ou la marge.
