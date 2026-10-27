# Audit de sécurité avant la publication du code

> **Pour qui :** toute personne qui évalue la sécurité du site.
> **Vous y trouverez :** ce qui a été vérifié avant de rendre le dépôt public, les défauts corrigés, et ce qui a changé depuis.
> **Statut :** rapport daté du 16 octobre 2026, fait alors que l'application tournait déjà sur Internet (vitrine publique, inscription des clients ouverte). Il n'est pas tenu à jour ; la politique en vigueur est dans [SECURITY.md](../SECURITY.md).

## Résumé

| Domaine | Résultat |
|---|---|
| Secrets dans l'historique publié | aucun (clés Google, OpenAI, GitHub, Slack, clés privées, mots de passe, jetons) |
| Données personnelles dans l'historique publié | aucune (auteurs `noreply`, ni nom, ni e-mail, ni IP) |
| Historique d'avant la réécriture du 12 octobre | absent du dépôt public (vérifié par l'API GitHub) |
| Dépendances Python (95, dont 43 déployées) | aucune vulnérabilité connue (pip-audit, base PyPI/OSV) |
| Application | 1 défaut corrigé (déni de service), 1 durcissement ajouté (HSTS) |

## Historique et nouveau dépôt

- Les commits d'avant la réécriture du 12 octobre contenaient des données
  personnelles. Ils ne sont plus dans `master`.
- Le dépôt public `citizenu03bb/lilydex` a été créé **privé** à partir de
  `master` seul : GitHub n'y connaît aucun de ces anciens commits (vérifié par
  l'API). L'unique issue y a été transférée.
- Balayage par motifs de tout l'historique publié et `detect-secrets` sur
  l'arbre : 40 signalements, tous faux positifs (empreintes SHA-256 des pièces
  du référentiel, mots de passe fictifs des tests).
- Restent volontairement publics : le domaine du site, déjà public, et les
  scripts de déploiement, sans adresse IP ni secret.

## Application

Vérifié sans défaut :

- mots de passe hachés avec scrypt (sel aléatoire, comparaison à temps
  constant), 10 caractères au moins ;
- cookie de session `HttpOnly`, `SameSite=Strict`, `Secure` derrière HTTPS ;
  nouvelle session à chaque connexion, sessions fermées à chaque changement de
  rôle ou de statut ;
- contrôle d'origine sur toute requête qui modifie ; politique de sécurité du
  contenu stricte (aucun script ni style intégré), `X-Frame-Options: DENY`,
  `nosniff`, `Referrer-Policy: no-referrer` ;
- aucun `innerHTML` ni `eval` dans les scripts : tout texte passe par
  `textContent` ;
- SQL toujours paramétré ; le seul fragment dynamique est un `ORDER BY` choisi
  dans une liste fixe ;
- photos envoyées : 8 Mo au plus, JPEG, PNG ou WEBP, 24 Mpx au plus, images
  piégées refusées ; corps de requête limités à 9 Mo par Caddy ;
- clients : test de couverture qui exige le contrôle `staff` sur toute route de
  gestion ; vitrine construite champ par champ ; inscription sans révéler les
  adresses connues ;
- limites par adresse : la production voit la vraie adresse du visiteur, et un
  en-tête `X-Forwarded-For` falsifié ne contourne pas la limite de connexion
  (essai du 16 octobre : 5 refus puis 429) ;
- la clé Gemini reste sur le serveur, jamais envoyée au navigateur.

Corrigé le 16 octobre :

- **Déni de service sur la vitrine** : la recherche anonyme faisait deux
  requêtes SQL par publication (≈ 0,5 s pour 1 415 cartes) ; avec 300 lectures
  par minute et par adresse, une seule adresse pouvait occuper le serveur. Elle
  lit désormais la vitrine en deux requêtes (0,15 à 0,26 s, réseau compris).
- **HSTS** : derrière HTTPS, `Strict-Transport-Security: max-age=31536000`.

## Avant de rendre le dépôt public

1. Licence : MIT, choisie le 16 octobre (`LICENSE`, au nom de `citizen-lambda`).
2. Une fois public, activer les avis de sécurité privés (Settings → Security)
   pour que `SECURITY.md` fonctionne.
3. Faire pointer le dépôt local vers `lilydex` (`git remote set-url origin …`).

## Points à suivre

- Inscriptions et demandes sans compte, sans captcha : 5 de chaque par heure
  et par adresse IP, 3 demandes en attente par e-mail. Une demande ne bloque
  aucune carte ; une adresse usurpée se repère à la réponse du vendeur.
  Surveiller les demandes « E-mail non vérifié ».
- Liens de mot de passe : jeton de 256 bits, empreinte seule en base, usage
  unique, 7 jours ; le jeton reste après le `#` et quitte l'adresse à
  l'ouverture.
- Suppression d'un compte client et de ses données (RGPD) : prévue en
  tranche 5, avec la page de confidentialité.
- Les limites de débit sont gardées en mémoire du processus : elles repartent
  de zéro à chaque redémarrage du service.

## Ce qui a changé depuis

- La suppression d'un compte client est en place : espace **Mon compte**,
  commande `forget`, durées de conservation appliquées chaque nuit, registre
  des traitements ([Données personnelles](RGPD.md)).
- Les copies de sauvegarde sur Google Drive sont chiffrées avant l'envoi
  ([Sauvegardes](DAILY-BACKUPS.md)).
- La documentation est contrôlée par la suite de tests : aucun lien vers des
  dossiers ignorés par git, et aucun motif d'une liste privée (nom, e-mail,
  adresse IP), lue hors du dépôt ([Contribuer](../CONTRIBUTING.md)).
