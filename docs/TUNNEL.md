# Accès HTTPS temporaire pendant le développement

Activé le 5 octobre 2026, après le choix explicite de Cloudflare par le propriétaire.

Adresse actuelle :
[Poképrice](https://<nom-du-tunnel>.trycloudflare.com).
Utiliser le compte existant. La création du compte initial est fermée.

La base et les photos restent sur le portable. Le trafic web transite par
Cloudflare, qui fournit l'adresse HTTPS. L'application contrôle les accès aux
cartes, photos, comptes, exports et sauvegardes ; les cookies de session de ce
serveur sont `Secure`, `HttpOnly` et `SameSite=Strict`. Le serveur du tunnel
écoute uniquement sur `127.0.0.1:3824`. L'accès Wi-Fi reste disponible séparément.

## Processus à conserver actifs

Depuis la racine du projet, dans deux terminaux :

```bash
.venv/bin/python -m pokeprice.manage serve --port 3824 --secure-cookie \
  --allowed-host <nom-du-tunnel>.trycloudflare.com \
  --allowed-host 127.0.0.1
```

```bash
/tmp/pokeprice-cloudflared tunnel --no-autoupdate \
  --url http://127.0.0.1:3824 --protocol http2
```

Ces processus sont déjà démarrés pour la session actuelle : ne pas lancer de
doublons. Le client officiel utilisé est cloudflared 2026.9.3 ; son checksum a
été vérifié avant exécution. Le binaire dans `/tmp` n'est pas une installation
système et peut disparaître après redémarrage.

Un redémarrage du backend permet de charger les changements Python tout en
gardant le tunnel actif. Les fichiers HTML/CSS/JS sont relus à chaque requête ;
actualiser le navigateur pour charger leur nouvelle version.

Le portable, sa connexion, le backend et le tunnel doivent rester actifs.
Arrêter le processus cloudflared coupe l'accès distant. À chaque nouveau
Quick Tunnel, relever l'URL affichée et adapter `--allowed-host` au nouveau nom
avant de partager le lien. Aucun démarrage automatique ni hébergement permanent
n'a été configuré.

Les [Quick Tunnels](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/)
servent au développement : leur adresse change au redémarrage et ils n'ont pas
de garantie de disponibilité. La mise en production reste dans
[DEPLOYMENT.md](DEPLOYMENT.md). Sauvegarder régulièrement avec la commande
`pokeprice-manage backup` ; aucune copie externe automatique n'est configurée.

## Vérification effectuée

Via l'URL HTTPS réelle : page de connexion et état du serveur accessibles,
inscription initiale fermée, cartes/photos/comptes/exports/sauvegardes refusés
sans connexion (`401`). Un essai de connexion avec de faux identifiants depuis
la même origine renvoie l'erreur d'authentification attendue, sans rejet CSRF.
Les mots de passe des comptes existants n'ont pas été consultés ni modifiés.

Preuve : [cloudflare-validation.json](../outputs/development/cloudflare-validation.json).
