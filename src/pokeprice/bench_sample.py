"""Grow the recognition bench: harvest past confirmations, choose what to verify next.

The truth of the bench stays human: a card enters it when a person has
confirmed its variant, never because a model said so. Everything around that
label is computed here, from a base opened **read-only**:

- ``harvest`` counts the copies a person already confirmed, by language, finish
  and provenance (blind verification, or confirmation harvested afterwards);
- ``sample`` proposes the copies to verify next on the physical card, the
  under-represented strata first, in binder order.

Nothing here writes to the collection, and no photo or reading leaves the base.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# A confirmation recorded with this reason prefix is a blind verification: the
# person observed the physical card from a sheet that shows no reading.
BLIND_REASON = "Vérification à l’aveugle (banc)"
# Reasons that state the card was observed in hand; any other is undetermined.
PHYSICAL = re.compile(r"physique|en main|observation du propriétaire", re.IGNORECASE)

EVERYTHING = "ensemble"
STRATA: dict[str, str] = {
    EVERYTHING: "Toutes les cartes",
    "japonais": "Cartes japonaises",
    "hors-francais": "Autres langues que le français",
    "reverse": "Reverses",
    "holo": "Holos",
    "voisines": "Éditions voisines (même nom, autre impression)",
    "valeur": "Cartes de valeur",
}
# Before the card is observed, its finish is only a possibility drawn from the
# catalogue: these shares are used until the base holds enough verified cards.
DEFAULT_YIELD = {"reverse": 0.25, "holo": 0.5}
YIELD_MINIMUM = 10


@dataclass(frozen=True)
class Copy:
    id: str
    version: int
    name: str
    number: str
    language: str
    catalog_id: str | None
    finish: str
    foil: bool
    album_id: str
    album: str
    page: int
    position: int
    reference_cents: int | None
    confirmed: bool
    available: bool
    photo: str | None
    variants: Mapping[str, bool] = field(default_factory=dict)

    @property
    def print_key(self) -> tuple[str, str]:
        """One physical print: a second copy adds nothing to an edition measure."""
        return (self.catalog_id or f"{self.name}|{self.number}", self.language)

    @property
    def binder_key(self) -> tuple[str, str, int, int]:
        return (self.album.casefold(), self.album_id, self.page, self.position)


@dataclass(frozen=True)
class Confirmation:
    """How the variant of a copy came to be confirmed, read from the journal."""

    copy: Copy
    provenance: str  # "aveugle", "recoltee" or "automate" (never a truth label)
    method: str  # "physique" when the reason says so, else "indeterminee"
    reading_seen: bool  # a finish reading existed before the confirmation
    confirmed_at: str


@dataclass(frozen=True)
class Stratum:
    key: str
    label: str
    target: int
    verified: int
    blind: int
    candidates: int
    chosen: int
    expected: float
    missing: float


@dataclass(frozen=True)
class Sample:
    cards: list[tuple[Copy, tuple[str, ...]]]
    strata: list[Stratum]


def open_readonly(data: str | Path) -> sqlite3.Connection:
    """Open the base of a ``--data`` folder without creating or migrating it."""
    database = Path(data).resolve() / "collection.sqlite3"
    if not database.is_file():
        raise FileNotFoundError(f"Base introuvable : {database}")
    db = sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    columns = {row[1] for row in db.execute("PRAGMA table_info(copies)")}
    if not {"variant_confirmed", "finish", "deleted_at"} <= columns:
        db.close()
        raise ValueError("Base trop ancienne : la variante confirmée n’y existe pas.")
    return db


def finish_class(finish: str) -> str:
    if finish in ("holo", "holo_border"):
        return "holo"
    return "reverse" if finish == "reverse" else "autre"


def catalogue_variants(db: sqlite3.Connection) -> dict[str, dict[str, bool]]:
    """Variants each print exists in, from the latest recorded price snapshot."""
    variants: dict[str, dict[str, bool]] = {}
    for row in db.execute(
        "SELECT after_json FROM events WHERE kind='price-snapshot' ORDER BY id"
    ):
        snapshot = json.loads(row[0])
        listed = snapshot.get("variants")
        if snapshot.get("catalog_id") and isinstance(listed, dict):
            variants[snapshot["catalog_id"]] = {k: bool(v) for k, v in listed.items()}
    return variants


def load_copies(db: sqlite3.Connection) -> list[Copy]:
    variants = catalogue_variants(db)
    return [
        Copy(
            id=row["id"],
            version=row["version"],
            name=row["name"],
            number=row["number"],
            language=row["language"],
            catalog_id=row["catalog_id"],
            finish=row["finish"],
            foil=bool(row["foil"]),
            album_id=row["album_id"],
            album=row["album"],
            page=row["page"],
            position=row["position"],
            reference_cents=row["reference_cents"],
            confirmed=bool(row["variant_confirmed"]),
            available=row["stock_state"] == "available",
            photo=row["photo"],
            variants=variants.get(row["catalog_id"] or "", {}),
        )
        for row in db.execute(
            "SELECT c.*,a.name album FROM copies c JOIN albums a ON a.id=c.album_id "
            "WHERE c.deleted_at='' ORDER BY a.name,c.album_id,c.page,c.position,c.id"
        )
    ]


def automated(actor: str) -> bool:
    return actor.startswith(("agent:", "system:"))


def declared_blind(reason: str) -> bool:
    """The reason starts with the blind marker, whatever the apostrophe typed."""
    return reason.replace("'", "’").casefold().startswith(BLIND_REASON.casefold())


def confirmations(db: sqlite3.Connection, copies: Iterable[Copy]) -> list[Confirmation]:
    """The journal entry that confirmed each variant, classified by provenance."""
    confirmed = {copy.id: copy for copy in copies if copy.confirmed}
    latest: dict[str, tuple[str, str, str]] = {}
    for row in db.execute(
        "SELECT copy_id,actor,reason,before_json,after_json,created_at FROM events "
        "WHERE kind IN ('correction','acquisition') ORDER BY id"
    ):
        if row["copy_id"] not in confirmed:
            continue
        before, after = json.loads(row["before_json"]), json.loads(row["after_json"])
        if after.get("variant_confirmed") and not before.get("variant_confirmed"):
            latest[row["copy_id"]] = (row["actor"], row["reason"], row["created_at"])
    readings: dict[str, list[str]] = {}
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "verifications" in tables:
        for row in db.execute(
            "SELECT copy_id,created_at FROM verifications WHERE kind='variant'"
        ):
            readings.setdefault(row["copy_id"], []).append(row["created_at"])
    result = []
    for copy_id, copy in confirmed.items():
        actor, reason, moment = latest.get(copy_id, ("", "", ""))
        seen = any(read <= moment for read in readings.get(copy_id, [])) if moment else bool(
            readings.get(copy_id)
        )
        if not moment or automated(actor):
            provenance = "automate" if moment else "recoltee"
        elif declared_blind(reason) and not seen:
            provenance = "aveugle"
        else:
            provenance = "recoltee"
        physical = provenance == "aveugle" or bool(PHYSICAL.search(reason))
        result.append(
            Confirmation(
                copy=copy,
                provenance=provenance,
                method="physique" if physical else "indeterminee",
                reading_seen=seen,
                confirmed_at=moment,
            )
        )
    return result


def neighbour_names(copies: Iterable[Copy]) -> set[tuple[str, str]]:
    """Names that exist under several prints in the base: the edition can be mistaken."""
    prints: dict[tuple[str, str], set[str]] = {}
    for copy in copies:
        if copy.catalog_id:
            prints.setdefault((copy.name.casefold(), copy.language), set()).add(
                copy.catalog_id
            )
    return {name for name, ids in prints.items() if len(ids) > 1}


def strata_of(
    copy: Copy, neighbours: set[tuple[str, str]], value_cents: int, *, observed: bool
) -> frozenset[str]:
    """Strata of a copy: by its observed finish once verified, by catalogue signals before."""
    keys = {EVERYTHING}
    if copy.language == "ja":
        keys.add("japonais")
    elif copy.language not in ("fr", "unknown", ""):
        keys.add("hors-francais")
    if observed:
        kind = finish_class(copy.finish)
        if kind != "autre":
            keys.add(kind)
    else:
        if copy.variants.get("reverse") or (copy.foil and copy.finish in ("", "reverse")):
            keys.add("reverse")
        if copy.variants.get("holo") or copy.finish in ("holo", "holo_border"):
            keys.add("holo")
    if (copy.name.casefold(), copy.language) in neighbours:
        keys.add("voisines")
    if (copy.reference_cents or 0) >= value_cents:
        keys.add("valeur")
    return frozenset(keys)


def finish_yields(
    verified: Sequence[Copy], neighbours: set[tuple[str, str]], value_cents: int
) -> dict[str, float]:
    """Share of the cards a signal announces that turn out to have that finish."""
    yields = dict(DEFAULT_YIELD)
    for key in DEFAULT_YIELD:
        announced = [
            copy
            for copy in verified
            if key in strata_of(copy, neighbours, value_cents, observed=False)
        ]
        if len(announced) >= YIELD_MINIMUM:
            hits = sum(finish_class(copy.finish) == key for copy in announced)
            # Never zero: a signal that has not paid yet can still be explored.
            yields[key] = max(hits / len(announced), 1 / (len(announced) + 1))
    return yields


def harvest(db: sqlite3.Connection, photos: Path | None = None) -> dict[str, Any]:
    """Counts of the confirmed copies usable as bench truth. No card is named."""
    copies = load_copies(db)
    found = confirmations(db, copies)
    human = [c for c in found if c.provenance != "automate"]
    ids = {c.copy.id for c in human}

    def table(rows: Iterable[tuple[str, ...]]) -> dict[str, int]:
        return {" · ".join(key): count for key, count in sorted(Counter(rows).items())}

    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    stored: Counter[str] = Counter()
    if "verifications" in tables:
        for row in db.execute("SELECT DISTINCT copy_id,kind FROM verifications"):
            if row["copy_id"] in ids:
                stored[row["kind"]] += 1
    first = sum(
        row[0] in ids for row in db.execute("SELECT copy_id FROM sources")
    )
    result: dict[str, Any] = {
        "confirmees_par_une_personne": len(human),
        "confirmees_par_un_automate_exclues": len(found) - len(human),
        "impressions_distinctes": len({c.copy.print_key for c in human}),
        "par_langue": table((c.copy.language,) for c in human),
        "par_finition": table((finish_class(c.copy.finish),) for c in human),
        "par_provenance": table((c.provenance,) for c in human),
        "par_methode": table((c.method,) for c in human),
        "lecture_de_finition_vue_avant": sum(c.reading_seen for c in human),
        "langue_finition_provenance_methode": table(
            (c.copy.language, finish_class(c.copy.finish), c.provenance, c.method)
            for c in human
        ),
        "avec_edition_catalogue": sum(bool(c.copy.catalog_id) for c in human),
        "premiere_lecture_enregistree": first,
        "lecture_de_finition_enregistree": stored["variant"],
        "controle_d_edition_enregistre": stored["edition"],
        "photo_enregistree": sum(bool(c.copy.photo) for c in human),
    }
    if photos is not None:
        result["photo_presente_sur_disque"] = sum(
            bool(c.copy.photo) and (photos / str(c.copy.photo)).is_file() for c in human
        )
    return result


def sample(
    copies: Sequence[Copy],
    found: Sequence[Confirmation],
    *,
    count: int = 60,
    target_total: int = 200,
    target_stratum: int = 60,
    value_cents: int = 1000,
    blind_only: bool = False,
    albums: Sequence[str] = (),
) -> Sample:
    """Greedy choice: each pick is the copy that fills the most missing strata.

    A stratum that is far from its target weighs more; a copy that only might
    be a reverse counts for the share of such copies that were reverses so far.
    Ties go to a page already in the session, then to binder order.
    """
    if count < 1:
        raise ValueError("Demandez au moins une carte.")
    neighbours = neighbour_names(copies)
    truths = [c for c in found if c.provenance != "automate"]
    targets = {key: target_stratum for key in STRATA}
    targets[EVERYTHING] = target_total
    verified: Counter[str] = Counter()
    blind: Counter[str] = Counter()
    for confirmation in truths:
        keys = strata_of(confirmation.copy, neighbours, value_cents, observed=True)
        if not blind_only or confirmation.provenance == "aveugle":
            verified.update(keys)
        if confirmation.provenance == "aveugle":
            blind.update(keys)
    yields = finish_yields([c.copy for c in truths], neighbours, value_cents)
    missing = {key: float(max(0, targets[key] - verified[key])) for key in STRATA}
    wanted = {album.casefold() for album in albums}
    pool = [
        (copy, strata_of(copy, neighbours, value_cents, observed=False))
        for copy in copies
        if not copy.confirmed
        and copy.available
        and copy.photo
        and (not wanted or copy.album.casefold() in wanted or copy.album_id in albums)
    ]
    candidates = Counter(key for _, keys in pool for key in keys)
    known = {c.copy.print_key for c in truths}
    chosen: list[tuple[Copy, tuple[str, ...]]] = []
    prints: set[tuple[str, str]] = set()
    pages: set[tuple[str, int]] = set()
    picked: Counter[str] = Counter()
    expected: dict[str, float] = dict.fromkeys(STRATA, 0.0)
    while len(chosen) < count:
        best: tuple[tuple[float, bool, bool], int] | None = None
        for index, (copy, keys) in enumerate(pool):
            if copy.print_key in prints:
                continue
            score = sum(
                missing[key] / targets[key] * yields.get(key, 1.0)
                for key in keys
                if targets[key] > 0
            )
            if score <= 0:
                continue
            rank = (
                round(score, 9),
                (copy.album_id, copy.page) in pages,
                copy.print_key not in known,
            )
            if best is None or rank > best[0]:  # The pool is in binder order.
                best = (rank, index)
        if best is None:
            break
        copy, keys = pool[best[1]]
        reasons = tuple(
            key for key in STRATA if key in keys and key != EVERYTHING and missing[key] > 0
        )
        for key in keys:
            gain = yields.get(key, 1.0)
            picked[key] += 1
            expected[key] += gain
            # Rounded: five picks at one in five must add up to one card.
            missing[key] = max(0.0, round(missing[key] - gain, 9))
        prints.add(copy.print_key)
        pages.add((copy.album_id, copy.page))
        chosen.append((copy, reasons))
    chosen.sort(key=lambda item: item[0].binder_key)
    return Sample(
        cards=chosen,
        strata=[
            Stratum(
                key=key,
                label=label,
                target=targets[key],
                verified=verified[key],
                blind=blind[key],
                candidates=candidates[key],
                chosen=picked[key],
                expected=round(expected[key], 1),
                missing=round(missing[key], 1),
            )
            for key, label in STRATA.items()
        ],
    )


def as_json(result: Sample) -> dict[str, Any]:
    """For tools: copy identifiers and versions, in binder order."""
    return {
        "consigne": (
            "Vérifier chaque carte sur la carte physique, sans regarder la fiche ; "
            f"enregistrer la confirmation avec un motif qui commence par « {BLIND_REASON} »."
        ),
        "strates": [
            {
                "strate": s.key,
                "libelle": s.label,
                "cible": s.target,
                "verifiees": s.verified,
                "dont_aveugle": s.blind,
                "candidates": s.candidates,
                "proposees": s.chosen,
                "gain_attendu": s.expected,
                "manque_apres_seance": s.missing,
            }
            for s in result.strata
        ],
        "cartes": [
            {
                "id": copy.id,
                "version": copy.version,
                "album": copy.album,
                "album_id": copy.album_id,
                "page": copy.page,
                "pochette": copy.position,
                "nom": copy.name,
                "numero": copy.number,
                "langue": copy.language,
                "motifs": list(reasons),
            }
            for copy, reasons in result.cards
        ],
    }


def as_sheet(result: Sample, *, names: bool = False) -> str:
    """The sheet to fill at the binder. It shows no reading: by default not even the name."""
    lines = [
        "Séance de vérification du banc — à remplir devant la carte physique",
        "Notez ce que vous voyez sur la carte, sans ouvrir sa fiche.",
        "Finition : M mate · H holo · R reverse (lumière rasante) · ? indéterminé",
        "",
    ]
    album = None
    for copy, _ in result.cards:
        if copy.album != album:
            album = copy.album
            lines += [f"== {album} ==", ""]
        place = f"page {copy.page}, pochette {copy.position}"
        if names:
            place += f" — {copy.name} {copy.number}".rstrip()
        lines += [
            f"[ ] {place}  ({copy.id[:8]})",
            "    nom : ____________  numéro : ______  langue : ____"
            if not names
            else "    identité conforme : oui / non → ____________",
            "    finition : M / H / R / ?    tampon : oui / non",
            "",
        ]
    lines.append(f"{len(result.cards)} carte(s). Strates :")
    for s in result.strata:
        lines.append(
            f"  {s.label} : {s.verified}/{s.target} vérifiées (dont {s.blind} à l’aveugle), "
            f"{s.chosen} proposées sur {s.candidates} candidates, "
            f"manque après la séance {s.missing:g}"
        )
    return "\n".join(lines) + "\n"
