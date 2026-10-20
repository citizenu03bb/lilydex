"""Basic Energy gate: recognise a basic Energy by image alone, before any Gemini call.

The bank is the collection itself: copies named as basic Energies are the
references, every other copy is a counter-example (special Energies such as
Double Énergie Incolore share the basic frame). A pocket is gated only when its
nearest basic Energy beats its nearest other card by MARGIN; anything closer is
read by Gemini as before. The type is a proposal, never a confirmed value.
"""

import json
import re
import unicodedata
from collections import Counter

from .ocr import CardOCRResult

PROTOCOL = "energy-gate-v1"
# On six binders (1,305 pockets, DINOv2 small): 162/164 basic Energies gated and
# no other card, while a margin of 0.08 still let a Double Énergie Incolore
# through. Leave-one-out protocol and results: scripts/eval_energy_gate.py and
# docs/BANC-RECONNAISSANCE.md.
MARGIN = 0.10
MIN_REFERENCES = 20
TYPES = {
    "feu": "Feu", "fire": "Feu", "eau": "Eau", "water": "Eau",
    "plante": "Plante", "grass": "Plante", "electrique": "Électrique",
    "lightning": "Électrique", "psy": "Psy", "psychic": "Psy",
    "combat": "Combat", "fighting": "Combat", "obscurite": "Obscurité",
    "darkness": "Obscurité", "metal": "Métal", "fee": "Fée", "fairy": "Fée",
}  # fmt: skip


def plain(text):
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", text).strip().lower()


def basic_energy(name):
    """(True, type or "") for a basic Energy name in French or English."""
    text = plain(name)
    if text in ("energy", "energie", "energie de base"):
        return True, ""
    match = re.fullmatch(r"energie (\w+)", text) or re.fullmatch(r"(\w+) energy", text)
    if match and match.group(1) in TYPES:
        return True, TYPES[match.group(1)]
    return False, ""


class EnergyGate:
    """``embed(images) -> normalised vectors``; bank rows are (vector, basic, type)."""

    def __init__(self, embed, vectors, basic, types, margin=MARGIN):
        self.embed, self.vectors, self.margin = embed, vectors, margin
        self.basic, self.types = list(basic), list(types)
        self.ready = sum(self.basic) >= MIN_REFERENCES and not all(self.basic)

    def check(self, image):
        """Evidence dict when the pocket is a basic Energy, else None."""
        if not self.ready:
            return None
        scores = (self.vectors @ self.embed([image.convert("RGB")])[0]).tolist()
        ranked = sorted(range(len(scores)), key=lambda i: -scores[i])
        best_basic = next(i for i in ranked if self.basic[i])
        best_other = next(i for i in ranked if not self.basic[i])
        gap = scores[best_basic] - scores[best_other]
        if gap < self.margin:
            return None
        typed = [i for i in ranked if self.basic[i] and self.types[i]][:5]
        votes = Counter(self.types[i] for i in typed)
        proposal, count = votes.most_common(1)[0] if votes else ("", 0)
        return {
            "protocol": PROTOCOL,
            "margin": self.margin,
            "gap": round(gap, 4),
            "basic_score": round(scores[best_basic], 4),
            "other_score": round(scores[best_other], 4),
            "type_proposal": proposal if count >= 3 else "",
            "type_votes": dict(votes),
        }


def gated_result(evidence):
    """The pocket's reading, without Gemini: a basic Energy whose type stays to confirm."""
    return CardOCRResult(
        "Énergie de base",
        0,
        "",
        False,
        json.dumps(evidence, ensure_ascii=False),
        occupied=True,
    )


def gated_note(evidence):
    proposal = evidence["type_proposal"]
    return (
        "Énergie de base reconnue par l’image (DINOv2, écart "
        + f"{evidence['gap']:.2f}".replace(".", ",")
        + "), "
        "sans lecture Gemini ; type "
        + (f"proposé : {proposal}, à confirmer." if proposal else "à préciser.")
    )


def from_store(store, reader=None):
    """Gate built from the collection's current copies, vectors cached by photo."""
    import torch
    from PIL import Image

    from .edition_check import Dinov2EditionReader

    reader = reader or Dinov2EditionReader(store.root / "references")
    cache_file = store.root / "references" / "energy-bank.pt"
    cache = torch.load(cache_file, weights_only=True) if cache_file.exists() else {}
    with store.connect() as db:
        rows = db.execute(
            "SELECT name,photo FROM copies WHERE deleted_at='' AND photo IS NOT NULL"
        ).fetchall()
    rows = [r for r in rows if (store.photos / r["photo"]).is_file()]
    missing = [r["photo"] for r in rows if r["photo"] not in cache]
    for start in range(0, len(missing), 64):
        batch = missing[start : start + 64]
        images = []
        for name in batch:
            with Image.open(store.photos / name) as image:
                images.append(image.convert("RGB"))
        for name, vector in zip(batch, reader.embed(images), strict=True):
            cache[name] = vector
    if missing:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        temporary = cache_file.with_suffix(".tmp")
        torch.save(cache, temporary)
        temporary.replace(cache_file)
    labels = [basic_energy(r["name"]) for r in rows]
    vectors = (
        torch.stack([cache[r["photo"]] for r in rows]) if rows else torch.empty(0, 384)
    )
    return EnergyGate(
        reader.embed, vectors, [b for b, _ in labels], [t for _, t in labels]
    )
