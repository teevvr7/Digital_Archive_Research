"""IDP text-extraction orchestrator.

Implements the cost cascade for Milestone C:
  1. PDF with text layer  → free PyMuPDF read (the ~85% case — no AI, no cost).
  2. PDF without text layer → rasterize each page → RapidOCR (CPU, no GPU).
  3. Image (JPEG/PNG/…) → RapidOCR directly, page_count = 1.

Returns an :class:`ExtractionResult` dataclass that ``jobs.py`` persists to the DB.
The VLM step (ai_extraction stage, next milestone) will consume ``.extracted_text``
and the page images as inputs.
"""

import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

_IMAGE_MIMES = {"image/jpeg", "image/png", "image/webp", "image/tiff"}


@dataclass
class ExtractionResult:
    text: str
    page_count: int
    has_text_layer: bool
    ocr_used: bool
    ocr_confidence: float | None


def run_extraction(file_bytes: bytes, mime_type: str) -> ExtractionResult:
    """Extract text from any supported file type.

    Logs per-stage timing so the caller can evaluate OCR performance.
    Raises on unrecoverable parse errors (caller should mark document as failed).
    """
    if mime_type in _IMAGE_MIMES:
        return _extract_image(file_bytes)
    return _extract_pdf(file_bytes)


def _extract_image(file_bytes: bytes) -> ExtractionResult:
    from app.modules.idp.ocr import ocr_image

    t0 = time.perf_counter()
    text, confidence = ocr_image(file_bytes)
    elapsed = time.perf_counter() - t0
    logger.info("OCR (image): %.2fs, confidence=%.3f, chars=%d", elapsed, confidence, len(text))

    return ExtractionResult(
        text=text,
        page_count=1,
        has_text_layer=False,
        ocr_used=True,
        ocr_confidence=confidence,
    )


def _extract_pdf(file_bytes: bytes) -> ExtractionResult:
    from app.modules.idp import parsing
    from app.modules.idp.ocr import ocr_image

    doc = parsing.open_pdf(file_bytes)
    try:
        page_count = doc.page_count

        # --- Try the free text-layer path first ---
        t0 = time.perf_counter()
        raw_text = parsing.extract_text_layer(doc)
        elapsed_text = time.perf_counter() - t0

        if parsing.has_usable_text_layer(raw_text, page_count):
            logger.info(
                "Text-layer (PDF %d pp): %.3fs, chars=%d — OCR skipped",
                page_count,
                elapsed_text,
                len(raw_text),
            )
            return ExtractionResult(
                text=raw_text.strip(),
                page_count=page_count,
                has_text_layer=True,
                ocr_used=False,
                ocr_confidence=None,
            )

        # --- No usable text layer → OCR each page ---
        logger.info(
            "No usable text layer (PDF %d pp, got %d chars) — falling back to OCR",
            page_count,
            len(raw_text.strip()),
        )

        page_texts: list[str] = []
        page_scores: list[float] = []

        for i, page in enumerate(doc):
            t_page = time.perf_counter()
            png = parsing.rasterize_page(page)
            text, conf = ocr_image(png)
            elapsed_page = time.perf_counter() - t_page
            logger.info(
                "  OCR page %d/%d: %.2fs, confidence=%.3f, chars=%d",
                i + 1,
                page_count,
                elapsed_page,
                conf,
                len(text),
            )
            page_texts.append(text)
            page_scores.append(conf)

        combined = "\n\n".join(t for t in page_texts if t)
        mean_conf = sum(page_scores) / len(page_scores) if page_scores else 0.0

        return ExtractionResult(
            text=combined.strip(),
            page_count=page_count,
            has_text_layer=False,
            ocr_used=True,
            ocr_confidence=mean_conf,
        )
    finally:
        doc.close()
