# 0035 — Le chat connaît la gestion par une carte courte dans sa consigne et lit le guide à la demande

> **Statut :** proposée, complète les [décisions 0029](0029-assistant-de-gestion.md) et [0032](0032-outils-assistant-lecture.md) · **Date :** 2026-11-05

**Contexte.** Le chat de gestion de la V1 lit la collection, les annonces, les
ventes et la file « À toi », mais il ne sait rien de l'application elle-même.
À « comment je mets une carte en vitrine ? » ou « c'est quoi la règle du
plancher pour un lot ? », il ne peut que deviner ou renvoyer vaguement vers la
gestion. Les réponses existent pourtant dans le dépôt : le guide
[APP.md](../APP.md), les guides d'agents de `skills/` et les fiches de
décision. Mais ces textes s'adressent aussi à l'opérateur du serveur : ils
contiennent des commandes de terminal, des options `--apply` et `--data`, des
chemins du serveur. Lily, elle, agit seulement par l'application.

**Options.**
1. **Tout mettre dans la consigne système** : le guide fait plus de 1 300
   lignes ; chaque question en paierait les jetons, et la consigne vieillirait
   à chaque changement du guide.
2. **Une recopie des règles dans le code** : courte, mais une seconde version
   des mêmes règles, qui diverge du guide sans que personne ne le voie.
3. **Une carte courte dans la consigne, plus un outil qui lit le guide au
   moment de la question**, par titre de section, en retirant les commandes.

**Décision.** Option 3.

*La carte.* Une section nommée « Carte de l'application » de
`src/pokeprice/assistant_prompt.md`, d'environ 700 jetons : le haut de la
gestion (bouton Assistant, Brief du jour, file « À toi » et son ordre), les
quatre onglets et ce que fait chacun, la vitrine, et ce que la V1 ne fait
pas : aucune écriture, aucune commande de terminal. Elle vit dans sa propre
section pour que d'autres règles de la consigne s'ajoutent à côté sans la
toucher. Le banc lit la même consigne.

*L'outil.* `knowledge(topic)` rejoint le registre de la fiche 0032, avec le
même contrat : schéma strict (un texte de 80 caractères au plus), sortie
relue par `check_output`, export `docs/assistant-tools.json` régénéré. Le
code est dans `src/pokeprice/assistant_knowledge.py`.

- Un index fermé de sujets associe un nom stable (`plancher`, `vitrine`,
  `suivre-lot`…) à un fichier et à un titre de section. Le texte n'est pas
  recopié : la section est lue dans le fichier au moment de l'appel, avec ses
  sous-sections, ou, dans une fiche de décision, le paragraphe ouvert par
  « **Décision.** » jusqu'au suivant.
- Les sujets couvrent le guide de l'application (un sujet par écran ou par
  geste) et cinq règles métier : le plancher anti-bradage
  ([pokeprice-autonome](../../skills/pokeprice-autonome/SKILL.md)), les
  dérogations ([0030](0030-derogations-plancher.md)), l'autonomie et les
  décisions humaines ([0021](0021-autonomie-maximale.md)), les lots
  ([pokeprice-lots](../../skills/pokeprice-lots/SKILL.md)) et l'ordre du
  classeur ([parcours des cartes à examiner](../RESOLUTION_CARTES.md) et tri
  Classeur du guide).
- Le sujet se trouve par son nom, un alias ou son titre, sans casse ni
  accents. Sans sujet ou sujet inconnu, l'outil renvoie la liste des sujets ;
  le modèle choisit alors dans la liste.
- La sortie est `{topic, title, sources, text, truncated}`, en texte simple
  (liens réduits à leur libellé, gras retiré), coupée à 4 000 caractères à une
  fin de ligne.

*Le filtre des commandes.* Les blocs de code, les commentaires HTML, les
images et les citations sont retirés. Puis, phrase par phrase, toute phrase
qui nomme une commande ou un détail d'exploitation est retirée :
`pokeprice-manage`, `pokeprice-agent`, l'outil de lots, une option `--…`, un
chemin du serveur (`/srv/`, `/opt/`, `~/`), `sudo`, `ssh`, `uv run`, Python,
un script, un chemin de code, une variable `POKEPRICE_…`, une route d'API.
Une parenthèse qui en nomme une, ou qui cite du code, est retirée seule, et la
phrase autour reste. C'est une liste noire : un test passe chaque sujet au
filtre, un autre vérifie la sortie sur une section synthétique pleine de
commandes.

*Le déploiement.* `deploy/oci-deploy.sh` copie sur le serveur les fichiers
suivis par Git dans `/opt/pokeprice`, puis `uv sync` installe le paquet en
mode éditable depuis cette copie. Le paquet trouve donc `docs/` et `skills/` à
côté de `src/`, comme `docs/assistant-tools.json` pour l'export de la
fiche 0032. Rien n'est embarqué dans la roue. Un test vérifie que chaque
fichier source d'un sujet est suivi par Git, donc copié au déploiement. Une
installation sans ces fichiers répond 503 `knowledge_unavailable`, et le chat
le dit.

**Conséquences.**
- Un changement du guide passe dans le chat sans toucher au code. Un titre de
  section renommé casse un test : l'index se met à jour dans le même commit.
- Une question « comment faire » coûte un appel d'outil de plus et environ
  1 000 jetons de résultat au plus ; la carte coûte environ 700 jetons à chaque
  question.
- Les guides d'agents parlent à un agent (« vous », « ne publiez jamais ») :
  le modèle les reformule pour Lily. Le texte rendu peut garder des noms
  internes (`Listings.publish`, `floor-request`) quand ils ne sont pas des
  commandes.
- Le filtre retire aussi des phrases utiles qui citent un chemin de code. On
  préfère un trou dans l'explication à une commande d'opérateur dans le chat.
- Le banc reçoit l'outil, deux cas « comment faire » et des extraits
  synthétiques ; il ne lit pas les guides.

**Pour aller plus loin.** [L'assistant dans le guide](../APP.md#lassistant),
[outils de l'assistant](../AGENT_CONTROL.md#outils-de-lassistant-de-gestion),
`tests/test_assistant_knowledge.py`.
