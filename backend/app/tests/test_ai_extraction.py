"""VLM structured-extraction unit tests.

All network calls are mocked — these tests run without a GPU endpoint, without
worker extras installed, and without any DB/Redis connection. The OpenAI client
is monkeypatched at the ``openai`` module level (the deferred import point).

Run: ``pytest app/tests/test_ai_extraction.py -v``
"""

import json
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_openai_response(content: str) -> MagicMock:
    """Build a fake openai ChatCompletion response."""
    msg = MagicMock()
    msg.content = content
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


def _make_openai_client(*response_contents: str) -> MagicMock:
    """Fake client returning one response per call (cycles through the args)."""
    client = MagicMock()
    responses = [_make_openai_response(c) for c in response_contents]
    if len(responses) == 1:
        client.chat.completions.create.return_value = responses[0]
    else:
        client.chat.completions.create.side_effect = responses
    return client


def _mock_settings(**over) -> MagicMock:
    """A settings stub with real numeric budget fields (MagicMock math would break)."""
    s = MagicMock()
    s.vlm_base_url = "http://fake-vlm/v1"
    s.vlm_api_key = "test-key"
    s.vlm_model = "Qwen2-VL-2B"
    s.vlm_max_model_len = 2048
    s.vlm_max_output_tokens = 768
    s.vlm_render_dpi = 120
    s.vlm_request_timeout = 90.0
    s.vlm_max_chunk_calls = 6
    s.vlm_max_pages = 10
    s.confidence_threshold = 0.7
    for k, v in over.items():
        setattr(s, k, v)
    return s


def _user_content(fake_client) -> list:
    """Return the user-message content list from the (first) recorded call."""
    call = fake_client.chat.completions.create.call_args
    messages = call.kwargs["messages"]
    user_msg = next(m for m in messages if m["role"] == "user")
    return user_msg["content"]


# ---------------------------------------------------------------------------
# Text mode (digital PDFs — has_text_layer=True)
# ---------------------------------------------------------------------------


class TestTextMode:
    def _call(self, *responses, text="Invoice total RM 100", **over):
        from app.modules.idp import extraction

        fake_client = _make_openai_client(*responses)
        with patch("app.modules.idp.extraction.settings", _mock_settings(**over)), \
             patch("openai.OpenAI", return_value=fake_client):
            outcome = extraction.extract_structured(b"", "application/pdf", text, True)
        return outcome, fake_client

    def test_valid_invoice_json_is_parsed(self):
        payload = json.dumps({
            "documentType": "invoice",
            "confidence": 0.92,
            "fields": {"vendor": "Tenaga Nasional", "invoice_number": "INV-1", "total_amount": 1284.5},
        })
        outcome, _ = self._call(payload)
        assert outcome.mode == "text"
        assert outcome.extraction is not None
        ext = outcome.extraction
        assert ext.document_type == "invoice"
        assert ext.confidence == pytest.approx(0.92)
        assert ext.fields["vendor"] == "Tenaga Nasional"
        assert ext.fields["total_amount"] == pytest.approx(1284.5)

    def test_text_mode_sends_text_not_images(self):
        """Digital docs must NOT include image parts — text-first cost cascade."""
        payload = json.dumps({"documentType": "invoice", "confidence": 0.8, "fields": {}})
        _, fake_client = self._call(payload)
        content = _user_content(fake_client)
        assert all(c.get("type") != "image_url" for c in content)
        assert any(c.get("type") == "text" for c in content)

    def test_unknown_document_type_maps_to_other(self):
        payload = json.dumps({"documentType": "fax", "confidence": 0.5, "fields": {"x": 1}})
        outcome, _ = self._call(payload)
        assert outcome.extraction.document_type == "other"

    def test_confidence_clamped(self):
        payload = json.dumps({"documentType": "report", "confidence": 1.5, "fields": {}})
        outcome, _ = self._call(payload)
        assert outcome.extraction.confidence <= 1.0

    def test_malformed_json_returns_error_outcome(self):
        outcome, _ = self._call("Sorry, I cannot extract data.")
        assert outcome.extraction is None
        assert outcome.error  # reason captured, not a silent None

    def test_prose_wrapped_json_parsed_tolerantly(self):
        payload = 'Here you go: {"documentType":"contract","confidence":0.75,"fields":{"parties":"A and B"}} done!'
        outcome, _ = self._call(payload)
        assert outcome.extraction is not None
        assert outcome.extraction.document_type == "contract"

    def test_flat_fields_without_wrapper_are_kept(self):
        """A small model returning flat keys (no 'fields' wrapper) must not lose data."""
        payload = json.dumps({"vendor": "ACME", "total_amount": 100})
        outcome, _ = self._call(payload)
        assert outcome.extraction is not None
        assert outcome.extraction.fields["vendor"] == "ACME"
        assert outcome.extraction.fields["total_amount"] == 100

    def test_long_text_chunks_and_merges(self):
        """Text over the per-call budget → multiple calls; line_items concatenate, total = last."""
        resp1 = json.dumps({
            "documentType": "invoice", "confidence": 0.9,
            "fields": {"vendor": "ACME", "line_items": [{"d": "A"}], "total": 50},
        })
        resp2 = json.dumps({
            "documentType": "invoice", "confidence": 0.7,
            "fields": {"line_items": [{"d": "B"}], "total": 200},
        })
        # Two ~600-char lines force two line-aligned chunks under a shrunk budget.
        big_text = ("A" * 600) + "\n" + ("B" * 600)
        outcome, fake_client = self._call(resp1, resp2, text=big_text, vlm_max_model_len=1200)

        assert fake_client.chat.completions.create.call_count == 2
        ext = outcome.extraction
        assert ext is not None
        assert ext.fields["line_items"] == [{"d": "A"}, {"d": "B"}]   # concatenated across pages
        assert ext.fields["total"] == 200                            # last page wins for totals
        assert ext.fields["vendor"] == "ACME"                        # first non-empty kept
        assert ext.confidence == pytest.approx(0.8)                  # mean of chunk confidences


# ---------------------------------------------------------------------------
# Vision mode (scans / images — has_text_layer=False)
# ---------------------------------------------------------------------------


class TestVisionMode:
    def test_image_upload_sends_image_parts(self):
        from app.modules.idp import extraction

        payload = json.dumps({"documentType": "receipt", "confidence": 0.8, "fields": {"vendor": "Parking"}})
        fake_client = _make_openai_client(payload)
        fake_img = b"\xff\xd8\xff fake jpeg"
        with patch("app.modules.idp.extraction.settings", _mock_settings()), \
             patch("openai.OpenAI", return_value=fake_client):
            outcome = extraction.extract_structured(fake_img, "image/jpeg", None, False)

        assert outcome.mode == "vision"
        assert outcome.extraction is not None
        content = _user_content(fake_client)
        image_parts = [c for c in content if c.get("type") == "image_url"]
        assert len(image_parts) >= 1
        assert image_parts[0]["image_url"]["url"].startswith("data:image/png;base64,")


# ---------------------------------------------------------------------------
# render_page_images
# ---------------------------------------------------------------------------


class TestRenderPageImages:
    _IMAGE_MIMES = ["image/jpeg", "image/png", "image/webp", "image/tiff"]

    def test_image_mime_returns_single_page(self):
        from app.modules.idp.extraction import render_page_images

        fake_img = b"\xff\xd8\xff fake jpeg"  # unopenable → resize returns it unchanged
        for mime in self._IMAGE_MIMES:
            assert render_page_images(fake_img, mime, max_pages=3) == [fake_img]

    def test_pdf_pages_rasterised_up_to_max(self):
        import sys

        parsing_mock = MagicMock()
        mock_page = MagicMock()
        mock_doc = MagicMock()
        mock_doc.page_count = 5
        mock_doc.__iter__ = MagicMock(return_value=iter([mock_page] * 5))
        mock_doc.close = MagicMock()
        parsing_mock.open_pdf.return_value = mock_doc
        parsing_mock.rasterize_page.return_value = b"\x89PNG fakepage"

        with patch.dict(sys.modules, {"app.modules.idp.parsing": parsing_mock}):
            from app.modules.idp import extraction as ext_mod
            result = ext_mod.render_page_images(b"fake-pdf", "application/pdf", max_pages=3, dpi=120)

        assert len(result) == 3
        assert parsing_mock.rasterize_page.call_count == 3


# ---------------------------------------------------------------------------
# Tolerant parse + truncation repair
# ---------------------------------------------------------------------------


class TestTolerantParse:
    def test_strips_code_fences(self):
        from app.modules.idp.extraction import _tolerant_parse

        parsed = _tolerant_parse('```json\n{"a": 1}\n```')
        assert parsed == {"a": 1}

    def test_repairs_truncated_json(self):
        """Output cut off mid line-items array is closed and parsed."""
        from app.modules.idp.extraction import _tolerant_parse

        truncated = '{"a":1,"items":[{"x":1},{"x":2'
        parsed = _tolerant_parse(truncated)
        assert parsed is not None
        assert parsed["items"][0]["x"] == 1
        assert parsed["items"][1]["x"] == 2

    def test_unrepairable_returns_none(self):
        from app.modules.idp.extraction import _tolerant_parse

        assert _tolerant_parse("not json at all") is None


# ---------------------------------------------------------------------------
# run_ai_extraction (pipeline orchestrator) — skip path
# ---------------------------------------------------------------------------


def test_run_ai_extraction_skips_when_no_endpoint():
    """No endpoint → skipped outcome, never imports parsing / never renders."""
    from app.modules.idp.pipeline import run_ai_extraction

    mock_settings = MagicMock()
    mock_settings.vlm_base_url = ""

    with patch("app.core.config.settings", mock_settings):
        outcome = run_ai_extraction(b"\xff\xd8\xff fake", "image/jpeg", "some text", False)

    assert outcome.extraction is None
    assert outcome.mode == "skipped"
    assert outcome.error is None


# ---------------------------------------------------------------------------
# DocumentOut schema — confidence is camelCase
# ---------------------------------------------------------------------------


def test_document_out_confidence_is_camel():
    import re
    from app.modules.files.schemas import DocumentOut

    CAMEL_RE = re.compile(r"^[a-z][a-zA-Z0-9]*$")
    for field_name in DocumentOut.model_fields:
        alias = DocumentOut.model_config.get("alias_generator", lambda x: x)(field_name)
        assert CAMEL_RE.match(alias), f"DocumentOut.{field_name} → '{alias}' not camelCase"

    assert "confidence" in DocumentOut.model_fields
