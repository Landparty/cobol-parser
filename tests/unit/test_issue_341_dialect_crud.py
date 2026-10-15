"""Regression tests for issue #341: dialect and CRUD-matrix gaps.

a) ``IBMEnterpriseCobol.validate_data_item`` warned on every *signed* COMP-3
   item (``S9(7)V99``) because it only accepted pictures starting with ``9``.
b) ``CICS_COMMANDS`` / ``IMS_COMMANDS`` lacked common commands and carried
   entries that are not commands (``NOHANDLE``; ``ENQUEUE`` / ``DEQUEUE`` /
   ``XDLT`` / ``XRPL``).
c) ``EXEC SQL TRUNCATE TABLE t`` parsed as ``UNKNOWN``, so the CRUD matrix
   gave the table no D (delete) mark.
"""

import pytest

from cobolparser import parse_cobol
from cobolparser.analysis.crud_matrix import CRUDMatrixGenerator
from cobolparser.dialects.ibm_enterprise import IBMDataItem, IBMEnterpriseCobol
from cobolparser.models.ast_base import SourceLocation
from cobolparser.models.data_items import PictureClause
from cobolparser.models.sql_statements import ExecSQLStatement, SQLStatementType

_LOC = SourceLocation(1, 1)


def _comp3_warnings(picture: str) -> list[str]:
    item = IBMDataItem("WS-A", 1, _LOC)
    item.picture_clause = PictureClause(picture, _LOC)
    item.usage = "COMP-3"
    return IBMEnterpriseCobol().validate_data_item(item)


class TestComp3NumericPicture:
    @pytest.mark.parametrize(
        "picture", ["S9(7)V99", "9(5)", "S9(5)", "V99", "SV9(3)", "9(3)PP", "s9v9"]
    )
    def test_numeric_pictures_do_not_warn(self, picture):
        assert _comp3_warnings(picture) == []

    @pytest.mark.parametrize("picture", ["X(5)", "S9(3)X", "A(4)", "Z(5)9", "9V9V9"])
    def test_non_numeric_pictures_still_warn(self, picture):
        assert _comp3_warnings(picture) == ["COMP-3 items should have numeric PICTURE"]


class TestCommandSets:
    @pytest.mark.parametrize(
        "command",
        [
            "READQ",
            "WRITEQ",
            "DELETEQ",
            "SYNCPOINT",
            "ENQ",
            "DEQ",
            "ASSIGN",
            "INQUIRE",
            "ADDRESS",
            "DUMP",
            "WAIT",
            "POST",
            "WEB",
            "INVOKE",
            "SIGNAL",
            "SPOOLOPEN",
            "QUERY",
        ],
    )
    def test_cics_commands_recognised(self, command):
        assert IBMEnterpriseCobol().is_cics_command(command) is True

    def test_nohandle_is_an_option_not_a_command(self):
        assert IBMEnterpriseCobol().is_cics_command("NOHANDLE") is False

    @pytest.mark.parametrize(
        "command",
        [
            "GHU",
            "GHN",
            "GHNP",
            "ROLL",
            "ROLS",
            "SETS",
            "SETU",
            "SYNC",
            "CHNG",
            "CMD",
            "GCMD",
            "INQY",
            "LOG",
            "STAT",
        ],
    )
    def test_ims_calls_recognised(self, command):
        assert IBMEnterpriseCobol().is_ims_command(command) is True

    @pytest.mark.parametrize("command", ["ENQUEUE", "DEQUEUE", "XDLT", "XRPL"])
    def test_non_dli_calls_rejected(self, command):
        assert IBMEnterpriseCobol().is_ims_command(command) is False


class TestTruncateTable:
    @pytest.mark.parametrize(
        ("sql", "table"),
        [
            ("TRUNCATE TABLE T15 IMMEDIATE", "T15"),
            ("TRUNCATE SCH.T16 REUSE STORAGE", "SCH.T16"),
        ],
    )
    def test_sql_type_and_table(self, sql, table):
        stmt = ExecSQLStatement(_LOC)
        stmt.set_sql_text(sql)
        assert stmt.sql_type == SQLStatementType.TRUNCATE
        assert stmt.tables == [table]

    def test_crud_matrix_marks_truncated_table_deleted(self):
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TRUNC.
       PROCEDURE DIVISION.
       MAIN-PARA.
           EXEC SQL TRUNCATE TABLE T15 IMMEDIATE END-EXEC
           STOP RUN.
"""
        result = parse_cobol(source)
        assert result.ast is not None
        matrix = CRUDMatrixGenerator().analyze(result.ast)
        crud = {e.table_name: e.crud.as_string() for e in matrix.table_entries}
        assert crud == {"T15": "---D"}
