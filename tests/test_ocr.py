import json
from types import SimpleNamespace
import pytest
from PIL import Image
from pokeprice.ocr import parse_ocr_response, GeminiVisionProvider, OllamaVisionProvider


@pytest.mark.parametrize(
    "field,value",
    [
        ("hp", "?"),
        ("condition", None),
        ("is_holo", "false"),
        ("name", None),
        ("card_number", 23),
    ],
)
def test_invalid_fields_are_failed_not_empty(field, value):
    payload = {"name": "Pikachu", "occupied": True, field: value}
    result = parse_ocr_response(json.dumps(payload))
    assert result.status == "failed"
    assert result.occupied is not False


@pytest.mark.parametrize("raw", ["{}", "bad json", "[]"])
def test_invalid_response_is_not_empty(raw):
    assert parse_ocr_response(raw).status == "failed"


def test_card_back_and_empty_are_distinct():
    assert parse_ocr_response('{"name":"","occupied":true}').status == "unidentified"
    assert parse_ocr_response('{"name":"","occupied":false}').status == "empty"


def test_absent_grade_remains_unknown():
    assert parse_ocr_response('{"name":"Pikachu","occupied":true}').condition == ""


@pytest.mark.parametrize("mode", ["RGBA", "P"])
def test_gemini_converts_supported_image_modes(mode):
    provider = GeminiVisionProvider.__new__(GeminiVisionProvider)
    provider.model = "mock"
    responses = iter(
        [
            '{"name":"Pikachu","occupied":true,"hp":50,"card_number":"1/100","is_holo":false,"condition":"","flaws":""}',
            '{"layout":"2x2"}',
        ]
    )

    def generate(**kwargs):
        assert kwargs["contents"][0].inline_data.data.startswith(b"\xff\xd8")
        return SimpleNamespace(text=next(responses))

    provider.client = SimpleNamespace(models=SimpleNamespace(generate_content=generate))
    image = Image.new(mode, (100, 100))
    assert provider.extract_card(image).name == "Pikachu"
    assert provider.detect_layout(image) == "2x2"


def test_gemini_incomplete_observations_are_retryable_failures():
    provider = GeminiVisionProvider.__new__(GeminiVisionProvider)
    provider.model = "mock"
    provider.client = SimpleNamespace(
        models=SimpleNamespace(
            generate_content=lambda **kw: SimpleNamespace(
                text='{"name":"Zarbi","occupied":true}'
            )
        )
    )
    result = provider.extract_card(Image.new("RGB", (100, 100)))
    assert (
        result.status == "failed"
        and result.raw_response == '{"name":"Zarbi","occupied":true}'
    )


def test_bad_layout_is_not_assumed_two_by_two(monkeypatch):
    provider = OllamaVisionProvider()
    monkeypatch.setattr(
        provider, "_query_ollama", lambda *a, **k: '{"layout":"unknown"}'
    )
    with pytest.raises(ValueError):
        provider.detect_layout(Image.new("RGB", (100, 100)))


def test_absent_layout_is_failed(monkeypatch):
    provider = OllamaVisionProvider()
    monkeypatch.setattr(provider, "_query_ollama", lambda *a, **k: "{}")
    with pytest.raises(ValueError):
        provider.detect_layout(Image.new("RGB", (100, 100)))


def test_ollama_request_disables_thinking(monkeypatch):
    """A thinking model would spend num_predict on reasoning and answer nothing."""
    import io
    import json
    import urllib.request

    sent = {}

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def urlopen(request, timeout):
        sent.update(json.loads(request.data))
        return Response(json.dumps({"response": "{}"}).encode())

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    from PIL import Image

    from pokeprice.ocr import OllamaVisionProvider

    OllamaVisionProvider()._query_ollama(Image.new("RGB", (8, 8)), "prompt")
    assert sent["think"] is False and sent["format"] == "json"
