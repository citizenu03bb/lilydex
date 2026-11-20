# 0047 — Un classeur s'importe page par page sur le serveur, en tâche de fond moins prioritaire que le site, et s'arrête au budget Gemini

> **Statut :** en vigueur, complète les décisions [0022](0022-agent-confirme-ou-demande-photo.md), [0025](0025-photo-page-classeur-gestion.md) et [0008](0008-reverses-examen-physique.md) · **Date :** 2026-11-20

**Contexte.** Le jalon M3 doit faire passer un classeur d'environ 100 cartes
de la photo à un inventaire « à vérifier » en moins d'une heure de travail
humain (critère S5), sans la ligne de commande. Aujourd'hui, un classeur neuf
passe par le portable : `pokeprice scan` découpe et lit les pages, puis un
manifeste s'importe dans une base. Or la base du serveur fait foi
([fiche 0002](0002-oracle-cloud-serveur-fait-foi.md)) et rien ne se
synchronise ([fiche 0013](0013-pas-de-synchronisation.md)). Dans
l'application, le dépôt de page ([fiche 0025](0025-photo-page-classeur-gestion.md))
découpe sans rien lire, et la saisie lit une carte à la fois, pendant la
requête. Le serveur est une petite machine de l'offre gratuite : un import
qui lit, compare des images et appelle Gemini pendant une heure ne doit pas
ralentir la vitrine. Le propriétaire a fixé le cadre : import sur le serveur,
clients d'abord, unité de travail la page, reprise toute seule, arrêt au
budget, administrateurs seulement.

**Options.**
1. **Garder le portable et documenter le transfert** (la procédure de M5) :
   le classeur reste hors de l'application, et la base du portable, qui ne
   fait pas foi, sert d'étape. Écarté : S5 se mesure sans la ligne de
   commande.
2. **Lire dans les requêtes web**, en tâches d'après réponse comme la saisie :
   un redémarrage perd le travail en cours, et chaque lecture prend du
   processeur au service qui répond aux clients.
3. **Un service d'import partagé et un processus à part**, qui reprend un
   état durable page par page, à une priorité plus basse que le site.

**Décision.** Option 3.

*Qui.* Seul un compte administrateur importe, depuis la gestion ou par
`pokeprice-manage --data … binder-import` sur le serveur. La ligne de commande
et l'application appellent le même service (`binder_import.py`) ; la commande
`pokeprice scan` du portable reste un outil de rapport et n'écrit aucune base.

*L'unité de travail : la page.* Un import vise un album, existant ou créé, et
une grille (3×3 par défaut ; 2×2, 3×4, 4×3, ou une carte par photo). Chaque
photo porte son numéro de page dans l'ordre du classeur. Une photo de page est
découpée par le découpage de la ligne de commande (`normalize_orientation`,
`detect_grid_layout`, `slice_grid` de `slicer.py`, par la même fonction que le
dépôt de page de la fiche 0025), jamais par une copie. Une photo de carte
remplace une pochette. Quand la découpe se passe mal, la personne reprend la
page entière ou les seules pochettes en cause.

*Le téléversement reprenable.* Une photo monte en morceaux de 512 Kio, à un
décalage annoncé ; le serveur garde le fichier partiel et répond au décalage
reçu. Le téléphone garde la photo jusqu'à l'accusé de réception : une coupure
reprend au dernier morceau reçu, et un rechargement de la page reprend la
file. L'empreinte SHA-256 annoncée au départ est vérifiée à la fin ; la même
photo annoncée deux fois est le même téléversement.

*L'état durable.* Les imports, leurs pages, leurs pochettes et leurs
téléversements vivent dans `binder_imports.sqlite3`, à côté de la base, créé
au premier usage : aucune migration de la collection. Les photos vont dans la
réserve par empreinte ([fiche 0028](0028-reserve-de-photos-par-empreinte.md)).
Chaque pochette avance par étapes enregistrées l'une après l'autre : reçue,
découpée, lue, exemplaire créé, contrôlée. Chaque étape se rejoue sans
effet de bord : l'exemplaire d'une pochette a un identifiant dérivé de
l'import, de la page et de la position, et sa création ne se fait qu'une fois ;
un contrôle déjà fait sur la photo courante n'est pas refait. Un redémarrage
reprend à la première étape non finie.

*Le processus à part.* `pokeprice-manage binder-worker` tourne dans son
service systemd, `pokeprice-import.service`, avec `Nice=10`,
`IOSchedulingClass=idle`, `CPUWeight=20` et `IOWeight=20` contre 100 pour le
site. Il traite une pochette à la fois et ne fait rien quand aucun import
n'attend. Le service web reçoit les photos et écrit l'état, sans rien lire
lui-même.

*Les interruptions.* Un redémarrage du serveur : le processus reprend l'état.
Une erreur Gemini (quota compris, que l'API ne distingue pas toujours) : la
pochette est réessayée après 1, 2, 4… minutes, au plus 30 ; l'import attend
sans bloquer les autres pages et repart seul. Une pochette qui échoue trois
fois alors que ses voisines passent devient « à reprendre » : sa photo est en
cause. Une coupure du téléphone : le téléversement reprend.

*Ce que l'import crée.* Chaque pochette lue devient un exemplaire
« à vérifier » (`identification_status="review"`) à son emplacement, avec sa
photo, la lecture et la recherche au catalogue comme preuve. Quand le
catalogue trouve une seule édition, au nom exact et à la référence complète,
elle est retenue sans être confirmée, comme à la saisie. Une pochette sans
recto lisible devient « à reprendre » ou se marque vide d'un geste. Une
énergie de base reconnue par l'image n'est pas lue par Gemini
([fiche 0015](0015-energies-de-base-en-vrac.md)). Les contrôles de la saisie
suivent : finition, édition par l'image, état. La file d'examen de l'import
suit l'ordre du classeur : page, puis pochette.

*L'agent de revue.* Après chaque page, l'agent de revue
([fiche 0022](0022-agent-confirme-ou-demande-photo.md)) passe sur ses
exemplaires. Pour un exemplaire importé, il confirme aussi l'identité, avec la
variante et l'état, quand l'édition retenue est l'unique résultat exact du
catalogue, que le contrôle d'édition par l'image la désigne avec la marge de la
[fiche 0006](0006-dinov2-marge.md) et que la langue lue est celle de
l'édition ; sous le seuil de valeur seulement. Tant que la vérification à
l'aveugle de la feuille de route n'a pas passé sa porte, il tourne en
simulation : le rapport dit ce qu'il confirmerait, et rien n'est écrit. Le
passage à l'écriture est un seul réglage de la base, `agent_review_apply`,
réservé à l'administrateur et journalisé, faux sans ligne.

*Le budget Gemini.* Chaque appel à Gemini fait par l'import (lecture,
finition, état) compte ses jetons, et leur coût s'estime avec la grille de
tarifs du chat (`assistant_pricing.json`, au taux de la
[fiche 0039](0039-alerte-de-cout-du-chat.md)). L'import affiche ce coût,
par classeur et par page. Avant chaque appel, si le coût atteint le budget de
l'import, l'import s'arrête : les pages restent en l'état, et une
notification demande à l'administrateur s'il continue. Continuer ajoute le
budget initial, une fois. Le budget initial est de 3 € par import
(`POKEPRICE_IMPORT_BUDGET_EUR`) : au tarif relevé, trois appels par carte
coûtent environ 1 € pour 100 cartes, 2 € au tarif annoncé pour 2027. Le
dépassement est au plus d'une étape : une lecture, ou les contrôles d'une
carte (finition et état, deux appels).

*La file « Référentiel à compléter ».* Une édition (extension × langue)
apportée par un classeur n'entre dans la file que si l'un de ses exemplaires
importés a une valeur en jeu d'au moins le seuil (10 € par défaut, le seuil de
S2), ou si l'édition compte au moins 20 exemplaires dans la collection.
Sinon, elle ne compte que dans un décompte du rapport d'import. Ce choix est
celui de la session qui orchestre M3 : la preuve d'une édition coûte environ
une heure ([guide du référentiel](../PRINT_REFERENCE_GUIDE.md)), et une
édition peu chère et rare ne la rembourse pas.

*Les reverses.* Pour une carte de « À examiner » au motif « reverse
possible », la fiche propose, sous la lecture de finition, une prise de vue au reflet : la carte inclinée
sous une lumière rasante. Cette photo, marquée comme reflet, passe par la
lecture de finition. Si la photo est de qualité suffisante, une bande
arc-en-ciel sur le corps de la carte (`background_shine="visible"`) propose la
reverse, un corps nettement mat (`not_visible`) propose la Standard, même
au-dessus du seuil : la photo tient lieu de l'examen sous éclairage rasant de
la [fiche 0008](0008-reverses-examen-physique.md). Une photo ordinaire, elle,
ne prouve toujours pas la Standard.

**Conséquences.**
- Un classeur se photographie au téléphone, page par page, sans attendre la
  lecture ; le serveur travaille ensuite seul, et la personne ne voit que les
  cartes que ni le catalogue ni l'agent ne tranchent.
- Le site garde la main sur le processeur et le disque ; un import est donc
  plus lent quand la vitrine est chargée.
- Tant que l'agent est en simulation, toutes les cartes importées restent à
  une personne : S5 ne se mesure qu'après la porte.
- L'état d'un import n'est pas dans la sauvegarde de la collection. Une base
  restaurée sans lui garde les exemplaires créés ; un import repris recrée
  les mêmes identifiants, sans doublon.
- Le budget borne un import, pas le mois : dix imports coûtent dix budgets.
- Une prise au reflet ratée ne tranche rien et laisse la carte à l'examen en
  main.

**Preuve.** `tests/test_binder_import.py`.
