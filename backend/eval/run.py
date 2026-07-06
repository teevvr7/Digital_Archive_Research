"""Phase 2 eval harness — deterministic pass rate + LLM share against eval/corpus.

Run from ``backend/``::

    python -m eval.run

For every ``<name>.expected.json`` fixture in ``eval/corpus/`` (paired with a
same-stem source document), this runs the exact same path the worker uses:

    sniff mime -> run_extraction (text-layer or OCR) -> extract_candidate
    (doc-type keyword gate) -> score_extraction (the 0.75 quality gate)

and reports the two CLAUDE.md headline numbers:

    deterministic pass rate = gate-passed / candidates attempted   (target >= 80%)
    LLM share                = (candidates attempted - passed) / total docs (target 10-20%)

Field-level diffs against each fixture's ``fields`` are printed for visibility
but are NOT part of the pass/fail metrics — several fixtures intentionally
document a *known* extraction gap (see their ``notes``) rather than pretend
this tier is perfect. The metrics that matter are the doc-type gate decision
and the quality-gate pass/fail, both checked against the fixture.
"""

import json
import sys
from pathlib import Path

CORPUS_DIR = Path(__file__).parent / "corpus"


def _load_text(doc_path: Path) -> tuple[str, float | None]:
    """Run the real Tier 0/1 pipeline (text-layer or OCR) for one corpus doc."""
    from app.modules.idp import mimetype
    from app.modules.idp.pipeline import run_extraction

    data = doc_path.read_bytes()
    mime = mimetype.sniff_mime(data, doc_path.name)
    result = run_extraction(data, mime)
    return result.text, result.ocr_confidence


def _find_source(stem: str) -> Path | None:
    for ext in (".pdf", ".png", ".jpg", ".jpeg"):
        candidate = CORPUS_DIR / f"{stem}{ext}"
        if candidate.exists():
            return candidate
    return None


def run() -> int:
    from app.modules.idp.extract import extract_candidate
    from app.modules.idp.gate import score_extraction

    fixtures = sorted(CORPUS_DIR.glob("*.expected.json"))
    if not fixtures:
        print(f"No fixtures found in {CORPUS_DIR} — nothing to evaluate.")
        return 0

    total = 0
    candidates_attempted = 0
    gate_passed = 0
    mismatches: list[str] = []

    for fixture_path in fixtures:
        stem = fixture_path.name[: -len(".expected.json")]
        doc_path = _find_source(stem)
        if doc_path is None:
            print(f"  SKIP {stem}: no source document found")
            continue

        expected = json.loads(fixture_path.read_text(encoding="utf-8"))
        total += 1

        text, ocr_conf = _load_text(doc_path)
        candidate = extract_candidate(text)
        is_candidate = candidate is not None

        print(f"\n=== {stem} ===")
        if is_candidate != expected.get("is_candidate", False):
            msg = f"{stem}: doc-type gate mismatch (got candidate={is_candidate}, expected={expected.get('is_candidate')})"
            mismatches.append(msg)
            print(f"  ** {msg} **")

        if not is_candidate:
            print("  not a structured-extraction candidate (skipped, as expected)"
                  if not expected.get("is_candidate", False) else "  not a candidate")
            continue

        candidates_attempted += 1
        result = score_extraction(candidate, ocr_conf)
        if result.passed:
            gate_passed += 1

        expected_pass = expected.get("expected_gate_pass")
        line = f"  score={result.score:.3f} passed={result.passed} breakdown={result.breakdown}"
        if expected_pass is not None and result.passed != expected_pass:
            line += f"  ** MISMATCH (expected passed={expected_pass}) **"
            mismatches.append(f"{stem}: gate-pass mismatch")
        print(line)

        actual_fields = candidate.to_fields()
        for key, expected_value in expected.get("fields", {}).items():
            actual_value = actual_fields.get(key)
            marker = "OK" if actual_value == expected_value else "DIFF"
            print(f"    [{marker}] {key}: actual={actual_value!r} expected={expected_value!r}")

    pass_rate = (gate_passed / candidates_attempted * 100) if candidates_attempted else 0.0
    llm_share = ((candidates_attempted - gate_passed) / total * 100) if total else 0.0

    print("\n" + "=" * 60)
    print(f"Total documents:                   {total}")
    print(f"Structured-extraction candidates:  {candidates_attempted}")
    print(f"Deterministic pass rate:           {pass_rate:.1f}%  (target >= 80%)")
    print(f"LLM share (of all documents):      {llm_share:.1f}%  (target 10-20%)")

    if mismatches:
        print("\nFixture mismatches (doc-type gate or quality-gate decision differs from the fixture):")
        for m in mismatches:
            print(f"  - {m}")
        return 1

    print("\nAll fixtures match their expected gate decision.")
    return 0


if __name__ == "__main__":
    sys.exit(run())
