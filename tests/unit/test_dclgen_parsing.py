"""Tests for EXEC SQL DECLARE TABLE (DCLGEN) parsing and host-variable resolution.

Covers:
  1. DB2 type → COBOL PICTURE / USAGE mapping utilities
  2. DB2ColumnDefinition construction and serialisation
  3. DeclareTableStatement parsing (table name, columns, nullability)
  4. SQLStatementType.DECLARE_TABLE detection in parse_exec_sql()
  5. HostVariableResolver: symbol-table building, column-index, resolution
  6. End-to-end: full COBOL program with DCLGEN DECLARE TABLE + DML statements
"""

from cobolparser.models.ast_base import SourceLocation
from cobolparser.models.sql_statements import (
    DB2ColumnDefinition,
    DeclareTableStatement,
    SQLStatementType,
    db2_type_to_cobol_pic,
    db2_type_to_cobol_usage,
    parse_exec_sql,
)
from cobolparser.parser import parse_cobol

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_LOC = SourceLocation(1, 1)


def _make_loc() -> SourceLocation:
    return SourceLocation(1, 1)


# ---------------------------------------------------------------------------
# 1. db2_type_to_cobol_pic / db2_type_to_cobol_usage
# ---------------------------------------------------------------------------


class TestDb2TypeMappingFunctions:
    """Unit-test the standalone mapping helpers."""

    def test_char_with_length(self):
        assert db2_type_to_cobol_pic("CHAR", length=30) == "X(30)"

    def test_char_no_length(self):
        # Default length 1
        assert db2_type_to_cobol_pic("CHAR") == "X(1)"

    def test_varchar_with_length(self):
        assert db2_type_to_cobol_pic("VARCHAR", length=50) == "X(50)"

    def test_integer(self):
        assert db2_type_to_cobol_pic("INTEGER") == "S9(9)"

    def test_int_alias(self):
        assert db2_type_to_cobol_pic("INT") == "S9(9)"

    def test_smallint(self):
        assert db2_type_to_cobol_pic("SMALLINT") == "S9(4)"

    def test_bigint(self):
        assert db2_type_to_cobol_pic("BIGINT") == "S9(18)"

    def test_decimal_with_scale(self):
        assert db2_type_to_cobol_pic("DECIMAL", precision=10, scale=2) == "S9(8)V9(2)"

    def test_decimal_integer_only(self):
        assert db2_type_to_cobol_pic("DECIMAL", precision=9, scale=0) == "S9(9)"

    def test_numeric_alias(self):
        assert db2_type_to_cobol_pic("NUMERIC", precision=5, scale=2) == "S9(3)V9(2)"

    def test_date(self):
        assert db2_type_to_cobol_pic("DATE") == "X(10)"

    def test_time(self):
        assert db2_type_to_cobol_pic("TIME") == "X(8)"

    def test_timestamp(self):
        assert db2_type_to_cobol_pic("TIMESTAMP") == "X(26)"

    def test_float_returns_comp2_annotation(self):
        # A bare DB2 FLOAT is FLOAT(53): double precision.
        assert db2_type_to_cobol_pic("FLOAT") == "COMP-2"

    def test_double_returns_comp2_annotation(self):
        assert db2_type_to_cobol_pic("DOUBLE") == "COMP-2"

    def test_unknown_type_returns_none(self):
        assert db2_type_to_cobol_pic("BLOB") is None

    def test_case_insensitive(self):
        assert db2_type_to_cobol_pic("char", length=10) == "X(10)"

    # Usage
    def test_usage_char(self):
        assert db2_type_to_cobol_usage("CHAR") == "DISPLAY"

    def test_usage_decimal(self):
        assert db2_type_to_cobol_usage("DECIMAL") == "COMP-3"

    def test_usage_integer(self):
        assert db2_type_to_cobol_usage("INTEGER") == "COMP"

    def test_usage_smallint(self):
        assert db2_type_to_cobol_usage("SMALLINT") == "COMP"

    def test_usage_float(self):
        # A bare DB2 FLOAT is FLOAT(53): double precision.
        assert db2_type_to_cobol_usage("FLOAT") == "COMP-2"

    def test_usage_double(self):
        assert db2_type_to_cobol_usage("DOUBLE") == "COMP-2"

    def test_usage_varchar(self):
        assert db2_type_to_cobol_usage("VARCHAR") == "DISPLAY"

    def test_usage_timestamp(self):
        assert db2_type_to_cobol_usage("TIMESTAMP") == "DISPLAY"


# ---------------------------------------------------------------------------
# 2. DB2ColumnDefinition
# ---------------------------------------------------------------------------


class TestDB2ColumnDefinition:
    """Test the DB2ColumnDefinition dataclass."""

    def test_char_column(self):
        col = DB2ColumnDefinition("CUST_NAME", "CHAR", length=30, nullable=False)
        assert col.name == "CUST_NAME"
        assert col.db2_type == "CHAR"
        assert col.length == 30
        assert col.nullable is False
        assert col.cobol_picture == "X(30)"
        assert col.cobol_usage == "DISPLAY"

    def test_decimal_column(self):
        col = DB2ColumnDefinition("SALARY", "DECIMAL", precision=9, scale=2)
        assert col.cobol_picture == "S9(7)V9(2)"
        assert col.cobol_usage == "COMP-3"

    def test_integer_column(self):
        col = DB2ColumnDefinition("CUST_ID", "INTEGER")
        assert col.cobol_picture == "S9(9)"
        assert col.cobol_usage == "COMP"
        assert col.nullable is True  # default

    def test_to_dict_structure(self):
        col = DB2ColumnDefinition("EMP_ID", "CHAR", length=6, nullable=False)
        d = col.to_dict()
        assert d["name"] == "EMP_ID"
        assert d["db2_type"] == "CHAR"
        assert d["length"] == 6
        assert d["precision"] is None
        assert d["scale"] is None
        assert d["nullable"] is False
        assert d["cobol_picture"] == "X(6)"
        assert d["cobol_usage"] == "DISPLAY"


# ---------------------------------------------------------------------------
# 3. DeclareTableStatement parsing
# ---------------------------------------------------------------------------


class TestDeclareTableStatement:
    """Test DeclareTableStatement instantiation and column parsing."""

    def _parse(self, sql: str) -> DeclareTableStatement:
        stmt = parse_exec_sql(sql, _make_loc())
        assert isinstance(
            stmt, DeclareTableStatement
        ), f"Expected DeclareTableStatement, got {type(stmt).__name__}"
        return stmt

    def test_basic_table_name(self):
        sql = "DECLARE EMPLOYEE TABLE (EMP_ID CHAR(6) NOT NULL)"
        stmt = self._parse(sql)
        assert stmt.table_name == "EMPLOYEE"

    def test_table_in_tables_list(self):
        sql = "DECLARE EMPLOYEE TABLE (EMP_ID CHAR(6))"
        stmt = self._parse(sql)
        assert "EMPLOYEE" in stmt.tables

    def test_sql_type_is_declare_table(self):
        sql = "DECLARE CUSTOMER TABLE (CUST_ID INTEGER NOT NULL)"
        stmt = self._parse(sql)
        assert stmt.sql_type == SQLStatementType.DECLARE_TABLE

    def test_single_char_column(self):
        sql = "DECLARE EMP TABLE (EMP_ID CHAR(6) NOT NULL)"
        stmt = self._parse(sql)
        assert len(stmt.columns) == 1
        col = stmt.columns[0]
        assert col.name == "EMP_ID"
        assert col.db2_type == "CHAR"
        assert col.length == 6
        assert col.nullable is False
        assert col.cobol_picture == "X(6)"

    def test_nullable_column(self):
        sql = "DECLARE EMP TABLE (DEPT_NO CHAR(3))"
        stmt = self._parse(sql)
        assert stmt.columns[0].nullable is True

    def test_multiple_columns(self):
        sql = (
            "DECLARE CUSTOMER TABLE\n"
            "( CUST_ID     INTEGER NOT NULL,\n"
            "  CUST_NAME   CHAR(30),\n"
            "  CUST_ADDR   CHAR(50),\n"
            "  CUST_PHONE  CHAR(15),\n"
            "  CREDIT_LIMIT DECIMAL(10,2)\n"
            ")"
        )
        stmt = self._parse(sql)
        assert len(stmt.columns) == 5

        names = [c.name for c in stmt.columns]
        assert names == [
            "CUST_ID",
            "CUST_NAME",
            "CUST_ADDR",
            "CUST_PHONE",
            "CREDIT_LIMIT",
        ]

        # CUST_ID — INTEGER
        assert stmt.columns[0].db2_type == "INTEGER"
        assert stmt.columns[0].cobol_picture == "S9(9)"
        assert stmt.columns[0].nullable is False

        # CUST_NAME — CHAR(30)
        assert stmt.columns[1].db2_type == "CHAR"
        assert stmt.columns[1].length == 30
        assert stmt.columns[1].cobol_picture == "X(30)"

        # CREDIT_LIMIT — DECIMAL(10,2)
        assert stmt.columns[4].db2_type == "DECIMAL"
        assert stmt.columns[4].precision == 10
        assert stmt.columns[4].scale == 2
        assert stmt.columns[4].cobol_picture == "S9(8)V9(2)"
        assert stmt.columns[4].cobol_usage == "COMP-3"

    def test_to_dict_contains_columns(self):
        sql = "DECLARE EMP TABLE (EMP_ID CHAR(6) NOT NULL, SALARY DECIMAL(9,2))"
        stmt = self._parse(sql)
        d = stmt.to_dict()
        assert d["table_name"] == "EMP"
        assert len(d["columns"]) == 2
        assert d["sql_type"] == SQLStatementType.DECLARE_TABLE

    def test_structured_output(self):
        sql = "DECLARE DEPT TABLE (DEPT_ID SMALLINT NOT NULL)"
        stmt = self._parse(sql)
        output = stmt.get_structured_output()
        assert output.table == "DEPT"

    def test_host_variables_empty_for_declare_table(self):
        """DECLARE TABLE blocks have no :host-var references."""
        sql = "DECLARE EMP TABLE (EMP_ID CHAR(6))"
        stmt = self._parse(sql)
        assert stmt.host_variables == []

    def test_set_sql_text_idempotent(self):
        """Calling set_sql_text twice must not accumulate duplicate columns."""
        sql = "DECLARE EMP TABLE (EMP_ID CHAR(6))"
        stmt = self._parse(sql)
        assert len(stmt.columns) == 1
        # Call again with the same SQL
        stmt.set_sql_text(sql)
        assert len(stmt.columns) == 1  # still 1, not 2

    def test_decimal_scale_equals_precision_clamped(self):
        """DECIMAL(5,5) — scale equals precision — integer digits clamped to 1."""
        stmt = parse_exec_sql("DECLARE T TABLE (V DECIMAL(5,5))", _make_loc())
        assert isinstance(stmt, DeclareTableStatement)
        col = stmt.columns[0]
        assert col.cobol_picture == "S9(1)V9(5)"

    def test_decimal_scale_exceeds_precision_raises(self):
        """DECIMAL(3,5) — scale > precision — must raise ValueError."""
        import pytest

        with pytest.raises(ValueError, match="scale"):
            parse_exec_sql("DECLARE T TABLE (V DECIMAL(3,5))", _make_loc())


# ---------------------------------------------------------------------------
# 4. parse_exec_sql factory: DECLARE TABLE vs DECLARE CURSOR dispatch
# ---------------------------------------------------------------------------


class TestParseExecSqlDispatch:
    """Ensure parse_exec_sql routes DECLARE TABLE and DECLARE CURSOR correctly."""

    def test_declare_cursor_still_works(self):
        sql = "DECLARE EMP_CUR CURSOR FOR SELECT * FROM EMPLOYEE"
        stmt = parse_exec_sql(sql, _make_loc())
        assert stmt.sql_type == SQLStatementType.DECLARE_CURSOR

    def test_declare_table_dispatched(self):
        sql = "DECLARE EMPLOYEE TABLE (EMP_ID CHAR(6))"
        stmt = parse_exec_sql(sql, _make_loc())
        assert stmt.sql_type == SQLStatementType.DECLARE_TABLE
        assert isinstance(stmt, DeclareTableStatement)

    def test_select_not_affected(self):
        sql = "SELECT NAME INTO :WS-NAME FROM EMPLOYEE WHERE ID = :WS-ID"
        stmt = parse_exec_sql(sql, _make_loc())
        assert stmt.sql_type == SQLStatementType.SELECT
        assert not isinstance(stmt, DeclareTableStatement)


# ---------------------------------------------------------------------------
# 5. HostVariableResolver — unit tests
# ---------------------------------------------------------------------------


class TestHostVariableResolver:
    """Test the HostVariableResolver analysis pass."""

    def _resolve(self, cobol_source: str):
        from cobolparser.analysis import HostVariableResolver

        result = parse_cobol(cobol_source)
        assert result.ast is not None, f"Parse failed: {result.errors}"
        resolver = HostVariableResolver()
        return resolver.resolve(result.ast)

    def test_resolved_from_working_storage(self):
        cobol = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST1.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-DATA.
           05  WS-NAME     PIC X(30).
           05  WS-ID       PIC 9(8) COMP.
       PROCEDURE DIVISION.
       MAIN.
           EXEC SQL
               SELECT NAME INTO :WS-NAME FROM EMP WHERE ID = :WS-ID
           END-EXEC
           STOP RUN.
"""
        report = self._resolve(cobol)
        assert "WS-NAME" in report.resolved
        assert report.resolved["WS-NAME"].picture == "X(30)"
        assert report.resolved["WS-NAME"].usage == "DISPLAY"

        assert "WS-ID" in report.resolved
        assert report.resolved["WS-ID"].picture == "9(8)"
        assert report.resolved["WS-ID"].usage == "COMP"

    def test_unresolved_host_variable(self):
        cobol = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST2.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-NAME     PIC X(30).
       PROCEDURE DIVISION.
       MAIN.
           EXEC SQL
               SELECT NAME, DEPT INTO :WS-NAME, :WS-DEPT FROM EMP
           END-EXEC
           STOP RUN.
"""
        report = self._resolve(cobol)
        assert "WS-NAME" in report.resolved
        assert "WS-DEPT" in report.unresolved

    def test_declare_table_collected(self):
        cobol = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST3.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
           EXEC SQL
               DECLARE EMPLOYEE TABLE
               ( EMP_ID CHAR(6) NOT NULL,
                 EMP_NAME CHAR(30)
               )
           END-EXEC.
       PROCEDURE DIVISION.
       MAIN.
           STOP RUN.
"""
        report = self._resolve(cobol)
        assert "EMPLOYEE" in report.declare_tables
        tbl = report.declare_tables["EMPLOYEE"]
        assert len(tbl.columns) == 2

    def test_dclgen_column_used_as_fallback(self):
        """Host vars with no DATA DIVISION entry fall back to the DB2 column definition.

        This test uses underscore-form host variable names (matching the DECLARE
        TABLE column names exactly) to exercise the DB2 column fallback path in
        HostVariableResolver.
        """
        cobol = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST4.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
           EXEC SQL
               DECLARE EMPLOYEE TABLE
               ( EMP_ID   CHAR(6) NOT NULL,
                 EMP_NAME CHAR(30)
               )
           END-EXEC.
       PROCEDURE DIVISION.
       MAIN.
           EXEC SQL
               SELECT EMP_ID, EMP_NAME
               INTO :EMP_ID, :EMP_NAME
               FROM EMPLOYEE
           END-EXEC
           STOP RUN.
"""
        report = self._resolve(cobol)
        # EMP_ID and EMP_NAME have no COBOL DATA DIVISION entries — the resolver
        # falls back to the DB2 column definitions from the DECLARE TABLE block.
        assert "EMP_ID" in report.resolved
        assert "EMP_NAME" in report.resolved
        # No DATA DIVISION item; db2_column is populated from DECLARE TABLE
        assert report.resolved["EMP_ID"].data_item is None
        assert report.resolved["EMP_ID"].db2_column is not None
        assert report.resolved["EMP_ID"].picture == "X(6)"
        assert report.resolved["EMP_NAME"].picture == "X(30)"
        # These variables are NOT unresolved
        assert "EMP_ID" not in report.unresolved
        assert "EMP_NAME" not in report.unresolved

    def test_null_indicators_resolved_as_host_variables(self):
        """Null indicator variables that exist in Working-Storage are resolved normally.

        COBOL allows null indicators to be any S9(4) COMP host variable.  The
        resolver treats them identically to other host variables: if the name is
        found in the DATA DIVISION it is *resolved*, not unresolved.
        """
        cobol = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST5.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-NAME     PIC X(30).
       01  WS-IND      PIC S9(4) COMP.
       PROCEDURE DIVISION.
       MAIN.
           EXEC SQL
               SELECT NAME INTO :WS-NAME INDICATOR :WS-IND FROM EMP
           END-EXEC
           STOP RUN.
"""
        report = self._resolve(cobol)
        assert "WS-NAME" in report.resolved
        # WS-IND is a valid Working-Storage item and appears as a host variable
        # (INDICATOR syntax is syntactic sugar; the var still has a WS entry)
        assert "WS-IND" in report.resolved
        assert "WS-IND" not in report.unresolved

    def test_to_dict_serialisable(self):
        cobol = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST6.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-NAME     PIC X(10).
       PROCEDURE DIVISION.
       MAIN.
           EXEC SQL
               SELECT NAME INTO :WS-NAME FROM T
           END-EXEC
           STOP RUN.
"""
        report = self._resolve(cobol)
        d = report.to_dict()
        assert isinstance(d["resolved_count"], int)
        assert isinstance(d["unresolved"], list)
        assert isinstance(d["resolved"], dict)
        assert "WS-NAME" in d["resolved"]

    def test_same_variable_in_multiple_statements(self):
        cobol = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST7.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-ID   PIC 9(5) COMP.
       PROCEDURE DIVISION.
       MAIN.
           EXEC SQL
               SELECT A INTO :WS-ID FROM T1
           END-EXEC
           EXEC SQL
               SELECT B INTO :WS-ID FROM T2
           END-EXEC
           STOP RUN.
"""
        report = self._resolve(cobol)
        assert "WS-ID" in report.resolved
        # The same variable appears in two statements
        assert len(report.resolved["WS-ID"].sql_statements) == 2

    def test_column_collision_reported(self):
        """Column names that appear in multiple DECLARE TABLE blocks are flagged."""
        cobol = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST9.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
           EXEC SQL
               DECLARE TABLE1 TABLE (ID INTEGER NOT NULL, NAME CHAR(30))
           END-EXEC.
           EXEC SQL
               DECLARE TABLE2 TABLE (ID CHAR(10) NOT NULL, CODE CHAR(5))
           END-EXEC.
       PROCEDURE DIVISION.
       MAIN.
           STOP RUN.
"""
        report = self._resolve(cobol)
        # "ID" appears in both TABLE1 and TABLE2 — must be flagged as a collision
        assert "ID" in report.column_name_collisions
        tables_for_id = report.column_name_collisions["ID"]
        assert "TABLE1" in tables_for_id
        assert "TABLE2" in tables_for_id
        # "NAME" and "CODE" are unique — no collision
        assert "NAME" not in report.column_name_collisions
        assert "CODE" not in report.column_name_collisions

    def test_collision_in_to_dict(self):
        """column_name_collisions is included in to_dict output."""
        cobol = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST10.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
           EXEC SQL
               DECLARE A TABLE (STATUS CHAR(1))
           END-EXEC.
           EXEC SQL
               DECLARE B TABLE (STATUS CHAR(2))
           END-EXEC.
       PROCEDURE DIVISION.
       MAIN.
           STOP RUN.
"""
        report = self._resolve(cobol)
        d = report.to_dict()
        assert "column_name_collisions" in d
        assert "collision_count" in d
        assert d["collision_count"] == 1
        assert "STATUS" in d["column_name_collisions"]

    def test_symbol_table_accessible(self):
        from cobolparser.analysis import HostVariableResolver

        cobol = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST8.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-ALPHA    PIC X(5).
       01  WS-NUM      PIC 9(3).
       PROCEDURE DIVISION.
       MAIN.
           STOP RUN.
"""
        result = parse_cobol(cobol)
        resolver = HostVariableResolver()
        resolver.resolve(result.ast)
        st = resolver.get_symbol_table()
        assert "WS-ALPHA" in st
        assert "WS-NUM" in st


# ---------------------------------------------------------------------------
# 6. End-to-end: full COBOL program resembling DCLGEN output
# ---------------------------------------------------------------------------


class TestEndToEndDclgen:
    """Integration tests using a realistic DCLGEN-style COBOL program."""

    DCLGEN_PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. DCLGEN-TEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.

      * DCLGEN-generated table declaration
           EXEC SQL
               DECLARE CUSTOMER TABLE
               ( CUST_ID     INTEGER NOT NULL,
                 CUST_NAME   CHAR(30),
                 CUST_ADDR   CHAR(50),
                 CUST_PHONE  CHAR(15),
                 CREDIT_LIMIT DECIMAL(10,2)
               )
           END-EXEC.

      * DCLGEN-generated host structure
       01  CUSTOMER-RECORD.
           05  WS-CUST-ID       PIC S9(9) COMP.
           05  WS-CUST-NAME     PIC X(30).
           05  WS-CUST-ADDR     PIC X(50).
           05  WS-CUST-PHONE    PIC X(15).
           05  WS-CREDIT-LIMIT  PIC S9(8)V9(2) COMP-3.

       01  WS-SQLCODE           PIC S9(9) COMP VALUE ZERO.

       PROCEDURE DIVISION.
       MAIN.
           EXEC SQL
               SELECT CUST_ID, CUST_NAME, CUST_ADDR, CUST_PHONE, CREDIT_LIMIT
               INTO :WS-CUST-ID, :WS-CUST-NAME, :WS-CUST-ADDR,
                    :WS-CUST-PHONE, :WS-CREDIT-LIMIT
               FROM CUSTOMER
               WHERE CUST_ID = :WS-CUST-ID
           END-EXEC
           MOVE SQLCODE TO WS-SQLCODE
           STOP RUN.
"""

    def test_parse_succeeds(self):
        result = parse_cobol(self.DCLGEN_PROGRAM)
        assert result.ast is not None

    def test_declare_table_found(self):
        from cobolparser.analysis import HostVariableResolver

        result = parse_cobol(self.DCLGEN_PROGRAM)
        report = HostVariableResolver().resolve(result.ast)
        assert "CUSTOMER" in report.declare_tables

    def test_five_columns_parsed(self):
        from cobolparser.analysis import HostVariableResolver

        result = parse_cobol(self.DCLGEN_PROGRAM)
        report = HostVariableResolver().resolve(result.ast)
        tbl = report.declare_tables["CUSTOMER"]
        assert len(tbl.columns) == 5

    def test_all_host_vars_resolved(self):
        from cobolparser.analysis import HostVariableResolver

        result = parse_cobol(self.DCLGEN_PROGRAM)
        report = HostVariableResolver().resolve(result.ast)

        for var in [
            "WS-CUST-ID",
            "WS-CUST-NAME",
            "WS-CUST-ADDR",
            "WS-CUST-PHONE",
            "WS-CREDIT-LIMIT",
        ]:
            assert var in report.resolved, (
                f"Expected {var!r} to be resolved, but it wasn't. "
                f"Resolved: {list(report.resolved)}, "
                f"Unresolved: {report.unresolved}"
            )

    def test_host_var_pictures(self):
        from cobolparser.analysis import HostVariableResolver

        result = parse_cobol(self.DCLGEN_PROGRAM)
        report = HostVariableResolver().resolve(result.ast)

        assert report.resolved["WS-CUST-NAME"].picture == "X(30)"
        assert report.resolved["WS-CUST-ADDR"].picture == "X(50)"
        assert report.resolved["WS-CREDIT-LIMIT"].picture == "S9(8)V9(2)"
        assert report.resolved["WS-CREDIT-LIMIT"].usage == "COMP-3"

    def test_no_unresolved_vars(self):
        from cobolparser.analysis import HostVariableResolver

        result = parse_cobol(self.DCLGEN_PROGRAM)
        report = HostVariableResolver().resolve(result.ast)
        assert report.unresolved == set()

    def test_report_to_dict(self):
        from cobolparser.analysis import HostVariableResolver

        result = parse_cobol(self.DCLGEN_PROGRAM)
        report = HostVariableResolver().resolve(result.ast)
        d = report.to_dict()
        assert d["resolved_count"] >= 5
        assert d["unresolved_count"] == 0
        assert "CUSTOMER" in d["declare_tables"]
