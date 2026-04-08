from cobolparser import CobolParser
from cobolparser.models.statements import EvaluateStatement


def _fixed_source(body: str) -> str:
    lines = [line.rstrip() for line in body.strip().splitlines()]
    return "\n".join(f"       {line}" for line in lines) + "\n"


def _parse(source: str) -> EvaluateStatement:
    parser = CobolParser()
    result = parser.parse(_fixed_source(source))
    assert result.ast is not None
    proc = result.ast.get_division("PROCEDURE")
    assert proc is not None

    # Check paragraphs first
    for paragraph in proc.paragraphs:
        for stmt in paragraph.statements:
            if isinstance(stmt, EvaluateStatement):
                return stmt

    # Check sections
    for section in proc.sections:
        # Check section statements directly
        for stmt in section.children:
            if isinstance(stmt, EvaluateStatement):
                return stmt
        # Check section paragraphs
        if hasattr(section, "paragraphs"):
            for paragraph in section.paragraphs:
                for stmt in paragraph.statements:
                    if isinstance(stmt, EvaluateStatement):
                        return stmt

    raise ValueError("EVALUATE statement not found in AST")


def test_evaluate_to_dict_structure():
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
            WHEN OTHER
                DISPLAY 'OTHER'
        END-EVALUATE.
    """
    ev = _parse(source)
    data = ev.to_dict()

    assert data["subjects"][0] == "WS-GRADE"
    assert len(data["when_clauses"]) == 1
    assert data["when_clauses"][0]["selectors"][0]["value"] == "1"
    assert data["default_when"] is not None
    assert data["location"]["line"] > 0


if __name__ == "__main__":
    test_evaluate_to_dict_structure()
    print("Test passed!")
