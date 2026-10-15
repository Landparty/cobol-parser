"""Regression tests for a follow-up sweep of the comma-separated-list bug
class fixed in the 2026-07-22/23 statement-support verification sweep
(see .okf/parser.md "Statement-Support Verification Sweep").

That sweep fixed comma truncation in CALL/SET/UNSTRING/DISPLAY/GO TO/
CANCEL/ENTRY. This file pins the same defect class found afterward in
areas that sweep did not touch:

- INITIALIZE's target list (warned drop before the fix).
- SORT/MERGE's ASCENDING/DESCENDING KEY field list -- the worst instance:
  fully silent (``errors=[], warnings=[]``), not even warned.
- SORT/MERGE's USING/GIVING file-name lists (shared ``_parse_file_list``).
- ADD/SUBTRACT/MULTIPLY/DIVIDE's GIVING clause, which (like TO/FROM
  targets already fixed) may carry a comma/space-separated list of result
  targets, each optionally ROUNDED -- previously only the first survived.
- MULTIPLY/DIVIDE format 1 (no GIVING)'s own second-operand target list.

A further targeted round (still 2026-07-24) checked the remaining
list-collecting loops this bug class hadn't been verified against yet and
found two more real, live instances:

- CALL's ``BY REFERENCE``/``BY CONTENT``/``BY VALUE`` passing mode did not
  persist across a comma-separated parameter list within one BY-phrase
  group (``BY CONTENT a, b`` silently mode-tagged ``b`` back to the
  REFERENCE default instead of CONTENT).
- COMPUTE's multi-target list (``COMPUTE A, B = expr``) had no comma
  handling at all -- worse than a silent/warned drop, this was a hard
  parse failure ("COMPUTE statement missing '=' operator") since the
  unconsumed comma blocked the subsequent '=' check.

SEARCH's WHEN-condition collector and READ/WRITE's INTO/FROM clauses were
also checked in this round and found NOT to need a fix: neither takes a
comma/space-separated list per the standard grammar (each is a single
value), so there is nothing to lose there.
"""

from cobolparser import parse_cobol
from cobolparser.models.statements import (
    AddStatement,
    CallStatement,
    ComputeStatement,
    DivideStatement,
    InitializeStatement,
    MergeStatement,
    MultiplyStatement,
    SortStatement,
    SubtractStatement,
)


def _parse_statement(statement: str, extra_ws: str = ""):
    """Parse a single PROCEDURE DIVISION statement, returning (result, stmts)."""
    src = (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. TEST-STMT.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01 WS-A PIC 9(5).\n"
        "       01 WS-B PIC 9(5).\n"
        "       01 WS-C PIC 9(5).\n"
        "       01 WS-D PIC 9(5).\n"
        f"{extra_ws}"
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
    return result, stmts


def _only(result, stmts, node_type):
    matches = [s for s in stmts if isinstance(s, node_type)]
    assert len(matches) == 1, f"expected exactly one {node_type.__name__}, got {stmts}"
    return matches[0]


_SORT_MERGE_WS = (
    "       FILE SECTION.\n" "       SD SORT-FILE.\n" "       01 SORT-REC PIC X(10).\n"
)


class TestInitializeCommaTargets:
    def test_space_separated_targets_unaffected(self):
        result, stmts = _parse_statement("           INITIALIZE WS-A WS-B WS-C.")
        stmt = _only(result, stmts, InitializeStatement)
        assert result.warnings == []
        assert stmt.targets == ["WS-A", "WS-B", "WS-C"]

    def test_comma_separated_targets(self):
        result, stmts = _parse_statement("           INITIALIZE WS-A, WS-B, WS-C.")
        stmt = _only(result, stmts, InitializeStatement)
        assert result.warnings == []
        assert stmt.targets == ["WS-A", "WS-B", "WS-C"]


class TestSortMergeKeyCommaList:
    def test_sort_ascending_key_comma_list(self):
        result, stmts = _parse_statement(
            "           SORT SORT-FILE ASCENDING KEY WS-A, WS-B.",
            extra_ws=_SORT_MERGE_WS,
        )
        stmt = _only(result, stmts, SortStatement)
        assert result.errors == []
        assert result.warnings == []
        assert stmt.keys == [
            {"field": "WS-A", "order": "ASCENDING"},
            {"field": "WS-B", "order": "ASCENDING"},
        ]

    def test_sort_descending_key_comma_list(self):
        result, stmts = _parse_statement(
            "           SORT SORT-FILE DESCENDING KEY WS-A, WS-B.",
            extra_ws=_SORT_MERGE_WS,
        )
        stmt = _only(result, stmts, SortStatement)
        assert result.errors == []
        assert result.warnings == []
        assert [k["field"] for k in stmt.keys] == ["WS-A", "WS-B"]

    def test_merge_ascending_key_comma_list(self):
        # Split across two lines to stay within fixed-format column 72 --
        # this is plain multi-line free-form-within-fixed-format layout
        # (no continuation marker needed), not a test of line-wrapping.
        result, stmts = _parse_statement(
            "           MERGE SORT-FILE ASCENDING KEY WS-A, WS-B\n"
            "               USING WS-C GIVING WS-D.",
            extra_ws=_SORT_MERGE_WS,
        )
        stmt = _only(result, stmts, MergeStatement)
        assert result.errors == []
        assert result.warnings == []
        assert [k["field"] for k in stmt.keys] == ["WS-A", "WS-B"]
        assert stmt.using_files == ["WS-C"]
        assert stmt.giving_files == ["WS-D"]

    def test_sort_key_space_separated_unaffected(self):
        result, stmts = _parse_statement(
            "           SORT SORT-FILE ASCENDING KEY WS-A WS-B.",
            extra_ws=_SORT_MERGE_WS,
        )
        stmt = _only(result, stmts, SortStatement)
        assert result.warnings == []
        assert [k["field"] for k in stmt.keys] == ["WS-A", "WS-B"]


class TestSortUsingGivingCommaFileList:
    def test_sort_using_comma_file_list(self):
        result, stmts = _parse_statement(
            "           SORT SORT-FILE ASCENDING SORT-REC\n"
            "               USING WS-A, WS-B GIVING WS-C.",
            extra_ws=_SORT_MERGE_WS,
        )
        stmt = _only(result, stmts, SortStatement)
        assert result.errors == []
        assert result.warnings == []
        assert stmt.using_files == ["WS-A", "WS-B"]
        assert stmt.giving_files == ["WS-C"]

    def test_sort_giving_comma_file_list(self):
        result, stmts = _parse_statement(
            "           SORT SORT-FILE ASCENDING SORT-REC\n"
            "               USING WS-A GIVING WS-C, WS-D.",
            extra_ws=_SORT_MERGE_WS,
        )
        stmt = _only(result, stmts, SortStatement)
        assert result.errors == []
        assert result.warnings == []
        assert stmt.giving_files == ["WS-C", "WS-D"]


class TestArithmeticGivingCommaMultiTarget:
    def test_add_to_giving_comma_multi_target(self):
        result, stmts = _parse_statement(
            "           ADD WS-A TO WS-B GIVING WS-C, WS-D."
        )
        stmt = _only(result, stmts, AddStatement)
        assert result.warnings == []
        assert stmt.giving == "WS-C"
        assert stmt.givings == ["WS-C", "WS-D"]

    def test_add_giving_only_comma_multi_target(self):
        result, stmts = _parse_statement("           ADD WS-A WS-B GIVING WS-C, WS-D.")
        stmt = _only(result, stmts, AddStatement)
        assert result.warnings == []
        assert stmt.givings == ["WS-C", "WS-D"]

    def test_subtract_giving_comma_multi_target(self):
        result, stmts = _parse_statement(
            "           SUBTRACT WS-A FROM WS-B GIVING WS-C, WS-D."
        )
        stmt = _only(result, stmts, SubtractStatement)
        assert result.warnings == []
        assert stmt.givings == ["WS-C", "WS-D"]

    def test_multiply_giving_comma_multi_target(self):
        result, stmts = _parse_statement(
            "           MULTIPLY WS-A BY WS-B GIVING WS-C, WS-D."
        )
        stmt = _only(result, stmts, MultiplyStatement)
        assert result.warnings == []
        assert stmt.giving == "WS-C"
        assert stmt.givings == ["WS-C", "WS-D"]

    def test_divide_giving_comma_multi_target(self):
        result, stmts = _parse_statement(
            "           DIVIDE WS-A BY WS-B GIVING WS-C, WS-D."
        )
        stmt = _only(result, stmts, DivideStatement)
        assert result.warnings == []
        assert stmt.givings == ["WS-C", "WS-D"]

    def test_divide_giving_multi_target_then_remainder_still_works(self):
        """A parser robustness check, not a claim this combination is
        standard-valid COBOL (REMAINDER conventionally pairs with a single
        GIVING target) -- REMAINDER must still be recognized as REMAINDER,
        not swallowed as a bogus extra GIVING target, even after a
        multi-target GIVING list.
        """
        result, stmts = _parse_statement(
            "           DIVIDE WS-A BY WS-B GIVING WS-C, WS-D REMAINDER WS-D."
        )
        stmt = _only(result, stmts, DivideStatement)
        assert result.warnings == []
        assert stmt.givings == ["WS-C", "WS-D"]
        assert stmt.remainder == "WS-D"

    def test_multiply_giving_rounded_per_target(self):
        result, stmts = _parse_statement(
            "           MULTIPLY WS-A BY WS-B GIVING WS-C ROUNDED, WS-D."
        )
        stmt = _only(result, stmts, MultiplyStatement)
        assert result.warnings == []
        assert stmt.givings == ["WS-C", "WS-D"]
        assert stmt.rounded is True

    def test_add_giving_single_target_unaffected(self):
        """Single-target GIVING (the common case) keeps working unchanged."""
        result, stmts = _parse_statement("           ADD WS-A TO WS-B GIVING WS-C.")
        stmt = _only(result, stmts, AddStatement)
        assert result.warnings == []
        assert stmt.giving == "WS-C"
        assert stmt.givings == ["WS-C"]


class TestMultiplyDivideFormat1MultiTarget:
    """MULTIPLY/DIVIDE format 1 (no GIVING) overwrites its second operand(s)
    in place and, per the standard grammar, accepts a comma/space-separated
    list of them (``BY id-2 [ROUNDED], id-3 [ROUNDED] ...`` /
    ``INTO id-2 [ROUNDED], id-3 [ROUNDED] ...``) -- distinct from (and found
    after) the GIVING multi-target fix above, which only covers format 2.
    """

    def test_multiply_format1_comma_multi_target(self):
        result, stmts = _parse_statement("           MULTIPLY WS-A BY WS-B, WS-C.")
        stmt = _only(result, stmts, MultiplyStatement)
        assert result.warnings == []
        assert stmt.target == "WS-B"
        assert stmt.targets == ["WS-B", "WS-C"]

    def test_divide_into_format1_comma_multi_target(self):
        result, stmts = _parse_statement("           DIVIDE WS-A INTO WS-B, WS-C.")
        stmt = _only(result, stmts, DivideStatement)
        assert result.warnings == []
        assert stmt.targets == ["WS-B", "WS-C"]

    def test_multiply_format1_rounded_per_target(self):
        result, stmts = _parse_statement(
            "           MULTIPLY WS-A BY WS-B ROUNDED, WS-C ROUNDED."
        )
        stmt = _only(result, stmts, MultiplyStatement)
        assert result.warnings == []
        assert stmt.targets == ["WS-B", "WS-C"]
        assert stmt.rounded is True

    def test_multiply_format1_single_target_unaffected(self):
        """Single-target format 1 (the common case) keeps working unchanged."""
        result, stmts = _parse_statement("           MULTIPLY WS-A BY WS-B.")
        stmt = _only(result, stmts, MultiplyStatement)
        assert result.warnings == []
        assert stmt.target == "WS-B"
        assert stmt.targets == ["WS-B"]

    def test_divide_format2_giving_unaffected_by_format1_fix(self):
        """Format 2 (GIVING) must NOT gain a spurious .target/.targets --
        the second operand there is a divisor, not an overwritten result.
        """
        result, stmts = _parse_statement("           DIVIDE WS-A BY WS-B GIVING WS-C.")
        stmt = _only(result, stmts, DivideStatement)
        assert result.warnings == []
        assert stmt.target is None
        assert stmt.targets == []
        assert stmt.giving == "WS-C"

    def test_divide_into_remainder_not_swallowed_as_target(self):
        """The tolerated no-GIVING REMAINDER form must stop the target list
        at REMAINDER rather than absorbing it as a bogus extra target.
        """
        result, stmts = _parse_statement(
            "           DIVIDE WS-A INTO WS-B, WS-C REMAINDER WS-D."
        )
        stmt = _only(result, stmts, DivideStatement)
        assert result.warnings == []
        assert stmt.targets == ["WS-B", "WS-C"]
        assert stmt.remainder == "WS-D"


def _param_pairs(stmt):
    return [(p.name, p.passing_mode) for p in stmt.using_parameters]


class TestCallByModePersistsAcrossCommaList:
    def test_by_content_mode_persists_across_comma_list(self):
        # Split across two lines to stay within fixed-format column 72.
        result, stmts = _parse_statement(
            "           CALL 'PROG' USING BY REFERENCE WS-A, WS-B\n"
            "               BY CONTENT WS-C, WS-D."
        )
        stmt = _only(result, stmts, CallStatement)
        assert result.warnings == []
        assert _param_pairs(stmt) == [
            ("WS-A", "REFERENCE"),
            ("WS-B", "REFERENCE"),
            ("WS-C", "CONTENT"),
            ("WS-D", "CONTENT"),
        ]

    def test_by_reference_single_group_comma_list_unaffected(self):
        result, stmts = _parse_statement(
            "           CALL 'PROG' USING BY REFERENCE WS-A, WS-B."
        )
        stmt = _only(result, stmts, CallStatement)
        assert result.warnings == []
        assert _param_pairs(stmt) == [("WS-A", "REFERENCE"), ("WS-B", "REFERENCE")]

    def test_default_reference_mode_with_no_by_phrase_unaffected(self):
        result, stmts = _parse_statement("           CALL 'PROG' USING WS-A, WS-B.")
        stmt = _only(result, stmts, CallStatement)
        assert result.warnings == []
        assert _param_pairs(stmt) == [("WS-A", "REFERENCE"), ("WS-B", "REFERENCE")]


class TestComputeCommaTargets:
    def test_compute_comma_separated_targets(self):
        result, stmts = _parse_statement("           COMPUTE WS-A, WS-B = WS-C + WS-D.")
        stmt = _only(result, stmts, ComputeStatement)
        assert result.errors == []
        assert result.warnings == []
        assert stmt.targets == ["WS-A", "WS-B"]
        assert stmt.expression == "WS-C + WS-D"

    def test_compute_space_separated_targets_unaffected(self):
        result, stmts = _parse_statement("           COMPUTE WS-A WS-B = WS-C + WS-D.")
        stmt = _only(result, stmts, ComputeStatement)
        assert result.errors == []
        assert result.warnings == []
        assert stmt.targets == ["WS-A", "WS-B"]

    def test_compute_comma_separated_targets_with_rounded(self):
        result, stmts = _parse_statement(
            "           COMPUTE WS-A ROUNDED, WS-B = WS-C + WS-D."
        )
        stmt = _only(result, stmts, ComputeStatement)
        assert result.errors == []
        assert result.warnings == []
        assert stmt.targets == ["WS-A", "WS-B"]
        assert stmt.rounded is True

    def test_compute_single_target_unaffected(self):
        result, stmts = _parse_statement("           COMPUTE WS-A = WS-C + WS-D.")
        stmt = _only(result, stmts, ComputeStatement)
        assert result.errors == []
        assert result.warnings == []
        assert stmt.targets == ["WS-A"]
