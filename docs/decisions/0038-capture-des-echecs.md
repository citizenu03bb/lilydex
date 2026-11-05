# 0038 — Le chat garde les réponses signalées, par un 👎 ou par un signal du serveur, pour en tirer des cas du banc sans donnée réelle

> **Statut :** proposée, complète les décisions [0029](0029-assistant-de-gestion.md) et [0034](0034-conversations-du-chat.md) · **Date :** 2026-11-05

**Contexte.** Le [banc](../../bench/assistant/README.md) choisit et surveille
le modèle du chat avec des commandes écrites à l'avance. Les échecs réels du
chat (une réponse fausse, un outil qui échoue, une question qu'il faut poser
deux fois) disparaissent au bout de 30 jours avec la conversation
([fiche 0034](0034-conversations-du-chat.md)), sans que personne les ait
relevés. Ce sont pourtant les meilleurs cas pour le banc, à une condition :
le dépôt est public, et un cas ne doit porter ni donnée de la collection ni
donnée d'un client.

**Options.**
1. **Relire le journal à la main** de temps en temps. Rien ne dit quelle
   conversation regarder, et 30 jours passent vite.
2. **Un 👎 seul.** Simple, mais il dépend d'un geste que l'on oublie ; une
   erreur de modèle ou un plafond de tours se voient sans lui.
3. **Un 👎 avec une note, et des signaux du serveur**, gardés à côté de la
   réponse, puis une commande qui en fait des brouillons anonymisés.

**Décision.** Option 3.
- **Le 👎.** Sous chaque réponse, avec une note libre facultative (500
  caractères), envoyé par `POST /api/assistant/answers/{id}/flag`, réservé
  aux comptes de gestion et à l'auteur de la conversation. Un second appui
  remplace la note.
- **Les signaux automatiques**, enregistrés de la même façon : erreur du
  modèle ; erreur d'un outil (outil inconnu, arguments refusés, exemplaire
  introuvable, droit perdu) ; plafond de quatre tours atteint alors que le
  modèle voulait encore appeler un outil ; **question reformulée** : la
  question suivante de la même conversation arrive dans les trois minutes
  après la réponse et redit la précédente (au moins la moitié des mots
  pleins en commun, ou les deux textes très proches). Le signal s'attache à
  la réponse précédente, celle qui n'a pas servi. Une question de suite
  (« et la première ? ») partage trop peu de mots pour compter.
- **« Défaut : … ».** Une question qui commence par « Défaut : » est un
  rapport, pas une question : elle ne part pas au modèle, le chat répond
  qu'elle est notée, et elle s'attache à la réponse précédente de la
  conversation, avec son texte pour note. La convention sert pendant les
  essais du chat comme au quotidien.
- **Rangement.** Une table `assistant_flags` dans `assistant.sqlite3`, créée
  au démarrage si elle manque : conversation, question, message de la
  question, réponse, type, note. Aucun texte de résultat d'outil.
- **Conservation.** Une conversation signalée échappe à la purge des 30
  jours, jusqu'à **180 jours** après le signal : le temps d'en tirer un cas.
  Elle reste effaçable par son auteur, avec ses signaux.
- **Brouillons.** `pokeprice-manage --data <dossier> assistant-drafts` lit
  le journal et la base en lecture seule et écrit, sur la sortie standard ou
  dans un fichier neuf, un brouillon par échange signalé au format des
  commandes du banc, marqué `"draft": true`. La question et la note y passent
  après remplacement de chaque identifiant, montant, date, adresse, téléphone
  et nom connu de la base (comptes, clients, exemplaires, annonces, demandes)
  par un emplacement `<…_n>`. La réponse du chat et les valeurs des arguments
  d'outils n'y passent pas. Le banc refuse un cas resté brouillon.

**Conséquences.**
- Un échec du chat devient un cas du banc en quelques minutes, sans relire
  tout le journal.
- Une question signalée qui nomme un client reste jusqu'à 180 jours côté
  serveur, au lieu de 30. Le cas tiré pour le dépôt, lui, ne la nomme pas.
- Le remplacement ne reconnaît que les noms connus de la base et les formes
  régulières : un nom tapé en minuscules qui n'est pas dans la base
  (« la tante de lily ») passerait. Celui qui complète le brouillon le relit
  avant de le copier dans `commands.json`.
- L'heuristique de reformulation se trompe parfois : un signal de trop coûte
  un brouillon à jeter, un signal manqué reste rattrapable par le 👎.
- Un « Défaut : » compte dans le plafond de questions du jour, sans jeton.

**Pour aller plus loin.** [L'assistant dans le guide](../APP.md#lassistant),
`src/pokeprice/assistant_signals.py`, `src/pokeprice/assistant.py`,
`tests/test_assistant_signals.py`.
