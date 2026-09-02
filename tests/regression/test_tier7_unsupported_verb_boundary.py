"""Regression tests for the "period-less statement swallows an unsupported
verb" residual gap left open by the 2026-07-07 C2 silent-drop fix.

C2 (`reports/audit-2026-07-07.md`) taught the PROCEDURE DIVISION's top-level
statement dispatch loop to emit a ``ParseResult.warnings`` entry when it
encounters a verb with no registered statement parser
(``ProcedureDivisionParser._warn_unsupported_statement``). That loop only
*sees* the offending token directly when a period separates it from the
previous statement — a period hands control back to the loop at the right
place. When the previous statement has **no** trailing period, control never
returns to the top-level loop at that point: the previous statement's own
trailing-token-collection loop (MOVE's target list, DISPLAY's item list, the
arithmetic operand collector, ...) runs first and decides for itself whether
to keep consuming.

That decision is driven by :data:`cobolparser.parsers.statements._utils.
STATEMENT_TOKEN_TYPES` / ``STATEMENT_KEYWORDS`` (via ``is_statement_
boundary()`` or an equivalent inline check) — the single source of truth for
"does this token start a new statement, so I must stop here". Several verbs
that ``ProcedureDivisionParser._UNSUPPORTED_VERBS`` already knows how to
label (DISABLE, ENABLE, PURGE, RAISE, READY, RECEIVE, RESET, RESUME, SEND,
SERVICE, TRANSFORM) — plus EXECUTE/EXHIBIT/INVOKE, whose *string* was
present but whose lexer ``TokenType`` was not — were missing from those
sets. So a period-less statement's trailing loop never recognized the
following verb as a boundary and silently absorbed its tokens as bogus
operands, with ``result.success is True`` and ``warnings == []`` — a
"clean" parse that had quietly dropped an entire statement.

The same audit also turned up two adjacent, previously-undetected instances
of the identical gap:

- ``COMMIT``/``ROLLBACK`` *do* have registered parsers, yet were absent from
  both boundary sets — worse than the unsupported-verb case, since a
  **supported** statement vanished silently.
- ``CHAIN``, ``ENTER``, ``EXAMINE``, ``GOTO`` (the fused one-word spelling;
  ``GO TO`` two words is unaffected), ``INITIATE``, ``NOTE``, ``RECOVER``,
  ``SUPPRESS``, ``TERMINATE`` are real (mostly obsolete/Report-Writer) COBOL
  verbs with dedicated lexer ``TokenType``s and no registered parser, and
  were likewise missing.

``PURGE``/``RAISE``/``RESUME`` have no dedicated lexer ``TokenType`` at all —
they lex as plain ``IDENTIFIER``, indistinguishable from a data-name. Fixing
``STATEMENT_KEYWORDS`` closes the gap for parsers whose trailing loop already
consults it (MOVE, the arithmetic operand collector, ...), but several
*other* statement parsers collect an open-ended list of bare ``IDENTIFIER``
tokens without consulting ``STATEMENT_KEYWORDS``/``is_statement_boundary`` at
all -- these kept silently swallowing ``PURGE``/``RAISE``/``RESUME`` even
after the ``STATEMENT_KEYWORDS`` fix:

- ``DISPLAY`` items, ``CANCEL`` program names, ``SET`` targets, ``OPEN``/
  ``CLOSE`` file names, ``INITIALIZE`` targets -- the *main* parse loop never
  consulted the shared predicate at all (even where the module already
  imported it for an unrelated clause, e.g. ``INITIALIZE``/``INSPECT`` share
  a file).
- ``UNSTRING``'s ``INTO`` target list, ``SORT``/``MERGE``'s shared
  ``_parse_keys``/``_parse_file_list`` helpers, and ``INSPECT``'s
  ``_parse_tallying`` counter-name loop -- the statement's *main* loop
  already called ``is_statement_boundary()`` (2026-07-06/2026-07-08 fixes),
  but these are separate nested helper loops with their own hand-rolled
  boundary keyword lists (or, for ``_parse_tallying``, no boundary check at
  all) that predate/bypass that fix.

Each of those ten loops now breaks on ``is_statement_boundary(token)`` before
accepting a bare ``IDENTIFIER`` as a list item.

A related, more severe pre-existing bug (independent of the
``STATEMENT_KEYWORDS`` gaps above -- found by the same sweep) lived in
``PerformStatementParser._parse_until_condition_only`` (the out-of-line
``PERFORM paragraph-name UNTIL condition`` form, no inline body): its
condition-collection loop had **no boundary check whatsoever** except a
literal period or ``END-PERFORM``, so a period-less ``PERFORM ... UNTIL
cond`` swallowed *every* subsequent token into the condition string --
including entire well-formed statements like ``DISPLAY``/``STOP RUN``, not
just unsupported verbs. See ``TestPerformUntilConditionNoLongerSwallowsRest``.

Every case below reproduces with a period-less lead statement so the lead
statement's own trailing loop is the thing under test, not the top-level
dispatch loop (which already worked -- see the period-terminated control
assertions).

A fourth finding (same sweep, ``EvaluateStatementParser``) is not about a
missing trailing period at all: ``EvaluateStatement._parse_subjects`` (the
subject-list loop before the first ``WHEN``) had no boundary check, so a
malformed/period-less ``EVALUATE`` with no ``WHEN`` clause folded a following
verb straight into ``stmt.subjects`` as free text. Worse, the *outer* clause
loop that scans for ``WHEN``/``END-EVALUATE`` between clauses treated any
other token as noise to skip past -- so a malformed ``EVALUATE`` could
consume forward past entire intervening statements (a ``MOVE``, even a whole
second ``EVALUATE``) in search of a literal "WHEN" token, silently annexing
that second EVALUATE's own ``WHEN`` clause as if it belonged to the first,
with zero errors and zero warnings. Both loops now stop at
``STATEMENT_KEYWORDS`` membership, matching the missing-WHEN/missing-
END-EVALUATE errors that were already reported but previously arrived too
late to prevent the swallow. See
``TestEvaluateSubjectsAndClauseScanDoNotSwallowFollowingContent``.
"""

import pytest

from cobolparser import parse_cobol
from cobolparser.plugins.core import ErrorRecoveryMode

PROC_TEMPLATE = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. PROBE.
       PROCEDURE DIVISION.
       MAIN-PARA.
{proc}
"""


def _parse(proc: str):
    return parse_cobol(
        PROC_TEMPLATE.format(proc=proc),
        filename="probe.cbl",
        error_recovery=ErrorRecoveryMode.COLLECT_ALL,
    )


def _statement_types(result):
    para = result.ast.get_division("PROCEDURE").paragraphs[0]
    return [type(stmt).__name__ for stmt in para.statements]


# Verbs with no registered parser: previously vanished with zero warnings,
# now must produce a PARSE_WARNING and leave the MOVE's target list alone.
# NOTE: ALLOCATE, FREE, and INVOKE were originally listed here too -- they
# now have registered parsers (allocate_free_parsers.py, invoke_parser.py)
# and correctly produce NO warning; see TestInvokeAllocateFreeNoLongerSwallowed
# below, which mirrors TestCommitRollbackNoLongerSwallowed for them.
UNSUPPORTED_VERBS = [
    # 2026-09-02: every real COBOL verb formerly listed here (SEND, RECEIVE,
    # SERVICE, DISABLE, ENABLE, READY, RESET, TRANSFORM, EXHIBIT, PURGE,
    # RAISE, RESUME, CHAIN, ENTER, EXAMINE, INITIATE, NOTE, SUPPRESS,
    # TERMINATE) now has a registered parser -- see
    # TestFormerlyUnsupportedVerbsNowDispatch below. Only verb-shaped
    # reserved words with no statement behind them remain on this path.
    "EXECUTE",
    "GOTO",
    "RECOVER",
]

# (verb spelled as real syntax, expected statement class) for every verb that
# used to be on the list above and now dispatches to a node.
NOW_SUPPORTED_VERBS = [
    ("SEND WS-C", "SendStatement"),
    ("RECEIVE WS-C MESSAGE INTO WS-D", "ReceiveStatement"),
    ("SERVICE RELOAD WS-C", "ServiceStatement"),
    ("DISABLE INPUT WS-C", "DisableStatement"),
    ("ENABLE OUTPUT WS-C", "EnableStatement"),
    ("READY TRACE", "TraceStatement"),
    ("RESET TRACE", "TraceStatement"),
    ("TRANSFORM WS-C CHARACTERS FROM 'a' TO 'b'", "TransformStatement"),
    ("EXHIBIT NAMED WS-C", "ExhibitStatement"),
    ("PURGE WS-C", "PurgeStatement"),
    ("RAISE EXCEPTION EC-ALL", "RaiseStatement"),
    ("RESUME NEXT STATEMENT", "ResumeStatement"),
    ("CHAIN 'PROG' USING WS-C", "ChainStatement"),
    ("ENTER COBOL", "EnterStatement"),
    ("EXAMINE WS-C TALLYING ALL 'A'", "ExamineStatement"),
    ("INITIATE WS-C", "InitiateStatement"),
    ("NOTE THIS IS A COMMENT", "NoteStatement"),
    ("SUPPRESS PRINTING", "SuppressStatement"),
    ("TERMINATE WS-C", "TerminateStatement"),
]


class TestUnsupportedVerbNoLongerSwallowedByPeriodLessStatement:
    def test_period_terminated_layout_already_warns(self):
        """Control case: the previously-covered path still works."""
        result = _parse(
            "           MOVE WS-A TO WS-B.\n"
            "           EXECUTE WS-C.\n"
            "           STOP RUN."
        )
        assert result.warnings, "period-terminated case should already warn"
        assert any("EXECUTE" in w for w in result.warnings)
        move = next(
            s
            for s in result.ast.get_division("PROCEDURE").paragraphs[0].statements
            if type(s).__name__ == "MoveStatement"
        )
        assert move.to_dict()["targets"] == ["WS-B"]

    def test_all_unsupported_verbs_warn_after_period_less_statement(self):
        for verb in UNSUPPORTED_VERBS:
            result = _parse(
                f"           MOVE WS-A TO WS-B\n"
                f"           {verb} WS-C\n"
                f"           STOP RUN."
            )
            assert result.success
            assert result.warnings, f"{verb} should have produced a warning"
            assert any(
                verb in w for w in result.warnings
            ), f"{verb}: warnings were {result.warnings!r}"
            move = next(
                s
                for s in result.ast.get_division("PROCEDURE").paragraphs[0].statements
                if type(s).__name__ == "MoveStatement"
            )
            assert move.to_dict()["targets"] == ["WS-B"], (
                f"{verb}: MOVE swallowed the following verb's operand: "
                f"{move.to_dict()['targets']!r}"
            )


class TestFormerlyUnsupportedVerbsNowDispatch:
    """Every verb that used to be warned-and-discarded now produces its own
    node -- and, just as importantly, a period-less MOVE before it still
    stops at the verb instead of swallowing it as an extra target."""

    @pytest.mark.parametrize("source,node_type", NOW_SUPPORTED_VERBS)
    def test_verb_after_period_less_move_dispatches(self, source, node_type):
        result = _parse(
            f"           MOVE WS-A TO WS-B\n"
            f"           {source}\n"
            f"           STOP RUN."
        )
        assert result.success
        assert result.warnings == [], f"{source}: {result.warnings!r}"
        statements = result.ast.get_division("PROCEDURE").paragraphs[0].statements
        types = [type(s).__name__ for s in statements]
        assert node_type in types, f"{source}: {types!r}"
        move = next(s for s in statements if type(s).__name__ == "MoveStatement")
        assert move.to_dict()["targets"] == ["WS-B"]


class TestCommitRollbackNoLongerSwallowed:
    """COMMIT/ROLLBACK have registered parsers -- these must dispatch to a
    real CommitStatement/RollbackStatement node instead of vanishing."""

    def test_commit_after_period_less_move(self):
        result = _parse(
            "           MOVE WS-A TO WS-B\n"
            "           COMMIT\n"
            "           STOP RUN."
        )
        assert result.success
        assert result.warnings == []
        assert _statement_types(result) == [
            "MoveStatement",
            "CommitStatement",
            "StopStatement",
        ]
        move = result.ast.get_division("PROCEDURE").paragraphs[0].statements[0]
        assert move.to_dict()["targets"] == ["WS-B"]

    def test_rollback_after_period_less_move(self):
        result = _parse(
            "           MOVE WS-A TO WS-B\n"
            "           ROLLBACK\n"
            "           STOP RUN."
        )
        assert result.success
        assert result.warnings == []
        assert _statement_types(result) == [
            "MoveStatement",
            "RollbackStatement",
            "StopStatement",
        ]


class TestInvokeAllocateFreeNoLongerSwallowed:
    """ALLOCATE, FREE, and INVOKE have registered parsers -- these must
    dispatch to a real AllocateStatement/FreeStatement/InvokeStatement node
    instead of vanishing, mirroring TestCommitRollbackNoLongerSwallowed."""

    def test_invoke_after_period_less_move(self):
        result = _parse(
            "           MOVE WS-A TO WS-B\n"
            "           INVOKE WS-OBJ 'run'\n"
            "           STOP RUN."
        )
        assert result.success
        assert result.warnings == []
        assert _statement_types(result) == [
            "MoveStatement",
            "InvokeStatement",
            "StopStatement",
        ]
        move = result.ast.get_division("PROCEDURE").paragraphs[0].statements[0]
        assert move.to_dict()["targets"] == ["WS-B"]

    def test_allocate_after_period_less_move(self):
        result = _parse(
            "           MOVE WS-A TO WS-B\n"
            "           ALLOCATE WS-REC RETURNING WS-PTR\n"
            "           STOP RUN."
        )
        assert result.success
        assert result.warnings == []
        assert _statement_types(result) == [
            "MoveStatement",
            "AllocateStatement",
            "StopStatement",
        ]
        move = result.ast.get_division("PROCEDURE").paragraphs[0].statements[0]
        assert move.to_dict()["targets"] == ["WS-B"]

    def test_free_after_period_less_move(self):
        result = _parse(
            "           MOVE WS-A TO WS-B\n"
            "           FREE WS-PTR\n"
            "           STOP RUN."
        )
        assert result.success
        assert result.warnings == []
        assert _statement_types(result) == [
            "MoveStatement",
            "FreeStatement",
            "StopStatement",
        ]
        move = result.ast.get_division("PROCEDURE").paragraphs[0].statements[0]
        assert move.to_dict()["targets"] == ["WS-B"]


# Verbs with no dedicated lexer TokenType -- they lex as plain IDENTIFIER,
# so only a value-based (STATEMENT_KEYWORDS) boundary check can catch them.
IDENTIFIER_ONLY_VERBS = ["PURGE", "RAISE", "RESUME"]

# 2026-09-02: all three now have registered parsers (communication_parsers.py
# / exception_parsers.py), so the boundary fix is observed as "the verb gets
# its own node and the lead statement is unchanged" rather than as a warning.
IDENTIFIER_ONLY_VERB_NODES = {
    "PURGE": "PurgeStatement",
    "RAISE": "RaiseStatement",
    "RESUME": "ResumeStatement",
}

# (lead statement, template, expected AST node type name for the lead)
_IDENTIFIER_LOOP_CASES = [
    ("DISPLAY WS-A", "DisplayStatement"),
    ('CANCEL "PROGA"', "CancelStatement"),
    ("SET WS-A TO 1", "SetStatement"),
    ("OPEN INPUT FILE-A", "IOOpenStatement"),
    ("CLOSE FILE-A", "IOCloseStatement"),
    ("INITIALIZE WS-A", "InitializeStatement"),
    (
        "STRING WS-A WS-B DELIMITED BY SPACE INTO WS-C",
        "StringStatement",
    ),
    ("UNSTRING WS-S INTO WS-A WS-B", "UnstringStatement"),
    ("SORT SORT-FILE ASCENDING KEY WS-A WS-B", "SortStatement"),
    (
        "MERGE MERGE-FILE ASCENDING KEY WS-A WS-B USING IN-FILE",
        "MergeStatement",
    ),
    (
        "INSPECT WS-X TALLYING WS-CNT FOR ALL 'A'",
        "InspectStatement",
    ),
]


class TestIdentifierTypedVerbNotSwallowedByOpenEndedListLoops:
    """DISPLAY/CANCEL/SET/OPEN/CLOSE/INITIALIZE, and the UNSTRING INTO-target
    list, SORT/MERGE's shared _parse_keys/_parse_file_list helpers, and
    INSPECT's _parse_tallying counter-name loop, each collect an open-ended
    list of bare IDENTIFIER tokens (items / program names / targets / file
    names / key fields / counter names). Unlike MOVE and the arithmetic
    operand collector, none of these loops consulted STATEMENT_KEYWORDS at
    all (or -- for UNSTRING/SORT/MERGE/INSPECT -- had their own hand-rolled
    boundary keyword list, or no boundary check at all, bypassing the shared
    predicate the statement's outer loop already used), so PURGE/RAISE/RESUME
    (no dedicated TokenType -- indistinguishable from a data-name by type
    alone) kept being folded into the list even after STATEMENT_KEYWORDS
    gained their strings."""

    def test_identifier_only_verb_not_swallowed(self):
        for lead, expected_type in _IDENTIFIER_LOOP_CASES:
            for verb in IDENTIFIER_ONLY_VERBS:
                result = _parse(
                    f"           {lead}\n"
                    f"           {verb} WS-C\n"
                    f"           STOP RUN."
                )
                assert result.success
                assert result.warnings == [], f"{lead} + {verb}: {result.warnings!r}"
                types = _statement_types(result)
                assert types == [
                    expected_type,
                    IDENTIFIER_ONLY_VERB_NODES[verb],
                    "StopStatement",
                ], (
                    f"{lead} + {verb}: {verb} was folded into the lead "
                    f"statement instead of producing its own node "
                    f"(types={types!r})"
                )


class TestPerformUntilConditionNoLongerSwallowsRest:
    """PerformStatementParser._parse_until_condition_only (the out-of-line
    `PERFORM paragraph-name UNTIL condition` form) had no boundary check at
    all -- only a literal period or END-PERFORM stopped it. A period-less
    PERFORM ... UNTIL swallowed every remaining token in the program into the
    condition string, not just unsupported verbs."""

    def test_perform_until_does_not_swallow_a_normal_following_statement(self):
        result = _parse(
            "           PERFORM SOME-PARA UNTIL WS-A = WS-B\n"
            "           DISPLAY 'HELLO'\n"
            "           STOP RUN.\n"
            "       SOME-PARA.\n"
            "           DISPLAY 'X'."
        )
        assert result.success
        assert result.warnings == []
        para = result.ast.get_division("PROCEDURE").paragraphs[0]
        types = [type(stmt).__name__ for stmt in para.statements]
        assert types == ["PerformStatement", "DisplayStatement", "StopStatement"]
        perform = para.statements[0]
        assert perform.to_dict()["until_condition"]["operands"] == ["WS-A = WS-B"]

    def test_perform_until_does_not_swallow_unsupported_verb(self):
        for verb in IDENTIFIER_ONLY_VERBS:
            result = _parse(
                "           PERFORM SOME-PARA UNTIL WS-A = WS-B\n"
                f"           {verb} WS-C\n"
                "           STOP RUN.\n"
                "       SOME-PARA.\n"
                "           DISPLAY 'X'."
            )
            assert result.success
            assert result.warnings == [], f"{verb}: {result.warnings!r}"
            para = result.ast.get_division("PROCEDURE").paragraphs[0]
            types = [type(stmt).__name__ for stmt in para.statements]
            assert types == [
                "PerformStatement",
                IDENTIFIER_ONLY_VERB_NODES[verb],
                "StopStatement",
            ], f"{verb}: swallowed into the UNTIL condition (types={types!r})"


class TestEvaluateSubjectsAndClauseScanDoNotSwallowFollowingContent:
    """A malformed EVALUATE (missing its first WHEN) previously vacuumed
    forward with no boundary check at all -- both in `_parse_subjects` (the
    subject-list loop) and in the outer clause-scan loop that searches for
    WHEN/END-EVALUATE between clauses."""

    def test_subjects_loop_does_not_absorb_a_following_unsupported_verb(self):
        for verb in IDENTIFIER_ONLY_VERBS:
            result = _parse(
                "           EVALUATE WS-X\n"
                f"           {verb} WS-C\n"
                "           STOP RUN."
            )
            assert result.warnings == [], f"{verb}: {result.warnings!r}"
            statements = result.ast.get_division("PROCEDURE").paragraphs[0].statements
            assert IDENTIFIER_ONLY_VERB_NODES[verb] in [
                type(s).__name__ for s in statements
            ]
            evaluate = statements[0]
            assert evaluate.to_dict()["subjects"] == ["WS-X"], (
                f"{verb}: folded into EVALUATE subjects: "
                f"{evaluate.to_dict()['subjects']!r}"
            )

    def test_clause_scan_does_not_annex_a_later_unrelated_evaluate(self):
        """A malformed EVALUATE with no WHEN must not swallow an intervening
        MOVE and a second, well-formed EVALUATE while hunting for a WHEN
        token -- it must stop at the MOVE and report its own missing-WHEN
        error instead."""
        result = _parse(
            "           EVALUATE WS-X\n"
            "           MOVE 1 TO WS-Y\n"
            "           EVALUATE WS-Y\n"
            "               WHEN 1\n"
            "                   DISPLAY 'A'\n"
            "           END-EVALUATE\n"
            "           STOP RUN."
        )
        assert result.errors, "malformed EVALUATE should report a parse error"
        assert any("WHEN" in str(e) for e in result.errors)
        types = _statement_types(result)
        assert types == [
            "EvaluateStatement",
            "MoveStatement",
            "EvaluateStatement",
            "StopStatement",
        ], f"MOVE and/or the second EVALUATE were annexed: {types!r}"
        para = result.ast.get_division("PROCEDURE").paragraphs[0]
        first_evaluate, move, second_evaluate, _ = para.statements
        assert first_evaluate.to_dict()["subjects"] == ["WS-X"]
        assert first_evaluate.to_dict()["when_clauses"] == []
        assert move.to_dict()["targets"] == ["WS-Y"]
        assert len(second_evaluate.to_dict()["when_clauses"]) == 1
