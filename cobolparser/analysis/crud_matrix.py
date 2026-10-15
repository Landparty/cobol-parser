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
import re
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
from ..models.statements.misc import (
    MergeStatement,
    ReleaseStatement,
    ReturnStatement,
    SortStatement,
)
from ._files import record_to_file_map, resolve_file_name


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
    cursors: list[str] = field(
        default_factory=list
    )  # cursor names that select from table

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


#: SQL statements that write one target table (``tables[0]``).
_WRITE_SQL_TYPES = frozenset(
    {
        SQLStatementType.INSERT,
        SQLStatementType.UPDATE,
        SQLStatementType.DELETE,
        SQLStatementType.TRUNCATE,
        SQLStatementType.MERGE,
    }
)
#: ``WHEN [NOT] MATCHED [AND ...] THEN INSERT|UPDATE|DELETE`` in a MERGE.
_MERGE_ACTION_RE = re.compile(r"\bTHEN\s+(INSERT|UPDATE|DELETE)\b")


class CRUDMatrixGenerator:
    """Generates a CRUD matrix for a parsed COBOL program.

    Traverses the AST once to collect all file and SQL table accesses,
    then marks Create/Read/Update/Delete per resource.

    COBOL file mapping:
        - C (Create)  <- WRITE statement
        - R (Read)    <- READ statement
        - U (Update)  <- REWRITE statement
        - D (Delete)  <- DELETE statement
        - SORT/MERGE ``USING`` files are read (R) and ``GIVING`` files are
          written (C); ``RELEASE`` writes (C) and ``RETURN`` reads (R) the
          SD work file
        OPEN modes (INPUT/OUTPUT/I-O/EXTEND) are recorded as metadata.

    SQL table mapping:
        - C (Create)  <- INSERT
        - R (Read)    <- SELECT, DECLARE CURSOR (implicit read path), FETCH,
                         and any table a write statement's subquery reads
        - U (Update)  <- UPDATE
        - D (Delete)  <- DELETE, TRUNCATE [TABLE]
        - MERGE marks its target with the actions its WHEN clauses take

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

        # ``CobolProgram.get_division`` is a plain dict lookup that returns
        # ``None`` for a missing division and never raises, so no broad
        # exception guard is needed here.
        env_div = ast.get_division("ENVIRONMENT")
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
        be attributed to the correct file. Shared with ``io_logger``/
        ``io_sequence`` via ``_files.record_to_file_map`` so the three
        analyzers cannot disagree about which file a record belongs to.
        """
        self._record_to_file = record_to_file_map(ast)

    # ------------------------------------------------------------------
    # OPEN mode tracking
    # ------------------------------------------------------------------

    def _collect_open_modes(self, statements: list) -> None:
        """Record OPEN modes for each file referenced in OPEN statements.

        ``IOOpenStatement.file_modes`` is the authoritative per-file source:
        ``OPEN INPUT IN-FILE OUTPUT OUT-FILE`` opens each file under its own
        mode group, while ``open_mode`` only ever reflects the statement's
        *first* mode group. Fall back to ``open_mode`` for any file the
        parser recorded no per-file mode for.
        """
        for stmt in statements:
            if isinstance(stmt, IOOpenStatement):
                file_modes = getattr(stmt, "file_modes", None) or {}
                for file_name in stmt.file_names:
                    mode = file_modes.get(file_name) or stmt.open_mode
                    if not mode:
                        continue
                    mode = mode.upper()
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
        """Return an upper-cased file name, falling back to record-to-file
        mapping. Shared resolution logic (``_files.resolve_file_name``),
        upper-cased here since ``self._file_entries`` is keyed by upper-case
        name -- ``io_logger``'s own use of the same helper keeps the file
        name as written for its human-readable report instead."""
        fn = resolve_file_name(file_name, record_name, self._record_to_file)
        return fn.upper() if fn else None

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

            elif isinstance(stmt, (SortStatement, MergeStatement)):
                # `SORT ... USING a GIVING b` opens, reads every record of
                # `a` and writes every record of `b` itself -- no READ or
                # WRITE statement of the program's own ever names them.
                for name in stmt.using_files:
                    fn = self._resolve_file_name(name, None)
                    if fn:
                        self._get_or_create_file_entry(fn).crud.read = True
                for name in stmt.giving_files:
                    fn = self._resolve_file_name(name, None)
                    if fn:
                        self._get_or_create_file_entry(fn).crud.create = True

            elif isinstance(stmt, ReleaseStatement):
                fn = self._resolve_file_name(None, stmt.record_name)
                if fn:
                    self._get_or_create_file_entry(fn).crud.create = True

            elif isinstance(stmt, ReturnStatement):
                fn = self._resolve_file_name(stmt.file_name, None)
                if fn:
                    self._get_or_create_file_entry(fn).crud.read = True

    # ------------------------------------------------------------------
    # SQL CRUD marking
    # ------------------------------------------------------------------

    def _mark_sql_crud(self, statements: list) -> None:
        """Mark C/R/U/D for SQL table operations."""
        for stmt in statements:
            if not isinstance(stmt, ExecSQLStatement):
                continue

            sql_type = stmt.sql_type

            # ``SELECT ... FROM FINAL TABLE (INSERT INTO T ...)``: the nested
            # data-change statement writes its table.
            for verb, table in getattr(stmt, "data_change_tables", []):
                entry = self._get_or_create_table_entry(table.upper())
                if verb == "INSERT":
                    entry.crud.create = True
                elif verb == "UPDATE":
                    entry.crud.update = True
                elif verb == "DELETE":
                    entry.crud.delete = True
                else:  # MERGE
                    actions = set(_MERGE_ACTION_RE.findall(stmt.sql_text.upper()))
                    entry.crud.create |= "INSERT" in actions
                    entry.crud.update |= "UPDATE" in actions
                    entry.crud.delete |= "DELETE" in actions

            if sql_type in _WRITE_SQL_TYPES:
                # tables[0] is the statement's target; any other table is
                # one a subquery (``WHERE X IN (SELECT X FROM T2)``,
                # ``INSERT INTO T SELECT ... FROM S``, ``MERGE ... USING S``)
                # only reads.
                if not stmt.tables:
                    continue
                target = self._get_or_create_table_entry(stmt.tables[0].upper())
                if sql_type == SQLStatementType.INSERT:
                    target.crud.create = True
                elif sql_type == SQLStatementType.UPDATE:
                    target.crud.update = True
                elif sql_type in (SQLStatementType.DELETE, SQLStatementType.TRUNCATE):
                    target.crud.delete = True
                else:  # MERGE: whichever actions its WHEN clauses take
                    actions = set(_MERGE_ACTION_RE.findall(stmt.sql_text.upper()))
                    target.crud.create |= "INSERT" in actions
                    target.crud.update |= "UPDATE" in actions
                    target.crud.delete |= "DELETE" in actions
                for table in stmt.tables[1:]:
                    self._get_or_create_table_entry(table.upper()).crud.read = True

            elif sql_type == SQLStatementType.SELECT:
                for table in stmt.tables:
                    self._get_or_create_table_entry(table.upper()).crud.read = True

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
