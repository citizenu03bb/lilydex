"""Downloadable sale drafts without private notes or publication side effects."""

import json
import re
import zipfile


def package(store, sale_id, target):
    with store.connect() as db:
        db.execute("BEGIN")
        sale = db.execute("SELECT * FROM sales WHERE id=?", (sale_id,)).fetchone()
        if not sale:
            raise KeyError("Lot inconnu.")
        cards = [
            store.get(db, r[0])
            for r in db.execute(
                "SELECT copy_id FROM sale_items WHERE sale_id=? ORDER BY copy_id",
                (sale_id,),
            )
        ]
    if any(c["deleted_at"] for c in cards):
        raise ValueError("Un exemplaire de ce lot est dans la corbeille.")
    lines = [sale["title"], "", f"Lot de {len(cards)} carte(s) Pokémon.", ""]
    checks, manifest = [], []
    if sale["asking_cents"] is not None:
        lines.append(f"Prix demandé : {sale['asking_cents'] / 100:.2f} EUR")
    else:
        checks.append("Fixer le prix demandé.")
    with zipfile.ZipFile(target, "x", zipfile.ZIP_DEFLATED) as archive:
        for n, c in enumerate(cards, 1):
            label = f"{c['name']} · {c['set_name'] or 'extension à vérifier'} · {c['number'] or 'référence à vérifier'} · {c['language']}"
            grade = (
                c["condition"]
                if c["condition_confirmed"] and c["condition"]
                else "état à vérifier"
            )
            lines.append(
                f"- {label} ; {grade}"
                + (" ; brillante" if c["foil"] else "")
                + (f" ; tampon « {c['stamp']} »" if c.get("stamp") else "")
            )
            if not c["condition_confirmed"]:
                checks.append(f"{n}. {c['name']} : vérifier l’état physique.")
            if c["identification_status"] != "confirmed":
                checks.append(f"{n}. {c['name']} : vérifier l’édition et la référence.")
            slug = re.sub(r"[^a-z0-9]+", "-", c["name"].lower()).strip("-") or "carte"
            files = []
            for field, face in (("photo", "recto"), ("back_photo", "verso")):
                if c[field]:
                    filename = f"photos/{n:03d}-{slug[:60]}-{face}.jpg"
                    archive.write(store.photos / c[field], filename)
                    files.append(filename)
                else:
                    checks.append(f"{n}. {c['name']} : ajouter une photo du {face}.")
            manifest.append(
                {
                    "name": c["name"],
                    "set_name": c["set_name"],
                    "number": c["number"],
                    "language": c["language"],
                    "condition": grade,
                    "photos": files,
                }
            )
        checks += [
            "Compléter les modalités de livraison et de paiement.",
            "Relire le texte et les photos avant toute publication.",
        ]
        archive.writestr("description.txt", "\n".join(lines) + "\n")
        archive.writestr("a-completer.txt", "\n".join(checks) + "\n")
        archive.writestr(
            "cartes.json", json.dumps(manifest, ensure_ascii=False, indent=2)
        )
