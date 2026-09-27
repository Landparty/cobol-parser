"""A literal holding its own delimiter reads back as one character.

Parsers re-emit every decoded literal through ``quote_literal``, which
doubles each embedded double quote. Consumers that stripped only the outer
delimiters read a VALUE literal holding a double quote with that quote
doubled in generated data, and folded a MOVE of a one-character quote
literal to two quote characters.
"""

from cobolparser import parse_cobol
from cobolparser._literals import quote_literal, unquote_literal
from cobolparser.analysis.const_fold import ConstantFolder
from cobolparser.generators import (
    CopybookDataGenerator,
    DataGeneratorOptions,
    ProgramLayoutIndex,
)


def test_unquote_inverts_quote():
    for value in ['"', 'A"B', "IT'S", "", '""', "plain"]:
        assert unquote_literal(quote_literal(value)) == value
    assert unquote_literal("'IT''S'") == "IT'S"
    assert unquote_literal("  WS-NAME ") == "WS-NAME"


def test_generated_value_clause_collapses_doubled_quotes():
    source = (
        "       01 REC.\n"
        "          05 F1 PIC X(3) VALUE 'I''M'.\n"
        '          05 F2 PIC X(3) VALUE "A""B".\n'
        "          05 F3 PIC X VALUE '\"'.\n"
    )
    dataset = CopybookDataGenerator(
        DataGeneratorOptions(rows=1, seed=1)
    ).generate_from_source(source)
    assert dataset.rows[0] == ["I'M", 'A"B', '"']


def test_folded_move_of_a_quote_character():
    source = (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. T.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01 A PIC X(3).\n"
        "       PROCEDURE DIVISION.\n"
        "       MAIN-PARA.\n"
        "           MOVE '\"' TO A\n"
        "           DISPLAY A\n"
        "           STOP RUN.\n"
    )
    result = parse_cobol(source)
    index = ProgramLayoutIndex.build(result.ast)
    assert ConstantFolder().fold(result.ast, index).known == {"A": '"'}
