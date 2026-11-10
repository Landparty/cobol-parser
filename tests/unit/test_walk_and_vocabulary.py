"""The shared traversal helpers (models/walk.py) and word lists (_vocabulary)."""

from __future__ import annotations

from cobolparser import parse_cobol
from cobolparser._vocabulary import (
    FIGURATIVE_CANONICAL,
    FIGURATIVE_CONSTANTS,
    FIGURATIVE_CONSTANTS_WITH_ALL,
    ZERO_WORDS,
)
from cobolparser.lexer import CobolLexer
from cobolparser.models.statements.call import CallStatement
from cobolparser.models.walk import all_paragraphs, own_statements, section_paragraphs

MIXED = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. OUTER.
       PROCEDURE DIVISION.
           DISPLAY 'BEFORE ANY NAME'.
       TOP-PARA.
           PERFORM S1.
           GOBACK.
       S1 SECTION.
       S1-A.
           CALL 'SUB1'.
       S2 SECTION.
       S2-A.
           DISPLAY 'X'.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. INNER.
       PROCEDURE DIVISION.
       IN-PARA.
           CALL 'OUTER'.
           GOBACK.
       END PROGRAM INNER.
       END PROGRAM OUTER.
"""


def _ast():
    result = parse_cobol(MIXED)
    assert result.ast is not None
    return result.ast


def test_all_paragraphs_in_source_order_once():
    paragraphs = all_paragraphs(_ast().procedure_division)
    names = [p.paragraph_name for p in paragraphs]
    # The unnamed paragraph holding the statement before the first name
    # comes first.
    assert names == ["", "TOP-PARA", "S1-A", "S2-A"]
    lines = [p.location.line for p in paragraphs]
    assert lines == sorted(lines)
    assert len({id(p) for p in paragraphs}) == len(paragraphs)


def test_section_paragraphs_name_their_owner():
    pairs = section_paragraphs(_ast().procedure_division)
    owners = {p.paragraph_name: owner for owner, p in pairs if p.paragraph_name}
    assert owners["TOP-PARA"] is None
    assert owners["S1-A"] == "S1"
    assert owners["S2-A"] == "S2"


def test_none_division():
    assert all_paragraphs(None) == []
    assert section_paragraphs(None) == []


def test_own_statements_skip_contained_programs():
    ast = _ast()
    targets = [
        s.called_program for s in own_statements(ast) if isinstance(s, CallStatement)
    ]
    assert targets == ["SUB1"]
    inner = ast.contained_programs[0]
    assert [
        s.called_program for s in own_statements(inner) if isinstance(s, CallStatement)
    ] == ["OUTER"]


def test_vocabulary_sets_agree():
    assert set(FIGURATIVE_CANONICAL) == FIGURATIVE_CONSTANTS
    assert len(FIGURATIVE_CONSTANTS) == 13
    assert FIGURATIVE_CONSTANTS_WITH_ALL == FIGURATIVE_CONSTANTS | {"ALL"}
    assert ZERO_WORDS <= FIGURATIVE_CONSTANTS
    assert set(FIGURATIVE_CANONICAL.values()) == {
        "ZERO",
        "SPACE",
        "HIGH-VALUE",
        "LOW-VALUE",
        "QUOTE",
        "NULL",
    }
    # The lexer's class attribute stays a mutable set with the same words.
    assert isinstance(CobolLexer.FIGURATIVE_CONSTANTS, set)
    assert CobolLexer.FIGURATIVE_CONSTANTS == FIGURATIVE_CONSTANTS_WITH_ALL
