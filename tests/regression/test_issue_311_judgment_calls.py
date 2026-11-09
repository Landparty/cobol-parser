"""Issue #311: small judgment calls from the 2026-10-14 bug hunt.

(1) ``diff`` moving every paragraph of a renamed section is pinned in
``tests/unit/analysis/test_ast_diff.py``. Here: (2) ``OCCURS UNBOUNDED``
sized at its minimum said so nowhere, and (3) the EXEC DLI interface block
(``DIBSTAT``) was an undefined name; it is a special register now, but
its tests stay business rules like a CICS ``RESP`` field's.
"""

from __future__ import annotations

from pathlib import Path

from cobolparser import parse_cobol
from cobolparser.analysis.business_rules import BusinessRuleExtractor
from cobolparser.analysis.xref import XrefAnalyzer, is_special_register
from cobolparser.layout.offsets import compute_program_data_items

ENTERPRISE = Path(__file__).resolve().parents[1] / "samples" / "enterprise"


def _ast(name: str):  # type: ignore[no-untyped-def]
    result = parse_cobol((ENTERPRISE / f"{name}.cbl").read_text(), f"{name}.cbl")
    assert result.ast is not None
    return result.ast


def test_occurs_unbounded_is_flagged_unresolved() -> None:
    report = compute_program_data_items(_ast("MODERN63"))
    row = next(i for i in report["items"] if i["name"] == "WS-ROW")
    # The shape the backend and the extension read is unchanged ...
    assert row["occurs"] == {"min": 1, "max": 1}
    # ... and the lower bound is said out loud.
    notes = [u for u in report["unresolved"] if "OCCURS UNBOUNDED" in u]
    assert len(notes) == 1
    assert notes[0].startswith("WS-UNBOUNDED-GROUP.WS-ROW:")
    assert "lower bound" in notes[0]


def test_a_bounded_table_gets_no_unbounded_note() -> None:
    report = compute_program_data_items(_ast("MODERN63"))
    assert not any("WS-RATE" in u and "UNBOUNDED" in u for u in report["unresolved"])


def test_dibstat_is_a_special_register_not_undefined() -> None:
    assert is_special_register("DIBSTAT")
    report = XrefAnalyzer().analyze(_ast("EXECDLI"))
    assert "DIBSTAT" not in report.to_dict()["undefined"]


def test_dibstat_tests_stay_business_rules() -> None:
    """A special register to xref, but a status field to business-rules:
    EXEC DLI has no RESP(), so DIBSTAT is how it tests a not-found, the role
    a CICS RESP field plays ("NOTFND -> CUSTOMER NOT FOUND" is business)."""
    report = BusinessRuleExtractor().analyze(_ast("EXECDLI"))
    assert report.technical_rules_excluded == 0
    (evaluate,) = [
        r
        for r in report.rules
        if any("DIBSTAT = 'GE'" in (b.condition or "") for b in r.branches)
    ]
    assert evaluate.kind == "validation"
    assert "DIBSTAT" in evaluate.inputs
    failed = [
        r
        for r in report.rules
        if r.kind == "validation"
        and any("DIBSTAT" in (b.condition or "") for b in r.branches)
    ]
    assert len(failed) == 3  # SCHD FAILED, CUSTOMER NOT FOUND, REPL FAILED


def test_mq_compcode_stays_a_business_rule() -> None:
    """Like a CICS RESP field, a user-declared MQ completion code compared
    to MQCC-/MQRC- constants stays a business rule (documented choice)."""
    report = BusinessRuleExtractor().analyze(_ast("MQBATCH"))
    assert any(
        any("WS-COMPCODE" in (b.condition or "") for b in r.branches)
        for r in report.rules
    )
