"""IDP pipeline unit tests — text extraction logic.

Tests ``run_extraction`` with all I/O mocked so they:
- Run without PyMuPDF or RapidOCR installed (worker extras not needed in dev).
- Run offline with no Supabase / Redis / DB dependencies.
- Execute in milliseconds.

``parsing`` and ``ocr`` modules are mocked via ``sys.modules`` so ``fitz`` /
``rapidocr_onnxruntime`` are never imported.

Run: ``pytest app/tests/test_idp_pipeline.py -v``
"""

import sys
import types
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Mock the heavy worker-only modules before pipeline imports them.
# This prevents ModuleNotFoundError for fitz / rapidocr_onnxruntime.
# ---------------------------------------------------------------------------

def _make_parsing_mock(
    page_count: int = 1,
    text: str = "Invoice Total 500 Hello World",
    usable: bool = True,
) -> MagicMock:
    """Build a mock that shadows app.modules.idp.parsing."""
    mock_page = MagicMock()
    mock_page.__iter__ = MagicMock(return_value=iter([mock_page] * page_count))

    mock_doc = MagicMock()
    mock_doc.page_count = page_count
    mock_doc.__iter__ = MagicMock(return_value=iter([mock_page] * page_count))
    mock_doc.close = MagicMock()

    m = MagicMock()
    m.open_pdf.return_value = mock_doc
    m.extract_text_layer.return_value = text
    m.has_usable_text_layer.return_value = usable
    m.rasterize_page.return_value = b"\x89PNG fake"
    return m


# ---------------------------------------------------------------------------
# text-layer path (digital PDF)
# ---------------------------------------------------------------------------


def test_text_layer_pdf_uses_text_layer_path():
    """Digital PDF → text-layer read; OCR must NOT be called."""
    parsing_mock = _make_parsing_mock(text="Invoice Total 500 Hello World", usable=True)
    ocr_mock = MagicMock(return_value=("", 0.0))

    with patch.dict(sys.modules, {"app.modules.idp.parsing": parsing_mock}), \
         patch("app.modules.idp.ocr.ocr_image", ocr_mock):
        # Force fresh import so patches take effect.
        if "app.modules.idp.pipeline" in sys.modules:
            del sys.modules["app.modules.idp.pipeline"]
        from app.modules.idp.pipeline import run_extraction

        result = run_extraction(b"fake-pdf-bytes", "application/pdf")

    assert result.has_text_layer is True
    assert result.ocr_used is False
    assert result.ocr_confidence is None
    assert len(result.text) > 0
    assert result.page_count == 1
    ocr_mock.assert_not_called()


def test_text_layer_pdf_text_is_non_empty():
    """Text extracted from a text-layer PDF must be non-empty after strip."""
    parsing_mock = _make_parsing_mock(text="Purchase Order Reference 9999", usable=True)

    with patch.dict(sys.modules, {"app.modules.idp.parsing": parsing_mock}):
        if "app.modules.idp.pipeline" in sys.modules:
            del sys.modules["app.modules.idp.pipeline"]
        from app.modules.idp.pipeline import run_extraction

        result = run_extraction(b"fake-pdf-bytes", "application/pdf")

    assert "Purchase" in result.text or len(result.text.strip()) > 0


# ---------------------------------------------------------------------------
# OCR fallback path (scanned PDF / image)
# ---------------------------------------------------------------------------


def test_scanned_pdf_falls_back_to_ocr():
    """PDF with no usable text layer → OCR runs, flags set correctly."""
    parsing_mock = _make_parsing_mock(text="   ", usable=False, page_count=1)
    ocr_result = ("scanned receipt text", 0.88)

    with patch.dict(sys.modules, {"app.modules.idp.parsing": parsing_mock}), \
         patch("app.modules.idp.ocr.ocr_image", return_value=ocr_result) as mock_ocr:
        if "app.modules.idp.pipeline" in sys.modules:
            del sys.modules["app.modules.idp.pipeline"]
        from app.modules.idp.pipeline import run_extraction

        result = run_extraction(b"fake-scanned-pdf", "application/pdf")

    assert result.has_text_layer is False
    assert result.ocr_used is True
    assert result.ocr_confidence == pytest.approx(0.88)
    assert result.text == "scanned receipt text"
    mock_ocr.assert_called()


def test_image_mime_always_uses_ocr():
    """Any image MIME type → OCR path, page_count=1."""
    with patch("app.modules.idp.ocr.ocr_image", return_value=("TOTAL RM 42.00", 0.92)) as mock_ocr:
        if "app.modules.idp.pipeline" in sys.modules:
            del sys.modules["app.modules.idp.pipeline"]
        from app.modules.idp.pipeline import run_extraction

        result = run_extraction(b"fake-png-bytes", "image/jpeg")

    assert result.page_count == 1
    assert result.ocr_used is True
    assert result.has_text_layer is False
    assert result.ocr_confidence == pytest.approx(0.92)
    mock_ocr.assert_called_once()


def test_ocr_confidence_is_mean_of_pages():
    """Multi-page scanned PDF: ocr_confidence is the mean over all pages."""
    parsing_mock = _make_parsing_mock(text="  ", usable=False, page_count=2)
    confidences = [0.8, 0.9]
    call_idx = {"n": 0}

    def _ocr_side(png_bytes):
        c = confidences[call_idx["n"] % len(confidences)]
        call_idx["n"] += 1
        return (f"page text {call_idx['n']}", c)

    with patch.dict(sys.modules, {"app.modules.idp.parsing": parsing_mock}), \
         patch("app.modules.idp.ocr.ocr_image", side_effect=_ocr_side):
        if "app.modules.idp.pipeline" in sys.modules:
            del sys.modules["app.modules.idp.pipeline"]
        from app.modules.idp.pipeline import run_extraction

        result = run_extraction(b"fake-2page-pdf", "application/pdf")

    assert result.page_count == 2
    assert result.ocr_used is True
    assert result.ocr_confidence == pytest.approx(0.85, abs=0.01)  # mean of 0.8 + 0.9


# ---------------------------------------------------------------------------
# DocumentOut schema carries extractedText (camelCase contract)
# ---------------------------------------------------------------------------


def test_document_out_has_extracted_text_camel():
    """DocumentOut must serialise extracted_text → extractedText."""
    import re
    from app.modules.files.schemas import DocumentOut

    CAMEL_RE = re.compile(r"^[a-z][a-zA-Z0-9]*$")
    for field_name in DocumentOut.model_fields:
        alias = DocumentOut.model_config.get("alias_generator", lambda x: x)(field_name)
        assert CAMEL_RE.match(alias), f"DocumentOut.{field_name} → '{alias}' not camelCase"

    assert "extracted_text" in DocumentOut.model_fields
