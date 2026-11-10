"""A CBL / PROCESS option card in front of a later program in a batch
compile is a compiler directive, as it is at the top of the file.

It used to reach the parser, which stopped at "No recognizable COBOL
division" and lost every program after the card (open-source corpus
finding: IBM DBB MortgageApplication ``epscsmrd.cbl``).
"""

from cobolparser import CobolParser, ErrorRecoveryMode
from cobolparser.models.walk import own_statements
from cobolparser.preprocess import strip_compiler_directives


def _units(src: str):
    result = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL).parse(src)
    assert result.ast is not None
    assert not result.errors, [str(e) for e in result.errors]
    return [
        (u.program_name, [type(s).__name__ for s in own_statements(u)])
        for u in result.ast.program_units()
    ]


BATCH = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. T.
       PROCEDURE DIVISION.
           DISPLAY "T".
       END PROGRAM T.
      * options for U
       CBL NODYNAM,
      -    APOST
       PROCESS ARITH(EXTEND)
       IDENTIFICATION DIVISION.
       PROGRAM-ID. U.
       PROCEDURE DIVISION.
           DISPLAY "U".
       END PROGRAM U.
"""


def test_cards_before_second_program_are_stripped():
    assert _units(BATCH) == [("T", ["DisplayStatement"]), ("U", ["DisplayStatement"])]


def test_cards_are_blanked_keeping_line_numbers():
    out = strip_compiler_directives(BATCH)
    lines = out.split("\n")
    assert len(lines) == len(BATCH.split("\n"))
    assert "CBL" not in out and "ARITH" not in out and "PROCESS" not in out
    assert lines[5].strip() == "* options for U"


def test_process_section_after_end_program_is_code():
    # Only option cards are stripped: a header ending in a period stays.
    src = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. OUTER.
       PROCEDURE DIVISION.
           DISPLAY "O".
       IDENTIFICATION DIVISION.
       PROGRAM-ID. INNER.
       PROCEDURE DIVISION.
           DISPLAY "I".
       END PROGRAM INNER.
       PROCESS SECTION.
           DISPLAY "P".
       END PROGRAM OUTER.
"""
    assert "PROCESS SECTION." in strip_compiler_directives(src)


def test_directive_section_closes_after_next_program_starts():
    src = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. T.
       PROCEDURE DIVISION.
           DISPLAY "T".
       END PROGRAM T.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. U.
       PROCEDURE DIVISION.
           PERFORM PROCESS-IT.
       PROCESS-IT.
           DISPLAY "U".
"""
    assert strip_compiler_directives(src) == src
