"""
Vision OCR engine supporting local Ollama (Gemma 4 E4B) and optional Gemini API fallback.
"""

import base64
import io
import json
import os
import re
from dataclasses import dataclass
from typing import Optional
from PIL import Image


@dataclass
class CardOCRResult:
    name: str
    hp: int
    card_number: str
    is_holo: bool
    raw_response: str
    condition: str = "NM/EX"
    flaws: str = ""


SYSTEM_OCR_PROMPT = """You are an expert OCR and condition grading engine for Pokemon trading cards (specifically French language editions).
Carefully examine this cropped Pokemon card image:
1. 'name': Card name printed at the top (include Level / NIV. if present, e.g. "Arbok NIV.31", "Givrali NIV.42", "Kapoera NIV.25", "Salle de Maître"). If in Japanese, provide the Romanized or French name (e.g. "Meganium LV.54").
2. 'hp': PV / Points de Vie (HP) number printed at top right (integer, e.g. '80 PV' -> 80. Return 0 for Trainers, Stadiums, or Energy cards).
3. 'card_number': Look very closely at the bottom-right and bottom-left margins/corners for the collector number fraction (e.g. "33/106", "4/102", "86/132"). Read the tiny digits and set symbol carefully. You may also cross-check attacks or the illustrator name at bottom right to confirm the exact expansion if digits are dark or faint. Return empty string only if genuinely absent.
4. 'is_holo': true ONLY if the card has real holographic foil / shiny artwork or foil border. Return false if flat non-holo ink or if gloss is just plastic sleeve reflection.
5. 'condition': Grade the physical condition:
   - 'NM' (Near Mint: clean borders, sharp corners, no scratches)
   - 'EX' (Excellent: very minor edge whitening or tiny flaw)
   - 'GD' (Good: noticeable white spots on borders/corners, light scratches)
   - 'LP' (Light Played: clear whitening along edges, minor bends/dings)
   - 'PL' (Played: heavy whitening, creases, dents, heavy surface wear)
   - 'PO' (Poor: major damage, tears, peeling corners)
6. 'flaws': Brief description of visible defects (e.g. 'edge whitening on top-right', 'scratched holo window', 'rounded peeling corners', or 'none visible').
If this image shows an empty binder pocket or no card, return empty string for 'name' and 'condition': '' and 'flaws': 'empty pocket'.

Respond ONLY with a valid JSON object matching this schema:
{
  "name": "<exact French card name>",
  "hp": <HP integer>,
  "card_number": "<collector fraction>",
  "is_holo": <boolean>,
  "condition": "<NM | EX | GD | LP | PL | PO>",
  "flaws": "<description of defects or 'none visible'>"
}
Do not write markdown explanations or introductory text outside the JSON."""

CORNER_OCR_PROMPT = """You are an expert Pokemon card reader.
Read the Pokemon card collector number fraction in this bottom margin (e.g. "33/106", "4/102", "15/114").
Respond ONLY with a valid JSON object:
{"card_number": "<fraction>"}"""

LAYOUT_PROMPT = """Look at this photo:
What is the layout of Pokemon cards in this image?
- '2x2' (4 cards arranged in 2 rows of 2 pockets)
- '3x3' (9 cards arranged in 3 rows of 3 pockets)
- '4x3' (12 cards arranged in 3 rows of 4 pockets)
- 'single' (1 single card alone, slab, or toploader)
- 'cover' (an album binder cover, back cover, or non-card photo)

Respond ONLY with a valid JSON object:
{"layout": "2x2" | "3x3" | "4x3" | "single" | "cover"}"""


class OllamaVisionProvider:
    def __init__(
        self,
        endpoint: str = "http://localhost:11434/api/generate",
        model: str = "gemma4:e4b-it-q4_K_M"
    ):
        self.endpoint = endpoint
        self.model = model

    def _query_ollama(self, image: Image.Image, prompt: str, num_predict: int = 128) -> str:
        import urllib.request
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        b64_img = base64.b64encode(buf.getvalue()).decode("utf-8")

        payload = {
            "model": self.model,
            "prompt": prompt,
            "images": [b64_img],
            "stream": False,
            "format": "json",
            "options": {
                "num_ctx": 4096,
                "num_predict": num_predict,
                "temperature": 0.1,
                "presence_penalty": 0.1,
                "frequency_penalty": 0.1
            }
        }

        req = urllib.request.Request(
            self.endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )

        with urllib.request.urlopen(req, timeout=45) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("response", "{}")

    def extract_card(self, image: Image.Image) -> CardOCRResult:
        try:
            raw_text = self._query_ollama(image, SYSTEM_OCR_PROMPT, num_predict=128)
        except Exception as e:
            return CardOCRResult(
                name="Error",
                hp=0,
                card_number="",
                is_holo=False,
                raw_response=str(e)
            )

        # Parse JSON from response
        parsed = self._parse_json(raw_text)
        name = parsed.get("name", "").strip()
        hp = int(parsed.get("hp", 0) or 0)
        card_num = parsed.get("card_number", "").strip()
        is_holo = bool(parsed.get("is_holo", False))

        # Targeted fallback crop if card_number is missing or incomplete (no slash)
        if not card_num or "/" not in card_num:
            try:
                w, h = image.size
                bottom_crop = image.crop((0, int(h * 0.82), w, h))
                corner_raw = self._query_ollama(bottom_crop, CORNER_OCR_PROMPT, num_predict=48)
                corner_parsed = self._parse_json(corner_raw)
                detected_corner_num = corner_parsed.get("card_number", "").strip()
                if detected_corner_num and ("/" in detected_corner_num or not card_num):
                    card_num = detected_corner_num
            except Exception:
                pass

        condition = parsed.get("condition", "NM/EX").strip()
        flaws = parsed.get("flaws", "").strip()

        return CardOCRResult(
            name=name,
            hp=hp,
            card_number=card_num,
            is_holo=is_holo,
            condition=condition,
            flaws=flaws,
            raw_response=raw_text
        )

    def detect_layout(self, image: Image.Image) -> str:
        """
        Fast zero-shot classification of card pocket layout on a 512px thumbnail.
        Returns: '2x2', '3x3', '4x3', 'single', or 'cover'.
        """
        thumb = image.copy()
        thumb.thumbnail((512, 512))
        try:
            raw = self._query_ollama(thumb, LAYOUT_PROMPT, num_predict=32)
            parsed = self._parse_json(raw)
            layout = parsed.get("layout", "2x2").lower().strip()
            if layout in ("2x2", "3x3", "4x3", "single", "cover"):
                return layout
        except Exception:
            pass
        return "2x2"

    @staticmethod
    def _parse_json(text: str) -> dict:
        text = text.strip()
        # Strip markdown ```json code block if present
        if "```" in text:
            match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
            if match:
                text = match.group(1)
        try:
            return json.loads(text)
        except Exception:
            # Fallback: find first { and last }
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1:
                try:
                    return json.loads(text[start : end + 1])
                except Exception:
                    pass
            return {}


class GeminiVisionProvider:
    """Cloud provider using google-genai SDK with Gemini 3.8 Flash by default."""
    def __init__(self, model: str = "gemini-3.8-flash"):
        self.model = model
        # Automatically load environment variables from ~/.env and local .env
        from pathlib import Path
        try:
            from dotenv import load_dotenv
            home_env = Path.home() / ".env"
            if home_env.exists():
                load_dotenv(home_env)
            load_dotenv()
        except ImportError:
            pass

        try:
            import logging
            logging.getLogger("google_genai").setLevel(logging.ERROR)
            from google import genai
            self.client = genai.Client()
        except ImportError:
            raise ImportError(
                "google-genai is not installed. Run 'uv pip install google-genai python-dotenv' to use cloud backend."
            )

    def extract_card(self, image: Image.Image) -> CardOCRResult:
        from google.genai import types
        
        buf = io.BytesIO()
        image.save(buf, format="JPEG", quality=95)
        
        response = self.client.models.generate_content(
            model=self.model,
            contents=[
                types.Part.from_bytes(data=buf.getvalue(), mime_type="image/jpeg"),
                SYSTEM_OCR_PROMPT
            ],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.1
            )
        )
        
        raw_text = response.text or "{}"
        try:
            parsed = json.loads(raw_text)
        except Exception:
            parsed = {}

        return CardOCRResult(
            name=parsed.get("name", "").strip(),
            hp=int(parsed.get("hp", 0) or 0),
            card_number=parsed.get("card_number", "").strip(),
            is_holo=bool(parsed.get("is_holo", False)),
            condition=parsed.get("condition", "NM/EX").strip(),
            flaws=parsed.get("flaws", "").strip(),
            raw_response=raw_text
        )

    def detect_layout(self, image: Image.Image) -> str:
        """Fast grid layout classification using Gemini API."""
        from google.genai import types
        thumb = image.copy()
        thumb.thumbnail((512, 512))
        buf = io.BytesIO()
        thumb.save(buf, format="JPEG", quality=80)
        try:
            resp = self.client.models.generate_content(
                model=self.model,
                contents=[
                    types.Part.from_bytes(data=buf.getvalue(), mime_type="image/jpeg"),
                    LAYOUT_PROMPT
                ],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.1
                )
            )
            parsed = json.loads(resp.text or "{}")
            layout = parsed.get("layout", "2x2").lower().strip()
            if layout in ("2x2", "3x3", "4x3", "single", "cover"):
                return layout
        except Exception:
            pass
        return "2x2"


def get_ocr_provider(backend: str = "ollama", model: Optional[str] = None):
    if backend == "ollama":
        target_model = model or "gemma4:e4b-it-q4_K_M"
        return OllamaVisionProvider(model=target_model)
    elif backend == "gemini":
        target_model = model or "gemini-3.8-flash"
        return GeminiVisionProvider(model=target_model)
    else:
        raise ValueError(f"Unknown OCR backend: {backend}. Choose 'ollama' or 'gemini'.")
