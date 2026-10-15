"""
Dead code detection for COBOL programs.

Analyzes the PROCEDURE DIVISION to find paragraphs and sections control can
never reach: never referenced by a control flow statement (PERFORM, GO TO,
ALTER, SORT/MERGE procedures) that itself runs, and never implicitly reached
by falling through from the paragraph immediately preceding them in source
order. The first procedure in the PROCEDURE DIVISION is always considered
reached as the program entry point. A reference written in dead code does
not count, so dead code is followed transitively (issue #384).
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
from ._procedures import (
    ProcedureIndex,
    enclosing_section,
    qualify,
    statement_qualifier,
)


@dataclass
class DeadCodeItem:
    """A paragraph or section identified as dead (unreachable) code."""

    name: str
    procedure_type: str  # "PARAGRAPH" or "SECTION"
    location: SourceLocation
    #: ``"X1 OF S2"`` when another paragraph shares this one's name, so the
    #: two can be told apart; ``None`` otherwise.
    qualified_name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "name": self.name,
            "type": self.procedure_type,
            "location": self.location.to_dict(),
        }
        if self.qualified_name:
            result["qualified_name"] = self.qualified_name
        return result


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
    """Analyzer for detecting dead (unreachable) code in COBOL programs.

    Scans the PROCEDURE DIVISION for paragraphs and sections that control
    can never reach. A procedure is considered "referenced" if it appears as
    a target in any of the following, written in a procedure that is itself
    referenced (a PERFORM in a dead paragraph never runs, so the paragraphs
    only it performs are dead too -- issue #384):

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
        # Last paragraph of every section a PERFORM/SORT/MERGE/XML PARSE runs
        # (``PERFORM 1000-INIT`` with no THRU, or a range ending on a
        # section) -> that section. The SECTION form of the ``GO TO
        # 1000-EXIT`` idiom: a jump onto it ends the performed section and
        # returns, the same as a THRU range end -- unless the section is
        # itself entered by fall-through or a GO TO, where the exit runs on.
        self._section_exits: dict[str, str] = {}
        # Section exits some GO TO / ALTER lands on, held back from being
        # fall-through sources until ``_collect_fallthrough_refs`` knows
        # whether their section is itself entered and keeps running.
        self._section_exit_jumps: set[str] = set()
        # Sections some transfer that does not return lands in from
        # *outside* the section (a GO TO / ALTER / CICS HANDLE written in
        # another section, or an ENTRY): on that path the section is not
        # running as a PERFORM, so its exit paragraph runs on.
        self._sections_entered_by_jump: set[str] = set()
        # Maps paragraph name -> its CobolParagraph node, for fall-through
        # termination checks. A section has an entry only when sentences sit
        # between its header and its first paragraph (the parser's unnamed
        # paragraph); a bare SECTION header never blocks fall-through.
        self._paragraph_nodes: dict[str, CobolParagraph] = {}
        # ``_terminates`` per procedure: asked again on every worklist round.
        self._terminates_cache: dict[str, bool] = {}
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
        # Sentences written before the first paragraph header of the
        # PROCEDURE DIVISION: the parser keeps them as an unnamed paragraph.
        # They are what runs first, so a STOP RUN / GOBACK among them means
        # the first *named* procedure is not entered by fall-through.
        self._leading_body: CobolParagraph | None = None
        self._index = ProcedureIndex([])

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
        self._section_exits = {}
        self._section_exit_jumps = set()
        self._sections_entered_by_jump = set()
        self._paragraph_nodes = {}
        self._terminates_cache = {}
        self._fallthrough_sources = set()
        self._declarative_procs = set()

        proc_division = ast.procedure_division
        if proc_division is None:
            return DeadCodeReport()

        self._collect_procedures(proc_division)
        self._collect_declaratives(proc_division)
        statements = self._own_statements(ast)
        by_owner: dict[str | None, list[Any]] = {}
        for stmt in statements:
            owner = None if self._always_counts(stmt) else self._owner(stmt)
            by_owner.setdefault(owner, []).append(stmt)

        # THRU range ends and performed-section exits come from *every*
        # statement, dead ones included, before any GO TO is classified, so a
        # jump onto one is not mistaken for a jump that keeps running. Taking
        # them from every statement rather than only reachable ones keeps the
        # pass below monotone: admitting more statements only ever adds
        # references, never retracts a fall-through source.
        for stmt in statements:
            self._collect_range_end(stmt)
        self._seed_roots()

        # Dead means *unreachable*, not merely unreferenced (issue #384): a
        # PERFORM written in a dead paragraph never runs, so it must not keep
        # its targets alive. A worklist from the roots -- the entry point,
        # the declaratives, the leading body, ENTRY paragraphs and CICS
        # HANDLE labels -- admits a procedure's statements only once the
        # procedure itself is reached.
        admitted: set[str | None] = set()
        pending: list[str | None] = [None]
        while pending:
            admitted.update(pending)
            for owner in pending:
                self._collect_references(by_owner.get(owner, []))
            self._collect_fallthrough_refs()
            # When a section is referenced, all its paragraphs are too
            self._propagate_section_downward()
            pending = [
                key
                for key in self._ordered_procedures
                if key in self._referenced_names and key not in admitted
            ]
        # Only once every round is done: a section kept alive merely by one
        # of its paragraphs must not look *directly* referenced to a later
        # downward pass (see ``_propagate_section_references``).
        self._propagate_section_upward()

        # Build report
        report = DeadCodeReport()
        report.total_procedures = len(self._procedure_names)
        report.referenced_procedures = len(
            self._referenced_names & set(self._procedure_names.keys())
        )

        for key in self._ordered_procedures:
            if key not in self._referenced_names:
                proc = self._index.by_key[key]
                report.dead_items.append(
                    DeadCodeItem(
                        proc.name,
                        proc.procedure_type,
                        proc.location,
                        proc.qualified_name,
                    )
                )

        return report

    def _seed_roots(self) -> None:
        """Mark the entry point and the declaratives as referenced.

        The entry point is marked before the fall-through pass (which
        propagates left-to-right and needs to know the first procedure is
        reachable) rather than after. Declaratives come first in source
        order but are never the entry point: control enters at the first
        procedure after END DECLARATIVES.
        """
        entry = next(
            (p for p in self._ordered_procedures if p not in self._declarative_procs),
            None,
        )
        leading_stops = self._leading_body is not None and any(
            self._is_terminator(stmt) for stmt in self._leading_body.statements
        )
        if entry is not None and not leading_stops:
            self._referenced_names.add(entry)
            self._fallthrough_sources.add(entry)
        self._referenced_names.update(self._declarative_procs)

    @staticmethod
    def _own_statements(ast: CobolProgram) -> list[Any]:
        """*ast*'s own statements, without its contained programs'.

        ``get_all_statements()`` also returns every contained program's, and
        a nested program's ``PERFORM 100-DO`` names *its own* ``100-DO`` --
        procedure names are local to a program unit -- so crediting it here
        kept a same-named dead paragraph of the container alive.
        """
        all_statements = ast.get_all_statements()
        if ast.contained_programs:
            inner = {
                id(stmt)
                for contained in ast.contained_programs
                for stmt in contained.get_all_statements()
            }
            all_statements = [s for s in all_statements if id(s) not in inner]
        return all_statements

    def _owner(self, stmt: Any) -> str | None:
        """The key of the procedure *stmt* is written in.

        ``None`` when it sits before the first paragraph header (the leading
        body, which always runs first) or its paragraph cannot be found --
        such a statement always counts, so a gap in the parent chain can
        only keep code alive, never report live code dead.
        """
        node = getattr(stmt, "parent", None)
        while node is not None and not isinstance(node, CobolParagraph):
            node = getattr(node, "parent", None)
        if node is None:
            return None
        section = node.parent if isinstance(node.parent, CobolSection) else None
        sec = section.section_name.upper() if section and section.section_name else None
        if not node.paragraph_name or not self._is_valid_procedure_name(
            node.paragraph_name
        ):
            # A section's sentences before its first paragraph header.
            return sec if sec in self._procedure_names else None
        name = node.paragraph_name.upper()
        for key in (qualify(name, sec) if sec else None, name):
            if key and key in self._procedure_names:
                return key
        return None

    @staticmethod
    def _always_counts(stmt: Any) -> bool:
        """An ENTRY (an external CALL lands on its paragraph) or a CICS
        HANDLE (its labels are handler entry points): roots of reachability
        wherever they are written."""
        return isinstance(stmt, EntryStatement) or (
            getattr(stmt, "node_type", None) == "EXEC_CICS"
            and (getattr(stmt, "cics_command", "") or "").upper() == "HANDLE"
        )

    def _collect_procedures(self, proc_division: CobolDivision) -> None:
        """Collect every paragraph and section of the PROCEDURE DIVISION.

        Keyed by :class:`~._procedures.ProcedureIndex` identity: the bare
        name, or ``"X1 OF S2"`` for a paragraph whose name another section
        also uses (issue #258), in physical source order (entry-point
        detection and fall-through both depend on ``_ordered_procedures``
        matching it).
        """
        self._index = ProcedureIndex.build(proc_division)
        top_level: list[Any] = sorted(
            [*proc_division._sections.values(), *proc_division.paragraphs],
            key=lambda item: item.location.line,
        )
        self._leading_body = None
        if (
            top_level
            and isinstance(top_level[0], CobolParagraph)
            and not top_level[0].paragraph_name
        ):
            self._leading_body = top_level[0]

        for entry in self._index.entries:
            self._procedure_names[entry.key] = (entry.procedure_type, entry.location)
            self._ordered_procedures.append(entry.key)
            if entry.procedure_type == "SECTION":
                self._section_paragraphs.setdefault(entry.key, [])
                # Sentences between the SECTION header and its first
                # paragraph header: the section's own body, whose
                # terminators decide whether the section falls through
                # (see ``_terminates``).
                section = entry.node
                assert isinstance(section, CobolSection)
                for para in section.paragraphs:
                    if not para.paragraph_name:
                        self._paragraph_nodes.setdefault(entry.key, para)
                        break
            else:
                assert isinstance(entry.node, CobolParagraph)
                self._paragraph_nodes[entry.key] = entry.node
                if entry.section is not None:
                    self._section_paragraphs.setdefault(entry.section, []).append(
                        entry.key
                    )
                    self._paragraph_sections.setdefault(entry.key, set()).add(
                        entry.section
                    )

    def _collect_declaratives(self, proc_division: CobolDivision) -> None:
        """Record every DECLARATIVES section and its paragraphs."""
        declarative = {
            e.key
            for e in self._index.entries
            if isinstance(e.node, CobolSection) and e.node.is_declarative
        }
        self._declarative_procs.update(
            e.key
            for e in self._index.entries
            if e.key in declarative or e.section in declarative
        )

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
        self._propagate_section_downward()
        self._propagate_section_upward()

    def _propagate_section_downward(self) -> None:
        """A *directly* referenced section makes its paragraphs referenced
        (must run before the upward pass -- see
        ``_propagate_section_references``).

        Entering a section runs its paragraphs in order, so a paragraph is
        reached only while the one before it (in the same section) was
        reached and does not terminate: a paragraph after one ending in
        STOP RUN / GOBACK / an unconditional GO TO is not executed just
        because its section is PERFORMed or fallen into. Marking every
        paragraph of a referenced section hid exactly that dead code.
        """
        for sec_name, para_names in self._section_paragraphs.items():
            if sec_name in self._referenced_names:
                # The section's own leading sentences run first.
                live = not self._terminates(sec_name)
                for pname in para_names:
                    reached = live or pname in self._fallthrough_sources
                    if reached:
                        self._referenced_names.add(pname)
                    live = reached and not self._terminates(pname)

    def _propagate_section_upward(self) -> None:
        """A referenced paragraph keeps its parent section(s) referenced.

        Every section holding a paragraph of that name, not just the last
        one registered: a bare ``PERFORM 100-DO`` in a program with a
        ``100-DO`` in both ``SEC-A`` and ``SEC-B`` cannot be told apart by
        name alone, and reporting one of those sections dead would be
        reporting live code -- the over-approximation goes the safe way.
        """
        for para_name, sec_names in self._paragraph_sections.items():
            if para_name in self._referenced_names:
                self._referenced_names.update(sec_names)

    def _collect_references(self, all_statements: list[Any]) -> None:
        """Collect all procedure name references from control flow statements.

        THRU range ends must already be known (``_collect_range_end``), so a
        GO TO onto one is not mistaken for a jump that keeps running.
        """
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
        self._collect_range_refs(
            stmt, stmt.processing_procedure, stmt.processing_procedure_thru
        )

    def _collect_cics_handle_refs(self, stmt: Any) -> None:
        """``EXEC CICS HANDLE AID|CONDITION|ABEND`` names paragraphs CICS
        branches to (``PF3(9000-EXIT)``, ``NOTFND(9000-NOT-FOUND)``,
        ``LABEL(9100-ABEND)``): each is a GO TO the runtime performs."""
        if (getattr(stmt, "cics_command", "") or "").upper() != "HANDLE":
            return
        for value in (getattr(stmt, "options", None) or {}).values():
            if value and self._is_valid_procedure_name(value):
                for key in self._keys(stmt, value):
                    self._add_goto_ref(key)

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
        # (start, thru, start qualifier, thru qualifier) per procedure phrase.
        phrases: list[tuple[str | None, str | None, str | None, str | None]] = []
        if isinstance(stmt, PerformStatement):
            phrases.append(
                (
                    stmt.target_paragraph,
                    stmt.thru_paragraph,
                    "target_qualifier",
                    "thru_qualifier",
                )
            )
        elif isinstance(stmt, SortStatement):
            phrases.append(
                (stmt.input_procedure, stmt.input_procedure_thru, None, None)
            )
            phrases.append(
                (stmt.output_procedure, stmt.output_procedure_thru, None, None)
            )
        elif isinstance(stmt, MergeStatement):
            phrases.append(
                (stmt.output_procedure, stmt.output_procedure_thru, None, None)
            )
        elif isinstance(stmt, XmlJsonStatement):
            phrases.append(
                (
                    stmt.processing_procedure,
                    stmt.processing_procedure_thru,
                    None,
                    None,
                )
            )
        for start, thru, start_q, thru_q in phrases:
            ends = (
                self._keys(stmt, thru, thru_q)
                if thru
                else self._keys(stmt, start, start_q)
            )
            for end in ends:
                if thru:
                    self._range_ends.add(end)
                # A range ending on a section (``PERFORM 1000-INIT``, or
                # ``... THRU 2000-SEC``) returns after that section's last
                # paragraph.
                paras = self._section_paragraphs.get(end)
                if paras:
                    self._section_exits[paras[-1]] = end

    def _collect_perform_refs(self, stmt: PerformStatement) -> None:
        """Collect references from a PERFORM statement."""
        self._collect_range_refs(
            stmt,
            stmt.target_paragraph,
            stmt.thru_paragraph,
            "target_qualifier",
            "thru_qualifier",
        )

    def _collect_goto_refs(self, stmt: GoStatement) -> None:
        """Collect references from a GO TO statement."""
        # target_paragraphs already holds every target (including all
        # computed GO TO ... DEPENDING ON targets); reconstructing them by
        # filtering operands would collapse a target that happens to share
        # its name with the DEPENDING ON variable.
        for target in stmt.target_paragraphs:
            qualifier_key = (
                "target_qualifier" if not stmt.depending_on_variable else None
            )
            for key in self._keys(stmt, target, qualifier_key):
                self._add_goto_ref(key, enclosing_section(stmt))

    def _collect_sort_refs(self, stmt: SortStatement) -> None:
        """Collect references from a SORT statement's procedures."""
        self._collect_range_refs(stmt, stmt.input_procedure, stmt.input_procedure_thru)
        self._collect_range_refs(
            stmt, stmt.output_procedure, stmt.output_procedure_thru
        )

    def _collect_merge_refs(self, stmt: MergeStatement) -> None:
        """Collect references from a MERGE statement's procedures."""
        self._collect_range_refs(
            stmt, stmt.output_procedure, stmt.output_procedure_thru
        )

    def _collect_alter_refs(self, stmt: AlterStatement) -> None:
        """Collect references from an ALTER statement.

        Only the modified GO TO's new target (``to_paragraph``) is an
        incoming jump. The ALTER's subject (``from_paragraph``) is the
        paragraph whose internal GO TO gets rewritten -- being named there
        is not itself a reference to that paragraph.
        """
        for alteration in stmt.alterations:
            for key in self._keys(stmt, alteration["to_paragraph"]):
                self._add_goto_ref(key)

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
        for key in self._keys(stmt, stmt.section_name):
            self._add_jump_ref(key)
            # Called from outside the program: never a PERFORM of its section.
            self._note_jump_into(key, None)

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
            if (
                current in self._fallthrough_sources
                or current in self._sections_entered_by_jump
            ):
                # A performed section that is *also* fallen into, gone to, or
                # jumped into from another section runs on past its exit
                # paragraph on that path, so a GO TO onto the exit does too
                # (issue #312's caveat).
                paras = self._section_paragraphs.get(current)
                if paras and paras[-1] in self._section_exit_jumps:
                    self._fallthrough_sources.add(paras[-1])
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
        cached = self._terminates_cache.get(name)
        if cached is not None:
            return cached
        result = self._terminates_uncached(name)
        self._terminates_cache[name] = result
        return result

    def _terminates_uncached(self, name: str) -> bool:
        para = self._paragraph_nodes.get(name)
        if para is None:
            # A bare section header (and a paragraph with no statements) has
            # no control flow of its own -- execution always falls into
            # whatever comes next. A section with sentences before its first
            # paragraph is keyed here to that unnamed body.
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

    def _keys(
        self, stmt: Any, name: str | None, qualifier_key: str | None = None
    ) -> list[str]:
        """The procedure key(s) *name*, referenced from *stmt*, means.

        The ``OF``/``IN`` qualifier when the parser recorded one, else the
        same-named paragraph in *stmt*'s own section, else the name when it
        is unique; an ambiguous reference keeps every candidate alive.
        """
        qualifier = statement_qualifier(stmt, qualifier_key) if qualifier_key else None
        return self._index.resolve(name, qualifier, enclosing_section(stmt))

    def _collect_range_refs(
        self,
        stmt: Any,
        start: str | None,
        end: str | None,
        start_qualifier: str | None = None,
        end_qualifier: str | None = None,
    ) -> None:
        """References from a ``p [THRU q]`` phrase: both ends and, for a
        range, every procedure between them."""
        starts = self._keys(stmt, start, start_qualifier)
        ends = self._keys(stmt, end, end_qualifier)
        for key in [*starts, *ends]:
            self._add_ref(key)
        for s_key in starts:
            for e_key in ends:
                self._mark_thru_range(s_key, e_key)

    def _add_ref(self, key: str | None) -> None:
        """Add a procedure key as referenced."""
        if key:
            self._referenced_names.add(key)

    def _add_jump_ref(self, key: str | None) -> None:
        """Add a procedure reached by a transfer that does *not* return.

        A GO TO (or an ALTERed one), and an ENTRY paragraph reached by an
        external ``CALL``, all land in the procedure and carry on from
        there -- so reaching its end falls into the next procedure in
        source order. That makes the target a fall-through source as well
        as a reference, unlike a PERFORM target.
        """
        if key:
            self._add_ref(key)
            self._fallthrough_sources.add(key)

    def _note_jump_into(self, key: str, from_section: str | None) -> None:
        """Record the section(s) of jump target *key* as entered by a jump
        when the jump comes from outside them (*from_section* ``None`` means
        from anywhere: an ALTER, a CICS HANDLE, an ENTRY)."""
        if key in self._section_paragraphs:
            targets = {key}
        else:
            targets = self._paragraph_sections.get(key, set())
        self._sections_entered_by_jump.update(t for t in targets if t != from_section)

    def _add_goto_ref(self, key: str | None, from_section: str | None = None) -> None:
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

        Every caller but a plain GO TO passes no *from_section*: an ALTERed
        GO TO or a CICS HANDLE branch can fire from any section.
        """
        if not key:
            return
        self._note_jump_into(key, from_section)
        if key in self._range_ends:
            self._add_ref(key)
        elif key in self._section_exits:
            # Settled in ``_collect_fallthrough_refs``, once it is known
            # whether the section itself is entered and keeps running.
            self._add_ref(key)
            self._section_exit_jumps.add(key)
        else:
            self._add_jump_ref(key)

    def _mark_thru_range(self, start: str | None, end: str | None) -> None:
        """Mark all procedures between keys start and end (inclusive) as
        referenced.

        Uses index-based lookup so that a missing or inverted range does not
        accidentally mark procedures all the way to the end of the list.
        """
        if not start or not end:
            return
        try:
            start_index = self._ordered_procedures.index(start)
            end_index = self._ordered_procedures.index(end)
        except ValueError:
            return

        if start_index > end_index:
            return

        for name in self._ordered_procedures[start_index : end_index + 1]:
            self._referenced_names.add(name)
