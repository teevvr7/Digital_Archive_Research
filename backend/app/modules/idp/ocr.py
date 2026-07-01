import logging
import io

logger = logging.getLogger(__name__)

_engine = None


def _get_engine():
    global _engine
    if _engine is None:
        try:
            from rapidocr_onnxruntime import RapidOCR
            _engine = RapidOCR()
        except Exception as e:
            logger.warning(
                "Failed to initialize local OCR engine (ONNX Runtime / RapidOCR): %s. "
                "Local OCR will be disabled.",
                e
            )
            _engine = False
    return _engine if _engine is not False else None


def ocr_image(png_bytes: bytes) -> tuple[str, float]:
    """Run OCR on a single PNG image.

    Returns ``(text, confidence)`` where ``confidence`` is the mean per-line score
    in ``[0.0, 1.0]`` (``0.0`` when nothing is detected).
    """
    import numpy as np
    from PIL import Image

    engine = _get_engine()
    if engine is None:
        logger.warning("Local OCR requested but engine is unavailable. Returning empty text.")
        return "", 0.0

    image = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    try:
        result, _elapsed = engine(np.array(image))
    except Exception as e:
        logger.error("Error during local OCR execution: %s", e)
        return "", 0.0

    if not result:
        return "", 0.0

    # RapidOCR returns a list of [box, text, score] triples.
    lines = [item[1] for item in result]
    scores = [float(item[2]) for item in result]
    text = "\n".join(lines)
    confidence = sum(scores) / len(scores) if scores else 0.0
    return text, confidence

