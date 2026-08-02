"""Regression tests for comma-separated SET statement targets.

Mirrors the fix applied to MOVE's target-list handling: a COMMA between
SET targets (e.g. ``SET IX1, IX2 UP BY 1.``) must be skipped as a
separator, not treated as a terminator that truncates target collection
and swallows the trailing action clause (UP BY / DOWN BY / TO ...).
"""

from cobolparser import parse_cobol
from cobolparser.models.statements import SetStatement


def _parse_set(statement: str):
    """Parse a single PROCEDURE DIVISION statement and return the SetStatement."""
    src = (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. TEST-STMT.\n"
        "       PROCEDURE DIVISION.\n"
        "       MAIN-PARA.\n"
        f"{statement}\n"
    )
    result = parse_cobol(src, filename="t.cob")
    assert result.ast is not None
    proc = result.ast.procedure_division
    if proc.paragraphs:
        stmts = proc.paragraphs[0].statements
    else:
        stmts = proc.sections[0].paragraphs[0].statements
    set_stmts = [s for s in stmts if isinstance(s, SetStatement)]
    assert len(set_stmts) == 1, f"expected exactly one SetStatement, got {stmts}"
    return result, set_stmts[0]


class TestSetCommaTargets:
    def test_space_separated_targets_up_by(self):
        """SET IX1 IX2 UP BY 1. (no comma) must keep working."""
        result, stmt = _parse_set("           SET IX1 IX2 UP BY 1.")
        assert result.warnings == []
        assert stmt.targets == ["IX1", "IX2"]
        assert stmt.set_type == "UP_BY"
        assert stmt.value == "1"

    def test_comma_separated_targets_up_by(self):
        """SET IX1, IX2 UP BY 1. -- the previously-broken case."""
        result, stmt = _parse_set("           SET IX1, IX2 UP BY 1.")
        assert result.warnings == []
        assert stmt.targets == ["IX1", "IX2"]
        assert stmt.set_type == "UP_BY"
        assert stmt.value == "1"

    def test_comma_separated_three_targets_down_by(self):
        """SET IX1, IX2, IX3 DOWN BY 2. -- three comma-separated targets."""
        result, stmt = _parse_set("           SET IX1, IX2, IX3 DOWN BY 2.")
        assert result.warnings == []
        assert stmt.targets == ["IX1", "IX2", "IX3"]
        assert stmt.set_type == "DOWN_BY"
        assert stmt.value == "2"

    def test_comma_separated_condition_names_to_true(self):
        """SET COND-A, COND-B TO TRUE. -- multiple condition-names."""
        result, stmt = _parse_set("           SET COND-A, COND-B TO TRUE.")
        assert result.warnings == []
        assert stmt.targets == ["COND-A", "COND-B"]
        assert stmt.set_type == "TRUE"
        assert stmt.value is None

    def test_set_to_null_unaffected(self):
        """SET WS-PTR TO NULL. -- unrelated single-target form still works."""
        result, stmt = _parse_set("           SET WS-PTR TO NULL.")
        assert result.warnings == []
        assert stmt.targets == ["WS-PTR"]
        assert stmt.set_type == "TO"
        assert stmt.value == "NULL"

    def test_set_address_of_unaffected(self):
        """SET ADDRESS OF WS-REC TO PTR-VAR. -- unrelated form still works."""
        result, stmt = _parse_set("           SET ADDRESS OF WS-REC TO PTR-VAR.")
        assert result.warnings == []
        assert stmt.targets == ["WS-REC"]
        assert stmt.set_type == "TO"
        assert stmt.value == "PTR-VAR"
