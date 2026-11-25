# 0053 — Une illustration holo vue de face ne se confirme que si le catalogue exclut la version mate

> **Statut :** en vigueur, complète la décision [0047](0047-import-de-classeur-sur-le-serveur.md) · **Date :** 2026-11-25

**Contexte.** Sur les 35 variantes que l'agent de revue confirmerait dans la
première vérification à l'aveugle, une est fausse : Magirêve, lue holo sur la
photo de page, est mate. Son illustration porte un dégradé imprimé qui imite le
holo, et le catalogue connaît pour elle une impression mate et une impression
holo distincte. La porte de la décision [0051](0051-porte-sur-les-erreurs-graves.md)
n'admet aucune variante fausse. Le second échantillon (26 variantes justes sur
26) ne contenait aucune carte holo, reverse ou trompeuse : il ne dit rien des
cas difficiles.

**Options.**
1. **Ne rien changer** : chaque dégradé imprimé peut devenir une holo
   confirmée, et la porte reste fermée.
2. **Demander une prise au reflet pour toute illustration lue holo** : sûr, mais
   une photo de plus aussi pour les holos d'origine, qui n'existent qu'en holo.
3. **Ne croire la photo de face que si le catalogue exclut la version mate**,
   et demander une prise au reflet sinon.

**Décision.** Option 3. Une illustration lue holo sur une photo à plat n'est
proposée que si le catalogue dit que l'édition n'a pas d'impression mate. Si
le catalogue connaît une version mate, ou ne dit rien, la lecture reste à
examiner et l'agent demande une prise au reflet. Sur une prise au reflet de
qualité suffisante, un corps mat propose la Standard ; une illustration qui
brille propose la holo quand le catalogue désigne l'impression (holo parallèle,
tampon d'extension), et laisse sinon la carte à examiner.

**Conséquences.**
- Les holos d'origine (sans impression mate au catalogue) se confirment
  toujours d'une seule photo.
- Les holos parallèles, les tampons d'extension et les éditions mal décrites
  par le catalogue demandent une prise au reflet.
- Une prise au reflet de qualité limitée ne tranche rien : l'agent demande un
  recto net, puis ne redemande pas le reflet, et la carte reste à une personne.
- La règle se mesure sur une fiche à l'aveugle ciblée : holos, reverses et
  cartes au fond trompeur, sans limite de prix.

**Preuve.** `tests/test_verification.py` (holo de face selon le catalogue),
`tests/test_agent_review.py` (demande de reflet, puis holo ou Standard).
