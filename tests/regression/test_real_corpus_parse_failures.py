"""Regression coverage for a real-corpus parse-failure sweep (2026-08-20).

An external analysis of a 559-file real-world COBOL corpus (mainframe
extracts, distinct from the NIST/shamrice fixtures already in this repo)
surfaced hard parse failures and silent content-drops that the existing
synthetic test fixtures never exercised. See the dated entry in
``.okf/log.md`` for the full writeup; each test below pins one of the five
confirmed, reproduced fixes.

A follow-up pass (2026-08-21) found two more statements that never learned
the all-digit-procedure-name support ``PERFORM`` already had: ``ALTER``'s
from-paragraph, and the extra targets of a computed ``GO TO ... DEPENDING
ON`` list. Both silently dropped content the same way the five fixes above
did.

A second controlled re-probe against the same corpus on 1.8.0 (2026-08-21)
found four items still standing:

* The paragraph-boundary heuristic's dedent disambiguation (H9) was only
  ever applied to a statement's *first* operand -- a second-or-later
  operand on its own continuation line was still misread as a paragraph
  header and dropped across every multi-operand statement (MOVE, OPEN,
  CLOSE, SET, DISPLAY, CANCEL, SORT/MERGE's KEY/USING/GIVING lists,
  STRING/UNSTRING, INITIALIZE/INSPECT's TALLYING, ADD/SUBTRACT/MULTIPLY/
  DIVIDE's extra TO/FROM/GIVING targets, and COMPUTE's expression).
* The lexer's digit-led-identifier lookahead only peeked one hyphen
  segment ahead, so a hyphenated paragraph/data name was misread as a
  numeric literal (plus a stray MINUS and identifier) whenever its first
  segment happened to look like scientific notation (``43E00-PROD``,
  ``4E000-X``) or its first letter only appeared two hyphens in
  (``22310-01-TRAITE``).
* SET's subscript fix from the first sweep only covered the *target* side
  (``SET tbl(1) TO ...``); the *value* side (``SET x TO tbl(1)``, ``... TO
  ADDRESS OF tbl(1)``, ``... UP/DOWN BY tbl(1)``) still dropped the
  subscript.
* Embedded SQL's ``¬=`` (the EBCDIC-derived not-equal spelling some
  mainframe source uses instead of ``!=``) had no lexer token and hit the
  same hard ``LexerError`` ``!=``/``||`` did before the first sweep.

``COMPUTE ... EQUAL`` (using the word ``EQUAL`` in place of ``=``) was
flagged again and again left alone: still unconfirmed against real IBM
Enterprise COBOL compiler behavior, so likely invalid COBOL rather than a
parser gap.
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

    def test_genuinely_missing_first_target_before_dedented_paragraph_still_errors(
        self,
    ):
        # Guard against over-correcting the other way: a MOVE with no
        # target at all (target_count == 0), immediately followed by a real
        # paragraph header dedented back to Area A, must still be flagged
        # as a boundary -- not silently absorbed as the MOVE's target,
        # which would both hide the malformed MOVE and delete the
        # following paragraph from the AST.
        program = textwrap.dedent("""\
            IDENTIFICATION DIVISION.
            PROGRAM-ID. REGTEST.
            DATA DIVISION.
            WORKING-STORAGE SECTION.
            01  WS-A PIC X(5).
            01  WS-B PIC X(5).
            PROCEDURE DIVISION.
            MAIN-PARA.
                MOVE WS-A TO
            NEXT-PARA.
                DISPLAY WS-B.
            """)
        result = parse_cobol(program)
        assert result.success is False
        assert any(
            "requires at least one target after TO" in str(e) for e in result.errors
        ), result.errors
        paragraphs = result.ast.procedure_division.paragraphs
        assert [p.paragraph_name for p in paragraphs] == ["MAIN-PARA", "NEXT-PARA"]
        move_stmt = result.ast.find_first_by_type("MoveStatement")
        assert move_stmt.targets == []


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

    def test_file_truncated_right_after_program_name_is_tolerated(self):
        # token_stream.expect(".") raises UnexpectedEndOfInput (not
        # TokenMismatch) when the stream is exhausted immediately after the
        # program name -- the exact shape of a truncated real-world corpus
        # file with nothing at all following PROGRAM-ID. NAME. Must be
        # tolerated the same way as a mismatched next token.
        program = "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. REGTEST"
        result = parse_cobol(program, filename="truncated.cbl")
        assert result.success, result.errors
        assert result.errors == []
        assert result.ast.program_name == "REGTEST"
        assert any(
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


class TestAlterNumericProcedureNames:
    """``ALTER``'s from-paragraph required an IDENTIFIER token, so an
    all-digit paragraph name (idiomatic THRU-style numbering, already
    supported everywhere ``PERFORM`` targets one) fell through as an
    unrecognized statement, dropping ``ALTER ... TO PROCEED TO ...``
    entirely.
    """

    def test_alter_with_numeric_from_paragraph_is_not_dropped(self):
        program = textwrap.dedent("""\
            IDENTIFICATION DIVISION.
            PROGRAM-ID. REGTEST.
            PROCEDURE DIVISION.
            MAIN-PARA.
                ALTER 1000 TO PROCEED TO 2000.
                STOP RUN.
            1000.
                GO TO 3000.
            2000.
                DISPLAY "B".
            3000.
                DISPLAY "C".
            """)
        result = parse_cobol(program)
        assert result.success, result.errors
        assert result.errors == []
        assert result.warnings == []
        alter_stmt = result.ast.find_first_by_type("AlterStatement")
        assert alter_stmt.alterations == [
            {"from_paragraph": "1000", "to_paragraph": "2000"}
        ]


class TestGoToDependingOnNumericTargets:
    """A computed ``GO TO target-1 target-2 ... DEPENDING ON`` list only
    recognized IDENTIFIER tokens as extra targets, so once the first
    target was an all-digit procedure name the scan-ahead for more targets
    (and for the ``DEPENDING`` keyword itself) never found them, leaving
    the rest of the statement -- including the ``DEPENDING ON`` variable
    -- unconsumed in the stream.
    """

    def test_all_numeric_targets_and_depending_on_are_captured(self):
        program = textwrap.dedent("""\
            IDENTIFICATION DIVISION.
            PROGRAM-ID. REGTEST.
            DATA DIVISION.
            WORKING-STORAGE SECTION.
            01  WS-N  PIC 9  VALUE 1.
            PROCEDURE DIVISION.
            MAIN-PARA.
                GO TO 1000 2000 3000 DEPENDING ON WS-N.
            1000.
                DISPLAY "A".
            2000.
                DISPLAY "B".
            3000.
                DISPLAY "C".
            """)
        result = parse_cobol(program)
        assert result.success, result.errors
        assert result.errors == []
        assert result.warnings == []
        go_stmt = result.ast.find_first_by_type("GoStatement")
        assert go_stmt.target_paragraphs == ["1000", "2000", "3000"]
        assert go_stmt.depending_on_variable == "WS-N"


class TestSecondOperandOnContinuationLine:
    """The H9 paragraph-boundary dedent disambiguation previously only
    applied to a statement's *first* operand; any later operand wrapped
    onto its own continuation line -- exactly as legitimate as the first --
    was still misread as the start of the next paragraph and dropped.
    """

    def test_move_second_target_on_continuation_line_is_not_dropped(self):
        program = textwrap.dedent("""\
            IDENTIFICATION DIVISION.
            PROGRAM-ID. REGTEST.
            PROCEDURE DIVISION.
            MAIN-PARA.
                MOVE SPACES TO LKTRT-IND-PREMIER-APPEL
                    LKTRT-INDIC-SUITE.
                STOP RUN.
            """)
        result = parse_cobol(program)
        assert result.success, result.errors
        assert result.warnings == []
        move_stmt = result.ast.find_first_by_type("MoveStatement")
        assert move_stmt.targets == [
            "LKTRT-IND-PREMIER-APPEL",
            "LKTRT-INDIC-SUITE",
        ]

    def test_open_second_file_on_continuation_line_is_not_dropped(self):
        program = textwrap.dedent("""\
            IDENTIFICATION DIVISION.
            PROGRAM-ID. REGTEST.
            PROCEDURE DIVISION.
            MAIN-PARA.
                OPEN OUTPUT FD020-FDDATE-OUT
                    FD020-SI6658-OUT.
                STOP RUN.
            """)
        result = parse_cobol(program)
        assert result.success, result.errors
        assert result.warnings == []
        open_stmt = result.ast.find_first_by_type("IOOpenStatement")
        assert open_stmt.file_names == ["FD020-FDDATE-OUT", "FD020-SI6658-OUT"]

    def test_a_genuinely_dedented_next_paragraph_is_still_a_boundary(self):
        # A real missing-target case: the follow-on token really is a
        # dedented (Area A) paragraph header, so it must still be treated
        # as a boundary rather than absorbed as a second MOVE target.
        program = textwrap.dedent("""\
            IDENTIFICATION DIVISION.
            PROGRAM-ID. REGTEST.
            DATA DIVISION.
            WORKING-STORAGE SECTION.
            01  WS-A  PIC X(5).
            01  WS-B  PIC X(5).
            PROCEDURE DIVISION.
            MAIN-PARA.
                MOVE WS-A TO WS-B
            NEXT-PARA.
                STOP RUN.
            """)
        result = parse_cobol(program)
        move_stmt = result.ast.find_first_by_type("MoveStatement")
        assert move_stmt.targets == ["WS-B"]
        assert any(
            "NEXT-PARA" in w and "paragraph" in w for w in result.warnings
        ), result.warnings
        paragraphs = [
            p.paragraph_name for p in result.ast.find_all_by_type("CobolParagraph")
        ]
        assert "NEXT-PARA" in paragraphs


class TestDigitLedHyphenatedProcedureNames:
    """The lexer's digit-led-identifier lookahead only peeked one character
    past the leading digit run. A hyphenated paragraph/data name was
    misread as a numeric literal (plus a stray MINUS and identifier)
    whenever its first segment happened to look like scientific notation
    (``43E00-PROD``) or its first letter only appeared two hyphens in
    (``22310-01-TRAITE``).
    """

    def test_exponent_shaped_first_segment_is_one_identifier(self):
        program = textwrap.dedent("""\
            IDENTIFICATION DIVISION.
            PROGRAM-ID. REGTEST.
            PROCEDURE DIVISION.
                PERFORM 43E00-PROD.
                STOP RUN.
            43E00-PROD.
                DISPLAY "IN PARA".
            """)
        result = parse_cobol(program)
        assert result.success, result.errors
        assert result.errors == []
        paragraphs = [
            p.paragraph_name for p in result.ast.find_all_by_type("CobolParagraph")
        ]
        assert "43E00-PROD" in paragraphs

    def test_letter_two_hyphens_in_is_one_identifier(self):
        program = textwrap.dedent("""\
            IDENTIFICATION DIVISION.
            PROGRAM-ID. REGTEST.
            PROCEDURE DIVISION.
                PERFORM 22310-01-TRAITE.
                STOP RUN.
            22310-01-TRAITE.
                DISPLAY "IN PARA".
            """)
        result = parse_cobol(program)
        assert result.success, result.errors
        assert result.errors == []
        paragraphs = [
            p.paragraph_name for p in result.ast.find_all_by_type("CobolParagraph")
        ]
        assert "22310-01-TRAITE" in paragraphs

    def test_plain_scientific_notation_literals_are_unaffected(self):
        program = textwrap.dedent("""\
            IDENTIFICATION DIVISION.
            PROGRAM-ID. REGTEST.
            PROCEDURE DIVISION.
            MAIN-PARA.
                COMPUTE WS-A = 5E10.
                COMPUTE WS-B = 5E+5.
                COMPUTE WS-C = 5E-3.
                COMPUTE WS-D = 1.5E10.
                STOP RUN.
            """)
        result = parse_cobol(program)
        assert result.success, result.errors
        assert result.errors == []
        computes = result.ast.find_all_by_type("ComputeStatement")
        assert [c.expression for c in computes] == ["5E10", "5E+5", "5E-3", "1.5E10"]


class TestSetSubscriptedValue:
    """SET's subscript fix from the first sweep only covered the *target*
    side (``SET tbl(1) TO ...``); the *value* side dropped the subscript
    for every SET form (plain TO, TO ADDRESS OF, UP BY, DOWN BY).
    """

    def test_plain_to_value_subscript_is_captured(self):
        program = textwrap.dedent("""\
            IDENTIFICATION DIVISION.
            PROGRAM-ID. REGTEST.
            PROCEDURE DIVISION.
            MAIN-PARA.
                SET WS-IDX TO TABLE-ITEM(5).
                STOP RUN.
            """)
        result = parse_cobol(program)
        assert result.success, result.errors
        set_stmt = result.ast.find_first_by_type("SetStatement")
        assert set_stmt.value == "TABLE-ITEM ( 5 )"

    def test_address_of_value_subscript_is_captured(self):
        program = textwrap.dedent("""\
            IDENTIFICATION DIVISION.
            PROGRAM-ID. REGTEST.
            PROCEDURE DIVISION.
            MAIN-PARA.
                SET WS-PTR TO ADDRESS OF TABLE-ITEM(I).
                STOP RUN.
            """)
        result = parse_cobol(program)
        assert result.success, result.errors
        set_stmt = result.ast.find_first_by_type("SetStatement")
        assert set_stmt.value == "TABLE-ITEM ( I )"
        assert set_stmt.value_is_address_of is True

    def test_up_by_value_subscript_is_captured(self):
        program = textwrap.dedent("""\
            IDENTIFICATION DIVISION.
            PROGRAM-ID. REGTEST.
            PROCEDURE DIVISION.
            MAIN-PARA.
                SET WS-IDX UP BY INCREMENT-TABLE(I).
                STOP RUN.
            """)
        result = parse_cobol(program)
        assert result.success, result.errors
        set_stmt = result.ast.find_first_by_type("SetStatement")
        assert set_stmt.value == "INCREMENT-TABLE ( I )"

    def test_down_by_value_subscript_is_captured(self):
        program = textwrap.dedent("""\
            IDENTIFICATION DIVISION.
            PROGRAM-ID. REGTEST.
            PROCEDURE DIVISION.
            MAIN-PARA.
                SET WS-IDX DOWN BY DECREMENT-TABLE(J).
                STOP RUN.
            """)
        result = parse_cobol(program)
        assert result.success, result.errors
        set_stmt = result.ast.find_first_by_type("SetStatement")
        assert set_stmt.value == "DECREMENT-TABLE ( J )"


class TestEmbeddedSqlNotSignOperator:
    """Embedded SQL's ``¬=`` (the EBCDIC-derived not-equal spelling some
    mainframe source uses instead of ``!=``) had no lexer token and hit the
    lexer's unrecognized-character branch, failing the entire parse just
    like ``!=``/``||`` did before the first sweep.
    """

    def test_not_sign_equal_operator_does_not_crash_the_parse(self):
        program = textwrap.dedent("""\
            IDENTIFICATION DIVISION.
            PROGRAM-ID. REGTEST.
            PROCEDURE DIVISION.
            MAIN-PARA.
                EXEC SQL
                    SELECT COL1 INTO :WS-HOST-VAR
                    FROM TABLE1
                    WHERE STATUS ¬= 'X'
                END-EXEC.
                DISPLAY "AFTER SQL".
                STOP RUN.
            """)
        result = parse_cobol(program)
        assert result.success, result.errors
        assert result.errors == []
        exec_stmt = result.ast.find_first_by_type("ExecSQLStatement")
        assert "¬=" in exec_stmt.sql_text
        display_stmt = result.ast.find_first_by_type("DisplayStatement")
        assert display_stmt.display_items == ['"AFTER SQL"']
