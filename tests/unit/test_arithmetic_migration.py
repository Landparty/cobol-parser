from cobolparser.models.statements import (
    AddStatement,
    ComputeStatement,
    DivideStatement,
    MultiplyStatement,
    SubtractStatement,
)
from cobolparser.parser import CobolParser


def parse_cobol(code):
    parser = CobolParser()
    return parser.parse(code)


def get_procedure_statements(proc_div):
    """Get statements from procedure division, handling both architectures."""
    # First check if paragraphs exist directly (new architecture)
    if proc_div.paragraphs:
        return proc_div.paragraphs[0].statements
    # Otherwise get from first section (old architecture)
    elif proc_div.sections:
        return (
            proc_div.sections[0].paragraphs[0].statements
            if proc_div.sections[0].paragraphs
            else []
        )
    return []


class TestArithmeticMigration:

    def test_add_statement(self):
        src = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST.
       PROCEDURE DIVISION.
           ADD 1 TO A.
           ADD A B TO C.
           ADD A TO B GIVING C.
           ADD A TO B ROUNDED.
        """
        result = parse_cobol(src)
        assert result.errors == []

        stmts = get_procedure_statements(result.ast.procedure_division)
        assert len(stmts) == 4

        assert isinstance(stmts[0], AddStatement)
        assert isinstance(stmts[1], AddStatement)
        assert isinstance(stmts[2], AddStatement)
        assert isinstance(stmts[3], AddStatement)

    def test_subtract_statement(self):
        src = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST.
       PROCEDURE DIVISION.
           SUBTRACT 5 FROM TOTAL.
           SUBTRACT A B FROM C.
        """
        result = parse_cobol(src)
        assert result.errors == []

        stmts = get_procedure_statements(result.ast.procedure_division)
        assert len(stmts) == 2
        assert isinstance(stmts[0], SubtractStatement)
        assert isinstance(stmts[1], SubtractStatement)

    def test_multiply_statement(self):
        src = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST.
       PROCEDURE DIVISION.
           MULTIPLY A BY B.
           MULTIPLY A BY B GIVING C.
        """
        result = parse_cobol(src)
        assert result.errors == []

        stmts = get_procedure_statements(result.ast.procedure_division)
        assert len(stmts) == 2
        assert isinstance(stmts[0], MultiplyStatement)
        assert isinstance(stmts[1], MultiplyStatement)

    def test_divide_statement(self):
        src = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST.
       PROCEDURE DIVISION.
           DIVIDE A INTO B.
           DIVIDE A BY B GIVING C REMAINDER D.
        """
        result = parse_cobol(src)
        assert result.errors == []

        stmts = get_procedure_statements(result.ast.procedure_division)
        assert len(stmts) == 2
        assert isinstance(stmts[0], DivideStatement)
        assert isinstance(stmts[1], DivideStatement)

    def test_compute_statement(self):
        src = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST.
       PROCEDURE DIVISION.
           COMPUTE A = B + C.
           COMPUTE A = (B * C) / D.
           COMPUTE A ROUNDED = B + C.
        """
        result = parse_cobol(src)
        assert result.errors == []

        stmts = get_procedure_statements(result.ast.procedure_division)
        assert len(stmts) == 3
        assert isinstance(stmts[0], ComputeStatement)
        assert "A" in stmts[0].targets

    def test_size_error_clause(self):
        src = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST.
       PROCEDURE DIVISION.
           ADD 1 TO A
               ON SIZE ERROR
                   DISPLAY "Error"
                   MOVE 0 TO A.
        """
        result = parse_cobol(src)
        assert result.errors == []

        stmts = get_procedure_statements(result.ast.procedure_division)
        assert len(stmts) == 1
        stmt = stmts[0]
        assert isinstance(stmt, AddStatement)

        # Check on_size_error
        nested = stmt.on_size_error
        assert nested is not None
        assert len(nested) == 2
        assert nested[0].statement_type == "DISPLAY"
        assert nested[1].statement_type == "MOVE"

    def test_not_on_size_error_clause(self):
        src = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST.
       PROCEDURE DIVISION.
           COMPUTE A = B / C
               NOT ON SIZE ERROR
                   DISPLAY "Success".
        """
        result = parse_cobol(src)
        assert result.errors == []

        stmts = get_procedure_statements(result.ast.procedure_division)
        assert len(stmts) == 1
        stmt = stmts[0]
        assert isinstance(stmt, ComputeStatement)

        # Check not_on_size_error
        nested = stmt.not_on_size_error
        assert nested is not None
        assert len(nested) == 1
        assert nested[0].statement_type == "DISPLAY"
