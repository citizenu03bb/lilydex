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
Inspect this cropped Pokemon card image very carefully.
Extract the card's information and respond ONLY with a valid JSON object matching this schema:
{
  "name": "<exact French card name printed at top, e.g. Gruikui, Kapoera NIV.25, Ortide, Salle de Maître>",
  "hp": <HP number printed at top right, e.g. 60, or 0 if it is a Trainer, Stadium, or Energy card>,
  "card_number": "<the fraction at the bottom corner, e.g. 15/114 or 4/106. Return empty string if no fraction>",
  "is_holo": <true if the card has holographic foil, glitter, shiny border, or rainbow sheen, else false>
}
Do not write markdown explanations or introductory text outside the JSON."""


class OllamaVisionProvider:
    def __init__(
        self,
        endpoint: str = "http://localhost:11434/api/generate",
        model: str = "gemma4:e4b-it-q4_K_M"
    ):
        self.endpoint = endpoint
        self.model = model

    def extract_card(self, image: Image.Image) -> CardOCRResult:
        import urllib.request

        # Convert PIL image to base64 JPEG
        buf = io.BytesIO()
        image.save(buf, format="JPEG", quality=92)
        b64_img = base64.b64encode(buf.getvalue()).decode("utf-8")

        payload = {
            "model": self.model,
            "prompt": SYSTEM_OCR_PROMPT,
            "images": [b64_img],
            "stream": False,
            "format": "json",
            "options": {
                "temperature": 0.1
            }
        }

        req = urllib.request.Request(
            self.endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )

        try:
            with urllib.request.urlopen(req, timeout=45) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                raw_text = data.get("response", "{}")
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
        return CardOCRResult(
            name=parsed.get("name", "").strip(),
            hp=int(parsed.get("hp", 0) or 0),
            card_number=parsed.get("card_number", "").strip(),
            is_holo=bool(parsed.get("is_holo", False)),
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
