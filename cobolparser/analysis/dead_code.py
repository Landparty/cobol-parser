"""
Dead code detection for COBOL programs.

Analyzes the PROCEDURE DIVISION to find paragraphs and sections that are
never referenced by any control flow statement (PERFORM, GO TO, ALTER,
SORT/MERGE procedures). The first procedure in the PROCEDURE DIVISION is
always considered referenced as the program entry point.
"""

from dataclasses import dataclass, field
from typing import Any

from ..models.ast_base import SourceLocation
from ..models.program import CobolDivision, CobolProgram
from ..models.statements.control import (
    GoStatement,
    PerformStatement,
)
from ..models.statements.misc import AlterStatement, MergeStatement, SortStatement


@dataclass
class DeadCodeItem:
    """A paragraph or section identified as dead (unreferenced) code."""

    name: str
    procedure_type: str  # "PARAGRAPH" or "SECTION"
    location: SourceLocation

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": self.procedure_type,
            "location": self.location.to_dict(),
        }


@dataclass
class DeadCodeReport:
    """Report of dead code analysis results."""

    dead_items: list[DeadCodeItem] = field(default_factory=list)
    total_procedures: int = 0
    referenced_procedures: int = 0

    @property
    def dead_count(self) -> int:
        return len(self.dead_items)

    @property
    def has_dead_code(self) -> bool:
        return len(self.dead_items) > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "dead_code": [item.to_dict() for item in self.dead_items],
            "summary": {
                "total_procedures": self.total_procedures,
                "referenced_procedures": self.referenced_procedures,
                "dead_procedures": self.dead_count,
            },
        }


class DeadCodeAnalyzer:
    """Analyzer for detecting dead (unreferenced) code in COBOL programs.

    Scans the PROCEDURE DIVISION for paragraphs and sections that are never
    referenced by control flow statements. A procedure is considered
    "referenced" if it appears as a target in any of:

    - PERFORM target / PERFORM target THRU target
    - GO TO target / GO TO targets DEPENDING ON
    - SORT/MERGE INPUT/OUTPUT PROCEDURE
    - ALTER ... TO PROCEED TO ...

    The first procedure in the PROCEDURE DIVISION is always considered
    referenced as the program entry point.

    Example:
        ```python
        from cobolparser import parse_cobol
        from cobolparser.analysis.dead_code import DeadCodeAnalyzer

        result = parse_cobol(source)
        analyzer = DeadCodeAnalyzer()
        report = analyzer.analyze(result.ast)

        for item in report.dead_items:
            print(f"Dead {item.procedure_type}: {item.name} at line {item.location.line}")
        ```
    """

    def __init__(self) -> None:
        self._procedure_names: dict[str, tuple[str, SourceLocation]] = {}
        self._referenced_names: set[str] = set()
        self._ordered_procedures: list[str] = []
        # Maps section name -> list of paragraph names within that section
        self._section_paragraphs: dict[str, list[str]] = {}
        # Maps paragraph name -> parent section name (if any)
        self._paragraph_section: dict[str, str] = {}

    def analyze(self, ast: CobolProgram) -> DeadCodeReport:
        """Analyze a COBOL program for dead code.

        Args:
            ast: The parsed COBOL program AST.

        Returns:
            A DeadCodeReport with all unreferenced procedures.
        """
        self._procedure_names = {}
        self._referenced_names = set()
        self._ordered_procedures = []
        self._section_paragraphs = {}
        self._paragraph_section = {}

        proc_division = ast.procedure_division
        if proc_division is None:
            return DeadCodeReport()

        self._collect_procedures(proc_division)
        self._collect_references(ast)

        # Entry point is always referenced
        if self._ordered_procedures:
            self._referenced_names.add(self._ordered_procedures[0])

        # When a section is referenced, all its paragraphs are too
        self._propagate_section_references()

        # Build report
        report = DeadCodeReport()
        report.total_procedures = len(self._procedure_names)
        report.referenced_procedures = len(
            self._referenced_names & set(self._procedure_names.keys())
        )

        for name in self._ordered_procedures:
            if name not in self._referenced_names:
                proc_type, location = self._procedure_names[name]
                report.dead_items.append(DeadCodeItem(name, proc_type, location))

        return report

    def _collect_procedures(self, proc_division: CobolDivision) -> None:
        """Collect all paragraph and section names from the PROCEDURE DIVISION."""
        # Collect sections and their paragraphs
        for section in proc_division._sections.values():
            name = section.section_name
            if name:
                upper_name = name.upper()
                self._procedure_names[upper_name] = ("SECTION", section.location)
                self._ordered_procedures.append(upper_name)
                self._section_paragraphs[upper_name] = []
            # Collect paragraphs within sections
            for para in section.paragraphs:
                pname = para.paragraph_name
                if pname and self._is_valid_procedure_name(pname):
                    upper_pname = pname.upper()
                    self._procedure_names[upper_pname] = ("PARAGRAPH", para.location)
                    self._ordered_procedures.append(upper_pname)
                    if name:
                        sec_upper = name.upper()
                        self._section_paragraphs[sec_upper].append(upper_pname)
                        self._paragraph_section[upper_pname] = sec_upper

        # Collect top-level paragraphs (not inside sections)
        for para in proc_division.paragraphs:
            pname = para.paragraph_name
            if pname and self._is_valid_procedure_name(pname):
                upper_pname = pname.upper()
                if upper_pname not in self._procedure_names:
                    self._procedure_names[upper_pname] = ("PARAGRAPH", para.location)
                    self._ordered_procedures.append(upper_pname)

    def _propagate_section_references(self) -> None:
        """Propagate section references in both directions.

        - Section → paragraphs: when a section is referenced, all its child
          paragraphs are reachable (PERFORM section-name executes all of them).
        - Paragraph → section: when any paragraph inside a section is referenced,
          the section itself is also considered referenced so it is not falsely
          reported as dead code.
        """
        # Upward: paragraph referenced -> parent section is referenced
        for para_name, sec_name in self._paragraph_section.items():
            if para_name in self._referenced_names:
                self._referenced_names.add(sec_name)

        # Downward: section referenced -> all child paragraphs are referenced
        for sec_name, para_names in self._section_paragraphs.items():
            if sec_name in self._referenced_names:
                for pname in para_names:
                    self._referenced_names.add(pname)

    def _collect_references(self, ast: CobolProgram) -> None:
        """Collect all procedure name references from control flow statements."""
        all_statements = ast.get_all_statements()

        for stmt in all_statements:
            if isinstance(stmt, PerformStatement):
                self._collect_perform_refs(stmt)
            elif isinstance(stmt, GoStatement):
                self._collect_goto_refs(stmt)
            elif isinstance(stmt, SortStatement):
                self._collect_sort_refs(stmt)
            elif isinstance(stmt, MergeStatement):
                self._collect_merge_refs(stmt)
            elif isinstance(stmt, AlterStatement):
                self._collect_alter_refs(stmt)

    def _collect_perform_refs(self, stmt: PerformStatement) -> None:
        """Collect references from a PERFORM statement."""
        if stmt.target_paragraph:
            self._add_ref(stmt.target_paragraph)
        if stmt.thru_paragraph:
            self._add_ref(stmt.thru_paragraph)
            # Mark all procedures between target and thru as referenced
            self._mark_thru_range(stmt.target_paragraph, stmt.thru_paragraph)

    def _collect_goto_refs(self, stmt: GoStatement) -> None:
        """Collect references from a GO TO statement."""
        # target_paragraphs already holds every target (including all
        # computed GO TO ... DEPENDING ON targets); reconstructing them by
        # filtering operands would collapse a target that happens to share
        # its name with the DEPENDING ON variable.
        for target in stmt.target_paragraphs:
            self._add_ref(target)

    def _collect_sort_refs(self, stmt: SortStatement) -> None:
        """Collect references from a SORT statement's procedures."""
        if stmt.input_procedure:
            self._add_ref(stmt.input_procedure)
        if stmt.input_procedure_thru:
            self._add_ref(stmt.input_procedure_thru)
            self._mark_thru_range(stmt.input_procedure, stmt.input_procedure_thru)
        if stmt.output_procedure:
            self._add_ref(stmt.output_procedure)
        if stmt.output_procedure_thru:
            self._add_ref(stmt.output_procedure_thru)
            self._mark_thru_range(stmt.output_procedure, stmt.output_procedure_thru)

    def _collect_merge_refs(self, stmt: MergeStatement) -> None:
        """Collect references from a MERGE statement's procedures."""
        if stmt.output_procedure:
            self._add_ref(stmt.output_procedure)
        if stmt.output_procedure_thru:
            self._add_ref(stmt.output_procedure_thru)
            self._mark_thru_range(stmt.output_procedure, stmt.output_procedure_thru)

    def _collect_alter_refs(self, stmt: AlterStatement) -> None:
        """Collect references from an ALTER statement."""
        for alteration in stmt.alterations:
            self._add_ref(alteration["from_paragraph"])
            self._add_ref(alteration["to_paragraph"])

    @staticmethod
    def _is_valid_procedure_name(name: str) -> bool:
        """Check whether *name* looks like a real COBOL procedure name.

        The parser may generate synthetic paragraphs (e.g. a lone period ``"."``)
        that should be excluded from the analysis.
        """
        return bool(name) and name not in (".",)

    def _add_ref(self, name: str | None) -> None:
        """Add a procedure name as referenced."""
        if name:
            self._referenced_names.add(name.upper())

    def _mark_thru_range(self, start: str | None, end: str | None) -> None:
        """Mark all procedures between start and end (inclusive) as referenced.

        Uses index-based lookup so that a missing or inverted range does not
        accidentally mark procedures all the way to the end of the list.
        """
        if not start or not end:
            return
        upper_start = start.upper()
        upper_end = end.upper()
        try:
            start_index = self._ordered_procedures.index(upper_start)
            end_index = self._ordered_procedures.index(upper_end)
        except ValueError:
            return

        if start_index > end_index:
            return

        for name in self._ordered_procedures[start_index : end_index + 1]:
            self._referenced_names.add(name)
