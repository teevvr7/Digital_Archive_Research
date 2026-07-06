"""Thumbnail generation — best-effort, never blocks or fails document processing.

Only PDF and raster images get a real visual thumbnail. Office/text/email
formats have no cheap rendering path without heavy infra (e.g. LibreOffice),
which is out of scope per the root ``CLAUDE.md`` "no heavy infra without
approval" rule — the frontend falls back to a generic type icon for those.
"""

import io
import logging

logger = logging.getLogger(__name__)

_THUMB_MAX_DIM = 320
_THUMB_DPI = 72  # low-res render is plenty for a list/grid thumbnail

_IMAGE_MIMES = {"image/jpeg", "image/png", "image/webp", "image/tiff"}


def generate_thumbnail(file_bytes: bytes, mime_type: str) -> bytes | None:
    """Return PNG thumbnail bytes, or ``None`` when this mime type has no preview.

    Swallows every exception — a thumbnail failure must never fail the
    document, matching the AI-extraction isolation pattern in ``idp/jobs.py``.
    """
    try:
        if mime_type == "application/pdf":
            return _thumbnail_pdf(file_bytes)
        if mime_type in _IMAGE_MIMES:
            return _resize_png(file_bytes)
        return None
    except Exception as exc:
        logger.warning("Thumbnail generation failed (mime=%s): %s", mime_type, exc)
        return None


def _thumbnail_pdf(file_bytes: bytes) -> bytes | None:
    from app.modules.idp import parsing

    doc = parsing.open_pdf(file_bytes)
    try:
        if doc.page_count == 0:
            return None
        png = parsing.rasterize_page(doc[0], dpi=_THUMB_DPI)
    finally:
        doc.close()
    return _resize_png(png)


def _resize_png(data: bytes) -> bytes:
    from PIL import Image

    img = Image.open(io.BytesIO(data))
    img.thumbnail((_THUMB_MAX_DIM, _THUMB_MAX_DIM))
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()
