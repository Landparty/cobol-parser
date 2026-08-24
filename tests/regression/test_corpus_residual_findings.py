"""Regression pins for a real-corpus residual-findings sweep (2026-08-24).

A follow-up corpus run against 1.8.x (105 programs; 88 OK, 17 refused, all
refusals PARSE_WARNING) surfaced six remaining causes -- some residual gaps
in the "Defect 4" (subscript/reference-mod/paren qualifier folding) and
"Defect 5" (``PERFORM ... WITH TEST BEFORE/AFTER``) fixes from earlier
sessions, some new:

1. ``NEXT SENTENCE`` had no statement parser at all, so an IF/EVALUATE/
   SEARCH condition-collection loop (which stops at a known statement
   keyword) never recognized ``NEXT`` as a boundary: the words "NEXT
   SENTENCE" were silently swallowed into the *condition* text instead of
   becoming a (missing) statement in the THEN/ELSE branch.
2. ``PERFORM ... WITH TEST BEFORE/AFTER``: all three call sites (inline,
   out-of-line, and inside the VARYING header) peeked the token right after
   consuming WITH/TEST with no ``skip_whitespace`` first -- so whenever
   WITH, TEST, or BEFORE/AFTER landed on separate continuation lines, the
   clause was left partially unconsumed and reported as unparsed tokens.
3. DISPLAY's local subscript-folding helper (``_consume_subscript``) peeked
   for a LEFT_PAREN with no whitespace-skip either, so a subscript on its
   own continuation line (``DISPLAY WS-ITEM\\n    (WS-IDX).``) was left
   unconsumed instead of folded into the display item.
4. ``consume_optional_qualifiers`` (the shared OF/IN/subscript "fold") was
   only wired into MOVE, arithmetic, and SET -- WRITE's record-name/FROM
   source, READ's INTO target/KEY name, and START's KEY name still dropped
   a qualified or subscripted operand's trailing tokens as unparsed.
"""

import textwrap

from cobolparser import parse_cobol


class TestNextSentenceStatement:
    """NEXT SENTENCE previously had no statement parser and was swallowed
    into the enclosing IF's condition text instead of becoming a statement.
    """

    def test_next_sentence_in_if_then_branch_is_its_own_statement(self):
        program = textwrap.dedent("""\
            IDENTIFICATION DIVISION.
            PROGRAM-ID. REGTEST.
            DATA DIVISION.
            WORKING-STORAGE SECTION.
            01  WS-A  PIC X VALUE "N".
            PROCEDURE DIVISION.
            MAIN-PARA.
                IF WS-A = "Y"
                    NEXT SENTENCE
                ELSE
                    DISPLAY "NO"
                END-IF.
                STOP RUN.
            """)
        result = parse_cobol(program)
        assert result.success, result.errors
        assert result.warnings == []
        if_stmt = result.ast.find_first_by_type("IfStatement")
        # The condition must not have absorbed "NEXT SENTENCE" as text.
        assert if_stmt.condition.right_operand == "'Y'"
        assert [type(s).__name__ for s in if_stmt.then_statements] == [
            "NextSentenceStatement"
        ]
        assert [type(s).__name__ for s in if_stmt.else_statements] == [
            "DisplayStatement"
        ]

    def test_next_sentence_in_evaluate_when_is_its_own_statement(self):
        program = textwrap.dedent("""\
            IDENTIFICATION DIVISION.
            PROGRAM-ID. REGTEST.
            DATA DIVISION.
            WORKING-STORAGE SECTION.
            01  WS-IDX  PIC 9 VALUE 1.
            PROCEDURE DIVISION.
            MAIN-PARA.
                EVALUATE WS-IDX
                    WHEN 1
                        NEXT SENTENCE
                    WHEN OTHER
                        DISPLAY "OTHER"
                END-EVALUATE.
                STOP RUN.
            """)
        result = parse_cobol(program)
        assert result.success, result.errors
        assert result.warnings == []
        next_sentence = result.ast.find_first_by_type("NextSentenceStatement")
        assert next_sentence is not None


class TestPerformWithTestNewlineTolerance:
    """WITH TEST BEFORE/AFTER split across continuation lines previously
    left TEST (or BEFORE/AFTER) unconsumed -- the "TEST unparsed" residual
    of the earlier Defect 5 fix.
    """

    def test_inline_perform_until_with_test_split_across_lines(self):
        program = textwrap.dedent("""\
            IDENTIFICATION DIVISION.
            PROGRAM-ID. REGTEST.
            DATA DIVISION.
            WORKING-STORAGE SECTION.
            01  WS-EOF-SW  PIC X VALUE "N".
            PROCEDURE DIVISION.
            MAIN-PARA.
                PERFORM WITH
                    TEST AFTER
                    UNTIL WS-EOF-SW = "Y"
                        DISPLAY "LOOP"
                END-PERFORM.
                STOP RUN.
            """)
        result = parse_cobol(program)
        assert result.success, result.errors
        assert result.warnings == []
        perf = result.ast.find_first_by_type("PerformStatement")
        assert perf.test_timing == "AFTER"
        assert perf.perform_type == "UNTIL"
        assert perf.until_condition is not None

    def test_out_of_line_perform_with_test_split_across_lines(self):
        program = textwrap.dedent("""\
            IDENTIFICATION DIVISION.
            PROGRAM-ID. REGTEST.
            PROCEDURE DIVISION.
            MAIN-PARA.
                PERFORM SUB-PARA WITH
                    TEST BEFORE
                    UNTIL 1 = 1.
                STOP RUN.
            SUB-PARA.
                DISPLAY "X".
            """)
        result = parse_cobol(program)
        assert result.success, result.errors
        assert result.warnings == []
        perf = result.ast.find_first_by_type("PerformStatement")
        assert perf.test_timing == "BEFORE"

    def test_perform_varying_with_test_split_across_lines(self):
        program = textwrap.dedent("""\
            IDENTIFICATION DIVISION.
            PROGRAM-ID. REGTEST.
            DATA DIVISION.
            WORKING-STORAGE SECTION.
            01  WS-I  PIC 9(3).
            PROCEDURE DIVISION.
            MAIN-PARA.
                PERFORM VARYING WS-I FROM 1 BY 1 WITH
                    TEST AFTER
                    UNTIL WS-I > 10
                        DISPLAY WS-I
                END-PERFORM.
                STOP RUN.
            """)
        result = parse_cobol(program)
        assert result.success, result.errors
        assert result.warnings == []
        perf = result.ast.find_first_by_type("PerformStatement")
        assert perf.test_timing == "AFTER"


class TestDisplaySubscriptOnContinuationLine:
    """DISPLAY's subscript-folding helper previously required the LEFT_PAREN
    to immediately follow the identifier token -- a subscript wrapped onto
    its own continuation line was left unconsumed as a stray '(' -- the
    "subscript/paren unparsed" residual of the earlier Defect 4 fix.
    """

    def test_subscript_on_its_own_continuation_line_is_folded(self):
        program = textwrap.dedent("""\
            IDENTIFICATION DIVISION.
            PROGRAM-ID. REGTEST.
            DATA DIVISION.
            WORKING-STORAGE SECTION.
            01  WS-TABLE.
                05  WS-ITEM PIC X(5) OCCURS 5 TIMES.
            01  WS-IDX PIC 9.
            PROCEDURE DIVISION.
            MAIN-PARA.
                DISPLAY WS-ITEM
                    (WS-IDX).
                STOP RUN.
            """)
        result = parse_cobol(program)
        assert result.success, result.errors
        assert result.warnings == []
        disp = result.ast.find_first_by_type("DisplayStatement")
        assert disp.display_items == ["WS-ITEM(WS-IDX)"]

    def test_unrelated_item_on_its_own_line_is_not_mistaken_for_a_subscript(
        self,
    ):
        # Guard against over-correcting: a following display item on its own
        # continuation line (no subscript at all) must still be collected as
        # a separate item, not consumed as part of the previous one.
        program = textwrap.dedent("""\
            IDENTIFICATION DIVISION.
            PROGRAM-ID. REGTEST.
            DATA DIVISION.
            WORKING-STORAGE SECTION.
            01  WS-A PIC X(5).
            01  WS-B PIC X(5).
            PROCEDURE DIVISION.
            MAIN-PARA.
                DISPLAY WS-A
                    WS-B.
                STOP RUN.
            """)
        result = parse_cobol(program)
        assert result.success, result.errors
        assert result.warnings == []
        disp = result.ast.find_first_by_type("DisplayStatement")
        assert disp.display_items == ["WS-A", "WS-B"]


class TestQualifierFoldingOnWriteReadStart:
    """consume_optional_qualifiers (OF/IN qualifier chain + subscript fold)
    was only wired into MOVE/arithmetic/SET; WRITE, READ, and START still
    dropped a qualified operand's trailing tokens as unparsed.
    """

    def test_write_from_qualified_source_is_folded(self):
        program = textwrap.dedent("""\
            IDENTIFICATION DIVISION.
            PROGRAM-ID. REGTEST.
            ENVIRONMENT DIVISION.
            INPUT-OUTPUT SECTION.
            FILE-CONTROL.
                SELECT OUT-FILE ASSIGN TO "OUT.DAT".
            DATA DIVISION.
            FILE SECTION.
            FD  OUT-FILE.
            01  OUT-REC PIC X(20).
            WORKING-STORAGE SECTION.
            01  WS-GROUP.
                05  WS-LINE PIC X(20).
            PROCEDURE DIVISION.
            MAIN-PARA.
                OPEN OUTPUT OUT-FILE.
                WRITE OUT-REC FROM WS-LINE OF WS-GROUP.
                CLOSE OUT-FILE.
                STOP RUN.
            """)
        result = parse_cobol(program)
        assert result.success, result.errors
        assert result.warnings == []
        write_stmt = result.ast.find_first_by_type("IOWriteStatement")
        assert write_stmt.from_clause == "WS-LINE OF WS-GROUP"

    def test_read_into_qualified_target_is_folded(self):
        program = textwrap.dedent("""\
            IDENTIFICATION DIVISION.
            PROGRAM-ID. REGTEST.
            ENVIRONMENT DIVISION.
            INPUT-OUTPUT SECTION.
            FILE-CONTROL.
                SELECT IN-FILE ASSIGN TO "IN.DAT".
            DATA DIVISION.
            FILE SECTION.
            FD  IN-FILE.
            01  IN-REC PIC X(20).
            WORKING-STORAGE SECTION.
            01  WS-GROUP.
                05  WS-LINE PIC X(20).
            PROCEDURE DIVISION.
            MAIN-PARA.
                OPEN INPUT IN-FILE.
                READ IN-FILE INTO WS-LINE OF WS-GROUP
                    AT END DISPLAY "EOF"
                END-READ.
                CLOSE IN-FILE.
                STOP RUN.
            """)
        result = parse_cobol(program)
        assert result.success, result.errors
        assert result.warnings == []
        read_stmt = result.ast.find_first_by_type("IOReadStatement")
        assert read_stmt.into_target == "WS-LINE OF WS-GROUP"

    def test_start_key_qualified_name_is_folded(self):
        program = textwrap.dedent("""\
            IDENTIFICATION DIVISION.
            PROGRAM-ID. REGTEST.
            ENVIRONMENT DIVISION.
            INPUT-OUTPUT SECTION.
            FILE-CONTROL.
                SELECT IDX-FILE ASSIGN TO "IDX.DAT"
                    ORGANIZATION IS INDEXED
                    RECORD KEY IS IDX-KEY.
            DATA DIVISION.
            FILE SECTION.
            FD  IDX-FILE.
            01  IDX-REC.
                05  IDX-KEY PIC X(10).
            WORKING-STORAGE SECTION.
            01  WS-GROUP.
                05  WS-KEY PIC X(10).
            PROCEDURE DIVISION.
            MAIN-PARA.
                OPEN INPUT IDX-FILE.
                START IDX-FILE KEY IS EQUAL TO WS-KEY OF WS-GROUP
                    INVALID KEY DISPLAY "BAD"
                END-START.
                CLOSE IDX-FILE.
                STOP RUN.
            """)
        result = parse_cobol(program)
        assert result.success, result.errors
        assert result.warnings == []
        start_stmt = result.ast.find_first_by_type("IOStartStatement")
        assert start_stmt.key_name == "WS-KEY OF WS-GROUP"
