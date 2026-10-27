# Sécurité

Merci de signaler toute faille **en privé**, jamais dans une issue publique :
utilisez l'onglet **Security → Report a vulnerability** de ce dépôt (avis de
sécurité privés de GitHub). Décrivez la faille, comment la reproduire et son
impact. Le projet est tenu par une seule personne : comptez une première réponse
sous sept jours en général, sans garantie.

Ne testez pas sur le site en ligne au-delà de ce qui est nécessaire pour
démontrer le problème, et n'accédez à aucune donnée qui n'est pas la vôtre.

## Ce que fait l'application

- Gestion privée (`/gestion`) : comptes de l'équipe, mots de passe hachés
  avec scrypt, sessions en cookie `HttpOnly`, `SameSite=Strict`, `Secure`
  derrière HTTPS ; contrôle d'origine sur toute requête qui modifie.
- Vitrine publique (`/`) : lecture seule, réponses construites champ par
  champ (aucune donnée privée), lectures et inscriptions limitées par adresse.
- Comptes clients : inscription validée par un administrateur ; un client
  n'accède à aucune route de gestion (test de couverture des routes).
- Les clés d'API (Gemini) restent sur le serveur, dans un fichier
  d'environnement lisible par le seul service ; elles ne sont jamais envoyées
  au navigateur ni versionnées.

Pour aller plus loin : l'[audit de sécurité](docs/AUDIT-SECURITE.md) fait avant la
publication du code, et le [registre des traitements de données](docs/RGPD.md).
