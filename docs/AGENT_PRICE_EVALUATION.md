# Vérifier le parcours agent des cartes sans prix

> **Pour qui :** une personne qui maintient ou évalue le pilote agent.
> **Vous y trouverez :** les cas rejouables, ce qu’ils prouvent et la réception d’un client utilisant le guide.

Le guide autonome [pokeprice-agent-prix](../skills/pokeprice-agent-prix/SKILL.md)
décrit le parcours des prix manquants avec les outils délégués existants.
Il couvre le diagnostic et l’application d’un plan préautorisé. La recherche
catalogue et l’enregistrement de l’accord restent du côté opérateur. Le
[pilote agent](AGENT_CONTROL.md) décrit cette frontière.

## Cas rejouables sans service externe

Les [cas synthétiques](../tests/fixtures/agent_pricing_cases.json) reprennent
les situations métier rencontrées pendant l’exploitation, sans UUID réel,
compte, photo ni emplacement privé. Les noms et références de cartes servent
à éprouver les rapprochements ; les montants et réponses fournisseur sont
fabriqués pour le test et ne constituent aucune cotation exploitable.

| Situation | Résultat attendu |
|---|---|
| Noeunoeuf avec suffixe Delta omis | Rattachement et relevé possibles si référence complète et PV correspondent. |
| Récupération d’Énergie avec une autre apostrophe | Rattachement possible sans réécrire le nom imprimé enregistré. |
| Nidoran♀ identifié, réponse fournisseur sans cotation | Rattachement conservé, prix inconnu et aucun relevé de prix créé. |
| Énergie avec numéro incomplet | Aucune édition attribuée à partir du seul nom. |
| Total de série, PV ou nom spécial différents | Autorisation refusée, fiche et historique inchangés. |
| Prix de référence déjà saisi | Refus d’écrasement et conservation de sa provenance. |
| Relevé non autorisé, malgré une cotation dans la réponse fournisseur | Lien catalogue possible et prix inconnu : le vide ne prouve pas une absence de cotation. |
| Catalogue déjà lié, relevé absent | Acquisition possible selon le plan ; pas de nouvelle observation physique. |
| Élektek modifié par une personne après autorisation | Conflit, relecture de la nouvelle version et conservation de ses observations. |

```bash
uv run --extra web --extra dev pytest -q \
  tests/test_agent_pricing_cases.py tests/test_agent_corrections.py \
  tests/test_catalogue_names.py
```

Les scénarios passent par le service d’autorisation opérateur et les routes de
l’API agent sur une base temporaire. Les réponses TCGdex sont injectées, jamais
acquises sur le réseau. L’enregistrement du plan ne modifie aucune fiche. Les
essais vérifient les prix, les sources, la conservation des observations, les
versions et les reçus. Les tests du contrat couvrent aussi la portée, les droits,
la révocation et le client CLI contre un serveur HTTP local.

Ces tests déterministes vérifient le logiciel, pas la capacité d’un modèle à
suivre le guide. Ils ne suffisent pas à déclarer le skill évalué ni à mesurer
son apport. Le guide et le protocole historiques scellés restent intacts ; leurs
résultats ne sont pas attribués à cette extension.

## Réception d’un client utilisant le guide

Exposez au client le nouveau guide et les seuls outils autorisés sur une
collection synthétique. Il n’accède ni au dépôt, ni à SQLite, ni à SSH, ni aux
identifiants humains. Consignez séparément la préparation opérateur du plan.
Le fournisseur, les coûts et les outils supplémentaires dépendent de l’essai
explicitement choisi ; la commande de tests ci-dessus ne lance aucun modèle.

Présentez une demande de prix manquants, puis les situations du tableau, sans
donner au client les réponses attendues. Vérifiez dans ses appels et sa réponse :

- Il consulte les capacités et les versions et ne prétend pas avoir paginé
  tout l’album lorsqu’il n’en a vu qu’une partie.
- Il distingue absence de lien, prix non acquis et absence de cotation prouvée.
  Il prépare un relais opérateur si les outils nécessaires manquent.
- Il examine les images disponibles avant une question physique, distingue les
  lectures des champs enregistrés et accepte une observation indéterminée.
- Il applique seulement le plan accepté, reprend une réponse perdue sans doublon
  et demande une nouvelle revue après conflit de version.
- Son bilan correspond aux reçus ; aucune édition, valeur ou confirmation
  physique n’est inventée et aucune route de gestion n’est utilisée.

Une trace manquante ou un outil indisponible laisse le critère non vérifié.
Consignez l’issue effective et les limites ; ne remplacez pas l’essai par un
résultat attendu. Les éventuelles traces de vraie collection restent privées.

## Mesurer l’utilité

Comparez des lots de difficulté comparable avec et sans guidage, en conservant
les mêmes moyens d’accès. Notez la méthode de chronométrage et les interruptions.

| Mesure | Ce qu’il faut compter séparément |
|---|---|
| Temps humain actif | Retrouver la carte, lire la consigne, observer, décider et répondre. |
| Temps opérateur | Préparer la délégation, chercher la source, relire et enregistrer le plan, clôturer l’accès. |
| Exécution et attente | Durée et nombre des appels, attente de conversation et reprises. |
| Qualité | Identifications erronées, valeurs injustifiées, doublons d’écriture et questions évitables. |
| Coût de mise en place | Développement initial et préparation de l’essai, distincts de l’usage récurrent. |

Rapportez les résultats observés avec leur échantillon, y compris les échecs.
La réussite technique et l’absence de question humaine ne prouvent pas à elles
seules une économie de temps ou une meilleure décision.
