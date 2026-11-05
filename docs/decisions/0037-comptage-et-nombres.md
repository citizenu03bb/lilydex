# 0037 — Le chat compte par un outil serveur, et chaque nombre de sa réponse vient d'un outil

> **Statut :** proposée, complète la [décision 0032](0032-outils-assistant-lecture.md) (V1.1 du chat) · **Date :** 2026-11-05

**Contexte.** Le soir de la mise en service du chat, à « top10 des cartes en
doublon », Gemini 3.8 Flash a répondu sans appeler d'outil, avec des chiffres
inventés : Pikachu 16, Évoli 15, Miaouss 9, Salamèche 8. Par nom, la
collection en compte 9, 12, 5 et 5 ; par édition exacte, le classement est
tout autre (deux cartes à sept exemplaires, puis des énergies). Aucun des
huit outils de la fiche 0032 ne savait répondre : `search_copies` renvoie au
plus 50 résumés par page, et compter des pages à la main fausse les totaux.
La consigne disait déjà « n'invente jamais un chiffre », sans dire comment
compter.

« Doublon » a deux sens : la même édition (ce qui se vend en lot de doublons)
ou le même Pokémon, toutes éditions confondues. Les deux classements
diffèrent.

**Options.**
1. **Relever le plafond de `search_copies`** : le modèle compterait lui-même
   des centaines de lignes ; c'est cher en jetons et peu fiable.
2. **Une règle seule dans la consigne** (« ne donne aucun nombre sans
   outil ») : le modèle refuserait honnêtement, sans pouvoir répondre.
3. **Un outil de comptage côté serveur, et une règle des nombres** : le
   serveur compte toute la collection ; le modèle ne fait que lire le
   résultat.

**Décision.** Option 3.

*L'outil.* `count_copies` rejoint le registre de la fiche 0032, au même
contrat : schéma strict, sortie relue par `check_output`, export
`docs/assistant-tools.json` régénéré. Il compte toute la collection, sans
page ni plafond, et regroupe par édition exacte (nom + extension + numéro +
langue, le défaut), par nom, extension, langue, statut d'identification,
stock ou album. `duplicates_only` ne garde que les groupes d'au moins deux
exemplaires ; `top` (1 à 100, 10 par défaut) borne le classement, du plus
nombreux au moins nombreux. Les filtres reprennent ceux de `search_copies`
(mots, extension, langue, statut, stock, mise en vente) ; `search_copies`
gagne le filtre de langue, que le modèle lui passait dès qu'il l'a vu sur
`count_copies`. La sortie donne le
total des exemplaires, le nombre de groupes et de doublons, les exemplaires
en trop, et pour chaque groupe ses champs, son nombre, le nombre d'éditions
(hors regroupement par édition) et jusqu'à cinq identifiants. Les vendus
comptent, sauf filtre `stock`.

*La règle.* Une section à part de `assistant_prompt.md`, « Nombres » :
chaque nombre de la réponse vient d'un résultat d'outil de cette question,
ou de la question elle-même ; sinon le chat dit qu'il ne peut pas le
compter. Il ne numérote pas un classement, pour que tout nombre affiché soit
un nombre vérifiable. Classements, doublons et comptes par groupe passent par
`count_copies`.

*Le banc.* La vérification `check_numbers` d'un cas échoue si la réponse
contient un nombre absent de la question et des résultats d'outils de la
question. Le cas `compter-01` rejoue la question du soir sur des doublons
synthétiques ; `compter-02` (par nom) et `compter-03` (par langue)
complètent. Une réponse sans outil, comme celle du soir, échoue deux fois :
mauvais outil et nombres sans source.

**Conséquences.**
- Un nombre calculé par le modèle (une différence, des exemplaires « en
  trop » non renvoyés) fait échouer le banc, même juste. C'est voulu :
  l'outil renvoie les sommes utiles (`duplicate_extra_copies`).
- La vérification des nombres ne lit que les chiffres ; un nombre écrit en
  toutes lettres lui échappe.
- Chaque appel relit toute la collection, comme les autres outils : coût
  accepté, non mesuré sur la base réelle.
- Les identifiants d'un groupe ne deviennent pas encore des liens dans le
  chat : seul un exemplaire renvoyé avec son nom et son extension en devient
  un.

**Pour aller plus loin.** [Schémas](../assistant-tools.json),
`tests/test_assistant_tools.py`, [banc](../../bench/assistant/README.md).
