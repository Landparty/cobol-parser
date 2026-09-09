"""
IO Logger - extracts all input/output operations from a parsed COBOL program.

This module provides an analyzer that traverses the AST and produces a
structured report of all I/O operations including program linkage (CALL/ENTRY),
database calls (EXEC SQL), file I/O, and console I/O.
"""

import json
import re
from dataclasses import dataclass, field
from typing import Any

from ..models.program import CobolProgram
from ..models.sql_statements import ExecSQLStatement, _strip_sql_literals_and_comments
from ..models.statements import (
    CallStatement,
    DisplayStatement,
    EntryStatement,
    IOAcceptStatement,
    IOCloseStatement,
    IODeleteStatement,
    IOOpenStatement,
    IOReadStatement,
    IORewriteStatement,
    IOStartStatement,
    IOUnlockStatement,
    IOWriteStatement,
)
from ._files import record_to_file_map, resolve_file_name


@dataclass
class IOOperation:
    """A single input/output operation extracted from the AST."""

    category: str  # CALL, SQL, FILE-IO, CONSOLE-IO, ENTRY
    operation: str  # e.g. "CALL PROGRAM-A", "SELECT", "READ", "ACCEPT"
    direction: str  # INPUT, OUTPUT, BIDIRECTIONAL
    variables: list[str] = field(default_factory=list)
    target: str | None = None  # Program name, file name, table name, device
    line: int | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "category": self.category,
            "operation": self.operation,
            "direction": self.direction,
            "variables": self.variables,
            "target": self.target,
            "line": self.line,
            "details": self.details,
        }


@dataclass
class IOLogReport:
    """Complete I/O report for a COBOL program."""

    program_name: str | None
    operations: list[IOOperation] = field(default_factory=list)

    @property
    def inputs(self) -> list[IOOperation]:
        """All INPUT operations."""
        return [op for op in self.operations if op.direction == "INPUT"]

    @property
    def outputs(self) -> list[IOOperation]:
        """All OUTPUT operations."""
        return [op for op in self.operations if op.direction == "OUTPUT"]

    @property
    def bidirectional(self) -> list[IOOperation]:
        """All BIDIRECTIONAL operations."""
        return [op for op in self.operations if op.direction == "BIDIRECTIONAL"]

    @property
    def calls(self) -> list[IOOperation]:
        """All CALL and ENTRY operations."""
        return [op for op in self.operations if op.category in ("CALL", "ENTRY")]

    @property
    def sql_operations(self) -> list[IOOperation]:
        """All SQL operations."""
        return [op for op in self.operations if op.category == "SQL"]

    @property
    def file_operations(self) -> list[IOOperation]:
        """All file I/O operations."""
        return [op for op in self.operations if op.category == "FILE-IO"]

    @property
    def console_operations(self) -> list[IOOperation]:
        """All console I/O operations."""
        return [op for op in self.operations if op.category == "CONSOLE-IO"]

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        direction_counts: dict[str, int] = {
            "INPUT": 0,
            "OUTPUT": 0,
            "BIDIRECTIONAL": 0,
        }
        category_counts: dict[str, int] = {
            "CALL": 0,
            "ENTRY": 0,
            "SQL": 0,
            "FILE-IO": 0,
            "CONSOLE-IO": 0,
        }
        for op in self.operations:
            if op.direction in direction_counts:
                direction_counts[op.direction] += 1
            if op.category in category_counts:
                category_counts[op.category] += 1

        return {
            "program_name": self.program_name,
            "operations": [op.to_dict() for op in self.operations],
            "summary": {
                "total": len(self.operations),
                "inputs": direction_counts["INPUT"],
                "outputs": direction_counts["OUTPUT"],
                "bidirectional": direction_counts["BIDIRECTIONAL"],
                "by_category": category_counts,
            },
        }

    def to_json(self, indent: int = 2) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), indent=indent)


_PASSING_MODE_DIRECTION = {
    "REFERENCE": "BIDIRECTIONAL",
    "CONTENT": "INPUT",
    "VALUE": "INPUT",
}

# Regex for extracting INTO :host-variables from SQL text (tolerates missing spaces)
_SQL_INTO_HOST_VARS_RE = re.compile(
    r"INTO\s*(:[\w-]+(?:\s*,?\s*:[\w-]+)*)", re.IGNORECASE
)
_SQL_HOST_VAR_RE = re.compile(r":([A-Za-z][A-Za-z0-9-]*)")


class IOLogger:
    """Analyzer that extracts all I/O operations from a COBOL program AST.

    Traverses the AST and collects all input/output operations into a
    structured report, covering:

    - CALL statements with USING parameters and RETURNING/GIVING
    - ENTRY statements with linkage parameters
    - EXEC SQL with host variables and INTO variables
    - File I/O (READ, WRITE, OPEN, CLOSE, REWRITE, DELETE, START, UNLOCK)
    - Console I/O (ACCEPT, DISPLAY)

    Example:
        ```python
        from cobolparser import parse_cobol
        from cobolparser.analysis import IOLogger

        result = parse_cobol(cobol_source)
        logger = IOLogger()
        report = logger.analyze(result.ast)

        for op in report.operations:
            print(f"{op.direction}: {op.operation} -> {op.variables}")

        print(report.to_json())
        ```
    """

    def __init__(self) -> None:
        """Initialize the IO logger."""
        self._operations: list[IOOperation] = []
        # FILE SECTION record name -> owning FD/SD name. WRITE/REWRITE name
        # a record, never a file, so their target is resolved through it.
        self._record_to_file: dict[str, str] = {}

    def analyze(self, ast: CobolProgram) -> IOLogReport:
        """Analyze AST and return structured I/O report.

        Args:
            ast: The parsed COBOL program AST

        Returns:
            IOLogReport with all extracted I/O operations
        """
        self._operations = []
        self._record_to_file = record_to_file_map(ast)

        # Collect all statements once to avoid repeated AST traversal
        all_statements = ast.get_all_statements()

        self._collect_call_operations(all_statements)
        self._collect_entry_operations(all_statements)
        self._collect_sql_operations(all_statements)
        self._collect_file_io_operations(all_statements)
        self._collect_console_io_operations(all_statements)

        return IOLogReport(
            program_name=ast.program_name,
            operations=list(self._operations),
        )

    def _collect_call_operations(self, statements: list) -> None:
        """Extract I/O from CALL statements."""
        for stmt in statements:
            if not isinstance(stmt, CallStatement):
                continue

            line = stmt.location.line if stmt.location else None
            program = stmt.called_program or "UNKNOWN"
            op_label = f"CALL {program}"

            details: dict[str, Any] = {
                "is_dynamic": stmt.is_dynamic,
            }
            if stmt.is_dynamic and stmt.possible_values:
                details["possible_values"] = stmt.possible_values

            # Each USING parameter becomes an operation
            has_params = False
            for param in stmt.using_parameters:
                has_params = True
                direction = _PASSING_MODE_DIRECTION.get(
                    param.passing_mode, "BIDIRECTIONAL"
                )
                self._operations.append(
                    IOOperation(
                        category="CALL",
                        operation=op_label,
                        direction=direction,
                        variables=[param.name],
                        target=program,
                        line=line,
                        details={**details, "passing_mode": param.passing_mode},
                    )
                )

            # RETURNING parameter
            if stmt.returning_parameter:
                has_params = True
                self._operations.append(
                    IOOperation(
                        category="CALL",
                        operation=op_label,
                        direction="OUTPUT",
                        variables=[stmt.returning_parameter],
                        target=program,
                        line=line,
                        details={**details, "passing_mode": "RETURNING"},
                    )
                )

            # GIVING parameter
            if stmt.giving_parameter:
                has_params = True
                self._operations.append(
                    IOOperation(
                        category="CALL",
                        operation=op_label,
                        direction="OUTPUT",
                        variables=[stmt.giving_parameter],
                        target=program,
                        line=line,
                        details={**details, "passing_mode": "GIVING"},
                    )
                )

            # Record parameterless CALLs so they still appear in the report
            if not has_params:
                self._operations.append(
                    IOOperation(
                        category="CALL",
                        operation=op_label,
                        direction="BIDIRECTIONAL",
                        variables=[],
                        target=program,
                        line=line,
                        details=details,
                    )
                )

    def _collect_entry_operations(self, statements: list) -> None:
        """Extract I/O from ENTRY statements."""
        for stmt in statements:
            if not isinstance(stmt, EntryStatement):
                continue

            line = stmt.location.line if stmt.location else None
            entry_name = stmt.entry_name or "UNKNOWN"

            if not stmt.using_parameters:
                self._operations.append(
                    IOOperation(
                        category="ENTRY",
                        operation=f"ENTRY {entry_name}",
                        direction="BIDIRECTIONAL",
                        variables=[],
                        target=entry_name,
                        line=line,
                        details={},
                    )
                )
                continue

            for param in stmt.using_parameters:
                self._operations.append(
                    IOOperation(
                        category="ENTRY",
                        operation=f"ENTRY {entry_name}",
                        direction="BIDIRECTIONAL",
                        variables=[param],
                        target=entry_name,
                        line=line,
                        details={},
                    )
                )

    def _collect_sql_operations(self, statements: list) -> None:
        """Extract I/O from EXEC SQL statements."""
        for stmt in statements:
            if not isinstance(stmt, ExecSQLStatement):
                continue

            line = stmt.location.line if stmt.location else None
            sql_type = stmt.sql_type

            details: dict[str, Any] = {
                "sql_type": sql_type,
                "sql_text": stmt.sql_text,
            }
            if stmt.tables:
                details["tables"] = stmt.tables
            if stmt.cursor_name:
                details["cursor_name"] = stmt.cursor_name

            target = stmt.tables[0] if stmt.tables else stmt.cursor_name

            # INTO variables are outputs (data fetched from DB)
            # Fall back to regex extraction when the parser doesn't populate
            # into_variables (can happen when SQL text has no space before colon)
            into_vars = list(stmt.into_variables)
            if not into_vars and stmt.sql_text:
                # Scrub string literals/comments first, matching the real
                # parser's own `_extract_into_variables` -- otherwise an
                # "INTO :x"-shaped substring sitting inside a quoted string
                # literal (which the parser correctly ignores) still matches
                # here, fabricating a host-variable operation that was never
                # actually present.
                scrubbed_sql = _strip_sql_literals_and_comments(stmt.sql_text)
                into_match = _SQL_INTO_HOST_VARS_RE.search(scrubbed_sql)
                if into_match:
                    into_vars = _SQL_HOST_VAR_RE.findall(into_match.group(1))

            into_set = set(into_vars)
            if into_vars:
                self._operations.append(
                    IOOperation(
                        category="SQL",
                        operation=sql_type,
                        direction="OUTPUT",
                        variables=into_vars,
                        target=target,
                        line=line,
                        details=details,
                    )
                )

            # Host variables minus INTO are inputs (data sent to DB)
            input_vars = [v for v in stmt.host_variables if v not in into_set]
            if input_vars:
                self._operations.append(
                    IOOperation(
                        category="SQL",
                        operation=sql_type,
                        direction="INPUT",
                        variables=input_vars,
                        target=target,
                        line=line,
                        details=details,
                    )
                )

            # If no host variables at all, still record the operation
            if not stmt.host_variables and not into_vars:
                direction = "INPUT"
                if sql_type in ("SELECT", "FETCH"):
                    direction = "OUTPUT"
                elif sql_type in ("OPEN", "CLOSE", "COMMIT", "ROLLBACK"):
                    direction = "BIDIRECTIONAL"
                self._operations.append(
                    IOOperation(
                        category="SQL",
                        operation=sql_type,
                        direction=direction,
                        variables=[],
                        target=target,
                        line=line,
                        details=details,
                    )
                )

    def _collect_file_io_operations(self, statements: list) -> None:
        """Extract I/O from file operations."""
        for stmt in statements:
            line = stmt.location.line if stmt.location else None

            if isinstance(stmt, IOReadStatement):
                variables = []
                if stmt.into_target:
                    variables.append(stmt.into_target)
                elif stmt.record_name:
                    variables.append(stmt.record_name)
                self._operations.append(
                    IOOperation(
                        category="FILE-IO",
                        operation="READ",
                        direction="INPUT",
                        variables=variables,
                        target=stmt.file_name,
                        line=line,
                        details={"access_mode": stmt.access_mode},
                    )
                )

            elif isinstance(stmt, IOWriteStatement):
                variables = []
                if stmt.from_clause:
                    variables.append(stmt.from_clause)
                elif stmt.record_name:
                    variables.append(stmt.record_name)
                self._operations.append(
                    IOOperation(
                        category="FILE-IO",
                        operation="WRITE",
                        direction="OUTPUT",
                        variables=variables,
                        target=self._file_for(stmt.file_name, stmt.record_name),
                        line=line,
                        details={"from_clause": stmt.from_clause},
                    )
                )

            elif isinstance(stmt, IOOpenStatement):
                # ``OPEN INPUT IN-FILE OUTPUT OUT-FILE`` opens each file under
                # its own mode group; ``open_mode`` only ever holds the first
                # one, so the per-file ``file_modes`` is authoritative and
                # ``open_mode`` merely the fallback (same as crud_matrix.py).
                file_modes = getattr(stmt, "file_modes", None) or {}
                for file_name in stmt.file_names:
                    mode = (
                        file_modes.get(file_name) or stmt.open_mode or "UNKNOWN"
                    ).upper()
                    if mode == "I-O":
                        direction = "BIDIRECTIONAL"
                    elif mode in ("OUTPUT", "EXTEND"):
                        direction = "OUTPUT"
                    else:
                        direction = "INPUT"
                    self._operations.append(
                        IOOperation(
                            category="FILE-IO",
                            operation=f"OPEN {mode}",
                            direction=direction,
                            variables=[],
                            target=file_name,
                            line=line,
                            details={"open_mode": mode},
                        )
                    )

            elif isinstance(stmt, IOCloseStatement):
                for file_name in stmt.file_names:
                    self._operations.append(
                        IOOperation(
                            category="FILE-IO",
                            operation="CLOSE",
                            direction="BIDIRECTIONAL",
                            variables=[],
                            target=file_name,
                            line=line,
                            details={},
                        )
                    )

            elif isinstance(stmt, IORewriteStatement):
                variables = []
                if stmt.record_name:
                    variables.append(stmt.record_name)
                self._operations.append(
                    IOOperation(
                        category="FILE-IO",
                        operation="REWRITE",
                        direction="OUTPUT",
                        variables=variables,
                        target=self._file_for(stmt.file_name, stmt.record_name),
                        line=line,
                        details={},
                    )
                )

            elif isinstance(stmt, IODeleteStatement):
                self._operations.append(
                    IOOperation(
                        category="FILE-IO",
                        operation="DELETE",
                        direction="OUTPUT",
                        variables=[],
                        target=stmt.file_name,
                        line=line,
                        details={},
                    )
                )

            elif isinstance(stmt, IOStartStatement):
                self._operations.append(
                    IOOperation(
                        category="FILE-IO",
                        operation="START",
                        direction="INPUT",
                        variables=[],
                        target=stmt.file_name,
                        line=line,
                        details={"key_condition": stmt.key_condition},
                    )
                )

            elif isinstance(stmt, IOUnlockStatement):
                self._operations.append(
                    IOOperation(
                        category="FILE-IO",
                        operation="UNLOCK",
                        direction="BIDIRECTIONAL",
                        variables=[],
                        target=stmt.file_name,
                        line=line,
                        details={"record_scope": stmt.record_scope},
                    )
                )

    def _file_for(self, file_name: str | None, record_name: str | None) -> str | None:
        """The file a WRITE/REWRITE targets, via its record's FD."""
        return resolve_file_name(file_name, record_name, self._record_to_file)

    def _collect_console_io_operations(self, statements: list) -> None:
        """Extract I/O from ACCEPT and DISPLAY statements."""
        for stmt in statements:
            line = stmt.location.line if stmt.location else None

            if isinstance(stmt, IOAcceptStatement):
                variables = []
                if stmt.target:
                    variables.append(stmt.target)
                self._operations.append(
                    IOOperation(
                        category="CONSOLE-IO",
                        operation="ACCEPT",
                        direction="INPUT",
                        variables=variables,
                        target=stmt.from_source,
                        line=line,
                        details={"from_source": stmt.from_source},
                    )
                )

            elif isinstance(stmt, DisplayStatement):
                self._operations.append(
                    IOOperation(
                        category="CONSOLE-IO",
                        operation="DISPLAY",
                        direction="OUTPUT",
                        variables=list(stmt.display_items),
                        target=stmt.output_device,
                        line=line,
                        details={"output_device": stmt.output_device},
                    )
                )
