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

## Banc comparatif des modèles Gemini

Huit modèles du fournisseur `google` ont été exécutés via le client Pi sur un
serveur HTTP local et une base SQLite temporaire isolée contenant huit cartes
synthétiques (cinq corrections préautorisées valides dont une sans cotation
fournisseur et une sans autorisation de relevé, un conflit de version `409`
après modification humaine concurrente, un numéro incomplet sans plan et une
carte déjà dotée d’un prix de référence humain). Le relevé détaillé est
conservé dans [`docs/evaluations/agent-pricing-gemini-2026-10-20.json`](evaluations/agent-pricing-gemini-2026-10-20.json).

*Conditions de mesure : 8 exemplaires synthétiques sur serveur local isolé, client Pi avec découverte `.agents/skills/pokeprice-agent-prix/SKILL.md`, 8 critères automatiques sur l’état final de la base et les appels CLI, octobre 2026.*

| Modèle | Score BDD | Durée | Appels outils | Jetons (entrée / cache / sortie) | Tarif ($ / M entrée · sortie) | Coût de la passe | Résultat |
|---|---:|---:|---:|---:|---|---:|---|
| **`gemini-3.1-flash-lite`** | **8 / 8** | **18,0 s** | **8** | 31 k / 41 k / 3,7 k | `$0.25` · `$1.50` | **`$0.0145`** | Regroupe les 6 appels `apply-correction`, relit la fiche en conflit `409` et rend un diagnostic exact. |
| **`gemini-2.5-flash-lite`** | **8 / 8** | 48,5 s | 11 | 33 k / 132 k / 10,9 k | `$0.10` · `$0.40` | **`$0.0090`** | Coût minimal par passe, appels séquentiels avec forte réutilisation du cache. |
| **`gemini-2.5-flash`** | **8 / 8** | 42,2 s | 12 | 37 k / 129 k / 6,5 k | `$0.30` · `$2.50` | `$0.0311` | Conforme sur les 8 critères. |
| **`gemini-3-flash-preview`** | **8 / 8** | 34,2 s | **6** | 38 k / 29 k / 4,2 k | `$0.50` · `$3.00` | `$0.0332` | Chaîne les commandes CLI en 6 appels. |
| **`gemini-3.5-flash-lite`** | **8 / 8** | 25,5 s | 14 | 51 k / 133 k / 6,9 k | `$0.30` · `$2.50` | `$0.0363` | Conforme, appels unitaires successifs. |
| **`gemini-3.8-flash`** | **8 / 8** | 92,1 s | 15 | 175 k / 20 k / 8,9 k | `$0.75` · `$3.75` | `$0.1662` | Conforme mais 11× à 18× plus coûteux que la gamme Flash-Lite pour piloter la CLI. |
| **`gemma-4-31b-it`** | 4 / 8 | 21,2 s | 3 | 10 k / 2 k / 0,6 k | `$0.00` · `$0.00` | `$0.0000` | Arrêt au 4e tour (`429 RESOURCE_EXHAUSTED`, quota d’entrée limité à 16 000 jetons/min). |
| **`gemini-3.1-pro-preview`** | 4 / 8 | > 180 s | 5 | 10 k / 0 / 0,7 k | `$2.00` · `$12.00` | `$0.0287` | Dépassement du délai de 180 s avant l’application des corrections. |

### Enseignements pour le choix du modèle

1. **Pilotage CLI et cohérence BDD (`gemini-3.1-flash-lite` ou `gemini-2.5-flash-lite`)** : les modèles Flash-Lite obtiennent le même score de conformité (`8/8`, zéro confirmation physique créée, zéro prix inventé, relecture après `409`) que `gemini-3.8-flash` pour un coût onze à dix-huit fois inférieur. `gemini-3.1-flash-lite` est cinq fois plus rapide grâce au regroupement des commandes d’application en un seul appel shell.
2. **Séparation entre lecture optique et orchestration CLI** : conserver `gemini-3.8-flash` pour la lecture unitaire des photos de cartes à la saisie ([banc de reconnaissance](BANC-RECONNAISSANCE.md)), et déléguer l’exécution des lots `pokeprice-agent` à `gemini-3.1-flash-lite` ou `gemini-2.5-flash-lite`.

