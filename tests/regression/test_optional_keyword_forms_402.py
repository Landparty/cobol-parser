"""Regression tests for issue #402: optional-keyword forms that dropped data.

1. ``OCCURS n TO UNBOUNDED [TIMES] DEPENDING ON`` -- read as one occurrence.
2. ``RECORD IS VARYING [IN SIZE] n TO m`` without FROM -- minimum lost.
3. ``ENTRY ... USING BY REFERENCE / BY VALUE`` -- parameters dropped.
4. ``INITIALIZE ... FILLER`` without WITH -- FILLER read as a target.
"""

from __future__ import annotations

from typing import Any

from cobolparser import parse_cobol
from cobolparser.analysis.program_signature import ProgramSignatureExtractor


def _program(
    *,
    file_control: str = "",
    fd: str = "",
    working: str = "",
    linkage: str = "",
    procedure: str = "",
) -> str:
    return f"""       IDENTIFICATION DIVISION.
       PROGRAM-ID. T402.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
{file_control}
       DATA DIVISION.
       FILE SECTION.
{fd}
       WORKING-STORAGE SECTION.
       01 N  PIC 9(4).
       01 RL PIC 9(4).
{working}
       LINKAGE SECTION.
       01 X1 PIC X.
       01 X2 PIC X.
       01 A  PIC S9(4) COMP.
       01 B  PIC S9(4) COMP.
{linkage}
       PROCEDURE DIVISION.
{procedure}
           GOBACK.
"""


def _find(node: Any, name: str) -> dict[str, Any] | None:
    if isinstance(node, dict):
        if node.get("name") == name and "level" in node:
            return node
        for value in node.values():
            found = _find(value, name)
            if found is not None:
                return found
    elif isinstance(node, list):
        for value in node:
            found = _find(value, name)
            if found is not None:
                return found
    return None


def _find_key(node: Any, key: str) -> Any:
    if isinstance(node, dict):
        if isinstance(node.get(key), dict):
            return node[key]
        children = list(node.values())
    elif isinstance(node, list):
        children = node
    else:
        return None
    for value in children:
        found = _find_key(value, key)
        if found is not None:
            return found
    return None


# ---------------------------------------------------------------- OCCURS


class TestOccursToUnbounded:
    def _occurs(self, clause: str, name: str = "Z") -> tuple[dict[str, Any], Any]:
        result = parse_cobol(
            _program(linkage=f"       01 G.\n           05 {name} PIC X {clause}")
        )
        item = _find(result.ast.to_dict(), name)
        assert item is not None
        return item, result

    def test_to_unbounded_times_depending_on(self) -> None:
        item, result = self._occurs("OCCURS 1 TO UNBOUNDED TIMES DEPENDING ON N.")
        assert result.warnings == []
        occurs = item["occurs_clause"]
        assert occurs["min_times"] == 1
        assert occurs["max_times"] is None
        assert occurs["depending_on"] == "N"
        assert occurs["is_unbounded"] is True

    def test_to_unbounded_without_times_keeps_minimum(self) -> None:
        item, result = self._occurs("OCCURS 3 TO UNBOUNDED DEPENDING ON N.")
        assert result.warnings == []
        occurs = item["occurs_clause"]
        assert occurs["min_times"] == 3
        assert occurs["max_times"] is None
        assert occurs["is_unbounded"] is True

    def test_unbounded_on_continuation_line(self) -> None:
        item, result = self._occurs(
            "OCCURS 2 TO\n                 UNBOUNDED DEPENDING ON N."
        )
        assert result.warnings == []
        assert item["occurs_clause"]["min_times"] == 2
        assert item["occurs_clause"]["max_times"] is None

    def test_bounded_to_form_unchanged(self) -> None:
        item, _ = self._occurs("OCCURS 1 TO 5 TIMES DEPENDING ON N.")
        occurs = item["occurs_clause"]
        assert (occurs["min_times"], occurs["max_times"]) == (1, 5)
        assert "is_unbounded" not in occurs

    def test_following_item_still_parsed(self) -> None:
        result = parse_cobol(
            _program(
                linkage=(
                    "       01 G.\n"
                    "           05 Z PIC X OCCURS 1 TO UNBOUNDED DEPENDING ON N.\n"
                    "       01 AFTER-Z PIC X."
                )
            )
        )
        assert result.warnings == []
        assert _find(result.ast.to_dict(), "AFTER-Z") is not None


# ---------------------------------------------------------- RECORD VARYING


class TestRecordVaryingWithoutFrom:
    def _record(self, clause: str) -> dict[str, Any]:
        result = parse_cobol(
            _program(
                file_control="           SELECT F1 ASSIGN TO 'F1'.",
                fd=f"       FD F1\n           {clause}.\n       01 F1R PIC X(30).",
            )
        )
        assert result.warnings == []
        record = _find_key(result.ast.to_dict(), "record")
        assert isinstance(record, dict) and "varying" in record
        return record

    def test_in_size_without_from(self) -> None:
        record = self._record(
            "RECORD IS VARYING IN SIZE 10 TO 30\n"
            "           CHARACTERS DEPENDING ON RL"
        )
        assert record == {
            "varying": True,
            "min": 10,
            "max": 30,
            "depending_on": "RL",
        }

    def test_size_without_in_or_from(self) -> None:
        record = self._record("RECORD VARYING SIZE 10 TO 30 DEPENDING RL")
        assert (record["min"], record["max"]) == (10, 30)

    def test_with_from_unchanged(self) -> None:
        record = self._record("RECORD IS VARYING IN SIZE FROM 10 TO 30")
        assert (record["min"], record["max"]) == (10, 30)

    def test_minimum_only_has_no_maximum(self) -> None:
        record = self._record(
            "RECORD VARYING IN SIZE 10 CHARACTERS\n           DEPENDING RL"
        )
        assert (record["min"], record["max"], record["depending_on"]) == (
            10,
            None,
            "RL",
        )

    def test_to_only_still_has_no_minimum(self) -> None:
        record = self._record("RECORD IS VARYING IN SIZE TO 80")
        assert (record["min"], record["max"]) == (None, 80)


# ------------------------------------------------------------------ ENTRY


class TestEntryUsingPassingModes:
    def _entry(self, statement: str) -> tuple[Any, Any]:
        result = parse_cobol(_program(procedure=f"           {statement}"))
        entries = result.ast.find_all_by_type("EntryStatement")
        assert len(entries) == 1
        return entries[0], result

    def test_by_reference(self) -> None:
        entry, result = self._entry("ENTRY 'E1' USING BY REFERENCE X1 X2.")
        assert result.warnings == []
        assert entry.using_parameters == ["X1", "X2"]
        assert entry.parameter_modes == ["REFERENCE", "REFERENCE"]

    def test_by_value(self) -> None:
        entry, result = self._entry("ENTRY 'E1' USING BY VALUE A B.")
        assert result.warnings == []
        assert entry.using_parameters == ["A", "B"]
        assert entry.parameter_modes == ["VALUE", "VALUE"]

    def test_value_without_by_is_not_a_parameter(self) -> None:
        entry, _ = self._entry("ENTRY 'E1' USING VALUE A B.")
        assert entry.using_parameters == ["A", "B"]
        assert entry.parameter_modes == ["VALUE", "VALUE"]
        assert "VALUE" not in entry.operands

    def test_mode_switches_mid_list(self) -> None:
        entry, result = self._entry("ENTRY 'E1' USING X1 BY VALUE A B BY REFERENCE X2.")
        assert result.warnings == []
        assert entry.using_parameters == ["X1", "A", "B", "X2"]
        assert entry.parameter_modes == ["REFERENCE", "VALUE", "VALUE", "REFERENCE"]

    def test_plain_using_defaults_to_reference(self) -> None:
        entry, _ = self._entry("ENTRY 'DLITCBL' USING X1 X2.")
        assert entry.using_parameters == ["X1", "X2"]
        assert entry.parameter_modes == ["REFERENCE", "REFERENCE"]
        assert entry.to_dict()["parameter_modes"] == ["REFERENCE", "REFERENCE"]

    def test_program_signature_carries_entry_modes(self) -> None:
        result = parse_cobol(
            _program(procedure="           ENTRY 'E1' USING X1 BY VALUE A.")
        )
        signature = ProgramSignatureExtractor().analyze(result.ast)
        entry = next(e for e in signature.entry_points if e.name == "E1")
        assert [(p.name, p.by_clause) for p in entry.parameters] == [
            ("X1", "REFERENCE"),
            ("A", "VALUE"),
        ]


# ------------------------------------------------------------- INITIALIZE


class TestInitializeBareFiller:
    def _initialize(self, statement: str) -> tuple[Any, Any]:
        result = parse_cobol(
            _program(
                working="       01 W1 PIC X.\n       01 W2 PIC X.",
                procedure=f"           {statement}",
            )
        )
        stmts = result.ast.find_all_by_type("InitializeStatement")
        assert len(stmts) == 1
        return stmts[0], result

    def test_filler_without_with(self) -> None:
        stmt, result = self._initialize("INITIALIZE W1 FILLER ALL TO VALUE.")
        assert result.warnings == []
        assert stmt.targets == ["W1"]
        assert stmt.with_filler is True
        assert stmt.to_value_category == "ALL"

    def test_filler_without_with_after_several_targets(self) -> None:
        stmt, _ = self._initialize("INITIALIZE W1 W2 FILLER.")
        assert stmt.targets == ["W1", "W2"]
        assert stmt.with_filler is True

    def test_with_filler_unchanged(self) -> None:
        stmt, _ = self._initialize("INITIALIZE W1 WITH FILLER ALL TO VALUE.")
        assert stmt.targets == ["W1"]
        assert stmt.with_filler is True

    def test_no_filler(self) -> None:
        stmt, _ = self._initialize("INITIALIZE W1 W2.")
        assert stmt.targets == ["W1", "W2"]
        assert stmt.with_filler is False
