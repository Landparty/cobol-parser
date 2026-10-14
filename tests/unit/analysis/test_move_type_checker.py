"""Unit tests for MoveTypeChecker.

Covers:
- PictureClause → DataCategory classification
- Figurative constant classification
- Numeric literal classification
- MOVE pair (legal / warning / error) detection
- MOVE CORRESPONDING (skip — no picture data on CORR source)
- Unknown source/target variable (skip without error)
- Full COBOL source round-trip via parse_cobol()
- Report.errors / Report.warnings properties
- to_dict() serialization
- Export from top-level package
"""

import json

from cobolparser import parse_cobol
from cobolparser.analysis.move_type_checker import (
    DataCategory,
    MoveTypeChecker,
    MoveTypeReport,
    MoveTypeViolation,
    MoveViolationKind,
    _classify_literal,
    _classify_picture,
    _is_non_integer_picture,
)
from cobolparser.models.ast_base import SourceLocation
from cobolparser.models.data_items import CobolDataItem, PictureClause
from cobolparser.models.program import (
    CobolDivision,
    CobolProgram,
    CobolSection,
)
from cobolparser.models.statements import MoveStatement

_LOC = SourceLocation(1, 1)


# ---------------------------------------------------------------------------
# DataCategory classification helpers
# ---------------------------------------------------------------------------


def _pic(pattern: str) -> PictureClause:
    return PictureClause(pattern, _LOC)


class TestClassifyPicture:
    def test_x_alphanumeric(self):
        assert _classify_picture(_pic("X")) == DataCategory.ALPHANUMERIC

    def test_x_n_alphanumeric(self):
        assert _classify_picture(_pic("X(10)")) == DataCategory.ALPHANUMERIC

    def test_a_alphabetic(self):
        assert _classify_picture(_pic("A")) == DataCategory.ALPHABETIC

    def test_a_n_alphabetic(self):
        assert _classify_picture(_pic("A(20)")) == DataCategory.ALPHABETIC


class TestIsNonIntegerPicture:
    """`_is_non_integer_picture` now reads only the canonical
    `PictureClause.decimal_digits` -- the single source
    `models.data_items.PictureClause._parse_scaled_pattern` already
    populates for both an ordinary `V`-decimal and a leading-`P`-scaled
    fraction -- rather than also re-deriving the leading-`P` case from the
    raw pattern string."""

    def test_ordinary_integer_is_not_flagged(self):
        assert _is_non_integer_picture(_pic("9(5)")) is False

    def test_v_decimal_is_flagged(self):
        assert _is_non_integer_picture(_pic("9(5)V99")) is True

    def test_leading_p_scaled_fraction_is_flagged(self):
        assert _is_non_integer_picture(_pic("SVPP9(3)")) is True

    def test_trailing_p_scaled_value_is_a_scaled_integer_not_flagged(self):
        # `9(3)PPP` is an integer whose low 3 digits are always zero
        # (123000), not a fraction -- decimal_digits == 0.
        assert _is_non_integer_picture(_pic("9(3)PPP")) is False

    def test_nine_numeric(self):
        assert _classify_picture(_pic("9")) == DataCategory.NUMERIC

    def test_nine_n_numeric(self):
        assert _classify_picture(_pic("9(5)")) == DataCategory.NUMERIC

    def test_s9_numeric(self):
        assert _classify_picture(_pic("S9(7)")) == DataCategory.NUMERIC

    def test_s9v99_numeric(self):
        assert _classify_picture(_pic("S9(5)V9(2)")) == DataCategory.NUMERIC

    def test_z9_numeric_edited(self):
        assert _classify_picture(_pic("Z9")) == DataCategory.NUMERIC_EDITED

    def test_nine_dot_nine_numeric_edited(self):
        assert _classify_picture(_pic("9.9")) == DataCategory.NUMERIC_EDITED

    def test_minus_nine_numeric_edited(self):
        assert _classify_picture(_pic("-9")) == DataCategory.NUMERIC_EDITED

    def test_mixed_x9_alphanumeric(self):
        # X mixed with 9 → alphanumeric
        assert _classify_picture(_pic("X9X")) == DataCategory.ALPHANUMERIC


class TestClassifyLiteral:
    def test_zero_figurative(self):
        assert _classify_literal("ZERO") == DataCategory.FIGURATIVE

    def test_zeros_figurative(self):
        assert _classify_literal("ZEROS") == DataCategory.FIGURATIVE

    def test_zeroes_figurative(self):
        assert _classify_literal("ZEROES") == DataCategory.FIGURATIVE

    def test_space_figurative(self):
        assert _classify_literal("SPACE") == DataCategory.FIGURATIVE

    def test_spaces_figurative(self):
        assert _classify_literal("SPACES") == DataCategory.FIGURATIVE

    def test_high_value_figurative(self):
        assert _classify_literal("HIGH-VALUE") == DataCategory.FIGURATIVE

    def test_low_value_figurative(self):
        assert _classify_literal("LOW-VALUE") == DataCategory.FIGURATIVE

    def test_quoted_string_alphanumeric(self):
        assert _classify_literal('"HELLO"') == DataCategory.ALPHANUMERIC

    def test_single_quoted_string_alphanumeric(self):
        assert _classify_literal("'HELLO'") == DataCategory.ALPHANUMERIC

    def test_numeric_literal(self):
        assert _classify_literal("42") == DataCategory.NUMERIC

    def test_numeric_literal_with_sign(self):
        assert _classify_literal("+100") == DataCategory.NUMERIC

    def test_numeric_literal_decimal(self):
        assert _classify_literal("3.14") == DataCategory.NUMERIC

    def test_unknown_variable(self):
        # An unquoted non-numeric name not in figurative constants → UNKNOWN
        assert _classify_literal("WS-VARIABLE") == DataCategory.UNKNOWN


# ---------------------------------------------------------------------------
# Build AST helpers
# ---------------------------------------------------------------------------


def _make_program_with_items(
    items: list[tuple[str, str]],  # [(name, pic_pattern), ...]
    moves: list[tuple[str, list[str]]],  # [(source, [targets]), ...]
) -> CobolProgram:
    prog = CobolProgram("TEST", _LOC)

    # DATA DIVISION with WORKING-STORAGE section
    data_div = CobolDivision("DATA", _LOC)
    ws_section = CobolSection("WORKING-STORAGE", _LOC)
    for name, pattern in items:
        item = CobolDataItem(name, 1, _LOC)
        item.level = 1
        item.set_picture_clause(PictureClause(pattern, _LOC))
        ws_section.add_data_item(item)
    data_div.add_section(ws_section)
    prog.add_division(data_div)

    # PROCEDURE DIVISION with MOVE statements
    proc_div = CobolDivision("PROCEDURE", _LOC)
    from cobolparser.models.program import CobolParagraph

    para = CobolParagraph("MAIN", _LOC)
    for source, targets in moves:
        stmt = MoveStatement(_LOC)
        stmt.set_source(source)
        for t in targets:
            stmt.add_target(t)
        para.add_statement(stmt)
    proc_div.add_paragraph(para)
    prog.add_division(proc_div)
    return prog


def _check(
    items: list[tuple[str, str]],
    moves: list[tuple[str, list[str]]],
) -> MoveTypeReport:
    prog = _make_program_with_items(items, moves)
    return MoveTypeChecker().check(prog)


# ---------------------------------------------------------------------------
# Legal MOVE combinations — no violations
# ---------------------------------------------------------------------------


class TestLegalMoves:
    def test_numeric_to_numeric(self):
        report = _check(
            [("SRC", "9(5)"), ("TGT", "9(3)")],
            [("SRC", ["TGT"])],
        )
        assert not report.violations

    def test_numeric_to_alphanumeric(self):
        report = _check(
            [("SRC", "9(5)"), ("TGT", "X(10)")],
            [("SRC", ["TGT"])],
        )
        assert not report.violations

    def test_alphanumeric_to_alphanumeric(self):
        report = _check(
            [("SRC", "X(10)"), ("TGT", "X(20)")],
            [("SRC", ["TGT"])],
        )
        assert not report.violations

    def test_alphabetic_to_alphabetic(self):
        report = _check(
            [("SRC", "A(10)"), ("TGT", "A(20)")],
            [("SRC", ["TGT"])],
        )
        assert not report.violations

    def test_alphabetic_to_alphanumeric(self):
        report = _check(
            [("SRC", "A(10)"), ("TGT", "X(20)")],
            [("SRC", ["TGT"])],
        )
        assert not report.violations

    def test_numeric_to_numeric_edited(self):
        report = _check(
            [("SRC", "9(5)"), ("TGT", "Z9")],
            [("SRC", ["TGT"])],
        )
        assert not report.violations

    def test_figurative_fill_constant_to_alphanumeric_is_legal(self):
        report = _check(
            [("TGT", "A(10)")],
            [("SPACES", ["TGT"])],
        )
        # SPACES has no digit value but fills an alphabetic receiver fine.
        assert not report.violations
        assert report.unresolved_count == 0

    def test_unknown_source_skipped(self):
        # Source not in catalog and not a recognizable literal → UNKNOWN → skip
        report = _check(
            [("TGT", "9(5)")],
            [("SOME-UNKNOWN-VAR", ["TGT"])],
        )
        assert not report.violations

    def test_unknown_target_skipped(self):
        report = _check(
            [("SRC", "9(5)")],
            [("SRC", ["UNKNOWN-TGT"])],
        )
        assert not report.violations


# ---------------------------------------------------------------------------
# Illegal MOVE combinations — ERROR
# ---------------------------------------------------------------------------


class TestIllegalMoves:
    def test_numeric_to_alphabetic_is_error(self):
        report = _check(
            [("SRC", "9(5)"), ("TGT", "A(10)")],
            [("SRC", ["TGT"])],
        )
        assert report.has_errors
        err = report.errors[0]
        assert err.kind == MoveViolationKind.ERROR
        assert err.source_category == DataCategory.NUMERIC
        assert err.target_category == DataCategory.ALPHABETIC

    def test_alphabetic_to_numeric_is_error(self):
        report = _check(
            [("SRC", "A(10)"), ("TGT", "9(5)")],
            [("SRC", ["TGT"])],
        )
        assert report.has_errors
        assert report.errors[0].source_category == DataCategory.ALPHABETIC
        assert report.errors[0].target_category == DataCategory.NUMERIC

    def test_numeric_edited_to_alphabetic_is_error(self):
        report = _check(
            [("SRC", "Z9"), ("TGT", "A(10)")],
            [("SRC", ["TGT"])],
        )
        assert report.has_errors

    def test_alphabetic_to_numeric_edited_is_error(self):
        report = _check(
            [("SRC", "A(10)"), ("TGT", "Z9")],
            [("SRC", ["TGT"])],
        )
        assert report.has_errors


# ---------------------------------------------------------------------------
# Warning-level MOVE combinations
# ---------------------------------------------------------------------------


class TestWarningMoves:
    def test_alphanumeric_to_numeric_is_warning(self):
        report = _check(
            [("SRC", "X(10)"), ("TGT", "9(5)")],
            [("SRC", ["TGT"])],
        )
        assert report.warnings
        w = report.warnings[0]
        assert w.kind == MoveViolationKind.WARNING
        assert w.source_category == DataCategory.ALPHANUMERIC
        assert w.target_category == DataCategory.NUMERIC

    def test_alphanumeric_to_numeric_edited_is_warning(self):
        report = _check(
            [("SRC", "X(10)"), ("TGT", "Z9")],
            [("SRC", ["TGT"])],
        )
        assert report.warnings

    def test_numeric_edited_to_numeric_is_warning(self):
        report = _check(
            [("SRC", "Z9"), ("TGT", "9(5)")],
            [("SRC", ["TGT"])],
        )
        assert report.warnings


# ---------------------------------------------------------------------------
# Multiple targets
# ---------------------------------------------------------------------------


class TestMultipleTargets:
    def test_one_good_one_bad_target(self):
        # SRC numeric → TGT-OK numeric (no violation) + TGT-BAD alphabetic (error)
        report = _check(
            [("SRC", "9(5)"), ("TGT-OK", "9(3)"), ("TGT-BAD", "A(10)")],
            [("SRC", ["TGT-OK", "TGT-BAD"])],
        )
        assert report.has_errors
        assert len(report.errors) == 1
        assert report.errors[0].target_name == "TGT-BAD"


# ---------------------------------------------------------------------------
# Report properties
# ---------------------------------------------------------------------------


class TestMoveTypeReport:
    def test_errors_property_filters_correctly(self):
        report = _check(
            [("SRC", "9(5)"), ("TGT", "A(10)")],
            [("SRC", ["TGT"])],
        )
        assert all(v.kind == MoveViolationKind.ERROR for v in report.errors)

    def test_warnings_property_filters_correctly(self):
        report = _check(
            [("SRC", "X(5)"), ("TGT", "9(5)")],
            [("SRC", ["TGT"])],
        )
        assert all(v.kind == MoveViolationKind.WARNING for v in report.warnings)

    def test_to_dict_is_json_serializable(self):
        report = _check(
            [("SRC", "9(5)"), ("TGT", "A(10)")],
            [("SRC", ["TGT"])],
        )
        json.dumps(report.to_dict())

    def test_to_dict_structure(self):
        report = _check([], [])
        d = report.to_dict()
        assert "error_count" in d
        assert "warning_count" in d
        assert "violations" in d

    def test_violation_to_dict_includes_location(self):
        report = _check(
            [("SRC", "9(5)"), ("TGT", "A(10)")],
            [("SRC", ["TGT"])],
        )
        v_dict = report.violations[0].to_dict()
        assert "source" in v_dict
        assert "target" in v_dict
        assert "source_category" in v_dict
        assert "target_category" in v_dict
        assert "message" in v_dict


# ---------------------------------------------------------------------------
# get_catalog()
# ---------------------------------------------------------------------------


class TestGetCatalog:
    def test_catalog_contains_known_items(self):
        prog = _make_program_with_items([("MY-FIELD", "9(5)")], [])
        checker = MoveTypeChecker()
        checker.check(prog)
        catalog = checker.get_catalog()
        assert "MY-FIELD" in catalog
        assert catalog["MY-FIELD"] == "NUMERIC"

    def test_catalog_empty_before_check(self):
        checker = MoveTypeChecker()
        assert checker.get_catalog() == {}


# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------


class TestExports:
    def test_exported_from_package(self):
        from cobolparser import DataCategory as DC
        from cobolparser import MoveTypeChecker as C
        from cobolparser import MoveTypeReport as R
        from cobolparser import MoveTypeViolation as V
        from cobolparser import MoveViolationKind as K

        assert C is MoveTypeChecker
        assert R is MoveTypeReport
        assert V is MoveTypeViolation
        assert K is MoveViolationKind
        assert DC is DataCategory


# ---------------------------------------------------------------------------
# Round-trip via parse_cobol()
# ---------------------------------------------------------------------------


class TestMoveTypeCheckerRoundTrip:
    def test_valid_program_no_errors(self):
        src = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-NUM PIC 9(5).
       01 WS-ALPHA PIC X(10).
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           MOVE 12345 TO WS-NUM
           MOVE 'HELLO' TO WS-ALPHA
           STOP RUN.
"""
        result = parse_cobol(src)
        assert result.ast is not None
        report = MoveTypeChecker().check(result.ast)
        assert not report.has_errors

    def test_illegal_move_detected_in_parsed_program(self):
        src = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-NUM PIC 9(5).
       01 WS-ALPHA PIC A(10).
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           MOVE WS-NUM TO WS-ALPHA
           STOP RUN.
"""
        result = parse_cobol(src)
        assert result.ast is not None
        report = MoveTypeChecker().check(result.ast)
        assert report.has_errors


# ---------------------------------------------------------------------------
# Additional edge cases
# ---------------------------------------------------------------------------


class TestPictureVariants:
    """Additional PIC patterns not covered by basic classification tests."""

    def test_repeated_nine_numeric(self):
        # 999 (no parens) → NUMERIC
        assert _classify_picture(_pic("999")) == DataCategory.NUMERIC

    def test_sv_decimal_numeric(self):
        assert _classify_picture(_pic("S9(3)V9(2)")) == DataCategory.NUMERIC

    def test_xbx_alphanumeric_edited(self):
        assert _classify_picture(_pic("XBX")) == DataCategory.ALPHANUMERIC_EDITED

    def test_dollar_z_numeric_edited(self):
        # $ZZZ.99 contains edit chars → NUMERIC_EDITED
        assert _classify_picture(_pic("$ZZZ.99")) == DataCategory.NUMERIC_EDITED

    def test_nine_slash_nine_numeric_edited(self):
        # Date patterns like 99/99/99
        assert _classify_picture(_pic("99/99/99")) == DataCategory.NUMERIC_EDITED

    def test_a_with_space_in_pattern_alphabetic(self):
        # A(5) → ALPHABETIC
        assert _classify_picture(_pic("A(5)")) == DataCategory.ALPHABETIC

    def test_repeated_a_alphabetic(self):
        # AAA / AAAAA must be ALPHABETIC, not ALPHANUMERIC (regression for
        # the original regex that only matched ^A(\(\d+\))?$)
        assert _classify_picture(_pic("AAA")) == DataCategory.ALPHABETIC
        assert _classify_picture(_pic("AAAAA")) == DataCategory.ALPHABETIC

    def test_nine_with_large_repetition_is_numeric(self):
        # 9(10) and S9(20) must be NUMERIC, not NUMERIC_EDITED.
        # The '0' in the repetition count must not trigger the edit-char check.
        assert _classify_picture(_pic("9(10)")) == DataCategory.NUMERIC
        assert _classify_picture(_pic("S9(20)")) == DataCategory.NUMERIC
        assert _classify_picture(_pic("9(10)V9(2)")) == DataCategory.NUMERIC

    def test_nine_in_repeat_count_is_not_a_digit_position(self):
        # Regression #336: the 9 in X(9) / A(9) is a repeat count, not a
        # digit, so these must classify like their X(10) / A(10) siblings.
        for pattern in ("X(9)BX(9)", "X(10)BX(10)", "A(9)B", "X(9)0", "X(19)/X"):
            assert (
                _classify_picture(_pic(pattern)) == DataCategory.ALPHANUMERIC_EDITED
            ), pattern

    def test_digit_positions_still_numeric_edited(self):
        assert _classify_picture(_pic("9(9)B9(9)")) == DataCategory.NUMERIC_EDITED
        assert _classify_picture(_pic("Z(9).99")) == DataCategory.NUMERIC_EDITED

    def test_repeat_count_nine_moves_match_x10_variant(self):
        # The four MOVEs from issue #336, through a real parse.
        src = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-ALPHA PIC A(5).
       01 WS-AN    PIC X(5).
       01 WS-DEC   PIC 9(3)V99.
       01 WS-XE    PIC X(9)BX(9).
       01 WS-XE2   PIC X(10)BX(10).
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           MOVE WS-ALPHA TO {t}
           MOVE WS-AN TO {t}
           MOVE WS-DEC TO {t}
           MOVE {t} TO WS-DEC
           STOP RUN.
"""

        def findings(target):
            result = parse_cobol(src.format(t=target))
            assert result.ast is not None
            report = MoveTypeChecker().check(result.ast)
            return sorted(
                (
                    "T" if v.source_name == target else v.source_name,
                    "T" if v.target_name == target else v.target_name,
                    v.kind.name,
                    v.target_category.name,
                )
                for v in report.violations
            )

        xe = findings("WS-XE")
        assert xe == findings("WS-XE2")
        assert ("WS-DEC", "T", "ERROR", "ALPHANUMERIC_EDITED") in xe
        assert not any(t == "T" and k != "ERROR" for _, t, k, _ in xe)


class TestLiteralSourceMoves:
    """MOVE with a literal source (not a data item name)."""

    def test_numeric_literal_to_numeric_no_error(self):
        report = _check(
            [("TGT", "9(5)")],
            [("12345", ["TGT"])],
        )
        assert not report.violations

    def test_numeric_literal_to_alphabetic_is_error(self):
        report = _check(
            [("TGT", "A(10)")],
            [("42", ["TGT"])],
        )
        assert report.has_errors
        assert report.errors[0].source_category == DataCategory.NUMERIC
        assert report.errors[0].target_category == DataCategory.ALPHABETIC

    def test_string_literal_to_numeric_is_warning(self):
        report = _check(
            [("TGT", "9(5)")],
            [('"HELLO"', ["TGT"])],
        )
        assert report.warnings
        assert report.warnings[0].source_category == DataCategory.ALPHANUMERIC
        assert report.warnings[0].target_category == DataCategory.NUMERIC

    def test_string_literal_to_alphanumeric_no_error(self):
        report = _check(
            [("TGT", "X(10)")],
            [('"HELLO"', ["TGT"])],
        )
        assert not report.violations

    def test_string_literal_to_alphabetic_no_error(self):
        # Quoted string is ALPHANUMERIC; ALPHANUMERIC → ALPHABETIC not in the
        # illegal or warning sets, so no violation
        report = _check(
            [("TGT", "A(10)")],
            [('"ABCDE"', ["TGT"])],
        )
        assert not report.violations


class TestMoveCorresponding:
    """MOVE CORRESPONDING sets is_corresponding=True; checker must not error."""

    def test_corresponding_move_no_error(self):
        prog = _make_program_with_items(
            [("SRC", "9(5)"), ("TGT", "A(10)")],
            [],
        )
        # Manually build a CORRESPONDING MOVE that would normally be illegal
        from cobolparser.models.program import CobolParagraph
        from cobolparser.models.statements import MoveStatement

        loc = SourceLocation(1, 1)
        stmt = MoveStatement(loc)
        stmt.set_source("SRC")
        stmt.set_corresponding(True)
        stmt.add_target("TGT")
        # Inject into the procedure division
        para = CobolParagraph("EXTRA-PARA", loc)
        para.add_statement(stmt)
        prog.procedure_division.add_paragraph(para)

        report = MoveTypeChecker().check(prog)
        # CORRESPONDING moves are structural; skip category checking on them
        assert not report.has_errors


class TestMoveEmptyOperands:
    """Moves with missing source or empty targets must not crash."""

    def test_empty_source_skipped(self):
        prog = _make_program_with_items([("TGT", "9(5)")], [])
        from cobolparser.models.program import CobolParagraph
        from cobolparser.models.statements import MoveStatement

        loc = SourceLocation(1, 1)
        stmt = MoveStatement(loc)
        stmt.set_source("")  # empty
        stmt.add_target("TGT")
        para = CobolParagraph("P", loc)
        para.add_statement(stmt)
        prog.procedure_division.add_paragraph(para)
        report = MoveTypeChecker().check(prog)
        assert not report.violations

    def test_no_targets_no_crash(self):
        prog = _make_program_with_items([("SRC", "9(5)")], [])
        from cobolparser.models.program import CobolParagraph
        from cobolparser.models.statements import MoveStatement

        loc = SourceLocation(1, 1)
        stmt = MoveStatement(loc)
        stmt.set_source("SRC")
        # deliberately add no targets
        para = CobolParagraph("P", loc)
        para.add_statement(stmt)
        prog.procedure_division.add_paragraph(para)
        report = MoveTypeChecker().check(prog)
        assert not report.violations


class TestCheckerStateReset:
    """check() must reset its internal catalog between calls."""

    def test_second_call_replaces_catalog(self):
        checker = MoveTypeChecker()
        prog1 = _make_program_with_items([("FIRST-FIELD", "9(5)")], [])
        checker.check(prog1)
        assert "FIRST-FIELD" in checker.get_catalog()

        prog2 = _make_program_with_items([("SECOND-FIELD", "X(10)")], [])
        checker.check(prog2)
        # Old catalog must be gone
        assert "FIRST-FIELD" not in checker.get_catalog()
        assert "SECOND-FIELD" in checker.get_catalog()

    def test_second_call_violations_are_independent(self):
        checker = MoveTypeChecker()
        # First call: no violations
        checker.check(
            _make_program_with_items([("N", "9(5)"), ("X", "X(5)")], [("N", ["X"])])
        )

        # Second call: illegal move
        report = checker.check(
            _make_program_with_items([("N", "9(5)"), ("A", "A(10)")], [("N", ["A"])])
        )
        assert report.has_errors
        # Only the second call's violation
        assert len(report.violations) == 1


class TestNestedDataItems:
    """Data items nested inside a group item must also be catalogued."""

    def test_elementary_child_catalogued(self):
        from cobolparser.models.program import CobolParagraph

        loc = SourceLocation(1, 1)
        prog = CobolProgram("TEST", loc)
        data_div = CobolDivision("DATA", loc)
        ws = CobolSection("WORKING-STORAGE", loc)

        # Build group: 01 GROUP → 05 CHILD PIC 9(5)
        group = CobolDataItem("GROUP-ITEM", 1, loc)
        child = CobolDataItem("CHILD-ITEM", 5, loc)
        child.set_picture_clause(PictureClause("9(5)", loc))
        group.add_child(child)
        ws.add_data_item(group)
        data_div.add_section(ws)
        prog.add_division(data_div)
        proc_div = CobolDivision("PROCEDURE", loc)
        proc_div.add_paragraph(CobolParagraph("MAIN", loc))
        prog.add_division(proc_div)

        checker = MoveTypeChecker()
        checker.check(prog)
        catalog = checker.get_catalog()
        assert "CHILD-ITEM" in catalog
        assert catalog["CHILD-ITEM"] == "NUMERIC"


# ---------------------------------------------------------------------------
# Special registers (RETURN-CODE, TALLY, LINAGE-COUNTER) -- fixed numeric
# category, never declared with a PICTURE clause of their own.
# ---------------------------------------------------------------------------


class TestSpecialRegisters:
    def test_return_code_target_resolves_numeric(self):
        report = _check([("SRC", "9(5)")], [("SRC", ["RETURN-CODE"])])
        assert report.unresolved_count == 0
        assert not report.violations

    def test_return_code_source_resolves_numeric(self):
        report = _check([("TGT", "9(5)")], [("RETURN-CODE", ["TGT"])])
        assert report.unresolved_count == 0
        assert not report.violations

    def test_figurative_zero_to_return_code_is_legal(self):
        # ZERO has a digit value, so it is a legal source for the numeric
        # RETURN-CODE special register -- genuinely checked, not skipped.
        report = _check([], [("ZERO", ["RETURN-CODE"])])
        assert report.unresolved_count == 0
        assert not report.violations

    def test_alphabetic_to_return_code_is_error(self):
        report = _check([("SRC", "A(5)")], [("SRC", ["RETURN-CODE"])])
        assert report.has_errors
        assert report.errors[0].source_category == DataCategory.ALPHABETIC
        assert report.errors[0].target_category == DataCategory.NUMERIC

    def test_tally_and_linage_counter_resolve_numeric(self):
        report = _check(
            [("SRC", "9(5)")],
            [("SRC", ["TALLY"]), ("SRC", ["LINAGE-COUNTER"])],
        )
        assert report.unresolved_count == 0
        assert not report.violations


# ---------------------------------------------------------------------------
# Intrinsic FUNCTION results with a category fixed by the COBOL standard.
# ---------------------------------------------------------------------------


class TestIntrinsicFunctionSources:
    def test_function_current_date_resolves_alphanumeric(self):
        report = _check([("TGT", "X(21)")], [("FUNCTION CURRENT-DATE", ["TGT"])])
        assert report.unresolved_count == 0
        assert not report.violations

    def test_function_when_compiled_resolves_alphanumeric(self):
        report = _check([("TGT", "X(21)")], [("FUNCTION WHEN-COMPILED", ["TGT"])])
        assert report.unresolved_count == 0
        assert not report.violations

    def test_function_current_date_to_numeric_is_warning(self):
        report = _check([("TGT", "9(5)")], [("FUNCTION CURRENT-DATE", ["TGT"])])
        assert report.warnings

    def test_unrecognized_function_still_unresolved(self):
        # Only the specific intrinsic functions this checker knows are
        # classified; anything else correctly stays unresolved rather than
        # guessing at its category.
        report = _check([("TGT", "9(5)")], [("FUNCTION SOME-OTHER-FUNC", ["TGT"])])
        assert report.unresolved_count == 1


# ---------------------------------------------------------------------------
# Figurative constant MOVE sources -- ZERO has a digit value and is legal
# into any receiver; the "fill" constants (SPACES, HIGH-VALUE, LOW-VALUE,
# QUOTE) are legal everywhere except a numeric/numeric-edited receiver; NULL
# stays unresolved (legal only into a POINTER receiver, unmodeled here).
# ---------------------------------------------------------------------------


class TestFigurativeConstantMoves:
    def test_zero_to_numeric_is_legal(self):
        report = _check([("TGT", "9(5)")], [("ZERO", ["TGT"])])
        assert report.unresolved_count == 0
        assert not report.violations

    def test_zero_to_alphanumeric_is_legal(self):
        report = _check([("TGT", "X(5)")], [("ZERO", ["TGT"])])
        assert report.unresolved_count == 0
        assert not report.violations

    def test_zeros_to_numeric_edited_is_legal(self):
        report = _check([("TGT", "Z9")], [("ZEROS", ["TGT"])])
        assert report.unresolved_count == 0
        assert not report.violations

    def test_spaces_to_numeric_is_error(self):
        report = _check([("TGT", "9(5)")], [("SPACES", ["TGT"])])
        assert report.unresolved_count == 0
        assert report.has_errors
        assert report.errors[0].source_category == DataCategory.FIGURATIVE
        assert report.errors[0].target_category == DataCategory.NUMERIC

    def test_spaces_to_numeric_edited_is_error(self):
        report = _check([("TGT", "Z9")], [("SPACES", ["TGT"])])
        assert report.has_errors

    def test_high_value_to_numeric_is_error(self):
        report = _check([("TGT", "9(5)")], [("HIGH-VALUE", ["TGT"])])
        assert report.has_errors

    def test_low_values_to_numeric_is_error(self):
        report = _check([("TGT", "9(5)")], [("LOW-VALUES", ["TGT"])])
        assert report.has_errors

    def test_quote_to_numeric_is_error(self):
        report = _check([("TGT", "9(5)")], [("QUOTE", ["TGT"])])
        assert report.has_errors

    def test_spaces_to_alphabetic_is_legal(self):
        report = _check([("TGT", "A(5)")], [("SPACES", ["TGT"])])
        assert report.unresolved_count == 0
        assert not report.violations

    def test_null_source_still_unresolved(self):
        # NULL is only legal into a POINTER receiving item, a category this
        # checker does not model -- left unresolved rather than guessed at.
        report = _check([("TGT", "9(5)")], [("NULL", ["TGT"])])
        assert report.unresolved_count == 1
        assert not report.violations


# ---------------------------------------------------------------------------
# Group-item MOVE operands -- a group with no PICTURE of its own is always
# treated as alphanumeric, per COBOL's elementary-move rule.
# ---------------------------------------------------------------------------


class TestGroupItemMoveOperand:
    def _group_program(self):
        from cobolparser.models.program import CobolParagraph

        loc = SourceLocation(1, 1)
        prog = CobolProgram("TEST", loc)
        data_div = CobolDivision("DATA", loc)
        ws = CobolSection("WORKING-STORAGE", loc)

        # 01 WS-DATE-TIME → 05 WS-YEAR PIC 9(4) (a group with no PIC of its own)
        group = CobolDataItem("WS-DATE-TIME", 1, loc)
        child = CobolDataItem("WS-YEAR", 5, loc)
        child.set_picture_clause(PictureClause("9(4)", loc))
        group.add_child(child)
        ws.add_data_item(group)

        for name, pattern in [
            ("WS-ALPHA", "X(10)"),
            ("WS-NUM", "9(5)"),
            ("WS-ALPHABETIC", "A(5)"),
        ]:
            item = CobolDataItem(name, 1, loc)
            item.set_picture_clause(PictureClause(pattern, loc))
            ws.add_data_item(item)

        data_div.add_section(ws)
        prog.add_division(data_div)

        proc_div = CobolDivision("PROCEDURE", loc)
        para = CobolParagraph("MAIN", loc)
        proc_div.add_paragraph(para)
        prog.add_division(proc_div)
        return prog, para

    def test_group_item_catalogued_as_alphanumeric(self):
        prog, _ = self._group_program()
        checker = MoveTypeChecker()
        checker.check(prog)
        assert checker.get_catalog()["WS-DATE-TIME"] == "ALPHANUMERIC"

    def test_move_to_group_item_target_not_unresolved(self):
        prog, para = self._group_program()
        stmt = MoveStatement(SourceLocation(1, 1))
        stmt.set_source("WS-ALPHA")
        stmt.add_target("WS-DATE-TIME")
        para.add_statement(stmt)

        report = MoveTypeChecker().check(prog)
        assert report.unresolved_count == 0
        assert not report.violations

    def test_move_group_item_source_to_numeric_is_warning(self):
        prog, para = self._group_program()
        stmt = MoveStatement(SourceLocation(1, 1))
        stmt.set_source("WS-DATE-TIME")
        stmt.add_target("WS-NUM")
        para.add_statement(stmt)

        report = MoveTypeChecker().check(prog)
        assert report.unresolved_count == 0
        assert report.warnings

    def test_move_alphabetic_to_group_item_is_legal(self):
        prog, para = self._group_program()
        stmt = MoveStatement(SourceLocation(1, 1))
        stmt.set_source("WS-ALPHABETIC")
        stmt.add_target("WS-DATE-TIME")
        para.add_statement(stmt)

        report = MoveTypeChecker().check(prog)
        assert report.unresolved_count == 0
        assert not report.violations


def _check_source(data: str, move: str) -> MoveTypeReport:
    src = (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. T.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        f"{data}"
        "       PROCEDURE DIVISION.\n"
        f"           {move}.\n"
        "           STOP RUN.\n"
    )
    result = parse_cobol(src)
    assert result.ast is not None, result.errors
    return MoveTypeChecker().check(result.ast)


class TestGroupReceiverAndZeroToAlphabetic:
    """Cross-checked against GnuCOBOL's own MOVE legality check."""

    _GROUP = (
        "       01 ND PIC 9(3)V99.\n"
        "       01 GR.\n"
        "          05 GR-A PIC X(2).\n"
        "          05 GR-B PIC 9(2).\n"
    )

    def test_non_integer_into_a_group_is_a_legal_group_move(self):
        assert not _check_source(self._GROUP, "MOVE ND TO GR").violations
        assert not _check_source(self._GROUP, "MOVE 12.5 TO GR").violations

    def test_non_integer_into_an_alphanumeric_item_is_still_illegal(self):
        report = _check_source(
            self._GROUP + "       01 AN PIC X(5).\n", "MOVE ND TO AN"
        )
        assert report.has_errors

    def test_zero_into_alphabetic_is_illegal(self):
        report = _check_source("       01 AB PIC A(5).\n", "MOVE ZERO TO AB")
        assert report.has_errors
        assert "ALPHABETIC" in report.errors[0].message

    def test_zero_into_alphanumeric_is_legal(self):
        assert not _check_source(
            "       01 AN PIC X(5).\n", "MOVE ZEROS TO AN"
        ).violations


class TestSubscriptedAndReferenceModifiedOperands:
    """The MOVE parser folds a source operand with its subscript /
    reference-modification glued on (``T-E(2)``, ``WS-A(1:3)``); those missed
    the catalog, so the MOVE went silently unchecked. A reference-modified
    operand is alphanumeric whatever its base item is."""

    SOURCE = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. REFMOD.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-A PIC X(10).
       01 WS-N PIC 9(5).
       01 WS-D PIC 9(3)V99.
       01 WS-AL PIC A(5).
       01 TBL.
          05 T-E PIC X(4) OCCURS 10 INDEXED BY IX.
       PROCEDURE DIVISION.
           MOVE WS-A(1:3) TO WS-N
           MOVE T-E(2) TO WS-N
           MOVE T-E(IX)(1:2) TO WS-N
           MOVE WS-A TO WS-N(2:3)
           MOVE WS-D(1:2) TO WS-A
           MOVE WS-N(1:2) TO WS-AL
           STOP RUN.
"""

    def test_verdicts(self):
        result = parse_cobol(self.SOURCE)
        report = MoveTypeChecker().check(result.ast)
        found = [(v.location.line, v.kind, v.source_name) for v in report.violations]
        assert found == [
            (12, MoveViolationKind.WARNING, "WS-A(1:3)"),
            (13, MoveViolationKind.WARNING, "T-E(2)"),
            (14, MoveViolationKind.WARNING, "T-E(IX)(1:2)"),
        ]
        assert report.to_dict()["unresolved_count"] == 0


# ---------------------------------------------------------------------------
# Intrinsic FUNCTION sending operands with arguments (issue #291): the
# result category comes from the intrinsic catalog, or from the first
# argument for TRIM / ABS / MAX / MIN / USUBSTR, instead of being counted as
# an unresolved operand that the lint caveat blamed on a missing COPY.
# ---------------------------------------------------------------------------


class TestIntrinsicFunctionsWithArguments:
    SOURCE = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. FUNCS.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 GRP.
          05 WS-X PIC X(10).
       01 WS-Y PIC X(10).
       01 WS-N PIC 9(5).
       01 WS-AL PIC A(5).
       01 TBL.
          05 T-E PIC 9(3)V9 OCCURS 5.
       PROCEDURE DIVISION.
           MOVE FUNCTION TRIM(WS-X) TO WS-Y
           MOVE FUNCTION TRIM ( WS-X OF GRP LEADING ) TO WS-Y
           MOVE FUNCTION LENGTH(T-E(1)) TO WS-N
           MOVE FUNCTION UPPER-CASE(WS-X) TO WS-AL
           MOVE FUNCTION CURRENT-DATE(1:8) TO WS-Y
           MOVE FUNCTION UPPER-CASE(WS-X)(1:3) TO WS-Y
           MOVE FUNCTION TRIM("A B") TO WS-Y
           MOVE FUNCTION NUMVAL(WS-X) TO WS-AL
           MOVE FUNCTION MAX(T-E(1), T-E(2)) TO WS-Y
           MOVE FUNCTION INTEGER(T-E(1)) TO WS-Y
           STOP RUN.
"""

    def test_every_function_source_is_checked(self):
        report = MoveTypeChecker().check(parse_cobol(self.SOURCE).ast)
        assert report.unresolved_count == 0
        assert report.unresolved_function_count == 0

    def test_verdicts_follow_the_return_category(self):
        report = MoveTypeChecker().check(parse_cobol(self.SOURCE).ast)
        found = [(v.location.line, v.kind, v.source_name) for v in report.violations]
        assert found == [
            # NUMVAL is numeric: illegal into an alphabetic item.
            (20, MoveViolationKind.ERROR, "FUNCTION NUMVAL(WS-X)"),
            # MAX takes its arguments' class: a non-integer numeric here,
            # which may not go to an alphanumeric item.
            (21, MoveViolationKind.ERROR, "FUNCTION MAX(T-E(1), T-E(2))"),
        ]

    def test_argument_class_function_with_unresolved_argument(self):
        # The argument may come from a COPY that was not expanded, so this
        # one is an ordinary unresolved operand, not a function caveat.
        report = _check([("TGT", "X(5)")], [("FUNCTION TRIM(MISSING)", ["TGT"])])
        assert report.unresolved_count == 1
        assert report.unresolved_function_count == 0

    def test_national_and_uncatalogued_functions_count_as_function_gaps(self):
        report = _check(
            [("SRC", "X(5)"), ("TGT", "X(5)")],
            [
                ("FUNCTION NATIONAL-OF(SRC)", ["TGT"]),
                ("FUNCTION SOME-OTHER-FUNC(SRC)", ["TGT"]),
            ],
        )
        assert report.unresolved_count == 2
        assert report.unresolved_function_count == 2
        assert report.to_dict()["unresolved_function_count"] == 2


class TestNumericFunctionIntegerness:
    """A numeric intrinsic's integer-ness is known only when its arguments
    decide it, by one rule for SUM / REM / RANGE / MAX / MIN / ABS: any
    non-integer argument makes a non-integer result, all-integer arguments an
    integer one. Otherwise (NUMVAL, ...) a MOVE of it to an alphanumeric item
    is a function caveat, never a guessed ERROR."""

    SOURCE = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. NUMFN.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-I1 PIC 9(3).
       01 WS-I2 PIC 9(3).
       01 WS-D PIC 9(3)V99.
       01 WS-F COMP-2.
       01 WS-X PIC X(10).
       01 WS-Y PIC X(10).
       01 WS-N PIC 9(5).
       01 WS-AL PIC A(5).
       01 WS-NAT PIC N(5).
       PROCEDURE DIVISION.
           MOVE FUNCTION SUM(WS-I1 WS-I2) TO WS-Y
           MOVE FUNCTION REM(WS-I1 WS-I2) TO WS-Y
           MOVE FUNCTION RANGE(WS-I1, 7) TO WS-Y
           MOVE FUNCTION NUMVAL(WS-X) TO WS-Y
           MOVE FUNCTION SUM(WS-I1 WS-D) TO WS-Y
           MOVE FUNCTION SUM(WS-F WS-I1) TO WS-Y
           MOVE FUNCTION MAX(WS-I1 WS-D) TO WS-Y
           MOVE FUNCTION NUMVAL(WS-X) TO WS-N
           MOVE FUNCTION NUMVAL(WS-X) TO WS-AL
           MOVE FUNCTION MAX(WS-I1 FUNCTION NUMVAL(WS-X)) TO WS-Y
           MOVE FUNCTION UPPER-CASE(WS-NAT) TO WS-Y
           MOVE FUNCTION TRIM(WS-NAT) TO WS-Y
           STOP RUN.
"""

    def _report(self):
        return MoveTypeChecker().check(parse_cobol(self.SOURCE).ast)

    def test_non_integer_arguments_and_alphabetic_receivers_are_errors(self):
        found = [(v.location.line, v.source_name) for v in self._report().violations]
        assert found == [
            (19, "FUNCTION SUM(WS-I1 WS-D)"),
            (20, "FUNCTION SUM(WS-F WS-I1)"),
            (21, "FUNCTION MAX(WS-I1 WS-D)"),
            (23, "FUNCTION NUMVAL(WS-X)"),
        ]
        assert all(v.kind == MoveViolationKind.ERROR for v in self._report().violations)

    def test_undecidable_results_are_function_caveats(self):
        report = self._report()
        # NUMVAL -> X and MAX over a NUMVAL -> X (integer-ness unknown), and
        # UPPER-CASE / TRIM of a national item (a national result): every
        # skipped MOVE here is the function's, none is a missing COPY's.
        assert report.unresolved_function_count == 4
        assert report.unresolved_count == 4
