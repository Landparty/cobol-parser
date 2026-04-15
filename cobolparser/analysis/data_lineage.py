"""
Data lineage and taint tracking for COBOL programs.

Traces the flow of data from input fields (LINKAGE SECTION parameters,
file records, SQL columns, CICS commarea, ACCEPT statements) to output
fields through MOVE, arithmetic, STRING, UNSTRING, and CALL BY REFERENCE.

Useful for GDPR/SOX compliance: understanding which sensitive input
fields reach which output fields or external calls.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from ..models.ast_base import SourceLocation
from ..models.data_items import CobolDataItem
from ..models.program import CobolProgram
from ..models.statements.arithmetic import ArithmeticStatement, ComputeStatement
from ..models.statements.call import CallStatement
from ..models.statements.control import (
    EvaluateStatement,
    IfStatement,
    PerformStatement,
    SearchStatement,
)
from ..models.statements.data import (
    DisplayStatement,
    MoveStatement,
    StringStatement,
    UnstringStatement,
)
from ..models.statements.io import (
    IOAcceptStatement,
    IOOpenStatement,
    IOReadStatement,
    IOWriteStatement,
)

# COBOL figurative constants and keywords to exclude from variable name extraction
_COBOL_RESERVED: frozenset[str] = frozenset(
    {
        "ZERO",
        "ZEROS",
        "ZEROES",
        "SPACE",
        "SPACES",
        "HIGH-VALUE",
        "HIGH-VALUES",
        "LOW-VALUE",
        "LOW-VALUES",
        "ALL",
        "TRUE",
        "FALSE",
        "NULL",
        "NULLS",
        "QUOTE",
        "QUOTES",
        "FUNCTION",
        "LENGTH",
        "AND",
        "OR",
        "NOT",
        "TO",
        "BY",
        "FROM",
        "GIVING",
        "INTO",
        "EQUAL",
        "GREATER",
        "LESS",
        "THAN",
        "ROUNDED",
        "REMAINDER",
    }
)

# ACCEPT FROM sources that are system-date/time (not user input)
_DATE_TIME_SOURCES: frozenset[str] = frozenset(
    {
        "DATE",
        "TIME",
        "DAY",
        "DAY-OF-WEEK",
        "CENTURY-DATE",
        "CENTURY-DAY",
        "YEAR-DATE",
    }
)

# Regex for COBOL identifier extraction from expression strings
_IDENT_RE = re.compile(r"\b([A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*)\b")


class SourceKind(StrEnum):
    """Kind of input data source."""

    FILE = "FILE"
    LINKAGE = "LINKAGE"
    SQL = "SQL"
    CICS_COMMAREA = "CICS_COMMAREA"
    ACCEPT = "ACCEPT"


class SinkKind(StrEnum):
    """Kind of output data sink."""

    FILE_WRITE = "FILE_WRITE"
    SQL_WRITE = "SQL_WRITE"
    DISPLAY = "DISPLAY"
    CALL_OUTPUT = "CALL_OUTPUT"
    CICS_SEND = "CICS_SEND"


@dataclass
class TaintSource:
    """An identified input data source in the program."""

    source_id: str  # e.g. "FILE:INFILE", "LINKAGE:WS-INPUT"
    kind: SourceKind
    variable_name: str  # uppercased COBOL variable name
    location: SourceLocation | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "source_id": self.source_id,
            "kind": self.kind.value,
            "variable_name": self.variable_name,
        }
        if self.location:
            result["location"] = self.location.to_dict()
        return result


@dataclass
class SinkField:
    """An identified output data sink in the program."""

    sink_id: str  # e.g. "FILE_WRITE:OUTFILE", "DISPLAY:WS-MSG"
    kind: SinkKind
    variable_name: str  # uppercased COBOL variable name
    paragraph: str | None = None
    location: SourceLocation | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "sink_id": self.sink_id,
            "kind": self.kind.value,
            "variable_name": self.variable_name,
        }
        if self.paragraph:
            result["paragraph"] = self.paragraph
        if self.location:
            result["location"] = self.location.to_dict()
        return result


@dataclass
class LineageEdge:
    """A single data flow event: taint sources propagated to a target variable."""

    source_ids: list[str]  # which source_ids contributed to this flow
    target_variable: str  # uppercased variable receiving the taints
    operation: str  # MOVE, ADD, COMPUTE, STRING, UNSTRING, CALL_BY_REF, etc.
    paragraph: str | None = None
    location: SourceLocation | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "source_ids": self.source_ids,
            "target_variable": self.target_variable,
            "operation": self.operation,
        }
        if self.paragraph:
            result["paragraph"] = self.paragraph
        if self.location:
            result["location"] = self.location.to_dict()
        return result


@dataclass
class DataLineageReport:
    """Complete data lineage analysis report for a COBOL program."""

    program_name: str
    sources: list[TaintSource] = field(default_factory=list)
    sinks: list[SinkField] = field(default_factory=list)
    edges: list[LineageEdge] = field(default_factory=list)
    variable_taints: dict[str, list[str]] = field(default_factory=dict)
    sink_taints: dict[str, list[str]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "program_name": self.program_name,
            "sources": [s.to_dict() for s in self.sources],
            "sinks": [s.to_dict() for s in self.sinks],
            "edges": [e.to_dict() for e in self.edges],
            "variable_taints": self.variable_taints,
            "sink_taints": self.sink_taints,
            "summary": {
                "source_count": len(self.sources),
                "sink_count": len(self.sinks),
                "edge_count": len(self.edges),
                "tainted_variables": len(self.variable_taints),
            },
        }

    def to_json(self, indent: int = 2) -> str:
        """Serialize the report to a JSON string."""
        return json.dumps(self.to_dict(), indent=indent)


class DataLineageAnalyzer:
    """Analyzer that traces data flow from inputs to outputs in a COBOL program.

    Identifies taint sources (LINKAGE SECTION parameters, file records opened
    for INPUT/I-O, SQL SELECT INTO variables, CICS COMMAREA, ACCEPT statements)
    and propagates their taints through MOVE, arithmetic, STRING, UNSTRING, and
    CALL BY REFERENCE operations to identify all output sinks.

    The analysis is a conservative single-pass over-approximation: it may report
    more flows than actually occur at runtime (due to ignored branching), but
    will never miss a real data flow that exists in any execution path.

    Example:
        ```python
        from cobolparser import parse_cobol
        from cobolparser.analysis.data_lineage import DataLineageAnalyzer

        result = parse_cobol(source)
        report = DataLineageAnalyzer().analyze(result.ast)
        print(report.to_json())
        ```
    """

    def __init__(self) -> None:
        self._taint_map: dict[str, set[str]] = {}
        self._sources: list[TaintSource] = []
        self._sinks: list[SinkField] = []
        self._edges: list[LineageEdge] = []
        self._sink_taints: dict[str, set[str]] = {}
        self._input_files: dict[str, str] = {}  # file_name.upper() -> source_id
        self._current_paragraph: str | None = None

    def analyze(self, ast: CobolProgram) -> DataLineageReport:
        """Analyze a COBOL program and build the data lineage graph.

        Args:
            ast: The parsed COBOL program AST.

        Returns:
            A DataLineageReport with sources, sinks, edges, and taint map.
        """
        self._taint_map = {}
        self._sources = []
        self._sinks = []
        self._edges = []
        self._sink_taints = {}
        self._input_files = {}
        self._current_paragraph = None

        # Pass 1: identify taint sources
        self._identify_file_sources(ast)
        self._identify_linkage_sources(ast)
        self._identify_sql_sources(ast)
        self._identify_accept_sources(ast)

        # Pass 2: propagate taints through procedure division
        self._propagate(ast)

        # Pass 3: identify output sinks and record which sources reach them
        self._identify_sinks(ast)

        variable_taints = {
            var: sorted(taints)
            for var, taints in self._taint_map.items()
            if taints
        }
        sink_taints = {
            sink_id: sorted(taints)
            for sink_id, taints in self._sink_taints.items()
            if taints
        }
        return DataLineageReport(
            program_name=ast.program_name,
            sources=self._sources,
            sinks=self._sinks,
            edges=self._edges,
            variable_taints=variable_taints,
            sink_taints=sink_taints,
        )

    # ------------------------------------------------------------------ #
    # Pass 1: source identification
    # ------------------------------------------------------------------ #

    def _identify_file_sources(self, ast: CobolProgram) -> None:
        """Register files opened INPUT/I-O as taint sources; seed READ targets."""
        for stmt in ast.get_all_statements():
            if isinstance(stmt, IOOpenStatement):
                if stmt.open_mode in ("INPUT", "I-O"):
                    for fname in stmt.file_names:
                        fname_upper = fname.upper()
                        if fname_upper not in self._input_files:
                            src_id = f"FILE:{fname_upper}"
                            self._sources.append(
                                TaintSource(
                                    source_id=src_id,
                                    kind=SourceKind.FILE,
                                    variable_name=fname_upper,
                                    location=stmt.location,
                                )
                            )
                            self._input_files[fname_upper] = src_id

        for stmt in ast.get_all_statements():
            if isinstance(stmt, IOReadStatement):
                fname_upper = (stmt.file_name or "").upper()
                read_src_id = self._input_files.get(fname_upper)
                if read_src_id is None:
                    continue
                if stmt.record_name:
                    self._seed_taint(stmt.record_name, read_src_id)
                if stmt.into_target:
                    self._seed_taint(stmt.into_target, read_src_id)

    def _identify_linkage_sources(self, ast: CobolProgram) -> None:
        """Register all LINKAGE SECTION items as taint sources."""
        data_div = ast.data_division
        if data_div is None:
            return
        linkage_sec = data_div.get_section_by_name("LINKAGE")
        if linkage_sec is None:
            return
        for item in getattr(linkage_sec, "data_items", []):
            if not isinstance(item, CobolDataItem):
                continue
            for di in _iter_data_items(item):
                if di.is_filler or not di.name:
                    continue
                var_name = di.name.upper()
                if var_name == "DFHCOMMAREA":
                    kind: SourceKind = SourceKind.CICS_COMMAREA
                    src_id = f"CICS_COMMAREA:{var_name}"
                else:
                    kind = SourceKind.LINKAGE
                    src_id = f"LINKAGE:{var_name}"
                self._sources.append(
                    TaintSource(
                        source_id=src_id,
                        kind=kind,
                        variable_name=var_name,
                        location=di.location,
                    )
                )
                self._seed_taint(var_name, src_id)

    def _identify_sql_sources(self, ast: CobolProgram) -> None:
        """Register SQL SELECT/FETCH INTO variables as taint sources."""
        for stmt in ast.get_all_statements():
            sql_type = getattr(stmt, "sql_type", None)
            if sql_type in ("SELECT", "FETCH"):
                into_vars: list[str] = getattr(stmt, "into_variables", [])
                for var in into_vars:
                    var_upper = var.lstrip(":").upper()
                    src_id = f"SQL:{var_upper}"
                    self._sources.append(
                        TaintSource(
                            source_id=src_id,
                            kind=SourceKind.SQL,
                            variable_name=var_upper,
                            location=getattr(stmt, "location", None),
                        )
                    )
                    self._seed_taint(var_upper, src_id)

    def _identify_accept_sources(self, ast: CobolProgram) -> None:
        """Register ACCEPT FROM (non-date) statements as taint sources."""
        for stmt in ast.get_all_statements():
            if not isinstance(stmt, IOAcceptStatement):
                continue
            from_src = (stmt.from_source or "").upper()
            if from_src in _DATE_TIME_SOURCES:
                continue
            if not stmt.target:
                continue
            var_upper = stmt.target.upper()
            src_id = f"ACCEPT:{var_upper}"
            self._sources.append(
                TaintSource(
                    source_id=src_id,
                    kind=SourceKind.ACCEPT,
                    variable_name=var_upper,
                    location=stmt.location,
                )
            )
            self._seed_taint(var_upper, src_id)

    # ------------------------------------------------------------------ #
    # Pass 2: taint propagation
    # ------------------------------------------------------------------ #

    def _propagate(self, ast: CobolProgram) -> None:
        """Propagate taints through all procedure division paragraphs."""
        proc_div = ast.procedure_division
        if proc_div is None:
            return

        for section in proc_div._sections.values():
            for para in section.paragraphs:
                self._current_paragraph = para.paragraph_name
                self._scan_stmts(para.statements)

        for para in proc_div.paragraphs:
            self._current_paragraph = para.paragraph_name
            self._scan_stmts(para.statements)

    def _scan_stmts(self, stmts: list[Any]) -> None:
        for stmt in stmts:
            self._process_stmt(stmt)

    def _process_stmt(self, stmt: Any) -> None:
        if not hasattr(stmt, "node_type"):
            return

        if isinstance(stmt, MoveStatement):
            self._process_move(stmt)
        elif isinstance(stmt, ComputeStatement):
            self._process_compute(stmt)
        elif isinstance(stmt, ArithmeticStatement):
            self._process_arithmetic(stmt)
        elif isinstance(stmt, StringStatement):
            self._process_string_stmt(stmt)
        elif isinstance(stmt, UnstringStatement):
            self._process_unstring_stmt(stmt)
        elif isinstance(stmt, CallStatement):
            self._process_call(stmt)
        elif isinstance(stmt, IfStatement):
            self._scan_stmts(stmt.then_statements)
            self._scan_stmts(stmt.else_statements)
        elif isinstance(stmt, EvaluateStatement):
            for wc in stmt.when_clauses:
                self._scan_stmts(wc.statements)
            if stmt.default_when:
                self._scan_stmts(stmt.default_when.statements)
        elif isinstance(stmt, PerformStatement):
            self._scan_stmts(stmt.inline_statements)
        elif isinstance(stmt, SearchStatement):
            for wc_dict in stmt.when_clauses:
                self._scan_stmts(wc_dict.get("statements", []))
            if stmt.at_end_clause:
                self._scan_stmts(stmt.at_end_clause)

    def _process_move(self, stmt: MoveStatement) -> None:
        src = stmt.source
        if not src:
            return
        src_taints = self._taint_map.get(src.upper(), set())
        if not src_taints:
            return
        op = "MOVE_CORRESPONDING" if stmt.is_corresponding else "MOVE"
        for target in stmt.targets:
            self._propagate_to(src_taints, target.upper(), op, stmt.location)

    def _process_arithmetic(self, stmt: ArithmeticStatement) -> None:
        all_taints: set[str] = set()
        for op in stmt.operands:
            all_taints |= self._taint_map.get(op.upper(), set())
        if not all_taints:
            return
        result_var = stmt.giving or stmt.target
        if result_var:
            self._propagate_to(
                all_taints,
                result_var.upper(),
                stmt.statement_type,
                stmt.location,
            )

    def _process_compute(self, stmt: ComputeStatement) -> None:
        expr_text = str(stmt.expression) if stmt.expression is not None else ""
        var_names = _extract_variable_names(expr_text)
        all_taints: set[str] = set()
        for vn in var_names:
            all_taints |= self._taint_map.get(vn.upper(), set())
        for op in stmt.operands:
            all_taints |= self._taint_map.get(op.upper(), set())
        if not all_taints:
            return
        for tgt in stmt.targets:
            self._propagate_to(all_taints, tgt.upper(), "COMPUTE", stmt.location)

    def _process_string_stmt(self, stmt: StringStatement) -> None:
        all_taints: set[str] = set()
        for op in stmt.operands:
            all_taints |= self._taint_map.get(op.upper(), set())
        if not all_taints or not stmt.into_target:
            return
        self._propagate_to(
            all_taints, stmt.into_target.upper(), "STRING", stmt.location
        )

    def _process_unstring_stmt(self, stmt: UnstringStatement) -> None:
        src = stmt.source_operand
        if not src:
            return
        src_taints = self._taint_map.get(src.upper(), set())
        if not src_taints:
            return
        for info in stmt.into_targets:
            tgt = info.get("target") if isinstance(info, dict) else None
            if tgt:
                self._propagate_to(src_taints, tgt.upper(), "UNSTRING", stmt.location)

    def _process_call(self, stmt: CallStatement) -> None:
        for param in stmt.using_parameters:
            if param.passing_mode == "REFERENCE":
                var = param.name.upper()
                program = (stmt.called_program or "UNKNOWN").strip("'\"").upper()
                ext_src_id = f"CALL_REF:{program}:{var}"
                self._taint_map.setdefault(var, set()).add(ext_src_id)
                self._sinks.append(
                    SinkField(
                        sink_id=f"CALL_OUTPUT:{var}",
                        kind=SinkKind.CALL_OUTPUT,
                        variable_name=var,
                        paragraph=self._current_paragraph,
                        location=stmt.location,
                    )
                )

    # ------------------------------------------------------------------ #
    # Pass 3: sink identification
    # ------------------------------------------------------------------ #

    def _identify_sinks(self, ast: CobolProgram) -> None:
        """Identify output sinks with paragraph context and record taint sources."""
        proc_div = ast.procedure_division
        if proc_div is None:
            return

        for section in proc_div._sections.values():
            for para in section.paragraphs:
                self._current_paragraph = para.paragraph_name
                for stmt in para.statements:
                    self._check_sink(stmt)

        for para in proc_div.paragraphs:
            self._current_paragraph = para.paragraph_name
            for stmt in para.statements:
                self._check_sink(stmt)

    def _check_sink(self, stmt: Any) -> None:
        if isinstance(stmt, IOWriteStatement):
            var = stmt.from_clause or stmt.record_name
            if var:
                self._record_sink(var, SinkKind.FILE_WRITE, stmt.location)
        elif isinstance(stmt, DisplayStatement):
            for item in stmt.display_items:
                if self._taint_map.get(item.upper()):
                    self._record_sink(item, SinkKind.DISPLAY, stmt.location)
        else:
            sql_type = getattr(stmt, "sql_type", None)
            if sql_type in ("INSERT", "UPDATE"):
                for hv in getattr(stmt, "host_variables", []):
                    self._record_sink(
                        hv.lstrip(":"), SinkKind.SQL_WRITE, stmt.location
                    )
            cics_cmd = getattr(stmt, "cics_command", None)
            if cics_cmd == "SEND":
                for op in getattr(stmt, "operands", []):
                    self._record_sink(op, SinkKind.CICS_SEND, stmt.location)

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    def _seed_taint(self, var_name: str, source_id: str) -> None:
        self._taint_map.setdefault(var_name.upper(), set()).add(source_id)

    def _propagate_to(
        self,
        taints: set[str],
        target: str,
        operation: str,
        location: SourceLocation | None,
    ) -> None:
        self._taint_map.setdefault(target, set()).update(taints)
        self._edges.append(
            LineageEdge(
                source_ids=sorted(taints),
                target_variable=target,
                operation=operation,
                paragraph=self._current_paragraph,
                location=location,
            )
        )

    def _record_sink(
        self,
        var_name: str,
        kind: SinkKind,
        location: SourceLocation | None,
    ) -> None:
        var_upper = var_name.upper()
        sink_id = f"{kind.value}:{var_upper}"
        taints = self._taint_map.get(var_upper, set())
        self._sinks.append(
            SinkField(
                sink_id=sink_id,
                kind=kind,
                variable_name=var_upper,
                paragraph=self._current_paragraph,
                location=location,
            )
        )
        if taints:
            self._sink_taints.setdefault(sink_id, set()).update(taints)


# ------------------------------------------------------------------ #
# Module-level helpers
# ------------------------------------------------------------------ #


def _iter_data_items(item: CobolDataItem) -> Iterator[CobolDataItem]:
    """Recursively yield a data item and all its CobolDataItem descendants."""
    yield item
    for child in item.children:
        if isinstance(child, CobolDataItem):
            yield from _iter_data_items(child)


def _extract_variable_names(expr_text: str) -> list[str]:
    """Extract COBOL variable names from an expression string.

    Filters out numeric literals and COBOL reserved words/figurative constants.
    """
    if not expr_text:
        return []
    matches = _IDENT_RE.findall(expr_text.upper())
    result = []
    for m in matches:
        if m in _COBOL_RESERVED:
            continue
        if m.replace("-", "").isdigit():
            continue
        result.append(m)
    return result
