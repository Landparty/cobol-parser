"""Regression tests for INVOKE, ALLOCATE, and FREE statement support.

Before this fix, all three verbs were recognized but had no registered
statement parser -- ``ProcedureDivisionParser`` warned "Unsupported
statement" and discarded their tokens up to the next statement boundary
(see ``UNSUPPORTED_VERBS`` in ``procedure_recovery.py``). All three are real,
valid IBM Enterprise COBOL verbs (INVOKE for Object-Oriented COBOL method
calls; ALLOCATE/FREE for dynamic storage), so a program using them parsed
"successfully" with an incomplete AST -- the statement itself was missing
from ``get_all_statements()`` with only a warning as a trace. This pins the
fix: each verb now produces a populated AST node.
"""

from cobolparser import parse_cobol


class TestInvokeStatement:
    def test_invoke_literal_method_with_returning(self):
        src = """IDENTIFICATION DIVISION.
PROGRAM-ID. T1.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 WS-OBJ PIC X(8).
01 WS-RESULT PIC X(20).
PROCEDURE DIVISION.
MAIN.
    INVOKE WS-OBJ 'getName' RETURNING WS-RESULT.
    STOP RUN.
"""
        result = parse_cobol(src)
        assert result.success
        assert result.errors == []
        assert result.warnings == []
        invokes = result.ast.find_all_by_type("InvokeStatement")
        assert len(invokes) == 1
        stmt = invokes[0]
        assert stmt.object_name == "WS-OBJ"
        assert stmt.method_name == "getName"
        assert stmt.method_is_literal is True
        assert stmt.returning_target == "WS-RESULT"

    def test_invoke_using_with_by_value_and_returning(self):
        src = """IDENTIFICATION DIVISION.
PROGRAM-ID. T2.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 WS-OBJ PIC X(8).
01 WS-RESULT PIC X(20).
PROCEDURE DIVISION.
MAIN.
    INVOKE WS-OBJ "setValue" USING BY VALUE 42 RETURNING WS-RESULT.
    DISPLAY 'after'.
    STOP RUN.
"""
        result = parse_cobol(src)
        assert result.success
        assert result.warnings == []
        stmt = result.ast.find_all_by_type("InvokeStatement")[0]
        assert stmt.method_name == "setValue"
        assert len(stmt.using_parameters) == 1
        assert stmt.using_parameters[0].name == "42"
        assert stmt.using_parameters[0].passing_mode == "VALUE"
        assert stmt.returning_target == "WS-RESULT"
        # A following statement with no separating issue must still parse.
        displays = result.ast.find_all_by_type("DisplayStatement")
        assert len(displays) == 1

    def test_invoke_no_longer_reported_as_unsupported(self):
        src = """IDENTIFICATION DIVISION.
PROGRAM-ID. T3.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 WS-OBJ PIC X(8).
PROCEDURE DIVISION.
MAIN.
    INVOKE WS-OBJ 'run'.
    STOP RUN.
"""
        result = parse_cobol(src)
        assert not any("INVOKE" in w for w in result.warnings)


class TestAllocateStatement:
    def test_allocate_characters_form(self):
        src = """IDENTIFICATION DIVISION.
PROGRAM-ID. T4.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 WS-PTR USAGE POINTER.
01 WS-SIZE PIC 9(4) VALUE 100.
PROCEDURE DIVISION.
MAIN.
    ALLOCATE WS-SIZE CHARACTERS INITIALIZED RETURNING WS-PTR.
    STOP RUN.
"""
        result = parse_cobol(src)
        assert result.success
        assert result.warnings == []
        stmt = result.ast.find_all_by_type("AllocateStatement")[0]
        assert stmt.is_characters is True
        assert stmt.size_expr == "WS-SIZE"
        assert stmt.data_item is None
        assert stmt.initialized is True
        assert stmt.returning_target == "WS-PTR"

    def test_allocate_based_data_item_form(self):
        src = """IDENTIFICATION DIVISION.
PROGRAM-ID. T5.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 WS-PTR USAGE POINTER.
01 REC-AREA PIC X(50) BASED.
PROCEDURE DIVISION.
MAIN.
    ALLOCATE REC-AREA RETURNING WS-PTR.
    STOP RUN.
"""
        result = parse_cobol(src)
        assert result.success
        assert result.warnings == []
        stmt = result.ast.find_all_by_type("AllocateStatement")[0]
        assert stmt.is_characters is False
        assert stmt.data_item == "REC-AREA"
        assert stmt.initialized is False
        assert stmt.returning_target == "WS-PTR"

    def test_allocate_no_longer_reported_as_unsupported(self):
        src = """IDENTIFICATION DIVISION.
PROGRAM-ID. T6.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 WS-PTR USAGE POINTER.
01 REC-AREA PIC X(10) BASED.
PROCEDURE DIVISION.
MAIN.
    ALLOCATE REC-AREA RETURNING WS-PTR.
    STOP RUN.
"""
        result = parse_cobol(src)
        assert not any("ALLOCATE" in w for w in result.warnings)


class TestFreeStatement:
    def test_free_single_pointer(self):
        src = """IDENTIFICATION DIVISION.
PROGRAM-ID. T7.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 WS-PTR USAGE POINTER.
PROCEDURE DIVISION.
MAIN.
    FREE WS-PTR.
    STOP RUN.
"""
        result = parse_cobol(src)
        assert result.success
        assert result.warnings == []
        stmt = result.ast.find_all_by_type("FreeStatement")[0]
        assert stmt.pointer_names == ["WS-PTR"]

    def test_free_multiple_pointers(self):
        src = """IDENTIFICATION DIVISION.
PROGRAM-ID. T8.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 WS-PTR-A USAGE POINTER.
01 WS-PTR-B USAGE POINTER.
PROCEDURE DIVISION.
MAIN.
    FREE WS-PTR-A WS-PTR-B.
    DISPLAY 'after'.
    STOP RUN.
"""
        result = parse_cobol(src)
        assert result.success
        assert result.warnings == []
        stmt = result.ast.find_all_by_type("FreeStatement")[0]
        assert stmt.pointer_names == ["WS-PTR-A", "WS-PTR-B"]
        assert len(result.ast.find_all_by_type("DisplayStatement")) == 1

    def test_free_and_allocate_remain_valid_data_item_declarations(self):
        """FREE/ALLOCATE have no dedicated TokenType (see the module
        docstring on allocate_free_parsers.py) -- they are recognized only by
        value at a genuine statement-start position via matches(), so a data
        item legitimately declared FREE/ALLOCATE must still lex as a normal
        IDENTIFIER in the DATA DIVISION, unaffected by the new parser.

        This does not cover using FREE/ALLOCATE as a *trailing operand* of
        another statement (e.g. ``DISPLAY FREE``, ``MOVE X TO ALLOCATE``) --
        that collides with the pre-existing STATEMENT_KEYWORDS boundary
        heuristic several other statement parsers already apply to any word
        in that set, independent of whether a parser is registered for it,
        and is out of scope here.
        """
        src = """IDENTIFICATION DIVISION.
PROGRAM-ID. T9.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 FREE PIC X(5) VALUE 'ABCDE'.
01 ALLOCATE PIC X(5) VALUE 'FGHIJ'.
PROCEDURE DIVISION.
MAIN.
    STOP RUN.
"""
        result = parse_cobol(src)
        assert result.success
        assert result.errors == []
        items = {i.name for i in result.ast.find_all_by_type("CobolDataItem")}
        assert {"FREE", "ALLOCATE"} <= items

    def test_free_and_allocate_as_bare_paragraph_names_no_longer_hang(self):
        """Known limitation, not regressed further by this fix: a paragraph
        named exactly ``FREE.``/``ALLOCATE.`` (with nothing else on that
        line) is ambiguous with a zero-operand FREE/ALLOCATE statement, and
        ``ProcedureDivisionParser``'s ``is_statement_keyword`` boundary check
        (``procedure_boundaries.py``) resolves that ambiguity in favor of the
        statement reading -- both are folded into one implicit unnamed
        paragraph instead of two correctly-named ones.

        This ambiguity is NOT introduced by this fix and is not something it
        attempts to resolve: it already existed for every other bare-word
        verb with no dedicated TokenType and no registered parser (PURGE,
        RESUME, ...), where a paragraph named after one of those words causes
        the parser to hang indefinitely (confirmed against the unmodified
        parser: ``PROCEDURE DIVISION. PURGE. DISPLAY '...'.`` never
        terminates). What this fix *does* guarantee -- because ALLOCATE/FREE
        now have real registered parsers -- is that the same shape no longer
        hangs and loses no statement content, even though the paragraph
        structure is imperfect.
        """
        src = """IDENTIFICATION DIVISION.
PROGRAM-ID. T10.
PROCEDURE DIVISION.
FREE.
    DISPLAY 'in free para'.
ALLOCATE.
    DISPLAY 'in allocate para'.
    STOP RUN.
"""
        result = parse_cobol(src)
        assert result.success
        assert result.errors == []
        assert result.warnings == []
        stmt_types = [type(s).__name__ for s in result.ast.get_all_statements()]
        assert stmt_types == [
            "FreeStatement",
            "DisplayStatement",
            "AllocateStatement",
            "DisplayStatement",
            "StopStatement",
        ]
