"""IDP text-extraction orchestrator.

Implements the cost cascade for the universal ingestion baseline:
  1. PDF with text layer  → free PyMuPDF read (the ~85% case — no AI, no cost).
  2. PDF without text layer → rasterize each page → RapidOCR (CPU, no GPU).
  3. Image (JPEG/PNG/…) → RapidOCR directly, page_count = 1.
  4. Office (docx/xlsx/pptx) → direct text extraction via python-docx/openpyxl/python-pptx.
  5. Plain text (txt/csv/md) → decode directly.
  6. Email (.eml) → stdlib ``email`` header + body extraction.

None of tiers 4-6 involve OCR or AI — they're free, deterministic reads, same
cost tier as tier 1. ``page_count`` is 1 for all of them (no native concept of
pages).

After text extraction, :func:`run_ai_extraction` sends page images to the configured
VLM endpoint for structured field extraction (Milestone E). It returns ``None`` when
no endpoint is configured so the pipeline degrades gracefully.
"""

import logging
import time
from dataclasses import dataclass, field

from app.modules.idp import mimetype

logger = logging.getLogger(__name__)

_IMAGE_MIMES = {"image/jpeg", "image/png", "image/webp", "image/tiff"}


def run_ai_extraction(
    file_bytes: bytes,
    mime_type: str,
    extracted_text: str | None,
    has_text_layer: bool,
) -> "VlmOutcome":
    """Run the VLM structured-extraction stage after text/OCR.

    Returns a :class:`~app.modules.idp.extraction.VlmOutcome` carrying either the
    extraction, or the reason it produced nothing (failure) / a clean skip.
    Never raises. Digital docs go through text mode, scans through vision mode.
    """
    from app.core.config import settings

    # Early exit: never import extraction/parsing when there's no endpoint —
    # keeps tests offline and avoids loading PyMuPDF in the no-VLM path.
    if not settings.vlm_base_url:
        logger.debug("VLM_BASE_URL not set — ai_extraction stage skipped")
        from app.modules.idp.extraction import VlmOutcome
        return VlmOutcome(None, "skipped", None)

    from app.modules.idp.extraction import extract_structured

    t0 = time.perf_counter()
    outcome = extract_structured(file_bytes, mime_type, extracted_text, has_text_layer)
    elapsed = time.perf_counter() - t0

    if outcome.extraction is None:
        logger.info(
            "AI extraction produced no data (mode=%s, reason=%s, %.2fs)",
            outcome.mode, outcome.error, elapsed,
        )
    else:
        ext = outcome.extraction
        logger.info(
            "AI extraction complete: mode=%s type=%s confidence=%.2f fields=%d (%.2fs)",
            outcome.mode, ext.document_type, ext.confidence, len(ext.fields), elapsed,
        )
    return outcome


# Forward-declare the type for the annotation above (avoids a circular import
# at module level when extraction.py is not yet imported).
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from app.modules.idp.extraction import VlmOutcome


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
    if mime_type == "application/pdf":
        return _extract_pdf(file_bytes)
    if mime_type in _IMAGE_MIMES:
        return _extract_image(file_bytes)
    if mime_type in mimetype.OFFICE_MIMES or mime_type in mimetype.TEXT_FAMILY_MIMES:
        return _extract_office_or_text(file_bytes, mime_type)
    if mime_type == mimetype.MIME_EML:
        return _extract_email(file_bytes)
    if mime_type == mimetype.MIME_XML:
        return _extract_xml(file_bytes)
    raise ValueError(f"Unsupported mime type: {mime_type}")


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


def _extract_office_or_text(file_bytes: bytes, mime_type: str) -> ExtractionResult:
    from app.modules.idp import office_parsing

    t0 = time.perf_counter()
    extractor = {
        mimetype.MIME_DOCX: office_parsing.extract_docx_text,
        mimetype.MIME_XLSX: office_parsing.extract_xlsx_text,
        mimetype.MIME_PPTX: office_parsing.extract_pptx_text,
        mimetype.MIME_TXT: office_parsing.extract_plain_text,
        mimetype.MIME_CSV: office_parsing.extract_plain_text,
        mimetype.MIME_MD: office_parsing.extract_plain_text,
    }[mime_type]
    text = extractor(file_bytes)
    elapsed = time.perf_counter() - t0
    logger.info("Office/text extract (%s): %.3fs, chars=%d", mime_type, elapsed, len(text))

    return ExtractionResult(
        text=text.strip(),
        page_count=1,
        has_text_layer=True,
        ocr_used=False,
        ocr_confidence=None,
    )


def _extract_email(file_bytes: bytes) -> ExtractionResult:
    from app.modules.idp import office_parsing

    t0 = time.perf_counter()
    text = office_parsing.extract_email_text(file_bytes)
    elapsed = time.perf_counter() - t0
    logger.info("Email extract: %.3fs, chars=%d", elapsed, len(text))

    return ExtractionResult(
        text=text.strip(),
        page_count=1,
        has_text_layer=True,
        ocr_used=False,
        ocr_confidence=None,
    )


def _extract_xml(file_bytes: bytes) -> ExtractionResult:
    """UBL invoices (e.g. MyInvois) get a richer text flatten; any other XML
    falls back to the generic plain-text decode, same as .txt/.csv/.md."""
    from app.modules.idp import office_parsing, ubl_invoice

    t0 = time.perf_counter()
    if ubl_invoice.is_ubl_invoice(file_bytes):
        text = ubl_invoice.extract_ubl_text(file_bytes)
    else:
        text = office_parsing.extract_plain_text(file_bytes)
    elapsed = time.perf_counter() - t0
    logger.info("XML extract: %.3fs, chars=%d", elapsed, len(text))

    return ExtractionResult(
        text=text.strip(),
        page_count=1,
        has_text_layer=True,
        ocr_used=False,
        ocr_confidence=None,
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
