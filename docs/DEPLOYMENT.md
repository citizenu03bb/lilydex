# Préparation du déploiement Internet

Configuration d'hébergement permanent préparée le 4 octobre 2026,
**non installée sur un serveur externe**. Depuis le 5 octobre, un
[tunnel HTTPS Cloudflare temporaire](TUNNEL.md) permet l'accès distant autorisé
par le propriétaire pendant le développement. La base et les photos restent sur le portable ;
le trafic web transite par Cloudflare.

## Proposition d'exploitation

Un petit serveur Linux avec disque local persistant, FastAPI sur loopback,
SQLite et Caddy pour HTTPS. Un seul processus applicatif au départ. Une machine
de 2 vCPU, 2 à 4 Go de RAM et environ 40 Go de disque est une hypothèse de
dimensionnement à mesurer, pas un résultat de test de charge. Les données gérées
initiales et leur ZIP occupent seulement quelques dizaines de Mo ; les photos
originales sont conservées dans l'instantané séparé d'environ 590 Mo.

[Hetzner Cloud](https://www.hetzner.com/cloud/) en Allemagne ou Finlande est une
option à chiffrer ; un serveur déjà disponible peut aussi convenir. Les tarifs
du site consulté sont chargés dynamiquement et n'ont pas fourni de devis fiable
avec TVA France et options. Aucun montant mensuel n'est donc présenté comme
validé. Chiffrer le serveur, l'adresse IP, la sauvegarde externe et le domaine
avant engagement. Google One peut recevoir une copie d'archive, sans héberger
le service ou synchroniser le fichier SQLite actif.

## Fichiers fournis

- `deploy/pokeprice.service` : service applicatif, utilisateur dédié, cookie
  HTTPS, hôte autorisé, base et photos sous `/srv/pokeprice/inventory`.
- `deploy/pokeprice-backup.service` et `.timer` : sauvegarde quotidienne en ZIP
  sous `/srv/pokeprice/backups`, sans suppression automatique de versions.
- `deploy/Caddyfile.example` : exemple HTTPS et proxy local. Remplacer
  `cards.example.com` par le domaine retenu.

Les fichiers sont des modèles préparés, pas des services déjà activés. Installer
Python 3.13, uv, Caddy et les dépendances sur le serveur retenu, puis copier le
code sous `/opt/pokeprice` et exécuter `uv sync --frozen --extra web`. Ne pas
copier `.env`, la collection ou les clés dans un dépôt public.

Créer l'utilisateur système `pokeprice` et le dossier `/srv/pokeprice` avec les
droits adaptés. Restaurer un ZIP contrôlé vers un **nouveau dossier** de données
et vérifier les comptes. Créer l'administrateur avant d'ouvrir le proxy :

```bash
cd /opt/pokeprice
# Exécuter avec l'utilisateur système de l'application.
.venv/bin/python -m pokeprice.manage --data /srv/pokeprice/inventory user pat --role admin
```

Cette commande demande le mot de passe sans l'afficher. Elle crée un compte ;
si celui-ci existe dans la sauvegarde restaurée, conserver ce compte.
Le mode `--secure-cookie` refuse de démarrer sans administrateur actif,
pour empêcher une initialisation publique non protégée.

Créer `/etc/pokeprice.env` avec `POKEPRICE_HOST=cards.example.com`, puis adapter
les unités et la configuration Caddy au domaine réel. Caddy gère les certificats
si les conditions DNS/réseau sont remplies ; voir sa
[documentation HTTPS](https://caddyserver.com/docs/automatic-https).
La collection et les photos passent par la même application authentifiée :
ne pas ajouter de chemin public vers `/srv/pokeprice`.

## Vérifications avant publication

Sur une copie d'abord : vérifier la connexion HTTPS, l'expiration/déconnexion,
les accès consultation/gestion, les photos privées et un parcours Android réel.
Vérifier les quantités après redémarrage, les erreurs de sauvegarde et l'espace
disponible. Restaurer un ZIP récent dans un environnement distinct avant de
basculer les données réelles. `/health` vérifie que le processus et sa base
répondent, sans publier les quantités ou identités.

Activer les unités seulement après validation de la machine et du domaine.
Vérifier le timer avec `systemctl list-timers` et le résultat du service dans
le journal. Les ZIP restent privés. Prévoir leur copie hors du serveur et une
alerte en cas d'échec ; ces deux éléments ne sont pas configurés par les modèles.
Le timer fonctionne selon le fuseau du serveur : choisir Europe/Paris si l'on
veut une sauvegarde vers 03 h heure française.

Avant une mise à jour, sauvegarder la base et les photos, puis tester la version
et ses migrations sur une restauration distincte. Pour un retour arrière après
migration, restaurer le ZIP précédent dans un autre dossier et pointer l'ancien
code vers celui-ci ; ne pas ouvrir un schéma plus récent avec un ancien code.

## Points à décider

Fournisseur, région, coût total, domaine et destination de sauvegarde externe.
Le déploiement public et l'engagement payant viennent après cette validation.
Aucune commande d'installation distante, création de compte, ouverture de port
public ou activation de service système n'a été exécutée ici.
