"""VLM-based structured extraction (Milestone E).

Cost-cascade strategy that respects a small model context window:

- **Text mode** (digital PDFs with a usable text layer): send the extracted text
  only — no images. Cheapest and most reliable; the text layer is already perfect.
- **Vision mode** (scanned PDFs / images with no text layer): render pages to PNG
  at a modest DPI, resize, and send as image parts.

Both modes are **budget-aware**: input is chunked so each call fits within
``settings.vlm_max_model_len`` (input + output). Multi-chunk results are merged
(``line_items`` concatenated across pages, header fields reconciled).

The stage is **opt-in by config**: when ``settings.vlm_base_url`` is empty it
returns a ``skipped`` outcome immediately so the rest of the pipeline is unaffected.

All heavy imports (openai, PIL, parsing) are deferred so the module imports cleanly
in environments without the worker extras — unit tests patch ``openai.OpenAI``.
"""

import base64
import io
import json
import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ValidationError

from app.core.config import settings

logger = logging.getLogger(__name__)

# Document type enum — must match frontend ProcessingStatus and Document.document_type.
_VALID_TYPES = {"invoice", "receipt", "contract", "report", "letter", "form", "other"}

# Scalar field keys whose value should come from the LAST page (grand total lives there).
_TOTAL_KEYS = ("total", "amount_due", "grand_total", "balance_due", "amount_payable")

_SYSTEM_PROMPT = (
    "You are a document extraction engine. Return ONLY a JSON object: "
    "{\"documentType\":\"...\",\"confidence\":0.0,\"fields\":{...}}.\n"
    "documentType: invoice|receipt|contract|report|letter|form|other.\n"
    "confidence: 0.0-1.0 (your certainty).\n"
    "fields rules:\n"
    "- Header fields (vendor, invoice_number, invoice_date, total_amount, currency, "
    "buyer, buyer_address, vendor_address, gst, grand_total, etc.) on first occurrence.\n"
    "- line_items: extract EVERY product/service row visible — do not skip any. "
    "Use compact keys only: code, description, qty, unit_price, amount. "
    "Omit Chinese text, secondary descriptions, and empty fields.\n"
    "Amounts as numbers. Dates as ISO 8601. Output JSON only — no prose, no fences."
)

# Two-phase prompts: split header extraction from line-item extraction so each
# call's output budget is fully dedicated to its task.
_HEADER_PROMPT = (
    "Extract document header metadata ONLY — do NOT include line_items. "
    "Return {\"documentType\":\"...\",\"confidence\":0.0,\"fields\":{...}}. "
    "fields: vendor, invoice_number, invoice_date, total_amount, currency, "
    "buyer, buyer_address, vendor_address, gst, grand_total, terms_conditions. "
    "documentType: invoice|receipt|contract|report|letter|form|other. "
    "JSON only — no prose, no fences."
)

_LINE_ITEMS_PROMPT = (
    "Extract ALL line items from this document section. "
    "Return {\"documentType\":\"invoice\",\"confidence\":0.9,\"fields\":{\"line_items\":[...]}}. "
    "Each item: {\"code\":\"...\",\"description\":\"...\",\"qty\":N,\"unit_price\":N,\"amount\":N}. "
    "Include EVERY product/service row visible — do not skip any. "
    "Omit header fields, Chinese text, empty fields. "
    "JSON only — no prose, no fences."
)

# --- Budget tuning (empirically measured on Qwen3-VL-4B against real invoice PDFs) ---
# Fixed overhead (system prompt + chat template + user wrapper): measured 182 tokens.
# Invoice content tokenisation rate: 1.35–1.44 chars/token (numbers/amounts tokenise densely).
# Use the conservative end; _MARGIN_TOKENS absorbs any model-version drift.
_CONTENT_CHARS_PER_TOKEN = 1.35   # measured 1.35-1.44; use conservative end
_FIXED_OVERHEAD_TOKENS = 200       # measured 182 tokens + 18-token buffer
_EST_IMAGE_TOKENS = 340            # ~tokens a 512px page costs the VLM processor
_MARGIN_TOKENS = 50                # additional safety headroom beyond the measured overhead
_MIN_TEXT_CHARS = 8                # below this, treat as "no text" and use vision
_VLM_MAX_SIDE = 512                # longest image side in px
# Backward-compat alias used by _estimate_tokens
_CHARS_PER_TOKEN = _CONTENT_CHARS_PER_TOKEN


@dataclass
class VlmExtraction:
    """Structured output from the VLM stage."""

    document_type: str
    fields: dict[str, Any]
    confidence: float
    model_name: str
    raw: str = field(repr=False)  # raw model output for debugging


@dataclass
class VlmOutcome:
    """Result envelope so callers can persist *why* extraction produced nothing.

    Exactly one of ``extraction`` (success) or ``error`` (failure reason) is set;
    ``error`` is ``None`` for a plain skip (no endpoint configured). Token counts
    are 0 when no VLM call was actually made (skip, or a pre-call error) — callers
    use these to meter spend against the per-tenant budget (``app.core.ai_budget``).
    """

    extraction: VlmExtraction | None
    mode: str            # "text" | "vision" | "skipped"
    error: str | None    # failure reason when extraction is None (None == clean skip)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class _VlmOut(BaseModel):
    """Validates the shape the VLM is asked to return."""

    documentType: str = "other"
    confidence: float = 0.0
    fields: dict[str, Any] = {}


# ---------------------------------------------------------------------------
# Budget helpers
# ---------------------------------------------------------------------------

def _estimate_tokens(text: str) -> int:
    return int(len(text) / _CHARS_PER_TOKEN)


def _input_budget_tokens() -> int:
    """Tokens available for input content, after fixed overhead + output reservation."""
    budget = settings.vlm_max_model_len - settings.vlm_max_output_tokens - _FIXED_OVERHEAD_TOKENS - _MARGIN_TOKENS
    return max(256, budget)


def _text_chunk_chars() -> int:
    return int(_input_budget_tokens() * _CONTENT_CHARS_PER_TOKEN)


def _images_per_call() -> int:
    return max(1, min(2, _input_budget_tokens() // _EST_IMAGE_TOKENS))


# ---------------------------------------------------------------------------
# Image rendering
# ---------------------------------------------------------------------------

def _resize_for_vlm(png_bytes: bytes, max_side: int = _VLM_MAX_SIDE) -> bytes:
    """Downscale *png_bytes* so the longest side is at most *max_side* pixels.

    Preserves aspect ratio. On failure logs and returns the original bytes — the
    PDF path also caps size at the source (low render DPI), so this is a second guard.
    """
    try:
        from PIL import Image

        img = Image.open(io.BytesIO(png_bytes))
        w, h = img.size
        if max(w, h) <= max_side:
            return png_bytes
        ratio = max_side / max(w, h)
        img = img.resize((max(1, int(w * ratio)), max(1, int(h * ratio))), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception as exc:  # noqa: BLE001 — never let resizing break extraction
        logger.warning("Image resize failed (%s) — using source bytes; may inflate tokens", exc)
        return png_bytes


def render_page_images(
    file_bytes: bytes,
    mime_type: str,
    max_pages: int,
    dpi: int | None = None,
) -> list[bytes]:
    """Return resized PNG bytes for up to ``max_pages`` pages of the document.

    Image MIMEs return the (resized) input as a single page. PDFs rasterise at
    ``dpi`` (default ``settings.vlm_render_dpi``) — low enough to keep image tokens
    down — then resize to :data:`_VLM_MAX_SIDE`.
    """
    _IMAGE_MIMES = {"image/jpeg", "image/png", "image/webp", "image/tiff"}
    render_dpi = dpi or settings.vlm_render_dpi

    if mime_type in _IMAGE_MIMES:
        return [_resize_for_vlm(file_bytes)]

    from app.modules.idp import parsing

    doc = parsing.open_pdf(file_bytes)
    try:
        pages_to_render = min(doc.page_count, max(1, max_pages))
        images: list[bytes] = []
        for i, page in enumerate(doc):
            if i >= pages_to_render:
                break
            images.append(_resize_for_vlm(parsing.rasterize_page(page, dpi=render_dpi)))
        return images
    finally:
        doc.close()


# ---------------------------------------------------------------------------
# VLM call + parsing
# ---------------------------------------------------------------------------

def _make_client() -> Any:
    from openai import OpenAI

    return OpenAI(
        base_url=settings.vlm_base_url,
        api_key=settings.vlm_api_key or "none",
        timeout=settings.vlm_request_timeout,
    )


def _usage_tokens(resp: Any) -> dict[str, int]:
    """Best-effort token usage from an OpenAI-style response.

    Tolerant of a missing or mocked ``.usage`` (e.g. test doubles that don't set
    it) — anything that isn't an int is treated as 0 rather than raising.
    """
    usage = getattr(resp, "usage", None)

    def _int(value: Any) -> int:
        return value if isinstance(value, int) else 0

    return {
        "prompt_tokens": _int(getattr(usage, "prompt_tokens", None)),
        "completion_tokens": _int(getattr(usage, "completion_tokens", None)),
        "total_tokens": _int(getattr(usage, "total_tokens", None)),
    }


def _empty_usage() -> dict[str, int]:
    return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}


def _accumulate(total: dict[str, int], usage: dict[str, int]) -> None:
    for key in total:
        total[key] += usage[key]


def _call_vlm(
    client: Any,
    content: list[dict[str, Any]],
    system_prompt: str | None = None,
) -> tuple[str, dict[str, int]]:
    """One chat completion. Raises on transport errors (caller handles).

    Returns ``(text, usage)`` — ``usage`` has ``prompt_tokens``/``completion_tokens``/
    ``total_tokens`` (0 for any the server didn't report).
    """
    resp = client.chat.completions.create(
        model=settings.vlm_model,
        messages=[
            {"role": "system", "content": system_prompt if system_prompt is not None else _SYSTEM_PROMPT},
            {"role": "user", "content": content},
        ],
        max_tokens=settings.vlm_max_output_tokens,
        temperature=0,
    )
    text = (resp.choices[0].message.content or "").strip()
    return text, _usage_tokens(resp)


def _text_content(text_chunk: str) -> list[dict[str, Any]]:
    return [{"type": "text", "text": f"Document text:\n{text_chunk}\n\nReturn the JSON object."}]


def _vision_content(images: list[bytes], hint: str | None) -> list[dict[str, Any]]:
    content: list[dict[str, Any]] = []
    for png in images:
        b64 = base64.b64encode(png).decode("ascii")
        content.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}})
    if hint:
        content.append({"type": "text", "text": f"OCR text (may be noisy):\n{hint[:400]}"})
    content.append({"type": "text", "text": "Extract all fields and return the JSON object."})
    return content


def _normalize(parsed: Any) -> dict[str, Any] | None:
    """Coerce a parsed object into the ``{documentType, confidence, fields}`` shape.

    Small models often return flat fields without the wrapper — fold those into
    ``fields`` so the data isn't dropped.
    """
    if not isinstance(parsed, dict):
        return None
    if isinstance(parsed.get("fields"), dict):
        return parsed
    known = {"documenttype", "document_type", "confidence"}
    fields = {k: v for k, v in parsed.items() if k.lower() not in known}
    return {
        "documentType": parsed.get("documentType", parsed.get("document_type", "other")),
        "confidence": parsed.get("confidence", 0.0),
        "fields": fields,
    }


def _to_extraction(parsed: Any, raw: str) -> VlmExtraction | None:
    normalized = _normalize(parsed)
    if normalized is None:
        return None
    try:
        out = _VlmOut.model_validate(normalized)
    except ValidationError as exc:
        logger.warning("VLM output failed validation: %s", exc)
        return None
    doc_type = out.documentType.lower()
    if doc_type not in _VALID_TYPES:
        doc_type = "other"
    return VlmExtraction(
        document_type=doc_type,
        fields=out.fields,
        confidence=max(0.0, min(1.0, out.confidence)),
        model_name=settings.vlm_model,
        raw=raw,
    )


def _tolerant_parse(text: str | None) -> dict[str, Any] | None:
    """Parse model output that may be fenced, prose-wrapped, or truncated."""
    if not text:
        return None
    s = text.strip()
    # Strip ```json ... ``` fences.
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z0-9]*\s*", "", s)
        s = re.sub(r"\s*```$", "", s).strip()

    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass

    start = s.find("{")
    if start == -1:
        return None
    candidate = s[start:]

    # Balanced: try the largest {...} span.
    end = candidate.rfind("}")
    if end != -1:
        try:
            return json.loads(candidate[: end + 1])
        except json.JSONDecodeError:
            pass

    # Truncation repair: close any open strings/brackets left by the token cap.
    repaired = _repair_truncated_json(candidate)
    if repaired is not None:
        try:
            return json.loads(repaired)
        except json.JSONDecodeError:
            pass
    return None


def _repair_truncated_json(s: str) -> str | None:
    """Best-effort close of a JSON object cut off mid-stream by the output limit."""
    stack: list[str] = []
    in_str = False
    escape = False
    for ch in s:
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            stack.append(ch)
        elif ch in "}]":
            if stack:
                stack.pop()

    res = s
    if in_str:
        res += '"'
    res = res.rstrip()
    # Drop a dangling comma or an incomplete trailing "key": pair / number.
    res = re.sub(r",\s*$", "", res)
    # Drop "key": with no value yet.
    res = re.sub(r'[,{[]\s*"[^"]*"\s*:\s*$', lambda m: m.group(0)[0], res)
    # Drop an unclosed key string (truncated before the closing quote).
    res = re.sub(r'[,{[]\s*"[^"]*$', lambda m: m.group(0)[0], res)
    # Drop a closed key string with no colon+value (happens when in_str fix added the closing
    # quote to a key that was truncated mid-name, e.g. ,"descriptio" or ,"amo").
    res = re.sub(r'[,{[]\s*"[^"]*"\s*$', lambda m: m.group(0)[0], res)
    res = re.sub(r",\s*$", "", res)  # second pass after key removal
    for ch in reversed(stack):
        res += "}" if ch == "{" else "]"
    return res or None


# ---------------------------------------------------------------------------
# Chunked extraction + merge
# ---------------------------------------------------------------------------

def _run_chunks(
    client: Any, contents: list[list[dict[str, Any]]]
) -> tuple[VlmExtraction | None, str | None, dict[str, int]]:
    """Call the VLM once per content chunk, parse each, merge successes.

    Returns ``(merged_extraction, None, usage)`` on any success, else
    ``(None, reason, usage)``. ``usage`` totals tokens across every attempted call.
    Stops early on a transport error (it will only repeat against a dead endpoint).
    """
    parts: list[VlmExtraction] = []
    last_err: str | None = None
    usage = _empty_usage()
    for idx, content in enumerate(contents):
        try:
            raw, call_usage = _call_vlm(client, content)
        except Exception as exc:  # noqa: BLE001 — transport/timeout; report and stop
            last_err = f"{type(exc).__name__}: {exc}"[:300]
            logger.warning("VLM call failed on chunk %d/%d: %s", idx + 1, len(contents), exc, exc_info=True)
            break
        _accumulate(usage, call_usage)
        parsed = _tolerant_parse(raw)
        if parsed is None:
            last_err = "unparseable model output"
            logger.warning("VLM unparseable output on chunk %d (%d chars): %.300s", idx + 1, len(raw), raw)
            continue
        ext = _to_extraction(parsed, raw)
        if ext is not None:
            parts.append(ext)
    if parts:
        return _merge_extractions(parts), None, usage
    return None, last_err or "no output", usage


def _chunk_text(text: str) -> list[str]:
    """Split *text* into line-aligned chunks within the per-call char budget."""
    budget = _text_chunk_chars()
    if len(text) <= budget:
        return [text]
    chunks: list[str] = []
    cur = ""
    for line in text.splitlines(keepends=True):
        if cur and len(cur) + len(line) > budget:
            chunks.append(cur)
            cur = ""
            if len(chunks) >= settings.vlm_max_chunk_calls:
                return chunks
        cur += line
    if cur and len(chunks) < settings.vlm_max_chunk_calls:
        chunks.append(cur)
    return chunks


def _batch_images(images: list[bytes]) -> list[list[bytes]]:
    """Group page images into per-call batches, bounded by the chunk-call cap."""
    per_call = _images_per_call()
    images = images[: per_call * settings.vlm_max_chunk_calls]
    return [images[i : i + per_call] for i in range(0, len(images), per_call)]


def _merge_extractions(parts: list[VlmExtraction]) -> VlmExtraction:
    """Merge per-chunk extractions: concatenate lists, reconcile scalars."""
    if len(parts) == 1:
        return parts[0]

    types = [p.document_type for p in parts if p.document_type != "other"]
    doc_type = Counter(types).most_common(1)[0][0] if types else "other"
    confidence = sum(p.confidence for p in parts) / len(parts)

    merged: dict[str, Any] = {}
    for part in parts:
        for key, value in part.fields.items():
            if isinstance(value, list):
                existing = merged.get(key)
                if isinstance(existing, list):
                    existing.extend(value)
                else:
                    merged[key] = list(value)
                continue
            if _is_empty(value):
                continue
            if any(t in key.lower() for t in _TOTAL_KEYS):
                merged[key] = value  # last non-empty wins (grand total on final page)
            elif _is_empty(merged.get(key)):
                merged[key] = value  # first non-empty wins for everything else

    raw = "\n---\n".join(p.raw for p in parts)
    return VlmExtraction(doc_type, merged, confidence, parts[0].model_name, raw)


def _is_empty(value: Any) -> bool:
    return value in (None, "", [], {})


# ---------------------------------------------------------------------------
# Two-phase text extraction
# ---------------------------------------------------------------------------

def _extract_two_phase(
    text: str, client: Any
) -> tuple[VlmExtraction | None, str | None, dict[str, int]]:
    """Header extraction in one call + exhaustive line-item extraction per chunk.

    Separating the two concerns lets the full output-token budget go to
    line items on Phase 2 calls, so a 70-item invoice doesn't get truncated
    after the first 4 items. ``usage`` totals tokens across every attempted call.
    """
    parts: list[VlmExtraction] = []
    last_err: str | None = None
    usage = _empty_usage()
    chunks = _chunk_text(text)
    remaining_calls = settings.vlm_max_chunk_calls

    # Phase 1 — header fields (first chunk only, header-only prompt)
    if chunks and remaining_calls > 0:
        header_content = [{"type": "text", "text": (
            f"Document text:\n{chunks[0]}\n\n"
            "Extract header fields only (no line_items). Return the JSON object."
        )}]
        try:
            raw, call_usage = _call_vlm(client, header_content, _HEADER_PROMPT)
            _accumulate(usage, call_usage)
            parsed = _tolerant_parse(raw)
            if parsed:
                ext = _to_extraction(parsed, raw)
                if ext:
                    ext.fields.pop("line_items", None)  # keep output budget free of items
                    parts.append(ext)
        except Exception as exc:  # noqa: BLE001
            last_err = f"header: {exc}"[:200]
            logger.warning("Header extraction failed: %s", exc)
        remaining_calls -= 1

    # Phase 2 — line items (all chunks, line-items-only prompt)
    for idx, chunk in enumerate(chunks[:remaining_calls]):
        item_content = [{"type": "text", "text": (
            f"Invoice section:\n{chunk}\n\n"
            "Extract ALL line items visible (every product/service row). "
            "Return the JSON object."
        )}]
        try:
            raw, call_usage = _call_vlm(client, item_content, _LINE_ITEMS_PROMPT)
            _accumulate(usage, call_usage)
        except Exception as exc:  # noqa: BLE001
            last_err = f"items chunk {idx}: {exc}"[:200]
            logger.warning("Line items chunk %d/%d failed: %s", idx + 1, len(chunks), exc)
            break
        parsed = _tolerant_parse(raw)
        if parsed is None:
            logger.warning("Unparseable line items output chunk %d", idx + 1)
            continue
        ext = _to_extraction(parsed, raw)
        if ext is not None:
            parts.append(ext)

    if parts:
        return _merge_extractions(parts), None, usage
    return None, last_err or "no output", usage


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def extract_structured(
    file_bytes: bytes,
    mime_type: str,
    extracted_text: str | None,
    has_text_layer: bool,
) -> VlmOutcome:
    """Dispatch to text or vision mode and return a :class:`VlmOutcome`.

    Text mode when the document has a usable text layer (cheap, reliable); vision
    mode otherwise. Never raises — transport/parse errors become ``error`` reasons.
    """
    if not settings.vlm_base_url:
        return VlmOutcome(None, "skipped", None)

    text = (extracted_text or "").strip()
    use_text = bool(has_text_layer and len(text) >= _MIN_TEXT_CHARS)
    mode = "text" if use_text else "vision"
    usage = _empty_usage()

    try:
        client = _make_client()
        if use_text:
            extraction, err, usage = _extract_two_phase(text, client)
        else:
            images = render_page_images(file_bytes, mime_type, settings.vlm_max_pages)
            if not images:
                return VlmOutcome(None, mode, "no page images to send")
            batches = _batch_images(images)
            contents = [_vision_content(b, text if i == 0 else None) for i, b in enumerate(batches)]
            extraction, err, usage = _run_chunks(client, contents)
    except Exception as exc:  # noqa: BLE001 — isolate the whole stage
        reason = f"{type(exc).__name__}: {exc}"[:500]
        logger.warning("VLM %s-mode extraction errored: %s", mode, exc, exc_info=True)
        return VlmOutcome(None, mode, reason, **usage)

    if extraction is None:
        return VlmOutcome(None, mode, err or "no output", **usage)
    logger.info(
        "VLM %s-mode ok: type=%s confidence=%.2f fields=%d",
        mode, extraction.document_type, extraction.confidence, len(extraction.fields),
    )
    return VlmOutcome(extraction, mode, None, **usage)
