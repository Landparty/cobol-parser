"""Host-variable type resolver for embedded SQL in COBOL programs.

This module walks a parsed COBOL AST and resolves every ``:host-var``
reference found in ``EXEC SQL`` blocks back to its DATA DIVISION definition.
It also integrates with DCLGEN-generated ``DECLARE TABLE`` blocks so that,
for each host variable, the corresponding DB2 column type and the COBOL
PICTURE / USAGE clauses are all available in a single place.

Typical usage::

    from cobolparser import parse_cobol
    from cobolparser.analysis import HostVariableResolver

    result = parse_cobol(source)
    resolver = HostVariableResolver()
    report = resolver.resolve(result.ast)

    for var_name, info in report.resolved.items():
        print(f":{var_name}  PIC {info.picture}  USAGE {info.usage}")

    for var_name in report.unresolved:
        print(f":{var_name}  — no DATA DIVISION definition found")
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ..models.ast_base import ASTNode
from ..models.data_items import CobolDataItem
from ..models.program import CobolProgram
from ..models.sql_statements import (
    DB2ColumnDefinition,
    DeclareTableStatement,
    ExecSQLStatement,
    _strip_sql_literals_and_comments,
)

#: ``:NAME`` or structure-qualified ``:STRUCT.NAME`` -- the qualifiers and
#: the variable itself.
_QUALIFIED_HOST_VAR_RE = re.compile(
    r":((?:[A-Za-z][A-Za-z0-9_-]*\.)*)([A-Za-z][A-Za-z0-9_-]*)"
)

# ---------------------------------------------------------------------------
# Public data structures
# ---------------------------------------------------------------------------


@dataclass
class HostVariableInfo:
    """All type information known about a single COBOL host variable.

    Attributes:
        name: Variable name (as it appears after the colon in SQL, upper-cased).
        picture: COBOL PICTURE string from the DATA DIVISION (e.g. ``"X(30)"``),
            or *None* for group items.
        usage: COBOL USAGE clause (e.g. ``"COMP-3"``, ``"DISPLAY"``).
        data_item: The :class:`~cobolparser.models.data_items.CobolDataItem`
            AST node, or *None* if the variable has no DATA DIVISION entry.
        db2_column: The :class:`~cobolparser.models.sql_statements.DB2ColumnDefinition`
            from the matching ``DECLARE TABLE`` block, or *None* when no
            DCLGEN table declaration was found.
        sql_statements: The ``EXEC SQL`` statements in which this variable
            appears (references, not definitions).
    """

    name: str
    picture: str | None = None
    usage: str = "DISPLAY"
    data_item: CobolDataItem | None = None
    db2_column: DB2ColumnDefinition | None = None
    sql_statements: list[ExecSQLStatement] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dictionary (no circular references)."""
        return {
            "name": self.name,
            "picture": self.picture,
            "usage": self.usage,
            "has_data_item": self.data_item is not None,
            "db2_column": self.db2_column.to_dict() if self.db2_column else None,
            "sql_statement_count": len(self.sql_statements),
        }


@dataclass
class HostVarResolutionReport:
    """Result of running :class:`HostVariableResolver` over a COBOL program.

    Attributes:
        resolved: Mapping of upper-cased variable name →
            :class:`HostVariableInfo`.  Every host variable that either has a
            DATA DIVISION entry *or* a matching DCLGEN column definition
            appears here.
        unresolved: Set of host-variable names that appear in SQL but have
            neither a DATA DIVISION entry nor a matching DB2 column.
        declare_tables: All ``DECLARE TABLE`` statements found in the program,
            keyed by upper-cased table name.
        column_name_collisions: Mapping of column name, in its DCLGEN
            host-variable form (``CUST_ID`` -> ``CUST-ID``) → list of
            table names that define a column with that name.  Only populated
            when the same column name exists in **two or more** DECLARE TABLE
            blocks.  When a collision exists the DB2 fallback for that name is
            ambiguous; callers should prefer the DATA DIVISION definition or
            disambiguate by table.
    """

    resolved: dict[str, HostVariableInfo] = field(default_factory=dict)
    unresolved: set[str] = field(default_factory=set)
    declare_tables: dict[str, DeclareTableStatement] = field(default_factory=dict)
    column_name_collisions: dict[str, list[str]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dictionary."""
        return {
            "resolved_count": len(self.resolved),
            "unresolved_count": len(self.unresolved),
            "collision_count": len(self.column_name_collisions),
            "resolved": {k: v.to_dict() for k, v in self.resolved.items()},
            "unresolved": sorted(self.unresolved),
            "declare_tables": {k: v.to_dict() for k, v in self.declare_tables.items()},
            "column_name_collisions": {
                k: sorted(v) for k, v in self.column_name_collisions.items()
            },
        }


def dclgen_name(name: str) -> str:
    """A DB2 column name the way the DCLGEN host variable for it is spelled.

    DB2 column names are underscored (``CUST_ID``); the COBOL host variables
    DCLGEN generates for them are hyphenated (``CUST-ID``), because ``_`` is
    not a COBOL data-name character. Columns are indexed, and host variables
    looked up, by this form -- comparing the two verbatim matched only the
    columns with no underscore in their name (#572). :class:`DclgenChecker`
    uses the same function, so the two cannot drift apart.
    """
    return name.strip().upper().replace("_", "-")


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------


class HostVariableResolver:
    """Resolves ``:host-var`` references in EXEC SQL blocks to their types.

    The resolver performs three passes over the AST:

    1. **Symbol table** — collect every :class:`~cobolparser.models.data_items.CobolDataItem`
       from the DATA DIVISION (Working-Storage, Linkage, Local-Storage sections).
    2. **DECLARE TABLE** — collect every ``EXEC SQL DECLARE tablename TABLE``
       block and index its columns by name for later cross-referencing.
    3. **Host-variable scan** — for each :class:`~cobolparser.models.sql_statements.ExecSQLStatement`,
       look up every ``:host-var`` in the symbol table, record the
       PICTURE / USAGE, and optionally attach the DB2 column information.
    """

    def __init__(self) -> None:
        # Upper-cased data-item name → CobolDataItem
        self._symbol_table: dict[str, CobolDataItem] = {}
        # Upper-cased data-item name → every item of that name, each with the
        # upper-cased names of its enclosing groups (for ``:STRUCT.NAME``).
        self._all_items: dict[str, list[tuple[CobolDataItem, list[str]]]] = {}
        # Upper-cased table name → DeclareTableStatement
        self._declare_tables: dict[str, DeclareTableStatement] = {}
        # DCLGEN host-variable form of the column name (``CUST_ID`` ->
        # ``CUST-ID``, see :func:`dclgen_name`) → DB2ColumnDefinition (first
        # occurrence wins)
        self._column_index: dict[str, DB2ColumnDefinition] = {}
        # DCLGEN host-variable form of the column name → tables defining it
        self._column_table_map: dict[str, list[str]] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(self, ast: CobolProgram) -> HostVarResolutionReport:
        """The same as :meth:`resolve`, under the name every program analyzer
        shares (:class:`~.protocol.ProgramAnalyzer`)."""
        return self.resolve(ast)

    def resolve(self, ast: CobolProgram) -> HostVarResolutionReport:
        """Run the full resolution pipeline and return a report.

        Args:
            ast: Parsed COBOL program AST.

        Returns:
            :class:`HostVarResolutionReport` with all resolved / unresolved
            host variables and the DECLARE TABLE index.
        """
        self._symbol_table = {}
        self._all_items = {}
        self._declare_tables = {}
        self._column_index = {}
        self._column_table_map = {}

        self._build_symbol_table(ast)
        self._collect_declare_tables(ast)

        # Identify column names that collide across multiple DECLARE TABLE blocks
        collisions = {
            col: tables
            for col, tables in self._column_table_map.items()
            if len(tables) > 1
        }
        report = HostVarResolutionReport(
            declare_tables=self._declare_tables,
            column_name_collisions=collisions,
        )
        self._resolve_host_vars(ast, report)
        return report

    # ------------------------------------------------------------------
    # Pass 1: symbol table from DATA DIVISION
    # ------------------------------------------------------------------

    def _build_symbol_table(
        self, node: ASTNode, ancestors: list[str] | None = None
    ) -> None:
        """Recursively collect CobolDataItem nodes into the symbol table."""
        ancestors = ancestors or []
        child_ancestors = ancestors
        if isinstance(node, CobolDataItem):
            name = (node.name or "").strip().upper()
            if name and not node.is_filler:
                # First occurrence wins (outer declaration takes precedence)
                self._symbol_table.setdefault(name, node)
                self._all_items.setdefault(name, []).append((node, ancestors))
            child_ancestors = [*ancestors, name] if name else ancestors

        if hasattr(node, "children"):
            for child in node.children:
                self._build_symbol_table(child, child_ancestors)

    def _lookup_item(self, upper: str, qualifiers: list[str]) -> CobolDataItem | None:
        """The data item *upper* names, honouring ``:STRUCT.NAME`` qualifiers.

        ``:DCLEMP.SALARY`` is the SALARY under DCLEMP, not whichever SALARY
        was declared first.
        """
        if qualifiers:
            for item, ancestors in self._all_items.get(upper, []):
                if all(q in ancestors for q in qualifiers):
                    return item
        return self._symbol_table.get(upper)

    # ------------------------------------------------------------------
    # Pass 2: collect DECLARE TABLE blocks
    # ------------------------------------------------------------------

    def _collect_declare_tables(self, node: ASTNode) -> None:
        """Recursively find DeclareTableStatement nodes and index their columns.

        When the same column name appears in multiple DECLARE TABLE blocks the
        first occurrence is kept in ``_column_index`` (so fallback resolution
        is deterministic) and the collision is recorded in ``_column_table_map``
        for later reporting.
        """
        if isinstance(node, DeclareTableStatement) and node.table_name:
            table_upper = node.table_name.upper()
            self._declare_tables[table_upper] = node
            for col in node.columns:
                # Keyed the way the host variable names it: DCLGEN turns
                # ``CUST_ID`` into ``CUST-ID`` (#572).
                col_upper = dclgen_name(col.name)
                self._column_table_map.setdefault(col_upper, [])
                self._column_table_map[col_upper].append(table_upper)
                # First occurrence wins — keeps fallback resolution deterministic
                self._column_index.setdefault(col_upper, col)

        if hasattr(node, "children"):
            for child in node.children:
                self._collect_declare_tables(child)

    # ------------------------------------------------------------------
    # Pass 3: resolve host variables in EXEC SQL statements
    # ------------------------------------------------------------------

    def _resolve_host_vars(
        self, node: ASTNode, report: HostVarResolutionReport
    ) -> None:
        """Walk the AST and resolve host variables in every ExecSQLStatement."""
        if isinstance(node, ExecSQLStatement) and not isinstance(
            node, DeclareTableStatement
        ):
            qualifiers: dict[str, list[str]] = {}
            scrubbed = _strip_sql_literals_and_comments(node.sql_text or "")
            for match in _QUALIFIED_HOST_VAR_RE.finditer(scrubbed):
                if match.group(1):
                    qualifiers.setdefault(
                        match.group(2).upper(),
                        [q.upper() for q in match.group(1).split(".") if q],
                    )
            for var_name in node.host_variables:
                self._resolve_one(
                    var_name, node, report, qualifiers.get(var_name.upper(), [])
                )

        if hasattr(node, "children"):
            for child in node.children:
                self._resolve_host_vars(child, report)

    def _resolve_one(
        self,
        var_name: str,
        stmt: ExecSQLStatement,
        report: HostVarResolutionReport,
        qualifiers: list[str] | None = None,
    ) -> None:
        """Resolve a single host variable name and update the report."""
        upper = var_name.upper()

        # Already resolved in a previous statement — just add the back-reference
        if upper in report.resolved:
            if stmt not in report.resolved[upper].sql_statements:
                report.resolved[upper].sql_statements.append(stmt)
            return

        data_item = self._lookup_item(upper, qualifiers or [])
        db2_col = self._column_index.get(dclgen_name(upper))

        if data_item is None and db2_col is None:
            report.unresolved.add(upper)
            return

        # Build HostVariableInfo
        if data_item is not None:
            pic_clause = data_item.picture_clause
            picture = pic_clause.pattern if pic_clause else None
            usage = data_item.usage
        else:
            # Fall back to DB2 column definition
            assert db2_col is not None
            picture = db2_col.cobol_picture
            usage = db2_col.cobol_usage

        info = HostVariableInfo(
            name=upper,
            picture=picture,
            usage=usage,
            data_item=data_item,
            db2_column=db2_col,
            sql_statements=[stmt],
        )
        report.resolved[upper] = info
        # If it was previously recorded as unresolved, remove it
        report.unresolved.discard(upper)

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------
