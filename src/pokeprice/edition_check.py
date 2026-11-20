"""Edition check (M2): is the photo closest to the recorded print, by image alone?

The gallery is every TCGdex print sharing the recorded edition's name, in the
card's language and in English. An image model ranks them against the front
photo; it never reads text, so it is independent of the Gemini reading that
proposed the edition. A disagreement enters « À examiner »; nothing is applied.

An edition reader is any callable ``reader(photo_bytes, references)`` where
``references`` maps a catalogue id to a local image file, returning
``(scores, raw, usage)`` with one similarity per id, plus ``source``,
``model`` and ``protocol`` attributes.
"""

import hashlib
import importlib.util
import io
import json
import re
import threading
import time
from pathlib import Path
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import Request, urlopen

from PIL import Image

from .intake import (
    LANGUAGES,
    catalogue_candidate,
    catalogue_reference,
    loose_name_key,
    number_key,
)
from .inventory import Conflict
from .tcgdex import TCGdexClient
from .verification import CheckService, check_rows, stale

API = "https://api.tcgdex.net/v2"
PROTOCOL = "edition-same-name-v1"
MAX_GALLERY = 300
# Similarity gap (cosine) below which two prints are too close to call. On the
# recognition bench: 1 false alarm in 27 true editions, and the most similar
# wrong print flagged 14 times in 26. See docs/decisions/0006-dinov2-marge.md.
MARGIN = 0.05
CARD_ID = re.compile(r"[A-Za-z0-9._%!?-]{1,120}")


def vision_installed():
    return all(importlib.util.find_spec(m) for m in ("torch", "transformers"))


def tcgdex_json(url):
    request = Request(url, headers={"User-Agent": "pokeprice/0.1.0"})
    with urlopen(request, timeout=15) as response:
        return json.loads(response.read())


def tcgdex_image(url):
    """Reference images come only from the catalogue's own asset hosts."""
    if urlsplit(url).netloc not in ("assets.tcgdex.net", "images.pokemontcg.io"):
        raise ValueError("Hôte d’image non autorisé.")
    request = Request(url, headers={"User-Agent": "pokeprice/0.1.0"})
    with urlopen(request, timeout=20) as response:
        data = response.read(8 * 1024 * 1024 + 1)
    if len(data) > 8 * 1024 * 1024:
        raise ValueError("Image de référence trop lourde.")
    with Image.open(io.BytesIO(data)) as image:
        image.verify()
    return data


def same_name_gallery(card, get_json):
    """TCGdex prints named like the recorded edition, recorded print first."""
    gallery = {}
    for language in dict.fromkeys([card["language"], "en"]):
        if language not in LANGUAGES:
            continue
        try:
            detail = get_json(f"{API}/{language}/cards/{quote(card['catalog_id'])}")
        except (OSError, ValueError):
            continue
        if not isinstance(detail, dict) or detail.get("id") != card["catalog_id"]:
            continue
        gallery.setdefault(detail["id"], reference(detail, language))
        add_prints(
            gallery,
            get_json,
            language,
            {"name": f"eq:{detail['name']}"},
            lambda name, official=detail["name"]: name == official,
        )
    return list(gallery.values())[:MAX_GALLERY]


def read_name_gallery(name, language, get_json):
    """TCGdex prints of a name as read on the card, in its language and in English.

    Names are compared without accents, case, brackets or punctuation: the
    exact search (``eq:``) misses « Fossile crâne » and « Zarbi [K] ». The
    search runs on the longest word of the name, then a local filter keeps
    the prints whose whole name matches; an omitted Delta suffix still matches.
    """
    key = loose_name_key(name)
    words = re.findall(r"\w+", TCGdexClient.clean_name(name))
    if not key or not words:
        return []
    gallery = {}
    for lang in dict.fromkeys([language, "en"]):
        if lang in LANGUAGES:
            add_prints(
                gallery,
                get_json,
                lang,
                {"name": max(words, key=len)},
                lambda official: loose_name_key(official) in (key, key + " δ"),
            )
    return list(gallery.values())[:MAX_GALLERY]


def add_prints(gallery, get_json, language, search, accept):
    """Physical prints found by a TCGdex search whose name ``accept`` keeps."""
    try:
        summaries = get_json(f"{API}/{language}/cards?" + urlencode(search))
    except (OSError, ValueError):
        summaries = []
    for item in summaries if isinstance(summaries, list) else []:
        if (
            isinstance(item, dict)
            and accept(str(item.get("name", "")))
            and CARD_ID.fullmatch(str(item.get("id", "")))
            and not digital_only(item)
        ):
            gallery.setdefault(item["id"], reference(item, language))


# TCG Pocket set ids (A1, A2b, B1, P-A…): the catalogue gives some no image.
POCKET_SET = re.compile(r"(?:[AB]\d+[a-z]?|P-[AB])-[^-]+")


def digital_only(item):
    """TCG Pocket prints (series ``tcgp``) exist only in the app, never in a binder."""
    parts = urlsplit(str(item.get("image") or "")).path.split("/")
    return (len(parts) > 2 and parts[2] == "tcgp") or bool(
        POCKET_SET.fullmatch(str(item.get("id", "")))
    )


def reference(item, language):
    image = item.get("image") or ""
    if urlsplit(image).netloc != "assets.tcgdex.net":
        image = ""
    return {
        "id": item["id"],
        "name": item.get("name", ""),
        "language": language,
        "image": image,
        "local_id": str(item.get("localId") or item["id"].rsplit("-", 1)[-1]),
    }


def image_urls(ref):
    """The same artwork in several formats and languages, then pokemontcg.io."""
    bases = []
    if ref["image"]:
        bases = [ref["image"]] + [
            re.sub(r"/(fr|en|de|it|es|pt|ja)/", f"/{lang}/", ref["image"], count=1)
            for lang in ("en", "fr")
        ]
    urls = [b + s for b in dict.fromkeys(bases) for s in ("/high.webp", "/high.png")]
    if "-" in ref["id"]:
        set_id, number = ref["id"].rsplit("-", 1)
        urls.append(
            f"https://images.pokemontcg.io/{set_id}/{number.lstrip('0') or '0'}_hires.png"
        )
    return urls


def propose_edition(card, result):
    """Agreement, disagreement or no call, against the copy's current edition."""
    scores = result.get("scores") or {}
    recorded = card.get("catalog_id")
    proposal = {"status": "unavailable", "top": None, "rank": None, "conflicts": []}
    if not recorded or recorded not in scores:
        return {
            **proposal,
            "reason": "Aucune image TCGdex de l’édition de la fiche dans ce contrôle : relancez-le après une correction d’édition.",
        }
    ranking = sorted(scores, key=lambda i: -scores[i])
    top, rank = ranking[0], ranking.index(recorded) + 1
    proposal.update(top=top, rank=rank)
    if len(ranking) == 1:
        return {
            **proposal,
            "status": "agree",
            "reason": "Seule impression de ce nom connue de TCGdex.",
        }
    if top == recorded:
        gap = scores[recorded] - scores[ranking[1]]
        return {
            **proposal,
            "status": "agree",
            "reason": f"L’édition de la fiche est la plus proche parmi {len(ranking)} impressions de même nom (écart {gap:.3f}).",
        }
    gap = scores[top] - scores[recorded]
    names = {g["id"]: g for g in result.get("gallery") or []}
    label = names.get(top, {}).get("set_name") or top
    if gap < MARGIN:
        return {
            **proposal,
            "status": "undecided",
            "reason": f"Images trop proches pour trancher : {label} ({top}) devance de peu l’édition de la fiche (écart {gap:.3f}).",
        }
    return {
        **proposal,
        "status": "disagree",
        "reason": f"L’image ressemble davantage à {label} ({top}) qu’à l’édition de la fiche, classée {rank}e (écart {gap:.3f}).",
        "conflicts": [
            f"L’image ressemble davantage à {label} ({top}) ; la fiche indique {recorded}."
        ],
    }


def edition_conflicts(db):
    """Unresolved edition disagreements per copy, for the review queue.

    Keeping the recorded edition after examination settles that reading; a
    newer reading that still disagrees raises it again.
    """
    kept = {
        json.loads(row[0]).get("verification_id")
        for row in db.execute(
            "SELECT after_json FROM events WHERE kind='edition-validation'"
        )
    }
    result = {}
    for row in db.execute(
        "SELECT v.id,v.copy_id,v.photos_json,v.result_json,c.photo,c.catalog_id "
        "FROM verifications v JOIN copies c ON c.id=v.copy_id WHERE v.kind='edition' "
        "AND v.rowid IN (SELECT max(rowid) FROM verifications WHERE kind='edition' GROUP BY copy_id)"
    ):
        card = dict(row)
        if row["id"] in kept or stale(row, card):
            continue
        conflicts = propose_edition(card, json.loads(row["result_json"]))["conflicts"]
        if conflicts:
            result[row["copy_id"]] = conflicts
    return result


class Dinov2EditionReader:
    """DINOv2 image embeddings, cosine similarity; reference vectors are cached."""

    source, model, protocol = "dinov2", "facebook/dinov2-small", PROTOCOL
    _loaded: dict = {}
    _load_lock = threading.Lock()

    def __init__(self, cache):
        self.cache_file = Path(cache) / "dinov2-small.pt"
        self.vectors = None
        self.lock = threading.Lock()

    def load(self):
        import torch
        from transformers import AutoImageProcessor, AutoModel

        with self._load_lock:
            if self.model not in self._loaded:
                device = "cuda" if torch.cuda.is_available() else "cpu"
                model = AutoModel.from_pretrained(self.model).to(device).eval()
                processor = AutoImageProcessor.from_pretrained(self.model)
                self._loaded[self.model] = (model, processor, device)
        return self._loaded[self.model]

    def embed(self, images):
        import torch

        model, processor, device = self.load()
        with torch.no_grad():
            vectors = []
            for start in range(0, len(images), 16):
                inputs = processor(
                    images=images[start : start + 16], return_tensors="pt"
                ).to(device)
                vectors.append(model(**inputs).last_hidden_state[:, 0].cpu())
        return torch.nn.functional.normalize(torch.cat(vectors), dim=-1)

    def __call__(self, photo, references):
        import torch

        started = time.monotonic()
        with self.lock:
            if self.vectors is None:
                self.vectors = (
                    torch.load(self.cache_file, weights_only=True)
                    if self.cache_file.exists()
                    else {}
                )
            keys = {
                ref_id: hashlib.sha256(path.read_bytes()).hexdigest()
                for ref_id, path in references.items()
            }
            missing = [r for r, key in keys.items() if key not in self.vectors]
            if missing:
                for ref_id, vector in zip(
                    missing,
                    self.embed([rgb(references[r].read_bytes()) for r in missing]),
                    strict=True,
                ):
                    self.vectors[keys[ref_id]] = vector
                self.cache_file.parent.mkdir(parents=True, exist_ok=True)
                temporary = self.cache_file.with_suffix(".tmp")
                torch.save(self.vectors, temporary)
                temporary.replace(self.cache_file)
            query = self.embed([rgb(photo)])[0]
            scores = {
                ref_id: round(float(query @ self.vectors[key]), 5)
                for ref_id, key in keys.items()
            }
        _, _, device = self.load()
        usage = {
            "seconds": round(time.monotonic() - started, 2),
            "device": device,
            "new_references": len(missing),
        }
        return scores, "", usage


def rgb(data):
    """Transparent catalogue scans on white, like a printed card."""
    with Image.open(io.BytesIO(data)) as image:
        if image.mode in ("RGBA", "LA", "P"):
            image = image.convert("RGBA")
            background = Image.new("RGBA", image.size, "white")
            return Image.alpha_composite(background, image).convert("RGB")
        return image.convert("RGB")


class EditionCheckService(CheckService):
    kind = "edition"
    card_fields = ("catalog_id", "language", "name", "number", "identification_status")
    labels = {
        "manual": "Contrôle de l’édition par l’image demandé explicitement ; fiche inchangée",
        "intake": "Contrôle de l’édition par l’image lancé automatiquement à la saisie ; fiche inchangée",
        "agent": "Contrôle de l’édition par l’image lancé par l’agent de revue ; fiche inchangée",
        "failed": "Contrôle automatique de l’édition impossible ; demandez-le depuis la fiche",
    }

    def __init__(
        self, store, reader=None, get_json=None, fetch=None, references=None
    ):
        self.references = Path(references or store.root / "references")
        if reader is None and vision_installed():
            reader = Dinov2EditionReader(self.references)
        super().__init__(store, reader)
        self.get_json, self.fetch = get_json or tcgdex_json, fetch or tcgdex_image

    @property
    def available(self):
        return self.reader is not None

    def ready(self, card):
        return bool(card["catalog_id"]) and card["identification_status"] == "confirmed"

    def image(self, ref):
        """A cached catalogue image, downloaded once; None when no source has it."""
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", ref["id"])
        path = self.references / f"{safe}.img"
        if path.exists():
            return path
        for url in image_urls(ref):
            try:
                data = self.fetch(url)
            except (OSError, ValueError):
                continue
            self.references.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".tmp")
            temporary.write_bytes(data)
            temporary.replace(path)
            return path
        return None

    def evaluate(self, copy_id, version, actor, trigger="manual"):
        if not self.available:
            raise RuntimeError(
                "Contrôle d’édition indisponible : installez l’option vision (uv sync --extra vision)."
            )

        def read(card, photo):
            if not self.ready(card):
                raise ValueError("Confirmez d’abord une édition du catalogue.")
            gallery = same_name_gallery(card, self.get_json)
            paths = {ref["id"]: self.image(ref) for ref in gallery}
            references = {i: p for i, p in paths.items() if p}
            if card["catalog_id"] not in references:
                raise RuntimeError(
                    "Image TCGdex de l’édition de la fiche introuvable : contrôle impossible."
                )
            scores, raw, usage = self.reader(photo, references)
            ranking = sorted(scores, key=lambda i: -scores[i])
            for ref in gallery:  # The leading prints are named, for the human.
                if ref["id"] in ranking[:3] or ref["id"] == card["catalog_id"]:
                    ref["set_name"] = self.set_name(ref)
            result = {
                "scores": scores,
                "gallery": [g for g in gallery if g["id"] in scores],
                "missing_images": sorted(i for i, p in paths.items() if not p),
            }
            return result, propose_edition(card, result), raw, usage

        return self.run(copy_id, version, actor, read, trigger)

    def set_name(self, ref):
        try:
            detail = self.get_json(f"{API}/{ref['language']}/cards/{quote(ref['id'])}")
        except (OSError, ValueError):
            return ""
        if not isinstance(detail, dict):
            return ""
        number = detail.get("localId", "")
        return " ".join(p for p in ((detail.get("set") or {}).get("name"), str(number)) if p)

    def evaluate_new_copy(self, copy_id, actor):
        return super().evaluate_new_copy(
            copy_id,
            actor,
            lambda card: self.evaluate(copy_id, card["version"], actor, "intake"),
        )

    def keep(self, copy_id, check_id, version, actor, reason):
        """The human keeps the recorded edition after examining the card."""
        with self.store.connect(write=True) as db:
            card = self.store.get(db, copy_id)
            if card["version"] != version:
                raise Conflict("La fiche a changé. Rechargez-la avant de valider.")
            row = next(
                (r for r in check_rows(db, card, self.kind) if r["id"] == check_id),
                None,
            )
            if not row:
                raise KeyError("Contrôle introuvable pour cet exemplaire.")
            if row["stale"]:
                raise Conflict(
                    "La photo du recto a changé depuis ce contrôle. Demandez-en un nouveau."
                )
            self.store.event(
                db,
                copy_id,
                actor,
                "edition-validation",
                reason,
                {},
                {
                    "verification_id": check_id,
                    "catalog_id": card["catalog_id"],
                    "proposal": propose_edition(card, row["result"]),
                    "photos": row["photos"],
                },
            )
            return self.store.get(db, copy_id)


# --- Edition proposed by the image at intake (M2, slice 5) --------------------

IMAGE_PROTOCOL = "edition-read-name-v1"
SETS_TTL = 7 * 86400


def set_id(catalog_id):
    return catalog_id.rsplit("-", 1)[0]


def number_parts(number):
    """(numerator, set size) of a number read, each possibly empty."""
    parts = number_key(number or "").split("/")
    total = parts[1] if len(parts) > 1 and parts[1].isdigit() else ""
    return parts[0], total


def number_filter(number, prints):
    """Prints whose number, or whose set size, matches the number read.

    A misread number still narrows the gallery: « 68/97 » keeps the set of 97
    cards, « 4/ » the prints numbered 4. Without any number read, nothing is
    filtered. Each print carries ``local_id`` and ``count`` (official set size).
    Returns ``(kept, discarded)``.
    """
    numerator, total = number_parts(number)
    if not numerator and not total:
        return list(prints), []
    kept, discarded = [], []
    for ref in prints:
        same_number = numerator and number_key(ref["local_id"]) == numerator
        same_set = total and str(ref.get("count") or "") == total
        (kept if same_number or same_set else discarded).append(ref)
    return kept, discarded


def image_proposal(kept, scores, filtered):
    """The leading print if the image separates it by MARGIN, else no proposal.

    ``filtered`` says a number narrowed the gallery. Then a kept print without
    image blocks the proposal: the true one may be the print the image cannot
    see. Without any number read, the proposal stands and names the prints
    without image, for the person who confirms.
    """
    missing = sorted(ref["id"] for ref in kept if ref["id"] not in scores)
    proposal = {
        "status": "none",
        "top": None,
        "gap": None,
        "kept": len(kept),
        "filtered": filtered,
        "missing_images": missing,
    }
    unseen = (
        f" Sans image TCGdex, donc non comparées : {', '.join(missing)}."
        if missing
        else ""
    )
    if not kept:
        return {
            **proposal,
            "reason": "Aucune impression de ce nom ne porte ce numéro ni ce nombre de cartes.",
        }
    if (missing and filtered) or not scores:
        return {
            **proposal,
            "reason": "Pas de proposition par l’image : la vraie impression peut être l’une de celles qui n’ont pas d’image."
            + unseen,
        }
    ranking = sorted(scores, key=lambda i: -scores[i])
    top = ranking[0]
    gap = scores[top] - scores[ranking[1]] if len(ranking) > 1 else None
    proposal.update(top=top, gap=None if gap is None else round(gap, 5))
    if gap is not None and gap < MARGIN:
        return {
            **proposal,
            "status": "undecided",
            "reason": f"Images trop proches pour proposer une édition parmi {len(ranking)} impressions (écart {gap:.3f})."
            + unseen,
        }
    label = next((r.get("set_name") for r in kept if r["id"] == top), "") or top
    among = (
        "seule impression de ce nom retenue par le numéro"
        if gap is None
        else f"la plus proche parmi {len(ranking)} impressions (écart {gap:.3f})"
    )
    return {
        **proposal,
        "status": "proposed",
        "reason": f"Proposée par l’image : {label} ({top}), {among}. Comparez avec la carte avant de confirmer."
        + unseen,
    }


class SetCounts:
    """Official card count of each TCGdex set, from ``/sets``, cached a week."""

    def __init__(self, get_json, folder):
        self.get_json, self.folder = get_json, Path(folder)
        self.memory = {}
        self.lock = threading.Lock()

    def __call__(self, language):
        with self.lock:
            cached = self.memory.get(language)
            if cached and cached[0] > time.time() - SETS_TTL:
                return cached[1]
            path = self.folder / f"sets-{language}.json"
            try:
                stored = json.loads(path.read_text())
                if stored["at"] > time.time() - SETS_TTL:
                    self.memory[language] = (stored["at"], stored["counts"])
                    return stored["counts"]
            except (OSError, ValueError, KeyError, TypeError):
                pass
            try:
                sets = self.get_json(f"{API}/{language}/sets")
            except (OSError, ValueError):
                return {}
            counts = {
                str(item["id"]): (item.get("cardCount") or {}).get("official")
                for item in (sets if isinstance(sets, list) else [])
                if isinstance(item, dict) and item.get("id")
            }
            now = time.time()
            self.memory[language] = (now, counts)
            self.folder.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".tmp")
            temporary.write_text(json.dumps({"at": now, "counts": counts}))
            temporary.replace(path)
            return counts


class EditionSuggester:
    """When the catalogue finds nothing, the image proposes an edition.

    The gallery is every print of the name read (``read_name_gallery``),
    narrowed by the number even misread (``number_filter``); DINOv2 ranks the
    photo against what remains (``image_proposal``). A person always confirms.
    """

    def __init__(self, checks):
        self.checks = checks
        self.sets = SetCounts(checks.get_json, checks.references)

    def gallery(self, query):
        """The name's prints, each with its set size, and the filter applied."""
        prints = read_name_gallery(query["name"], query["language"], self.checks.get_json)
        counts = {}
        for language in dict.fromkeys(["en", query["language"]]):
            counts.update({k: v for k, v in self.sets(language).items() if v})
        for ref in prints:
            ref["count"] = counts.get(set_id(ref["id"]))
        kept, _ = number_filter(query.get("number", ""), prints)
        return prints, kept, any(number_parts(query.get("number", "")))

    def evaluate(self, photo, query):
        """Everything the bench records: prints, filter, scores and proposal."""
        prints, kept, filtered = self.gallery(query)
        paths = {ref["id"]: self.checks.image(ref) for ref in kept}
        references = {i: p for i, p in paths.items() if p}
        scores = self.checks.reader(photo, references)[0] if references else {}
        for ref in kept:  # The leading print is named, for the human.
            if scores and ref["id"] == max(scores, key=scores.get):
                ref["set_name"] = self.checks.set_name(ref)
        return {
            "prints": prints,
            "kept": [ref["id"] for ref in kept],
            "scores": scores,
            "proposal": image_proposal(kept, scores, filtered),
        }

    def candidate(self, top, query):
        """The proposed print as a catalogue choice, in the card's language."""
        for language in dict.fromkeys([query["language"], "en"]):
            try:
                detail = self.checks.get_json(f"{API}/{language}/cards/{quote(top)}")
            except (OSError, ValueError):
                continue
            if isinstance(detail, dict) and detail.get("id") == top and detail.get("name"):
                # The copy keeps the language read; the catalogue id is shared.
                return catalogue_candidate(
                    detail,
                    query["language"],
                    printed_name=detail["name"],
                    printed_number=catalogue_reference(detail),
                )
        return None

    def __call__(self, photo, query):
        """Fields merged into the catalogue answer; never raises."""
        if query.get("language") not in LANGUAGES:
            return {}
        try:
            found = self.evaluate(photo, query)
            proposal = found["proposal"]
            candidate = (
                self.candidate(proposal["top"], query)
                if proposal["status"] == "proposed"
                else None
            )
        except Exception:  # noqa: BLE001 - The proposal is a help; intake goes on without it.
            return {
                "image_proposal": {
                    "status": "none",
                    "reason": "Proposition par l’image indisponible.",
                }
            }
        summary = {
            k: proposal[k]
            for k in ("status", "top", "gap", "kept", "filtered", "missing_images", "reason")
        }
        summary["protocol"] = IMAGE_PROTOCOL
        if not candidate:
            return {"image_proposal": summary}
        candidate.update(proposed_by="image", similarity_gap=proposal["gap"])
        return {
            "candidates": [candidate],
            "image_proposal": summary,
            "message": "Le catalogue ne trouve pas ce numéro. "
            + proposal["reason"],
        }
