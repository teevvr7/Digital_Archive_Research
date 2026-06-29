"""Content sniffing — magic bytes only, never the client-declared content-type
or filename extension for the binary/security boundary.

Deliberately has **zero native dependencies** (no ``python-magic``/libmagic):
this codebase has already been burned twice by native binaries misbehaving on
Windows (LiteParse dropped; Tesseract passed over for RapidOCR — see root
``CLAUDE.md``). OOXML subtypes (docx/xlsx/pptx) are distinguished by peeking
inside the zip container with the stdlib ``zipfile`` module instead of a
magic-number database.
"""

import email
import zipfile
from io import BytesIO

MIME_PDF = "application/pdf"
MIME_PNG = "image/png"
MIME_JPEG = "image/jpeg"
MIME_WEBP = "image/webp"
MIME_TIFF = "image/tiff"
MIME_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
MIME_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MIME_PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
MIME_TXT = "text/plain"
MIME_CSV = "text/csv"
MIME_MD = "text/markdown"
MIME_EML = "message/rfc822"

IMAGE_MIMES = {MIME_PNG, MIME_JPEG, MIME_WEBP, MIME_TIFF}
OFFICE_MIMES = {MIME_DOCX, MIME_XLSX, MIME_PPTX}
TEXT_FAMILY_MIMES = {MIME_TXT, MIME_CSV, MIME_MD}

# Structured (VLM) extraction only ever made sense for what it was designed for
# — scans and digital PDFs. Office/text/email formats still get the full
# universal baseline (text, thumbnail, generic metadata), just never a forced
# VLM call — structured extraction is type-conditional, not a default applied
# to every file. Shared by idp/jobs.py and files/service.py.
VLM_ELIGIBLE_MIMES = {MIME_PDF} | IMAGE_MIMES

# Every mime type this archive knows how to parse for text — the upload
# allow-list source of truth. Maps sniffed mime -> the extension used in
# storage_key.
ALLOWED_MIMES: dict[str, str] = {
    MIME_PDF: "pdf",
    MIME_JPEG: "jpg",
    MIME_PNG: "png",
    MIME_WEBP: "webp",
    MIME_TIFF: "tif",
    MIME_DOCX: "docx",
    MIME_XLSX: "xlsx",
    MIME_PPTX: "pptx",
    MIME_TXT: "txt",
    MIME_CSV: "csv",
    MIME_MD: "md",
    MIME_EML: "eml",
}

_OOXML_MARKERS = {
    "word/document.xml": MIME_DOCX,
    "xl/workbook.xml": MIME_XLSX,
    "ppt/presentation.xml": MIME_PPTX,
}

# Extensions we accept for the plain-text family. Used only to pick a cosmetic
# subtype once content sniffing has already confirmed the bytes decode as text
# — never to admit a file that failed decoding, and never to override a
# binary signature match above.
_TEXT_EXTENSIONS = {"csv": MIME_CSV, "md": MIME_MD, "markdown": MIME_MD, "txt": MIME_TXT}

_EMAIL_HEADER_KEYS = ("From", "To", "Subject", "Date", "Message-ID", "Return-Path")
_EMAIL_HEADER_MIN_MATCHES = 2

# ``bytes.decode("latin-1")`` never raises — every byte value maps to *some*
# character — so it cannot be used on its own to tell text from binary.
# This gates that fallback: printable ASCII + tab/LF/CR + the Latin-1 letter
# range (0xA0-0xFF), excluding the C1 control block (0x80-0x9F). Genuine
# binary garbage fails this at a high rate; real legacy-encoded text doesn't.
_TEXT_SAFE_BYTES = frozenset(range(0x20, 0x7F)) | {0x09, 0x0A, 0x0D} | frozenset(range(0xA0, 0x100))
_TEXT_SAFE_MIN_RATIO = 0.95


def _is_probably_text(data: bytes) -> bool:
    if not data:
        return True
    if b"\x00" in data:
        return False
    sample = data[:8192]
    safe = sum(1 for b in sample if b in _TEXT_SAFE_BYTES)
    return safe / len(sample) > _TEXT_SAFE_MIN_RATIO


def _sniff_ooxml(data: bytes) -> str | None:
    """Peek inside a zip (OOXML container) for the part that names its kind."""
    try:
        with zipfile.ZipFile(BytesIO(data)) as zf:
            names = set(zf.namelist())
    except zipfile.BadZipFile:
        return None
    for marker, mime in _OOXML_MARKERS.items():
        if marker in names:
            return mime
    return None


def _looks_like_email(text: str) -> bool:
    """Heuristic: does the leading header block parse as >=2 RFC822 headers?"""
    msg = email.message_from_string(text[:4096])
    matches = sum(1 for key in _EMAIL_HEADER_KEYS if msg.get(key))
    return matches >= _EMAIL_HEADER_MIN_MATCHES


def sniff_mime(data: bytes, filename: str | None = None) -> str | None:
    """Identify a file's real type from its bytes. Returns ``None`` when unrecognised.

    Binary types are identified purely by magic-byte signature — renaming a
    binary file never changes what it sniffs as. For the plain-text family
    (txt/csv/md), where no magic number exists and all three are extracted
    identically downstream, the extension is used only to pick a cosmetic
    subtype label after the bytes have already proven to be decodable text.
    """
    if data.startswith(b"%PDF-"):
        return MIME_PDF
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return MIME_PNG
    if data.startswith(b"\xff\xd8\xff"):
        return MIME_JPEG
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return MIME_WEBP
    if data[:4] in (b"II*\x00", b"MM\x00*"):
        return MIME_TIFF
    if data[:4] == b"PK\x03\x04":
        return _sniff_ooxml(data)

    # No binary signature matched — try decoding as text. Valid UTF-8 is a
    # strong signal on its own; the latin-1 fallback (which always succeeds)
    # is gated by a printability check so unrecognised binary isn't
    # misclassified as text just because latin-1 can decode any byte.
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        if not _is_probably_text(data):
            return None
        text = data.decode("latin-1", errors="replace")

    if _looks_like_email(text):
        return MIME_EML

    ext = filename.rsplit(".", 1)[-1].lower() if filename and "." in filename else ""
    return _TEXT_EXTENSIONS.get(ext, MIME_TXT)
