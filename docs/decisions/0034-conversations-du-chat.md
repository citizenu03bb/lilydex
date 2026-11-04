# 0034 — Les conversations du chat restent 30 jours au plus, dans un fichier à part, hors des sauvegardes

> **Statut :** proposée, complète les décisions [0029](0029-assistant-de-gestion.md) et [0031](0031-modele-du-chat.md) · **Date :** 2026-11-04

**Contexte.** La V1 du chat de gestion répond aux questions de Lily en lisant
la collection par les outils de la [fiche 0032](0032-outils-assistant-lecture.md).
Le serveur doit garder une trace de chaque échange :

- la conversation en cours, pour qu'une question de suite (« et la
  première ? ») ait son contexte, et pour la retrouver en rouvrant le panneau ;
- le journal des questions et des appels d'outils, pour comprendre une
  réponse fausse et suivre le coût ;
- le compte des questions et des jetons, pour le plafond du jour.

Une question peut nommer un client (« la demande de Martin ? ») ; la réponse
cite des cartes et des montants. Ces textes n'ont pas leur place pour
toujours dans la base de la collection : elle est sauvegardée chaque nuit, et
une sauvegarde chiffrée se garde des mois sur Drive.

**Options.**
1. **Rien garder** : chaque question part seule. Pas de question de suite, pas
   de journal pour comprendre une erreur, pas de plafond fiable.
2. **Des tables dans `collection.sqlite3`**. Tout est sauvegardé avec la
   collection : une conversation effacée resterait dans chaque sauvegarde
   antérieure.
3. **Un fichier à part, `assistant.sqlite3`, à côté de la base**, sur le
   modèle de la mesure d'audience : hors des sauvegardes, avec une durée de
   conservation courte.

**Décision.** Option 3.
- `assistant.sqlite3` vit dans le dossier de la collection, mais ni `backup`
  ni la sauvegarde quotidienne ne le copient. Le perdre ne coûte que
  l'historique du chat.
- Il garde les questions et les réponses, et le journal : pour chaque
  question, le modèle, les jetons en entrée et en sortie (métadonnées d'usage
  du fournisseur), la durée, le nombre de tours et l'issue ; pour chaque appel
  d'outil, l'outil, ses arguments, sa durée et son issue. **Le texte des
  résultats d'outils n'y entre jamais** : il se recalcule depuis la base.
- **30 jours au plus.** `pokeprice-manage purge`, qui applique déjà les
  durées de conservation des clients chaque nuit, efface les messages, les
  questions et les appels plus anciens.
- **Effaçables par leur auteur** : le bouton « Effacer » du panneau et
  `DELETE /api/assistant/conversations` retirent les conversations et les
  arguments des appels. Le décompte de la question reste, sans texte ni
  argument, jusqu'à la purge : sinon effacer contournerait le plafond du
  jour.
- Chaque compte ne voit et n'efface que ses conversations.

**Conséquences.**
- Une restauration de sauvegarde ne ramène aucune conversation ; un effacement
  est réel au bout de 30 jours au plus.
- Le total de jetons visible dans la gestion porte sur 30 jours, pas sur le
  mois civil : il sert de repère, la facture fait foi.
- Une question qui nomme un client est gardée 30 jours, côté serveur. Elle
  part aussi chez Google à chaque question, comme l'indique la
  [fiche 0031](0031-modele-du-chat.md) ; la page [RGPD](../RGPD.md) devra le
  dire si le chat sert un jour à traiter les messages des clients (V3).
- Le journal d'un appel garde ses arguments : un mot cherché (« dracaufeu »)
  y reste 30 jours.

**Pour aller plus loin.** [L'assistant dans le guide](../APP.md#lassistant),
`src/pokeprice/assistant.py`, `tests/test_assistant.py`.
