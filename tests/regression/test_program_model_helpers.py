"""Regression tests for CobolProgram query helpers and ParseResult statistics.

Each class pins one defect found in the AST / public-API bug hunt:

* ``has_cics()`` / ``has_ims()`` / ``get_*_statements()`` matched
  ``statement_type == "EXEC-CICS"``, a spelling only the hand-built dialect
  nodes use -- the statement parser builds ``"EXEC CICS"`` / ``"EXEC IMS"``,
  so every real CICS / EXEC DLI program read as having none. The typed EXEC
  SQL subclasses (FETCH, DECLARE CURSOR, COMMIT) were likewise missed by
  ``get_sql_statements()``, and ``get_statistics()["statement_count"]`` left
  EXEC CICS / EXEC IMS out.
* ``find_statements_using_variable()`` matched by substring.
* ``get_intrinsic_function_usages()`` reported ``OF`` for ``DLI-FUNCTION OF
  REC`` and words inside quoted literals.
"""

from pathlib import Path

from cobolparser import parse_cobol
from cobolparser.models.statements import CobolStatement

ENTERPRISE = Path(__file__).resolve().parents[1] / "samples" / "enterprise"


def _parse_sample(name: str):
    result = parse_cobol((ENTERPRISE / name).read_text(), name)
    assert result.ast is not None
    return result.ast


class TestExecStatementHelpers:
    def test_parsed_cics_program_has_cics(self):
        ast = _parse_sample("CICSONLN.cbl")
        cics = ast.get_cics_statements()
        assert ast.has_cics() is True
        assert len(cics) == 12
        assert all(s.node_type == "EXEC_CICS" for s in cics)
        assert ast.has_sql() is False
        assert ast.has_ims() is False

    def test_parsed_exec_dli_program_has_ims(self):
        ast = _parse_sample("EXECDLI.cbl")
        assert ast.has_ims() is True
        assert len(ast.get_ims_statements()) == 9
        assert ast.has_cics() is False

    def test_typed_sql_subclasses_are_sql_statements(self):
        ast = _parse_sample("DB2BATCH.cbl")
        kinds = {type(s).__name__ for s in ast.get_sql_statements()}
        assert {"ExecSQLStatement", "FetchStatement"} <= kinds
        assert "TransactionControlStatement" in kinds
        assert len(ast.get_sql_statements()) == 12

    def test_statement_count_includes_exec_cics(self):
        ast = _parse_sample("CICSCHNL.cbl")
        in_tree = [
            n for n in ast.traverse_depth_first() if isinstance(n, CobolStatement)
        ]
        assert ast.get_statistics()["statement_count"] == len(in_tree)


_VARS_SOURCE = """\
IDENTIFICATION DIVISION.
PROGRAM-ID. VARS.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 WS-A PIC 9.
01 WS-AMOUNT PIC 9.
01 T1.
   05 X OCCURS 3 PIC 9.
PROCEDURE DIVISION.
    MOVE 1 TO WS-AMOUNT.
    MOVE 2 TO WS-A.
    DISPLAY 'WS-A'.
    MOVE ws-a TO X(WS-A).
    STOP RUN.
"""


class TestFindStatementsUsingVariable:
    def test_whole_word_match_only(self):
        ast = parse_cobol(_VARS_SOURCE, free_form=True).ast
        found = ast.find_statements_using_variable("WS-A")
        assert [s.location.line for s in found] == [11, 13]

    def test_short_name_does_not_match_inside_longer_names(self):
        ast = parse_cobol(_VARS_SOURCE, free_form=True).ast
        assert ast.find_statements_using_variable("A") == []
        assert ast.find_statements_using_variable("") == []
