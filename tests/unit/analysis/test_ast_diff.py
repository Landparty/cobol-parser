"""Tests for the structural (semantic) diff between two parsed programs.

Programs come from real parses (``parse_cobol``) rather than hand-built
ASTs wherever possible, so the reported changes are pinned against what the
parser actually produces. A couple of tests build a tiny AST by hand where
the shape being exercised (an undecomposable nested statement) cannot be
written in COBOL source that this parser produces.
"""

from __future__ import annotations

import json
from typing import Any

from cobolparser.analysis.ast_diff import (
    DiffChange,
    DiffReport,
    ProgramDiffer,
)
from cobolparser.models.ast_base import SourceLocation
from cobolparser.models.data_items import RenamesItem
from cobolparser.models.program import (
    CobolDivision,
    CobolParagraph,
    CobolProgram,
    CobolSection,
)
from cobolparser.models.statements.base import CobolStatement
from cobolparser.parser import parse_cobol

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse(source: str) -> CobolProgram:
    result = parse_cobol(source, filename="prog.cbl")
    assert result.ast is not None, result.errors
    return result.ast


def _diff(old_source: str, new_source: str, **kwargs: Any) -> DiffReport:
    return ProgramDiffer(**kwargs).diff(_parse(old_source), _parse(new_source))


def _kinds(report: DiffReport) -> list[str]:
    return [change.kind for change in report.changes]


def _of_kind(report: DiffReport, kind: str) -> list[DiffChange]:
    return [change for change in report.changes if change.kind == kind]


def _program(procedure: str, data: str = "", program_id: str = "DIFFPROG") -> str:
    """A minimal, parseable program with the given DATA/PROCEDURE bodies."""
    data_division = f"       DATA DIVISION.\n{data}" if data else ""
    return (
        "       IDENTIFICATION DIVISION.\n"
        f"       PROGRAM-ID. {program_id}.\n"
        f"{data_division}"
        "       PROCEDURE DIVISION.\n"
        f"{procedure}"
    )


_WS = (
    "       WORKING-STORAGE SECTION.\n"
    "       01  WS-A             PIC 9(5).\n"
    "       01  WS-B             PIC X(10).\n"
)


# ---------------------------------------------------------------------------
# Identical programs / determinism
# ---------------------------------------------------------------------------


def test_identical_programs_produce_no_changes():
    source = _program(
        "       MAIN-PARA.\n"
        "           PERFORM INIT-PARA\n"
        "           MOVE 1 TO WS-A\n"
        "           STOP RUN.\n"
        "       INIT-PARA.\n"
        "           MOVE SPACES TO WS-B.\n",
        data=_WS,
    )
    report = _diff(source, source)

    assert report.changes == []
    assert report.change_count == 0
    assert report.has_changes is False
    assert report.old_program == "DIFFPROG"
    assert report.new_program == "DIFFPROG"


def test_reformatting_alone_is_not_a_change():
    """Extra blank lines / indentation shift every source line, nothing else."""
    old = _program(
        "       MAIN-PARA.\n           MOVE 1 TO WS-A\n           STOP RUN.\n",
        data=_WS,
    )
    new = _program(
        "\n"
        "       MAIN-PARA.\n"
        "\n"
        "            MOVE 1 TO WS-A\n"
        "\n"
        "            STOP RUN.\n",
        data=_WS,
    )
    report = _diff(old, new)

    assert report.changes == []


def test_diffing_the_same_pair_twice_is_byte_identical():
    old = _program(
        "       MAIN-PARA.\n"
        "           PERFORM ONE-PARA\n"
        "           CALL 'SUBA'\n"
        "           STOP RUN.\n"
        "       ONE-PARA.\n"
        "           MOVE 1 TO WS-A.\n"
        "       TWO-PARA.\n"
        "           MOVE 2 TO WS-A.\n",
        data=_WS,
    )
    new = _program(
        "       MAIN-PARA.\n"
        "           PERFORM TWO-PARA\n"
        "           CALL 'SUBB'\n"
        "           STOP RUN.\n"
        "       TWO-PARA.\n"
        "           MOVE 2 TO WS-A.\n"
        "       THREE-PARA.\n"
        "           MOVE 3 TO WS-B.\n",
        data=_WS,
        program_id="OTHERPRG",
    )

    first = _diff(old, new).to_dict()
    second = _diff(old, new).to_dict()

    assert first == second
    assert json.dumps(first) == json.dumps(second)


def test_changes_are_sorted_by_category_then_symbol_then_kind():
    old = _program(
        "       MAIN-PARA.\n           MOVE 1 TO WS-A\n           STOP RUN.\n",
        data=_WS,
    )
    new = _program(
        "       MAIN-PARA.\n           MOVE 2 TO WS-B\n           STOP RUN.\n"
        "       EXTRA-PARA.\n           MOVE 3 TO WS-A.\n",
        data=(
            "       WORKING-STORAGE SECTION.\n"
            "       01  WS-A             PIC 9(7).\n"
            "       01  WS-B             PIC X(10).\n"
        ),
        program_id="RENAMED",
    )
    report = _diff(old, new)

    keys = [(change.category, change.symbol, change.kind) for change in report.changes]
    assert keys == sorted(keys)
    assert {change.category for change in report.changes} >= {
        "data",
        "procedure",
        "program",
    }


# ---------------------------------------------------------------------------
# Program level
# ---------------------------------------------------------------------------


def test_program_id_changed():
    old = _program("       MAIN-PARA.\n           STOP RUN.\n", program_id="ALPHA")
    new = _program("       MAIN-PARA.\n           STOP RUN.\n", program_id="BETA")
    report = _diff(old, new)

    changes = _of_kind(report, "program-id-changed")
    assert len(changes) == 1
    assert changes[0].category == "program"
    assert changes[0].old == "ALPHA"
    assert changes[0].new == "BETA"
    assert "ALPHA" in changes[0].detail and "BETA" in changes[0].detail


def test_program_id_case_change_is_not_a_change():
    old = _program("       MAIN-PARA.\n           STOP RUN.\n", program_id="ALPHA")
    new = _program("       MAIN-PARA.\n           STOP RUN.\n", program_id="Alpha")
    assert _of_kind(_diff(old, new), "program-id-changed") == []


def test_division_added_and_removed():
    old = _program("       MAIN-PARA.\n           STOP RUN.\n")
    new = _program("       MAIN-PARA.\n           STOP RUN.\n", data=_WS)

    added = _of_kind(_diff(old, new), "division-added")
    assert [change.symbol for change in added] == ["DATA DIVISION"]

    removed = _of_kind(_diff(new, old), "division-removed")
    assert [change.symbol for change in removed] == ["DATA DIVISION"]


def test_procedure_division_using_changed():
    template = (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. USINGPRG.\n"
        "       DATA DIVISION.\n"
        "       LINKAGE SECTION.\n"
        "       01  L-A PIC X.\n"
        "       01  L-B PIC X.\n"
        "       PROCEDURE DIVISION USING {params}.\n"
        "       MAIN-PARA.\n"
        "           GOBACK.\n"
    )
    report = _diff(template.format(params="L-A"), template.format(params="L-A L-B"))

    changes = _of_kind(report, "procedure-using-changed")
    assert len(changes) == 1
    assert changes[0].old == "L-A"
    assert changes[0].new == "L-A, L-B"


# ---------------------------------------------------------------------------
# Procedures: rename, move, add, remove
# ---------------------------------------------------------------------------


_RENAME_BODY = (
    "       MAIN-PARA.\n"
    "           PERFORM {target}\n"
    "           STOP RUN.\n"
    "       {name}.\n"
    "           MOVE 1 TO WS-A\n"
    "           MOVE SPACES TO WS-B\n"
    "           ADD 1 TO WS-A.\n"
)


def test_pure_rename_is_a_rename_not_add_plus_remove():
    old = _program(
        _RENAME_BODY.format(name="OLD-NAME-PARA", target="OLD-NAME-PARA"), data=_WS
    )
    new = _program(
        _RENAME_BODY.format(name="NEW-NAME-PARA", target="NEW-NAME-PARA"), data=_WS
    )
    report = _diff(old, new)

    renames = _of_kind(report, "paragraph-renamed")
    assert len(renames) == 1
    assert renames[0].old == "OLD-NAME-PARA"
    assert renames[0].new == "NEW-NAME-PARA"
    assert renames[0].symbol == "NEW-NAME-PARA"
    assert renames[0].category == "procedure"

    assert _of_kind(report, "paragraph-added") == []
    assert _of_kind(report, "paragraph-removed") == []
    # The renamed paragraph's own body did not change.
    assert [c.symbol for c in _of_kind(report, "paragraph-body-changed")] == [
        "MAIN-PARA"
    ]


def test_renamed_paragraph_keeps_its_source_locations():
    old = _program(
        _RENAME_BODY.format(name="OLD-NAME-PARA", target="OLD-NAME-PARA"), data=_WS
    )
    new = _program(
        "\n\n" + _RENAME_BODY.format(name="NEW-NAME-PARA", target="NEW-NAME-PARA"),
        data=_WS,
    )
    change = _of_kind(_diff(old, new), "paragraph-renamed")[0]

    assert change.old_location is not None
    assert change.new_location is not None
    assert change.new_location.line > change.old_location.line


def test_empty_bodies_never_rename_match():
    """Two empty paragraphs are no evidence of a rename (ratio would be 1.0)."""
    old = _program(
        "       MAIN-PARA.\n           STOP RUN.\n       OLD-STUB.\n           EXIT.\n"
    )
    new = _program(
        "       MAIN-PARA.\n           STOP RUN.\n       NEW-STUB.\n           EXIT.\n"
    )
    report = _diff(old, new)

    # EXIT is a statement, so these stubs are not literally empty -- but they
    # are identical, so the rename must be *found*, not refused.
    assert [c.new for c in _of_kind(report, "paragraph-renamed")] == ["NEW-STUB"]


def test_truly_empty_bodies_are_reported_as_add_plus_remove():
    loc = SourceLocation(1, 1)
    old = CobolProgram("EMPTYP", loc)
    new = CobolProgram("EMPTYP", loc)
    for program, name in ((old, "OLD-EMPTY"), (new, "NEW-EMPTY")):
        division = CobolDivision("PROCEDURE", loc)
        division.add_paragraph(CobolParagraph(name, SourceLocation(10, 8)))
        program.add_division(division)

    report = ProgramDiffer().diff(old, new)

    assert _of_kind(report, "paragraph-renamed") == []
    assert [c.new for c in _of_kind(report, "paragraph-added")] == ["NEW-EMPTY"]
    assert [c.old for c in _of_kind(report, "paragraph-removed")] == ["OLD-EMPTY"]


def test_reorder_is_a_move_not_a_body_change():
    old = _program(
        "       MAIN-PARA.\n"
        "           PERFORM A-PARA\n"
        "           PERFORM B-PARA\n"
        "           STOP RUN.\n"
        "       A-PARA.\n"
        "           MOVE 1 TO WS-A.\n"
        "       B-PARA.\n"
        "           MOVE 2 TO WS-A.\n",
        data=_WS,
    )
    new = _program(
        "       MAIN-PARA.\n"
        "           PERFORM A-PARA\n"
        "           PERFORM B-PARA\n"
        "           STOP RUN.\n"
        "       B-PARA.\n"
        "           MOVE 2 TO WS-A.\n"
        "       A-PARA.\n"
        "           MOVE 1 TO WS-A.\n",
        data=_WS,
    )
    report = _diff(old, new)

    moved = _of_kind(report, "paragraph-moved")
    assert len(moved) == 1
    assert moved[0].symbol in {"A-PARA", "B-PARA"}
    assert moved[0].old != moved[0].new
    assert "position" in moved[0].detail

    assert _of_kind(report, "paragraph-body-changed") == []
    assert _of_kind(report, "paragraph-added") == []
    assert _of_kind(report, "paragraph-removed") == []


def test_inserting_a_paragraph_does_not_report_everything_after_it_as_moved():
    old = _program(
        "       MAIN-PARA.\n           STOP RUN.\n"
        "       A-PARA.\n           MOVE 1 TO WS-A.\n"
        "       B-PARA.\n           MOVE 2 TO WS-A.\n",
        data=_WS,
    )
    new = _program(
        "       NEW-FIRST.\n           MOVE 9 TO WS-A.\n"
        "       MAIN-PARA.\n           STOP RUN.\n"
        "       A-PARA.\n           MOVE 1 TO WS-A.\n"
        "       B-PARA.\n           MOVE 2 TO WS-A.\n",
        data=_WS,
    )
    report = _diff(old, new)

    assert [c.new for c in _of_kind(report, "paragraph-added")] == ["NEW-FIRST"]
    assert _of_kind(report, "paragraph-moved") == []


def test_added_and_removed_paragraphs():
    old = _program(
        "       MAIN-PARA.\n           STOP RUN.\n"
        "       GONE-PARA.\n           MOVE 1 TO WS-A\n           ADD 1 TO WS-A.\n",
        data=_WS,
    )
    new = _program(
        "       MAIN-PARA.\n           STOP RUN.\n"
        "       FRESH-PARA.\n"
        "           DISPLAY 'HI'\n"
        "           MOVE SPACES TO WS-B.\n",
        data=_WS,
    )
    report = _diff(old, new)

    assert [c.symbol for c in _of_kind(report, "paragraph-added")] == ["FRESH-PARA"]
    assert [c.symbol for c in _of_kind(report, "paragraph-removed")] == ["GONE-PARA"]
    assert _of_kind(report, "paragraph-renamed") == []


def test_near_miss_rename_is_reported_as_add_plus_remove_with_a_caveat():
    old = _program(
        "       MAIN-PARA.\n           STOP RUN.\n"
        "       GONE-PARA.\n           MOVE 1 TO WS-A\n           ADD 1 TO WS-A.\n",
        data=_WS,
    )
    new = _program(
        "       MAIN-PARA.\n           STOP RUN.\n"
        "       FRESH-PARA.\n"
        "           DISPLAY 'HI'\n"
        "           MOVE SPACES TO WS-B.\n",
        data=_WS,
    )
    report = _diff(old, new)

    assert any("below the 0.80 rename threshold" in caveat for caveat in report.caveats)
    assert any("GONE-PARA" in caveat for caveat in report.caveats)


def test_rename_threshold_is_configurable():
    body = (
        "       MAIN-PARA.\n           STOP RUN.\n"
        "       {name}.\n"
        "           MOVE 1 TO WS-A\n"
        "           MOVE 2 TO WS-A\n"
        "           MOVE 3 TO WS-A\n"
        "           MOVE 4 TO WS-A\n"
        "           {last}.\n"
    )
    old = _program(body.format(name="OLD-WORK", last="MOVE 5 TO WS-A"), data=_WS)
    new = _program(body.format(name="NEW-WORK", last="MOVE 9 TO WS-B"), data=_WS)

    lenient = _diff(old, new, rename_threshold=0.5)
    assert [c.new for c in _of_kind(lenient, "paragraph-renamed")] == ["NEW-WORK"]
    # A renamed paragraph whose body also changed reports both facts.
    assert [c.symbol for c in _of_kind(lenient, "paragraph-body-changed")] == [
        "NEW-WORK"
    ]

    strict = _diff(old, new, rename_threshold=1.0)
    assert _of_kind(strict, "paragraph-renamed") == []
    assert [c.symbol for c in _of_kind(strict, "paragraph-added")] == ["NEW-WORK"]
    assert [c.symbol for c in _of_kind(strict, "paragraph-removed")] == ["OLD-WORK"]


def test_default_rename_threshold_is_documented_value():
    assert ProgramDiffer().rename_threshold == 0.8


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------


_SECTION_PROGRAM = (
    "       {first} SECTION.\n"
    "       MAIN-PARA.\n"
    "           PERFORM WORK-PARA\n"
    "           STOP RUN.\n"
    "       {second} SECTION.\n"
    "       WORK-PARA.\n"
    "           MOVE 1 TO WS-A\n"
    "           MOVE SPACES TO WS-B.\n"
)


def test_section_added_and_removed():
    old = _program(
        "       ONLY-SECT SECTION.\n" "       MAIN-PARA.\n" "           STOP RUN.\n",
        data=_WS,
    )
    new = _program(
        "       ONLY-SECT SECTION.\n"
        "       MAIN-PARA.\n"
        "           STOP RUN.\n"
        "       EXTRA-SECT SECTION.\n"
        "       EXTRA-PARA.\n"
        "           MOVE 1 TO WS-A.\n",
        data=_WS,
    )
    report = _diff(old, new)

    assert [c.symbol for c in _of_kind(report, "section-added")] == ["EXTRA-SECT"]
    assert [c.symbol for c in _of_kind(_diff(new, old), "section-removed")] == [
        "EXTRA-SECT"
    ]


def test_section_renamed_by_fingerprint():
    old = _program(
        _SECTION_PROGRAM.format(first="MAIN-SECT", second="OLD-SECT"), data=_WS
    )
    new = _program(
        _SECTION_PROGRAM.format(first="MAIN-SECT", second="NEW-SECT"), data=_WS
    )
    report = _diff(old, new)

    renames = _of_kind(report, "section-renamed")
    assert [(c.old, c.new) for c in renames] == [("OLD-SECT", "NEW-SECT")]
    assert _of_kind(report, "section-added") == []
    assert _of_kind(report, "section-removed") == []


def test_section_body_changed_is_reported_for_the_section_too():
    old = _program(
        _SECTION_PROGRAM.format(first="MAIN-SECT", second="WORK-SECT"), data=_WS
    )
    new = _program(
        (
            "       MAIN-SECT SECTION.\n"
            "       MAIN-PARA.\n"
            "           PERFORM WORK-PARA\n"
            "           STOP RUN.\n"
            "       WORK-SECT SECTION.\n"
            "       WORK-PARA.\n"
            "           MOVE 2 TO WS-A\n"
            "           MOVE SPACES TO WS-B.\n"
        ),
        data=_WS,
    )
    report = _diff(old, new)

    assert [c.symbol for c in _of_kind(report, "section-body-changed")] == ["WORK-SECT"]
    assert "WORK-PARA" in [c.symbol for c in _of_kind(report, "paragraph-body-changed")]


def test_paragraph_moved_between_sections_is_reported_as_a_move():
    old = _program(
        "       A-SECT SECTION.\n"
        "       SHARED-PARA.\n"
        "           MOVE 1 TO WS-A.\n"
        "       B-SECT SECTION.\n"
        "       OTHER-PARA.\n"
        "           STOP RUN.\n",
        data=_WS,
    )
    new = _program(
        "       A-SECT SECTION.\n"
        "       OTHER-PARA.\n"
        "           STOP RUN.\n"
        "       B-SECT SECTION.\n"
        "       SHARED-PARA.\n"
        "           MOVE 1 TO WS-A.\n",
        data=_WS,
    )
    report = _diff(old, new)

    moved = {c.symbol for c in _of_kind(report, "paragraph-moved")}
    assert "SHARED-PARA" in moved
    assert any("section" in c.detail for c in _of_kind(report, "paragraph-moved"))


# ---------------------------------------------------------------------------
# Statements
# ---------------------------------------------------------------------------


def _statement_diff(old_body: str, new_body: str) -> DiffReport:
    return _diff(
        _program(f"       MAIN-PARA.\n{old_body}", data=_WS),
        _program(f"       MAIN-PARA.\n{new_body}", data=_WS),
    )


def test_changed_perform_target():
    report = _statement_diff(
        "           PERFORM ONE-PARA\n           STOP RUN.\n"
        "       ONE-PARA.\n           MOVE 1 TO WS-A.\n"
        "       TWO-PARA.\n           MOVE 2 TO WS-B.\n",
        "           PERFORM TWO-PARA\n           STOP RUN.\n"
        "       ONE-PARA.\n           MOVE 1 TO WS-A.\n"
        "       TWO-PARA.\n           MOVE 2 TO WS-B.\n",
    )

    changes = _of_kind(report, "perform-target-changed")
    assert len(changes) == 1
    assert changes[0].symbol == "MAIN-PARA"
    assert changes[0].old == "PERFORM ONE-PARA"
    assert changes[0].new == "PERFORM TWO-PARA"
    assert _of_kind(report, "statement-changed") == []


def test_set_up_to_down_is_a_change_with_distinct_text():
    # #274: both sides used to render as "SET WS-A TO 1".
    report = _statement_diff(
        "           SET WS-A UP BY 1\n           STOP RUN.\n",
        "           SET WS-A DOWN BY 1\n           STOP RUN.\n",
    )

    changes = _of_kind(report, "statement-changed")
    assert len(changes) == 1
    assert changes[0].old == "SET WS-A UP BY 1"
    assert changes[0].new == "SET WS-A DOWN BY 1"


def test_perform_varying_from_change_has_distinct_text():
    tail = "           STOP RUN.\n       P2.\n           CONTINUE.\n"
    report = _statement_diff(
        "           PERFORM P2 VARYING WS-A FROM 1 BY 1 UNTIL WS-A > 3\n" + tail,
        "           PERFORM P2 VARYING WS-A FROM 2 BY 1 UNTIL WS-A > 3\n" + tail,
    )

    changes = _of_kind(report, "statement-changed")
    assert len(changes) == 1
    assert changes[0].old == "PERFORM P2 VARYING WS-A FROM 1 BY 1 UNTIL WS-A > 3"
    assert changes[0].new == "PERFORM P2 VARYING WS-A FROM 2 BY 1 UNTIL WS-A > 3"


def test_compute_rounded_change_has_distinct_text():
    report = _statement_diff(
        "           COMPUTE WS-A = WS-A / 3\n           STOP RUN.\n",
        "           COMPUTE WS-A ROUNDED = WS-A / 3\n           STOP RUN.\n",
    )

    changes = _of_kind(report, "statement-changed")
    assert len(changes) == 1
    assert changes[0].old == "COMPUTE WS-A = WS-A / 3"
    assert changes[0].new == "COMPUTE WS-A ROUNDED = WS-A / 3"


def test_changed_call_target():
    report = _statement_diff(
        "           CALL 'SUBA' USING WS-A\n           STOP RUN.\n",
        "           CALL 'SUBB' USING WS-A\n           STOP RUN.\n",
    )

    changes = _of_kind(report, "call-target-changed")
    assert len(changes) == 1
    assert "SUBA" in (changes[0].old or "")
    assert "SUBB" in (changes[0].new or "")


def test_changed_call_arguments():
    report = _statement_diff(
        "           CALL 'SUBA' USING WS-A\n           STOP RUN.\n",
        "           CALL 'SUBA' USING WS-A WS-B\n           STOP RUN.\n",
    )

    assert len(_of_kind(report, "call-arguments-changed")) == 1
    assert _of_kind(report, "call-target-changed") == []


def test_changed_move_target_and_source():
    target_changed = _statement_diff(
        "           MOVE 1 TO WS-A\n           STOP RUN.\n",
        "           MOVE 1 TO WS-B\n           STOP RUN.\n",
    )
    assert len(_of_kind(target_changed, "move-target-changed")) == 1

    source_changed = _statement_diff(
        "           MOVE 1 TO WS-A\n           STOP RUN.\n",
        "           MOVE 2 TO WS-A\n           STOP RUN.\n",
    )
    assert len(_of_kind(source_changed, "move-source-changed")) == 1


def test_changed_if_condition_is_a_condition_change_not_a_rewrite():
    report = _statement_diff(
        "           IF WS-A > 5\n"
        "              MOVE 1 TO WS-A\n"
        "           END-IF\n"
        "           STOP RUN.\n",
        "           IF WS-A > 9\n"
        "              MOVE 1 TO WS-A\n"
        "           END-IF\n"
        "           STOP RUN.\n",
    )

    changes = _of_kind(report, "condition-changed")
    assert len(changes) == 1
    assert "IF" in changes[0].detail
    # The unchanged statement inside the THEN arm is not reported.
    assert _of_kind(report, "statement-added") == []
    assert _of_kind(report, "statement-removed") == []


def test_change_inside_a_branch_is_reported_at_the_branch_it_lives_in():
    report = _statement_diff(
        "           IF WS-A > 5\n"
        "              MOVE 1 TO WS-A\n"
        "           ELSE\n"
        "              MOVE 2 TO WS-A\n"
        "           END-IF\n"
        "           STOP RUN.\n",
        "           IF WS-A > 5\n"
        "              MOVE 1 TO WS-A\n"
        "           ELSE\n"
        "              MOVE 3 TO WS-A\n"
        "           END-IF\n"
        "           STOP RUN.\n",
    )

    changes = _of_kind(report, "move-source-changed")
    assert len(changes) == 1
    assert "IF/ELSE" in changes[0].detail


def test_changed_perform_until_condition():
    report = _statement_diff(
        "           PERFORM UNTIL WS-A > 5\n"
        "              ADD 1 TO WS-A\n"
        "           END-PERFORM\n"
        "           STOP RUN.\n",
        "           PERFORM UNTIL WS-A > 9\n"
        "              ADD 1 TO WS-A\n"
        "           END-PERFORM\n"
        "           STOP RUN.\n",
    )

    changes = _of_kind(report, "condition-changed")
    assert len(changes) == 1
    assert "PERFORM UNTIL" in changes[0].detail


def test_changed_evaluate_when_selector():
    report = _statement_diff(
        "           EVALUATE WS-A\n"
        "              WHEN 1\n"
        "                 MOVE 1 TO WS-B\n"
        "              WHEN OTHER\n"
        "                 MOVE 2 TO WS-B\n"
        "           END-EVALUATE\n"
        "           STOP RUN.\n",
        "           EVALUATE WS-A\n"
        "              WHEN 7\n"
        "                 MOVE 1 TO WS-B\n"
        "              WHEN OTHER\n"
        "                 MOVE 2 TO WS-B\n"
        "           END-EVALUATE\n"
        "           STOP RUN.\n",
    )

    changes = _of_kind(report, "condition-changed")
    assert len(changes) == 1
    assert "WHEN" in changes[0].detail


def test_changed_goto_target():
    report = _statement_diff(
        "           GO TO ONE-PARA.\n"
        "       ONE-PARA.\n           MOVE 1 TO WS-A.\n"
        "       TWO-PARA.\n           MOVE 2 TO WS-B.\n",
        "           GO TO TWO-PARA.\n"
        "       ONE-PARA.\n           MOVE 1 TO WS-A.\n"
        "       TWO-PARA.\n           MOVE 2 TO WS-B.\n",
    )

    assert len(_of_kind(report, "goto-target-changed")) == 1


def test_added_and_removed_statements():
    report = _statement_diff(
        "           MOVE 1 TO WS-A\n           STOP RUN.\n",
        "           MOVE 1 TO WS-A\n"
        "           DISPLAY 'DONE'\n"
        "           STOP RUN.\n",
    )

    added = _of_kind(report, "statement-added")
    assert len(added) == 1
    assert "DISPLAY" in (added[0].new or "")
    assert added[0].symbol == "MAIN-PARA"

    reverse = _statement_diff(
        "           MOVE 1 TO WS-A\n"
        "           DISPLAY 'DONE'\n"
        "           STOP RUN.\n",
        "           MOVE 1 TO WS-A\n           STOP RUN.\n",
    )
    removed = _of_kind(reverse, "statement-removed")
    assert len(removed) == 1
    assert "DISPLAY" in (removed[0].old or "")


def test_replaced_statement_of_a_different_verb_is_add_plus_remove():
    report = _statement_diff(
        "           MOVE 1 TO WS-A\n           STOP RUN.\n",
        "           ADD 1 TO WS-A\n           STOP RUN.\n",
    )

    assert len(_of_kind(report, "statement-added")) == 1
    assert len(_of_kind(report, "statement-removed")) == 1
    assert _of_kind(report, "statement-changed") == []


def test_generic_statement_change_falls_back_to_statement_changed():
    report = _statement_diff(
        "           DISPLAY 'ONE'\n           STOP RUN.\n",
        "           DISPLAY 'TWO'\n           STOP RUN.\n",
    )

    changes = _of_kind(report, "statement-changed")
    assert len(changes) == 1
    assert "ONE" in (changes[0].old or "")
    assert "TWO" in (changes[0].new or "")


def test_generic_statement_clause_change_is_not_missed():
    # The rendered summary of STRING / READ omits INTO; the change must
    # still be reported, while a nested AT END body stays compared apart.
    report = _statement_diff(
        "           STRING 'X' DELIMITED BY SIZE INTO WS-B\n           STOP RUN.\n",
        "           STRING 'X' DELIMITED BY SIZE INTO WS-A\n           STOP RUN.\n",
    )
    assert len(_of_kind(report, "statement-changed")) == 1

    report = _statement_diff(
        "           STRING 'X' DELIMITED BY SIZE INTO WS-B\n"
        "               ON OVERFLOW DISPLAY 'A'\n"
        "           END-STRING\n           STOP RUN.\n",
        "           STRING 'X' DELIMITED BY SIZE INTO WS-B\n"
        "               ON OVERFLOW DISPLAY 'B'\n"
        "           END-STRING\n           STOP RUN.\n",
    )
    changes = _of_kind(report, "statement-changed")
    assert [change.old for change in changes] == ['DISPLAY "A"']


# ---------------------------------------------------------------------------
# Data items
# ---------------------------------------------------------------------------


def _data_diff(old_data: str, new_data: str) -> DiffReport:
    body = "       MAIN-PARA.\n           STOP RUN.\n"
    return _diff(_program(body, data=old_data), _program(body, data=new_data))


def test_picture_changed():
    report = _data_diff(
        "       WORKING-STORAGE SECTION.\n       01  WS-A PIC X(5).\n",
        "       WORKING-STORAGE SECTION.\n       01  WS-A PIC X(9).\n",
    )

    changes = _of_kind(report, "picture-changed")
    assert len(changes) == 1
    assert changes[0].category == "data"
    assert changes[0].symbol == "WS-A"
    assert changes[0].old == "X(5)"
    assert changes[0].new == "X(9)"


def test_equivalent_picture_spellings_are_not_a_change():
    # `X(2)` and `XX` (and `S9(3)V9(2)` / `S999V99`) are one PICTURE; a
    # rewrite from one spelling to the other used to read as picture-changed.
    report = _data_diff(
        "       WORKING-STORAGE SECTION.\n"
        "       01  WS-A PIC X(2).\n"
        "       01  WS-B PIC S9(3)V9(2).\n"
        "       01  WS-C PIC 9(4).\n",
        "       WORKING-STORAGE SECTION.\n"
        "       01  WS-A PIC XX.\n"
        "       01  WS-B PIC S999V99.\n"
        "       01  WS-C PIC 9(5).\n",
    )

    changes = _of_kind(report, "picture-changed")
    assert [(c.symbol, c.old, c.new) for c in changes] == [("WS-C", "9(4)", "9(5)")]


def test_usage_synonyms_are_not_a_change():
    report = _data_diff(
        "       WORKING-STORAGE SECTION.\n"
        "       01  WS-A PIC S9(5) COMP-3.\n"
        "       01  WS-B PIC S9(4) COMP.\n"
        "       01  WS-C PIC S9(4) COMPUTATIONAL-4.\n"
        "       01  WS-D PIC S9(4) COMP.\n",
        "       WORKING-STORAGE SECTION.\n"
        "       01  WS-A PIC S9(5) PACKED-DECIMAL.\n"
        "       01  WS-B PIC S9(4) BINARY.\n"
        "       01  WS-C PIC S9(4) COMP.\n"
        "       01  WS-D PIC S9(4) COMP-5.\n",
    )

    # COMP-5 is not truncated to its PICTURE, so COMP -> COMP-5 is real.
    changes = _of_kind(report, "usage-changed")
    assert [(c.symbol, c.old, c.new) for c in changes] == [("WS-D", "COMP", "COMP-5")]


def test_usage_level_and_value_changed():
    report = _data_diff(
        "       WORKING-STORAGE SECTION.\n"
        "       01  WS-GRP.\n"
        "           05  WS-A PIC 9(5) VALUE 1.\n",
        "       WORKING-STORAGE SECTION.\n"
        "       01  WS-GRP.\n"
        "           03  WS-A PIC 9(5) COMP-3 VALUE 2.\n",
    )

    assert [c.symbol for c in _of_kind(report, "usage-changed")] == ["WS-GRP.WS-A"]
    assert [c.symbol for c in _of_kind(report, "level-changed")] == ["WS-GRP.WS-A"]
    assert [c.symbol for c in _of_kind(report, "value-changed")] == ["WS-GRP.WS-A"]


def test_occurs_changed():
    report = _data_diff(
        "       WORKING-STORAGE SECTION.\n"
        "       01  WS-TAB.\n"
        "           05  WS-ENT OCCURS 5 TIMES PIC 9(3).\n",
        "       WORKING-STORAGE SECTION.\n"
        "       01  WS-TAB.\n"
        "           05  WS-ENT OCCURS 10 TIMES PIC 9(3).\n",
    )

    changes = _of_kind(report, "occurs-changed")
    assert len(changes) == 1
    assert changes[0].old == "5..5"
    assert changes[0].new == "10..10"


def test_redefines_retargeted():
    report = _data_diff(
        "       WORKING-STORAGE SECTION.\n"
        "       01  WS-A PIC X(10).\n"
        "       01  WS-B PIC X(10).\n"
        "       01  WS-C REDEFINES WS-A PIC 9(10).\n",
        "       WORKING-STORAGE SECTION.\n"
        "       01  WS-A PIC X(10).\n"
        "       01  WS-B PIC X(10).\n"
        "       01  WS-C REDEFINES WS-B PIC 9(10).\n",
    )

    changes = _of_kind(report, "redefines-changed")
    assert len(changes) == 1
    assert changes[0].old == "WS-A"
    assert changes[0].new == "WS-B"


def test_data_item_added_and_removed():
    report = _data_diff(
        "       WORKING-STORAGE SECTION.\n       01  WS-A PIC X(5).\n",
        "       WORKING-STORAGE SECTION.\n"
        "       01  WS-A PIC X(5).\n"
        "       01  WS-NEW PIC 9(4).\n",
    )
    assert [c.symbol for c in _of_kind(report, "data-item-added")] == ["WS-NEW"]

    reverse = _data_diff(
        "       WORKING-STORAGE SECTION.\n"
        "       01  WS-A PIC X(5).\n"
        "       01  WS-NEW PIC 9(4).\n",
        "       WORKING-STORAGE SECTION.\n       01  WS-A PIC X(5).\n",
    )
    assert [c.symbol for c in _of_kind(reverse, "data-item-removed")] == ["WS-NEW"]


def test_level_88_condition_names_are_compared():
    report = _data_diff(
        "       WORKING-STORAGE SECTION.\n"
        "       01  WS-FLAG PIC X.\n"
        "           88  WS-FLAG-ON  VALUE 'Y'.\n",
        "       WORKING-STORAGE SECTION.\n"
        "       01  WS-FLAG PIC X.\n"
        "           88  WS-FLAG-ON  VALUE 'T'.\n"
        "           88  WS-FLAG-OFF VALUE 'N'.\n",
    )

    changed = _of_kind(report, "condition-value-changed")
    assert [c.symbol for c in changed] == ["WS-FLAG.WS-FLAG-ON"]
    assert [c.symbol for c in _of_kind(report, "condition-name-added")] == [
        "WS-FLAG.WS-FLAG-OFF"
    ]


def test_data_section_added_and_removed():
    report = _data_diff(
        "       WORKING-STORAGE SECTION.\n       01  WS-A PIC X(5).\n",
        "       WORKING-STORAGE SECTION.\n"
        "       01  WS-A PIC X(5).\n"
        "       LINKAGE SECTION.\n"
        "       01  L-A PIC X(5).\n",
    )

    assert [c.symbol for c in _of_kind(report, "data-section-added")] == [
        "LINKAGE SECTION"
    ]
    reverse = _data_diff(
        "       WORKING-STORAGE SECTION.\n"
        "       01  WS-A PIC X(5).\n"
        "       LINKAGE SECTION.\n"
        "       01  L-A PIC X(5).\n",
        "       WORKING-STORAGE SECTION.\n       01  WS-A PIC X(5).\n",
    )
    assert [c.symbol for c in _of_kind(reverse, "data-section-removed")] == [
        "LINKAGE SECTION"
    ]


def test_same_name_in_two_sections_is_not_confused():
    """The key is section-qualified, so LINKAGE:WS-A is not WORKING-STORAGE:WS-A."""
    report = _data_diff(
        "       WORKING-STORAGE SECTION.\n       01  SHARED-NAME PIC X(5).\n",
        "       LINKAGE SECTION.\n       01  SHARED-NAME PIC X(5).\n",
    )

    assert [c.symbol for c in _of_kind(report, "data-item-added")] == ["SHARED-NAME"]
    assert [c.symbol for c in _of_kind(report, "data-item-removed")] == ["SHARED-NAME"]
    assert _of_kind(report, "picture-changed") == []


def test_sign_and_flag_clause_changes_are_not_silently_ignored():
    report = _data_diff(
        "       WORKING-STORAGE SECTION.\n"
        "       01  WS-A PIC S9(5) SIGN IS LEADING.\n",
        "       WORKING-STORAGE SECTION.\n"
        "       01  WS-A PIC S9(5) SIGN IS TRAILING SEPARATE CHARACTER.\n",
    )

    assert len(_of_kind(report, "sign-changed")) == 1


# ---------------------------------------------------------------------------
# Files (SELECT / FD)
# ---------------------------------------------------------------------------


_FILE_TEMPLATE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. FILEPROG.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
{selects}\
       DATA DIVISION.
       FILE SECTION.
{fds}\
       PROCEDURE DIVISION.
       MAIN-PARA.
           STOP RUN.
"""

_CUST_SELECT = """\
           SELECT CUST-FILE ASSIGN TO 'CUST.DAT'
               ORGANIZATION IS {org}
               ACCESS MODE IS {access}
               RECORD KEY IS {key}.
"""

_CUST_FD = """\
       FD  CUST-FILE.
       01  CUST-REC.
           05  CUST-ID   PIC X(6).
           05  CUST-ALT  PIC X(6).
"""


def _file_program(
    org: str = "INDEXED",
    access: str = "DYNAMIC",
    key: str = "CUST-ID",
    selects: str | None = None,
    fds: str = _CUST_FD,
) -> str:
    return _FILE_TEMPLATE.format(
        selects=(
            selects
            if selects is not None
            else _CUST_SELECT.format(org=org, access=access, key=key)
        ),
        fds=fds,
    )


def test_file_organization_access_and_key_changed():
    report = _diff(
        _file_program(),
        _file_program(org="SEQUENTIAL", access="SEQUENTIAL", key="CUST-ALT"),
    )

    assert [c.old for c in _of_kind(report, "file-organization-changed")] == ["INDEXED"]
    assert [c.new for c in _of_kind(report, "file-access-changed")] == ["SEQUENTIAL"]
    key_changes = _of_kind(report, "file-key-changed")
    assert [(c.old, c.new) for c in key_changes] == [("CUST-ID", "CUST-ALT")]
    assert all(
        change.category == "file"
        for change in report.changes
        if change.kind.startswith("file-")
    )


def test_file_added_and_removed():
    two_files = (
        _CUST_SELECT.format(org="INDEXED", access="DYNAMIC", key="CUST-ID")
        + "           SELECT LOG-FILE ASSIGN TO 'LOG.DAT'\n"
        "               ORGANIZATION IS SEQUENTIAL.\n"
    )
    old = _file_program()
    new = _file_program(selects=two_files)

    report = _diff(old, new)
    assert [c.symbol for c in _of_kind(report, "file-added")] == ["LOG-FILE"]

    reverse = _diff(new, old)
    assert [c.symbol for c in _of_kind(reverse, "file-removed")] == ["LOG-FILE"]


def test_fd_added_and_removed():
    report = _diff(_file_program(fds=""), _file_program())
    assert [c.symbol for c in _of_kind(report, "fd-added")] == ["CUST-FILE"]

    reverse = _diff(_file_program(), _file_program(fds=""))
    assert [c.symbol for c in _of_kind(reverse, "fd-removed")] == ["CUST-FILE"]


def test_fd_record_clause_changed():
    with_record = """\
       FD  CUST-FILE
           RECORD CONTAINS 80 CHARACTERS.
       01  CUST-REC.
           05  CUST-ID   PIC X(6).
"""
    other_record = """\
       FD  CUST-FILE
           RECORD CONTAINS 120 CHARACTERS.
       01  CUST-REC.
           05  CUST-ID   PIC X(6).
"""
    report = _diff(_file_program(fds=with_record), _file_program(fds=other_record))

    changes = _of_kind(report, "fd-record-changed")
    assert len(changes) == 1
    assert "80" in (changes[0].old or "")
    assert "120" in (changes[0].new or "")


def test_file_status_and_assign_changes():
    old_select = """\
           SELECT CUST-FILE ASSIGN TO 'CUST.DAT'
               ORGANIZATION IS SEQUENTIAL
               FILE STATUS IS WS-STAT-A.
"""
    new_select = """\
           SELECT CUST-FILE ASSIGN TO 'CUST2.DAT'
               ORGANIZATION IS SEQUENTIAL
               FILE STATUS IS WS-STAT-B.
"""
    report = _diff(_file_program(selects=old_select), _file_program(selects=new_select))

    assert len(_of_kind(report, "file-status-changed")) == 1
    assert len(_of_kind(report, "file-assign-changed")) == 1


# ---------------------------------------------------------------------------
# Report shape, rendering and caveats
# ---------------------------------------------------------------------------


def test_to_dict_shape_and_keys():
    old = _program("       MAIN-PARA.\n           STOP RUN.\n", program_id="A1")
    new = _program(
        "       MAIN-PARA.\n           STOP RUN.\n"
        "       ADDED-PARA.\n           MOVE 1 TO WS-A.\n",
        data=_WS,
        program_id="A2",
    )
    payload = _diff(old, new).to_dict()

    assert set(payload) == {
        "old_program",
        "new_program",
        "changes",
        "caveats",
        "summary",
    }
    assert payload["old_program"] == "A1"
    assert payload["new_program"] == "A2"
    assert set(payload["summary"]) == {"total_changes", "by_category", "by_kind"}
    assert payload["summary"]["total_changes"] == len(payload["changes"])
    assert sum(payload["summary"]["by_category"].values()) == len(payload["changes"])
    assert sum(payload["summary"]["by_kind"].values()) == len(payload["changes"])

    change = payload["changes"][0]
    assert set(change) == {
        "kind",
        "category",
        "symbol",
        "detail",
        "old",
        "new",
        "old_location",
        "new_location",
    }


def test_change_to_dict_serializes_locations():
    change = DiffChange(
        kind="paragraph-added",
        category="procedure",
        symbol="X",
        detail="x added",
        new_location=SourceLocation(4, 8),
    )
    payload = change.to_dict()

    assert payload["old_location"] is None
    assert payload["new_location"]["line"] == 4
    assert change.sign == "+"


def test_change_sign_for_each_shape():
    def sign(kind: str) -> str:
        return DiffChange(kind=kind, category="data", symbol="S", detail="d").sign

    assert sign("data-item-added") == "+"
    assert sign("data-item-removed") == "-"
    assert sign("picture-changed") == "~"


def test_changes_by_category_and_counts_by_kind_are_sorted():
    old = _program("       MAIN-PARA.\n           STOP RUN.\n", program_id="A1")
    new = _program(
        "       MAIN-PARA.\n           STOP RUN.\n"
        "       ADDED-PARA.\n           MOVE 1 TO WS-A.\n",
        data=_WS,
        program_id="A2",
    )
    report = _diff(old, new)

    grouped = report.changes_by_category()
    assert list(grouped) == sorted(grouped)
    assert sum(len(items) for items in grouped.values()) == report.change_count

    counts = report.counts_by_kind()
    assert list(counts) == sorted(counts)
    assert sum(counts.values()) == report.change_count


def test_to_text_renders_a_readable_summary():
    old = _program(
        "       MAIN-PARA.\n           MOVE 1 TO WS-A\n           STOP RUN.\n",
        data=_WS,
        program_id="A1",
    )
    new = _program(
        "       MAIN-PARA.\n           MOVE 2 TO WS-A\n           STOP RUN.\n",
        data=_WS,
        program_id="A2",
    )
    text = _diff(old, new).to_text()

    assert text.startswith("PROGRAM A1 -> A2")
    assert "procedure:" in text
    assert "[program-id-changed]" in text
    assert "caveats:" in text


def test_to_text_for_an_unchanged_pair():
    source = _program("       MAIN-PARA.\n           STOP RUN.\n")
    text = _diff(source, source).to_text()

    assert "No structural changes." in text


def test_to_text_singular_change_wording():
    old = _program("       MAIN-PARA.\n           STOP RUN.\n", program_id="A1")
    new = _program("       MAIN-PARA.\n           STOP RUN.\n", program_id="A2")
    text = _diff(old, new).to_text()

    assert "1 change\n" in text


def test_caveats_are_deduplicated_and_sorted():
    source = _program("       MAIN-PARA.\n           STOP RUN.\n", data=_WS)
    report = _diff(source, source)

    assert report.caveats == sorted(set(report.caveats))
    assert any("IDENTIFICATION DIVISION" in caveat for caveat in report.caveats)


def test_contained_program_units_are_caveated_not_silently_ignored():
    source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. OUTERP.
       PROCEDURE DIVISION.
       MAIN-PARA.
           STOP RUN.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. INNERP.
       PROCEDURE DIVISION.
       INNER-PARA.
           GOBACK.
       END PROGRAM INNERP.
       END PROGRAM OUTERP.
"""
    ast = _parse(source)
    assert ast.contained_programs, "expected a contained program unit"

    report = ProgramDiffer().diff(ast, ast)
    assert any(
        "only the outermost unit is compared" in caveat for caveat in report.caveats
    )
    assert report.changes == []


def test_duplicate_procedure_name_is_caveated():
    source = _program(
        "       MAIN-PARA.\n           STOP RUN.\n"
        "       DUP-PARA.\n           MOVE 1 TO WS-A.\n"
        "       DUP-PARA.\n           MOVE 2 TO WS-A.\n",
        data=_WS,
    )
    report = _diff(source, source)

    assert any("more than once" in caveat for caveat in report.caveats)


def test_undecomposed_nested_statement_is_caveated():
    """A statement nesting shape the flattener does not know must be visible."""
    loc = SourceLocation(1, 1)

    def build() -> CobolProgram:
        program = CobolProgram("NESTP", loc)
        division = CobolDivision("PROCEDURE", loc)
        paragraph = CobolParagraph("MAIN-PARA", SourceLocation(10, 8))
        outer = CobolStatement("MYSTERY", SourceLocation(11, 12))
        inner = CobolStatement("HIDDEN", SourceLocation(12, 16))
        outer.add_child(inner)
        paragraph.add_statement(outer)
        division.add_paragraph(paragraph)
        program.add_division(division)
        return program

    report = ProgramDiffer().diff(build(), build())

    assert any("is not decomposed by this diff" in c for c in report.caveats)
    assert any("HIDDEN" in c for c in report.caveats)
    assert report.changes == []


def test_report_defaults_are_empty():
    report = DiffReport()

    assert report.changes == []
    assert report.caveats == []
    assert report.change_count == 0
    assert report.has_changes is False
    assert report.changes_by_category() == {}
    assert report.counts_by_kind() == {}
    assert report.to_dict()["summary"]["total_changes"] == 0
    assert "(unnamed)" in report.to_text()


def test_program_without_a_procedure_division_diffs_cleanly():
    old = (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. NOPROC.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01  WS-A PIC X(5).\n"
    )
    new = (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. NOPROC.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01  WS-A PIC X(9).\n"
    )
    report = _diff(old, new)

    assert [c.kind for c in report.changes] == ["picture-changed"]


def test_hand_built_program_with_a_section_and_no_data_division():
    """A section rename also reparents the paragraphs it owns."""
    loc = SourceLocation(1, 1)

    def build(section_name: str) -> CobolProgram:
        program = CobolProgram("SECTP", loc)
        division = CobolDivision("PROCEDURE", loc)
        section = CobolSection(section_name, SourceLocation(10, 8))
        paragraph = CobolParagraph("WORK-PARA", SourceLocation(11, 8))
        paragraph.add_statement(CobolStatement("CONTINUE", SourceLocation(12, 12)))
        section.add_paragraph(paragraph)
        division.add_section(section)
        program.add_division(division)
        return program

    report = ProgramDiffer().diff(build("A-SECT"), build("B-SECT"))

    assert sorted(_kinds(report)) == ["paragraph-moved", "section-renamed"]
    moved = _of_kind(report, "paragraph-moved")[0]
    assert moved.old == "position 2 of section A-SECT"
    assert moved.new == "position 2 of section B-SECT"


# ---------------------------------------------------------------------------
# Nested clause shapes
# ---------------------------------------------------------------------------


_SEARCH_PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SEARCHP.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A PIC 9(3).
       01  WS-TAB.
           05  WS-ENT OCCURS 5 TIMES INDEXED BY WS-IDX.
               10  WS-K PIC X(3).
       PROCEDURE DIVISION.
       MAIN-PARA.
           SEARCH WS-ENT
               AT END DISPLAY '{at_end}'
               WHEN WS-K = '{when}'
                   MOVE 1 TO WS-A
           END-SEARCH
           STOP RUN.
"""


def test_search_when_condition_change_is_tagged_with_its_arm():
    report = _diff(
        _SEARCH_PROGRAM.format(at_end="NONE", when="AAA"),
        _SEARCH_PROGRAM.format(at_end="NONE", when="BBB"),
    )

    changes = _of_kind(report, "condition-changed")
    assert len(changes) == 1
    assert "SEARCH/WHEN1" in changes[0].detail


def test_search_at_end_body_change_is_tagged_with_its_arm():
    report = _diff(
        _SEARCH_PROGRAM.format(at_end="NONE", when="AAA"),
        _SEARCH_PROGRAM.format(at_end="EMPTY", when="AAA"),
    )

    changes = _of_kind(report, "statement-changed")
    assert len(changes) == 1
    assert "AT-END" in changes[0].detail


_READ_PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. READP.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-FILE ASSIGN TO 'IN.DAT'.
       DATA DIVISION.
       FILE SECTION.
       FD  IN-FILE.
       01  IN-REC PIC X(80).
       WORKING-STORAGE SECTION.
       01  WS-EOF PIC X VALUE 'N'.
       PROCEDURE DIVISION.
       MAIN-PARA.
           READ IN-FILE
               AT END MOVE '{value}' TO WS-EOF
           END-READ
           STOP RUN.
"""


def test_read_at_end_handler_change_is_tagged_with_its_clause():
    report = _diff(_READ_PROGRAM.format(value="Y"), _READ_PROGRAM.format(value="Z"))

    changes = _of_kind(report, "move-source-changed")
    assert len(changes) == 1
    assert "AT-END" in changes[0].detail


def test_inline_perform_until_condition_shows_both_conditions():
    template = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. VARYP.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-I PIC 9(3).
       01  WS-A PIC 9(3).
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM VARYING WS-I FROM 1 BY 1 UNTIL WS-I > {limit}
               ADD 1 TO WS-A
           END-PERFORM
           STOP RUN.
"""
    report = _diff(template.format(limit="5"), template.format(limit="9"))

    changes = _of_kind(report, "condition-changed")
    assert len(changes) == 1
    assert changes[0].old != changes[0].new
    assert "5" in (changes[0].old or "")
    assert "9" in (changes[0].new or "")


def test_evaluate_subject_change():
    template = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. EVALP.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A PIC 9(3).
       01  WS-B PIC 9(3).
       01  WS-C PIC 9(3).
       PROCEDURE DIVISION.
       MAIN-PARA.
           EVALUATE {subject}
               WHEN 1
                   MOVE 1 TO WS-C
               WHEN OTHER
                   MOVE 2 TO WS-C
           END-EVALUATE
           STOP RUN.
"""
    report = _diff(template.format(subject="WS-A"), template.format(subject="WS-B"))

    changes = _of_kind(report, "condition-changed")
    assert len(changes) == 1
    assert "EVALUATE" in changes[0].detail


def test_evaluate_when_other_body_change():
    template = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. EVALP.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A PIC 9(3).
       01  WS-C PIC 9(3).
       PROCEDURE DIVISION.
       MAIN-PARA.
           EVALUATE WS-A
               WHEN 1
                   MOVE 1 TO WS-C
               WHEN OTHER
                   MOVE {value} TO WS-C
           END-EVALUATE
           STOP RUN.
"""
    report = _diff(template.format(value="2"), template.format(value="3"))

    changes = _of_kind(report, "move-source-changed")
    assert len(changes) == 1
    assert "WHEN-OTHER" in changes[0].detail


# ---------------------------------------------------------------------------
# More data-item shapes
# ---------------------------------------------------------------------------


def test_occurs_depending_on_indexed_by_and_key_changes():
    template = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ODOP.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-CNT PIC 9(3).
       01  WS-CNT2 PIC 9(3).
       01  WS-TAB.
           05  WS-ENT OCCURS 1 TO 10 TIMES DEPENDING ON {counter}
                   INDEXED BY {index}
                   ASCENDING KEY IS WS-K.
               10  WS-K PIC X(3).
       PROCEDURE DIVISION.
       MAIN-PARA.
           STOP RUN.
"""
    report = _diff(
        template.format(counter="WS-CNT", index="WS-IDX"),
        template.format(counter="WS-CNT2", index="WS-IDX2"),
    )

    changes = _of_kind(report, "occurs-changed")
    assert len(changes) == 1
    assert "DEPENDING ON WS-CNT" in (changes[0].old or "")
    assert "INDEXED BY WS-IDX2" in (changes[0].new or "")
    assert "ASCENDING" in (changes[0].new or "")


def test_repeated_filler_entries_are_keyed_by_position_with_a_caveat():
    template = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. FILLP.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-GRP.
           05  FILLER PIC X(3) VALUE 'AAA'.
           05  FILLER PIC X(3) VALUE '{value}'.
       PROCEDURE DIVISION.
       MAIN-PARA.
           STOP RUN.
"""
    report = _diff(template.format(value="BBB"), template.format(value="CCC"))

    changes = _of_kind(report, "value-changed")
    assert len(changes) == 1
    assert changes[0].symbol == "WS-GRP.FILLER#2"
    assert any("FILLER entries" in caveat for caveat in report.caveats)


def test_unnamed_entries_are_implicit_fillers_not_keyed_by_line():
    # `05 PIC X(3).` has no data-name; the parser's synthetic name carries
    # its line number, which must not make a line shift read as a change.
    template = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ANONP.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
{extra}       01  WS-GRP.
           05  PIC X(3) VALUE 'AAA'.
           05  PIC X(3) VALUE '{value}'.
       PROCEDURE DIVISION.
       MAIN-PARA.
           STOP RUN.
"""
    old = template.format(extra="", value="BBB")
    shifted = template.format(extra="       01  WS-NEW PIC X.\n", value="BBB")
    report = _diff(old, shifted)
    assert [c.symbol for c in report.changes] == ["WS-NEW"]

    report = _diff(old, template.format(extra="", value="CCC"))
    changes = _of_kind(report, "value-changed")
    assert [c.symbol for c in changes] == ["WS-GRP.FILLER#2"]


def test_level_66_renames_entries_are_caveated():
    loc = SourceLocation(1, 1)

    def build() -> CobolProgram:
        program = CobolProgram("RENP", loc)
        division = CobolDivision("DATA", loc)
        section = CobolSection("WORKING-STORAGE", SourceLocation(5, 8))
        section.add_child(RenamesItem("WS-REN", "WS-X", "WS-Y", SourceLocation(8, 8)))
        division.add_section(section)
        program.add_division(division)
        return program

    report = ProgramDiffer().diff(build(), build())

    assert any("RENAMES" in caveat for caveat in report.caveats)
    assert report.changes == []


# ---------------------------------------------------------------------------
# More file shapes
# ---------------------------------------------------------------------------


def test_fd_becoming_an_sd_is_reported():
    template = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SORTP.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT SORT-FILE ASSIGN TO 'SORTWK'.
       DATA DIVISION.
       FILE SECTION.
       {kind}  SORT-FILE.
       01  SORT-REC.
           05  S-KEY PIC X(4).
       PROCEDURE DIVISION.
       MAIN-PARA.
           STOP RUN.
"""
    report = _diff(template.format(kind="FD"), template.format(kind="SD"))

    changes = _of_kind(report, "fd-type-changed")
    assert len(changes) == 1
    assert (changes[0].old, changes[0].new) == ("FD", "SD")


def test_optional_clause_change_renders_as_yes_no():
    template = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. OPTP.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT {optional}IN-FILE ASSIGN TO 'IN.DAT'
               ORGANIZATION IS SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD  IN-FILE.
       01  IN-REC PIC X(80).
       PROCEDURE DIVISION.
       MAIN-PARA.
           STOP RUN.
"""
    report = _diff(template.format(optional=""), template.format(optional="OPTIONAL "))

    changes = _of_kind(report, "file-optional-changed")
    assert len(changes) == 1
    assert (changes[0].old, changes[0].new) == ("no", "yes")


def test_duplicate_select_for_one_file_is_caveated():
    source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. DUPSEL.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-FILE ASSIGN TO 'IN.DAT'
               ORGANIZATION IS SEQUENTIAL.
           SELECT IN-FILE ASSIGN TO 'IN2.DAT'
               ORGANIZATION IS SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD  IN-FILE.
       01  IN-REC PIC X(80).
       PROCEDURE DIVISION.
       MAIN-PARA.
           STOP RUN.
"""
    report = _diff(source, source)

    assert any("more than once" in caveat for caveat in report.caveats)
    assert report.changes == []


def test_select_added_for_a_file_that_only_had_an_fd():
    loc = SourceLocation(1, 1)

    def build(with_select: bool) -> CobolProgram:
        from cobolparser.models.data_items import CobolDataItem
        from cobolparser.models.statements.misc import SelectStatement

        program = CobolProgram("FDONLY", loc)
        data = CobolDivision("DATA", loc)
        file_section = CobolSection("FILE", SourceLocation(5, 8))
        record = CobolDataItem("IN-REC", 1, SourceLocation(6, 8))
        record.set_metadata("fd_file_name", "IN-FILE")
        record.set_metadata("fd_clauses", {})
        record.set_metadata("fd_record_type", "FD")
        file_section.add_data_item(record)
        data.add_section(file_section)
        program.add_division(data)

        if with_select:
            environment = CobolDivision("ENVIRONMENT", loc)
            select = SelectStatement(SourceLocation(3, 12))
            select.set_file_name("IN-FILE")
            environment.add_child(select)
            program.add_division(environment)
        return program

    added = ProgramDiffer().diff(build(False), build(True))
    assert [c.kind for c in _of_kind(added, "file-select-added")] == [
        "file-select-added"
    ]

    removed = ProgramDiffer().diff(build(True), build(False))
    assert [c.kind for c in _of_kind(removed, "file-select-removed")] == [
        "file-select-removed"
    ]


def test_evaluate_range_selector_change():
    template = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. RANGEP.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A PIC 9(3).
       01  WS-C PIC 9(3).
       PROCEDURE DIVISION.
       MAIN-PARA.
           EVALUATE WS-A
               WHEN 1 THRU {end}
                   MOVE 1 TO WS-C
               WHEN WS-A > 50
                   MOVE 2 TO WS-C
           END-EVALUATE
           STOP RUN.
"""
    report = _diff(template.format(end="5"), template.format(end="7"))

    changes = _of_kind(report, "condition-changed")
    assert len(changes) == 1
    assert "RANGE:1..5" in (changes[0].old or "")
    assert "RANGE:1..7" in (changes[0].new or "")


_ALT_KEY_PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ALTP.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT CUST-FILE ASSIGN TO 'C.DAT'
               ORGANIZATION IS INDEXED
               ACCESS MODE IS DYNAMIC
               RECORD KEY IS CUST-ID
               ALTERNATE RECORD KEY IS {alt} WITH DUPLICATES.
       DATA DIVISION.
       FILE SECTION.
       FD  CUST-FILE
           RECORDING MODE IS {mode}.
       01  CUST-REC.
           05  CUST-ID PIC X(6).
           05  CUST-A  PIC X(6).
           05  CUST-B  PIC X(6).
       PROCEDURE DIVISION.
       MAIN-PARA.
           STOP RUN.
"""


def test_alternate_key_and_recording_mode_changes():
    report = _diff(
        _ALT_KEY_PROGRAM.format(alt="CUST-A", mode="F"),
        _ALT_KEY_PROGRAM.format(alt="CUST-B", mode="V"),
    )

    alt = _of_kind(report, "file-alternate-keys-changed")
    assert len(alt) == 1
    assert "CUST-A" in (alt[0].old or "")
    assert "CUST-B" in (alt[0].new or "")

    mode = _of_kind(report, "fd-recording-mode-changed")
    assert [(c.old, c.new) for c in mode] == [("F", "V")]


def test_report_section_clauses_are_caveated_not_silently_compared():
    template = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. RPTP.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT RPT-FILE ASSIGN TO 'R.DAT'.
       DATA DIVISION.
       FILE SECTION.
       FD  RPT-FILE
           REPORT IS SALES-REPORT.
       REPORT SECTION.
       RD  SALES-REPORT
           PAGE LIMIT IS 60 LINES.
       01  DETAIL-LINE TYPE IS DETAIL.
           05  LINE NUMBER IS PLUS 1.
               10  COLUMN NUMBER IS {column} PIC X(10) SOURCE WS-A.
       WORKING-STORAGE SECTION.
       01  WS-A PIC X(10).
       PROCEDURE DIVISION.
       MAIN-PARA.
           STOP RUN.
"""
    report = _diff(template.format(column="5"), template.format(column="9"))

    assert any("REPORT SECTION group clauses" in c for c in report.caveats)
    # The COLUMN change itself is not modelled -- the caveat is what keeps the
    # empty change list from reading as "nothing changed".
    assert report.changes == []


def test_third_repeated_filler_gets_its_own_positional_key():
    template = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. FILL3P.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-GRP.
           05  FILLER PIC X(3) VALUE 'AAA'.
           05  FILLER PIC X(3) VALUE 'BBB'.
           05  FILLER PIC X(3) VALUE '{value}'.
       PROCEDURE DIVISION.
       MAIN-PARA.
           STOP RUN.
"""
    report = _diff(template.format(value="CCC"), template.format(value="DDD"))

    changes = _of_kind(report, "value-changed")
    assert [c.symbol for c in changes] == ["WS-GRP.FILLER#3"]


# ---------------------------------------------------------------------------
# Review follow-ups (PR #212)
# ---------------------------------------------------------------------------


def test_statements_without_a_dedicated_signature_still_report_an_edit():
    """A COMPUTE's expression, an OPEN's mode and an EXEC SQL's text live off
    ``operands``; the fallback signature must not read them as unchanged."""
    old = _program(
        "       MAIN.\n"
        "           COMPUTE WS-N = WS-M + 1\n"
        "           OPEN INPUT F1\n"
        "           EXEC SQL SELECT A INTO :WS-N FROM T END-EXEC\n"
        "           STOP RUN.\n",
        data=(
            "       WORKING-STORAGE SECTION.\n"
            "       01 WS-N PIC 9(4).\n"
            "       01 WS-M PIC 9(4).\n"
        ),
    )
    new = (
        old.replace("WS-M + 1", "WS-M * 2")
        .replace("OPEN INPUT F1", "OPEN OUTPUT F1")
        .replace("SELECT A INTO", "SELECT B INTO")
    )
    report = _diff(old, new)
    assert len(report.changes) >= 3, [c.to_dict() for c in report.changes]
