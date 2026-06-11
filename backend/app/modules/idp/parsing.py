"""PDF parsing helpers (PyMuPDF).

Two responsibilities, both cheap and deterministic:
- Read the embedded **text layer** of digital PDFs for free (the ~85% case — no AI,
  no OCR). This is the single biggest cost lever in the pipeline.
- **Rasterize** pages to PNG when there is no usable text layer, so the OCR fallback
  (and, later, the VLM) has an image to work on.

``fitz`` is the import name for PyMuPDF.
"""

import re

import fitz  # PyMuPDF

# 200 DPI is a good accuracy/cost balance for OCR.
_OCR_DPI = 200
_ZOOM = _OCR_DPI / 72.0  # PDF user space is 72 DPI


def open_pdf(data: bytes) -> fitz.Document:
    """Open PDF bytes as a PyMuPDF document (caller is responsible for closing)."""
    return fitz.open(stream=data, filetype="pdf")


def extract_text_layer(doc: fitz.Document) -> str:
    """Concatenate the embedded text of every page (empty for scanned PDFs)."""
    return "\n".join(page.get_text("text") for page in doc)


def has_usable_text_layer(text: str, page_count: int) -> bool:
    """Heuristic: does this PDF carry a real text layer, or is it scanned?

    Scanned PDFs return little-to-no text from ``get_text``. We require a small
    amount of non-whitespace text that scales with page count, so a mostly-blank
    extraction falls through to OCR.
    """
    non_whitespace = len(re.sub(r"\s+", "", text))
    return non_whitespace >= max(16, 8 * max(page_count, 1))


def rasterize_page(page: fitz.Page) -> bytes:
    """Render a single PDF page to PNG bytes at the OCR resolution.

    Reused by the VLM milestone to produce page images.
    """
    pix = page.get_pixmap(matrix=fitz.Matrix(_ZOOM, _ZOOM))
    return pix.tobytes("png")
