"""
SQL statement AST nodes for embedded SQL in COBOL programs.

This module provides comprehensive AST nodes for all types of SQL statements
embedded within COBOL EXEC SQL blocks, with structured output for analysis.
"""

from typing import Dict, Any, List, Optional, Set
from dataclasses import dataclass, field
import re

from .ast_base import ASTNode, SourceLocation
from .statements import CobolStatement


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
    SELECT = "SELECT"
    INSERT = "INSERT"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    DECLARE_CURSOR = "DECLARE CURSOR"
    OPEN_CURSOR = "OPEN"
    FETCH = "FETCH"
    CLOSE_CURSOR = "CLOSE"
    COMMIT = "COMMIT"
    ROLLBACK = "ROLLBACK"
    PREPARE = "PREPARE"
    EXECUTE = "EXECUTE"
    INCLUDE = "INCLUDE"
    WHENEVER = "WHENEVER"
    UNKNOWN = "UNKNOWN"


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
        # Pattern: :variable-name (COBOL names can have hyphens)
        # Also handle null indicators like :var:indicator or :var INDICATOR :ind
        pattern = r':([A-Za-z][A-Za-z0-9-]*)'
        matches = re.findall(pattern, sql)
        
        for var in matches:
            if var.upper() not in ['NULL', 'INDICATOR']:
                if var not in self.host_variables:
                    self.host_variables.append(var)
                    
        # Extract null indicators (either :var:indicator or INDICATOR :var)
        indicator_pattern = r':([A-Za-z][A-Za-z0-9-]*)\s*:\s*([A-Za-z][A-Za-z0-9-]*)'
        indicator_matches = re.findall(indicator_pattern, sql)
        for var, indicator in indicator_matches:
            if indicator not in self.null_indicators:
                self.null_indicators.append(indicator)
                
        # Also check for INDICATOR keyword pattern
        indicator_keyword_pattern = r'INDICATOR\s+:([A-Za-z][A-Za-z0-9-]*)'
        indicator_keyword_matches = re.findall(indicator_keyword_pattern, sql, re.IGNORECASE)
        for indicator in indicator_keyword_matches:
            if indicator not in self.null_indicators:
                self.null_indicators.append(indicator)
                
    def _extract_tables(self, sql: str) -> None:
        """Extract table names from the SQL statement."""
        upper_sql = sql.upper()
        
        # Different patterns based on SQL type
        table_patterns = []
        
        if self._sql_type == SQLStatementType.SELECT:
            # FROM clause: FROM table [alias] [, table2 ...]
            # JOIN clauses: JOIN table [alias]
            table_patterns.append(r'FROM\s+([A-Za-z_][A-Za-z0-9_]*)')
            table_patterns.append(r'JOIN\s+([A-Za-z_][A-Za-z0-9_]*)')
            
        elif self._sql_type == SQLStatementType.INSERT:
            # INSERT INTO table
            table_patterns.append(r'INTO\s+([A-Za-z_][A-Za-z0-9_]*)')
            
        elif self._sql_type == SQLStatementType.UPDATE:
            # UPDATE table
            table_patterns.append(r'UPDATE\s+([A-Za-z_][A-Za-z0-9_]*)')
            
        elif self._sql_type == SQLStatementType.DELETE:
            # DELETE FROM table
            table_patterns.append(r'FROM\s+([A-Za-z_][A-Za-z0-9_]*)')
            
        elif self._sql_type == SQLStatementType.DECLARE_CURSOR:
            # DECLARE ... FOR SELECT ... FROM table
            table_patterns.append(r'FROM\s+([A-Za-z_][A-Za-z0-9_]*)')
            table_patterns.append(r'JOIN\s+([A-Za-z_][A-Za-z0-9_]*)')
            
        elif self._sql_type == SQLStatementType.FETCH:
            # FETCH ... FROM cursor_name - note: cursor_name is not a table
            # The "FROM" in FETCH refers to cursor, not table
            # Check if there's a cursor associated that might have table info
            pass
            
        for pattern in table_patterns:
            matches = re.findall(pattern, sql, re.IGNORECASE)
            for table in matches:
                # Filter out SQL keywords that might be mistakenly captured
                if table.upper() not in ['SELECT', 'INSERT', 'UPDATE', 'DELETE', 
                                         'WHERE', 'INTO', 'VALUES', 'SET', 'AND', 
                                         'OR', 'NULL', 'NOT', 'IN', 'LIKE']:
                    if table not in self.tables:
                        self.tables.append(table)
                        
    def _extract_into_variables(self, sql: str) -> None:
        """Extract variables from INTO clause."""
        # Pattern: INTO :var1, :var2, :var3
        into_pattern = r'INTO\s+(:[\w-]+(?:\s*,\s*:[\w-]+)*)'
        match = re.search(into_pattern, sql, re.IGNORECASE)
        if match:
            into_clause = match.group(1)
            vars_pattern = r':([A-Za-z][A-Za-z0-9-]*)'
            vars_matches = re.findall(vars_pattern, into_clause)
            self.into_variables = vars_matches
            
    def _extract_cursor_info(self, sql: str) -> None:
        """Extract cursor name if this is a cursor-related statement."""
        upper_sql = sql.upper()
        
        if self._sql_type == SQLStatementType.DECLARE_CURSOR:
            # DECLARE cursor_name CURSOR FOR ...
            match = re.search(r'DECLARE\s+([A-Za-z_][A-Za-z0-9_-]*)\s+CURSOR', sql, re.IGNORECASE)
            if match:
                self.cursor_name = match.group(1)
                
        elif self._sql_type == SQLStatementType.FETCH:
            # FETCH cursor_name INTO ...
            # or FETCH FROM cursor_name INTO ...
            # or FETCH NEXT FROM cursor_name INTO ...
            match = re.search(r'FETCH\s+(?:NEXT\s+)?(?:FROM\s+)?([A-Za-z_][A-Za-z0-9_-]*)', sql, re.IGNORECASE)
            if match:
                cursor_candidate = match.group(1)
                if cursor_candidate.upper() not in ['INTO', 'NEXT', 'PRIOR', 'FIRST', 'LAST']:
                    self.cursor_name = cursor_candidate
                    
        elif self._sql_type == SQLStatementType.OPEN_CURSOR:
            # OPEN cursor_name
            match = re.search(r'OPEN\s+([A-Za-z_][A-Za-z0-9_-]*)', sql, re.IGNORECASE)
            if match:
                self.cursor_name = match.group(1)
                
        elif self._sql_type == SQLStatementType.CLOSE_CURSOR:
            # CLOSE cursor_name
            match = re.search(r'CLOSE\s+([A-Za-z_][A-Za-z0-9_-]*)', sql, re.IGNORECASE)
            if match:
                self.cursor_name = match.group(1)
                
        # Check for PREPARE statement
        if self._sql_type == SQLStatementType.PREPARE:
            # PREPARE statement_name FROM ...
            match = re.search(r'PREPARE\s+([A-Za-z_][A-Za-z0-9_-]*)\s+FROM', sql, re.IGNORECASE)
            if match:
                self.prepared_statement_name = match.group(1)
                
        elif self._sql_type == SQLStatementType.EXECUTE:
            # EXECUTE statement_name [USING ...]
            match = re.search(r'EXECUTE\s+([A-Za-z_][A-Za-z0-9_-]*)', sql, re.IGNORECASE)
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
            match = re.search(r'FOR\s+(SELECT.+)', self.sql_text, re.IGNORECASE | re.DOTALL)
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
        table_patterns = [
            r'FROM\s+([A-Za-z_][A-Za-z0-9_]*)',
            r'JOIN\s+([A-Za-z_][A-Za-z0-9_]*)'
        ]
        for pattern in table_patterns:
            matches = re.findall(pattern, sql, re.IGNORECASE)
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
        match = re.search(r'TO\s+(?:SAVEPOINT\s+)?([A-Za-z_][A-Za-z0-9_-]*)', sql, re.IGNORECASE)
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
        stmt = DeclareCursorStatement(location)
        stmt.set_sql_text(sql_text)
        # Extract cursor name
        match = re.search(r'DECLARE\s+([A-Za-z_][A-Za-z0-9_-]*)\s+CURSOR', sql_text, re.IGNORECASE)
        if match:
            stmt.cursor_name = match.group(1)
        # Extract SELECT statement
        match = re.search(r'FOR\s+(SELECT.+)', sql_text, re.IGNORECASE | re.DOTALL)
        if match:
            stmt.set_select_statement(match.group(1))
        # Extract cursor options
        if "WITH HOLD" in upper_sql:
            stmt.add_cursor_option("WITH HOLD")
        if "FOR UPDATE" in upper_sql:
            stmt.add_cursor_option("FOR UPDATE")
        return stmt
        
    elif upper_sql.startswith("FETCH"):
        stmt = FetchStatement(location)
        stmt.set_sql_text(sql_text)
        # Extract direction
        for direction in ["NEXT", "PRIOR", "FIRST", "LAST"]:
            if direction in upper_sql:
                stmt.set_fetch_direction(direction)
                break
        return stmt
        
    elif upper_sql.startswith("PREPARE") or upper_sql.startswith("EXECUTE"):
        stmt = DynamicSQLStatement(location)
        stmt.set_sql_text(sql_text)
        # Extract USING variables
        match = re.search(r'USING\s+(:[\w-]+(?:\s*,\s*:[\w-]+)*)', sql_text, re.IGNORECASE)
        if match:
            using_clause = match.group(1)
            vars_pattern = r':([A-Za-z][A-Za-z0-9-]*)'
            vars_matches = re.findall(vars_pattern, using_clause)
            for var in vars_matches:
                stmt.add_using_variable(var)
        return stmt
        
    elif upper_sql.startswith("COMMIT") or upper_sql.startswith("ROLLBACK"):
        stmt = TransactionControlStatement(location)
        stmt.set_sql_text(sql_text)
        if "WORK" in upper_sql:
            stmt.is_work = True
        # Check for savepoint
        match = re.search(r'TO\s+(?:SAVEPOINT\s+)?([A-Za-z_][A-Za-z0-9_-]*)', sql_text, re.IGNORECASE)
        if match:
            stmt.set_savepoint(match.group(1))
        return stmt
        
    else:
        # Default to generic ExecSQLStatement
        stmt = ExecSQLStatement(location)
        stmt.set_sql_text(sql_text)
        return stmt


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
