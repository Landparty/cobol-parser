"""Regression coverage for a real-corpus parse-failure sweep (2026-08-20).

An external analysis of a 559-file real-world COBOL corpus (mainframe
extracts, distinct from the NIST/shamrice fixtures already in this repo)
surfaced hard parse failures and silent content-drops that the existing
synthetic test fixtures never exercised. See the dated entry in
``.okf/log.md`` for the full writeup; each test below pins one of the five
confirmed, reproduced fixes.
"""

import textwrap

from cobolparser import parse_cobol


class TestMoveTargetOnContinuationLine:
    """MOVE's paragraph-boundary heuristic previously misread a target on
    its own continuation line as the start of the next paragraph whenever
    that target wasn't a known DATA DIVISION name (e.g. declared via an
    unexpanded COPY member) -- dropping the target entirely and reporting
    "MOVE statement requires at least one target after TO" on otherwise
    valid COBOL.
    """

    def test_unexpanded_copybook_target_on_next_line_is_not_dropped(self):
        program = textwrap.dedent("""\
            IDENTIFICATION DIVISION.
            PROGRAM-ID. REGTEST.
            DATA DIVISION.
            WORKING-STORAGE SECTION.
            01  WS-SOURCE-FIELD    PIC 9(5).
            COPY UNEXPANDED-COPYBOOK.
            PROCEDURE DIVISION.
            MAIN-PARA.
                MOVE WS-SOURCE-FIELD TO
                    WS-TARGET-FROM-COPYBOOK.
                STOP RUN.
            """)
        result = parse_cobol(program)
        assert result.success, result.errors
        assert result.errors == []
        move_stmt = result.ast.find_first_by_type("MoveStatement")
        assert move_stmt.targets == ["WS-TARGET-FROM-COPYBOOK"]

    def test_declared_target_on_next_line_still_works(self):
        # Same shape, but the target IS a known DATA DIVISION name -- this
        # already worked before the fix and must keep working.
        program = textwrap.dedent("""\
            IDENTIFICATION DIVISION.
            PROGRAM-ID. REGTEST.
            DATA DIVISION.
            WORKING-STORAGE SECTION.
            01  WS-SOURCE-FIELD    PIC 9(5).
            01  WS-TARGET-FIELD    PIC 9(5).
            PROCEDURE DIVISION.
            MAIN-PARA.
                MOVE WS-SOURCE-FIELD TO
                    WS-TARGET-FIELD.
                STOP RUN.
            """)
        result = parse_cobol(program)
        assert result.success, result.errors
        move_stmt = result.ast.find_first_by_type("MoveStatement")
        assert move_stmt.targets == ["WS-TARGET-FIELD"]

    def test_genuine_next_paragraph_after_complete_move_still_recognized(self):
        # Guard against over-correcting: once a MOVE already has a target
        # (target_count > 0), the paragraph-boundary check must still fire
        # for a genuinely following paragraph.
        program = textwrap.dedent("""\
            IDENTIFICATION DIVISION.
            PROGRAM-ID. REGTEST.
            DATA DIVISION.
            WORKING-STORAGE SECTION.
            01  WS-A PIC X(5).
            01  WS-B PIC X(5).
            PROCEDURE DIVISION.
            MAIN-PARA.
                MOVE WS-A TO WS-B
            NEXT-PARA.
                DISPLAY "Y".
            """)
        result = parse_cobol(program)
        assert result.errors == []
        paragraphs = result.ast.procedure_division.paragraphs
        assert [p.paragraph_name for p in paragraphs] == ["MAIN-PARA", "NEXT-PARA"]


class TestEmbeddedSqlNotEqualAndConcatOperators:
    """'!=' and '||' inside EXEC SQL previously hit the lexer's
    unrecognized-character branch, which records a hard LexerError and
    fails the *entire* parse (result.ast is None) -- not just that one
    embedded SQL statement.
    """

    def test_not_equal_and_concat_operators_do_not_crash_the_parse(self):
        program = textwrap.dedent("""\
            IDENTIFICATION DIVISION.
            PROGRAM-ID. REGTEST.
            DATA DIVISION.
            WORKING-STORAGE SECTION.
            01  WS-HOST-VAR        PIC X(10).
            01  WS-COMP-VAR        PIC S9(5) COMP-3.
            PROCEDURE DIVISION.
            MAIN-PARA.
                EXEC SQL
                    SELECT COL1 || COL2 INTO :WS-HOST-VAR
                    FROM TABLE1
                    WHERE STATUS != 'X'
                    AND AMOUNT <= :WS-COMP-VAR
                END-EXEC.
                DISPLAY "AFTER SQL".
                STOP RUN.
            """)
        result = parse_cobol(program)
        assert result.success, result.errors
        assert result.errors == []
        exec_stmt = result.ast.find_first_by_type("ExecSQLStatement")
        assert "||" in exec_stmt.sql_text
        assert "!=" in exec_stmt.sql_text
        display_stmt = result.ast.find_first_by_type("DisplayStatement")
        assert display_stmt.display_items == ['"AFTER SQL"']


class TestProgramIdMissingTrailingPeriod:
    """IBM Enterprise COBOL tolerates a missing period after the PROGRAM-ID
    program name; the parser previously raised a hard ParseError there,
    which aborted IDENTIFICATION DIVISION parsing before AUTHOR/
    DATE-WRITTEN/etc. were ever reached.
    """

    def test_missing_period_after_program_name_is_tolerated(self):
        program = textwrap.dedent("""\
            IDENTIFICATION DIVISION.
            PROGRAM-ID. REGTEST
            AUTHOR. SOMEONE.
            PROCEDURE DIVISION.
            MAIN-PARA.
                STOP RUN.
            """)
        result = parse_cobol(program)
        assert result.success, result.errors
        assert result.errors == []
        assert result.ast.program_name == "REGTEST"
        assert any(
            "Missing '.' after program name" in w for w in result.warnings
        ), result.warnings

    def test_well_formed_program_id_period_unaffected(self):
        program = textwrap.dedent("""\
            IDENTIFICATION DIVISION.
            PROGRAM-ID. REGTEST.
            PROCEDURE DIVISION.
            MAIN-PARA.
                STOP RUN.
            """)
        result = parse_cobol(program)
        assert result.success, result.errors
        assert not any(
            "Missing '.' after program name" in w for w in result.warnings
        ), result.warnings


class TestSetSubscriptedTargetWithAddressOf:
    """SET target(subscript) TO ADDRESS OF ... previously dropped both the
    subscript and the entire TO ADDRESS OF value clause, since the
    unconsumed subscript tokens stopped the target-collection loop before
    the TO keyword was ever reached.
    """

    def test_subscripted_target_and_address_of_value_are_both_captured(self):
        program = textwrap.dedent("""\
            IDENTIFICATION DIVISION.
            PROGRAM-ID. REGTEST.
            DATA DIVISION.
            WORKING-STORAGE SECTION.
            01  WS-PTR-TABLE PIC S9(9) COMP OCCURS 5 TIMES.
            01  WS-TARGET    PIC X(10).
            PROCEDURE DIVISION.
            MAIN-PARA.
                SET WS-PTR-TABLE(1) TO ADDRESS OF WS-TARGET.
                STOP RUN.
            """)
        result = parse_cobol(program)
        assert result.success, result.errors
        assert result.warnings == []
        set_stmt = result.ast.find_first_by_type("SetStatement")
        assert set_stmt.targets == ["WS-PTR-TABLE ( 1 )"]
        assert set_stmt.value == "WS-TARGET"
        assert set_stmt.value_is_address_of is True


class TestSkipCompilerDirectives:
    """SKIP1/SKIP2/SKIP3 (compiler-directing listing no-ops, the same class
    as EJECT) previously lexed as plain IDENTIFIERs with no registered
    parser, dropping the directive and adjacent statement tokens from the
    AST via the PROCEDURE DIVISION's unrecognized-statement recovery.
    """

    def test_skip_directives_do_not_drop_surrounding_statements(self):
        program = textwrap.dedent("""\
            IDENTIFICATION DIVISION.
            PROGRAM-ID. REGTEST.
            PROCEDURE DIVISION.
            MAIN-PARA.
                DISPLAY "BEFORE".
                SKIP1
                SKIP2
                SKIP3
                DISPLAY "AFTER".
                STOP RUN.
            """)
        result = parse_cobol(program)
        assert result.success, result.errors
        assert result.errors == []
        statement_types = [type(s).__name__ for s in result.ast.get_all_statements()]
        assert statement_types == [
            "DisplayStatement",
            "SkipStatement",
            "SkipStatement",
            "SkipStatement",
            "DisplayStatement",
            "StopStatement",
        ]
        skip_stmts = result.ast.find_all_by_type("SkipStatement")
        assert [s.lines for s in skip_stmts] == [1, 2, 3]
