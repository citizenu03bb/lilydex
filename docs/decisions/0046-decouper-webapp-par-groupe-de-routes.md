# 0046 — `webapp.py` est découpé par groupe de routes, par déplacements à l'identique prouvés par des instantanés

> **Statut :** en vigueur · **Date :** 2026-11-19

**Contexte.** Une revue externe a demandé de découper `webapp.py` et `app.js`.
`webapp.py` réunissait près de 3 000 lignes : schémas, mots de passe, en-têtes,
erreurs, services et toutes les routes dans une seule fonction `create_app`.
Un fichier de cette taille se relit mal et se modifie à plusieurs mains avec
des conflits ; or la table des routes, les en-têtes et les réponses sont le
contrat du serveur, et le moindre déplacement peut les changer sans bruit.

**Options.**
1. Réécrire les routes par groupe en les nettoyant au passage : le résultat
   est plus propre, mais un changement de comportement ne se distingue plus
   d'un déplacement.
2. Ne rien déplacer et ajouter des commentaires : la taille reste.
3. Déplacer le code à l'identique, un groupe à la fois, chaque étape prouvée
   par des instantanés.

**Décision.** Option 3.

- **Découpage.** Les modules feuilles d'abord (`web_constants`, `schemas`,
  `passwords`, `errors`, `security`), puis un module par groupe de routes dans
  `src/pokeprice/routes/`, avec une fonction `register_<nom>(app, ctx)`. Les
  services partagés sont construits une fois par `build_services` et réunis
  dans `AppContext` (`routes/context.py`). `create_app` garde l'ordre des
  appels `register_*`.
- **Déplacement à l'identique.** Pas de renommage, de correction ni
  d'amélioration dans un déplacement : ce qu'on voit dans le diff est un
  changement de fichier, rien d'autre.
- **Preuve.** `tests/test_web_snapshots.py` compare à des fichiers de
  `tests/snapshots/` la table des routes (ordre compris) dans chaque
  configuration, le document OpenAPI avec et sans l'API agent, les
  intergiciels, les gestionnaires d'erreurs et les en-têtes. Un instantané ne
  se régénère pas pour faire passer une étape : s'il change, l'étape est fausse.
- **Pull requests empilées.** Une demande par groupe, chacune sur la
  précédente ; l'orchestrateur relit, fusionne et déploie dans l'ordre, et le
  diff de chaque étape reste petit.

**Conséquences.**
- `webapp.py` ne garde que `create_app` et les noms que d'autres modules
  importent encore (`__all__`).
- Les écarts de style que les déplacements ont laissés (`raise … from` absent,
  deux affectations typées) restent signalés par des exceptions de `ruff` et de
  `mypy` dans `pyproject.toml` ; les corriger est un travail à part, hors
  déplacement.
- Une nouvelle route se range dans le module de son groupe ; un test vérifie
  qu'aucun module web n'importe `webapp`.
- Le découpage de `app.js` suit, avec la même méthode.
