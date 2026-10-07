"""Image-retrieval runner of the recognition bench (pre-trained models, no training).

Each card photo is compared with every TCGdex reference image of the gallery
(the true edition plus all same-name cards as distractors). Needs PyTorch and
transformers, e.g. an existing CUDA environment:

    HF_HOME=/mnt/models/huggingface <python-with-torch> scripts/bench_embed.py
"""

import json
import sys
from pathlib import Path

import torch
from PIL import Image
from transformers import AutoImageProcessor, AutoModel, CLIPModel, CLIPProcessor

OUT = Path(__file__).resolve().parents[1] / "outputs/bench-recognition"
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"


def rgb(path):
    image = Image.open(path)
    if image.mode in ("RGBA", "LA", "P"):
        image = image.convert("RGBA")
        background = Image.new("RGBA", image.size, "white")
        image = Image.alpha_composite(background, image)
    return image.convert("RGB")


def embedder(name):
    if name.startswith("openai/clip"):
        model = CLIPModel.from_pretrained(name).to(DEVICE).eval()
        processor = CLIPProcessor.from_pretrained(name)

        def embed(images):
            inputs = processor(images=images, return_tensors="pt").to(DEVICE)
            return model.get_image_features(**inputs)

    else:
        model = AutoModel.from_pretrained(name).to(DEVICE).eval()
        processor = AutoImageProcessor.from_pretrained(name)

        def embed(images):
            inputs = processor(images=images, return_tensors="pt").to(DEVICE)
            return model(**inputs).last_hidden_state[:, 0]  # CLS token

    @torch.no_grad()
    def run(paths):
        vectors = []
        for start in range(0, len(paths), 16):
            vectors.append(embed([rgb(p) for p in paths[start : start + 16]]))
        return torch.nn.functional.normalize(torch.cat(vectors), dim=-1)

    return run


def main():
    entries = json.loads((OUT / "truth.json").read_text())
    gallery = json.loads((OUT / "gallery.json").read_text())
    ids = [g["id"] for g in gallery]
    names = {g["id"]: g["name"] for g in gallery}
    models = sys.argv[1:] or ["facebook/dinov2-small", "openai/clip-vit-base-patch32"]
    for model_name in models:
        run = embedder(model_name)
        refs = run([OUT / g["path"] for g in gallery])
        photos = run([OUT / e["photo"] for e in entries])
        similarity = photos @ refs.T
        results = {}
        for row, entry in zip(similarity.tolist(), entries, strict=True):
            order = sorted(range(len(ids)), key=lambda i: -row[i])
            truth = entry["truth"]["catalog_id"]
            evaluable = truth in ids
            rank = [ids[i] for i in order].index(truth) + 1 if evaluable else None
            top = ids[order[0]]
            results[entry["copy_id"]] = {
                "edition_read": top,
                "edition_name": names[top],
                "edition_ok": (top == truth) if evaluable else None,
                "rank": rank,
                "top3": [ids[i] for i in order[:3]],
                "margin": round(row[order[0]] - row[order[1]], 4),
                "ranking": [ids[i] for i in order],
                "evaluable": evaluable,
            }
            print(f"{model_name:<30} {entry['label']:<45} rang {rank} top {top}")
        short = model_name.split("/")[1]
        (OUT / f"result-embed-{short}.json").write_text(json.dumps(results, indent=1))


if __name__ == "__main__":
    main()
