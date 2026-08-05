"""Regression tests for removing dead/harmful entries from lexer.KEYWORDS.

Seven words -- FILE-STATUS, RECORD-DELIMITER, READ-ONLY, END-OF-FILE, EOF,
END-SET, OTHERWISE -- were mapped in ``CobolLexer.KEYWORDS`` to a
``TokenType`` that no parser anywhere ever consumed (verified: zero
non-lexer references to ``TokenType.FILE_STATUS`` / ``RECORD_DELIMITER`` /
``READ_ONLY`` / ``END_OF_FILE`` / ``END_SET`` / ``OTHERWISE`` in the
codebase). Real COBOL syntax for FILE STATUS / RECORD DELIMITER / READ ONLY
is always two separate words (parsed by ``environment_select.py`` dispatching
on the leading word); END-SET and OTHERWISE are not COBOL reserved words at
all; END-OF-FILE/EOF is not a reserved word either -- it is exactly the
condition-name real IBM programs conventionally give their end-of-file
level-88 flag. Every one of these entries therefore existed only to silently
corrupt a legitimately-named data item, paragraph, or level-88 condition:
the word never reached ``ANONYMOUS-N`` naming as an ``IDENTIFIER`` and every
downstream reference to it produced a wrong or missing AST node with
``result.success`` still ``True``.
"""

import pytest

from cobolparser import parse_cobol

DEAD_KEYWORDS = [
    "FILE-STATUS",
    "RECORD-DELIMITER",
    "READ-ONLY",
    "END-OF-FILE",
    "EOF",
    "END-SET",
    "OTHERWISE",
]


class TestDeadKeywordsAsDataNames:
    @pytest.mark.parametrize("word", DEAD_KEYWORDS)
    def test_usable_as_a_data_item_name(self, word):
        src = f"""IDENTIFICATION DIVISION.
PROGRAM-ID. T1.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 {word} PIC X(5) VALUE 'ABCDE'.
PROCEDURE DIVISION.
MAIN-PARA.
    MOVE 'HELLO' TO {word}
    DISPLAY {word}.
    STOP RUN.
"""
        result = parse_cobol(src)
        assert result.success, f"{word}: errors={result.errors}"
        assert result.errors == []
        assert result.warnings == []
        items = [i.name for i in result.ast.find_all_by_type("CobolDataItem")]
        assert word in items
        moves = result.ast.find_all_by_type("MoveStatement")
        assert any(word in m.targets for m in moves)


class TestDeadKeywordsAsParagraphNames:
    @pytest.mark.parametrize("word", DEAD_KEYWORDS)
    def test_usable_as_a_paragraph_name(self, word):
        src = f"""IDENTIFICATION DIVISION.
PROGRAM-ID. T2.
PROCEDURE DIVISION.
{word}.
    DISPLAY 'X'.
    STOP RUN.
"""
        result = parse_cobol(src)
        assert result.success, f"{word}: errors={result.errors}"
        assert result.errors == []
        paras = [
            p.paragraph_name for p in result.ast.find_all_by_type("CobolParagraph")
        ]
        assert word in paras


class TestEndOfFileAsConditionName:
    def test_bare_level_88_condition_name_end_of_file(self):
        """The project's own parsers/statements/_conditions.py docstring
        cites ``IF END-OF-FILE`` as the canonical bare condition-name
        example; this pins that it actually parses that way now."""
        src = """IDENTIFICATION DIVISION.
PROGRAM-ID. T3.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 WS-FLAGS.
   05 EOF-SW PIC X VALUE 'N'.
      88 END-OF-FILE VALUE 'Y'.
PROCEDURE DIVISION.
MAIN.
    IF END-OF-FILE DISPLAY 'DONE' END-IF.
    STOP RUN.
"""
        result = parse_cobol(src)
        assert result.success
        assert result.errors == []
        assert result.warnings == []


class TestRealTwoWordClausesStillWork:
    """The removed hyphenated single-token entries never matched genuine
    COBOL syntax in the first place (see module docstring) -- this confirms
    the real, two-word SELECT clauses these words are named after are
    unaffected by removing the bogus fused-word keyword."""

    def test_file_status_record_delimiter_read_only_select_clauses(self):
        src = """IDENTIFICATION DIVISION.
PROGRAM-ID. T4.
ENVIRONMENT DIVISION.
INPUT-OUTPUT SECTION.
FILE-CONTROL.
    SELECT CUST-FILE ASSIGN TO 'CUSTFILE'
        ORGANIZATION IS INDEXED
        ACCESS MODE IS DYNAMIC
        RECORD KEY IS CUST-ID
        RECORD DELIMITER IS STANDARD-1
        FILE STATUS IS WS-STATUS
        SHARING WITH READ ONLY.
DATA DIVISION.
FILE SECTION.
FD CUST-FILE.
01 CUST-REC.
   05 CUST-ID PIC X(6).
WORKING-STORAGE SECTION.
01 WS-STATUS PIC XX.
PROCEDURE DIVISION.
MAIN.
    STOP RUN.
"""
        result = parse_cobol(src)
        assert result.success
        assert result.errors == []
        assert result.warnings == []
        select = result.ast.find_all_by_type("SelectStatement")[0]
        assert select.file_status == "WS-STATUS"
        assert select.record_delimiter == "STANDARD-1"
        assert select.sharing_mode == "READ ONLY"
