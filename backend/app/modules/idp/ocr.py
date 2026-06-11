"""OCR fallback (RapidOCR / ONNXRuntime).

Used ONLY when a document has no usable text layer (scanned PDFs, images) — the
expensive path the cost cascade tries to avoid. The model is loaded lazily as a
process-wide singleton because initialisation is heavy; one worker process pays
that cost once.

Heavy imports are deferred so this module can be imported in environments that
don't have the worker extras installed — tests mock :func:`ocr_image`.
"""

_engine = None


def _get_engine():
    global _engine
    if _engine is None:
        from rapidocr_onnxruntime import RapidOCR
        _engine = RapidOCR()
    return _engine


def ocr_image(png_bytes: bytes) -> tuple[str, float]:
    """Run OCR on a single PNG image.

    Returns ``(text, confidence)`` where ``confidence`` is the mean per-line score
    in ``[0.0, 1.0]`` (``0.0`` when nothing is detected).
    """
    import io

    import numpy as np
    from PIL import Image

    image = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    result, _elapsed = _get_engine()(np.array(image))
    if not result:
        return "", 0.0

    # RapidOCR returns a list of [box, text, score] triples.
    lines = [item[1] for item in result]
    scores = [float(item[2]) for item in result]
    text = "\n".join(lines)
    confidence = sum(scores) / len(scores) if scores else 0.0
    return text, confidence
