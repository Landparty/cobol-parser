"""Invariant tests for the PROCEDURE DIVISION statement-parser registration order.

``cobolparser/parsers/divisions/procedure_registry.py`` documents that
``create_statement_registry()`` populates a first-match registry where order
is significant by design: more specific parsers (the IBM EXEC extensions,
which share a leading ``EXEC`` token) must be registered ahead of more
general ones. Nothing previously verified that invariant automatically -- a
future contributor could insert or reorder a registration incorrectly and
the mistake would only surface as a subtly wrong AST at runtime, never as a
test failure.

These tests pin the registration order against the production registry and
verify that every registered parser still claims its own keyword when
dispatched through ``create_statement_registry()``. A misordered or
shadowing registration fails one of these tests immediately instead of
silently mis-parsing at runtime.
"""

import pytest

from cobolparser.core.token_stream import TokenStream
from cobolparser.lexer import Token, TokenType
from cobolparser.models.ast_base import SourceLocation
from cobolparser.parsers.divisions.procedure_registry import create_statement_registry
from cobolparser.parsers.statements import (
    AcceptStatementParser,
    AddStatementParser,
    AlterStatementParser,
    CallStatementParser,
    CancelStatementParser,
    CloseStatementParser,
    CommitStatementParser,
    ComputeStatementParser,
    ContinueStatementParser,
    DeleteStatementParser,
    DisplayStatementParser,
    DivideStatementParser,
    EntryStatementParser,
    EvaluateStatementParser,
    ExecCicsStatementParser,
    ExecImsStatementParser,
    ExecSqlStatementParser,
    ExitStatementParser,
    GenerateStatementParser,
    GobackStatementParser,
    GoStatementParser,
    IfStatementParser,
    InitializeStatementParser,
    InspectStatementParser,
    MergeStatementParser,
    MoveStatementParser,
    MultiplyStatementParser,
    OpenStatementParser,
    PerformStatementParser,
    ReadStatementParser,
    ReleaseStatementParser,
    ReturnStatementParser,
    RewriteStatementParser,
    RollbackStatementParser,
    SearchStatementParser,
    SetStatementParser,
    SortStatementParser,
    StartStatementParser,
    StringStatementParser,
    SubtractStatementParser,
    UnlockStatementParser,
    UnstringStatementParser,
    UseStatementParser,
    XmlJsonStatementParser,
)
from cobolparser.parsers.statements.stop_parser import StopStatementParser
from cobolparser.parsers.statements.write_parser import WriteStatementParser

# Mirrors the exact registration order in
# create_statement_registry() (cobolparser/parsers/divisions/procedure_registry.py).
#
# This list IS the invariant under test. Adding, removing, or reordering a
# registration in procedure_registry.py must be accompanied by a deliberate
# update here -- that friction is the point: it converts a silent ordering
# mistake into a reviewed, intentional change.
EXPECTED_ORDER = [
    ExecSqlStatementParser,
    ExecCicsStatementParser,
    ExecImsStatementParser,
    XmlJsonStatementParser,
    IfStatementParser,
    PerformStatementParser,
    EvaluateStatementParser,
    DisplayStatementParser,
    MoveStatementParser,
    CallStatementParser,
    StopStatementParser,
    EntryStatementParser,
    GoStatementParser,
    ExitStatementParser,
    ContinueStatementParser,
    GobackStatementParser,
    AcceptStatementParser,
    ReadStatementParser,
    OpenStatementParser,
    CloseStatementParser,
    RewriteStatementParser,
    DeleteStatementParser,
    StartStatementParser,
    WriteStatementParser,
    UnlockStatementParser,
    InitializeStatementParser,
    SetStatementParser,
    StringStatementParser,
    UnstringStatementParser,
    InspectStatementParser,
    SearchStatementParser,
    SortStatementParser,
    MergeStatementParser,
    ReleaseStatementParser,
    ReturnStatementParser,
    ComputeStatementParser,
    AddStatementParser,
    SubtractStatementParser,
    MultiplyStatementParser,
    DivideStatementParser,
    AlterStatementParser,
    CancelStatementParser,
    GenerateStatementParser,
    UseStatementParser,
    CommitStatementParser,
    RollbackStatementParser,
]

# (case label, [(TokenType, value), ...] tokens matches() actually inspects,
# parser class that must claim them) -- one entry per parser registered by
# create_statement_registry(). Most verbs are single-token; the EXEC family
# and XML/JSON need a second token because their matches() disambiguates on
# lookahead rather than on the first token alone.
DISPATCH_CASES = [
    (
        "EXEC SQL",
        [(TokenType.EXEC, "EXEC"), (TokenType.SQL, "SQL")],
        ExecSqlStatementParser,
    ),
    (
        "EXEC CICS",
        [(TokenType.EXEC, "EXEC"), (TokenType.CICS, "CICS")],
        ExecCicsStatementParser,
    ),
    (
        "EXEC IMS",
        [(TokenType.EXEC, "EXEC"), (TokenType.IDENTIFIER, "IMS")],
        ExecImsStatementParser,
    ),
    (
        "EXEC DLI",
        [(TokenType.EXEC, "EXEC"), (TokenType.IDENTIFIER, "DLI")],
        ExecImsStatementParser,
    ),
    (
        "XML GENERATE",
        [(TokenType.IDENTIFIER, "XML"), (TokenType.IDENTIFIER, "GENERATE")],
        XmlJsonStatementParser,
    ),
    (
        "JSON PARSE",
        [(TokenType.IDENTIFIER, "JSON"), (TokenType.IDENTIFIER, "PARSE")],
        XmlJsonStatementParser,
    ),
    ("IF", [(TokenType.IF, "IF")], IfStatementParser),
    ("PERFORM", [(TokenType.PERFORM, "PERFORM")], PerformStatementParser),
    ("EVALUATE", [(TokenType.EVALUATE, "EVALUATE")], EvaluateStatementParser),
    ("DISPLAY", [(TokenType.DISPLAY, "DISPLAY")], DisplayStatementParser),
    ("MOVE", [(TokenType.MOVE, "MOVE")], MoveStatementParser),
    ("CALL", [(TokenType.CALL, "CALL")], CallStatementParser),
    ("STOP", [(TokenType.STOP, "STOP")], StopStatementParser),
    ("ENTRY", [(TokenType.ENTRY, "ENTRY")], EntryStatementParser),
    ("GO", [(TokenType.GO, "GO")], GoStatementParser),
    ("EXIT", [(TokenType.EXIT, "EXIT")], ExitStatementParser),
    ("CONTINUE", [(TokenType.CONTINUE, "CONTINUE")], ContinueStatementParser),
    ("GOBACK", [(TokenType.GOBACK, "GOBACK")], GobackStatementParser),
    ("ACCEPT", [(TokenType.ACCEPT, "ACCEPT")], AcceptStatementParser),
    ("READ", [(TokenType.READ, "READ")], ReadStatementParser),
    ("OPEN", [(TokenType.OPEN, "OPEN")], OpenStatementParser),
    ("CLOSE", [(TokenType.CLOSE, "CLOSE")], CloseStatementParser),
    ("REWRITE", [(TokenType.REWRITE, "REWRITE")], RewriteStatementParser),
    ("DELETE", [(TokenType.DELETE, "DELETE")], DeleteStatementParser),
    ("START", [(TokenType.START, "START")], StartStatementParser),
    ("WRITE", [(TokenType.WRITE, "WRITE")], WriteStatementParser),
    ("UNLOCK", [(TokenType.UNLOCK, "UNLOCK")], UnlockStatementParser),
    ("INITIALIZE", [(TokenType.INITIALIZE, "INITIALIZE")], InitializeStatementParser),
    ("SET", [(TokenType.SET, "SET")], SetStatementParser),
    ("STRING", [(TokenType.STRING, "STRING")], StringStatementParser),
    ("UNSTRING", [(TokenType.UNSTRING, "UNSTRING")], UnstringStatementParser),
    ("INSPECT", [(TokenType.INSPECT, "INSPECT")], InspectStatementParser),
    ("SEARCH", [(TokenType.SEARCH, "SEARCH")], SearchStatementParser),
    ("SORT", [(TokenType.SORT, "SORT")], SortStatementParser),
    ("MERGE", [(TokenType.MERGE, "MERGE")], MergeStatementParser),
    ("RELEASE", [(TokenType.RELEASE, "RELEASE")], ReleaseStatementParser),
    ("RETURN", [(TokenType.RETURN, "RETURN")], ReturnStatementParser),
    ("COMPUTE", [(TokenType.COMPUTE, "COMPUTE")], ComputeStatementParser),
    ("ADD", [(TokenType.ADD, "ADD")], AddStatementParser),
    ("SUBTRACT", [(TokenType.SUBTRACT, "SUBTRACT")], SubtractStatementParser),
    ("MULTIPLY", [(TokenType.MULTIPLY, "MULTIPLY")], MultiplyStatementParser),
    ("DIVIDE", [(TokenType.DIVIDE, "DIVIDE")], DivideStatementParser),
    ("ALTER", [(TokenType.ALTER, "ALTER")], AlterStatementParser),
    ("CANCEL", [(TokenType.CANCEL, "CANCEL")], CancelStatementParser),
    ("GENERATE", [(TokenType.GENERATE, "GENERATE")], GenerateStatementParser),
    ("USE", [(TokenType.USE, "USE")], UseStatementParser),
    ("COMMIT", [(TokenType.COMMIT, "COMMIT")], CommitStatementParser),
    ("ROLLBACK", [(TokenType.ROLLBACK, "ROLLBACK")], RollbackStatementParser),
]


def _stream(*specs: tuple[TokenType, str]) -> TokenStream:
    """Build a bare TokenStream from (TokenType, value) pairs.

    Only the tokens a parser's matches() probe actually inspects are
    needed -- dispatch never looks past what matches() reads.
    """
    tokens = [Token(t, v, SourceLocation(1, 1)) for t, v in specs]
    return TokenStream(tokens)


@pytest.fixture(scope="module")
def registry():
    """The production registry, built exactly as ProcedureDivisionParser does."""
    return create_statement_registry()


def test_registration_order_matches_documented_priority(registry):
    """create_statement_registry() must register parsers in EXPECTED_ORDER.

    This pins today's order so any future insertion, removal, or reordering
    in procedure_registry.py is caught here immediately, rather than only
    changing which parser wins first-match for some statement at parse time.
    """
    actual_order = [type(p) for p in registry.get_all_parsers()]
    assert actual_order == EXPECTED_ORDER


@pytest.mark.parametrize(
    "label,specs,expected_cls", DISPATCH_CASES, ids=[c[0] for c in DISPATCH_CASES]
)
def test_registry_dispatches_each_verb_to_its_own_parser(
    registry, label, specs, expected_cls
):
    """Every registered parser must claim its own keyword(s) in the real registry.

    Run against the exact registry ProcedureDivisionParser uses in
    production. If a future registration is inserted in the wrong position
    -- shadowing a more specific parser with an overly broad one -- this
    fails with a wrong-class assertion instead of silently mis-parsing at
    runtime.
    """
    found = registry.find_parser(_stream(*specs))
    assert type(found) is expected_cls, (
        f"{label}: expected {expected_cls.__name__}, got "
        f"{type(found).__name__ if found else None}"
    )


def test_dispatch_cases_cover_every_registered_parser(registry):
    """Guard the guard: DISPATCH_CASES must not silently fall out of sync.

    If a parser is registered in production but has no corresponding case
    above, a shadowing bug involving that parser could slip through
    unnoticed. Fails loudly instead of by omission.
    """
    registered_classes = {type(p) for p in registry.get_all_parsers()}
    covered_classes = {cls for _, _, cls in DISPATCH_CASES}
    assert registered_classes == covered_classes
