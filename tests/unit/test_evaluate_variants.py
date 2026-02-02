import pytest

from cobolparser import CobolParser
from cobolparser.models.program import CobolProgram
from cobolparser.models.statements import CobolStatement
from cobolparser.models.statements import PerformStatement
from cobolparser import ParseResult
from cobolparser.models.statements import EvaluateStatement


def _fixed_source(body: str) -> str:
    lines = [line.rstrip() for line in body.strip().splitlines()]
    return "\n".join(f"       {line}" for line in lines) + "\n"


def _parse_and_get_program(source: str) -> CobolProgram:
    parser = CobolParser()
    result: ParseResult = parser.parse(source)
    assert result.ast is not None, "Parse did not produce AST"
    return result.ast


def _first_evaluate(program: CobolProgram):
    proc = program.get_division("PROCEDURE")
    assert proc is not None, "Procedure division missing"
    
    # Search in direct paragraphs (new architecture)
    for paragraph in proc.paragraphs:
        for stmt in paragraph.statements:
            if isinstance(stmt, EvaluateStatement):
                return stmt
    
    # Search in sections -> paragraphs -> statements (current architecture)
    for section in proc.sections:
        for paragraph in section.paragraphs:
            for stmt in paragraph.statements:
                if isinstance(stmt, EvaluateStatement):
                    return stmt
    
    # Fallback: search all children (legacy)
    for section in proc.sections:
        for child in section.children:
            if isinstance(child, EvaluateStatement):
                return child
    
    raise AssertionError("No EVALUATE statement found")


def test_single_subject_literals_and_ranges():
    source = """
    IDENTIFICATION DIVISION.
    PROGRAM-ID. TEST.
    DATA DIVISION.
    WORKING-STORAGE SECTION.
    01  WS-GRADE PIC 9.
    PROCEDURE DIVISION.
        EVALUATE WS-GRADE
            WHEN 1
                DISPLAY 'ONE'
            WHEN 2 THRU 3
                DISPLAY 'LOW'
            WHEN OTHER
                DISPLAY 'OTHER'
        END-EVALUATE.
    """
    program = _parse_and_get_program(_fixed_source(source))
    ev = _first_evaluate(program)
    assert ev.statement_type == "EVALUATE"
    subjects = [s for s in ev.subjects]
    assert subjects == ["WS-GRADE"]
    assert len(ev.when_clauses) == 2
    selectors_first = ev.when_clauses[0].selectors
    assert selectors_first[0]["type"] in {"Literal", "Identifier"}
    assert selectors_first[0].get("value") == "1"
    selectors_second = ev.when_clauses[1].selectors
    assert selectors_second[0]["type"] == "Range"
    assert selectors_second[0]["start"] == "2"
    assert selectors_second[0]["end"] == "3"
    assert ev.default_when is not None


def test_multiple_subjects_any_and_also():
    source = """
    IDENTIFICATION DIVISION.
    PROGRAM-ID. TEST.
    DATA DIVISION.
    WORKING-STORAGE SECTION.
    01  WS-GRADE PIC 9.
    01  WS-STATUS PIC X.
    PROCEDURE DIVISION.
        EVALUATE WS-GRADE ALSO WS-STATUS
            WHEN 1 ALSO 'A'
                DISPLAY 'ALPHA'
            WHEN ANY ALSO 'Z'
                DISPLAY 'ANY-Z'
            WHEN OTHER
                DISPLAY 'FALLBACK'
        END-EVALUATE.
    """
    program = _parse_and_get_program(_fixed_source(source))
    ev = _first_evaluate(program)
    assert len(ev.subjects) == 2
    # WHEN 1 ALSO 'A'
    first_sel = ev.when_clauses[0].selectors
    assert first_sel[0]["value"] == "1"
    assert first_sel[1]["value"] == "'A'" or first_sel[1]["value"] == "A"
    # WHEN ANY ALSO 'Z'
    any_sel = ev.when_clauses[1].selectors
    assert any_sel[0]["type"] == "Any"
    assert any_sel[1]["value"] in {"'Z'", "Z"}
    assert ev.default_when is not None


def test_evaluate_true_with_conditions_and_or():
    source = """
    IDENTIFICATION DIVISION.
    PROGRAM-ID. TEST.
    DATA DIVISION.
    WORKING-STORAGE SECTION.
    01  WS-GRADE PIC 9.
    01  WS-COUNTER PIC 9.
    01  WS-STATUS PIC X.
    PROCEDURE DIVISION.
        EVALUATE TRUE
            WHEN WS-GRADE = 9 AND WS-COUNTER > 5
                DISPLAY 'HIGH'
            WHEN WS-COUNTER <= 5 OR WS-STATUS = 'S'
                DISPLAY 'MED'
            WHEN OTHER
                DISPLAY 'DEFAULT'
        END-EVALUATE.
    """
    program = _parse_and_get_program(_fixed_source(source))
    ev = _first_evaluate(program)
    assert ev.subjects == ["TRUE"]
    first_when = ev.when_clauses[0]
    assert first_when.selectors[0]["type"] == "Condition"
    assert first_when.selectors[0]["operator"] == "AND"
    second_when = ev.when_clauses[1]
    assert second_when.selectors[0]["operator"] == "OR"
    assert ev.default_when is not None
