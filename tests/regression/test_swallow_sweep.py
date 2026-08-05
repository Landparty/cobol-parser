"""Generic sweep for the "statement swallows the next statement" bug class.

``parser.md``'s Silent-Drop Audit sections (2026-07-05 through 2026-07-09)
found the same defect shape in more than a dozen statement parsers, one at a
time, via manual repro: a statement with no trailing period, immediately
followed by another statement, has its trailing token-collection loop
over-consume into the next statement's tokens (or, for a scope-taking
statement like SEARCH/EVALUATE/IF, fails to stop at its own scope
terminator) -- silently erasing the following statement with
``result.success is True`` and often ``warnings == []``.

Every one of those fixes was found by hand-rolling "verb X, no period,
followed by a marker statement" and checking whether the marker survived.
This module formalizes that probe as a permanent, self-maintaining
regression: one minimal period-less snippet per statement parser registered
in :func:`create_statement_registry`, each followed by a canonical
``DISPLAY 'MARKER'.`` sentinel, asserting the sentinel always survives as
its own top-level statement. ``test_fixture_table_covers_every_registered_
parser`` fails loudly if a future statement parser is registered without a
matching fixture, so this sweep -- unlike the one-off audits above -- covers
new verbs automatically instead of waiting for the next manual sweep.

Oracle detail: survival is checked against ``CobolParagraph.statements``
(the flat, source-order list the PROCEDURE DIVISION parser appends to via
``add_statement()``), not the tree-wide ``CobolProgram.get_all_statements()``.
A swallowed marker is not deleted -- it is absorbed as a *child* of the
statement under test (folded into an expression string, or nested into a
THEN/WHEN/AT END body), and ``get_all_statements()`` deliberately recurses
into exactly those bodies (see its docstring), so it would still find the
marker and report a false pass. ``CobolParagraph.statements`` only records
the flat sequence of top-level statements PROCEDURE DIVISION parsing itself
produced, so a swallowed marker simply never appears there.
"""

from __future__ import annotations

import textwrap
from dataclasses import dataclass

import pytest

from cobolparser import parse_cobol
from cobolparser.parsers.divisions.procedure_registry import create_statement_registry

_TEST_PARAGRAPH = "SWEEP-PARA"

_ENV_DIVISION = """\
ENVIRONMENT DIVISION.
INPUT-OUTPUT SECTION.
FILE-CONTROL.
    SELECT SWEEP-FILE ASSIGN TO "SWEEPFILE"
        ORGANIZATION IS SEQUENTIAL.
"""

_FILE_SECTION = """\
FILE SECTION.
FD  SWEEP-FILE.
01  SWEEP-REC PIC X(80).
"""

_WORKING_STORAGE = """\
01  WS-A       PIC 9(4) VALUE 1.
01  WS-B       PIC 9(4) VALUE 2.
01  WS-C       PIC 9(4).
01  WS-VAR     PIC X(10) VALUE 'HELLO'.
01  WS-VAR2    PIC X(10).
01  WS-IDX     PIC 9(4) VALUE 1.
01  WS-COUNT   PIC 9(4).
01  WS-KEY     PIC X(4).
"""

# GO TO / PERFORM / ALTER need a target paragraph; harmless for everything
# else. Real COBOL doesn't require the target to precede the reference.
_TRAILER_PARAGRAPH = """\
OTHER-PARA.
    CONTINUE.
"""


@dataclass(frozen=True)
class Fixture:
    """One minimal, period-less snippet exercising a single statement parser."""

    node_type: str  # expected class name of the statement-under-test's own AST node
    snippet: str  # PROCEDURE DIVISION text, no trailing period, Area-B indented
    needs_file: bool = False  # whether the ENVIRONMENT/FILE SECTION scaffold is needed


# One entry per class registered in create_statement_registry(). Keyed by
# parser class name so the completeness guard below can diff it against the
# live registry.
FIXTURES: dict[str, Fixture] = {
    "ExecSqlStatementParser": Fixture(
        "ExecSQLStatement", "    EXEC SQL SELECT COUNT(*) FROM EMPLOYEE END-EXEC"
    ),
    "ExecCicsStatementParser": Fixture(
        "ExecCicsStatement", "    EXEC CICS RETURN TRANSID('EMP1') END-EXEC"
    ),
    "ExecImsStatementParser": Fixture(
        "ExecImsStatement", "    EXEC IMS GU EMPDB END-EXEC"
    ),
    "XmlJsonStatementParser": Fixture(
        "XmlJsonStatement", "    JSON GENERATE WS-VAR FROM WS-VAR2"
    ),
    "IfStatementParser": Fixture(
        "IfStatement", '    IF 1 = 1\n        DISPLAY "TRUE"\n    END-IF'
    ),
    "PerformStatementParser": Fixture("PerformStatement", "    PERFORM OTHER-PARA"),
    "EvaluateStatementParser": Fixture(
        "EvaluateStatement",
        "    EVALUATE WS-IDX\n"
        "        WHEN 1\n"
        '            DISPLAY "ONE"\n'
        "        WHEN OTHER\n"
        '            DISPLAY "OTHER"\n'
        "    END-EVALUATE",
    ),
    "DisplayStatementParser": Fixture("DisplayStatement", "    DISPLAY WS-VAR"),
    "MoveStatementParser": Fixture("MoveStatement", "    MOVE WS-VAR TO WS-VAR2"),
    "CallStatementParser": Fixture("CallStatement", '    CALL "SUBPROGRAM"'),
    "StopStatementParser": Fixture("StopStatement", "    STOP RUN"),
    "EntryStatementParser": Fixture("EntryStatement", "    ENTRY 'MAINENTRY'"),
    "GoStatementParser": Fixture("GoStatement", "    GO TO OTHER-PARA"),
    "ExitStatementParser": Fixture("ExitStatement", "    EXIT PROGRAM"),
    "ContinueStatementParser": Fixture("ContinueStatement", "    CONTINUE"),
    "EjectStatementParser": Fixture("EjectStatement", "    EJECT"),
    "GobackStatementParser": Fixture("GobackStatement", "    GOBACK"),
    "AcceptStatementParser": Fixture("IOAcceptStatement", "    ACCEPT WS-VAR"),
    "ReadStatementParser": Fixture(
        "IOReadStatement", "    READ SWEEP-FILE", needs_file=True
    ),
    "OpenStatementParser": Fixture(
        "IOOpenStatement", "    OPEN INPUT SWEEP-FILE", needs_file=True
    ),
    "CloseStatementParser": Fixture(
        "IOCloseStatement", "    CLOSE SWEEP-FILE", needs_file=True
    ),
    "RewriteStatementParser": Fixture(
        "IORewriteStatement",
        "    REWRITE SWEEP-REC FROM WS-VAR",
        needs_file=True,
    ),
    "DeleteStatementParser": Fixture(
        "IODeleteStatement", "    DELETE SWEEP-FILE", needs_file=True
    ),
    "StartStatementParser": Fixture(
        "IOStartStatement",
        "    START SWEEP-FILE KEY IS EQUAL TO WS-KEY",
        needs_file=True,
    ),
    "WriteStatementParser": Fixture(
        "IOWriteStatement",
        "    WRITE SWEEP-REC FROM WS-VAR",
        needs_file=True,
    ),
    "UnlockStatementParser": Fixture(
        "IOUnlockStatement", "    UNLOCK SWEEP-FILE", needs_file=True
    ),
    "InitializeStatementParser": Fixture(
        "InitializeStatement", "    INITIALIZE WS-VAR"
    ),
    "SetStatementParser": Fixture("SetStatement", "    SET WS-IDX TO 1"),
    "StringStatementParser": Fixture(
        "StringStatement",
        "    STRING WS-VAR DELIMITED BY SPACE\n        INTO WS-VAR2",
    ),
    "UnstringStatementParser": Fixture(
        "UnstringStatement",
        "    UNSTRING WS-VAR DELIMITED BY SPACE\n        INTO WS-VAR2",
    ),
    "InspectStatementParser": Fixture(
        "InspectStatement",
        "    INSPECT WS-VAR TALLYING WS-COUNT\n        FOR ALL 'A'",
    ),
    "SearchStatementParser": Fixture(
        "SearchStatement",
        "    SEARCH WS-VAR\n"
        "        WHEN WS-IDX = 1\n"
        '            DISPLAY "FOUND"\n'
        "    END-SEARCH",
    ),
    "SortStatementParser": Fixture(
        "SortStatement",
        "    SORT SORT-FILE ON ASCENDING KEY WS-KEY\n"
        "        USING SWEEP-FILE GIVING SWEEP-FILE",
        needs_file=True,
    ),
    "MergeStatementParser": Fixture(
        "MergeStatement",
        "    MERGE SORT-FILE ON ASCENDING KEY WS-KEY\n"
        "        USING SWEEP-FILE SWEEP-FILE GIVING SWEEP-FILE",
        needs_file=True,
    ),
    "ReleaseStatementParser": Fixture("ReleaseStatement", "    RELEASE SORT-REC"),
    "ReturnStatementParser": Fixture(
        "ReturnStatement",
        '    RETURN SORT-FILE AT END DISPLAY "EOF" END-RETURN',
        needs_file=True,
    ),
    "ComputeStatementParser": Fixture(
        "ComputeStatement", "    COMPUTE WS-C = WS-A + WS-B"
    ),
    # GIVING targets are subscripted deliberately: ADD/SUBTRACT/MULTIPLY/
    # DIVIDE's plain scalar-target forms don't exercise any loop a boundary
    # bug could trip (a single bare IDENTIFIER target is consumed in one
    # shot, no matter how the following-statement check is wired). The
    # shared `consume_optional_subscript` paren-tracking loop
    # (`_utils.py`), used by every arithmetic verb's GIVING clause, is where
    # parser.md's real historical swallow bugs lived (e.g. `ADD 1 TO A
    # GIVING RESULT (H, I, 1)` dropping the subscript) -- this shape is what
    # actually probes it.
    "AddStatementParser": Fixture(
        "AddStatement", "    ADD 1 TO WS-A GIVING WS-C (WS-IDX)"
    ),
    "SubtractStatementParser": Fixture(
        "SubtractStatement", "    SUBTRACT 1 FROM WS-B GIVING WS-C (WS-IDX)"
    ),
    "MultiplyStatementParser": Fixture(
        "MultiplyStatement", "    MULTIPLY WS-A BY WS-B GIVING WS-C (WS-IDX)"
    ),
    "DivideStatementParser": Fixture(
        "DivideStatement", "    DIVIDE WS-A INTO WS-B GIVING WS-C (WS-IDX)"
    ),
    "AlterStatementParser": Fixture(
        "AlterStatement", "    ALTER OTHER-PARA TO PROCEED TO OTHER-PARA"
    ),
    "CancelStatementParser": Fixture("CancelStatement", "    CANCEL 'SUBPROG'"),
    "GenerateStatementParser": Fixture("GenerateStatement", "    GENERATE DETAIL-LINE"),
    "UseStatementParser": Fixture(
        "UseStatement", "    USE AFTER STANDARD EXCEPTION PROCEDURE ON INPUT"
    ),
    "CommitStatementParser": Fixture("CommitStatement", "    COMMIT"),
    "RollbackStatementParser": Fixture("RollbackStatement", "    ROLLBACK WORK"),
}


def _program(fixture: Fixture) -> str:
    env = _ENV_DIVISION if fixture.needs_file else ""
    file_section = _FILE_SECTION if fixture.needs_file else ""
    return textwrap.dedent(f"""\
        IDENTIFICATION DIVISION.
        PROGRAM-ID. SWEEPTEST.
        {env}DATA DIVISION.
        {file_section}WORKING-STORAGE SECTION.
        {_WORKING_STORAGE}PROCEDURE DIVISION.
        {_TEST_PARAGRAPH}.
        {fixture.snippet}
            DISPLAY 'MARKER'.
        {_TRAILER_PARAGRAPH}""")


def _test_paragraph(ast):
    for para in ast.find_all_by_type("Paragraph"):
        if para.paragraph_name == _TEST_PARAGRAPH:
            return para
    raise AssertionError(f"{_TEST_PARAGRAPH} not found in parsed AST")


def _is_marker_display(stmt) -> bool:
    return type(stmt).__name__ == "DisplayStatement" and any(
        "MARKER" in item for item in getattr(stmt, "display_items", [])
    )


class TestFixtureTableCompleteness:
    """Guards the fixture table itself, not the parser."""

    def test_fixture_table_covers_every_registered_parser(self):
        registered = {
            type(p).__name__ for p in create_statement_registry().get_all_parsers()
        }
        fixtured = set(FIXTURES)
        missing = registered - fixtured
        stale = fixtured - registered
        assert not missing, (
            f"New statement parser(s) registered with no swallow-sweep fixture: "
            f"{sorted(missing)}. Add an entry to FIXTURES in "
            f"tests/regression/test_swallow_sweep.py."
        )
        assert not stale, (
            f"Fixture(s) reference statement parser(s) no longer registered: "
            f"{sorted(stale)}. Remove them from FIXTURES."
        )

    @pytest.mark.parametrize("parser_cls,fixture", sorted(FIXTURES.items()))
    def test_fixture_is_period_less(self, parser_cls, fixture):
        assert not fixture.snippet.rstrip().endswith("."), (
            f"{parser_cls}'s fixture ends with a period, which defeats the "
            f"whole point of this sweep -- it must exercise the period-less "
            f"boundary-detection path."
        )


@pytest.mark.parametrize("parser_cls,fixture", sorted(FIXTURES.items()))
def test_marker_survives_after(parser_cls, fixture):
    """DISPLAY 'MARKER'. must survive as its own top-level statement.

    A period-less snippet immediately followed by the marker is exactly the
    shape every bug in parser.md's Silent-Drop Audit sections shares: if the
    statement under test over-consumes (or fails to close its own scope),
    the marker is absorbed as a *child* of that statement instead of
    becoming SWEEP-PARA's next top-level statement, and disappears from
    ``CobolParagraph.statements``.
    """
    source = _program(fixture)
    result = parse_cobol(source, filename="swallow_sweep.cbl")

    assert result.ast is not None, (
        f"{parser_cls}: program failed to produce an AST at all "
        f"(errors={result.errors})"
    )
    paragraph = _test_paragraph(result.ast)
    statements = paragraph.statements

    assert len(statements) >= 2, (
        f"{parser_cls}: expected at least 2 top-level statements in "
        f"{_TEST_PARAGRAPH} (the statement under test + the MARKER "
        f"sentinel), got {[type(s).__name__ for s in statements]} -- the "
        f"marker was swallowed."
    )

    own_statement = statements[-2]
    assert type(own_statement).__name__ == fixture.node_type, (
        f"{parser_cls}: expected the statement immediately before the "
        f"marker to be a {fixture.node_type}, got "
        f"{type(own_statement).__name__} -- the statement under test may "
        f"not have parsed at all (silently skipped as unsupported)."
    )

    marker = statements[-1]
    assert _is_marker_display(marker), (
        f"{parser_cls}: last top-level statement in {_TEST_PARAGRAPH} is "
        f"{type(marker).__name__} ({getattr(marker, 'display_items', None)}), "
        f"not the MARKER DISPLAY -- it was swallowed by {fixture.node_type}."
    )


class TestHarnessDetectsSwallowing:
    """Canary proving the oracle above actually bites.

    Without this, a future change to ``CobolParagraph.add_statement`` or
    the PROCEDURE DIVISION dispatch loop could silently turn every case in
    ``test_marker_survives_after`` into a vacuous pass with nothing left to
    notice.
    """

    def test_missing_scope_terminator_is_caught(self):
        # Same IF fixture as above, but with END-IF removed: the marker
        # DISPLAY is legitimately absorbed into the THEN body instead of
        # becoming SWEEP-PARA's next top-level statement.
        source = textwrap.dedent(f"""\
            IDENTIFICATION DIVISION.
            PROGRAM-ID. SWEEPTEST.
            DATA DIVISION.
            WORKING-STORAGE SECTION.
            {_WORKING_STORAGE}PROCEDURE DIVISION.
            {_TEST_PARAGRAPH}.
                IF 1 = 1
                    DISPLAY "TRUE"
                DISPLAY 'MARKER'.
            """)
        result = parse_cobol(source, filename="swallow_sweep_canary.cbl")
        paragraph = _test_paragraph(result.ast)

        assert len(paragraph.statements) == 1
        assert type(paragraph.statements[0]).__name__ == "IfStatement"

    def test_fixture_table_guard_catches_a_missing_entry(self):
        registered = {
            type(p).__name__ for p in create_statement_registry().get_all_parsers()
        }
        incomplete = dict(FIXTURES)
        incomplete.pop(next(iter(incomplete)))
        assert registered - set(incomplete)
