"""Regressions for the defects found by the 2026-09-07 repo audit.

Each test names the thing that used to be silently wrong, so a reappearance
is legible from the failure alone rather than from a diff. See
`reports/audit-2026-09-07.md` for the reproductions these were derived from.
"""

from __future__ import annotations

from cobolparser import UnusedVariableAnalyzer, parse_cobol
from cobolparser.analysis.boundary_inventory import BoundaryInventoryAnalyzer
from cobolparser.analysis.constraints import ConstraintExtractor
from cobolparser.analysis.domains import Unsatisfiable, Witness, solve
from cobolparser.generators.data.options import DataGeneratorOptions
from cobolparser.generators.data.program_layout import ProgramLayoutIndex
from cobolparser.generators.data.views import build_record_views

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _ast(source: str):
    result = parse_cobol(source, filename="audit.cbl")
    assert result.ast is not None, result.errors
    return result.ast


def _constraints(source: str):
    ast = _ast(source)
    index = ProgramLayoutIndex.build(ast)
    boundaries = BoundaryInventoryAnalyzer().analyze(ast, index)
    return ConstraintExtractor().extract(ast, index, boundaries)


def _record(source: str):
    ast = _ast(source)
    return next(
        item for item in ast.find_all_by_type("CobolDataItem") if item.level == 1
    )


def _unused(source: str) -> list[str]:
    report = UnusedVariableAnalyzer().analyze(_ast(source))
    return sorted(item.name.upper() for item in report.unused_items)


_DATA_HEADER = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. AUDIT.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
"""


# ---------------------------------------------------------------------------
# H1 -- a non-literal comparison operand is not a value
# ---------------------------------------------------------------------------


class TestH1NonLiteralOperand:
    """`IF WS-IN = WS-E (IDX)` used to become `WS-IN eq 'WS-E ( IDX )'`.

    The layout index cannot resolve a subscripted operand, so the extractor
    fell through to its "right side is a literal" branch and used the
    operand's own source text as the compared-against value. Nothing landed
    in `unsupported`, the arm was counted as targeted, and the negated arm
    was trivially satisfied by any generated value -- so a scenario that
    never reaches its branch was stamped verified.
    """

    SOURCE = _DATA_HEADER + """\
       01  WS-IN     PIC 9(4).
       01  WS-TAB.
           05 WS-E OCCURS 3 TIMES PIC 9(4).
       01  IDX       PIC 9(1) VALUE 1.
       PROCEDURE DIVISION.
       MAIN.
           ACCEPT WS-IN
           IF WS-IN = WS-E (IDX)
               DISPLAY "B"
           END-IF
           STOP RUN.
"""

    def test_subscripted_operand_yields_no_constraint(self):
        report = _constraints(self.SOURCE)
        for branch in report.branches:
            for constraints in branch.arms.values():
                for constraint in constraints:
                    assert (
                        "WS-E" not in constraint.values[0]
                    ), "the operand's source text was used as a literal value"

    def test_the_gap_is_reported_rather_than_fabricated(self):
        report = _constraints(self.SOURCE)
        assert any(
            "non-literal operand" in reason for reason in report.unsupported
        ), report.unsupported

    def test_a_real_literal_still_builds_a_constraint(self):
        """The guard is a whitelist, so the forms that must keep working are
        pinned here: quoted, integer, decimal, and a negative (whose sign
        reaches the extractor as its own token, `- 45`, and is stored
        reattached as `-45` -- the 2026-09-09 review found the spaced form
        made the solver drop the constraint)."""
        for literal, expected in [
            ('"AB"', "AB"),
            ("'AB'", "AB"),
            ("123", "123"),
            ("-45", "-45"),
            ("1.5", "1.5"),
        ]:
            source = _DATA_HEADER + f"""\
       01  WS-T PIC X(6).
       PROCEDURE DIVISION.
       MAIN.
           ACCEPT WS-T
           IF WS-T = {literal}
               DISPLAY "x"
           END-IF
           STOP RUN.
"""
            report = _constraints(source)
            values = [
                constraint.values[0]
                for branch in report.branches
                for constraints in branch.arms.values()
                for constraint in constraints
            ]
            assert expected in values, f"{literal} produced {values}"

    def test_evaluate_when_naming_a_data_item_is_not_a_literal(self):
        """The lexer unquotes a selector before it reaches the extractor, so
        `WHEN "AB"` and `WHEN WS-OTHER` arrive identical. Whether the value
        names a real data item is the only discriminator left."""
        source = _DATA_HEADER + """\
       01  WS-CODE  PIC X(3).
       01  WS-OTHER PIC X(3) VALUE 'ZZZ'.
       PROCEDURE DIVISION.
       MAIN.
           ACCEPT WS-CODE
           EVALUATE WS-CODE
               WHEN "AB"     DISPLAY "1"
               WHEN WS-OTHER DISPLAY "2"
           END-EVALUATE
           STOP RUN.
"""
        report = _constraints(source)
        values = [
            constraint.values[0]
            for branch in report.branches
            for constraints in branch.arms.values()
            for constraint in constraints
        ]
        assert "AB" in values, "a genuine literal selector must still work"
        assert "WS-OTHER" not in values
        assert any("names a data item" in r for r in report.unsupported)

    def test_search_when_string_literal_survives_unquoting(self):
        """SEARCH WHEN / EVALUATE TRUE text is already unquoted, so the
        strict whitelist cannot apply there without rejecting every string
        literal. A bare word stays admissible; a subscript does not."""
        source = _DATA_HEADER + """\
       01  F1-STATUS PIC X.
       PROCEDURE DIVISION.
       MAIN.
           ACCEPT F1-STATUS
           EVALUATE TRUE
               WHEN F1-STATUS = 'Z'
                   DISPLAY 'B'
           END-EVALUATE
           STOP RUN.
"""
        report = _constraints(source)
        values = [
            constraint.values[0]
            for branch in report.branches
            for constraints in branch.arms.values()
            for constraint in constraints
        ]
        assert "Z" in values


# ---------------------------------------------------------------------------
# H2 -- the text domain no longer hands out unsatisfying witnesses
# ---------------------------------------------------------------------------


class TestH2TextDomainWitnesses:
    """`_apply_text` returned "still satisfiable" for every op it did not
    model, so `solve()` returned a witness that did not satisfy it -- and
    the SAME witness for a branch's two opposite arms."""

    CLASS_SOURCE = _DATA_HEADER + """\
       01  WS-TXT  PIC X(10).
       PROCEDURE DIVISION.
       MAIN.
           ACCEPT WS-TXT
           IF WS-TXT IS NUMERIC
               DISPLAY "N"
           ELSE
               DISPLAY "A"
           END-IF
           STOP RUN.
"""

    def test_is_numeric_on_a_text_field_gets_a_numeric_witness(self):
        report = _constraints(self.CLASS_SOURCE)
        witnesses = {}
        for branch in report.branches:
            for arm, constraints in branch.arms.items():
                result = solve(constraints[0].field.spec, constraints)
                assert isinstance(result, Witness), result
                witnesses[arm] = result.value

        assert witnesses["THEN"].strip().isdigit(), witnesses
        assert not witnesses["ELSE"].strip().isdigit(), witnesses
        # The bug in one line: both arms used to get the same value.
        assert witnesses["THEN"] != witnesses["ELSE"]

    def test_ordering_a_text_domain_is_unsatisfiable_not_satisfied(self):
        """`IF WS-TXT > 0` on a `PIC X` field: an allow/deny set genuinely
        cannot express ordering. Unsatisfiable puts the arm in coverage as
        missed *with this reason*; a witness would have been a claim the
        data does not keep."""
        source = _DATA_HEADER + """\
       01  WS-TXT  PIC X(10).
       PROCEDURE DIVISION.
       MAIN.
           ACCEPT WS-TXT
           IF WS-TXT > 0
               DISPLAY "N"
           END-IF
           STOP RUN.
"""
        report = _constraints(source)
        constraints = [
            c
            for branch in report.branches
            for cs in branch.arms.values()
            for c in cs
            if c.op in ("gt", "lt", "ge", "le")
        ]
        assert constraints, "expected a relational constraint on the text field"
        for constraint in constraints:
            result = solve(constraint.field.spec, [constraint])
            assert isinstance(result, Unsatisfiable), result
            assert "not modeled" in result.reason


# ---------------------------------------------------------------------------
# M1 -- unused-variables false positives
# ---------------------------------------------------------------------------


class TestM1UnusedVariableFalsePositives:
    """Four constructs that reference a data item without the analyzer
    seeing it. Each reported a used variable as dead."""

    def test_unstring_delimited_by_identifier(self):
        assert _unused(_DATA_HEADER + """\
       01 WS-SRC   PIC X(20) VALUE 'A|B'.
       01 WS-DELIM PIC X VALUE '|'.
       01 WS-P1    PIC X(10).
       PROCEDURE DIVISION.
       MAIN.
           UNSTRING WS-SRC DELIMITED BY WS-DELIM
               INTO WS-P1
           END-UNSTRING
           STOP RUN.
""") == []

    def test_string_delimited_by_identifier(self):
        assert _unused(_DATA_HEADER + """\
       01 WS-A   PIC X(4).
       01 WS-D   PIC X.
       01 WS-OUT PIC X(20).
       PROCEDURE DIVISION.
       MAIN.
           STRING WS-A DELIMITED BY WS-D INTO WS-OUT
           END-STRING
           STOP RUN.
""") == []

    def test_group_passed_to_call_using_marks_its_children_used(self):
        """`CALL 'SUB' USING WS-GRP` hands the whole group to code this
        analyzer cannot see, so every field under it is consumed."""
        assert _unused(_DATA_HEADER + """\
       01 WS-GRP.
           05 WS-CHILD PIC X(4).
       PROCEDURE DIVISION.
       MAIN.
           CALL 'SUB' USING WS-GRP
           STOP RUN.
""") == []

    def test_a_group_merely_moved_to_still_reports_its_fields(self):
        """The CALL rule is deliberately narrow. `MOVE SPACES TO WS-GRP`
        really does leave WS-CHILD never individually referenced, and that
        is a finding worth keeping -- propagating parent -> child for every
        group reference would have silenced it."""
        assert _unused(_DATA_HEADER + """\
       01 WS-GRP.
           05 WS-CHILD PIC X(4).
       PROCEDURE DIVISION.
       MAIN.
           MOVE SPACES TO WS-GRP
           STOP RUN.
""") == ["WS-CHILD"]

    def test_report_section_source_and_sum_are_references(self):
        """A Report Writer program never names these fields in its
        PROCEDURE DIVISION -- the report groups do. Scanning only the
        PROCEDURE DIVISION reported every field of every such program dead.
        """
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. RPT.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT RPT-FILE ASSIGN TO "R".
       DATA DIVISION.
       FILE SECTION.
       FD  RPT-FILE REPORT IS SALES-RPT.
       WORKING-STORAGE SECTION.
       01  IN-AMOUNT   PIC 9(7)V99.
       01  IN-DEPT     PIC X(4).
       01  IN-UNUSED   PIC 9(7)V99.
       REPORT SECTION.
       RD  SALES-RPT CONTROL IS IN-DEPT.
       01  DETAIL-LINE TYPE IS DETAIL.
           05  COLUMN 10  PIC $$$,$$9.99  SOURCE IN-AMOUNT.
       01  TOT-LINE TYPE IS CONTROL FOOTING.
           05  COLUMN 25  PIC $$$,$$9.99  SUM IN-AMOUNT.
       PROCEDURE DIVISION.
       MAIN.
           OPEN OUTPUT RPT-FILE
           INITIATE SALES-RPT
           TERMINATE SALES-RPT
           CLOSE RPT-FILE
           STOP RUN.
"""
        # IN-UNUSED is the control: a genuinely dead item must still be
        # reported, or this fix would have bought silence rather than
        # accuracy.
        assert _unused(source) == ["IN-UNUSED"]


# ---------------------------------------------------------------------------
# M2 -- branch-level gaps reach the documented report-level list
# ---------------------------------------------------------------------------


def test_m2_branch_gaps_roll_up_into_report_unsupported():
    """`ConstraintReport.unsupported` is documented as the place gaps are
    never silently dropped, but branch-level gaps used to live only on the
    branch, so a caller following the documented API saw a clean list for a
    program with unmodelled branches."""
    report = _constraints(_DATA_HEADER + """\
       01  WS-IN     PIC 9(4).
       01  WS-LIMIT  PIC 9(4) VALUE 100.
       PROCEDURE DIVISION.
       MAIN.
           ACCEPT WS-IN
           IF WS-IN = WS-LIMIT
               DISPLAY "A"
           END-IF
           STOP RUN.
""")
    branch_gaps = [gap for branch in report.branches for gap in branch.unsupported]
    assert branch_gaps, "expected the two-resolved-fields gap"
    for gap in branch_gaps:
        assert gap in report.unsupported

    # Rolled up, not moved: a caller that wants to know which decision point
    # a gap belongs to still needs it on the branch.
    assert all(branch.unsupported for branch in report.branches)


def test_m2_a_clean_program_still_reports_nothing():
    """The rollup must not invent gaps -- a program with no unmodelled
    branch keeps an empty list."""
    report = _constraints(_DATA_HEADER + """\
       01  WS-IN  PIC 9(4).
       PROCEDURE DIVISION.
       MAIN.
           ACCEPT WS-IN
           IF WS-IN = 5
               DISPLAY "A"
           END-IF
           STOP RUN.
""")
    assert report.unsupported == []


# ---------------------------------------------------------------------------
# M4 -- views.py agrees with layout_offsets.py, or says why not
# ---------------------------------------------------------------------------


class TestM4LayoutAgreement:
    def test_a_wider_redefines_grows_the_framing_length(self):
        """`RecordView.length` sums only non-redefining fields, so a
        redefinition wider than what it redefines left the decoder framing
        fixed-length records at the wrong stride -- shredding every record
        after the first. `data-items` reserves the widest slot member; so
        does framing now."""
        views = build_record_views(
            _record(_DATA_HEADER + """\
       01  R.
           05 A PIC X(4).
           05 A-R REDEFINES A PIC X(8).
           05 B PIC X(2).
"""),
            DataGeneratorOptions(),
        )
        assert views.base.length == 6
        # 10, not 8: the slot is the widest member, so B sits at 8 -- what
        # `data-items` reports -- and the record ends at 10. Before #296 the
        # overlay view held only A-R, so framing stopped at 8 and B decoded
        # as '' with no error.
        assert views.framing_length == 10
        assert any("wider than the item they redefine" in c for c in views.caveats)

    def test_a_conforming_layout_frames_at_its_own_length(self):
        views = build_record_views(
            _record(_DATA_HEADER + """\
       01  R.
           05 A PIC X(4).
           05 A-R REDEFINES A PIC X(2).
           05 B PIC X(2).
"""),
            DataGeneratorOptions(),
        )
        assert views.framing_length == views.base.length == 6
        assert views.caveats == []

    def test_offsets_after_a_depending_on_table_are_flagged_on_the_base_view(self):
        """`offset_ambiguous` existed but only overlays could ever carry it,
        so `--list-views` reported a maximum-length guess as a fact for the
        very fields `data-items` reports as `byte_offset: null`."""
        views = build_record_views(
            _record(_DATA_HEADER + """\
       01  R.
           05 N PIC 9(2).
           05 T OCCURS 1 TO 5 TIMES DEPENDING ON N.
               10 TA PIC X(2).
           05 Z PIC X(1).
"""),
            DataGeneratorOptions(),
        )
        assert views.base.offset_ambiguous is True
        assert any("OCCURS ... DEPENDING ON" in c for c in views.caveats)

    def test_the_serialized_form_carries_the_framing_stride(self):
        """`to_dict()` backs `decode --list-views`. It used to report only
        `record_length` (the base view's span), so for the one layout
        `framing_length` exists for, a consumer reading the serialized form
        framed records on a number the decoder itself does not use -- the
        same mismatch, one surface over. Copilot review on #208."""
        views = build_record_views(
            _record(_DATA_HEADER + """\
       01  R.
           05 A PIC X(4).
           05 A-R REDEFINES A PIC X(8).
           05 B PIC X(2).
"""),
            DataGeneratorOptions(),
        )
        payload = views.to_dict()
        assert payload["record_length"] == 6
        assert payload["framing_length"] == 10 == views.framing_length
        assert payload["caveats"], "the divergence must be named, not just numbered"

    def test_the_two_lengths_agree_for_a_conforming_layout(self):
        views = build_record_views(
            _record(_DATA_HEADER + """\
       01  R.
           05 A PIC X(4).
           05 B PIC X(2).
"""),
            DataGeneratorOptions(),
        )
        payload = views.to_dict()
        assert payload["framing_length"] == payload["record_length"] == 6

    def test_a_fixed_layout_is_not_flagged_ambiguous(self):
        views = build_record_views(
            _record(_DATA_HEADER + """\
       01  R.
           05 A PIC X(4).
           05 B PIC 9(4) COMP.
"""),
            DataGeneratorOptions(),
        )
        assert views.base.offset_ambiguous is False
        assert views.caveats == []
