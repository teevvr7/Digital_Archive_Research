"""IDP text-extraction orchestrator.

Implements the cost cascade:
  1. PDF with text layer  → free PyMuPDF read (the ~85% case — no AI, no cost).
  2. PDF without text layer → rasterize each page → RapidOCR (CPU, no GPU).
  3. Image (JPEG/PNG/…) → RapidOCR directly, page_count = 1.

After text extraction, :func:`run_ai_extraction` sends page images to the configured
VLM endpoint for structured field extraction (Milestone E). It returns ``None`` when
no endpoint is configured so the pipeline degrades gracefully.
"""

import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

_IMAGE_MIMES = {"image/jpeg", "image/png", "image/webp", "image/tiff"}


def run_ai_extraction(
    db,
    doc,
    file_bytes: bytes,
    mime_type: str,
    extracted_text: str | None,
    has_text_layer: bool,
) -> "VlmOutcome":
    """Run the VLM structured-extraction stage after text/OCR.

    Dispatches dynamically between the teammate's default cascade and your custom
    paddle_qwen pipeline based on document configurations in the database.
    """
    from app.core.config import settings
    from app.models.document_type import DocumentType
    from app.models.document_template import DocumentTemplate

    strategy = "default"
    custom_prompt = None

    if doc.template_id:
        template = db.get(DocumentTemplate, doc.template_id)
        if template:
            strategy = template.extraction_method
            custom_prompt = template.field_mappings.get("_prompt") if isinstance(template.field_mappings, dict) else None
    elif doc.document_type_id:
        doc_type = db.get(DocumentType, doc.document_type_id)
        if doc_type:
            strategy = doc_type.extraction_method
            custom_prompt = doc_type.json_schema.get("_prompt") if isinstance(doc_type.json_schema, dict) else None
    else:
        doc_type = db.query(DocumentType).filter(
            DocumentType.name == doc.document_type,
            (DocumentType.tenant_id == doc.tenant_id) | (DocumentType.tenant_id.is_(None))
        ).first()
        if doc_type:
            strategy = doc_type.extraction_method
            custom_prompt = doc_type.json_schema.get("_prompt") if isinstance(doc_type.json_schema, dict) else None

    if strategy == "paddle_qwen":
        logger.info("Executing custom Paddle-Qwen IDP strategy for document %s", doc.id)
        from app.modules.idp.paddle_qwen import run_paddle_ocr_prediction, extract_from_ocr_text, validate_extraction
        from app.modules.idp.extraction import VlmExtraction, VlmOutcome
        
        t0 = time.perf_counter()
        import tempfile
        import os
        from app.modules.idp.parsing import open_pdf, rasterize_page
        
        try:
            ocr_text = ""
            if mime_type == "application/pdf":
                pdf_doc = open_pdf(file_bytes)
                try:
                    pages_to_render = min(pdf_doc.page_count, max(1, settings.vlm_max_pages))
                    page_texts = []
                    for i in range(pages_to_render):
                        page = pdf_doc[i]
                        png_bytes = rasterize_page(page, dpi=settings.vlm_render_dpi)
                        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                            tmp.write(png_bytes)
                            tmp_path = tmp.name
                        try:
                            page_texts.append(run_paddle_ocr_prediction(tmp_path))
                        finally:
                            if os.path.exists(tmp_path):
                                os.remove(tmp_path)
                    ocr_text = "\n\n".join(page_texts)
                finally:
                    pdf_doc.close()
            else:
                with tempfile.NamedTemporaryFile(suffix=f".{mime_type.split('/')[-1]}", delete=False) as tmp:
                    tmp.write(file_bytes)
                    tmp_path = tmp.name
                try:
                    ocr_text = run_paddle_ocr_prediction(tmp_path)
                finally:
                    if os.path.exists(tmp_path):
                        os.remove(tmp_path)
            
            from app.modules.idp.paddle_qwen import clean_ocr_text
            cleaned_text = clean_ocr_text(ocr_text)
            
            extracted_json, raw_content = extract_from_ocr_text(cleaned_text, custom_prompt)
            validated_json = validate_extraction(extracted_json)
            
            elapsed = time.perf_counter() - t0
            
            # Heuristic: 0.9 if validation is completely green
            confidence = 0.9 if not validated_json.get("requires_human_review", False) else 0.4
            
            extraction = VlmExtraction(
                document_type=validated_json.get("document_details", {}).get("document_type", "other"),
                fields=validated_json,
                confidence=confidence,
                model_name=settings.qwen_llm_model,
                raw=raw_content
            )
            return VlmOutcome(extraction, "text_via_paddle", None)
            
        except Exception as exc:
            logger.exception("Custom Paddle-Qwen IDP strategy errored: %s", exc)
            return VlmOutcome(None, "text_via_paddle", str(exc))

    # Teammate's default cascade
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
