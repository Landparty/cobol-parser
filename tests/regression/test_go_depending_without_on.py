"""``GO TO a b DEPENDING ws-x`` with the optional ON omitted (issue #377).

The variable used to be left in the stream: it was re-parsed as a phantom
paragraph and the jump table read as an unconditional GO TO its first
target, so every analyzer downstream got the statement wrong.
"""

import pytest

from cobolparser import (
    ComplexityAnalyzer,
    DeadCodeAnalyzer,
    ErrorRecoveryMode,
    ProgramFlowAnalyzer,
    UnusedVariableAnalyzer,
    parse_cobol,
)

SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. GODEP.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-D PIC 9 VALUE 1.
       PROCEDURE DIVISION.
       P-0.       GO TO P-B P-C DEPENDING WS-D.
       P-INVALID. DISPLAY 'OUT OF RANGE' STOP RUN.
       P-B. DISPLAY 'B' STOP RUN.
       P-C. DISPLAY 'C' STOP RUN.
"""


@pytest.fixture(scope="module")
def result():
    return parse_cobol(SOURCE, error_recovery=ErrorRecoveryMode.FAIL_FAST)


def test_parses_cleanly_with_variable(result):
    assert result.success, result.errors
    assert not any("Unparsed" in w for w in result.warnings)
    gos = result.ast.find_all_by_type("GoStatement")
    assert len(gos) == 1
    go = gos[0]
    assert go.depending_on_variable == "WS-D"
    assert go.target_paragraphs == ["P-B", "P-C"]


def test_no_phantom_paragraph(result):
    names = [p.paragraph_name for p in result.ast.find_all_by_type("CobolParagraph")]
    assert "WS-D" not in names


def test_dead_code_keeps_fall_through_paragraph(result):
    dead = [d.name for d in DeadCodeAnalyzer().analyze(result.ast).dead_items]
    assert "WS-D" not in dead
    assert "P-INVALID" not in dead


def test_program_flow_reaches_every_target(result):
    report = ProgramFlowAnalyzer().analyze(result.ast)
    assert "P-C" not in report.unreachable_nodes


def test_variable_counts_as_used(result):
    unused = [u.name for u in UnusedVariableAnalyzer().analyze(result.ast).unused_items]
    assert "WS-D" not in unused


def test_complexity_counts_the_jump_table(result):
    procs = {p.name: p for p in ComplexityAnalyzer().analyze(result.ast).procedures}
    assert procs["P-0"].cyclomatic_complexity > 1
