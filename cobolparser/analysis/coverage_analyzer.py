"""
Coverage analyzer for COBOL AST.

Walks the parsed AST and produces a CoverageMap identifying every paragraph,
branch point, I/O path, arithmetic error path, and data dependency that
needs testing for full coverage.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum

from ..models.ast_base import ASTNode, SourceLocation
from ..models.data_items import CobolDataItem
from ..models.program import CobolDivision, CobolParagraph, CobolProgram
from ..models.statements.arithmetic import ArithmeticStatement, ComputeStatement
from ..models.statements.base import CobolStatement
from ..models.statements.call import CallStatement
from ..models.statements.control import (
    EvaluateStatement,
    IfStatement,
    PerformStatement,
    SearchStatement,
    StopStatement,
)
from ..models.statements.data import (
    DisplayStatement,
    MoveStatement,
    SetStatement,
    StringStatement,
    UnstringStatement,
)
from ..models.statements.io import (
    IOAcceptStatement,
    IODeleteStatement,
    IOReadStatement,
    IORewriteStatement,
    IOStartStatement,
    IOWriteStatement,
)
from ..models.statements.misc import GobackStatement


class BranchType(StrEnum):
    """Type of branch point in the program."""

    IF_TRUE = "if_true"
    IF_FALSE = "if_false"
    EVALUATE_WHEN = "evaluate_when"
    EVALUATE_DEFAULT = "evaluate_default"
    SEARCH_WHEN = "search_when"
    SEARCH_AT_END = "search_at_end"
    IO_AT_END = "io_at_end"
    IO_NOT_AT_END = "io_not_at_end"
    IO_INVALID_KEY = "io_invalid_key"
    IO_NOT_INVALID_KEY = "io_not_invalid_key"
    IO_AT_EOP = "io_at_eop"
    ARITH_SIZE_ERROR = "arith_size_error"
    ARITH_NOT_SIZE_ERROR = "arith_not_size_error"
    CALL_ON_EXCEPTION = "call_on_exception"
    CALL_NOT_ON_EXCEPTION = "call_not_on_exception"
    STRING_ON_OVERFLOW = "string_on_overflow"
    STRING_NOT_ON_OVERFLOW = "string_not_on_overflow"
    PERFORM_BODY = "perform_body"


@dataclass
class BranchPoint:
    """A single branch within a statement that needs testing."""

    branch_type: BranchType
    parent_statement_type: str
    paragraph_name: str
    condition_text: str | None = None
    location: SourceLocation | None = None


@dataclass
class ParagraphCoverage:
    """Coverage information for a single paragraph."""

    paragraph_name: str
    section_name: str | None = None
    statement_count: int = 0
    branch_points: list[BranchPoint] = field(default_factory=list)
    reads_variables: set[str] = field(default_factory=set)
    writes_variables: set[str] = field(default_factory=set)
    calls_paragraphs: list[str] = field(default_factory=list)
    has_stop_run: bool = False
    has_goback: bool = False
    is_empty: bool = False


@dataclass
class DataItemInfo:
    """Simplified data item info for test generation."""

    name: str
    level: int
    picture_pattern: str | None = None
    is_numeric: bool = False
    is_signed: bool = False
    decimal_digits: int = 0
    integer_digits: int = 0
    size: int | None = None
    initial_value: str | None = None
    usage: str = "DISPLAY"


@dataclass
class CoverageMap:
    """Complete coverage map of a COBOL program."""

    program_name: str
    paragraphs: list[ParagraphCoverage] = field(default_factory=list)
    data_items: list[DataItemInfo] = field(default_factory=list)
    total_branch_points: int = 0
    total_paragraphs: int = 0
    has_procedure_division: bool = False

    def get_paragraph(self, name: str) -> ParagraphCoverage | None:
        """Look up paragraph coverage by name."""
        upper = name.upper()
        for p in self.paragraphs:
            if p.paragraph_name.upper() == upper:
                return p
        return None

    def get_data_item(self, name: str) -> DataItemInfo | None:
        """Look up a data item by name."""
        upper = name.upper()
        for d in self.data_items:
            if d.name.upper() == upper:
                return d
        return None


class CoverageAnalyzer:
    """Walks a COBOL AST and produces a CoverageMap."""

    def __init__(self) -> None:
        self._coverage_map: CoverageMap | None = None

    def analyze(self, program: CobolProgram) -> CoverageMap:
        """Analyze a parsed COBOL program and return its coverage map."""
        program_name = ""
        id_div = program.get_division("IDENTIFICATION")
        if id_div is not None:
            # program_id may be a direct attribute or stored in metadata
            program_name = (
                getattr(id_div, "program_id", "")
                or (id_div._metadata or {}).get("program_id", "")
                or ""
            )

        if not program_name:
            program_name = getattr(program, "program_name", "") or "UNKNOWN"

        cmap = CoverageMap(program_name=program_name)

        proc_div = program.get_division("PROCEDURE")
        if proc_div is None:
            self._coverage_map = cmap
            return cmap

        cmap.has_procedure_division = True
        cmap.paragraphs = self._analyze_paragraphs(proc_div)
        cmap.data_items = self._extract_data_items(program)
        cmap.total_paragraphs = len(cmap.paragraphs)
        cmap.total_branch_points = sum(len(p.branch_points) for p in cmap.paragraphs)
        self._coverage_map = cmap
        return cmap

    def _analyze_paragraphs(
        self, proc_division: CobolDivision
    ) -> list[ParagraphCoverage]:
        """Extract paragraph info from PROCEDURE division."""
        results: list[ParagraphCoverage] = []

        # Paragraphs directly on the division (no section)
        for para in proc_division.paragraphs:
            results.append(self._analyze_paragraph(para, section_name=None))

        # Paragraphs within sections
        for section in proc_division._sections.values():
            for para in section.paragraphs:
                results.append(
                    self._analyze_paragraph(para, section_name=section.section_name)
                )

        return results

    def _analyze_paragraph(
        self,
        paragraph: CobolParagraph,
        section_name: str | None = None,
    ) -> ParagraphCoverage:
        """Analyze a single paragraph for coverage targets."""
        pc = ParagraphCoverage(
            paragraph_name=paragraph.paragraph_name,
            section_name=section_name,
        )

        statements = paragraph.statements
        pc.statement_count = len(statements)
        pc.is_empty = pc.statement_count == 0

        for stmt in statements:
            # Collect branch points
            pc.branch_points.extend(
                self._collect_branch_points(stmt, paragraph.paragraph_name)
            )
            # Collect variable reads/writes
            pc.reads_variables.update(self._collect_variable_reads(stmt))
            pc.writes_variables.update(self._collect_variable_writes(stmt))
            # Detect STOP RUN / GOBACK
            if isinstance(stmt, StopStatement):
                pc.has_stop_run = True
            if isinstance(stmt, GobackStatement):
                pc.has_goback = True
            # Track PERFORM targets
            if isinstance(stmt, PerformStatement) and stmt.target_paragraph:
                pc.calls_paragraphs.append(stmt.target_paragraph)

        return pc

    def _collect_branch_points(
        self,
        statement: CobolStatement,
        paragraph_name: str,
    ) -> list[BranchPoint]:
        """Recursively collect branch points from a statement tree."""
        points: list[BranchPoint] = []
        loc = statement.location if hasattr(statement, "location") else None

        # IF statement
        if isinstance(statement, IfStatement):
            condition_text = None
            if statement.condition is not None:
                condition_text = str(
                    statement.condition.to_dict()
                    if hasattr(statement.condition, "to_dict")
                    else statement.condition
                )
            points.append(
                BranchPoint(
                    branch_type=BranchType.IF_TRUE,
                    parent_statement_type="IF",
                    paragraph_name=paragraph_name,
                    condition_text=condition_text,
                    location=loc,
                )
            )
            points.append(
                BranchPoint(
                    branch_type=BranchType.IF_FALSE,
                    parent_statement_type="IF",
                    paragraph_name=paragraph_name,
                    condition_text=condition_text,
                    location=loc,
                )
            )
            # Recurse into branches
            for s in statement.then_statements:
                points.extend(self._collect_branch_points(s, paragraph_name))
            for s in statement.else_statements:
                points.extend(self._collect_branch_points(s, paragraph_name))

        # EVALUATE statement
        elif isinstance(statement, EvaluateStatement):
            for wc in statement.when_clauses:
                selector_text = str(wc.selectors) if wc.selectors else None
                points.append(
                    BranchPoint(
                        branch_type=BranchType.EVALUATE_WHEN,
                        parent_statement_type="EVALUATE",
                        paragraph_name=paragraph_name,
                        condition_text=selector_text,
                        location=loc,
                    )
                )
                for s in wc.statements:
                    points.extend(self._collect_branch_points(s, paragraph_name))
            if statement.default_when is not None:
                points.append(
                    BranchPoint(
                        branch_type=BranchType.EVALUATE_DEFAULT,
                        parent_statement_type="EVALUATE",
                        paragraph_name=paragraph_name,
                        condition_text="WHEN OTHER",
                        location=loc,
                    )
                )
                for s in statement.default_when.statements:
                    points.extend(self._collect_branch_points(s, paragraph_name))

        # SEARCH statement (when_clauses are list[dict], not WhenClause)
        elif isinstance(statement, SearchStatement):
            for wc in statement.when_clauses:  # type: ignore[assignment]
                points.append(
                    BranchPoint(
                        branch_type=BranchType.SEARCH_WHEN,
                        parent_statement_type="SEARCH",
                        paragraph_name=paragraph_name,
                        condition_text=wc.get("condition"),  # type: ignore[attr-defined]
                        location=loc,
                    )
                )
                for s in wc.get("statements", []):  # type: ignore[attr-defined]
                    points.extend(self._collect_branch_points(s, paragraph_name))
            if statement.at_end_clause:
                points.append(
                    BranchPoint(
                        branch_type=BranchType.SEARCH_AT_END,
                        parent_statement_type="SEARCH",
                        paragraph_name=paragraph_name,
                        condition_text="AT END",
                        location=loc,
                    )
                )
                for s in statement.at_end_clause:
                    points.extend(self._collect_branch_points(s, paragraph_name))

        # PERFORM with inline statements
        elif isinstance(statement, PerformStatement):
            if statement.inline_statements:
                points.append(
                    BranchPoint(
                        branch_type=BranchType.PERFORM_BODY,
                        parent_statement_type="PERFORM",
                        paragraph_name=paragraph_name,
                        condition_text=None,
                        location=loc,
                    )
                )
                for s in statement.inline_statements:
                    points.extend(self._collect_branch_points(s, paragraph_name))

        # IO statements with clauses
        elif isinstance(statement, IOReadStatement):
            for clause_name, branch_type in (
                ("at_end_clause", BranchType.IO_AT_END),
                ("not_at_end_clause", BranchType.IO_NOT_AT_END),
                ("invalid_key_clause", BranchType.IO_INVALID_KEY),
                ("not_invalid_key_clause", BranchType.IO_NOT_INVALID_KEY),
            ):
                clause_stmts = getattr(statement, clause_name, None)
                if clause_stmts:
                    points.append(
                        BranchPoint(
                            branch_type=branch_type,
                            parent_statement_type="READ",
                            paragraph_name=paragraph_name,
                            location=loc,
                        )
                    )
                    for s in clause_stmts:
                        points.extend(self._collect_branch_points(s, paragraph_name))

        elif isinstance(statement, IOWriteStatement):
            for clause_name, branch_type in (
                ("at_eop_clause", BranchType.IO_AT_EOP),
                ("invalid_key_clause", BranchType.IO_INVALID_KEY),
                ("not_invalid_key_clause", BranchType.IO_NOT_INVALID_KEY),
            ):
                clause_stmts = getattr(statement, clause_name, None)
                if clause_stmts:
                    points.append(
                        BranchPoint(
                            branch_type=branch_type,
                            parent_statement_type="WRITE",
                            paragraph_name=paragraph_name,
                            location=loc,
                        )
                    )
                    for s in clause_stmts:
                        points.extend(self._collect_branch_points(s, paragraph_name))

        elif isinstance(
            statement, (IODeleteStatement, IORewriteStatement, IOStartStatement)
        ):
            for clause_name, branch_type in (
                ("invalid_key_clause", BranchType.IO_INVALID_KEY),
                ("not_invalid_key_clause", BranchType.IO_NOT_INVALID_KEY),
            ):
                clause_stmts = getattr(statement, clause_name, None)
                if clause_stmts:
                    points.append(
                        BranchPoint(
                            branch_type=branch_type,
                            parent_statement_type=statement.statement_type,
                            paragraph_name=paragraph_name,
                            location=loc,
                        )
                    )
                    for s in clause_stmts:
                        points.extend(self._collect_branch_points(s, paragraph_name))

        # Arithmetic size error
        elif isinstance(statement, (ArithmeticStatement, ComputeStatement)):
            for clause_name, branch_type in (
                ("on_size_error", BranchType.ARITH_SIZE_ERROR),
                ("not_on_size_error", BranchType.ARITH_NOT_SIZE_ERROR),
            ):
                clause_stmts = getattr(statement, clause_name, None)
                if clause_stmts:
                    points.append(
                        BranchPoint(
                            branch_type=branch_type,
                            parent_statement_type=statement.statement_type,
                            paragraph_name=paragraph_name,
                            location=loc,
                        )
                    )
                    for s in clause_stmts:
                        points.extend(self._collect_branch_points(s, paragraph_name))

        # CALL exception
        elif isinstance(statement, CallStatement):
            for clause_name, branch_type in (
                ("on_exception", BranchType.CALL_ON_EXCEPTION),
                ("not_on_exception", BranchType.CALL_NOT_ON_EXCEPTION),
            ):
                clause_stmts = getattr(statement, clause_name, None)
                if clause_stmts:
                    points.append(
                        BranchPoint(
                            branch_type=branch_type,
                            parent_statement_type="CALL",
                            paragraph_name=paragraph_name,
                            location=loc,
                        )
                    )
                    for s in clause_stmts:
                        points.extend(self._collect_branch_points(s, paragraph_name))

        # STRING / UNSTRING overflow
        elif isinstance(statement, (StringStatement, UnstringStatement)):
            for clause_name, branch_type in (
                ("on_overflow", BranchType.STRING_ON_OVERFLOW),
                ("not_on_overflow", BranchType.STRING_NOT_ON_OVERFLOW),
            ):
                clause_stmts = getattr(statement, clause_name, None)
                if clause_stmts:
                    points.append(
                        BranchPoint(
                            branch_type=branch_type,
                            parent_statement_type=statement.statement_type,
                            paragraph_name=paragraph_name,
                            location=loc,
                        )
                    )
                    for s in clause_stmts:
                        points.extend(self._collect_branch_points(s, paragraph_name))

        return points

    def _collect_variable_reads(self, statement: ASTNode) -> set[str]:
        """Collect variables read by a statement (best-effort)."""
        reads: set[str] = set()

        if isinstance(statement, MoveStatement):
            if statement.source and self._is_variable_name(statement.source):
                reads.add(statement.source.upper())
        elif isinstance(statement, DisplayStatement):
            for item in statement.display_items:
                if self._is_variable_name(item):
                    reads.add(item.upper())
        elif isinstance(statement, (ArithmeticStatement, ComputeStatement)):
            # Operands minus last one (which is typically the target)
            for op in statement.operands:
                if self._is_variable_name(op):
                    reads.add(op.upper())
        elif isinstance(statement, CallStatement):
            for param in statement.using_parameters:
                reads.add(param.name.upper())
        elif isinstance(statement, IfStatement):
            if statement.condition and hasattr(statement.condition, "operands"):
                for op in statement.condition.operands:
                    if self._is_variable_name(op):
                        reads.add(op.upper())
        elif isinstance(statement, SetStatement):
            for op in statement.operands:
                if self._is_variable_name(op):
                    reads.add(op.upper())

        # Recurse into all nested statement containers
        for s in self._nested_statements(statement):
            reads.update(self._collect_variable_reads(s))

        return reads

    _FIGURATIVE_CONSTANTS = frozenset(
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
            "QUOTE",
            "QUOTES",
            "ALL",
            "NULL",
            "NULLS",
            "TRUE",
            "FALSE",
        }
    )

    @classmethod
    def _is_variable_name(cls, value: str) -> bool:
        """Return True if the value looks like a COBOL variable name.

        Filters out quoted string literals, numeric literals, and
        figurative constants so they don't pollute reads_variables.
        """
        stripped = value.strip()
        if not stripped:
            return False
        # Quoted strings
        if (stripped.startswith('"') and stripped.endswith('"')) or (
            stripped.startswith("'") and stripped.endswith("'")
        ):
            return False
        # Numeric literals (with optional sign and decimal point)
        numeric = stripped.lstrip("+-")
        if numeric and numeric.replace(".", "", 1).isdigit():
            return False
        # Figurative constants
        if stripped.upper() in cls._FIGURATIVE_CONSTANTS:
            return False
        return True

    @staticmethod
    def _nested_statements(statement: ASTNode) -> list[ASTNode]:
        """Return all nested statement lists from any container statement."""
        stmts: list[ASTNode] = []

        if isinstance(statement, IfStatement):
            stmts.extend(statement.then_statements)
            stmts.extend(statement.else_statements)
        elif isinstance(statement, EvaluateStatement):
            for wc in statement.when_clauses:
                stmts.extend(wc.statements)
            if statement.default_when:
                stmts.extend(statement.default_when.statements)
        elif isinstance(statement, SearchStatement):
            for wc in statement.when_clauses:  # type: ignore[assignment]
                stmts.extend(wc.get("statements", []))  # type: ignore[attr-defined]
            if statement.at_end_clause:
                stmts.extend(statement.at_end_clause)
        elif isinstance(statement, PerformStatement):
            stmts.extend(statement.inline_statements)

        # IO clause bodies
        for attr in (
            "at_end_clause",
            "not_at_end_clause",
            "invalid_key_clause",
            "not_invalid_key_clause",
            "at_eop_clause",
        ):
            clause = getattr(statement, attr, None)
            if clause and isinstance(clause, list):
                stmts.extend(clause)

        # Arithmetic / CALL / STRING handler bodies
        for attr in (
            "on_size_error",
            "not_on_size_error",
            "on_exception",
            "not_on_exception",
            "on_overflow",
            "not_on_overflow",
        ):
            clause = getattr(statement, attr, None)
            if clause and isinstance(clause, list):
                stmts.extend(clause)

        return stmts

    def _collect_variable_writes(self, statement: ASTNode) -> set[str]:
        """Collect variables written by a statement (best-effort)."""
        writes: set[str] = set()

        if isinstance(statement, MoveStatement):
            for target in statement.targets:
                writes.add(target.upper())
        elif isinstance(statement, ComputeStatement):
            for target in statement.targets:
                writes.add(target.upper())
        elif isinstance(statement, ArithmeticStatement):
            if hasattr(statement, "target") and statement.target:
                writes.add(statement.target.upper())
            if hasattr(statement, "giving") and statement.giving:
                writes.add(statement.giving.upper())
        elif isinstance(statement, UnstringStatement):
            for into in statement.into_targets:
                into_target: str | None = into.get("target")
                if into_target:
                    writes.add(into_target.upper())
        elif isinstance(statement, IOReadStatement):
            if statement.into_target:
                writes.add(statement.into_target.upper())
        elif isinstance(statement, IOAcceptStatement):
            if statement.target:
                writes.add(statement.target.upper())
        elif isinstance(statement, PerformStatement):
            if statement.varying_clause and "variable" in statement.varying_clause:
                writes.add(statement.varying_clause["variable"].upper())

        # Recurse into all nested statement containers
        for s in self._nested_statements(statement):
            writes.update(self._collect_variable_writes(s))

        return writes

    def _extract_data_items(self, program: CobolProgram) -> list[DataItemInfo]:
        """Extract data item info from DATA division."""
        data_div = program.get_division("DATA")
        if data_div is None:
            return []

        items: list[DataItemInfo] = []
        self._walk_data_items(data_div, items)
        return items

    def _walk_data_items(self, node: ASTNode, items: list[DataItemInfo]) -> None:
        """Recursively walk AST collecting data items."""
        if isinstance(node, CobolDataItem):
            if not node.is_filler and node.name:
                items.append(self._data_item_to_info(node))

        if hasattr(node, "children"):
            for child in node.children:
                self._walk_data_items(child, items)

    def _data_item_to_info(self, item: CobolDataItem) -> DataItemInfo:
        """Convert a CobolDataItem to DataItemInfo."""
        info = DataItemInfo(
            name=item.name,
            level=item.level,
            usage=item.usage or "DISPLAY",
            initial_value=(
                str(item.value_clause) if item.value_clause is not None else None
            ),
        )

        pic = item.picture_clause
        if pic is not None:
            info.picture_pattern = pic.pattern
            info.size = pic.size
            info.is_signed = pic.is_signed
            info.decimal_digits = pic.decimal_digits or 0
            info.integer_digits = pic.integer_digits or 0
            # Determine if numeric from PIC character types (not repeat
            # counts).  Strip '(n)' groups first so PIC A(9) doesn't
            # false-positive on the '9' inside the parentheses.
            if pic.pattern:
                stripped_pat = re.sub(r"\(\d+\)", "", pic.pattern.upper())
                info.is_numeric = (
                    any(c in stripped_pat for c in ("9", "V", "P"))
                    and "X" not in stripped_pat
                    and "A" not in stripped_pat
                )

        return info
