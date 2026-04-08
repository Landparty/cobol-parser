from cobolparser import parse_cobol
from cobolparser.models.statements import MoveStatement


def get_procedure_statements(proc_div):
    """Get statements from procedure division, handling both architectures."""
    if proc_div.paragraphs:
        return proc_div.paragraphs[0].statements
    elif proc_div.sections:
        return (
            proc_div.sections[0].paragraphs[0].statements
            if proc_div.sections[0].paragraphs
            else []
        )
    return []


def test_move_multiple_targets():
    src = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. MULTI-MOVE.
       PROCEDURE DIVISION.
           MOVE "Hello" TO A B C.
    """
    result = parse_cobol(src)
    assert result.ast is not None
    assert result.ast.procedure_division is not None

    # In simple programs without sections, statements are in paragraphs
    stmts = get_procedure_statements(result.ast.procedure_division)
    assert len(stmts) == 1
    assert isinstance(stmts[0], MoveStatement)
    mv = stmts[0]

    assert mv.source == '"Hello"'
    assert len(mv.targets) == 3
    assert mv.targets == ["A", "B", "C"]


def test_move_corresponding():
    src = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CORR-MOVE.
       PROCEDURE DIVISION.
           MOVE CORR GROUP-1 TO GROUP-2.
           MOVE CORRESPONDING GROUP-3 TO GROUP-4.
    """
    result = parse_cobol(src)
    assert result.ast is not None
    assert result.ast.procedure_division is not None

    stmts = get_procedure_statements(result.ast.procedure_division)
    assert len(stmts) == 2

    mv1 = stmts[0]
    assert mv1.is_corresponding is True
    assert mv1.source == "GROUP-1"
    assert mv1.targets == ["GROUP-2"]

    mv2 = stmts[1]
    assert mv2.is_corresponding is True
    assert mv2.source == "GROUP-3"
    assert mv2.targets == ["GROUP-4"]


def test_move_complex_source():
    src = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. COMPLEX.
       PROCEDURE DIVISION.
           MOVE TABLE(1) TO TARGET.
           MOVE TABLE (1, 2) TO TARGET-2.
    """
    result = parse_cobol(src)
    if result.ast is None:
        print(f"Errors: {result.errors}")
    assert result.ast is not None
    assert result.ast.procedure_division is not None

    stmts = get_procedure_statements(result.ast.procedure_division)

    mv1 = stmts[0]
    # Source might be normalized differently in legacy vs new
    # New parser accumulates tokens: 'TABLE', '(', '1', ')'
    # Note: Whitespace might be stripped or retained depending on lexer
    print(f"MV1 Source: {mv1.source}")
    assert "TABLE" in mv1.source
    assert "1" in mv1.source
