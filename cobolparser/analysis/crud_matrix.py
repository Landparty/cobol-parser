"""
CRUD Matrix Generator for COBOL programs.

For each program × file/table, marks C/R/U/D based on:
- OPEN mode + READ/WRITE/REWRITE/DELETE for VSAM/sequential files
- EXEC SQL verbs (SELECT/INSERT/UPDATE/DELETE/FETCH) for DB2 tables

Standard deliverable in mainframe modernization engagements.
"""

import csv
import io
import json
from dataclasses import dataclass, field
from typing import Any

from ..models.program import CobolProgram
from ..models.sql_statements import (
    DeclareCursorStatement,
    ExecSQLStatement,
    FetchStatement,
    SQLStatementType,
)
from ..models.statements import (
    IODeleteStatement,
    IOOpenStatement,
    IOReadStatement,
    IORewriteStatement,
    IOWriteStatement,
)


@dataclass
class CRUDFlags:
    """C/R/U/D access flags for a single resource."""

    create: bool = False  # WRITE (file) | INSERT (SQL)
    read: bool = False  # READ (file) | SELECT / FETCH (SQL)
    update: bool = False  # REWRITE (file) | UPDATE (SQL)
    delete: bool = False  # DELETE (file) | DELETE (SQL)

    def as_string(self) -> str:
        """Return compact CRUD string, e.g. 'CR-D' or '----'."""
        return "".join(
            [
                "C" if self.create else "-",
                "R" if self.read else "-",
                "U" if self.update else "-",
                "D" if self.delete else "-",
            ]
        )

    def any(self) -> bool:
        """True if at least one flag is set."""
        return self.create or self.read or self.update or self.delete

    def to_dict(self) -> dict[str, Any]:
        return {
            "create": self.create,
            "read": self.read,
            "update": self.update,
            "delete": self.delete,
            "summary": self.as_string(),
        }


@dataclass
class FileEntry:
    """CRUD entry for a single program × COBOL file combination."""

    program_name: str
    file_name: str
    crud: CRUDFlags = field(default_factory=CRUDFlags)
    open_modes: list[str] = field(default_factory=list)  # INPUT/OUTPUT/I-O/EXTEND seen
    organization: str | None = None  # SEQUENTIAL/INDEXED/RELATIVE from SELECT
    access_mode: str | None = None  # SEQUENTIAL/RANDOM/DYNAMIC from SELECT

    def to_dict(self) -> dict[str, Any]:
        return {
            "program_name": self.program_name,
            "resource_type": "FILE",
            "resource_name": self.file_name,
            "crud": self.crud.to_dict(),
            "open_modes": sorted(set(self.open_modes)),
            "organization": self.organization,
            "access_mode": self.access_mode,
        }


@dataclass
class TableEntry:
    """CRUD entry for a single program × DB2 table combination."""

    program_name: str
    table_name: str
    crud: CRUDFlags = field(default_factory=CRUDFlags)
    cursors: list[str] = field(default_factory=list)  # cursor names that select from table

    def to_dict(self) -> dict[str, Any]:
        return {
            "program_name": self.program_name,
            "resource_type": "TABLE",
            "resource_name": self.table_name,
            "crud": self.crud.to_dict(),
            "cursors": sorted(set(self.cursors)),
        }


@dataclass
class CRUDMatrix:
    """Complete CRUD matrix report for one or more COBOL programs."""

    program_name: str | None
    file_entries: list[FileEntry] = field(default_factory=list)
    table_entries: list[TableEntry] = field(default_factory=list)

    @property
    def entries(self) -> list[FileEntry | TableEntry]:
        """All entries (files and tables) sorted by program then resource name."""
        combined: list[FileEntry | TableEntry] = list(self.file_entries) + list(
            self.table_entries
        )
        return sorted(
            combined,
            key=lambda e: (
                e.program_name,
                e.table_name if isinstance(e, TableEntry) else e.file_name,
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "program_name": self.program_name,
            "files": [e.to_dict() for e in self.file_entries],
            "tables": [e.to_dict() for e in self.table_entries],
            "summary": {
                "total_files": len(self.file_entries),
                "total_tables": len(self.table_entries),
                "total_resources": len(self.file_entries) + len(self.table_entries),
            },
        }

    def to_json(self, indent: int = 2) -> str:
        """Return JSON-formatted CRUD matrix."""
        return json.dumps(self.to_dict(), indent=indent)

    def to_csv(self) -> str:
        """Return CSV-formatted CRUD matrix suitable for spreadsheet delivery.

        Columns: Program, ResourceType, ResourceName, C, R, U, D, CRUD, OpenModes/Cursors, Organization
        """
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "Program",
                "ResourceType",
                "ResourceName",
                "C",
                "R",
                "U",
                "D",
                "CRUD",
                "Extra",
                "Organization",
            ]
        )
        for entry in self.entries:
            crud = entry.crud
            if isinstance(entry, FileEntry):
                extra = "|".join(sorted(set(entry.open_modes)))
                org = entry.organization or ""
                resource_name = entry.file_name
                resource_type = "FILE"
            else:
                extra = "|".join(sorted(set(entry.cursors)))
                org = ""
                resource_name = entry.table_name
                resource_type = "TABLE"
            writer.writerow(
                [
                    entry.program_name,
                    resource_type,
                    resource_name,
                    "C" if crud.create else "",
                    "R" if crud.read else "",
                    "U" if crud.update else "",
                    "D" if crud.delete else "",
                    crud.as_string(),
                    extra,
                    org,
                ]
            )
        return output.getvalue()


class CRUDMatrixGenerator:
    """Generates a CRUD matrix for a parsed COBOL program.

    Traverses the AST once to collect all file and SQL table accesses,
    then marks Create/Read/Update/Delete per resource.

    COBOL file mapping:
        - C (Create)  <- WRITE statement
        - R (Read)    <- READ statement
        - U (Update)  <- REWRITE statement
        - D (Delete)  <- DELETE statement
        OPEN modes (INPUT/OUTPUT/I-O/EXTEND) are recorded as metadata.

    SQL table mapping:
        - C (Create)  <- INSERT
        - R (Read)    <- SELECT, DECLARE CURSOR (implicit read path), FETCH
        - U (Update)  <- UPDATE
        - D (Delete)  <- DELETE

    Example:
        ```python
        from cobolparser import parse_cobol
        from cobolparser.analysis.crud_matrix import CRUDMatrixGenerator

        result = parse_cobol(cobol_source)
        gen = CRUDMatrixGenerator()
        matrix = gen.analyze(result.ast)

        print(matrix.to_csv())
        print(matrix.to_json())
        ```
    """

    def __init__(self) -> None:
        self._file_entries: dict[str, FileEntry] = {}
        self._table_entries: dict[str, TableEntry] = {}
        # cursor_name -> set of table names (from DECLARE CURSOR)
        self._cursor_tables: dict[str, set[str]] = {}
        # record_name (upper) -> file_name (upper) built from FD metadata
        self._record_to_file: dict[str, str] = {}
        self._program_name: str | None = None

    def analyze(self, ast: CobolProgram) -> CRUDMatrix:
        """Analyze a parsed COBOL program and return its CRUD matrix.

        Args:
            ast: The parsed COBOL program AST from parse_cobol().

        Returns:
            CRUDMatrix with one entry per program × file/table pair.
        """
        self._file_entries = {}
        self._table_entries = {}
        self._cursor_tables = {}
        self._record_to_file = {}
        self._program_name = ast.program_name

        all_statements = ast.get_all_statements()

        # First pass: collect SELECT statement metadata (file organization/access mode)
        self._collect_file_metadata(ast)

        # Second pass: build record-to-file mapping from FD metadata in FILE SECTION
        self._collect_record_to_file_mapping(ast)

        # Third pass: collect OPEN modes (must precede CRUD marking so metadata is ready)
        self._collect_open_modes(all_statements)

        # Fourth pass: collect DECLARE CURSOR table associations for FETCH tracking
        self._collect_cursor_declarations(all_statements)

        # Fifth pass: mark CRUD operations
        self._mark_file_crud(all_statements)
        self._mark_sql_crud(all_statements)

        return CRUDMatrix(
            program_name=self._program_name,
            file_entries=list(self._file_entries.values()),
            table_entries=list(self._table_entries.values()),
        )

    # ------------------------------------------------------------------
    # File metadata collection
    # ------------------------------------------------------------------

    def _collect_file_metadata(self, ast: CobolProgram) -> None:
        """Extract file organization/access mode from SELECT statements in ENVIRONMENT DIVISION."""
        from ..models.statements.misc import SelectStatement

        try:
            env_div = ast.get_division("ENVIRONMENT")
        except Exception:
            return
        if env_div is None:
            return

        for node in env_div.find_all_by_type("Statement"):
            if isinstance(node, SelectStatement) and node.file_name:
                name = node.file_name.upper()
                entry = self._get_or_create_file_entry(name)
                entry.organization = node.organization
                entry.access_mode = node.access_mode

    # ------------------------------------------------------------------
    # Record-to-file mapping (built from FD metadata set by data parser)
    # ------------------------------------------------------------------

    def _collect_record_to_file_mapping(self, ast: CobolProgram) -> None:
        """Build record_name -> file_name mapping from FILE SECTION FD metadata.

        The data division parser sets ``fd_file_name`` metadata on 01-level data
        items when it detects an ``FD`` declaration preceding them.  This mapping
        lets WRITE/REWRITE statements (which carry a record name, not a file name)
        be attributed to the correct file.
        """
        from ..models.data_items import CobolDataItem

        data_div = ast.get_division("DATA")
        if data_div is None:
            return
        file_section = data_div._sections.get("FILE")
        if file_section is None:
            return
        for item in file_section.data_items:
            if not isinstance(item, CobolDataItem):
                continue
            fd_file = item.get_metadata("fd_file_name")
            if fd_file and item.name:
                self._record_to_file[item.name.upper()] = fd_file.upper()

    # ------------------------------------------------------------------
    # OPEN mode tracking
    # ------------------------------------------------------------------

    def _collect_open_modes(self, statements: list) -> None:
        """Record OPEN modes for each file referenced in OPEN statements."""
        for stmt in statements:
            if isinstance(stmt, IOOpenStatement) and stmt.open_mode:
                mode = stmt.open_mode.upper()
                for file_name in stmt.file_names:
                    entry = self._get_or_create_file_entry(file_name.upper())
                    if mode not in entry.open_modes:
                        entry.open_modes.append(mode)

    # ------------------------------------------------------------------
    # Cursor tracking
    # ------------------------------------------------------------------

    def _collect_cursor_declarations(self, statements: list) -> None:
        """Map cursor names to the tables they SELECT FROM."""
        for stmt in statements:
            if isinstance(stmt, DeclareCursorStatement) and stmt.cursor_name:
                cursor = stmt.cursor_name.upper()
                tables = {t.upper() for t in stmt.tables if t}
                if cursor not in self._cursor_tables:
                    self._cursor_tables[cursor] = set()
                self._cursor_tables[cursor].update(tables)
            elif (
                isinstance(stmt, ExecSQLStatement)
                and stmt.sql_type == SQLStatementType.DECLARE_CURSOR
                and stmt.cursor_name
            ):
                cursor = stmt.cursor_name.upper()
                tables = {t.upper() for t in stmt.tables if t}
                if cursor not in self._cursor_tables:
                    self._cursor_tables[cursor] = set()
                self._cursor_tables[cursor].update(tables)

    # ------------------------------------------------------------------
    # File CRUD marking
    # ------------------------------------------------------------------

    def _resolve_file_name(
        self, file_name: str | None, record_name: str | None
    ) -> str | None:
        """Return an upper-cased file name, falling back to record-to-file mapping."""
        if file_name:
            return file_name.upper()
        if record_name:
            return self._record_to_file.get(record_name.upper())
        return None

    def _mark_file_crud(self, statements: list) -> None:
        """Mark C/R/U/D for COBOL file operations."""
        for stmt in statements:
            if isinstance(stmt, IOReadStatement):
                fn = self._resolve_file_name(stmt.file_name, stmt.record_name)
                if fn:
                    self._get_or_create_file_entry(fn).crud.read = True

            elif isinstance(stmt, IOWriteStatement):
                fn = self._resolve_file_name(stmt.file_name, stmt.record_name)
                if fn:
                    self._get_or_create_file_entry(fn).crud.create = True

            elif isinstance(stmt, IORewriteStatement):
                fn = self._resolve_file_name(stmt.file_name, stmt.record_name)
                if fn:
                    self._get_or_create_file_entry(fn).crud.update = True

            elif isinstance(stmt, IODeleteStatement):
                fn = self._resolve_file_name(stmt.file_name, None)
                if fn:
                    self._get_or_create_file_entry(fn).crud.delete = True

    # ------------------------------------------------------------------
    # SQL CRUD marking
    # ------------------------------------------------------------------

    def _mark_sql_crud(self, statements: list) -> None:
        """Mark C/R/U/D for SQL table operations."""
        for stmt in statements:
            if not isinstance(stmt, ExecSQLStatement):
                continue

            sql_type = stmt.sql_type

            if sql_type == SQLStatementType.INSERT:
                for table in stmt.tables:
                    self._get_or_create_table_entry(table.upper()).crud.create = True

            elif sql_type == SQLStatementType.SELECT:
                for table in stmt.tables:
                    self._get_or_create_table_entry(table.upper()).crud.read = True

            elif sql_type == SQLStatementType.UPDATE:
                for table in stmt.tables:
                    self._get_or_create_table_entry(table.upper()).crud.update = True

            elif sql_type == SQLStatementType.DELETE:
                for table in stmt.tables:
                    self._get_or_create_table_entry(table.upper()).crud.delete = True

            elif sql_type == SQLStatementType.DECLARE_CURSOR:
                # DECLARE CURSOR implies a read path on the tables it selects from
                for table in stmt.tables:
                    table_upper = table.upper()
                    entry = self._get_or_create_table_entry(table_upper)
                    entry.crud.read = True
                    if stmt.cursor_name:
                        cursor = stmt.cursor_name.upper()
                        if cursor not in entry.cursors:
                            entry.cursors.append(cursor)

            elif sql_type == SQLStatementType.FETCH:
                # FETCH reads from a cursor; mark the underlying tables as Read
                if isinstance(stmt, FetchStatement) and stmt.cursor_name:
                    cursor = stmt.cursor_name.upper()
                elif stmt.cursor_name:
                    cursor = stmt.cursor_name.upper()
                else:
                    cursor = None

                if cursor and cursor in self._cursor_tables:
                    for table in self._cursor_tables[cursor]:
                        entry = self._get_or_create_table_entry(table)
                        entry.crud.read = True
                        if cursor not in entry.cursors:
                            entry.cursors.append(cursor)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_or_create_file_entry(self, file_name: str) -> FileEntry:
        if file_name not in self._file_entries:
            self._file_entries[file_name] = FileEntry(
                program_name=self._program_name or "",
                file_name=file_name,
            )
        return self._file_entries[file_name]

    def _get_or_create_table_entry(self, table_name: str) -> TableEntry:
        if table_name not in self._table_entries:
            self._table_entries[table_name] = TableEntry(
                program_name=self._program_name or "",
                table_name=table_name,
            )
        return self._table_entries[table_name]
