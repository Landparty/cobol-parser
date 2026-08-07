"""Regression test: a DATA DIVISION `EXEC SQL ... END-EXEC` block (e.g. a
DCLGEN-style `EXEC SQL INCLUDE SQLCA END-EXEC`) must never be swallowed as
unrecognized clause tokens of a preceding, not-yet-terminated data item.

`DataDivisionParser._parse_section` (data.py) already recognizes a
top-level `EXEC SQL` block correctly -- but only when its section-level scan
loop sees the leading EXEC token *fresh*. If the immediately preceding data
item is missing its terminating period (a common real-world slip, especially
right before a COPY- or DCLGEN-inserted block), `DataItemClauseParser`'s
per-item clause dispatch loop (`data_clauses.py`) kept consuming tokens
looking for that item's period -- so EXEC / SQL / INCLUDE / SQLCA / END-EXEC
were each swallowed one at a time as "clause not fully supported" and the
whole SQL statement vanished from the AST (with only a spray of misleading
per-token warnings as a trace, e.g. a real-world case that surfaced this:
"parsed token 'EXEC' ... in data item 'ANONYMOUS-79-602' skipped").

Fixed by treating a leading `EXEC SQL` token pair as a data-item boundary in
the clause dispatch loop (same treatment as LEVEL_NUMBER / a division token):
break out without consuming, implicitly closing the dangling item and handing
the EXEC token back to the section-level loop so it parses the SQL block
normally.
"""

from cobolparser import parse_cobol

HEADER = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. EXECBOUNDREG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
"""

FOOTER = """\
       PROCEDURE DIVISION.
       MAIN-PARA.
           STOP RUN.
"""


def _parse(ws_source: str):
    return parse_cobol(HEADER + ws_source + FOOTER, filename="execboundreg.cbl")


class TestMissingPeriodDoesNotSwallowExecSql:
    def test_missing_period_before_exec_sql_include(self):
        source = (
            "       01  WS-DUMMY PIC X(5)\n"
            "           EXEC SQL\n"
            "               INCLUDE SQLCA\n"
            "           END-EXEC.\n"
            "       01  WS-FIELD PIC X(10).\n"
        )
        result = _parse(source)
        assert result.warnings == []

        sql_stmt = result.ast.find_first_by_type("ExecSQLStatement")
        assert sql_stmt is not None
        assert "SQLCA" in sql_stmt.sql_text

        # The dangling WS-DUMMY item and the following WS-FIELD item must
        # both still be present, undamaged by the EXEC SQL block sitting
        # between them.
        names = {
            item.name
            for item in result.ast.find_all_by_type("DataItem")
            if getattr(item, "name", None)
        }
        assert "WS-DUMMY" in names
        assert "WS-FIELD" in names

        # No phantom "ANONYMOUS-*" item should have absorbed the SQL tokens.
        assert not any(name.startswith("ANONYMOUS-") for name in names)

    def test_properly_terminated_exec_sql_still_works(self):
        """The already-working case (item properly terminated by a period
        before the EXEC SQL block) must keep working identically."""
        source = (
            "       01  WS-DUMMY PIC X(5).\n"
            "           EXEC SQL\n"
            "               INCLUDE SQLCA\n"
            "           END-EXEC.\n"
            "       01  WS-FIELD PIC X(10).\n"
        )
        result = _parse(source)
        assert result.warnings == []

        sql_stmt = result.ast.find_first_by_type("ExecSQLStatement")
        assert sql_stmt is not None
        assert "SQLCA" in sql_stmt.sql_text
