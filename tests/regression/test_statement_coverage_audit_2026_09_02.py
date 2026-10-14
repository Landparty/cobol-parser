"""Regression tests for the 2026-09-02 statement-coverage audit.

The audit asked one question of the parser: can a statement vanish from the
AST without an error or a warning? It found several ways, all pinned here:

1. ``ExecCicsStatement`` / ``ExecImsStatement`` extended ``ASTNode`` rather
   than ``CobolStatement``, so ``CobolProgram.get_all_statements()`` -- the
   walk every analyzer is built on -- never returned them. Silent.
2. ``GO TO`` at the end of a line with its target on the next line took the
   NEWLINE token as the target and re-parsed the real target as a phantom
   paragraph. Silent.
3. The optional ``ON``/``AT`` of a handler phrase (``ADD ... SIZE ERROR``,
   ``CALL ... EXCEPTION``, ``CALL ... OVERFLOW``, ``READ ... END``,
   ``WRITE ... END-OF-PAGE``, ``RETURN/SEARCH ... END``) was not recognised:
   the keyword was swallowed as an operand and the handler body escaped to
   the enclosing paragraph as free-standing statements. Silent.
4. A string literal spelled like a verb (``IF X = "IF"``, ``STRING "IF"
   ...``) was mistaken for the next statement's verb by the value-based
   boundary checks and truncated the condition/operand list (warned, but
   the enclosing statement's structure was lost).
5. A CALL handler body swallowed the enclosing IF's ``ELSE``/``END-IF`` or
   PERFORM's ``END-PERFORM`` (warned as "unsupported statement"), folding
   the ELSE branch into the handler.
6. ``,`` / ``;`` statement separators were reported as dropped content and
   broke IF/ELSE structure when they sat between a THEN body and ``ELSE``.
7. ``XML GENERATE ... SUPPRESS WHEN SPACES`` ended the statement at
   SUPPRESS (a Report Writer verb elsewhere).
8. A set of clause-level gaps found by sweeping the NIST suite: multi-group
   SET, ``[WITH] NO REWIND`` / bare ``LOCK`` / ``REVERSED`` on OPEN/CLOSE,
   ``PERFORM id TIMES``, ``PERFORM WITH TEST AFTER VARYING``, bare ``TEST
   BEFORE``, ``START ... KEY IS = / >= k`` and ``KEY GREATER OR EQUAL``,
   DISPLAY of qualified / small-numeric items, ``GO TO ... DEPENDING ON
   subscripted``, ``READ ... WITH LOCK KEY IS k``, ``ACCEPT ... [ON]
   EXCEPTION``, qualified procedure names, CALL USING numeric literals and
   ``ADDRESS OF``.
"""

import pytest

from cobolparser import parse_cobol
from cobolparser.parsers.statements.ibm_exec_statements import (
    ExecCicsStatement,
    ExecImsStatement,
)

_HEADER = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. AUDIT.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT F1 ASSIGN TO INDD.
       DATA DIVISION.
       FILE SECTION.
       FD  F1.
       01  R1                 PIC X(80).
       WORKING-STORAGE SECTION.
       01  WS-A               PIC 9(4) VALUE 1.
       01  WS-B               PIC X(4) VALUE 'X'.
       01  WS-N               PIC 9 VALUE 2.
       01  SW-1               PIC X.
       01  SW-2               PIC X.
       01  WS-T.
           05 WS-E OCCURS 3 INDEXED BY WS-I PIC X.
       PROCEDURE DIVISION.
       MAIN-PARA.
"""
_FOOTER = "       FAIL.\n           STOP RUN.\n"


def _parse(*lines: str):
    body = "".join(f"           {line}\n" for line in lines)
    return parse_cobol(_HEADER + body + _FOOTER)


def _main(result):
    return result.ast.get_division("PROCEDURE").paragraphs[0].statements


def _types(statements):
    return [type(s).__name__ for s in statements]


def _clean(result):
    assert result.errors == [], result.errors
    assert result.warnings == [], result.warnings


# ---------------------------------------------------------------------------
# 1. EXEC CICS / EXEC DLI are statements
# ---------------------------------------------------------------------------


class TestExecCicsImsAreStatements:
    def test_get_all_statements_returns_exec_cics_and_dli(self):
        result = _parse(
            "EXEC CICS RETURN END-EXEC.",
            "EXEC DLI GU SEGMENT(X) END-EXEC.",
            "EXEC SQL SELECT 1 INTO :WS-A FROM T END-EXEC.",
        )
        _clean(result)
        types = _types(result.ast.get_all_statements())
        assert "ExecCicsStatement" in types
        assert "ExecImsStatement" in types
        assert "ExecSQLStatement" in types

    def test_node_type_and_dict_shape_are_unchanged(self):
        result = _parse("EXEC CICS SEND MAP('M') MAPSET('S') END-EXEC.")
        cics = result.ast.find_all_by_type("EXEC_CICS")[0]
        assert isinstance(cics, ExecCicsStatement)
        assert cics.node_type == "EXEC_CICS"
        assert cics.statement_type == "EXEC CICS"
        assert cics.cics_command == "SEND"
        assert set(cics.to_dict()) == {
            "node_type",
            "cics_command",
            "cics_text",
            "options",
            "location",
        }
        assert result.ast.find_all_by_type("ExecCicsStatement") == [cics]

    def test_ims_command_property_round_trips(self):
        result = _parse("EXEC DLI GU SEGMENT(X) END-EXEC.")
        ims = result.ast.find_all_by_type("EXEC_IMS")[0]
        assert isinstance(ims, ExecImsStatement)
        assert ims.ims_command == "GU"
        assert ims.node_type == "EXEC_IMS"
        assert ims.to_dict()["ims_command"] == "GU"


# ---------------------------------------------------------------------------
# 2. GO TO target on the next line
# ---------------------------------------------------------------------------


class TestGoToTargetAcrossNewline:
    def test_target_on_next_line(self):
        result = _parse("GO TO", "FAIL.")
        _clean(result)
        go = _main(result)[0]
        assert type(go).__name__ == "GoStatement"
        assert go.target_paragraph == "FAIL"
        assert [
            p.paragraph_name for p in result.ast.get_division("PROCEDURE").paragraphs
        ] == [
            "MAIN-PARA",
            "FAIL",
        ]

    def test_depending_on_subscripted_variable(self):
        result = _parse("GO TO FAIL MAIN-PARA DEPENDING ON", "    WS-E (2).")
        _clean(result)
        go = _main(result)[0]
        assert go.to_dict()["depending_on_variable"] == "WS-E ( 2 )"

    def test_section_qualified_target(self):
        result = _parse("GO TO FAIL OF MAIN-SECTION.")
        _clean(result)
        go = _main(result)[0]
        assert go.target_paragraph == "FAIL"
        assert go.metadata["target_qualifier"] == "MAIN-SECTION"


# ---------------------------------------------------------------------------
# 3. Optional ON / AT in handler phrases
# ---------------------------------------------------------------------------


class TestOptionalHandlerKeywords:
    def test_add_size_error_without_on(self):
        result = _parse(
            "ADD 1 TO WS-A SIZE ERROR MOVE 'E' TO WS-B",
            "    NOT SIZE ERROR MOVE 'F' TO WS-B END-ADD.",
        )
        _clean(result)
        add = _main(result)[0]
        assert add.operands == ["1", "WS-A"]
        assert _types(add.on_size_error) == ["MoveStatement"]
        assert _types(add.not_on_size_error) == ["MoveStatement"]
        assert _types(_main(result)) == ["AddStatement"]

    def test_add_inside_call_handler_leaves_not_on_exception_alone(self):
        """NIST IC222A: the ADD's size-error scan must not eat the CALL's
        ``NOT ON EXCEPTION``."""
        result = _parse(
            "CALL 'X' USING WS-A",
            "    ON EXCEPTION",
            "        MOVE 'F' TO WS-B",
            "        ADD 2 TO WS-A",
            "    NOT ON EXCEPTION",
            "        MOVE 'P' TO WS-B",
            "END-CALL.",
        )
        _clean(result)
        call = _main(result)[0]
        assert _types(call.on_exception) == ["MoveStatement", "AddStatement"]
        assert _types(call.not_on_exception) == ["MoveStatement"]

    @pytest.mark.parametrize(
        "source,attr",
        [
            (
                "CALL 'X' USING WS-A EXCEPTION MOVE 'E' TO WS-B END-CALL.",
                "on_exception",
            ),
            ("CALL 'X' USING WS-A OVERFLOW MOVE 'E' TO WS-B END-CALL.", "on_overflow"),
        ],
    )
    def test_call_exception_overflow_without_on(self, source, attr):
        result = _parse(source)
        _clean(result)
        call = _main(result)[0]
        assert call.operands == ["X", "WS-A"]
        assert _types(getattr(call, attr)) == ["MoveStatement"]
        assert _types(_main(result)) == ["CallStatement"]

    def test_call_not_exception_without_on(self):
        result = _parse(
            "CALL 'X' USING WS-A ON EXCEPTION MOVE 'E' TO WS-B",
            "    NOT EXCEPTION MOVE 'F' TO WS-B END-CALL.",
        )
        _clean(result)
        call = _main(result)[0]
        assert _types(call.on_exception) == ["MoveStatement"]
        assert _types(call.not_on_exception) == ["MoveStatement"]

    def test_read_end_and_not_end_without_at(self):
        result = _parse(
            "READ F1 END MOVE 'E' TO WS-B NOT END MOVE 'F' TO WS-B",
            "END-READ.",
        )
        _clean(result)
        read = _main(result)[0]
        assert _types(read.at_end_clause) == ["MoveStatement"]
        assert _types(read.not_at_end_clause) == ["MoveStatement"]

    def test_read_bare_end_does_not_eat_end_program(self):
        source = _HEADER + "           READ F1\n       END PROGRAM AUDIT.\n"
        result = parse_cobol(source)
        read = _main(result)[0]
        assert type(read).__name__ == "IOReadStatement"
        assert not read.at_end_clause

    def test_write_end_of_page_without_at(self):
        result = _parse("WRITE R1 END-OF-PAGE MOVE 'E' TO WS-B END-WRITE.")
        _clean(result)
        write = _main(result)[0]
        assert _types(write.at_eop_clause) == ["MoveStatement"]

    def test_return_and_search_end_without_at(self):
        result = _parse(
            "RETURN F1 END MOVE 'E' TO WS-B END-RETURN.",
            "SEARCH WS-E END MOVE 'G' TO WS-B WHEN WS-E (WS-I) = 'A'",
            "    CONTINUE END-SEARCH.",
        )
        _clean(result)
        ret, search = _main(result)[:2]
        assert _types(ret.at_end_clause) == ["MoveStatement"]
        assert _types(search.at_end_clause) == ["MoveStatement"]

    def test_accept_on_exception(self):
        result = _parse(
            "ACCEPT WS-B ON EXCEPTION DISPLAY 'E'",
            "    NOT ON EXCEPTION DISPLAY 'F' END-ACCEPT.",
        )
        _clean(result)
        accept = _main(result)[0]
        assert _types(accept.on_exception) == ["DisplayStatement"]
        assert _types(accept.not_on_exception) == ["DisplayStatement"]
        assert _types(_main(result)) == ["IOAcceptStatement"]
        d = accept.to_dict()
        assert len(d["on_exception"]) == 1 and len(d["not_on_exception"]) == 1


# ---------------------------------------------------------------------------
# 4. Literals spelled like verbs
# ---------------------------------------------------------------------------


class TestLiteralSpelledLikeVerb:
    def test_if_condition_with_literal_if(self):
        result = _parse(
            "IF WS-B EQUAL TO 'IF'",
            "    MOVE 'STOP' TO WS-B",
            "ELSE",
            "    DISPLAY 'MOVE' 'DISPLAY'",
            "END-IF.",
        )
        _clean(result)
        if_stmt = _main(result)[0]
        assert if_stmt.condition.to_dict()["right_operand"] == "'IF'"
        assert _types(if_stmt.then_statements) == ["MoveStatement"]
        assert _types(if_stmt.else_statements) == ["DisplayStatement"]
        assert _types(_main(result)) == ["IfStatement"]

    def test_compound_condition_with_literal_else(self):
        result = _parse("IF WS-B = 'IF' AND WS-A = 1 MOVE 'A' TO WS-B END-IF.")
        _clean(result)
        assert _types(_main(result)) == ["IfStatement"]
        assert _types(_main(result)[0].then_statements) == ["MoveStatement"]

    def test_string_source_literal_if(self):
        result = _parse("STRING 'IF' DELIMITED BY SIZE INTO WS-B.")
        _clean(result)
        assert _main(result)[0].operands == ['"IF"']

    def test_compute_function_argument_literal(self):
        result = _parse("COMPUTE WS-A = FUNCTION LENGTH('IF').")
        _clean(result)
        assert _types(_main(result)) == ["ComputeStatement"]

    def test_perform_until_literal_stop(self):
        result = _parse("PERFORM FAIL UNTIL WS-B = 'STOP'.")
        _clean(result)
        perform = _main(result)[0]
        assert perform.until_condition is not None

    def test_evaluate_when_literal_verb(self):
        result = _parse(
            "EVALUATE WS-B",
            "    WHEN 'IF' MOVE 'A' TO WS-B",
            "    WHEN 'ELSE' MOVE 'B' TO WS-B",
            "END-EVALUATE.",
        )
        _clean(result)
        ev = _main(result)[0]
        assert len(ev.when_clauses) == 2


# ---------------------------------------------------------------------------
# 5. CALL handler bodies stop at the enclosing statement's boundary
# ---------------------------------------------------------------------------


class TestCallHandlerBoundaries:
    def test_not_on_exception_inside_if_else(self):
        result = _parse(
            "IF WS-B = 'Y'",
            "    CALL 'SUB' USING WS-A",
            "        ON EXCEPTION",
            "            MOVE 'E' TO WS-B",
            "        NOT ON EXCEPTION",
            "            MOVE 'S' TO WS-B",
            "ELSE",
            "    MOVE 'N' TO WS-B",
            "END-IF.",
        )
        _clean(result)
        if_stmt = _main(result)[0]
        assert _types(if_stmt.then_statements) == ["CallStatement"]
        assert _types(if_stmt.else_statements) == ["MoveStatement"]
        call = if_stmt.then_statements[0]
        assert _types(call.on_exception) == ["MoveStatement"]
        assert _types(call.not_on_exception) == ["MoveStatement"]

    def test_handler_inside_inline_perform(self):
        result = _parse(
            "PERFORM 2 TIMES",
            "    CALL 'SUB' USING WS-A",
            "        NOT ON EXCEPTION",
            "            MOVE 'S' TO WS-B",
            "END-PERFORM.",
        )
        _clean(result)
        perform = _main(result)[0]
        assert _types(perform.inline_statements) == ["CallStatement"]
        assert _types(_main(result)) == ["PerformStatement"]


# ---------------------------------------------------------------------------
# 6. Statement separators
# ---------------------------------------------------------------------------


class TestStatementSeparators:
    def test_comma_between_statements(self):
        result = _parse("PERFORM FAIL, GO TO FAIL.")
        _clean(result)
        assert _types(_main(result)) == ["PerformStatement", "GoStatement"]

    def test_semicolon_before_else(self):
        """NIST NC107A: ``... GO TO X; ELSE PERFORM FAIL, GO TO X.``"""
        result = _parse("IF WS-B = '1' GO TO FAIL; ELSE PERFORM FAIL, GO TO FAIL.")
        _clean(result)
        if_stmt = _main(result)[0]
        assert _types(if_stmt.then_statements) == ["GoStatement"]
        assert _types(if_stmt.else_statements) == ["PerformStatement", "GoStatement"]
        assert _types(_main(result)) == ["IfStatement"]

    def test_semicolon_before_call_handler(self):
        """NIST IC201A: ``CALL ... USING A, B; ON OVERFLOW ...``"""
        result = _parse(
            "CALL 'X' USING WS-A, WS-B;",
            "    ON OVERFLOW MOVE 'E' TO WS-B",
            "    GO TO FAIL.",
        )
        _clean(result)
        call = _main(result)[0]
        assert call.operands == ["X", "WS-A", "WS-B"]
        assert _types(call.on_overflow) == ["MoveStatement", "GoStatement"]

    @pytest.mark.parametrize(
        "source",
        [
            "WRITE R1 BEFORE ADVANCING 1 LINE ; AT EOP MOVE 1 TO WS-A.",
            "READ F1 ; AT END MOVE 1 TO WS-A.",
            "START F1 ; INVALID KEY MOVE 1 TO WS-A.",
        ],
    )
    def test_separator_before_io_handler(self, source):
        result = _parse(source)
        _clean(result)
        assert _types(_main(result)) == [_types(_main(result))[0]]

    def test_semicolons_in_set_targets(self):
        """NIST NC245A: ``SET INAME1; INAME2; INAME3 TO 3.``"""
        result = _parse("SET WS-I; WS-I; WS-I TO 3.")
        _clean(result)
        assert _main(result)[0].targets == ["WS-I", "WS-I", "WS-I"]

    def test_separators_in_open_close_file_lists(self):
        result = _parse("OPEN INPUT F1, F1 OUTPUT F1.", "CLOSE F1,", "      F1.")
        _clean(result)
        assert _types(_main(result)) == ["IOOpenStatement", "IOCloseStatement"]


# ---------------------------------------------------------------------------
# 7. XML GENERATE clause words
# ---------------------------------------------------------------------------


class TestXmlGenerateClauses:
    def test_suppress_and_not_on_exception_stay_inside_the_statement(self):
        result = _parse(
            "XML GENERATE WS-B FROM WS-T",
            "    SUPPRESS WHEN SPACES",
            "    ON EXCEPTION DISPLAY 'X' STOP RUN",
            "    NOT ON EXCEPTION DISPLAY 'OK'",
            "END-XML.",
        )
        _clean(result)
        assert _types(_main(result)) == ["XmlJsonStatement"]
        node = _main(result)[0]
        assert node.clause_text == "SUPPRESS WHEN SPACES"
        # The handler bodies are real statement lists (2026-09-02), not
        # clause text -- and STOP RUN stayed inside the ON EXCEPTION body.
        assert [s.statement_type for s in node.on_exception] == ["DISPLAY", "STOP"]
        assert [s.statement_type for s in node.not_on_exception] == ["DISPLAY"]

    def test_shamrice_xml_generate_sample_is_clean(self):
        source = open(
            "examples/cobol/shamrice/xml_generate.cbl", encoding="utf-8"
        ).read()
        result = parse_cobol(source)
        assert not any("SUPPRESS" in w for w in result.warnings), result.warnings
        assert not any("Unparsed tokens" in w for w in result.warnings), result.warnings


# ---------------------------------------------------------------------------
# 8. Clause-level gaps from the NIST sweep
# ---------------------------------------------------------------------------


class TestClauseLevelGaps:
    def test_set_multi_group(self):
        result = _parse("SET     SW-1 TO ON", "        SW-2 TO OFF.")
        _clean(result)
        stmt = _main(result)[0]
        assert stmt.targets == ["SW-1"]
        assert stmt.value == "ON"
        assert stmt.groups == [
            {
                "targets": ["SW-2"],
                "set_type": "TO",
                "value": "OFF",
                "value_is_address_of": False,
                "value_is_entry": False,
            }
        ]
        assert stmt.operands == ["SW-1", "ON", "SW-2", "OFF"]
        assert stmt.to_dict()["groups"] == stmt.groups

    def test_set_index_multi_group(self):
        result = _parse("SET WS-I TO 1 WS-I UP BY 2.")
        _clean(result)
        stmt = _main(result)[0]
        assert stmt.set_type == "TO" and stmt.value == "1"
        assert stmt.groups[0]["set_type"] == "UP_BY"
        assert stmt.groups[0]["value"] == "2"

    @pytest.mark.parametrize(
        "source,field",
        [
            ("OPEN OUTPUT F1 WITH NO REWIND.", "no_rewind"),
            ("OPEN INPUT F1 NO REWIND.", "no_rewind"),
            ("OPEN INPUT F1 REVERSED.", "reversed"),
            ("OPEN I-O F1 WITH LOCK.", "with_lock"),
        ],
    )
    def test_open_options(self, source, field):
        result = _parse(source)
        _clean(result)
        stmt = _main(result)[0]
        assert stmt.file_names == ["F1"]
        assert stmt.to_dict()[field] is True

    @pytest.mark.parametrize(
        "source,field",
        [
            ("CLOSE F1 LOCK.", "with_lock"),
            ("CLOSE F1 NO REWIND.", "no_rewind"),
            ("CLOSE F1 WITH LOCK.", "with_lock"),
        ],
    )
    def test_close_bare_options(self, source, field):
        result = _parse(source)
        _clean(result)
        stmt = _main(result)[0]
        assert stmt.file_names == ["F1"]
        assert stmt.to_dict()["close_options"]["F1"][field] is True

    def test_perform_identifier_times_inline(self):
        result = _parse("PERFORM WS-N TIMES ADD 1 TO WS-A END-PERFORM.")
        _clean(result)
        stmt = _main(result)[0]
        assert stmt.times_count == "WS-N"
        assert _types(stmt.inline_statements) == ["AddStatement"]

    def test_perform_with_test_after_varying_inline(self):
        result = _parse(
            "PERFORM WITH TEST AFTER VARYING WS-A FROM 1 BY 1",
            "    UNTIL WS-A > 3 ADD 1 TO WS-N END-PERFORM.",
        )
        _clean(result)
        stmt = _main(result)[0]
        assert stmt.test_timing == "AFTER"
        assert stmt.varying_clause is not None
        assert _types(stmt.inline_statements) == ["AddStatement"]

    def test_perform_bare_test_before(self):
        result = _parse("PERFORM FAIL THRU FAIL TEST BEFORE", "    UNTIL WS-B = 'Y'.")
        _clean(result)
        stmt = _main(result)[0]
        assert stmt.test_timing == "BEFORE"
        assert stmt.until_condition is not None

    def test_perform_section_qualified_target(self):
        result = _parse("PERFORM FAIL OF MAIN-SECTION.")
        _clean(result)
        stmt = _main(result)[0]
        assert stmt.target_paragraph == "FAIL"
        assert stmt.metadata["target_qualifier"] == "MAIN-SECTION"

    @pytest.mark.parametrize(
        "source,condition",
        [
            ("START F1 KEY IS = WS-B INVALID KEY MOVE 'E' TO WS-B END-START.", "="),
            ("START F1 KEY IS >= WS-B INVALID KEY MOVE 'E' TO WS-B.", ">="),
            ("START F1 KEY > WS-B.", ">"),
            ("START F1 KEY GREATER OR EQUAL TO WS-B.", "GREATER OR EQUAL TO"),
        ],
    )
    def test_start_key_conditions(self, source, condition):
        result = _parse(source)
        _clean(result)
        stmt = _main(result)[0]
        assert stmt.key_condition == condition
        assert stmt.key_name == "WS-B"
        assert _types(_main(result)) == ["IOStartStatement"]

    def test_display_qualified_and_small_numeric_items(self):
        result = _parse("DISPLAY WS-E OF WS-T, 21 SPACES 1325.")
        _clean(result)
        assert _main(result)[0].operands == ["WS-E OF WS-T", "21", "SPACES", "1325"]

    def test_read_key_is_after_with_lock(self):
        result = _parse(
            "READ F1 WITH LOCK KEY IS WS-B INVALID KEY DISPLAY 'N'", "END-READ."
        )
        _clean(result)
        stmt = _main(result)[0]
        assert stmt.key_name == "WS-B"
        assert _types(stmt.invalid_key_clause) == ["DisplayStatement"]

    def test_accept_subscripted_target_and_message_count(self):
        result = _parse("ACCEPT WS-E (2).", "ACCEPT WS-T MESSAGE COUNT.")
        _clean(result)
        first, second = _main(result)[:2]
        assert first.target == "WS-E ( 2 )"
        assert second.from_source == "MESSAGE COUNT"

    def test_call_using_numeric_literal_subscript_and_address_of(self):
        result = _parse(
            "CALL 'X' USING BY VALUE 100 BY REFERENCE ADDRESS OF WS-B",
            "    WS-E (2).",
        )
        _clean(result)
        call = _main(result)[0]
        assert [p["name"] for p in call.to_dict()["using_parameters"]] == [
            "100",
            "ADDRESS OF WS-B",
            "WS-E ( 2 )",
        ]

    def test_stop_figurative_constant(self):
        result = _parse("STOP ZERO.")
        _clean(result)
        assert _main(result)[0].stop_type == "ZERO"

    def test_alter_multi_group_with_qualifiers(self):
        result = _parse(
            "ALTER FAIL TO PROCEED TO MAIN-PARA,",
            "    MAIN-PARA IN MAIN-SEC TO PROCEED TO FAIL OF MAIN-SEC.",
        )
        _clean(result)
        stmt = _main(result)[0]
        assert [(a["from_paragraph"], a["to_paragraph"]) for a in stmt.alterations] == [
            ("FAIL", "MAIN-PARA"),
            ("MAIN-PARA", "FAIL"),
        ]


# ---------------------------------------------------------------------------
# Corpus-level guard
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "examples/cobol/RL110A.CBL",  # READ ... END (no AT)
        "examples/cobol/NC107A.CBL",  # GO TO across newline; ; ELSE
        "examples/cobol/NC126A.CBL",  # IF TB-25 EQUAL TO "IF"
        "examples/cobol/NC174A.CBL",  # multi-group SET
        "examples/cobol/NC204M.CBL",  # DISPLAY qualified items, ACCEPT OF
        "examples/cobol/NC208A.CBL",  # PERFORM x OF section
        "examples/cobol/IC201A.CBL",  # USING ...; ON OVERFLOW
        "examples/cobol/IC222A.CBL",  # ADD inside handler before NOT ON EXCEPTION
        "examples/cobol/IC235A.CBL",  # USING subscripted argument
        "examples/cobol/IX208A.CBL",  # START KEY IS = / >
        "examples/cobol/RL205A.CBL",  # KEY GREATER OR EQUAL
        "examples/cobol/SQ203A.CBL",  # READ ; AT END
        "examples/cobol/SQ128A.CBL",  # CLOSE F1, F2, F3
        "examples/cobol/OBSQ3A.CBL",  # OPEN/CLOSE WITH NO REWIND
        "examples/cobol/OBNC1M.CBL",  # STOP ZERO / STOP QUOTE
        "examples/cobol/CM101M.CBL",  # Communication Module
        "examples/cobol/CM102M.CBL",
        "examples/cobol/RW101A.CBL",  # Report Writer INITIATE/TERMINATE
        "examples/cobol/NC303M.CBL",  # ALTER a TO ..., b TO ...
        "examples/cobol/SM208A.CBL",  # PERFORM WITH TEST AFTER VARYING
    ],
)
def test_nist_program_has_no_statement_drop_warnings(path):
    source = open(path, encoding="utf-8", errors="replace").read()
    result = parse_cobol(source, filename=path)
    drops = [
        w
        for w in result.warnings
        if "Unsupported statement" in w or "Unparsed tokens" in w
    ]
    assert drops == []
