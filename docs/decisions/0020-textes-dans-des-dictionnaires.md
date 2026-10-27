# 0020 — Les textes de la vitrine vivent dans des dictionnaires JSON

> **Statut :** en vigueur · **Date :** 2026-10-27

**Contexte.** La collection est multilingue et le site vise un public
international, mais chaque texte de l'interface est écrit en français dans le
HTML et le JavaScript. L'interface n'a pas d'étape de construction : le
serveur lit les pages, y substitue `{{site_name}}` et les sert. La politique de
sécurité du contenu interdit les scripts en ligne. Les noms de cartes existent
déjà en six langues grâce au cache TCGdex.

**Options.**
1. Une copie anglaise de chaque page : rapide, mais les deux versions
   divergent dès la première modification.
2. gettext et Babel, avec des gabarits Jinja2 : outillage standard, mais tout
   le HTML est à réécrire et le JavaScript reste sans solution.
3. i18next dans le navigateur : complet, mais une dépendance de plus, à
   embarquer ou à charger d'un CDN, pour un besoin modeste.
4. La traduction automatique du navigateur : aucun travail, mais les pages
   partent chez un tiers et les noms de cartes sont mal traduits.
5. Un dictionnaire JSON par langue, lu par le serveur pour le HTML et par une
   fonction `t()` d'une trentaine de lignes pour le JavaScript ; pluriels,
   montants et dates par `Intl`.

**Décision.** Option 5, pour la vitrine d'abord, en français et en anglais.
Les textes sont dans `src/pokeprice/web/messages/<langue>.json`. Le serveur remplace
`{{t:clé}}` dans le HTML, puis glisse le dictionnaire dans la page sous forme
de bloc `<script type="application/json">`, que la politique de sécurité
laisse passer puisqu'il ne s'exécute pas. `components.js` en tire `t()`.

**Conséquences.**
- Une page s'affiche d'emblée dans sa langue, sans requête de plus ni texte
  qui change sous les yeux.
- Seule une clé qui finit par `_html` peut contenir du HTML, inséré tel quel
  par le serveur ; il échappe toutes les autres, et le JavaScript n'écrit
  jamais que du texte.
- Un pluriel est un objet indexé par les catégories d'`Intl.PluralRules`,
  avec un `zero` facultatif ; seul le JavaScript, qui connaît le nombre, s'en
  sert.
- Un test vérifie que chaque clé employée existe, qu'aucune clé n'est
  orpheline, que toutes les langues ont les mêmes clés et que le HTML de la
  vitrine ne garde aucun texte en propre.
- La langue suit un préfixe d'adresse : `/` en français, `/en/` en anglais
  britannique (`en-GB`, dates au format 27/10/2026). Pas de cookie, comme la
  mesure d'audience, et pas de redirection selon `Accept-Language`, qui
  pourra au plus suggérer une langue. Un lien partagé garde sa langue.
- L'API publique envoie des codes (finition, statut d'une demande) que la page
  nomme, et la page écrit ses propres confirmations d'envoi.
- La gestion reste en français : elle sert le vendeur et les agents. Seuls
  les composants qu'elle partage avec la vitrine passent par le dictionnaire.
- Les messages d'erreur du serveur gardent leur `detail` en français, pour
  la gestion et les clients existants. Ceux qu'un visiteur peut rencontrer
  portent en plus un `code` stable (`card_unavailable`, `wrong_credentials`…),
  tiré de la table `ERROR_CODES` de `webapp.py` ; la vitrine affiche
  `error.<code>` dans sa langue, et le `detail` quand elle ne connaît pas le
  code. Un test vérifie que chaque code a sa clé dans chaque dictionnaire, et
  que le texte français est le `detail` lui-même.
- La page À propos porte des engagements sur les données : sa version
  anglaise est une page entière, `about.en.html`, traduite du français et
  relue par le vendeur, plutôt qu'une suite de clés. Elle annonce que le texte
  français fait foi, et suit chacune de ses modifications.
