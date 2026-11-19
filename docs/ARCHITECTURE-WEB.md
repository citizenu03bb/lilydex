# Carte des modules web

> **Pour qui :** toute personne qui doit modifier le serveur web et cherche où vit une route.
> **Vous y trouverez :** le rôle de chaque module, la façon dont l'application est assemblée et les tests qui prouvent que les routes ne bougent pas.

## Assemblage

`src/pokeprice/webapp.py` ne contient que `create_app`. Elle appelle
`build_services` (`routes/context.py`), qui construit une fois, dans un ordre
fixe, l'origine publique, le réglage d'indexation, le magasin, les hôtes
autorisés puis chaque service, et les range dans un `AppContext`. Elle installe
ensuite la sécurité (`security.py`) et les gestionnaires d'erreurs
(`errors.py`), puis appelle chaque `register_<nom>(app, ctx)` dans un ordre
qui fait partie de la table des routes : ne le changez pas sans raison.

Un module de `routes/` expose une ou plusieurs fonctions
`register_<nom>(app, ctx)` qui déclarent ses routes sur `app` avec les services
de `ctx`. Aucun module web n'importe `webapp` ; `webapp` réexporte seulement les
noms que les tests et d'autres modules lui demandent (`__all__`).

## Modules de premier niveau

| Module | Rôle |
|---|---|
| `web_constants.py` | Constantes partagées : `APP_SHELL`, langues, clé de texte, `interface_version`, `indexing_enabled` |
| `schemas.py` | Corps de requête validés par FastAPI |
| `passwords.py` | Hachage des mots de passe et création de compte |
| `errors.py` | Codes d'erreur côté visiteur et gestionnaires d'exceptions |
| `security.py` | Hôtes autorisés, écritures de même origine, en-têtes de réponse |

## Modules de `routes/`

| Module | Ce qu'il sert |
|---|---|
| `context.py` | `AppContext` et `build_services` |
| `auth_deps.py`, `limits.py`, `pages.py` | Dépendances de session et de rôle, limiteurs de débit, rendu des pages ; construits par `build_services` |
| `hooks.py` | Contrôles lancés après la réponse, partagés par la saisie, l'identification et les lots de photos |
| `auth.py` | Première configuration, connexion, session, sonde de santé, déconnexion |
| `users.py` | Comptes de gestion, par un administrateur |
| `settings.py` | Réglages d'administrateur : paiement, marge du plancher, rotation des lots |
| `shell.py` | Coquille installable de la gestion, ressources statiques, favicon |
| `storefront.py` | Pages de la vitrine, adresse propre d'une carte, `robots.txt`, plan du site |
| `public.py` | API publique : recherche, inscription, devis, demandes des invités, annonces |
| `accounts.py` | Compte d'un client et administration des comptes clients |
| `client_requests.py` | Demandes d'achat des clients, côté gestion |
| `floor_requests.py` | Dérogations au plancher anti-bradage |
| `copies.py` | Exemplaires : listes, détail, corrections, références, prix, photos |
| `capture.py` | Séances de saisie d'une page de classeur |
| `photo_batches.py`, `move_batches.py` | Lots de photos et lots de déplacements, aperçus, application, annulation |
| `intake.py` | Brouillons de saisie par photo |
| `checks.py` | Contrôles d'état, de variante et d'édition d'un exemplaire |
| `listings.py` | Annonces de la vitrine côté gestion |
| `sales.py` | Registre des ventes, modifications, brouillon d'annonce |
| `exports.py` | Export CSV, JSON ou HTML |
| `backup.py` | État des sauvegardes, lancement forcé, téléchargement |
| `push.py` | Clé publique et abonnements Web Push |
| `statistics.py` | Statistiques d'audience |
| `todo.py` | Brief et file « À toi » |
| `assistant.py` | Chat de gestion, chargé au démarrage et non à l'import |

## Preuves que les routes ne changent pas

- `tests/test_web_snapshots.py` compare aux fichiers de `tests/snapshots/` la
  table des routes (ordre compris) dans chaque configuration, le document
  OpenAPI avec et sans l'API agent, les intergiciels, les gestionnaires, l'état
  de l'application et les en-têtes ; il compare aussi `robots.txt` et le plan du
  site octet par octet. On ne régénère jamais un instantané pour faire passer une
  étape.
- `tests/test_web_context.py` vérifie l'ordre de construction des services,
  que les modules web n'importent pas `webapp` et qu'aucune annotation différée
  n'est utilisée là où FastAPI les lit.

Les raisons de ce découpage sont dans la
[décision 0046](decisions/0046-decouper-webapp-par-groupe-de-routes.md).
