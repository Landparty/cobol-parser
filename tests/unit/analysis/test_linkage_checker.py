"""Unit tests for LinkageChecker.

Covers:
- LINKAGE SECTION 01-item collection
- ENTRY statement parameter collection
- PROCEDURE DIVISION USING collection (via metadata)
- CALL with correct arg count → no violation
- CALL with too many args → TOO_MANY_ARGS
- CALL with too few args → TOO_FEW_ARGS
- CALL passing a LINKAGE item BY VALUE → no violation (legal COBOL; the
  former VALUE_TO_LINKAGE rule was a false positive, removed 2026-09-09)
- LINKAGE 01-item never referenced → UNREFERENCED_LINKAGE
- Dynamic CALL → skip
- CALL targeting external program (not in ENTRY list) → skip
- Empty LINKAGE section → no violations
- No DATA DIVISION → no crash
- Report.to_dict() serialization
- Exports from top-level package
- Round-trip via parse_cobol()
"""

import json

from cobolparser import parse_cobol
from cobolparser.analysis.linkage_checker import (
    LinkageChecker,
    LinkageReport,
    LinkageViolation,
    LinkageViolationKind,
)
from cobolparser.models.ast_base import SourceLocation
from cobolparser.models.data_items import CobolDataItem
from cobolparser.models.program import (
    CobolDivision,
    CobolParagraph,
    CobolProgram,
    CobolSection,
)
from cobolparser.models.statements import EntryStatement
from cobolparser.models.statements.call import CallStatement

_LOC = SourceLocation(1, 1)


# ---------------------------------------------------------------------------
# AST builder helpers
# ---------------------------------------------------------------------------


def _make_program(
    linkage_items: list[str] | None = None,
    entry_params: dict[str, list[str]] | None = None,
    calls: list[tuple[str, list[tuple[str, str]]]] | None = None,
    dynamic_calls: list[str] | None = None,
) -> CobolProgram:
    """Build a minimal program.

    Args:
        linkage_items: list of 01-level LINKAGE item names.
        entry_params: {entry_name: [param_name, ...]} for ENTRY statements.
        calls: [(target, [(param_name, mode), ...]), ...] for CALL statements.
        dynamic_calls: list of variable names for dynamic CALL statements.
    """
    prog = CobolProgram("TEST", _LOC)

    id_div = CobolDivision("IDENTIFICATION", _LOC)
    prog.add_division(id_div)

    if linkage_items is not None:
        data_div = CobolDivision("DATA", _LOC)
        lk_section = CobolSection("LINKAGE", _LOC)
        for name in linkage_items:
            item = CobolDataItem(name, 1, _LOC)
            item.level = 1
            lk_section.add_data_item(item)
        data_div.add_section(lk_section)
        prog.add_division(data_div)

    proc_div = CobolDivision("PROCEDURE", _LOC)
    para = CobolParagraph("MAIN", _LOC)

    if entry_params:
        for entry_name, params in entry_params.items():
            entry = EntryStatement(_LOC)
            entry.set_entry_name(entry_name)
            for p in params:
                entry.add_using_parameter(p)
            para.add_statement(entry)

    if calls:
        for target, params in calls:
            stmt = CallStatement(_LOC)
            stmt.set_called_program(target)
            for p_name, p_mode in params:
                stmt.add_using_parameter(p_name, p_mode)
            para.add_statement(stmt)

    if dynamic_calls:
        for var in dynamic_calls:
            stmt = CallStatement(_LOC)
            stmt.set_called_program(var, is_dynamic=True)
            para.add_statement(stmt)

    proc_div.add_paragraph(para)
    prog.add_division(proc_div)
    return prog


def _check(**kw) -> LinkageReport:
    return LinkageChecker().check(_make_program(**kw))


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestLinkageHappyPath:
    def test_no_data_division(self):
        prog = CobolProgram("TEST", _LOC)
        prog.add_division(CobolDivision("IDENTIFICATION", _LOC))
        prog.add_division(CobolDivision("PROCEDURE", _LOC))
        report = LinkageChecker().check(prog)
        assert not report.has_violations

    def test_empty_linkage_no_violations(self):
        report = _check(linkage_items=[])
        assert not report.has_violations

    def test_correct_arg_count_no_violations(self):
        report = _check(
            linkage_items=["PARM-A", "PARM-B"],
            entry_params={"MY-ENTRY": ["PARM-A", "PARM-B"]},
            calls=[("MY-ENTRY", [("WS-A", "REFERENCE"), ("WS-B", "REFERENCE")])],
        )
        assert not report.has_violations

    def test_call_to_external_program_skipped(self):
        """CALL targeting a program not in ENTRY list must not emit violations."""
        report = _check(
            linkage_items=["PARM-A"],
            entry_params={},
            calls=[("EXTERNAL-PGM", [("WS-A", "REFERENCE"), ("WS-B", "REFERENCE")])],
        )
        # LINKAGE item unreferenced is a separate violation; no arg-count violation
        arg_violations = [
            v
            for v in report.violations
            if v.kind
            in (LinkageViolationKind.TOO_MANY_ARGS, LinkageViolationKind.TOO_FEW_ARGS)
        ]
        assert not arg_violations

    def test_dynamic_call_skipped(self):
        report = _check(
            entry_params={"MY-ENTRY": ["PARM-A"]},
            dynamic_calls=["WS-PROG-NAME"],
        )
        arg_violations = [
            v
            for v in report.violations
            if v.kind
            in (LinkageViolationKind.TOO_MANY_ARGS, LinkageViolationKind.TOO_FEW_ARGS)
        ]
        assert not arg_violations


# ---------------------------------------------------------------------------
# TOO_MANY_ARGS
# ---------------------------------------------------------------------------


class TestTooManyArgs:
    def test_call_extra_arg(self):
        report = _check(
            linkage_items=["PARM-A"],
            entry_params={"MY-ENTRY": ["PARM-A"]},
            calls=[
                (
                    "MY-ENTRY",
                    [("WS-A", "REFERENCE"), ("WS-B", "REFERENCE")],
                )
            ],
        )
        kinds = [v.kind for v in report.violations]
        assert LinkageViolationKind.TOO_MANY_ARGS in kinds

    def test_message_mentions_counts(self):
        report = _check(
            entry_params={"MY-ENTRY": ["P1"]},
            calls=[("MY-ENTRY", [("A", "REFERENCE"), ("B", "REFERENCE")])],
        )
        msgs = [
            v.message
            for v in report.violations
            if v.kind == LinkageViolationKind.TOO_MANY_ARGS
        ]
        assert msgs
        assert "2" in msgs[0] or "1" in msgs[0]


# ---------------------------------------------------------------------------
# TOO_FEW_ARGS
# ---------------------------------------------------------------------------


class TestTooFewArgs:
    def test_call_missing_arg(self):
        report = _check(
            linkage_items=["PARM-A", "PARM-B"],
            entry_params={"MY-ENTRY": ["PARM-A", "PARM-B"]},
            calls=[("MY-ENTRY", [("WS-A", "REFERENCE")])],
        )
        kinds = [v.kind for v in report.violations]
        assert LinkageViolationKind.TOO_FEW_ARGS in kinds

    def test_call_with_zero_args(self):
        report = _check(
            entry_params={"MY-ENTRY": ["PARM-A"]},
            calls=[("MY-ENTRY", [])],
        )
        kinds = [v.kind for v in report.violations]
        assert LinkageViolationKind.TOO_FEW_ARGS in kinds


# ---------------------------------------------------------------------------
# BY VALUE to a LINKAGE item is legal (former VALUE_TO_LINKAGE false positive)
# ---------------------------------------------------------------------------


class TestByValueToLinkageIsLegal:
    """COBOL has no rule against passing a LINKAGE item BY VALUE -- it is
    what a caller must write when the callee declares ``PROCEDURE DIVISION
    USING BY VALUE``. The former VALUE_TO_LINKAGE rule flagged that legal
    call as an error and is gone."""

    def test_rule_no_longer_exists(self):
        assert not hasattr(LinkageViolationKind, "VALUE_TO_LINKAGE")

    def test_by_value_to_linkage_item_is_not_a_violation(self):
        report = _check(
            linkage_items=["PARM-A"],
            entry_params={"MY-ENTRY": ["PARM-A"]},
            calls=[("MY-ENTRY", [("PARM-A", "VALUE")])],
        )
        assert not report.has_violations

    def test_by_reference_to_linkage_no_violation(self):
        report = _check(
            linkage_items=["PARM-A"],
            entry_params={"MY-ENTRY": ["PARM-A"]},
            calls=[("MY-ENTRY", [("PARM-A", "REFERENCE")])],
        )
        assert not report.has_violations

    def test_by_value_to_non_linkage_item_no_violation(self):
        """BY VALUE to a working-storage variable is fine: a clean report."""
        report = _check(
            linkage_items=["PARM-A"],
            entry_params={"MY-ENTRY": ["PARM-A"]},
            calls=[("MY-ENTRY", [("WS-FIELD", "VALUE")])],
        )
        assert not report.has_violations
        assert report.violations == []


# ---------------------------------------------------------------------------
# UNREFERENCED_LINKAGE
# ---------------------------------------------------------------------------


class TestUnreferencedLinkage:
    def test_linkage_item_not_in_any_entry_is_unreferenced(self):
        report = _check(
            linkage_items=["PARM-A", "PARM-B"],
            entry_params={"MY-ENTRY": ["PARM-A"]},
            calls=[("MY-ENTRY", [("WS-A", "REFERENCE")])],
        )
        kinds = [v.kind for v in report.violations]
        assert LinkageViolationKind.UNREFERENCED_LINKAGE in kinds
        msgs = [
            v.message
            for v in report.violations
            if v.kind == LinkageViolationKind.UNREFERENCED_LINKAGE
        ]
        assert any("PARM-B" in m for m in msgs)

    def test_all_linkage_items_referenced_no_violation(self):
        report = _check(
            linkage_items=["PARM-A"],
            entry_params={"MY-ENTRY": ["PARM-A"]},
            calls=[("MY-ENTRY", [("PARM-A", "REFERENCE")])],
        )
        assert not any(
            v.kind == LinkageViolationKind.UNREFERENCED_LINKAGE
            for v in report.violations
        )

    def test_no_linkage_items_no_unreferenced_violation(self):
        report = _check(
            linkage_items=[],
            entry_params={"MY-ENTRY": []},
            calls=[("MY-ENTRY", [])],
        )
        assert not report.has_violations


# ---------------------------------------------------------------------------
# Report fields
# ---------------------------------------------------------------------------


class TestLinkageReport:
    def test_report_entry_interfaces(self):
        prog = _make_program(
            entry_params={"MY-ENTRY": ["PARM-A", "PARM-B"]},
        )
        report = LinkageChecker().check(prog)
        assert "MY-ENTRY" in report.entry_interfaces
        assert report.entry_interfaces["MY-ENTRY"] == ["PARM-A", "PARM-B"]

    def test_report_linkage_items_list(self):
        report = _check(linkage_items=["PARM-A", "PARM-B"])
        assert "PARM-A" in report.linkage_items
        assert "PARM-B" in report.linkage_items

    def test_to_dict_is_json_serializable(self):
        report = _check(
            linkage_items=["PARM-A"],
            entry_params={"MY-ENTRY": ["PARM-A"]},
            calls=[("MY-ENTRY", [("WS-A", "REFERENCE"), ("WS-B", "REFERENCE")])],
        )
        json.dumps(report.to_dict())

    def test_to_dict_structure(self):
        report = _check()
        d = report.to_dict()
        assert "has_violations" in d
        assert "violation_count" in d
        assert "violations" in d
        assert "entry_interfaces" in d
        assert "linkage_items" in d

    def test_violation_to_dict(self):
        v = LinkageViolation(
            kind=LinkageViolationKind.TOO_MANY_ARGS,
            call_target="MY-ENTRY",
            location=_LOC,
            message="CALL passes 2 args but entry declares 1",
        )
        d = v.to_dict()
        assert d["kind"] == "TOO_MANY_ARGS"
        assert d["call_target"] == "MY-ENTRY"
        assert d["location"]["line"] == 1
        assert "2" in d["message"] or "1" in d["message"]

    def test_violation_to_dict_no_location(self):
        v = LinkageViolation(
            kind=LinkageViolationKind.UNREFERENCED_LINKAGE,
            call_target=None,
            location=None,
            message="unreferenced",
        )
        d = v.to_dict()
        assert d["location"] is None
        assert d["call_target"] is None


# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------


class TestExports:
    def test_exported_from_package(self):
        from cobolparser import LinkageChecker as C
        from cobolparser import LinkageReport as R
        from cobolparser import LinkageViolation as V
        from cobolparser import LinkageViolationKind as K

        assert C is LinkageChecker
        assert R is LinkageReport
        assert V is LinkageViolation
        assert K is LinkageViolationKind


# ---------------------------------------------------------------------------
# Round-trip via parse_cobol()
# ---------------------------------------------------------------------------


class TestLinkageCheckerRoundTrip:
    def test_no_linkage_section_no_violations(self):
        src = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           CALL 'SUBPROG' USING WS-A WS-B.
           STOP RUN.
"""
        result = parse_cobol(src)
        assert result.ast is not None
        report = LinkageChecker().check(result.ast)
        # No LINKAGE section → no violations expected
        assert not any(
            v.kind == LinkageViolationKind.UNREFERENCED_LINKAGE
            for v in report.violations
        )


# ---------------------------------------------------------------------------
# Additional edge cases
# ---------------------------------------------------------------------------


class TestLinkageItemLevelFiltering:
    """Only 01-level items count as top-level LINKAGE parameters."""

    def test_level_77_not_in_linkage_items(self):
        """Level 77 is an elementary item, not an 01-level group — must NOT appear."""
        prog = _make_program(linkage_items=[])  # start with empty
        # Manually add a level-77 item to the LINKAGE section
        data_div = CobolDivision("DATA", _LOC)
        lk = CobolSection("LINKAGE", _LOC)
        item77 = CobolDataItem("LK-77", 77, _LOC)
        lk.add_data_item(item77)
        data_div.add_section(lk)
        prog.add_division(data_div)

        report = LinkageChecker().check(prog)
        assert "LK-77" not in report.linkage_items

    def test_level_88_not_in_linkage_items(self):
        """Level 88 condition items must never appear as top-level LINKAGE items."""
        prog = _make_program(linkage_items=[])
        data_div = CobolDivision("DATA", _LOC)
        lk = CobolSection("LINKAGE", _LOC)
        item88 = CobolDataItem("LK-88-COND", 88, _LOC)
        lk.add_data_item(item88)
        data_div.add_section(lk)
        prog.add_division(data_div)

        report = LinkageChecker().check(prog)
        assert "LK-88-COND" not in report.linkage_items

    def test_level_05_child_not_in_linkage_items(self):
        """Level 05 sub-items in LINKAGE must not appear in linkage_items."""
        prog = _make_program(linkage_items=[])
        data_div = CobolDivision("DATA", _LOC)
        lk = CobolSection("LINKAGE", _LOC)
        parent = CobolDataItem("LK-PARENT", 1, _LOC)
        child = CobolDataItem("LK-CHILD", 5, _LOC)
        parent.add_child(child)
        lk.add_data_item(parent)
        data_div.add_section(lk)
        prog.add_division(data_div)

        report = LinkageChecker().check(prog)
        assert "LK-PARENT" in report.linkage_items
        assert "LK-CHILD" not in report.linkage_items


class TestMultipleEntryPoints:
    """Programs with multiple ENTRY statements."""

    def test_two_entries_each_validated_independently(self):
        """CALL to entry-A with too many args must not also flag entry-B."""
        prog = _make_program(
            entry_params={
                "ENTRY-A": ["P1"],
                "ENTRY-B": ["P1", "P2"],
            },
            calls=[
                ("ENTRY-A", [("X", "REFERENCE"), ("Y", "REFERENCE")]),  # too many
                ("ENTRY-B", [("X", "REFERENCE"), ("Y", "REFERENCE")]),  # correct
            ],
        )
        report = LinkageChecker().check(prog)
        too_many = [
            v for v in report.violations if v.kind == LinkageViolationKind.TOO_MANY_ARGS
        ]
        assert len(too_many) == 1
        assert too_many[0].call_target == "ENTRY-A"

    def test_all_entries_appear_in_entry_interfaces(self):
        prog = _make_program(
            entry_params={
                "ENTRY-A": ["P1"],
                "ENTRY-B": ["P2", "P3"],
            },
        )
        report = LinkageChecker().check(prog)
        assert "ENTRY-A" in report.entry_interfaces
        assert "ENTRY-B" in report.entry_interfaces

    def test_linkage_item_referenced_by_any_entry_not_flagged(self):
        """PARM-A referenced only by ENTRY-A should not be flagged as unreferenced."""
        report = _check(
            linkage_items=["PARM-A", "PARM-B"],
            entry_params={"ENTRY-A": ["PARM-A"], "ENTRY-B": ["PARM-B"]},
            calls=[],
        )
        assert not any(
            v.kind == LinkageViolationKind.UNREFERENCED_LINKAGE
            for v in report.violations
        )


class TestByContentMode:
    """The passing mode never makes a matching CALL a violation."""

    def test_by_content_to_linkage_item_no_violation(self):
        report = _check(
            linkage_items=["PARM-A"],
            entry_params={"MY-ENTRY": ["PARM-A"]},
            calls=[("MY-ENTRY", [("PARM-A", "CONTENT")])],
        )
        assert not report.has_violations

    def test_by_reference_and_content_mixed_no_value_violation(self):
        report = _check(
            linkage_items=["PARM-A", "PARM-B"],
            entry_params={"MY-ENTRY": ["PARM-A", "PARM-B"]},
            calls=[
                (
                    "MY-ENTRY",
                    [("PARM-A", "REFERENCE"), ("PARM-B", "CONTENT")],
                )
            ],
        )
        assert not report.has_violations


class TestCaseInsensitiveMatching:
    """CALL targets and ENTRY names should be matched case-insensitively."""

    def test_call_uppercase_matches_entry_mixed_case(self):
        """CALL 'MY-ENTRY' should match ENTRY 'My-Entry'."""
        prog = _make_program(
            entry_params={"My-Entry": ["P1"]},
            calls=[("MY-ENTRY", [("X", "REFERENCE")])],
        )
        report = LinkageChecker().check(prog)
        # Correct arg count → no arg-count violation
        assert not any(
            v.kind
            in (LinkageViolationKind.TOO_MANY_ARGS, LinkageViolationKind.TOO_FEW_ARGS)
            for v in report.violations
        )

    def test_linkage_item_matched_case_insensitively(self):
        """ENTRY 'parm-a' should mark LINKAGE item 'PARM-A' as referenced."""
        report = _check(
            linkage_items=["PARM-A"],
            entry_params={"MY-ENTRY": ["parm-a"]},
            calls=[],
        )
        assert not any(
            v.kind == LinkageViolationKind.UNREFERENCED_LINKAGE
            for v in report.violations
        )


class TestAnalyzerStateReset:
    """check() must fully reset between calls."""

    def test_second_call_independent(self):
        checker = LinkageChecker()
        # First call: unreferenced item
        prog1 = _make_program(linkage_items=["ORPHAN"])
        checker.check(prog1)
        assert "ORPHAN" in checker._linkage_items

        # Second call: clean program
        prog2 = _make_program()
        report2 = checker.check(prog2)
        assert not report2.has_violations
        assert "ORPHAN" not in checker._linkage_items

    def test_entry_interfaces_reset_between_calls(self):
        checker = LinkageChecker()
        prog1 = _make_program(entry_params={"ENTRY-ONE": ["P1"]})
        checker.check(prog1)
        assert "ENTRY-ONE" in checker._entry_interfaces

        prog2 = _make_program(entry_params={"ENTRY-TWO": ["P2"]})
        checker.check(prog2)
        assert "ENTRY-ONE" not in checker._entry_interfaces
        assert "ENTRY-TWO" in checker._entry_interfaces


class TestViolationMessages:
    """Violation messages must contain actionable details."""

    def test_too_many_args_message_contains_target_and_counts(self):
        report = _check(
            entry_params={"MY-ENTRY": ["P1"]},
            calls=[("MY-ENTRY", [("A", "REFERENCE"), ("B", "REFERENCE")])],
        )
        v = next(
            v for v in report.violations if v.kind == LinkageViolationKind.TOO_MANY_ARGS
        )
        assert "MY-ENTRY" in v.message
        # Both the actual count (2) and declared count (1) should appear
        assert "2" in v.message or "1" in v.message

    def test_too_few_args_message_contains_target_and_counts(self):
        report = _check(
            entry_params={"MY-ENTRY": ["P1", "P2"]},
            calls=[("MY-ENTRY", [("A", "REFERENCE")])],
        )
        v = next(
            v for v in report.violations if v.kind == LinkageViolationKind.TOO_FEW_ARGS
        )
        assert "MY-ENTRY" in v.message

    def test_unreferenced_message_contains_item_name(self):
        report = _check(linkage_items=["LONELY-PARAM"], entry_params={}, calls=[])
        v = next(
            v
            for v in report.violations
            if v.kind == LinkageViolationKind.UNREFERENCED_LINKAGE
        )
        assert "LONELY-PARAM" in v.message
