# Audit de sécurité avant publication du dépôt — 16 octobre 2026

Audit fait avant de rendre le code public, alors que l'application tourne déjà
sur Internet (vitrine publique, inscription des clients ouverte).

## Résumé

| Domaine | Résultat |
|---|---|
| Secrets dans l'historique publié | aucun (clés Google, OpenAI, GitHub, Slack, clés privées, mots de passe, jetons) |
| Données personnelles dans l'historique publié | aucune (auteurs `noreply`, ni nom, ni e-mail, ni IP) |
| Ancien dépôt `pokeprice` | **ne pas le rendre public** : GitHub y garde les commits d'avant la réécriture du 12 octobre |
| Dépendances Python (95, dont 43 déployées) | aucune vulnérabilité connue (pip-audit, base PyPI/OSV) |
| Application | 1 défaut corrigé (déni de service), 1 durcissement ajouté (HSTS) |

## Historique et nouveau dépôt

- Les commits d'avant la réécriture du 12 octobre portent le nom et l'adresse
  personnelle du propriétaire, et la documentation de l'époque des
  identifiants de dossiers Google Drive. Ils ne sont plus dans `master`, mais
  GitHub les conserve dans l'ancien dépôt et les sert encore par leur
  identifiant ; rendre ce dépôt public les exposerait.
- Le nouveau dépôt `citizenu03bb/lilydex` a été créé **privé** à partir de
  `master` seul : GitHub n'y connaît aucun de ces anciens commits (vérifié par
  l'API). L'unique issue y a été transférée. L'ancien dépôt reste privé.
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

1. Choisir une licence (sans licence, le code reste « tous droits réservés »).
2. Une fois public, activer les avis de sécurité privés (Settings → Security)
   pour que `SECURITY.md` fonctionne.
3. Faire pointer le dépôt local vers `lilydex` (`git remote set-url origin …`)
   et garder l'ancien dépôt `pokeprice` privé (ou le supprimer).

## Points à suivre

- Inscriptions sans captcha : limitées à 5 par heure et par adresse et soumises
  à validation ; surveiller la liste « en attente ».
- Suppression d'un compte client et de ses données (RGPD) : prévue en
  tranche 5, avec la page de confidentialité.
- Les limites de débit sont gardées en mémoire du processus : elles repartent
  de zéro à chaque redémarrage du service.
