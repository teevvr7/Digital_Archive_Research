"""Quality gate — the pass/fail decision between Tier 2 (deterministic) and
Tier 4 (VLM fallback).

A weighted score in [0, 1] combining four signals: completeness (did we find
the load-bearing fields), format validity (do the values look plausible),
OCR confidence (how legible was the source), and a math audit (do the line
items reconcile with the total). ``PASS_THRESHOLD = 0.75`` is fixed per spec
— changing it requires explicit human sign-off (root ``CLAUDE.md``); never
tune the threshold or the weights to force a specific document to pass.
"""

from dataclasses import dataclass, field

from app.modules.idp.extract import ExtractionCandidate

PASS_THRESHOLD = 0.75

_WEIGHT_COMPLETENESS = 0.4
_WEIGHT_FORMAT_VALIDITY = 0.2
_WEIGHT_OCR_CONFIDENCE = 0.2
_WEIGHT_MATH_AUDIT = 0.2

# Math audit: line items must reconcile with the total within whichever
# tolerance is looser — a fixed RM/USD 1.00, or 2% of the total (rounding
# and small surcharges/discounts are common on real invoices).
_MATH_AUDIT_ABS_TOLERANCE = 1.0
_MATH_AUDIT_REL_TOLERANCE = 0.02
_MATH_AUDIT_MISMATCH_SCORE = 0.3

_VENDOR_COMPLETENESS_BONUS = 0.1


@dataclass
class GateResult:
    score: float
    passed: bool
    breakdown: dict[str, float] = field(default_factory=dict)


def _is_valid_invoice_number(value: str) -> bool:
    """A real invoice/receipt number almost always contains a digit.

    Catches the OCR-column-bleed failure mode where a neighbouring word
    (e.g. a customer's name) gets captured instead of the real number —
    see the calibration notes in idp/extract.py for a concrete example.
    """
    return any(ch.isdigit() for ch in value)


def _completeness_score(c: ExtractionCandidate) -> float:
    """The three load-bearing header fields. Vendor/line-items are bonus
    signals, never required — text-only extraction has no layout/bbox info
    to reliably place them across every template."""
    required = [
        c.invoice_number is not None,
        c.invoice_date is not None or c.due_date is not None,
        c.total_amount is not None,
    ]
    score = sum(required) / len(required)
    if c.vendor:
        score = min(1.0, score + _VENDOR_COMPLETENESS_BONUS)
    return score


def _format_validity_score(c: ExtractionCandidate) -> float:
    checks: list[bool] = []
    if c.invoice_number is not None:
        checks.append(_is_valid_invoice_number(c.invoice_number))
    if c.total_amount is not None:
        checks.append(c.total_amount > 0)
    if c.invoice_date is not None and c.due_date is not None:
        checks.append(c.due_date >= c.invoice_date)
    if not checks:
        return 0.5  # nothing extracted to validate — neutral, not a free pass
    return sum(checks) / len(checks)


def _math_audit_score(c: ExtractionCandidate) -> float:
    """1.0 (neutral) when there's nothing to audit — never punish a document
    for this tier's known line-item limitation (see idp/extract.py)."""
    if not c.line_items or c.total_amount is None:
        return 1.0
    items_total = sum(li.amount for li in c.line_items if li.amount is not None)
    if items_total == 0:
        return 1.0
    diff = abs(items_total - c.total_amount)
    tolerance = max(_MATH_AUDIT_ABS_TOLERANCE, c.total_amount * _MATH_AUDIT_REL_TOLERANCE)
    return 1.0 if diff <= tolerance else _MATH_AUDIT_MISMATCH_SCORE


def score_extraction(candidate: ExtractionCandidate, ocr_confidence: float | None) -> GateResult:
    """Score a deterministic extraction candidate. ``ocr_confidence`` is the
    document's OCR confidence (``None`` for a text-layer PDF — no OCR
    uncertainty, scored as a clean 1.0)."""
    completeness = _completeness_score(candidate)
    format_validity = _format_validity_score(candidate)
    ocr_score = ocr_confidence if ocr_confidence is not None else 1.0
    math_audit = _math_audit_score(candidate)

    score = (
        completeness * _WEIGHT_COMPLETENESS
        + format_validity * _WEIGHT_FORMAT_VALIDITY
        + ocr_score * _WEIGHT_OCR_CONFIDENCE
        + math_audit * _WEIGHT_MATH_AUDIT
    )
    breakdown = {
        "completeness": completeness,
        "format_validity": format_validity,
        "ocr_confidence": ocr_score,
        "math_audit": math_audit,
    }
    return GateResult(score=round(score, 4), passed=score >= PASS_THRESHOLD, breakdown=breakdown)
