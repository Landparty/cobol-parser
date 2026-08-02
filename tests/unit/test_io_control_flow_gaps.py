"""Regression tests for control-flow-corrupting IO statement gaps.

These pin three confirmed bugs where a conditional clause body (INVALID
KEY / NOT INVALID KEY / AT END-OF-PAGE / NOT AT END-OF-PAGE) failed to
parse and its imperative statements leaked out of the clause as
unconditional top-level statements in the enclosing paragraph -- silently
corrupting control flow for any downstream consumer (dead-code analysis,
program-flow analysis, CRUD matrix, IO sequence analysis), not just
losing data:

1. START ... KEY IS {GREATER|LESS} THAN OR EQUAL TO key-name dropped the
   trailing TO token, which blocked key-name / INVALID KEY / NOT INVALID
   KEY parsing entirely (start_parser.py).
2. WRITE ... AT END-OF-PAGE / NOT AT END-OF-PAGE was never implemented
   (write_parser.py, models/statements/io.py).
3. OPEN INPUT FILE-A OUTPUT FILE-B collapsed every file to the first
   mode group's mode, making FILE-B indistinguishable from an INPUT file
   to any consumer keyed off `.open_mode` (open_parser.py,
   models/statements/io.py).
"""

from cobolparser import parse_cobol


def _prog(procedure_stmts: str, extra_data: str = "", extra_env: str = "") -> str:
    return f"""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT WS-FILE ASSIGN TO 'X.DAT'
               ORGANIZATION IS INDEXED
               RECORD KEY IS WS-KEY.
{extra_env}
       DATA DIVISION.
       FILE SECTION.
       FD  WS-FILE.
       01  WS-RECORD.
           05 WS-KEY    PIC X(10).
       WORKING-STORAGE SECTION.
       01  WS-KEY2      PIC X(10).
       01  WS-SOURCE    PIC X(10).
{extra_data}
       PROCEDURE DIVISION.
       MAIN-PARA.
{procedure_stmts}
           STOP RUN.
    """


def _paragraph_statements(ast):
    proc = ast.procedure_division
    if proc.paragraphs:
        return proc.paragraphs[0].statements
    return proc.sections[0].paragraphs[0].statements


class TestStartKeyGreaterThanOrEqualTo:
    """Bug 1: START ... KEY IS GREATER THAN OR EQUAL TO key-name."""

    def test_invalid_key_clauses_populated_and_key_name_captured(self):
        result = parse_cobol(
            _prog(
                "           START WS-FILE KEY IS GREATER THAN OR EQUAL TO WS-KEY2\n"
                "               INVALID KEY DISPLAY 'NOT FOUND'\n"
                "               NOT INVALID KEY DISPLAY 'FOUND'\n"
                "           END-START."
            )
        )
        assert result.errors == []
        stmt = result.ast.find_statements("START_STATEMENT")[0]

        assert stmt.key_condition == "GREATER THAN OR EQUAL TO"
        assert stmt.key_name == "WS-KEY2"
        assert stmt.invalid_key_clause is not None
        assert [s.statement_type for s in stmt.invalid_key_clause] == ["DISPLAY"]
        assert stmt.not_invalid_key_clause is not None
        assert [s.statement_type for s in stmt.not_invalid_key_clause] == ["DISPLAY"]

    def test_display_bodies_do_not_leak_as_top_level_statements(self):
        result = parse_cobol(
            _prog(
                "           START WS-FILE KEY IS GREATER THAN OR EQUAL TO WS-KEY2\n"
                "               INVALID KEY DISPLAY 'NOT FOUND'\n"
                "               NOT INVALID KEY DISPLAY 'FOUND'\n"
                "           END-START."
            )
        )
        stmts = _paragraph_statements(result.ast)
        # Only the START and the trailing STOP RUN should appear at the
        # paragraph level -- the two DISPLAYs belong inside the clauses.
        assert [s.statement_type for s in stmts] == ["START_STATEMENT", "STOP"]

    def test_less_than_or_equal_to_variant(self):
        result = parse_cobol(
            _prog(
                "           START WS-FILE KEY IS LESS THAN OR EQUAL TO WS-KEY2\n"
                "           END-START."
            )
        )
        assert result.errors == []
        stmt = result.ast.find_statements("START_STATEMENT")[0]
        assert stmt.key_condition == "LESS THAN OR EQUAL TO"
        assert stmt.key_name == "WS-KEY2"

    def test_or_equal_without_trailing_to_still_works(self):
        """OR EQUAL with no trailing TO token (a real, distinct usage)."""
        result = parse_cobol(
            _prog("           START WS-FILE KEY IS GREATER THAN OR EQUAL WS-KEY2.")
        )
        assert result.errors == []
        stmt = result.ast.find_statements("START_STATEMENT")[0]
        assert stmt.key_condition == "GREATER THAN OR EQUAL"
        assert stmt.key_name == "WS-KEY2"

    def test_plain_greater_than_not_regressed(self):
        result = parse_cobol(
            _prog("           START WS-FILE KEY IS GREATER THAN WS-KEY2.")
        )
        assert result.errors == []
        stmt = result.ast.find_statements("START_STATEMENT")[0]
        assert stmt.key_condition == "GREATER THAN"
        assert stmt.key_name == "WS-KEY2"

    def test_not_less_than_not_regressed(self):
        result = parse_cobol(
            _prog("           START WS-FILE KEY IS NOT LESS THAN WS-KEY2.")
        )
        assert result.errors == []
        stmt = result.ast.find_statements("START_STATEMENT")[0]
        assert stmt.key_condition == "NOT LESS THAN"
        assert stmt.key_name == "WS-KEY2"

    def test_not_greater_than_not_regressed(self):
        result = parse_cobol(
            _prog("           START WS-FILE KEY IS NOT GREATER THAN WS-KEY2.")
        )
        assert result.errors == []
        stmt = result.ast.find_statements("START_STATEMENT")[0]
        assert stmt.key_condition == "NOT GREATER THAN"
        assert stmt.key_name == "WS-KEY2"


class TestWriteAtEndOfPage:
    """Bug 2: WRITE ... AT END-OF-PAGE / NOT AT END-OF-PAGE."""

    def test_eop_clauses_populated(self):
        result = parse_cobol(
            _prog(
                "           WRITE WS-RECORD FROM WS-SOURCE\n"
                "               AT END-OF-PAGE DISPLAY 'EOP'\n"
                "               NOT AT END-OF-PAGE DISPLAY 'NOT EOP'\n"
                "           END-WRITE."
            )
        )
        assert result.errors == []
        stmt = result.ast.find_statements("WRITE")[0]

        assert stmt.at_eop_clause is not None
        assert [s.statement_type for s in stmt.at_eop_clause] == ["DISPLAY"]
        assert stmt.not_at_eop_clause is not None
        assert [s.statement_type for s in stmt.not_at_eop_clause] == ["DISPLAY"]

    def test_display_bodies_do_not_leak_as_top_level_statements(self):
        result = parse_cobol(
            _prog(
                "           WRITE WS-RECORD FROM WS-SOURCE\n"
                "               AT END-OF-PAGE DISPLAY 'EOP'\n"
                "               NOT AT END-OF-PAGE DISPLAY 'NOT EOP'\n"
                "           END-WRITE."
            )
        )
        stmts = _paragraph_statements(result.ast)
        assert [s.statement_type for s in stmts] == ["WRITE", "STOP"]

    def test_eop_clause_serializes_in_to_dict(self):
        result = parse_cobol(
            _prog(
                "           WRITE WS-RECORD FROM WS-SOURCE\n"
                "               AT END-OF-PAGE DISPLAY 'EOP'\n"
                "           END-WRITE."
            )
        )
        stmt = result.ast.find_statements("WRITE")[0]
        d = stmt.to_dict()
        assert "at_eop_clause" in d
        assert len(d["at_eop_clause"]) == 1
        assert "not_at_eop_clause" in d

    def test_write_without_eop_clauses_not_regressed(self):
        result = parse_cobol(_prog("           WRITE WS-RECORD FROM WS-SOURCE."))
        assert result.errors == []
        stmt = result.ast.find_statements("WRITE")[0]
        assert stmt.at_eop_clause is None
        assert stmt.not_at_eop_clause is None
        assert stmt.record_name == "WS-RECORD"
        assert stmt.from_clause == "WS-SOURCE"

    def test_write_invalid_key_still_works(self):
        """Format 2 (INVALID KEY) branch must be unaffected by the EOP fix."""
        result = parse_cobol(
            _prog(
                "           WRITE WS-RECORD\n"
                "               INVALID KEY DISPLAY 'BAD'\n"
                "               NOT INVALID KEY DISPLAY 'OK'\n"
                "           END-WRITE."
            )
        )
        assert result.errors == []
        stmt = result.ast.find_statements("WRITE")[0]
        assert [s.statement_type for s in stmt.invalid_key_clause] == ["DISPLAY"]
        assert [s.statement_type for s in stmt.not_invalid_key_clause] == ["DISPLAY"]
        stmts = _paragraph_statements(result.ast)
        assert [s.statement_type for s in stmts] == ["WRITE", "STOP"]


class TestOpenMultipleModeGroups:
    """Bug 3: OPEN INPUT FILE-A OUTPUT FILE-B per-file mode tracking."""

    def _parse_two_file_open(self):
        code = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT FILE-A ASSIGN TO 'A.DAT'.
           SELECT FILE-B ASSIGN TO 'B.DAT'.
       DATA DIVISION.
       FILE SECTION.
       FD  FILE-A.
       01  REC-A PIC X(10).
       FD  FILE-B.
       01  REC-B PIC X(10).
       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT FILE-A OUTPUT FILE-B.
           STOP RUN.
        """
        return parse_cobol(code)

    def test_per_file_mode_distinguished(self):
        result = self._parse_two_file_open()
        assert result.errors == []
        stmt = result.ast.find_statements("OPEN")[0]

        assert stmt.file_names == ["FILE-A", "FILE-B"]
        assert stmt.file_modes["FILE-A"] == "INPUT"
        assert stmt.file_modes["FILE-B"] == "OUTPUT"
        # Backward-compat alias: first mode group.
        assert stmt.open_mode == "INPUT"

    def test_file_modes_serializes_in_to_dict(self):
        result = self._parse_two_file_open()
        stmt = result.ast.find_statements("OPEN")[0]
        d = stmt.to_dict()
        assert d["file_modes"] == {"FILE-A": "INPUT", "FILE-B": "OUTPUT"}
        assert d["file_names"] == ["FILE-A", "FILE-B"]

    def test_three_mode_groups(self):
        code = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT FILE-A ASSIGN TO 'A.DAT'.
           SELECT FILE-B ASSIGN TO 'B.DAT'.
           SELECT FILE-C ASSIGN TO 'C.DAT'.
       DATA DIVISION.
       FILE SECTION.
       FD  FILE-A.
       01  REC-A PIC X(10).
       FD  FILE-B.
       01  REC-B PIC X(10).
       FD  FILE-C.
       01  REC-C PIC X(10).
       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT FILE-A OUTPUT FILE-B EXTEND FILE-C.
           STOP RUN.
        """
        result = parse_cobol(code)
        stmt = result.ast.find_statements("OPEN")[0]
        assert stmt.file_modes == {
            "FILE-A": "INPUT",
            "FILE-B": "OUTPUT",
            "FILE-C": "EXTEND",
        }

    def test_single_mode_group_not_regressed(self):
        code = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT FILE-A ASSIGN TO 'A.DAT'.
           SELECT FILE-B ASSIGN TO 'B.DAT'.
       DATA DIVISION.
       FILE SECTION.
       FD  FILE-A.
       01  REC-A PIC X(10).
       FD  FILE-B.
       01  REC-B PIC X(10).
       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT FILE-A FILE-B.
           STOP RUN.
        """
        result = parse_cobol(code)
        assert result.errors == []
        stmt = result.ast.find_statements("OPEN")[0]
        assert stmt.open_mode == "INPUT"
        assert stmt.file_names == ["FILE-A", "FILE-B"]
        assert stmt.file_modes == {"FILE-A": "INPUT", "FILE-B": "INPUT"}
