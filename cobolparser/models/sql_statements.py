"""
SQL statement AST nodes for embedded SQL in COBOL programs.

This module provides comprehensive AST nodes for all types of SQL statements
embedded within COBOL EXEC SQL blocks, with structured output for analysis.
"""

from typing import ClassVar, Dict, Any, List, Optional, Set, Union
from dataclasses import dataclass, field
import re

from .ast_base import ASTNode, SourceLocation
from .statements import CobolStatement

# Pre-compiled regex patterns for SQL statement parsing (avoids re-compilation per statement)
_SQL_HOST_VAR_RE = re.compile(r':([A-Za-z][A-Za-z0-9-]*)')
_SQL_INDICATOR_RE = re.compile(r':([A-Za-z][A-Za-z0-9-]*)\s*:\s*([A-Za-z][A-Za-z0-9-]*)')
_SQL_INDICATOR_KW_RE = re.compile(r'INDICATOR\s+:([A-Za-z][A-Za-z0-9-]*)', re.IGNORECASE)
_SQL_FROM_TABLE_RE = re.compile(r'FROM\s+([A-Za-z_][A-Za-z0-9_]*)', re.IGNORECASE)
_SQL_JOIN_TABLE_RE = re.compile(r'JOIN\s+([A-Za-z_][A-Za-z0-9_]*)', re.IGNORECASE)
_SQL_INTO_TABLE_RE = re.compile(r'INTO\s+([A-Za-z_][A-Za-z0-9_]*)', re.IGNORECASE)
_SQL_UPDATE_TABLE_RE = re.compile(r'UPDATE\s+([A-Za-z_][A-Za-z0-9_]*)', re.IGNORECASE)
_SQL_INTO_VARS_RE = re.compile(r'INTO\s+(:[\w-]+(?:\s*,\s*:[\w-]+)*)', re.IGNORECASE)
_SQL_DECLARE_CURSOR_RE = re.compile(r'DECLARE\s+([A-Za-z_][A-Za-z0-9_-]*)\s+CURSOR', re.IGNORECASE)
_SQL_FETCH_RE = re.compile(r'FETCH\s+(?:NEXT\s+)?(?:FROM\s+)?([A-Za-z_][A-Za-z0-9_-]*)', re.IGNORECASE)
_SQL_OPEN_RE = re.compile(r'OPEN\s+([A-Za-z_][A-Za-z0-9_-]*)', re.IGNORECASE)
_SQL_CLOSE_RE = re.compile(r'CLOSE\s+([A-Za-z_][A-Za-z0-9_-]*)', re.IGNORECASE)
_SQL_PREPARE_RE = re.compile(r'PREPARE\s+([A-Za-z_][A-Za-z0-9_-]*)\s+FROM', re.IGNORECASE)
_SQL_EXECUTE_RE = re.compile(r'EXECUTE\s+([A-Za-z_][A-Za-z0-9_-]*)', re.IGNORECASE)
_SQL_FOR_SELECT_RE = re.compile(r'FOR\s+(SELECT.+)', re.IGNORECASE | re.DOTALL)
_SQL_USING_VARS_RE = re.compile(r'USING\s+(:[\w-]+(?:\s*,\s*:[\w-]+)*)', re.IGNORECASE)
_SQL_SAVEPOINT_RE = re.compile(r'TO\s+(?:SAVEPOINT\s+)?([A-Za-z_][A-Za-z0-9_-]*)', re.IGNORECASE)

# SQL keyword filter set (used in table extraction)
_SQL_KEYWORDS = frozenset(['SELECT', 'INSERT', 'UPDATE', 'DELETE',
                           'WHERE', 'INTO', 'VALUES', 'SET', 'AND',
                           'OR', 'NULL', 'NOT', 'IN', 'LIKE'])


@dataclass
class SQLStatementInfo:
    """Structured information about a parsed SQL statement."""
    table: Optional[str] = None
    query: Optional[str] = None
    cursor: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "table": self.table,
            "query": self.query,
            "cursor": self.cursor
        }


class SQLStatementType:
    """SQL statement type constants."""
    SELECT: ClassVar[str] = "SELECT"
    INSERT: ClassVar[str] = "INSERT"
    UPDATE: ClassVar[str] = "UPDATE"
    DELETE: ClassVar[str] = "DELETE"
    DECLARE_CURSOR: ClassVar[str] = "DECLARE CURSOR"
    OPEN_CURSOR: ClassVar[str] = "OPEN"
    FETCH: ClassVar[str] = "FETCH"
    CLOSE_CURSOR: ClassVar[str] = "CLOSE"
    COMMIT: ClassVar[str] = "COMMIT"
    ROLLBACK: ClassVar[str] = "ROLLBACK"
    PREPARE: ClassVar[str] = "PREPARE"
    EXECUTE: ClassVar[str] = "EXECUTE"
    INCLUDE: ClassVar[str] = "INCLUDE"
    WHENEVER: ClassVar[str] = "WHENEVER"
    UNKNOWN: ClassVar[str] = "UNKNOWN"


class ExecSQLStatement(CobolStatement):
    """AST node for EXEC SQL statements with enhanced parsing.

    Provides structured output with table, query, and cursor information
    as well as comprehensive host variable detection.
    """

    def __init__(self, location: SourceLocation):
        super().__init__("EXEC-SQL", location)
        self.sql_text: str = ""
        self._sql_type: str = SQLStatementType.UNKNOWN
        self.host_variables: List[str] = []
        self.null_indicators: List[str] = []
        self.tables: List[str] = []
        self.cursor_name: Optional[str] = None
        self.prepared_statement_name: Optional[str] = None
        self.into_variables: List[str] = []

    @property
    def sql_type(self) -> str:
        """Return SQL type (SELECT, INSERT, UPDATE, DELETE, etc.)."""
        return self._sql_type

    def set_sql_text(self, sql_text: str) -> None:
        """Set the SQL statement text and parse its components."""
        self.sql_text = sql_text.strip()
        self._parse_sql_statement()

    def _parse_sql_statement(self) -> None:
        """Parse the SQL statement to extract type, tables, host variables, etc."""
        if not self.sql_text:
            return

        # Normalize whitespace for easier parsing
        normalized = ' '.join(self.sql_text.split())
        upper_sql = normalized.upper()

        # Determine SQL type
        self._sql_type = self._determine_sql_type(upper_sql)

        # Extract host variables (:variable_name)
        self._extract_host_variables(normalized)

        # Extract table names
        self._extract_tables(normalized)

        # Extract INTO variables
        self._extract_into_variables(normalized)

        # Extract cursor name if applicable
        self._extract_cursor_info(normalized)

    def _determine_sql_type(self, upper_sql: str) -> str:
        """Determine the type of SQL statement."""
        # Check for cursor operations first
        if upper_sql.startswith("DECLARE") and "CURSOR" in upper_sql:
            return SQLStatementType.DECLARE_CURSOR
        elif upper_sql.startswith("FETCH"):
            return SQLStatementType.FETCH
        elif upper_sql.startswith("OPEN"):
            return SQLStatementType.OPEN_CURSOR
        elif upper_sql.startswith("CLOSE"):
            return SQLStatementType.CLOSE_CURSOR

        # DML statements
        if upper_sql.startswith("SELECT"):
            return SQLStatementType.SELECT
        elif upper_sql.startswith("INSERT"):
            return SQLStatementType.INSERT
        elif upper_sql.startswith("UPDATE"):
            return SQLStatementType.UPDATE
        elif upper_sql.startswith("DELETE"):
            return SQLStatementType.DELETE

        # Transaction control
        if upper_sql.startswith("COMMIT"):
            return SQLStatementType.COMMIT
        elif upper_sql.startswith("ROLLBACK"):
            return SQLStatementType.ROLLBACK

        # Dynamic SQL
        if upper_sql.startswith("PREPARE"):
            return SQLStatementType.PREPARE
        elif upper_sql.startswith("EXECUTE"):
            return SQLStatementType.EXECUTE

        # Other
        if upper_sql.startswith("INCLUDE"):
            return SQLStatementType.INCLUDE
        elif upper_sql.startswith("WHENEVER"):
            return SQLStatementType.WHENEVER

        return SQLStatementType.UNKNOWN

    def _extract_host_variables(self, sql: str) -> None:
        """Extract host variables prefixed with colon."""
        matches = _SQL_HOST_VAR_RE.findall(sql)

        for var in matches:
            if var.upper() not in ['NULL', 'INDICATOR']:
                if var not in self.host_variables:
                    self.host_variables.append(var)

        # Extract null indicators (either :var:indicator or INDICATOR :var)
        indicator_matches = _SQL_INDICATOR_RE.findall(sql)
        for var, indicator in indicator_matches:
            if indicator not in self.null_indicators:
                self.null_indicators.append(indicator)

        # Also check for INDICATOR keyword pattern
        indicator_keyword_matches = _SQL_INDICATOR_KW_RE.findall(sql)
        for indicator in indicator_keyword_matches:
            if indicator not in self.null_indicators:
                self.null_indicators.append(indicator)

    def _extract_tables(self, sql: str) -> None:
        """Extract table names from the SQL statement."""
        # Use pre-compiled patterns based on SQL type
        compiled_patterns = []

        if self._sql_type == SQLStatementType.SELECT:
            compiled_patterns.append(_SQL_FROM_TABLE_RE)
            compiled_patterns.append(_SQL_JOIN_TABLE_RE)

        elif self._sql_type == SQLStatementType.INSERT:
            compiled_patterns.append(_SQL_INTO_TABLE_RE)

        elif self._sql_type == SQLStatementType.UPDATE:
            compiled_patterns.append(_SQL_UPDATE_TABLE_RE)

        elif self._sql_type == SQLStatementType.DELETE:
            compiled_patterns.append(_SQL_FROM_TABLE_RE)

        elif self._sql_type == SQLStatementType.DECLARE_CURSOR:
            compiled_patterns.append(_SQL_FROM_TABLE_RE)
            compiled_patterns.append(_SQL_JOIN_TABLE_RE)

        elif self._sql_type == SQLStatementType.FETCH:
            pass

        for pattern in compiled_patterns:
            matches = pattern.findall(sql)
            for table in matches:
                if table.upper() not in _SQL_KEYWORDS:
                    if table not in self.tables:
                        self.tables.append(table)

    def _extract_into_variables(self, sql: str) -> None:
        """Extract variables from INTO clause."""
        match = _SQL_INTO_VARS_RE.search(sql)
        if match:
            into_clause = match.group(1)
            vars_matches = _SQL_HOST_VAR_RE.findall(into_clause)
            self.into_variables = vars_matches

    def _extract_cursor_info(self, sql: str) -> None:
        """Extract cursor name if this is a cursor-related statement."""
        if self._sql_type == SQLStatementType.DECLARE_CURSOR:
            match = _SQL_DECLARE_CURSOR_RE.search(sql)
            if match:
                self.cursor_name = match.group(1)

        elif self._sql_type == SQLStatementType.FETCH:
            match = _SQL_FETCH_RE.search(sql)
            if match:
                cursor_candidate = match.group(1)
                if cursor_candidate.upper() not in ['INTO', 'NEXT', 'PRIOR', 'FIRST', 'LAST']:
                    self.cursor_name = cursor_candidate

        elif self._sql_type == SQLStatementType.OPEN_CURSOR:
            match = _SQL_OPEN_RE.search(sql)
            if match:
                self.cursor_name = match.group(1)

        elif self._sql_type == SQLStatementType.CLOSE_CURSOR:
            match = _SQL_CLOSE_RE.search(sql)
            if match:
                self.cursor_name = match.group(1)

        # Check for PREPARE statement
        if self._sql_type == SQLStatementType.PREPARE:
            match = _SQL_PREPARE_RE.search(sql)
            if match:
                self.prepared_statement_name = match.group(1)

        elif self._sql_type == SQLStatementType.EXECUTE:
            match = _SQL_EXECUTE_RE.search(sql)
            if match:
                self.prepared_statement_name = match.group(1)

    def add_host_variable(self, variable: str) -> None:
        """Add a host variable used in the SQL statement."""
        if variable not in self.host_variables:
            self.host_variables.append(variable)

    def get_structured_output(self) -> SQLStatementInfo:
        """Get structured output with table, query, and cursor fields."""
        result = SQLStatementInfo()

        # Set table (primary table for the operation)
        if self.tables:
            result.table = self.tables[0]

        # Set query or cursor based on statement type
        if self._sql_type in [SQLStatementType.FETCH, SQLStatementType.OPEN_CURSOR,
                              SQLStatementType.CLOSE_CURSOR]:
            # For cursor operations, output goes to cursor field
            if self.cursor_name:
                result.cursor = f"{self._sql_type} {self.cursor_name}"
                if self._sql_type == SQLStatementType.FETCH and self.into_variables:
                    result.cursor = f"FETCH :{','.join(self.into_variables)} FROM {self.cursor_name}"
        elif self._sql_type == SQLStatementType.DECLARE_CURSOR:
            # For DECLARE CURSOR, both query and cursor are relevant
            result.cursor = f"DECLARE {self.cursor_name} CURSOR"
            # Extract the SELECT portion
            match = _SQL_FOR_SELECT_RE.search(self.sql_text)
            if match:
                result.query = match.group(1).strip()
        else:
            # For regular DML statements, output goes to query field
            result.query = self.sql_text

        return result

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        result = super().to_dict()
        structured = self.get_structured_output()
        result.update({
            "sql_text": self.sql_text,
            "sql_type": self.sql_type,
            "host_variables": self.host_variables,
            "null_indicators": self.null_indicators,
            "tables": self.tables,
            "cursor_name": self.cursor_name,
            "prepared_statement_name": self.prepared_statement_name,
            "into_variables": self.into_variables,
            "structured_output": structured.to_dict()
        })
        return result


class DeclareCursorStatement(ExecSQLStatement):
    """AST node specifically for DECLARE CURSOR statements."""

    def __init__(self, location: SourceLocation):
        super().__init__(location)
        self.statement_type = "DECLARE-CURSOR"
        self.select_statement: Optional[str] = None
        self.cursor_options: List[str] = []  # WITH HOLD, FOR UPDATE, etc.

    def set_select_statement(self, select_sql: str) -> None:
        """Set the SELECT statement for the cursor."""
        self.select_statement = select_sql.strip()
        # Parse tables from the SELECT
        self._extract_tables_from_select(select_sql)

    def _extract_tables_from_select(self, sql: str) -> None:
        """Extract tables from the cursor's SELECT statement."""
        compiled_patterns = [_SQL_FROM_TABLE_RE, _SQL_JOIN_TABLE_RE]
        for pattern in compiled_patterns:
            matches = pattern.findall(sql)
            for table in matches:
                if table.upper() not in ['SELECT', 'WHERE', 'AND', 'OR', 'NOT', 'IN']:
                    if table not in self.tables:
                        self.tables.append(table)

    def add_cursor_option(self, option: str) -> None:
        """Add a cursor option (WITH HOLD, FOR UPDATE, etc.)."""
        if option not in self.cursor_options:
            self.cursor_options.append(option)

    def get_structured_output(self) -> SQLStatementInfo:
        """Get structured output for DECLARE CURSOR."""
        result = SQLStatementInfo()
        result.cursor = f"DECLARE {self.cursor_name} CURSOR"
        if self.select_statement:
            result.query = self.select_statement
        if self.tables:
            result.table = self.tables[0]
        return result

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        result = super().to_dict()
        result.update({
            "select_statement": self.select_statement,
            "cursor_options": self.cursor_options
        })
        return result


class FetchStatement(ExecSQLStatement):
    """AST node specifically for FETCH statements."""

    def __init__(self, location: SourceLocation):
        super().__init__(location)
        self.statement_type = "FETCH"
        self.fetch_direction: str = "NEXT"  # NEXT, PRIOR, FIRST, LAST
        self.fetch_count: Optional[int] = None

    def set_fetch_direction(self, direction: str) -> None:
        """Set fetch direction (NEXT, PRIOR, FIRST, LAST)."""
        self.fetch_direction = direction.upper()

    def get_structured_output(self) -> SQLStatementInfo:
        """Get structured output for FETCH."""
        result = SQLStatementInfo()
        if self.into_variables:
            result.cursor = f"FETCH :{','.join(self.into_variables)} FROM {self.cursor_name or 'UNKNOWN'}"
        else:
            result.cursor = f"FETCH FROM {self.cursor_name or 'UNKNOWN'}"
        return result

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        result = super().to_dict()
        result.update({
            "fetch_direction": self.fetch_direction,
            "fetch_count": self.fetch_count
        })
        return result


class DynamicSQLStatement(ExecSQLStatement):
    """AST node for dynamic SQL (PREPARE/EXECUTE)."""

    def __init__(self, location: SourceLocation):
        super().__init__(location)
        self.statement_type = "DYNAMIC-SQL"
        self.dynamic_sql_text: Optional[str] = None
        self.using_variables: List[str] = []

    def set_dynamic_sql(self, sql: str) -> None:
        """Set the dynamic SQL text."""
        self.dynamic_sql_text = sql.strip()

    def add_using_variable(self, variable: str) -> None:
        """Add a variable to the USING clause."""
        if variable not in self.using_variables:
            self.using_variables.append(variable)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        result = super().to_dict()
        result.update({
            "dynamic_sql_text": self.dynamic_sql_text,
            "using_variables": self.using_variables
        })
        return result


class TransactionControlStatement(ExecSQLStatement):
    """AST node for transaction control statements (COMMIT, ROLLBACK)."""

    def __init__(self, location: SourceLocation):
        super().__init__(location)
        self.statement_type = "TRANSACTION-CONTROL"
        self.savepoint_name: Optional[str] = None
        self.is_work: bool = False  # COMMIT WORK vs COMMIT

    def set_sql_text(self, sql: str) -> None:
        """Set the SQL text and detect WORK keyword."""
        super().set_sql_text(sql)
        upper_sql = sql.upper()
        if "WORK" in upper_sql:
            self.is_work = True
        # Auto-detect savepoint
        match = _SQL_SAVEPOINT_RE.search(sql)
        if match:
            self.savepoint_name = match.group(1)

    def set_savepoint(self, savepoint: str) -> None:
        """Set savepoint name for ROLLBACK TO SAVEPOINT."""
        self.savepoint_name = savepoint

    def get_structured_output(self) -> SQLStatementInfo:
        """Get structured output for transaction control."""
        result = SQLStatementInfo()
        result.query = self.sql_text
        return result

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        result = super().to_dict()
        result.update({
            "savepoint_name": self.savepoint_name,
            "is_work": self.is_work
        })
        return result


def parse_exec_sql(sql_text: str, location: SourceLocation) -> ExecSQLStatement:
    """Factory function to parse EXEC SQL and return the appropriate statement type.

    Args:
        sql_text: The SQL text (without EXEC SQL and END-EXEC)
        location: Source location for the statement

    Returns:
        Appropriate ExecSQLStatement subclass based on the SQL type
    """
    normalized = ' '.join(sql_text.strip().split())
    upper_sql = normalized.upper()

    # Determine statement type and create appropriate node
    if upper_sql.startswith("DECLARE") and "CURSOR" in upper_sql:
        declare_stmt = DeclareCursorStatement(location)
        declare_stmt.set_sql_text(sql_text)
        # Extract cursor name
        match = _SQL_DECLARE_CURSOR_RE.search(sql_text)
        if match:
            declare_stmt.cursor_name = match.group(1)
        # Extract SELECT statement
        match = _SQL_FOR_SELECT_RE.search(sql_text)
        if match:
            declare_stmt.set_select_statement(match.group(1))
        # Extract cursor options
        if "WITH HOLD" in upper_sql:
            declare_stmt.add_cursor_option("WITH HOLD")
        if "FOR UPDATE" in upper_sql:
            declare_stmt.add_cursor_option("FOR UPDATE")
        return declare_stmt

    elif upper_sql.startswith("FETCH"):
        fetch_stmt = FetchStatement(location)
        fetch_stmt.set_sql_text(sql_text)
        # Extract direction
        for direction in ["NEXT", "PRIOR", "FIRST", "LAST"]:
            if direction in upper_sql:
                fetch_stmt.set_fetch_direction(direction)
                break
        return fetch_stmt

    elif upper_sql.startswith("PREPARE") or upper_sql.startswith("EXECUTE"):
        dynamic_stmt = DynamicSQLStatement(location)
        dynamic_stmt.set_sql_text(sql_text)
        # Extract USING variables
        match = _SQL_USING_VARS_RE.search(sql_text)
        if match:
            using_clause = match.group(1)
            vars_matches = _SQL_HOST_VAR_RE.findall(using_clause)
            for var in vars_matches:
                dynamic_stmt.add_using_variable(var)
        return dynamic_stmt

    elif upper_sql.startswith("COMMIT") or upper_sql.startswith("ROLLBACK"):
        txn_stmt = TransactionControlStatement(location)
        txn_stmt.set_sql_text(sql_text)
        if "WORK" in upper_sql:
            txn_stmt.is_work = True
        # Check for savepoint
        match = _SQL_SAVEPOINT_RE.search(sql_text)
        if match:
            txn_stmt.set_savepoint(match.group(1))
        return txn_stmt

    else:
        # Default to generic ExecSQLStatement
        generic_stmt = ExecSQLStatement(location)
        generic_stmt.set_sql_text(sql_text)
        return generic_stmt


__all__ = [
    "SQLStatementInfo",
    "SQLStatementType",
    "ExecSQLStatement",
    "DeclareCursorStatement",
    "FetchStatement",
    "DynamicSQLStatement",
    "TransactionControlStatement",
    "parse_exec_sql"
]
