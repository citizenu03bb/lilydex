# 0039 — Le chat prévient une fois par mois quand son coût estimé atteint 30 €, sans plafond dur

> **Statut :** proposée, complète les décisions [0031](0031-modele-du-chat.md), [0033](0033-notifications-web-push.md) et [0034](0034-conversations-du-chat.md) · **Date :** 2026-11-05

**Contexte.** Le chat de gestion paie chaque jeton à Google, sur une clé à
lui ([fiche 0031](0031-modele-du-chat.md)). Au tarif relevé et à l'usage
prévu, il coûte de 3 à 7 $ par mois. Le plafond de 100 questions par jour
borne le nombre de questions, pas leur taille : une conversation qui fait
tourner les outils à vide, une clé utilisée ailleurs ou un tarif qui change
peuvent faire grimper la facture sans que rien ne se voie dans la gestion.
Le propriétaire ne veut pas de coupure automatique : un chat qui s'arrête en
pleine saison de vente gêne plus qu'une facture de quelques euros de trop.

**Options.**
1. **Un plafond dur** : le chat s'éteint au-delà d'un montant. Écarté par le
   propriétaire.
2. **L'alerte de budget de Google Cloud** : elle existe, mais par e-mail,
   avec un retard de plusieurs heures, sur un compte que Lily ne lit pas.
3. **Une estimation côté serveur et une alerte Web Push** : les jetons de
   chaque question sont déjà connus du serveur ; leur coût se calcule au tarif
   public, et l'alerte part sur le téléphone par le canal existant.

**Décision.** Option 3, en plus du plafond de questions qui reste.

*Le compte.* Après chaque question, ses jetons d'entrée et de sortie (la
réflexion du modèle comprise, comptée en sortie par Gemini) s'ajoutent au
cumul du mois civil, par modèle, dans la table `token_months` de
`assistant.sqlite3`. Ce cumul est à part du journal des questions : la purge
des 30 jours ([fiche 0034](0034-conversations-du-chat.md)) n'entame jamais un
mois en cours (un mois de 31 jours dépasserait la fenêtre). Il ne porte que
des nombres, jamais de texte ni de compte, et se garde 13 mois. Le mois est
celui du temps universel, comme le plafond du jour : l'alerte peut changer de
mois une ou deux heures avant minuit à Paris. Une question coupée en plein
tour de modèle ne compte que les tours finis : l'estimation peut être un peu
basse, jamais haute.

*Le tarif.* Une seule grille, `src/pokeprice/assistant_pricing.json`, en
dollars par million de jetons, avec la source et la date du relevé. Elle
était dans `bench/assistant/` ; elle passe dans le paquet parce que le
serveur doit la lire sans dépendre de la copie du dépôt, et le banc la lit au
même endroit. Un tarif annoncé s'écrit dans `changes`, avec son mois
d'entrée en vigueur : Gemini 3.8 Flash passe de 0,75 / 3,75 $ à 1,50 / 7,50 $
en janvier 2027, et l'estimation suit sans qu'on y pense. Un tarif changé
sans annonce ne se voit qu'en relisant la grille : l'alerte ne remplace pas
la facture.

*La devise.* La grille reste en dollars, la devise de la facture ; le seuil
est en euros, la devise du propriétaire. La conversion se fait à un taux fixe,
`POKEPRICE_ASSISTANT_EUR_PER_USD`, 0,95 € par défaut : au-dessus du cours du
jour (environ 0,86 €), pour que l'estimation en euros soit un peu haute et
l'alerte un peu en avance plutôt qu'en retard. Un cours en ligne ajouterait
un service à appeler pour un écart de quelques pour cent sur un seuil
quatre fois au-dessus du coût attendu.

*L'alerte.* Dès que le coût estimé du mois atteint
`POKEPRICE_ASSISTANT_COST_ALERT_EUR` (30 € par défaut ; 0 l'éteint), une
notification part sur les canaux d'alerte du notifieur (Web Push, et
l'e-mail s'il est configuré) : « Chat : coût estimé 31,20 € ce mois-ci »,
avec le seuil et un lien vers `/gestion`. Elle se déclenche au fil des
questions, après l'enregistrement des jetons, et non par un minuteur : le
coût ne bouge qu'avec une question. L'envoi part dans un fil à lui, la
réponse n'attend jamais le service de push. La table `cost_alerts` retient le
mois envoyé : une seule alerte par mois civil, même après un redémarrage. Si
tous les canaux échouent, la question suivante réessaie, dix minutes au plus
tôt après. Le texte ne porte que des montants : ni question, ni client.

*Un modèle sans tarif.* Si le modèle configuré n'est pas dans la grille, ses
jetons sont comptés mais pas chiffrés ; le journal du serveur l'écrit une fois
par processus. Le chat continue de répondre.

**Conséquences.**
- Le seuil est à 4 à 10 fois le coût attendu : une alerte signale un usage
  anormal ou un tarif changé, pas un mois chargé. Elle ne coupe rien ; c'est
  au propriétaire de regarder le journal du chat, la console de facturation,
  et d'éteindre la clé si besoin.
- Changer de modèle (`POKEPRICE_ASSISTANT_MODEL`) demande de vérifier qu'il
  figure dans la grille.
- L'estimation n'est pas la facture : pas d'offre gratuite déduite, pas de
  remise de cache, pas de taxe. Elle sert à prévenir, pas à comptabiliser.
- Les nouvelles tables se créent au premier usage, sans toucher au schéma
  des conversations.
