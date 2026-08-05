"""Regression tests: POINTER data items with VALUE IS NULL in WORKING-STORAGE.

NULL and NULLS are standard COBOL figurative constants (IBM Enterprise COBOL
and ISO/IEC 1989), used as the VALUE clause of USAGE POINTER /
PROCEDURE-POINTER / FUNCTION-POINTER data items, and as the operand of
`SET ptr TO NULL` / relational pointer comparisons (`IF ptr = NULL`).
`CobolLexer.FIGURATIVE_CONSTANTS` (lexer.py) previously omitted them, so
`NULL` lexed as a plain IDENTIFIER token instead of
`TokenType.FIGURATIVE_CONSTANT` -- notably, several analysis modules
(`analysis/move_type_checker.py`, `analysis/constraints.py`,
`generators/data/values.py`) already carried their own private
"NULL"/"NULLS" figurative-constant lists in anticipation of this, but the
lexer itself -- the single source of truth for token classification -- never
actually classified the word that way.

`parse_value_clause` (parsers/divisions/data_clauses.py) happened to also
accept a bare IDENTIFIER token as a VALUE clause operand, so `VALUE IS NULL`
already produced `value_clause == "NULL"` by accident even before this fix.
This suite pins the *correct* lexical classification (FIGURATIVE_CONSTANT)
alongside the parser-level behavior, so a future change to the IDENTIFIER
fallback branch in `parse_value_clause` cannot silently regress pointer
VALUE clauses.
"""

from cobolparser import parse_cobol
from cobolparser.lexer import CobolLexer, TokenType

HEADER = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. NULLPTRREG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
"""

FOOTER = """\
       PROCEDURE DIVISION.
       MAIN-PARA.
           STOP RUN.
"""


def _parse(ws_source: str):
    result = parse_cobol(HEADER + ws_source + FOOTER, filename="nullptrreg.cbl")
    assert result.success, result.errors
    return result


def _find_item(result, name: str):
    """Find the first data item with the given name in the parsed AST."""
    for item in result.ast.find_all_by_type("DataItem"):
        if getattr(item, "name", None) and item.name.upper() == name.upper():
            return item
    return None


class TestNullFigurativeConstantLexing:
    """NULL/NULLS must lex as TokenType.FIGURATIVE_CONSTANT, not IDENTIFIER."""

    def test_null_lexes_as_figurative_constant(self):
        tokens = CobolLexer("VALUE IS NULL.", free_form=True).tokenize()
        null_tok = next(t for t in tokens if t.value.upper() == "NULL")
        assert null_tok.type == TokenType.FIGURATIVE_CONSTANT

    def test_nulls_lexes_as_figurative_constant(self):
        tokens = CobolLexer("VALUE IS NULLS.", free_form=True).tokenize()
        null_tok = next(t for t in tokens if t.value.upper() == "NULLS")
        assert null_tok.type == TokenType.FIGURATIVE_CONSTANT


class TestPointerValueIsNull:
    """USAGE POINTER (and PROCEDURE-POINTER/FUNCTION-POINTER) VALUE IS NULL."""

    def test_pointer_value_is_null(self):
        item = _find_item(
            _parse("       01  WS-PTR  USAGE IS POINTER VALUE IS NULL.\n"),
            "WS-PTR",
        )
        assert item is not None
        assert item.usage == "POINTER"
        assert item.value_clause == "NULL"

    def test_pointer_value_null_no_is(self):
        item = _find_item(
            _parse("       01  WS-PTR  USAGE POINTER VALUE NULL.\n"), "WS-PTR"
        )
        assert item is not None
        assert item.value_clause == "NULL"

    def test_pointer_value_nulls_plural(self):
        item = _find_item(
            _parse("       01  WS-PTR  USAGE POINTER VALUE NULLS.\n"), "WS-PTR"
        )
        assert item is not None
        assert item.value_clause == "NULLS"

    def test_pointer_without_usage_keyword_value_null(self):
        """POINTER may appear bare, without an explicit USAGE keyword."""
        item = _find_item(_parse("       01  WS-PTR  POINTER VALUE NULL.\n"), "WS-PTR")
        assert item is not None
        assert item.usage == "POINTER"
        assert item.value_clause == "NULL"

    def test_procedure_pointer_value_null(self):
        item = _find_item(
            _parse("       01  WS-PPTR  USAGE IS PROCEDURE-POINTER VALUE IS NULL.\n"),
            "WS-PPTR",
        )
        assert item is not None
        assert item.usage == "PROCEDURE-POINTER"
        assert item.value_clause == "NULL"

    def test_function_pointer_value_null(self):
        item = _find_item(
            _parse("       01  WS-FPTR  USAGE IS FUNCTION-POINTER VALUE IS NULL.\n"),
            "WS-FPTR",
        )
        assert item is not None
        assert item.usage == "FUNCTION-POINTER"
        assert item.value_clause == "NULL"

    def test_pointer_value_null_emits_no_warnings(self):
        result = _parse("       01  WS-PTR  USAGE IS POINTER VALUE IS NULL.\n")
        assert result.warnings == []


class TestNullInProcedureDivision:
    """SET ptr TO NULL and relational NULL comparisons alongside the VALUE clause."""

    def test_set_pointer_to_null_and_compare(self):
        source = f"""\
{HEADER}       01  WS-PTR  USAGE IS POINTER VALUE IS NULL.
       PROCEDURE DIVISION.
       MAIN-PARA.
           SET WS-PTR TO NULL.
           IF WS-PTR = NULL
               DISPLAY "NULL PTR"
           END-IF.
           STOP RUN.
"""
        result = parse_cobol(source, filename="nullptrreg2.cbl")
        assert result.success, result.errors
        assert result.warnings == []

        set_stmt = result.ast.find_first_by_type("SetStatement")
        assert set_stmt is not None
        assert set_stmt.targets == ["WS-PTR"]
        assert set_stmt.value == "NULL"
