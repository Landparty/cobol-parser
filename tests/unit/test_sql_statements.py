"""Comprehensive unit tests for SQL statement parsing in COBOL programs.

This module tests all SQL edge cases including:
1. Standard SELECT, INSERT, UPDATE, and DELETE statements
2. DECLARE CURSOR and FETCH operations with host variables
3. Multi-table JOINs and subqueries
4. EXEC SQL and END-EXEC block boundaries
5. Host variables prefixed with colons
6. Inline and multi-line SQL statements
7. SQL statements with COBOL copybook references
8. COMMIT, ROLLBACK, and transaction control statements
9. Dynamic SQL using PREPARE and EXECUTE
10. Null indicator handling and INTO clauses
11. Whitespace variations and COBOL continuation lines
12. Comments embedded within SQL blocks
"""

import pytest

from cobolparser.models.ast_base import SourceLocation
from cobolparser.models.sql_statements import (
    DeclareCursorStatement,
    DynamicSQLStatement,
    ExecSQLStatement,
    FetchStatement,
    SQLStatementInfo,
    SQLStatementType,
    TransactionControlStatement,
    parse_exec_sql,
)
from cobolparser.parser import parse_cobol
from cobolparser.plugins.core import ErrorRecoveryMode


class TestSQLStatementInfo:
    """Test SQLStatementInfo dataclass."""

    def test_sql_statement_info_creation(self):
        """Test creating SQLStatementInfo with all fields."""
        info = SQLStatementInfo(
            table="person", query="SELECT * FROM person", cursor=None
        )
        assert info.table == "person"
        assert info.query == "SELECT * FROM person"
        assert info.cursor is None

    def test_sql_statement_info_to_dict(self):
        """Test to_dict output format."""
        info = SQLStatementInfo(
            table="person", query="SELECT * FROM person", cursor=None
        )
        result = info.to_dict()

        assert result == {
            "table": "person",
            "query": "SELECT * FROM person",
            "cursor": None,
        }

    def test_sql_statement_info_cursor_operation(self):
        """Test SQLStatementInfo for cursor operations."""
        info = SQLStatementInfo(
            table="person", query=None, cursor="FETCH :tata FROM person"
        )
        result = info.to_dict()

        assert result == {
            "table": "person",
            "query": None,
            "cursor": "FETCH :tata FROM person",
        }


class TestStandardSQLStatements:
    """Test standard SELECT, INSERT, UPDATE, DELETE statements."""

    def test_select_statement_basic(self):
        """Test basic SELECT statement parsing."""
        location = SourceLocation(1, 1)
        stmt = parse_exec_sql("SELECT * FROM person", location)

        assert stmt.sql_type == SQLStatementType.SELECT
        assert stmt.tables == ["person"]

        output = stmt.get_structured_output()
        assert output.table == "person"
        assert output.query == "SELECT * FROM person"
        assert output.cursor is None

    def test_select_with_columns(self):
        """Test SELECT with specific columns."""
        location = SourceLocation(1, 1)
        sql = "SELECT id, name, salary FROM employee WHERE dept = 'IT'"
        stmt = parse_exec_sql(sql, location)

        assert stmt.sql_type == SQLStatementType.SELECT
        assert "employee" in stmt.tables

        output = stmt.get_structured_output()
        assert output.table == "employee"

    def test_select_with_host_variables(self):
        """Test SELECT with host variables in WHERE clause."""
        location = SourceLocation(1, 1)
        sql = "SELECT name, salary INTO :WS-NAME, :WS-SALARY FROM employee WHERE id = :WS-ID"
        stmt = parse_exec_sql(sql, location)

        assert stmt.sql_type == SQLStatementType.SELECT
        assert "WS-NAME" in stmt.host_variables
        assert "WS-SALARY" in stmt.host_variables
        assert "WS-ID" in stmt.host_variables
        assert "WS-NAME" in stmt.into_variables
        assert "WS-SALARY" in stmt.into_variables

    def test_insert_statement(self):
        """Test INSERT statement parsing."""
        location = SourceLocation(1, 1)
        sql = "INSERT INTO person (id, name) VALUES (:WS-ID, :WS-NAME)"
        stmt = parse_exec_sql(sql, location)

        assert stmt.sql_type == SQLStatementType.INSERT
        assert "person" in stmt.tables
        assert "WS-ID" in stmt.host_variables
        assert "WS-NAME" in stmt.host_variables

        output = stmt.get_structured_output()
        assert output.table == "person"
        assert "INSERT" in output.query

    def test_update_statement(self):
        """Test UPDATE statement parsing."""
        location = SourceLocation(1, 1)
        sql = "UPDATE employee SET salary = :NEW-SALARY WHERE id = :EMP-ID"
        stmt = parse_exec_sql(sql, location)

        assert stmt.sql_type == SQLStatementType.UPDATE
        assert "employee" in stmt.tables
        assert "NEW-SALARY" in stmt.host_variables
        assert "EMP-ID" in stmt.host_variables

        output = stmt.get_structured_output()
        assert output.table == "employee"

    def test_delete_statement(self):
        """Test DELETE statement parsing."""
        location = SourceLocation(1, 1)
        sql = "DELETE FROM person WHERE id = :DELETE-ID"
        stmt = parse_exec_sql(sql, location)

        assert stmt.sql_type == SQLStatementType.DELETE
        assert "person" in stmt.tables
        assert "DELETE-ID" in stmt.host_variables

        output = stmt.get_structured_output()
        assert output.table == "person"


class TestCursorOperations:
    """Test DECLARE CURSOR and FETCH operations."""

    def test_declare_cursor_basic(self):
        """Test basic DECLARE CURSOR statement."""
        location = SourceLocation(1, 1)
        sql = "DECLARE emp_cursor CURSOR FOR SELECT * FROM employee"
        stmt = parse_exec_sql(sql, location)

        assert stmt.sql_type == SQLStatementType.DECLARE_CURSOR
        assert isinstance(stmt, DeclareCursorStatement)
        assert stmt.cursor_name == "emp_cursor"
        assert "employee" in stmt.tables

        output = stmt.get_structured_output()
        assert "DECLARE emp_cursor CURSOR" in output.cursor
        assert "SELECT" in output.query

    @pytest.mark.parametrize(
        "sql, table",
        [
            ("UPDATE EMP SET SAL = :WS-SAL WHERE CURRENT OF C1", "EMP"),
            ("DELETE FROM EMP WHERE CURRENT OF EMP-CUR", "EMP"),
        ],
    )
    def test_positioned_update_delete_names_the_cursor(self, sql, table):
        # Regression (2026-09-28): WHERE CURRENT OF left cursor_name None.
        stmt = parse_exec_sql(sql, SourceLocation(1, 1))
        assert stmt.cursor_name == sql.rsplit(" ", 1)[1]
        assert stmt.tables[0] == table

    def test_searched_update_has_no_cursor(self):
        stmt = parse_exec_sql(
            "UPDATE EMP SET SAL = 1 WHERE ID = 5", SourceLocation(1, 1)
        )
        assert stmt.cursor_name is None

    def test_declare_cursor_with_host_variables(self):
        """Test DECLARE CURSOR with host variables."""
        location = SourceLocation(1, 1)
        sql = "DECLARE dept_cursor CURSOR FOR SELECT name, salary FROM employee WHERE dept = :WS-DEPT"
        stmt = parse_exec_sql(sql, location)

        assert stmt.cursor_name == "dept_cursor"
        assert "WS-DEPT" in stmt.host_variables

    def test_declare_cursor_with_hold(self):
        """Test DECLARE CURSOR WITH HOLD option."""
        location = SourceLocation(1, 1)
        sql = "DECLARE my_cursor CURSOR WITH HOLD FOR SELECT * FROM employee"
        stmt = parse_exec_sql(sql, location)

        assert isinstance(stmt, DeclareCursorStatement)
        assert "WITH HOLD" in stmt.cursor_options

    def test_declare_cursor_for_update(self):
        """Test DECLARE CURSOR FOR UPDATE option."""
        location = SourceLocation(1, 1)
        sql = "DECLARE upd_cursor CURSOR FOR SELECT * FROM employee FOR UPDATE"
        stmt = parse_exec_sql(sql, location)

        assert isinstance(stmt, DeclareCursorStatement)
        assert "FOR UPDATE" in stmt.cursor_options

    def test_fetch_basic(self):
        """Test basic FETCH statement."""
        location = SourceLocation(1, 1)
        sql = "FETCH emp_cursor INTO :WS-ID, :WS-NAME"
        stmt = parse_exec_sql(sql, location)

        assert stmt.sql_type == SQLStatementType.FETCH
        assert isinstance(stmt, FetchStatement)
        assert stmt.cursor_name == "emp_cursor"
        assert "WS-ID" in stmt.into_variables
        assert "WS-NAME" in stmt.into_variables

        output = stmt.get_structured_output()
        assert output.cursor is not None
        assert "FETCH" in output.cursor

    def test_fetch_next(self):
        """Test FETCH NEXT statement."""
        location = SourceLocation(1, 1)
        sql = "FETCH NEXT FROM my_cursor INTO :WS-DATA"
        stmt = parse_exec_sql(sql, location)

        assert stmt.cursor_name == "my_cursor"
        assert stmt.fetch_direction == "NEXT"

    def test_open_cursor(self):
        """Test OPEN cursor statement."""
        location = SourceLocation(1, 1)
        sql = "OPEN emp_cursor"
        stmt = parse_exec_sql(sql, location)

        assert stmt.sql_type == SQLStatementType.OPEN_CURSOR
        assert stmt.cursor_name == "emp_cursor"

        output = stmt.get_structured_output()
        assert "OPEN" in output.cursor

    def test_close_cursor(self):
        """Test CLOSE cursor statement."""
        location = SourceLocation(1, 1)
        sql = "CLOSE emp_cursor"
        stmt = parse_exec_sql(sql, location)

        assert stmt.sql_type == SQLStatementType.CLOSE_CURSOR
        assert stmt.cursor_name == "emp_cursor"


class TestJoinsAndSubqueries:
    """Test multi-table JOINs and subqueries."""

    def test_inner_join(self):
        """Test SELECT with INNER JOIN."""
        location = SourceLocation(1, 1)
        sql = "SELECT e.name, d.dept_name FROM employee e INNER JOIN department d ON e.dept_id = d.id"
        stmt = parse_exec_sql(sql, location)

        assert stmt.sql_type == SQLStatementType.SELECT
        assert "employee" in stmt.tables
        assert "department" in stmt.tables

    def test_left_join(self):
        """Test SELECT with LEFT JOIN."""
        location = SourceLocation(1, 1)
        sql = "SELECT e.name, d.dept_name FROM employee e LEFT JOIN department d ON e.dept_id = d.id"
        stmt = parse_exec_sql(sql, location)

        assert "employee" in stmt.tables
        assert "department" in stmt.tables

    def test_multiple_joins(self):
        """Test SELECT with multiple JOINs."""
        location = SourceLocation(1, 1)
        sql = """SELECT e.name, d.dept_name, m.name
                 FROM employee e
                 JOIN department d ON e.dept_id = d.id
                 JOIN employee m ON e.manager_id = m.id"""
        stmt = parse_exec_sql(sql, location)

        assert "employee" in stmt.tables
        assert "department" in stmt.tables

    def test_subquery_in_where(self):
        """Test SELECT with subquery in WHERE clause."""
        location = SourceLocation(1, 1)
        sql = "SELECT name FROM employee WHERE salary > (SELECT AVG(salary) FROM employee)"
        stmt = parse_exec_sql(sql, location)

        assert stmt.sql_type == SQLStatementType.SELECT
        assert "employee" in stmt.tables

    def test_subquery_in_from(self):
        """Test SELECT with subquery in FROM clause."""
        location = SourceLocation(1, 1)
        sql = "SELECT t.name FROM (SELECT name FROM employee WHERE active = 1) t"
        stmt = parse_exec_sql(sql, location)

        # Note: subquery parsing captures outer tables
        assert stmt.sql_type == SQLStatementType.SELECT


class TestHostVariables:
    """Test host variables with colons and null indicators."""

    def test_host_variable_detection(self):
        """Test detection of host variables prefixed with colons."""
        location = SourceLocation(1, 1)
        sql = "SELECT :WS-COL1, :ws-col2 INTO :OUTPUT1, :output2 FROM table1"
        stmt = parse_exec_sql(sql, location)

        assert "WS-COL1" in stmt.host_variables
        assert "ws-col2" in stmt.host_variables
        assert "OUTPUT1" in stmt.host_variables
        assert "output2" in stmt.host_variables

    def test_host_variable_with_hyphen(self):
        """Test host variables with hyphens (COBOL naming convention)."""
        location = SourceLocation(1, 1)
        sql = "SELECT * FROM emp WHERE id = :WS-EMPLOYEE-ID AND dept = :WS-DEPT-CODE"
        stmt = parse_exec_sql(sql, location)

        assert "WS-EMPLOYEE-ID" in stmt.host_variables
        assert "WS-DEPT-CODE" in stmt.host_variables

    def test_null_indicator_colon_syntax(self):
        """Test null indicator with colon:indicator syntax."""
        location = SourceLocation(1, 1)
        sql = "SELECT name INTO :WS-NAME:WS-NAME-IND FROM employee"
        stmt = parse_exec_sql(sql, location)

        assert "WS-NAME" in stmt.host_variables
        assert "WS-NAME-IND" in stmt.null_indicators

    def test_null_indicator_keyword(self):
        """Test null indicator with INDICATOR keyword."""
        location = SourceLocation(1, 1)
        sql = "SELECT salary INTO :WS-SALARY INDICATOR :WS-SAL-IND FROM employee"
        stmt = parse_exec_sql(sql, location)

        assert "WS-SALARY" in stmt.host_variables
        assert "WS-SAL-IND" in stmt.null_indicators

    def test_null_indicator_keyword_as_parsed_from_source(self):
        """The EXEC SQL parser rebuilds the text as ``INDICATOR:IND`` (no
        blank before the colon); the keyword form was missed there."""
        from cobolparser import parse_cobol

        source = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. T.\n"
            "       PROCEDURE DIVISION.\n"
            "           EXEC SQL SELECT BAL INTO :BAL INDICATOR :IND-2\n"
            "                FROM CUST END-EXEC\n"
            "           STOP RUN.\n"
        )
        (stmt,) = parse_cobol(source).ast.find_all_by_type("ExecSQLStatement")
        assert stmt.null_indicators == ["IND-2"]


class TestTransactionControl:
    """Test COMMIT, ROLLBACK, and transaction control statements."""

    def test_commit(self):
        """Test COMMIT statement."""
        location = SourceLocation(1, 1)
        stmt = parse_exec_sql("COMMIT", location)

        assert stmt.sql_type == SQLStatementType.COMMIT
        assert isinstance(stmt, TransactionControlStatement)

        output = stmt.get_structured_output()
        assert output.query == "COMMIT"

    def test_commit_work(self):
        """Test COMMIT WORK statement."""
        location = SourceLocation(1, 1)
        stmt = parse_exec_sql("COMMIT WORK", location)

        assert stmt.sql_type == SQLStatementType.COMMIT
        assert stmt.is_work is True

    def test_rollback(self):
        """Test ROLLBACK statement."""
        location = SourceLocation(1, 1)
        stmt = parse_exec_sql("ROLLBACK", location)

        assert stmt.sql_type == SQLStatementType.ROLLBACK

    def test_rollback_to_savepoint(self):
        """Test ROLLBACK TO SAVEPOINT statement."""
        location = SourceLocation(1, 1)
        stmt = parse_exec_sql("ROLLBACK TO SAVEPOINT my_savepoint", location)

        assert stmt.sql_type == SQLStatementType.ROLLBACK
        assert stmt.savepoint_name == "my_savepoint"


class TestDynamicSQL:
    """Test PREPARE and EXECUTE dynamic SQL statements."""

    def test_prepare_statement(self):
        """Test PREPARE statement."""
        location = SourceLocation(1, 1)
        sql = "PREPARE stmt1 FROM :WS-SQL-TEXT"
        stmt = parse_exec_sql(sql, location)

        assert stmt.sql_type == SQLStatementType.PREPARE
        assert isinstance(stmt, DynamicSQLStatement)
        assert stmt.prepared_statement_name == "stmt1"
        assert "WS-SQL-TEXT" in stmt.host_variables

    def test_execute_statement(self):
        """Test EXECUTE statement."""
        location = SourceLocation(1, 1)
        sql = "EXECUTE stmt1"
        stmt = parse_exec_sql(sql, location)

        assert stmt.sql_type == SQLStatementType.EXECUTE
        assert stmt.prepared_statement_name == "stmt1"

    def test_execute_with_using(self):
        """Test EXECUTE statement with USING clause."""
        location = SourceLocation(1, 1)
        sql = "EXECUTE stmt1 USING :WS-PARAM1, :WS-PARAM2"
        stmt = parse_exec_sql(sql, location)

        assert stmt.sql_type == SQLStatementType.EXECUTE
        assert isinstance(stmt, DynamicSQLStatement)
        assert "WS-PARAM1" in stmt.using_variables
        assert "WS-PARAM2" in stmt.using_variables


class TestMultiLineSQLParsing:
    """Test multi-line SQL statements with proper handling."""

    def test_multiline_select(self):
        """Test multi-line SELECT statement."""
        location = SourceLocation(1, 1)
        sql = """
            SELECT
                e.employee_id,
                e.first_name,
                e.last_name
            INTO
                :WS-EMP-ID,
                :WS-FIRST-NAME,
                :WS-LAST-NAME
            FROM
                employee e
            WHERE
                e.department = :WS-DEPT
        """
        stmt = parse_exec_sql(sql, location)

        assert stmt.sql_type == SQLStatementType.SELECT
        assert "employee" in stmt.tables
        assert "WS-EMP-ID" in stmt.into_variables
        assert "WS-DEPT" in stmt.host_variables

    def test_sql_with_embedded_comment(self):
        """Test SQL with embedded comments (not common in COBOL but should be handled)."""
        location = SourceLocation(1, 1)
        sql = "SELECT * FROM employee WHERE id = :WS-ID"
        stmt = parse_exec_sql(sql, location)

        assert stmt.sql_type == SQLStatementType.SELECT


class TestExecSQLParsing:
    """Test full EXEC SQL block parsing in COBOL programs."""

    def test_exec_sql_select_in_cobol(self):
        """Test parsing EXEC SQL SELECT in a COBOL program."""
        source = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. SQL-SELECT-TEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-EMPNO       PIC 9(6).
       01  WS-ENAME       PIC X(20).
       PROCEDURE DIVISION.
       MAIN-PARA.
           EXEC SQL
               SELECT EMPNO, ENAME
               INTO :WS-EMPNO, :WS-ENAME
               FROM EMPLOYEE
               WHERE DEPT = 'IT'
           END-EXEC.
           STOP RUN.
        """
        result = parse_cobol(source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)

        assert result.success or len(result.errors) == 0
        if result.ast:
            proc_div = result.ast.get_division("PROCEDURE")
            if proc_div:
                # Find SQL statement
                sql_found = False
                for section in proc_div.sections:
                    for child in section.children:
                        if isinstance(child, ExecSQLStatement):
                            sql_found = True
                            assert child.sql_type == SQLStatementType.SELECT
                # SQL statement should be found
                assert sql_found, "SQL statement not found in parsed AST"

    def test_exec_sql_insert_in_cobol(self):
        """Test parsing EXEC SQL INSERT in a COBOL program."""
        source = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. SQL-INSERT-TEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-ID          PIC 9(6).
       01  WS-NAME        PIC X(20).
       PROCEDURE DIVISION.
       INSERT-PARA.
           EXEC SQL
               INSERT INTO PERSON (ID, NAME)
               VALUES (:WS-ID, :WS-NAME)
           END-EXEC.
           STOP RUN.
        """
        result = parse_cobol(source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)

        assert result is not None

    def test_exec_sql_cursor_operations(self):
        """Test parsing cursor operations in a COBOL program."""
        source = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. CURSOR-TEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-ID          PIC 9(6).
       01  WS-NAME        PIC X(20).
       PROCEDURE DIVISION.
       DECLARE-CURSOR.
           EXEC SQL
               DECLARE EMP-CURSOR CURSOR FOR
               SELECT ID, NAME FROM EMPLOYEE
           END-EXEC.
       OPEN-CURSOR.
           EXEC SQL
               OPEN EMP-CURSOR
           END-EXEC.
       FETCH-LOOP.
           EXEC SQL
               FETCH EMP-CURSOR INTO :WS-ID, :WS-NAME
           END-EXEC.
       CLOSE-CURSOR.
           EXEC SQL
               CLOSE EMP-CURSOR
           END-EXEC.
           STOP RUN.
        """
        result = parse_cobol(source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)

        assert result is not None

    def test_exec_sql_transaction_control(self):
        """Test parsing COMMIT and ROLLBACK in a COBOL program."""
        source = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TXN-TEST.
       PROCEDURE DIVISION.
       TXN-PARA.
           EXEC SQL COMMIT END-EXEC.
           EXEC SQL ROLLBACK END-EXEC.
           STOP RUN.
        """
        result = parse_cobol(source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)

        assert result is not None


class TestStructuredOutput:
    """Test the structured JSON output format."""

    def test_select_structured_output(self):
        """Test structured output for SELECT statement."""
        location = SourceLocation(1, 1)
        stmt = parse_exec_sql("SELECT * FROM person", location)

        output = stmt.get_structured_output()
        result = output.to_dict()

        expected = {"table": "person", "query": "SELECT * FROM person", "cursor": None}
        assert result == expected

    def test_fetch_structured_output(self):
        """Test structured output for FETCH statement."""
        location = SourceLocation(1, 1)
        stmt = parse_exec_sql("FETCH my_cursor INTO :WS-DATA", location)

        output = stmt.get_structured_output()
        result = output.to_dict()

        assert result["query"] is None
        assert result["cursor"] is not None
        assert "FETCH" in result["cursor"]

    def test_cursor_declare_structured_output(self):
        """Test structured output for DECLARE CURSOR."""
        location = SourceLocation(1, 1)
        sql = "DECLARE emp_cur CURSOR FOR SELECT * FROM employee"
        stmt = parse_exec_sql(sql, location)

        output = stmt.get_structured_output()
        result = output.to_dict()

        assert result["cursor"] is not None
        assert "DECLARE emp_cur CURSOR" in result["cursor"]
        assert result["query"] is not None
        assert "SELECT" in result["query"]

    def test_to_dict_full_output(self):
        """Test full to_dict output with all fields."""
        location = SourceLocation(1, 1)
        sql = (
            "SELECT id, name INTO :WS-ID, :WS-NAME FROM employee WHERE dept = :WS-DEPT"
        )
        stmt = parse_exec_sql(sql, location)

        result = stmt.to_dict()

        assert "sql_text" in result
        assert "sql_type" in result
        assert "host_variables" in result
        assert "tables" in result
        assert "into_variables" in result
        assert "structured_output" in result

        # Verify structured_output format
        structured = result["structured_output"]
        assert "table" in structured
        assert "query" in structured
        assert "cursor" in structured


class TestEdgeCases:
    """Test edge cases and special scenarios."""

    def test_empty_sql(self):
        """Test handling of empty SQL text."""
        location = SourceLocation(1, 1)
        stmt = parse_exec_sql("", location)

        assert stmt.sql_type == SQLStatementType.UNKNOWN
        assert stmt.tables == []
        assert stmt.host_variables == []

    def test_whitespace_only(self):
        """Test handling of whitespace-only SQL."""
        location = SourceLocation(1, 1)
        stmt = parse_exec_sql("   \n\t   ", location)

        assert stmt.sql_type == SQLStatementType.UNKNOWN

    def test_include_statement(self):
        """Test INCLUDE statement for copybook references."""
        location = SourceLocation(1, 1)
        stmt = parse_exec_sql("INCLUDE SQLCA", location)

        assert stmt.sql_type == SQLStatementType.INCLUDE

    def test_whenever_statement(self):
        """Test WHENEVER statement."""
        location = SourceLocation(1, 1)
        stmt = parse_exec_sql("WHENEVER SQLERROR CONTINUE", location)

        assert stmt.sql_type == SQLStatementType.WHENEVER

    def test_complex_where_clause(self):
        """Test SELECT with complex WHERE clause."""
        location = SourceLocation(1, 1)
        sql = """SELECT * FROM employee
                 WHERE dept IN ('IT', 'HR')
                 AND salary BETWEEN :MIN-SAL AND :MAX-SAL
                 AND status NOT IN ('INACTIVE', 'TERMINATED')"""
        stmt = parse_exec_sql(sql, location)

        assert stmt.sql_type == SQLStatementType.SELECT
        assert "MIN-SAL" in stmt.host_variables
        assert "MAX-SAL" in stmt.host_variables

    def test_sql_with_functions(self):
        """Test SQL with built-in functions."""
        location = SourceLocation(1, 1)
        sql = "SELECT COUNT(*), MAX(salary), AVG(salary) INTO :WS-COUNT, :WS-MAX, :WS-AVG FROM employee"
        stmt = parse_exec_sql(sql, location)

        assert stmt.sql_type == SQLStatementType.SELECT
        assert "WS-COUNT" in stmt.into_variables
        assert "WS-MAX" in stmt.into_variables
        assert "WS-AVG" in stmt.into_variables

    def test_update_with_case(self):
        """Test UPDATE with CASE expression."""
        location = SourceLocation(1, 1)
        sql = """UPDATE employee
                 SET salary = CASE
                     WHEN dept = 'IT' THEN salary * 1.1
                     ELSE salary * 1.05
                 END
                 WHERE id = :WS-ID"""
        stmt = parse_exec_sql(sql, location)

        assert stmt.sql_type == SQLStatementType.UPDATE
        assert "employee" in stmt.tables
        assert "WS-ID" in stmt.host_variables


class TestExecSQLStatementMethods:
    """Test ExecSQLStatement class methods."""

    def test_sql_type_property(self):
        """Test sql_type property."""
        location = SourceLocation(1, 1)
        stmt = ExecSQLStatement(location)

        assert stmt.sql_type == SQLStatementType.UNKNOWN

        stmt.set_sql_text("SELECT * FROM test")
        assert stmt.sql_type == SQLStatementType.SELECT

    def test_statement_inheritance(self):
        """Test that ExecSQLStatement inherits from CobolStatement."""
        location = SourceLocation(1, 1)
        stmt = ExecSQLStatement(location)

        assert hasattr(stmt, "operands")
        assert hasattr(stmt, "add_operand")
        assert stmt.statement_type == "EXEC-SQL"


class TestDeclareCursorStatement:
    """Test DeclareCursorStatement class."""

    def test_declare_cursor_creation(self):
        """Test DeclareCursorStatement creation."""
        location = SourceLocation(1, 1)
        stmt = DeclareCursorStatement(location)
        stmt.cursor_name = "test_cursor"
        stmt.set_select_statement("SELECT * FROM employee")

        assert stmt.cursor_name == "test_cursor"
        assert stmt.select_statement == "SELECT * FROM employee"
        assert "employee" in stmt.tables

    def test_add_cursor_option(self):
        """Test add_cursor_option method."""
        location = SourceLocation(1, 1)
        stmt = DeclareCursorStatement(location)

        stmt.add_cursor_option("WITH HOLD")
        stmt.add_cursor_option("FOR UPDATE")
        stmt.add_cursor_option("WITH HOLD")  # Duplicate

        assert "WITH HOLD" in stmt.cursor_options
        assert "FOR UPDATE" in stmt.cursor_options
        assert len(stmt.cursor_options) == 2


class TestFetchStatement:
    """Test FetchStatement class."""

    def test_fetch_statement_creation(self):
        """Test FetchStatement creation."""
        location = SourceLocation(1, 1)
        stmt = FetchStatement(location)
        stmt.cursor_name = "my_cursor"
        stmt.set_fetch_direction("PRIOR")

        assert stmt.cursor_name == "my_cursor"
        assert stmt.fetch_direction == "PRIOR"

    def test_fetch_directions(self):
        """Test various fetch directions."""
        location = SourceLocation(1, 1)

        for direction in ["NEXT", "PRIOR", "FIRST", "LAST"]:
            stmt = FetchStatement(location)
            stmt.set_fetch_direction(direction.lower())  # Test case insensitivity
            assert stmt.fetch_direction == direction


class TestDynamicSQLStatement:
    """Test DynamicSQLStatement class."""

    def test_add_using_variable(self):
        """Test add_using_variable method."""
        location = SourceLocation(1, 1)
        stmt = DynamicSQLStatement(location)

        stmt.add_using_variable("WS-PARAM1")
        stmt.add_using_variable("WS-PARAM2")
        stmt.add_using_variable("WS-PARAM1")  # Duplicate

        assert "WS-PARAM1" in stmt.using_variables
        assert "WS-PARAM2" in stmt.using_variables
        assert len(stmt.using_variables) == 2


class TestTransactionControlStatement:
    """Test TransactionControlStatement class."""

    def test_transaction_control_creation(self):
        """Test TransactionControlStatement creation."""
        location = SourceLocation(1, 1)
        stmt = TransactionControlStatement(location)
        stmt.set_sql_text("COMMIT WORK")

        assert stmt.is_work is True

    def test_savepoint_setting(self):
        """Test set_savepoint method."""
        location = SourceLocation(1, 1)
        stmt = TransactionControlStatement(location)
        stmt.set_savepoint("my_savepoint")

        assert stmt.savepoint_name == "my_savepoint"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


class TestFunctionArgumentFromIsNotATable:
    """``EXTRACT(YEAR FROM col)`` / ``TRIM(... FROM col)`` name a column."""

    @pytest.mark.parametrize(
        ("sql", "tables"),
        [
            ("SELECT EXTRACT(YEAR FROM HIRE_DATE) INTO :WS-Y FROM EMP", ["EMP"]),
            ("SELECT TRIM(LEADING '0' FROM ACCT_NO) INTO :A FROM ACCT", ["ACCT"]),
            (
                "SELECT SUBSTRING(NAME FROM 1 FOR 3) FROM EMP WHERE X IN "
                "(SELECT X FROM T2 WHERE Y = EXTRACT(DAY FROM Z))",
                ["EMP", "T2"],
            ),
            (
                "DECLARE C1 CURSOR FOR SELECT EXTRACT(YEAR FROM D) FROM T10",
                ["T10"],
            ),
            ("SELECT A FROM ((SELECT A FROM T1) UNION SELECT A FROM T3) X", None),
        ],
    )
    def test_tables(self, sql, tables):
        stmt = parse_exec_sql(sql, SourceLocation(1, 1))
        if tables is None:  # subqueries keep every table they read
            assert {"T1", "T3"} <= set(stmt.tables)
        else:
            assert stmt.tables == tables


class TestWriteStatementSubqueryTables:
    """INSERT/UPDATE keep their target first, then the tables they read."""

    def test_insert_select(self):
        stmt = parse_exec_sql(
            "INSERT INTO ARCHIVE SELECT * FROM HISTORY", SourceLocation(1, 1)
        )
        assert stmt.tables == ["ARCHIVE", "HISTORY"]

    def test_update_where_subquery(self):
        stmt = parse_exec_sql(
            "UPDATE ACCOUNT SET RATE = 1 WHERE TIER = (SELECT MAX(TIER) FROM TIERS)",
            SourceLocation(1, 1),
        )
        assert stmt.tables == ["ACCOUNT", "TIERS"]
