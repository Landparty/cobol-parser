"""Regression tests for the 2026-07-08 "silent drips and gaps" audit.

Pins fixes for:

- SORT/MERGE: the "remaining clauses" loop's ``else: consume()`` fallback
  swallowed a following un-punctuated statement one token at a time (same bug
  class as the INSPECT/STRING/UNSTRING fix in tier2, but SORT/MERGE were
  missed).
- ENTRY: the USING-parameter loop's fallback branch accepted any token
  (including a following statement's verb and operands) as a parameter.
- CALL: an unsupported verb inside ON EXCEPTION / NOT ON EXCEPTION / ON
  OVERFLOW was dropped with no warning, unlike the identical verb at the top
  level of PROCEDURE DIVISION (audit C2).
"""

from cobolparser import CobolParser, ErrorRecoveryMode

PROG_TEMPLATE = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. PROBE.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-X PIC X(10).
       01 WORK-FILE ASSIGN TO 'WORK'.
       PROCEDURE DIVISION.
       MAIN-PARA.
{proc}
           GOBACK.
"""


def _parse_proc(proc: str, mode: ErrorRecoveryMode = ErrorRecoveryMode.COLLECT_ALL):
    source = PROG_TEMPLATE.format(proc=proc)
    return CobolParser(error_recovery=mode).parse(source, filename="probe.cbl")


class TestSortDoesNotSwallowFollowingStatement:
    def test_sort_without_period_keeps_next_display(self):
        result = _parse_proc(
            "           SORT WORK-FILE ASCENDING KEY WS-X USING WORK-FILE "
            "GIVING WORK-FILE\n"
            "           DISPLAY 'DONE'."
        )
        types = [type(s).__name__ for s in result.ast.get_all_statements()]
        assert "SortStatement" in types
        assert "DisplayStatement" in types
        assert result.errors == []


class TestMergeDoesNotSwallowFollowingStatement:
    def test_merge_without_period_keeps_next_display(self):
        result = _parse_proc(
            "           MERGE WORK-FILE ASCENDING KEY WS-X USING WORK-FILE "
            "GIVING WORK-FILE\n"
            "           DISPLAY 'DONE'."
        )
        types = [type(s).__name__ for s in result.ast.get_all_statements()]
        assert "MergeStatement" in types
        assert "DisplayStatement" in types
        assert result.errors == []


class TestEntryUsingClauseDoesNotSwallowFollowingStatement:
    def test_entry_without_period_keeps_next_display(self):
        result = _parse_proc(
            "           ENTRY 'ALTENTRY' USING WS-X\n           DISPLAY 'DONE'."
        )
        entry = result.ast.get_all_statements()[0]
        types = [type(s).__name__ for s in result.ast.get_all_statements()]
        assert type(entry).__name__ == "EntryStatement"
        assert entry.using_parameters == ["WS-X"]
        assert "DisplayStatement" in types
        assert result.errors == []


class TestCallHandlerWarnsOnUnsupportedVerb:
    def test_unsupported_verb_in_on_exception_warns_and_is_dropped(self):
        result = _parse_proc(
            "           CALL 'SUB' USING WS-X\n"
            "              ON EXCEPTION\n"
            "                  INVOKE FOO 'bar'\n"
            "                  DISPLAY 'HANDLED'\n"
            "           END-CALL."
        )
        call = result.ast.get_all_statements()[0]
        handler_types = [type(s).__name__ for s in (call.on_exception or [])]
        assert handler_types == ["DisplayStatement"]
        assert any(
            "INVOKE" in w and "no parser is registered" in w for w in result.warnings
        )
        assert result.errors == []
