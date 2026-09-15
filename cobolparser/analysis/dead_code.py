"""
Dead code detection for COBOL programs.

Analyzes the PROCEDURE DIVISION to find paragraphs and sections that are
never referenced by any control flow statement (PERFORM, GO TO, ALTER,
SORT/MERGE procedures) and never implicitly reached by falling through from
the paragraph immediately preceding them in source order. The first
procedure in the PROCEDURE DIVISION is always considered referenced as the
program entry point.
"""

from dataclasses import dataclass, field
from typing import Any

from ..models.ast_base import SourceLocation
from ..models.program import CobolDivision, CobolParagraph, CobolProgram, CobolSection
from ..models.statements.call import EntryStatement
from ..models.statements.control import (
    GoStatement,
    PerformStatement,
    StopStatement,
)
from ..models.statements.misc import (
    AlterStatement,
    ExitStatement,
    GobackStatement,
    MergeStatement,
    SortStatement,
    XmlJsonStatement,
)


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
    - Implicit fall-through: control runs off the end of the procedure
      immediately preceding it in source order -- the default shape of a
      straight-line COBOL program with no explicit control transfer
      between paragraphs.

    Fall-through only propagates out of a procedure that control can
    *arrive at and keep running from*: the entry point, an ENTRY paragraph,
    a GO TO / ALTER target, or something already reached by fall-through.
    A ``PERFORM`` target is deliberately not such a procedure -- a PERFORM
    returns to its caller at the end of its range instead of running on
    into the next paragraph -- and neither is a SORT/MERGE INPUT or OUTPUT
    procedure. Crediting those with fall-through is what made the analyzer
    report *no* dead code at all for the most common COBOL program shape,
    a ``MAIN`` paragraph of ``PERFORM``s followed by the paragraphs it
    performs: every unreferenced paragraph after the first performed one
    was kept alive by a fall-through edge that cannot happen at runtime.

    The first procedure in the PROCEDURE DIVISION is always considered
    referenced as the program entry point. A paragraph that contains an
    ENTRY statement is also always considered referenced, since it is a
    legitimate alternate external entry point (callable via CALL
    'entry-name') even when nothing internally PERFORMs or GOes to it.

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
        # Maps paragraph name -> every parent section name it appears under
        # (a name may repeat across sections). Only the first same-named
        # paragraph is registered as a procedure, but every section holding
        # one is recorded here so a bare ``PERFORM 100-DO`` (or a qualified
        # ``PERFORM 100-DO OF SEC-A``, whose qualifier the parser keeps only
        # as metadata) keeps each of those sections alive rather than just
        # the last one seen.
        self._paragraph_sections: dict[str, set[str]] = {}
        # Closing paragraphs of every PERFORM/SORT/MERGE ... THRU range. A
        # GO TO landing on one of these (the ``GO TO 1000-EXIT`` idiom
        # inside ``PERFORM 1000-INIT THRU 1000-EXIT``) ends the range and
        # *returns* to the performer -- it does not run on into whatever
        # follows the range in source order.
        self._range_ends: set[str] = set()
        # Maps paragraph name -> its CobolParagraph node, for fall-through
        # termination checks. Sections have no entry here -- a bare SECTION
        # header has no statements of its own and never blocks fall-through.
        self._paragraph_nodes: dict[str, CobolParagraph] = {}
        # Procedures control can arrive at and then *keep running from*, so
        # that reaching the end of one falls into the next in source order.
        # A strict subset of ``_referenced_names``: see the class docstring
        # for why a PERFORM/SORT-procedure target is excluded.
        self._fallthrough_sources: set[str] = set()
        # Sections declared between DECLARATIVES. and END DECLARATIVES.
        # (and their paragraphs): USE procedures the runtime invokes, so
        # they are live without any PERFORM naming them, and they are never
        # the program's entry point.
        self._declarative_procs: set[str] = set()

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
        self._paragraph_sections = {}
        self._range_ends = set()
        self._paragraph_nodes = {}
        self._fallthrough_sources = set()
        self._declarative_procs = set()

        proc_division = ast.procedure_division
        if proc_division is None:
            return DeadCodeReport()

        self._collect_procedures(proc_division)
        self._collect_declaratives(proc_division)
        self._collect_references(ast)

        # Entry point is always referenced. Marked before the fall-through
        # pass (which propagates left-to-right and needs to know the first
        # procedure is reachable) rather than after. Declaratives come
        # first in source order but are never the entry point: control
        # enters at the first procedure after END DECLARATIVES.
        entry = next(
            (p for p in self._ordered_procedures if p not in self._declarative_procs),
            None,
        )
        if entry is not None:
            self._referenced_names.add(entry)
            self._fallthrough_sources.add(entry)
        self._referenced_names.update(self._declarative_procs)

        self._collect_fallthrough_refs()

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
        """Collect all paragraph and section names from the PROCEDURE DIVISION.

        COBOL allows paragraphs before the first SECTION header, so sections
        and top-level paragraphs are interleaved by source line to preserve
        physical order (entry-point detection and fall-through edges both
        depend on ``_ordered_procedures`` matching source order).
        """
        top_level_items: list[Any] = sorted(
            [*proc_division._sections.values(), *proc_division.paragraphs],
            key=lambda item: item.location.line,
        )

        for item in top_level_items:
            if isinstance(item, CobolSection):
                name = item.section_name
                if name:
                    upper_name = name.upper()
                    if upper_name not in self._procedure_names:
                        self._procedure_names[upper_name] = (
                            "SECTION",
                            item.location,
                        )
                        self._ordered_procedures.append(upper_name)
                    # Always ensure a paragraph bucket exists for this section
                    # name, even when the SECTION registration above was
                    # skipped due to a name collision, so the paragraph loop
                    # below can unconditionally .append() into it.
                    self._section_paragraphs.setdefault(upper_name, [])
                # Collect paragraphs within the section
                for para in item.paragraphs:
                    pname = para.paragraph_name
                    if pname and self._is_valid_procedure_name(pname):
                        upper_pname = pname.upper()
                        if upper_pname not in self._procedure_names:
                            self._procedure_names[upper_pname] = (
                                "PARAGRAPH",
                                para.location,
                            )
                            self._ordered_procedures.append(upper_pname)
                            self._paragraph_nodes[upper_pname] = para
                        if name:
                            sec_upper = name.upper()
                            self._section_paragraphs[sec_upper].append(upper_pname)
                            self._paragraph_sections.setdefault(upper_pname, set()).add(
                                sec_upper
                            )
            else:
                # Top-level paragraph (not inside a section)
                pname = item.paragraph_name
                if pname and self._is_valid_procedure_name(pname):
                    upper_pname = pname.upper()
                    if upper_pname not in self._procedure_names:
                        self._procedure_names[upper_pname] = (
                            "PARAGRAPH",
                            item.location,
                        )
                        self._ordered_procedures.append(upper_pname)
                        self._paragraph_nodes[upper_pname] = item

    def _collect_declaratives(self, proc_division: CobolDivision) -> None:
        """Record every DECLARATIVES section and its paragraphs."""
        for item in proc_division._sections.values():
            if not isinstance(item, CobolSection) or not item.is_declarative:
                continue
            if item.section_name:
                self._declarative_procs.add(item.section_name.upper())
            for para in item.paragraphs:
                if para.paragraph_name:
                    self._declarative_procs.add(para.paragraph_name.upper())

    def _propagate_section_references(self) -> None:
        """Propagate section references in both directions.

        - Section → paragraphs: when a section is referenced, all its child
          paragraphs are reachable (PERFORM section-name executes all of them).
        - Paragraph → section: when any paragraph inside a section is referenced,
          the section itself is also considered referenced so it is not falsely
          reported as dead code.

        Order matters here and is not interchangeable. Downward propagation
        must run first, using only the references already collected by
        ``_collect_references``/entry-point-marking/``_collect_fallthrough_refs``
        -- i.e. sections that are *directly* referenced (PERFORM/GO TO the
        section name itself, or falling into it). If upward ran first, a
        section would gain "referenced" status merely because one of its own
        paragraphs happens to be a PERFORM target, and the downward pass would
        then broadcast that to every *sibling* paragraph too -- reviving
        genuinely dead paragraphs that are neither PERFORMed/GONE TO nor
        reachable by fall-through (a plain ``PERFORM child-para`` does not
        execute the rest of its section, unlike ``PERFORM section-name``).
        Running downward first means it only ever sees pre-existing direct
        section references, so a paragraph-only reference can still protect
        its *own* section from being reported dead (via the upward pass
        below) without resurrecting unrelated siblings.
        """
        # Downward: a *directly* referenced section makes all its paragraphs
        # referenced too (must run before the upward pass -- see docstring).
        for sec_name, para_names in self._section_paragraphs.items():
            if sec_name in self._referenced_names:
                for pname in para_names:
                    self._referenced_names.add(pname)

        # Upward: paragraph referenced -> parent section is referenced.
        # Every section holding a paragraph of that name, not just the last
        # one registered: a bare ``PERFORM 100-DO`` in a program with a
        # ``100-DO`` in both ``SEC-A`` and ``SEC-B`` cannot be told apart by
        # name alone, and reporting one of those sections dead would be
        # reporting live code -- the over-approximation goes the safe way.
        for para_name, sec_names in self._paragraph_sections.items():
            if para_name in self._referenced_names:
                self._referenced_names.update(sec_names)

    def _collect_references(self, ast: CobolProgram) -> None:
        """Collect all procedure name references from control flow statements."""
        all_statements = ast.get_all_statements()

        # THRU range ends must be known before any GO TO is classified, so a
        # jump onto one is not mistaken for a jump that keeps running.
        for stmt in all_statements:
            self._collect_range_end(stmt)

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
            elif isinstance(stmt, EntryStatement):
                self._collect_entry_refs(stmt)
            elif isinstance(stmt, XmlJsonStatement):
                self._collect_xml_refs(stmt)
            elif getattr(stmt, "node_type", None) == "EXEC_CICS":
                self._collect_cics_handle_refs(stmt)

    def _collect_xml_refs(self, stmt: XmlJsonStatement) -> None:
        """``XML PARSE ... PROCESSING PROCEDURE p [THRU q]`` runs p (through
        q) once per XML event -- an out-of-line PERFORM the parser invokes."""
        if stmt.processing_procedure:
            self._add_ref(stmt.processing_procedure)
        if stmt.processing_procedure_thru:
            self._add_ref(stmt.processing_procedure_thru)
            self._mark_thru_range(
                stmt.processing_procedure, stmt.processing_procedure_thru
            )

    def _collect_cics_handle_refs(self, stmt: Any) -> None:
        """``EXEC CICS HANDLE AID|CONDITION|ABEND`` names paragraphs CICS
        branches to (``PF3(9000-EXIT)``, ``NOTFND(9000-NOT-FOUND)``,
        ``LABEL(9100-ABEND)``): each is a GO TO the runtime performs."""
        if (getattr(stmt, "cics_command", "") or "").upper() != "HANDLE":
            return
        for value in (getattr(stmt, "options", None) or {}).values():
            if value and self._is_valid_procedure_name(value):
                self._add_goto_ref(value)

    def _collect_range_end(self, stmt: Any) -> None:
        """Record the closing paragraph of a PERFORM/SORT/MERGE THRU range.

        Not built on ``program_flow.edges.EdgeCollector.range_members``/
        ``thru_target`` (checked before writing this rather than assumed
        different): this analyzer only ever needs a set membership test
        ("is paragraph X some range's end"), a three-attribute read
        (``thru_paragraph``/``input_procedure_thru``/``output_procedure_
        thru``) already this cheap. Building the full CFG `EdgeCollector`
        constructs (node classification, cycle detection, every edge of
        every kind) to answer that one question would be a much heavier
        dependency for the same result -- unlike ``recursion_risk.py``,
        which genuinely needs the CFG's cycle data and correctly reuses
        ``ProgramFlowAnalyzer`` for it.
        """
        ends: list[str | None] = []
        if isinstance(stmt, PerformStatement):
            ends.append(stmt.thru_paragraph)
        elif isinstance(stmt, SortStatement):
            ends.extend([stmt.input_procedure_thru, stmt.output_procedure_thru])
        elif isinstance(stmt, MergeStatement):
            ends.append(stmt.output_procedure_thru)
        for end in ends:
            if end:
                self._range_ends.add(end.upper())

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
            self._add_goto_ref(target)

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
        """Collect references from an ALTER statement.

        Only the modified GO TO's new target (``to_paragraph``) is an
        incoming jump. The ALTER's subject (``from_paragraph``) is the
        paragraph whose internal GO TO gets rewritten -- being named there
        is not itself a reference to that paragraph.
        """
        for alteration in stmt.alterations:
            self._add_goto_ref(alteration["to_paragraph"])

    def _collect_entry_refs(self, stmt: EntryStatement) -> None:
        """Mark the paragraph containing an ENTRY statement as referenced.

        The ENTRY statement's literal name is not a procedure name -- it is
        the paragraph physically holding the ENTRY statement that is the
        alternate entry point, so that paragraph (and, per
        ``_propagate_section_references``, its enclosing section) must never
        be reported as dead code. A blank/whitespace-only ENTRY literal isn't
        a real alternate entry point (matches the same filter
        ``program_flow/scanner.py``'s ``collect_entry_points`` applies), so
        such a statement doesn't mask a truly-dead paragraph.
        """
        if not stmt.entry_name or not stmt.entry_name.strip("'\"").strip():
            return
        para_name = stmt.section_name
        if para_name:
            self._add_jump_ref(para_name)

    def _collect_fallthrough_refs(self) -> None:
        """Mark a procedure as referenced when the one immediately before it
        in physical source order is itself reachable and does not terminate.

        In COBOL, when a paragraph finishes without a hard terminator or an
        unconditional GO TO, execution falls through to the next procedure
        in source order -- the default shape of a straight-line program with
        no explicit control transfer. A SECTION header has no statements of
        its own and never blocks fall-through into its (or the next
        procedure's) content.

        Gated on ``current`` being a *fall-through source* -- a procedure
        control can arrive at and keep running from (the entry point, an
        ENTRY paragraph, a GO TO/ALTER target, or something this same
        left-to-right pass already reached by fall-through). Not on plain
        ``_referenced_names`` membership: that also holds PERFORM and
        SORT/MERGE procedure targets, whose range *returns* to the caller
        at its end rather than running on, so crediting them here invents a
        runtime edge that does not exist and hides every dead paragraph
        that happens to sit after a performed one. Must run after the entry
        point is seeded, and a single forward pass suffices since
        fall-through only ever propagates in source order.
        """
        for i in range(len(self._ordered_procedures) - 1):
            current = self._ordered_procedures[i]
            next_proc = self._ordered_procedures[i + 1]
            if current in self._fallthrough_sources and not self._terminates(current):
                self._add_ref(next_proc)
                self._fallthrough_sources.add(next_proc)

    def _terminates(self, name: str) -> bool:
        """Check whether procedure *name* unconditionally transfers control
        away, so that execution never falls through to the next procedure.

        Any top-level statement counts, not just the last: once an
        unconditional terminator is reached, it always fires, so whatever is
        physically written after it in the same paragraph is itself
        unreachable and irrelevant to whether the paragraph falls through --
        checking only ``para.statements[-1]`` would miss a mid-paragraph
        terminator followed by dead trailing statements. Nested statements
        (inside an IF/EVALUATE arm) are deliberately excluded: a terminator
        there only fires conditionally, so it must not suppress
        fall-through whenever that branch isn't the one actually taken.
        """
        para = self._paragraph_nodes.get(name)
        if para is None:
            # Sections (and paragraphs with no statements) have no control
            # flow of their own -- execution always falls into whatever
            # comes next.
            return False
        return any(self._is_terminator(stmt) for stmt in para.statements)

    @staticmethod
    def _is_terminator(stmt: Any) -> bool:
        """Check whether *stmt* unconditionally transfers control away when
        reached: STOP RUN (not STOP 'literal', which merely halts pending
        operator action), GOBACK, EXIT PROGRAM, or a bare (non-DEPENDING)
        GO TO.
        """
        if isinstance(stmt, GobackStatement):
            return True
        if isinstance(stmt, StopStatement):
            return stmt.stop_type == "RUN"
        if isinstance(stmt, ExitStatement):
            return stmt.exit_type == "PROGRAM"
        if isinstance(stmt, GoStatement):
            return bool(stmt.target_paragraph) and not stmt.depending_on_variable
        return False

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

    def _add_jump_ref(self, name: str | None) -> None:
        """Add a procedure reached by a transfer that does *not* return.

        A GO TO (or an ALTERed one), and an ENTRY paragraph reached by an
        external ``CALL``, all land in the procedure and carry on from
        there -- so reaching its end falls into the next procedure in
        source order. That makes the target a fall-through source as well
        as a reference, unlike a PERFORM target.
        """
        if name:
            self._add_ref(name)
            self._fallthrough_sources.add(name.upper())

    def _add_goto_ref(self, name: str | None) -> None:
        """Add a GO TO (or ALTER ... TO PROCEED TO) target.

        A jump lands in the target and carries on -- unless the target is
        the closing paragraph of a ``PERFORM ... THRU`` range, where the
        ``GO TO 1000-EXIT`` idiom ends the range early and control returns
        to the performer. Such a target is referenced (never dead) but is
        *not* a fall-through source: crediting it with one invented a
        runtime edge out of the range that hid every dead paragraph after
        ``1000-EXIT``. A GO TO onto a *middle* paragraph of a range still
        falls on to the range end, which then returns just the same; that
        residual over-approximation is deliberate -- a range end can also
        be reached by a path that never PERFORMed it, and reporting live
        code dead is the worse error.
        """
        if not name:
            return
        if name.upper() in self._range_ends:
            self._add_ref(name)
        else:
            self._add_jump_ref(name)

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
