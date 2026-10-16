"""Check recorded identities against copy photos, without Gemini.

An identity read on a photo depends on its crop: after a recrop or a new photo,
name, number and HP must be checked again. Three local means, combined:

- ``sheets`` / ``strips``: contact sheets for a visual review (whole card with a
  zoom on the number, or name/HP band + number band), labelled with the
  recorded identity;
- ``lookup``: names of a catalogue id from the TCGdex set lists already cached
  in ``catalog_lookups`` (no network): a number read on the photo must give the
  name read on the photo;
- ``score``: DINOv2 similarity of the photo with the recorded print, its rank in
  the local reference gallery, a 180° check and a blue-back measure.

Then ``propose`` turns reviewed decisions into Store.patch proposals and
``apply`` replays them, on a temporary copy by default. With ``--apply`` a
backup is made first. See docs/AUDIT-PHOTOS.md.

    uv run --extra web python scripts/audit_photo_identity.py sheets copies.csv out/ --level grave
    uv run --extra web python scripts/audit_photo_identity.py lookup pl3-97 dp5-57
    uv run --extra web --extra vision python scripts/audit_photo_identity.py score copies.csv scores.json
    uv run --extra web python scripts/audit_photo_identity.py propose decisions.csv proposals.json
    uv run --extra web python scripts/audit_photo_identity.py apply proposals.json [--apply]
"""

import argparse
import csv
import io
import json
import re
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FIELDS = ("name", "set_name", "number", "language", "catalog_id", "hp",
          "identification_status", "reference_cents", "version", "photo",
          "album_id", "page", "position", "notes")


def readonly(data):
    db = sqlite3.connect(f"file:{Path(data) / 'collection.sqlite3'}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    return db


def load_copies(data, path, levels=()):
    """Copies listed in a CSV/JSON (column copy_id or id, optional level/niveau), current DB values."""
    path = Path(path)
    rows = json.loads(path.read_text()) if path.suffix == ".json" else list(csv.DictReader(open(path)))
    db = readonly(data)
    out = []
    for r in rows:
        lvl = r.get("level") or r.get("niveau") or ""
        if levels and lvl not in levels:
            continue
        cid = r.get("copy_id") or r.get("id")
        c = db.execute(
            "SELECT c.*, a.name AS album FROM copies c JOIN albums a ON a.id=c.album_id "
            "WHERE c.id=? AND c.deleted_at=''", (cid,)
        ).fetchone()
        if c:
            out.append(dict({k: c[k] for k in FIELDS}, copy_id=cid, album=c["album"], level=lvl))
    return out


def font(size):
    for name in ("DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default()


def label(c, i):
    return (f"#{i} {c['album'][:10]} p{c['page']}#{c['position']} {c['identification_status'][:5]}",
            f"{c['name'][:18]} {c['number']} PV{c['hp']}")


def sheets(copies, photos, out, cols=4, rows=2, w=330, h=470, zoom=110):
    """Whole card resized, then a zoom on the lower right (number, set symbol)."""
    out.mkdir(parents=True, exist_ok=True)
    f = font(17)
    made = []
    for s in range(0, len(copies), cols * rows):
        sheet = Image.new("RGB", (cols * (w + 8), rows * (h + zoom + 56)), "white")
        draw = ImageDraw.Draw(sheet)
        for k, c in enumerate(copies[s:s + cols * rows]):
            with Image.open(photos / c["photo"]) as im:
                im = im.convert("RGB")
            pw, ph = im.size
            x, y = (k % cols) * (w + 8), (k // cols) * (h + zoom + 56)
            sheet.paste(im.resize((w, h)), (x, y))
            sheet.paste(im.crop((int(pw * .40), int(ph * .80), int(pw * .95), int(ph * .93))).resize((w, zoom)), (x, y + h))
            top, bottom = label(c, s + k)
            draw.text((x + 2, y + h + zoom + 2), top, fill="black", font=f)
            draw.text((x + 2, y + h + zoom + 24), bottom, fill="blue", font=f)
        path = out / f"sheet_{s // (cols * rows):03d}.jpg"
        sheet.save(path, quality=88)
        made.append(path)
    return made


def strips(copies, photos, out, cols=2, rows=6, w=640):
    """Name/HP band and number band only: a fast check of many copies."""
    out.mkdir(parents=True, exist_ok=True)
    f = font(17)
    made = []
    for s in range(0, len(copies), cols * rows):
        tiles = []
        for k, c in enumerate(copies[s:s + cols * rows]):
            with Image.open(photos / c["photo"]) as im:
                im = im.convert("RGB")
            pw, ph = im.size
            a = im.crop((0, int(ph * .055), pw, int(ph * .17)))
            b = im.crop((0, int(ph * .80), pw, int(ph * .925)))
            a, b = (x.resize((w, int(w * x.size[1] / pw))) for x in (a, b))
            tile = Image.new("RGB", (w, a.size[1] + b.size[1] + 24), "white")
            tile.paste(a, (0, 0))
            tile.paste(b, (0, a.size[1]))
            ImageDraw.Draw(tile).text((2, tile.size[1] - 22), " | ".join(label(c, s + k)), fill="blue", font=f)
            tiles.append(tile)
        th = max(t.size[1] for t in tiles)
        sheet = Image.new("RGB", (cols * (w + 10), rows * (th + 8)), "white")
        for k, t in enumerate(tiles):
            sheet.paste(t, ((k % cols) * (w + 10), (k // cols) * (th + 8)))
        path = out / f"strips_{s // (cols * rows):03d}.jpg"
        sheet.save(path, quality=88)
        made.append(path)
    return made


def lookup(db, catalog_id, languages=("fr", "en")):
    """Name of a catalogue id per language, from the cached set lists; None when the set is unknown."""
    set_id = catalog_id.rsplit("-", 1)[0]
    names = {}
    for language in languages:
        row = db.execute("SELECT value FROM catalog_lookups WHERE key=? AND found=1",
                         (f"set:{language}:{set_id}",)).fetchone()
        names[language] = json.loads(row[0]).get(catalog_id, "") if row else None
    return names


def detail(cache, catalog_id, language, get_json=None):
    """TCGdex card detail, cached as JSON next to the app's reference images."""
    path = Path(cache) / f"{catalog_id}.{language}.json"
    if path.exists():
        return json.loads(path.read_text())
    from pokeprice.edition_check import API, tcgdex_json

    try:
        value = (get_json or tcgdex_json)(f"{API}/{language}/cards/{catalog_id}")
    except (OSError, ValueError):
        return None
    if not isinstance(value, dict) or value.get("id") != catalog_id:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False))
    return value


def blue_back(image):
    """Share of saturated blue in the card centre: a visible back scores high."""
    hsv = image.convert("RGB").resize((90, 126)).convert("HSV").crop((15, 20, 75, 106))
    pixels = list(hsv.getdata())
    return sum(1 for h, s, v in pixels if 140 < h < 180 and s > 90 and v > 60) / len(pixels)


def score(copies, photos, cache, store=None, extra=()):
    """DINOv2 of each photo against the local reference gallery (recorded and extra ids fetched)."""
    from pokeprice.edition_check import (
        Dinov2EditionReader, EditionCheckService, reference, tcgdex_image)

    cache = Path(cache)
    # Only the app's image cache is used: no store, nothing recorded.
    service = EditionCheckService.__new__(EditionCheckService)
    service.references, service.fetch = cache, tcgdex_image
    wanted = {(c["catalog_id"], c["language"] if c["language"] in ("fr", "en") else "fr")
              for c in copies if c["catalog_id"]} | {(cid, "fr") for cid in extra}
    for cid, language in sorted(wanted):
        d = detail(cache, cid, language) or detail(cache, cid, "en")
        service.image(reference(d, language) if d else {"id": cid, "image": ""})
    gallery = {p.stem: p for p in cache.glob("*.img")}
    reader = Dinov2EditionReader(cache)
    out = []
    for c in copies:
        with Image.open(photos / c["photo"]) as im:
            im = im.convert("RGB")
        buf, rot = io.BytesIO(), io.BytesIO()
        im.save(buf, "JPEG", quality=95)
        im.rotate(180).save(rot, "JPEG", quality=95)
        scores, _, _ = reader(buf.getvalue(), gallery)
        turned, _, _ = reader(rot.getvalue(), gallery)
        order = sorted(scores, key=scores.get, reverse=True)
        cid = c["catalog_id"]
        out.append({
            "copy_id": c["copy_id"], "catalog_id": cid, "gallery": len(gallery),
            "recorded_score": scores.get(cid), "recorded_rank": order.index(cid) + 1 if cid in scores else None,
            "top": [(t, scores[t]) for t in order[:5]],
            "upside_down": bool(cid in turned and turned[cid] > scores[cid] + 0.05),
            "blue_back": round(blue_back(im), 3),
        })
    return out


def propose(decisions, data, cache, get_json=None):
    """Store.patch proposals from reviewed decisions.

    A decision gives copy_id plus either catalog_id (identity read on the photo
    and found in the catalogue) or name (+ language) alone, and the observation.
    The status becomes « review » (À vérifier): only the owner confirms.
    """
    db = readonly(data)
    setnames = {}
    for cid, set_name, language in db.execute(
        "SELECT catalog_id, set_name, language FROM copies WHERE catalog_id IS NOT NULL AND deleted_at=''"
    ):
        setnames.setdefault((cid.rsplit("-", 1)[0], language), set_name)
    out = []
    for d in decisions:
        c = db.execute("SELECT * FROM copies WHERE id=?", (d["copy_id"],)).fetchone()
        language = d.get("language") or "fr"
        if d.get("catalog_id"):
            card = detail(cache, d["catalog_id"], language, get_json) or detail(cache, d["catalog_id"], "fr", get_json)
            if card is None:
                raise ValueError(f"{d['catalog_id']} absent du catalogue")
            sid = d["catalog_id"].rsplit("-", 1)[0]
            target = {
                "name": d.get("name") or card["name"],
                "number": f"{card['localId']}/{card['set']['cardCount']['official']}",
                "catalog_id": d["catalog_id"], "hp": card.get("hp"),
                "set_name": setnames.get((sid, language)) or setnames.get((sid, "fr")) or card["set"]["name"],
                "language": language, "identification_status": "review",
            }
            what = f"{target['name']} {target['number']}" + (f", PV {target['hp']}" if target["hp"] else "")
            source = f"référence trouvée dans le catalogue TCGdex local ({d['catalog_id']})"
        else:
            target = {"name": d["name"], "language": language}
            what = f"une carte « {d['name']} » (langue {language}) sans numéro lisible"
            source = "identité toujours à identifier"
        changes = {k: v for k, v in target.items() if c[k] != v}
        if not changes:
            continue
        reason = (f"Audit des photos redécoupées : la nouvelle photo montre {what}. "
                  f"Lecture visuelle par Claude, {source}. "
                  + (f"{d['note']}. " if d.get("note") else "")
                  + "À vérifier par le propriétaire.")
        out.append({"copy_id": d["copy_id"], "version": c["version"], "changes": changes,
                    "before": {k: c[k] for k in target} | {"reference_cents": c["reference_cents"]},
                    "observation": d.get("observation", ""), "reason": reason})
    return out


def apply(patches, data, actor="claude", write=False, backup_dir=None):
    """Replay patches with their expected version; on a temporary copy unless write."""
    from pokeprice.inventory import Conflict, Store

    if write:
        from pokeprice.inventory_backup import backup

        store = Store(data)
        target = Path(backup_dir or store.root.parent / "backups") / (
            "collection-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + ".zip")
        backup(store, target)
        print("sauvegarde", target)
    else:
        tmp = Path(tempfile.mkdtemp(prefix="pokeprice-dry-")) / "inventory"
        tmp.mkdir()
        source = sqlite3.connect(f"file:{Path(data) / 'collection.sqlite3'}?mode=ro", uri=True)
        copy = sqlite3.connect(tmp / "collection.sqlite3")
        source.backup(copy)
        copy.close()
        source.close()
        store = Store(tmp)
    done, skipped = [], []
    for p in patches:
        try:
            after = store.patch(p["copy_id"], p["changes"], p["version"], actor, p["reason"])
        except (Conflict, ValueError) as error:
            skipped.append((p["copy_id"], str(error)))
            continue
        drift = {k: after[k] for k, v in p["changes"].items() if after[k] != v}
        done.append((p["copy_id"], after["version"], drift))
    return store, done, skipped


def read_decisions(path):
    path = Path(path)
    rows = json.loads(path.read_text()) if path.suffix == ".json" else list(csv.DictReader(open(path)))
    return [{k: v for k, v in r.items() if v not in ("", None)} for r in rows]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--data", default="data/inventory")
    parser.add_argument("--cache", help="références TCGdex (défaut : <data>/references)")
    actions = parser.add_subparsers(dest="action", required=True)
    for name in ("sheets", "strips"):
        a = actions.add_parser(name)
        a.add_argument("copies")
        a.add_argument("output")
        a.add_argument("--level", action="append", default=[])
    a = actions.add_parser("lookup")
    a.add_argument("ids", nargs="+")
    a = actions.add_parser("score")
    a.add_argument("copies")
    a.add_argument("output")
    a.add_argument("--level", action="append", default=[])
    a.add_argument("--extra", action="append", default=[], help="identifiant catalogue à ajouter à la galerie")
    a = actions.add_parser("propose")
    a.add_argument("decisions")
    a.add_argument("output")
    a = actions.add_parser("apply")
    a.add_argument("proposals")
    a.add_argument("--apply", action="store_true", help="écrire dans la base (sauvegarde d'abord)")
    args = parser.parse_args(argv)
    data = Path(args.data)
    cache = Path(args.cache or data / "references")
    if args.action in ("sheets", "strips"):
        copies = load_copies(data, args.copies, args.level)
        made = (sheets if args.action == "sheets" else strips)(copies, data / "photos", Path(args.output))
        print(len(copies), "exemplaires,", len(made), "planches")
    elif args.action == "lookup":
        db = readonly(data)
        for cid in args.ids:
            print(cid, lookup(db, cid))
    elif args.action == "score":
        result = score(load_copies(data, args.copies, args.level), data / "photos", cache, extra=args.extra)
        Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=1))
        print(len(result), "->", args.output)
    elif args.action == "propose":
        result = propose(read_decisions(args.decisions), data, cache)
        Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=1))
        print(len(result), "propositions ->", args.output)
    else:
        patches = json.loads(Path(args.proposals).read_text())
        patches = patches.get("patches", patches) if isinstance(patches, dict) else patches
        _, done, skipped = apply(patches, data, write=args.apply)
        print(("appliqué" if args.apply else "essai sur copie temporaire"), len(done), "sauté", len(skipped))
        for copy_id, error in skipped:
            print("  SAUTÉ", copy_id, error)
        for copy_id, _, drift in done:
            if drift:
                print("  ÉCART", copy_id, drift)


if __name__ == "__main__":
    main()
