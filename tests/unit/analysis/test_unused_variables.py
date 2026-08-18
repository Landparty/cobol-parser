"""Unit tests for UnusedVariableAnalyzer.

Covers:
- Basic used/unused detection via MOVE
- FILLER always excluded
- Group items used-if-any-descendant-used
- Level-88 condition-name usage marks its parent item used
- IF/PERFORM UNTIL condition operands (not in .operands, walked via the
  expression tree)
- REDEFINES propagation
- OCCURS ... DEPENDING ON marks the depending variable used
- LINKAGE / FILE SECTION coverage
- copybook_item_names / include_copybook_variables filtering
- to_dict() serialization
- Export from top-level package
- Round-trip via parse_cobol()
"""

import json

from cobolparser import parse_cobol
from cobolparser.analysis.unused_variables import (
    UnusedVariableAnalyzer,
    UnusedVariableItem,
    UnusedVariableReport,
    collect_declared_items,
)
from cobolparser.models.ast_base import SourceLocation
from cobolparser.models.data_items import CobolDataItem
from cobolparser.models.program import (
    CobolDivision,
    CobolParagraph,
    CobolProgram,
    CobolSection,
)
from cobolparser.models.statements.base import CobolExpression
from cobolparser.models.statements.control import EvaluateStatement
from cobolparser.models.statements.data import InspectStatement


def _analyze(src: str, **kwargs) -> UnusedVariableReport:
    result = parse_cobol(src)
    assert result.ast is not None, "\n".join(str(e) for e in result.errors)
    return UnusedVariableAnalyzer().analyze(result.ast, **kwargs)


def _names(report: UnusedVariableReport) -> set[str]:
    return {item.name for item in report.unused_items}


class TestBasicUsage:
    def test_used_variable_not_reported(self):
        src = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-USED PIC 9(5).
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           MOVE 1 TO WS-USED
           STOP RUN.
"""
        report = _analyze(src)
        assert report.total_variables == 1
        assert report.referenced_variables == 1
        assert not report.has_unused_variables

    def test_unused_variable_reported(self):
        src = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-UNUSED PIC 9(5).
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           DISPLAY 'HELLO'
           STOP RUN.
"""
        report = _analyze(src)
        assert _names(report) == {"WS-UNUSED"}
        assert report.total_variables == 1
        assert report.referenced_variables == 0

    def test_mixed_used_and_unused(self):
        src = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-USED PIC 9(5).
       01 WS-UNUSED PIC 9(5).
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           DISPLAY WS-USED
           STOP RUN.
"""
        report = _analyze(src)
        assert _names(report) == {"WS-UNUSED"}

    def test_no_data_division_no_crash(self):
        src = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           STOP RUN.
"""
        report = _analyze(src)
        assert report.total_variables == 0
        assert not report.has_unused_variables


class TestQualifiedAndFunctionOperands:
    """Statement parsers frequently join a whole qualified reference or
    intrinsic function call into a single operand string instead of
    splitting out the underlying data-name(s) -- e.g. MoveStatement.source
    for `MOVE WS-A OF WS-GRP TO ...` is the literal string
    "WS-A OF WS-GRP". Treating an operand as one opaque token meant none
    of the underlying names ever matched a declared item's bare name and
    were falsely reported unused. See _extract_identifiers.
    """

    def test_qualified_name_with_of_marks_both_items_used(self):
        src = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-GRP.
           05 WS-A PIC X(5).
       01 WS-TARGET PIC X(5).
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           MOVE WS-A OF WS-GRP TO WS-TARGET
           STOP RUN.
"""
        report = _analyze(src)
        assert not _names(report)

    def test_qualified_name_with_in_marks_both_items_used(self):
        src = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-GRP.
           05 WS-A PIC X(5).
       01 WS-TARGET PIC X(5).
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           MOVE WS-A IN WS-GRP TO WS-TARGET
           STOP RUN.
"""
        report = _analyze(src)
        assert not _names(report)

    def test_function_call_argument_marks_field_used(self):
        src = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-X PIC X(10) VALUE 'hello'.
       01 WS-UPPER PIC X(10).
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           MOVE FUNCTION UPPER-CASE(WS-X) TO WS-UPPER
           STOP RUN.
"""
        report = _analyze(src)
        assert not _names(report)

    def test_length_of_special_register_marks_field_used(self):
        src = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-X PIC X(10).
       01 WS-LEN PIC 9(4).
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           MOVE LENGTH OF WS-X TO WS-LEN
           STOP RUN.
"""
        report = _analyze(src)
        assert not _names(report)

    def test_subscripted_reference_marks_both_items_used(self):
        src = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-IDX PIC 9(2) VALUE 1.
       01 WS-TABLE.
           05 WS-ENTRY PIC X(5) OCCURS 5 TIMES.
       01 WS-TARGET PIC X(5).
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           MOVE WS-ENTRY(WS-IDX) TO WS-TARGET
           STOP RUN.
"""
        report = _analyze(src)
        assert not _names(report)


class TestAnonymousItems:
    def test_anonymous_level_number_entry_never_reported(self):
        """A level-number entry with no IDENTIFIER token gets a synthetic
        ``ANONYMOUS-<level>-<line>`` name from the parser -- never a name a
        program could reference, so it must never show up as "unused".
        """
        src = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-GROUP.
           05 PIC X(5).
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           DISPLAY 'HELLO'
           STOP RUN.
"""
        report = _analyze(src)
        assert not any(name.startswith("ANONYMOUS-") for name in _names(report))


class TestFiller:
    def test_filler_never_reported(self):
        src = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-GROUP.
           05 WS-FIELD PIC X(5).
           05 FILLER PIC X(5).
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           MOVE 'X' TO WS-FIELD
           STOP RUN.
"""
        report = _analyze(src)
        assert "FILLER" not in _names(report)


class TestGroupItems:
    def test_group_used_via_child(self):
        src = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-GROUP.
           05 WS-CHILD-USED PIC X(5).
           05 WS-CHILD-UNUSED PIC X(5).
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           MOVE 'X' TO WS-CHILD-USED
           STOP RUN.
"""
        report = _analyze(src)
        # The group itself is "used" because a descendant is used, but the
        # unused sibling child is still independently reported.
        assert _names(report) == {"WS-CHILD-UNUSED"}

    def test_wholly_unused_group_reports_group_and_children(self):
        src = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-DEAD-GROUP.
           05 WS-DEAD-CHILD PIC X(5).
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           DISPLAY 'HELLO'
           STOP RUN.
"""
        report = _analyze(src)
        assert _names(report) == {"WS-DEAD-GROUP", "WS-DEAD-CHILD"}


class TestConditionNames:
    def test_level_88_usage_marks_parent_used(self):
        src = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-STATUS PIC X(1).
           88 STATUS-OK VALUE 'Y'.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           IF STATUS-OK
               DISPLAY 'OK'
           END-IF
           STOP RUN.
"""
        report = _analyze(src)
        assert "WS-STATUS" not in _names(report)


class TestConditionExpressions:
    def test_if_condition_operand_not_in_flat_operands(self):
        """IfStatement.condition lives in a structural expression tree, not
        in IfStatement.operands -- this exercises the expression walker.
        """
        src = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-FLAG PIC X(1).
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           IF WS-FLAG = 'Y'
               DISPLAY 'YES'
           END-IF
           STOP RUN.
"""
        report = _analyze(src)
        assert "WS-FLAG" not in _names(report)

    def test_perform_until_condition_operand(self):
        src = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-EOF PIC X(1) VALUE 'N'.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           PERFORM UNTIL WS-EOF = 'Y'
               MOVE 'Y' TO WS-EOF
           END-PERFORM
           STOP RUN.
"""
        report = _analyze(src)
        assert "WS-EOF" not in _names(report)

    def test_perform_varying_loop_variable_used(self):
        src = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-I PIC 9(3).
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           PERFORM VARYING WS-I FROM 1 BY 1 UNTIL WS-I > 10
               DISPLAY WS-I
           END-PERFORM
           STOP RUN.
"""
        report = _analyze(src)
        assert "WS-I" not in _names(report)


class TestEvaluateSubjects:
    """EVALUATE subject-1 [ALSO subject-2]...: string subjects reach
    `.operands` (evaluate_parser routes them through `add_subject()`), and
    the analyzer additionally walks `stmt.subjects` explicitly -- the only
    coverage for a `CobolExpression` subject, which `add_subject()` sends
    to `add_child()`, never `add_operand()`. Each parsed-source test
    declares a deliberately-unused sibling item asserted to BE reported,
    as a positive control proving the analyzer really saw the
    declarations (without it, a parser regression that dropped the
    WORKING-STORAGE items would leave the negative assertions vacuously
    green). See the EvaluateStatement branch in
    `_collect_referenced_names`.
    """

    def test_single_subject_marks_variable_used(self):
        src = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-CODE PIC X(1).
       01 WS-DEAD PIC X(1).
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           EVALUATE WS-CODE
               WHEN 'A'
                   DISPLAY 'A'
               WHEN OTHER
                   DISPLAY 'OTHER'
           END-EVALUATE
           STOP RUN.
"""
        report = _analyze(src)
        assert "WS-CODE" not in _names(report)
        assert "WS-DEAD" in _names(report)

    def test_also_joined_subjects_all_marked_used(self):
        src = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-A PIC X(1).
       01 WS-B PIC X(1).
       01 WS-DEAD PIC X(1).
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           EVALUATE WS-A ALSO WS-B
               WHEN 'A' ALSO 'B'
                   DISPLAY 'AB'
               WHEN OTHER
                   DISPLAY 'OTHER'
           END-EVALUATE
           STOP RUN.
"""
        report = _analyze(src)
        assert "WS-A" not in _names(report)
        assert "WS-B" not in _names(report)
        assert "WS-DEAD" in _names(report)

    def test_subjects_reach_operands_and_public_lookup(self):
        """Parser-altitude regression pin: subjects are routed through
        add_subject(), so they land in the generic .operands bag and
        .operands-based public APIs (find_statements_using_variable here)
        see a variable whose only reference is an EVALUATE subject."""
        src = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-CODE PIC X(1).
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           EVALUATE WS-CODE
               WHEN 'A'
                   DISPLAY 'A'
               WHEN OTHER
                   DISPLAY 'OTHER'
           END-EVALUATE
           STOP RUN.
"""
        result = parse_cobol(src)
        assert result.ast is not None
        evaluates = result.ast.find_all_by_type("EvaluateStatement")
        assert evaluates
        assert "WS-CODE" in evaluates[0].operands
        assert result.ast.find_statements_using_variable("WS-CODE")

    def test_when_selector_only_variable_not_reported(self):
        """A data-name referenced ONLY as a WHEN selector arrives from
        _build_selector as {'type': 'Literal'} (the parser never emits
        'Identifier'), so _selector_identifiers must scan Literal values
        -- skipping them falsely reported WS-LIMIT unused."""
        src = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-CODE PIC 9(2).
       01 WS-LIMIT PIC 9(2).
       01 WS-DEAD PIC 9(2).
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           MOVE 5 TO WS-CODE
           EVALUATE WS-CODE
               WHEN WS-LIMIT
                   CONTINUE
               WHEN OTHER
                   CONTINUE
           END-EVALUATE
           STOP RUN.
"""
        report = _analyze(src)
        assert "WS-LIMIT" not in _names(report)
        assert "WS-DEAD" in _names(report)

    def test_expression_subject_walked_structurally(self):
        """A CobolExpression subject (only constructible via add_subject;
        the real parser always produces strings) goes to .children, never
        .operands, so the analyzer's explicit subjects walk is its only
        coverage -- including the opaque-shape fallback, which must scan
        EVERY operand, not just operands[0]."""
        loc = SourceLocation(1, 1)
        prog = CobolProgram("TEST", loc)
        prog.add_division(CobolDivision("IDENTIFICATION", loc))

        data_div = CobolDivision("DATA", loc)
        ws = CobolSection("WORKING-STORAGE", loc)
        ws.add_data_item(CobolDataItem("WS-A", 1, loc))
        ws.add_data_item(CobolDataItem("WS-B", 1, loc))
        ws.add_data_item(CobolDataItem("WS-DEAD", 1, loc))
        data_div.add_section(ws)
        prog.add_division(data_div)

        proc_div = CobolDivision("PROCEDURE", loc)
        para = CobolParagraph("MAIN", loc)
        stmt = EvaluateStatement(loc)
        expr = CobolExpression("CONDITION", loc)
        expr.operands.extend(["WS-A", "WS-B"])
        stmt.add_subject(expr)
        para.add_statement(stmt)
        proc_div.add_paragraph(para)
        prog.add_division(proc_div)

        report = UnusedVariableAnalyzer().analyze(prog)
        names = {i.name for i in report.unused_items}
        assert "WS-A" not in names
        assert "WS-B" not in names
        assert "WS-DEAD" in names


class TestRedefines:
    def test_redefines_target_used_when_redefiner_used(self):
        src = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-ORIGINAL PIC 9(5).
       01 WS-ALIAS REDEFINES WS-ORIGINAL PIC X(5).
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           MOVE 'HELLO' TO WS-ALIAS
           STOP RUN.
"""
        report = _analyze(src)
        # WS-ORIGINAL's own name never appears in PROCEDURE DIVISION, but
        # it shares storage with the used WS-ALIAS.
        assert "WS-ORIGINAL" not in _names(report)

    def test_redefines_target_unused_when_redefiner_unused(self):
        src = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-ORIGINAL PIC 9(5).
       01 WS-ALIAS REDEFINES WS-ORIGINAL PIC X(5).
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           DISPLAY 'HELLO'
           STOP RUN.
"""
        report = _analyze(src)
        assert _names(report) == {"WS-ORIGINAL", "WS-ALIAS"}


class TestOccursDependingOn:
    def test_depending_on_variable_marked_used(self):
        src = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-COUNT PIC 9(3).
       01 WS-TABLE.
           05 WS-ENTRY PIC X(5) OCCURS 1 TO 10 TIMES
               DEPENDING ON WS-COUNT.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           DISPLAY 'HELLO'
           STOP RUN.
"""
        report = _analyze(src)
        # WS-COUNT is never referenced in PROCEDURE DIVISION but is a real
        # runtime dependency via OCCURS DEPENDING ON.
        assert "WS-COUNT" not in _names(report)
        # WS-TABLE/WS-ENTRY are genuinely never used anywhere.
        assert "WS-ENTRY" in _names(report)


class TestSections:
    def test_linkage_item_unused(self):
        src = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.
       DATA DIVISION.
       LINKAGE SECTION.
       01 LK-PARM PIC X(10).
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           DISPLAY 'HELLO'
           STOP RUN.
"""
        report = _analyze(src)
        assert _names(report) == {"LK-PARM"}
        assert report.unused_items[0].section == "LINKAGE"

    def test_file_section_record_used_via_write(self):
        src = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT OUT-FILE ASSIGN TO 'OUT.DAT'.
       DATA DIVISION.
       FILE SECTION.
       FD OUT-FILE.
       01 OUT-RECORD PIC X(20).
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           OPEN OUTPUT OUT-FILE
           WRITE OUT-RECORD
           CLOSE OUT-FILE
           STOP RUN.
"""
        report = _analyze(src)
        assert "OUT-RECORD" not in _names(report)


class TestCopybookFiltering:
    def test_include_copybook_variables_default_reports_everything(self):
        src = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-LOCAL PIC 9(5).
       01 WS-FROM-COPY PIC 9(5).
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           DISPLAY 'HELLO'
           STOP RUN.
"""
        report = _analyze(src, copybook_item_names={"WS-FROM-COPY"})
        assert _names(report) == {"WS-LOCAL", "WS-FROM-COPY"}
        item = next(i for i in report.unused_items if i.name == "WS-FROM-COPY")
        assert item.from_copybook is True
        assert report.skipped_copybook_count == 0

    def test_exclude_copybook_variables_filters_them_out(self):
        src = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-LOCAL PIC 9(5).
       01 WS-FROM-COPY PIC 9(5).
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           DISPLAY 'HELLO'
           STOP RUN.
"""
        report = _analyze(
            src,
            include_copybook_variables=False,
            copybook_item_names={"WS-FROM-COPY"},
        )
        assert _names(report) == {"WS-LOCAL"}
        assert report.skipped_copybook_count == 1
        # Still counted in totals for accurate summary numbers.
        assert report.total_variables == 2

    def test_exclude_without_copybook_names_is_a_no_op(self):
        src = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-UNUSED PIC 9(5).
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           DISPLAY 'HELLO'
           STOP RUN.
"""
        report = _analyze(src, include_copybook_variables=False)
        assert _names(report) == {"WS-UNUSED"}


class TestSerialization:
    def test_to_dict_shape(self):
        item = UnusedVariableItem(
            name="WS-X",
            level=1,
            section="WORKING-STORAGE",
            location=__import__(
                "cobolparser.models.ast_base", fromlist=["SourceLocation"]
            ).SourceLocation(10, 8),
            from_copybook=False,
        )
        d = item.to_dict()
        assert d["name"] == "WS-X"
        assert d["level"] == 1
        assert d["section"] == "WORKING-STORAGE"
        assert d["from_copybook"] is False
        assert d["location"] == {"line": 10, "column": 8}

    def test_report_to_dict_json_serializable(self):
        src = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-UNUSED PIC 9(5).
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           DISPLAY 'HELLO'
           STOP RUN.
"""
        report = _analyze(src)
        d = report.to_dict()
        json.dumps(d)  # must not raise
        assert d["summary"]["total_variables"] == 1
        assert d["summary"]["unused_variables"] == 1
        assert len(d["unused_variables"]) == 1


class TestCollectDeclaredItems:
    def test_collects_across_sections_excludes_filler(self):
        src = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-A PIC X(5).
       01 WS-B.
           05 WS-B-1 PIC X(1).
           05 FILLER PIC X(1).
       LINKAGE SECTION.
       01 LK-A PIC X(5).
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           STOP RUN.
"""
        result = parse_cobol(src)
        assert result.ast is not None
        items = collect_declared_items(result.ast)
        names = {i.name for i in items}
        assert names == {"WS-A", "WS-B", "WS-B-1", "LK-A"}


class TestExtrasLookupIsMroAware:
    def test_subclass_of_keyed_statement_type_still_gets_its_extras(self):
        """_STR_ATTR_EXTRAS/_DICT_LIST_EXTRAS are looked up by walking
        type(stmt).__mro__, not exact type -- a subclass of a keyed
        statement type (InspectStatement here) must not silently lose the
        extras lookup. InspectStatement.set_converting doesn't reach
        .operands at all (see module docstring), so this exercises the gap
        directly: exact-type lookup would miss it, MRO lookup finds it via
        the InspectStatement base class.
        """

        class CustomInspectStatement(InspectStatement):
            pass

        loc = SourceLocation(1, 1)
        prog = CobolProgram("TEST", loc)
        prog.add_division(CobolDivision("IDENTIFICATION", loc))

        data_div = CobolDivision("DATA", loc)
        ws = CobolSection("WORKING-STORAGE", loc)
        ws.add_data_item(CobolDataItem("WS-CONVERT-TARGET", 1, loc))
        data_div.add_section(ws)
        prog.add_division(data_div)

        proc_div = CobolDivision("PROCEDURE", loc)
        para = CobolParagraph("MAIN", loc)
        stmt = CustomInspectStatement(loc)
        stmt.set_target("WS-UNRELATED")
        stmt.set_converting("A", "WS-CONVERT-TARGET")
        para.add_statement(stmt)
        proc_div.add_paragraph(para)
        prog.add_division(proc_div)

        report = UnusedVariableAnalyzer().analyze(prog)
        assert "WS-CONVERT-TARGET" not in {i.name for i in report.unused_items}


class TestExports:
    def test_exported_from_top_level_package(self):
        import cobolparser

        assert cobolparser.UnusedVariableAnalyzer is UnusedVariableAnalyzer
        assert cobolparser.UnusedVariableReport is UnusedVariableReport
        assert cobolparser.UnusedVariableItem is UnusedVariableItem
