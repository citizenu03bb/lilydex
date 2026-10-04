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


SYSTEM_OCR_PROMPT = """You are an expert OCR engine for Pokemon trading cards (specifically French language editions).
Carefully examine this cropped Pokemon card image:
1. 'name': Card name printed at the top (include Level / NIV. if present, e.g. "Arbok NIV.31", "Givrali NIV.42", "Kapoera NIV.25", "Salle de Maître").
2. 'hp': PV / Points de Vie (HP) number printed at top right (integer, e.g. '80 PV' -> 80. Return 0 for Trainers, Stadiums, or Energy cards).
3. 'card_number': Look very closely at the bottom-right and bottom-left margins/corners for the collector number fraction (e.g. "33/106", "4/102", "15/114"). Read the tiny digits carefully. Return empty string only if genuinely absent.
4. 'is_holo': true if the card has holographic foil, glitter, shiny border, or rainbow sheen, else false.

Respond ONLY with a valid JSON object matching this schema:
{
  "name": "<exact French card name>",
  "hp": <HP integer>,
  "card_number": "<collector fraction like 33/106>",
  "is_holo": <boolean>
}
Do not write markdown explanations or introductory text outside the JSON."""

CORNER_OCR_PROMPT = """You are an expert Pokemon card reader.
Read the Pokemon card collector number fraction in this bottom margin (e.g. "33/106", "4/102", "15/114").
Respond ONLY with a valid JSON object:
{"card_number": "<fraction>"}"""


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

        return CardOCRResult(
            name=name,
            hp=hp,
            card_number=card_num,
            is_holo=is_holo,
            raw_response=raw_text
        )

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
    """Optional cloud provider using google-genai SDK if GEMINI_API_KEY is configured."""
    def __init__(self, model: str = "gemini-2.5-flash"):
        self.model = model
        try:
            from google import genai
            self.client = genai.Client()
        except ImportError:
            raise ImportError(
                "google-genai is not installed. Run 'uv pip install google-genai' to use cloud backend."
            )

    def extract_card(self, image: Image.Image) -> CardOCRResult:
        from google.genai import types
        
        buf = io.BytesIO()
        image.save(buf, format="JPEG", quality=92)
        
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
            raw_response=raw_text
        )


def get_ocr_provider(backend: str = "ollama", model: Optional[str] = None):
    if backend == "ollama":
        target_model = model or "gemma4:e4b-it-q4_K_M"
        return OllamaVisionProvider(model=target_model)
    elif backend == "gemini":
        target_model = model or "gemini-2.5-flash"
        return GeminiVisionProvider(model=target_model)
    else:
        raise ValueError(f"Unknown OCR backend: {backend}. Choose 'ollama' or 'gemini'.")
