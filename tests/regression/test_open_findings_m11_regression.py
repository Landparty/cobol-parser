"""Regression tests for open-findings M11: structured EXEC CICS/IMS/SQL capture.

Before the fix, ExecCicsStatement/ExecImsStatement only captured a command
name plus a flat joined-token text blob (no MAP/MAPSET/... fields), and
parse_exec_sql extracted only regex-level sql_type/host_variables/tables with
no SELECT-list or WHERE structure. These tests pin the new structured fields
and assert the pre-existing fields keep populating (backward compatibility).
"""

import textwrap

from cobolparser import parse_cobol
from cobolparser.models.ast_base import SourceLocation
from cobolparser.models.sql_statements import parse_exec_sql


def _program(procedure_body: str) -> str:
    return textwrap.dedent(f"""\
        IDENTIFICATION DIVISION.
        PROGRAM-ID. M11PROG.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01  WS-REC PIC X(80).
        PROCEDURE DIVISION.
        MAIN-PARA.
        {procedure_body}
            STOP RUN.
        """)


class TestM11ExecStructured:
    # ------------------------------------------------------------------
    # EXEC CICS
    # ------------------------------------------------------------------

    def test_cics_send_map_mapset_options_present(self):
        src = _program("    EXEC CICS SEND MAP('MAP1') MAPSET('SET1') END-EXEC.")
        result = parse_cobol(src, filename="m11.cbl")
        assert result.success

        node = result.ast.find_all_by_type("EXEC_CICS")[0]
        assert node.options["MAP"] == "MAP1"
        assert node.options["MAPSET"] == "SET1"
        # Structure exposed through to_dict as well.
        d = node.to_dict()
        assert d["options"]["MAP"] == "MAP1"
        assert d["options"]["MAPSET"] == "SET1"

    def test_cics_flag_options_are_none_valued(self):
        src = _program(
            "    EXEC CICS SEND MAP('M') MAPSET('S') ERASE NOHANDLE END-EXEC."
        )
        result = parse_cobol(src, filename="m11.cbl")
        assert result.success

        node = result.ast.find_all_by_type("EXEC_CICS")[0]
        assert "ERASE" in node.options
        assert node.options["ERASE"] is None
        assert "NOHANDLE" in node.options
        assert node.options["NOHANDLE"] is None

    def test_cics_nested_paren_argument(self):
        src = _program(
            "    EXEC CICS SEND FROM(WS-DATA(1:10)) LENGTH(WS-LEN) END-EXEC."
        )
        result = parse_cobol(src, filename="m11.cbl")
        assert result.success

        node = result.ast.find_all_by_type("EXEC_CICS")[0]
        assert node.options["FROM"] == "WS-DATA(1:10)"
        assert node.options["LENGTH"] == "WS-LEN"

    def test_cics_read_and_link_option_shapes(self):
        src = _program(
            "    EXEC CICS READ FILE('EMPFILE') INTO(WS-REC)\n"
            "        RIDFLD(WS-KEY) END-EXEC.\n"
            "    EXEC CICS LINK PROGRAM('SUBPROG') COMMAREA(WS-CA)\n"
            "        LENGTH(100) END-EXEC.\n"
            "    EXEC CICS RETURN TRANSID('TRN1') END-EXEC."
        )
        result = parse_cobol(src, filename="m11.cbl")
        assert result.success

        nodes = result.ast.find_all_by_type("EXEC_CICS")
        read = next(n for n in nodes if n.cics_command == "READ")
        assert read.options["FILE"] == "EMPFILE"
        assert read.options["INTO"] == "WS-REC"
        assert read.options["RIDFLD"] == "WS-KEY"
        link = next(n for n in nodes if n.cics_command == "LINK")
        assert link.options["PROGRAM"] == "SUBPROG"
        assert link.options["COMMAREA"] == "WS-CA"
        assert link.options["LENGTH"] == "100"
        ret = next(n for n in nodes if n.cics_command == "RETURN")
        assert ret.options["TRANSID"] == "TRN1"

    def test_cics_backward_compat_fields_still_populate(self):
        src = _program("    EXEC CICS SEND MAP('MAP1') MAPSET('SET1') ERASE END-EXEC.")
        result = parse_cobol(src, filename="m11.cbl")
        assert result.success

        node = result.ast.find_all_by_type("EXEC_CICS")[0]
        # Old fields unchanged.
        assert node.cics_command == "SEND"
        assert "MAP" in node.cics_text and "MAPSET" in node.cics_text
        d = node.to_dict()
        assert d["cics_command"] == "SEND"
        assert "cics_text" in d
        assert "location" in d

    # ------------------------------------------------------------------
    # EXEC IMS / DLI
    # ------------------------------------------------------------------

    def test_ims_gu_with_ssa_arguments(self):
        src = _program(
            "    EXEC DLI GU USING PCB(1) SEGMENT(EMPLOYEE)\n"
            "        INTO(WS-AREA) WHERE(EMPID=:WS-ID) END-EXEC."
        )
        result = parse_cobol(src, filename="m11.cbl")
        assert result.success

        node = result.ast.find_all_by_type("EXEC_IMS")[0]
        assert node.ims_command == "GU"
        assert node.ims_call_type == "GU"
        assert "USING" in node.arguments
        assert "PCB(1)" in node.arguments
        assert "SEGMENT(EMPLOYEE)" in node.arguments
        assert "INTO(WS-AREA)" in node.arguments
        assert any(arg.startswith("WHERE(") for arg in node.arguments)
        assert node.to_dict()["arguments"] == node.arguments

    def test_ims_positional_pcb_argument(self):
        src = _program("    EXEC IMS GU EMPDB END-EXEC.")
        result = parse_cobol(src, filename="m11.cbl")
        assert result.success

        node = result.ast.find_all_by_type("EXEC_IMS")[0]
        assert node.arguments == ["EMPDB"]

    def test_ims_backward_compat_fields_still_populate(self):
        src = _program("    EXEC IMS ISRT EMPDB END-EXEC.")
        result = parse_cobol(src, filename="m11.cbl")
        assert result.success

        node = result.ast.find_all_by_type("EXEC_IMS")[0]
        assert node.ims_command == "ISRT"
        assert node.ims_call_type == "ISRT"
        assert "EMPDB" in node.ims_text
        d = node.to_dict()
        assert d["ims_command"] == "ISRT"
        assert d["ims_call_type"] == "ISRT"
        assert "ims_text" in d

    # ------------------------------------------------------------------
    # EXEC SQL
    # ------------------------------------------------------------------

    def test_sql_select_indicator_and_join_tables(self):
        stmt = parse_exec_sql(
            "SELECT E.NAME, D.DNAME INTO :WS-NAME:WS-IND, :WS-DNAME "
            "FROM EMPLOYEE E JOIN DEPT D ON E.DNO = D.DNO "
            "WHERE E.ID = :WS-ID",
            SourceLocation(1, 1),
        )
        assert stmt.sql_type == "SELECT"
        # :HV:IND indicator form.
        assert "WS-NAME" in stmt.host_variables
        assert "WS-IND" in stmt.null_indicators
        assert "WS-ID" in stmt.host_variables
        # JOIN table extraction.
        assert "EMPLOYEE" in stmt.tables
        assert "DEPT" in stmt.tables
        # New structure.
        assert stmt.select_columns == ["E.NAME", "D.DNAME"]
        assert stmt.where_present is True
        d = stmt.to_dict()
        assert d["select_columns"] == ["E.NAME", "D.DNAME"]
        assert d["where_present"] is True

    def test_sql_multi_table_from_list(self):
        stmt = parse_exec_sql(
            "SELECT A, COUNT(*) FROM T1, T2 WHERE A > 1", SourceLocation(1, 1)
        )
        assert stmt.tables == ["T1", "T2"]
        assert stmt.select_columns == ["A", "COUNT(*)"]
        assert stmt.where_present is True

    def test_sql_no_where_flag(self):
        stmt = parse_exec_sql("SELECT A FROM T1", SourceLocation(1, 1))
        assert stmt.where_present is False
        assert stmt.select_columns == ["A"]

    def test_sql_literals_do_not_pollute_extraction(self):
        stmt = parse_exec_sql(
            "UPDATE EMP SET NOTE = 'copy FROM BADTBL :FAKE-VAR' " "WHERE ID = :WS-ID",
            SourceLocation(1, 1),
        )
        assert stmt.tables == ["EMP"]
        assert stmt.host_variables == ["WS-ID"]
        assert "FAKE-VAR" not in stmt.host_variables
        assert stmt.where_present is True

    def test_sql_backward_compat_fields_still_populate(self):
        stmt = parse_exec_sql(
            "SELECT NAME INTO :WS-NAME FROM EMPLOYEE WHERE ID = :WS-ID",
            SourceLocation(1, 1),
        )
        # Pre-existing fields.
        assert stmt.sql_type == "SELECT"
        assert stmt.tables == ["EMPLOYEE"]
        assert stmt.host_variables == ["WS-NAME", "WS-ID"]
        assert stmt.into_variables == ["WS-NAME"]
        d = stmt.to_dict()
        for key in (
            "sql_text",
            "sql_type",
            "host_variables",
            "null_indicators",
            "tables",
            "cursor_name",
            "prepared_statement_name",
            "into_variables",
            "structured_output",
        ):
            assert key in d

    def test_sql_end_to_end_parse_cobol(self):
        src = _program(
            "    EXEC SQL\n"
            "        SELECT NAME INTO :WS-NAME\n"
            "        FROM EMPLOYEE E JOIN DEPT D ON E.DNO = D.DNO\n"
            "        WHERE E.ID = :WS-ID\n"
            "    END-EXEC."
        )
        result = parse_cobol(src, filename="m11.cbl")
        assert result.success

        stmts = [
            s
            for s in result.ast.find_all_by_type("Statement")
            if getattr(s, "sql_type", None) == "SELECT"
        ]
        assert stmts
        stmt = stmts[0]
        assert "EMPLOYEE" in stmt.tables
        assert "DEPT" in stmt.tables
        assert stmt.where_present is True
        assert stmt.select_columns == ["NAME"]
