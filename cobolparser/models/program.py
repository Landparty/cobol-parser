"""
COBOL program structure nodes including programs, divisions, and sections.

This module implements the high-level structural elements of COBOL programs
including program nodes, division nodes, and section nodes with full
JSON serialization support.
"""

import fnmatch
import json
import re
import warnings
from typing import TYPE_CHECKING, Any, Optional, Union, cast

from ..plugins import SerializationConfig
from .ast_base import ASTNode, SourceLocation, ValidationResult

if TYPE_CHECKING:
    from ..analysis.dead_code import DeadCodeReport
    from .data_items import CobolDataItem
    from .statements import CobolStatement

# Type alias for procedures (Paragraph or Section)
CobolProcedure = Union["CobolParagraph", "CobolSection"]


class CobolSection(ASTNode):
    """AST node for COBOL sections within divisions."""

    def __init__(self, section_name: str, location: SourceLocation):
        super().__init__("Section", location)
        self._own_section_name = (
            section_name  # Use _own_ prefix to avoid property conflict
        )
        self.paragraphs: list[CobolParagraph] = []
        self.data_items: list[CobolDataItem] = []

    @property
    def is_declarative(self) -> bool:
        """True for a section declared between ``DECLARATIVES.`` and ``END
        DECLARATIVES.`` -- a USE procedure the runtime invokes on an I/O
        error or before a report group is printed, never reached by the
        program's own PERFORM / GO TO / fall-through control flow."""
        return bool(self.get_metadata("declarative"))

    def add_paragraph(self, paragraph: "CobolParagraph") -> None:
        """Add a paragraph to this section."""
        self.add_child(paragraph)
        self.paragraphs.append(paragraph)

    def add_data_item(self, data_item: "CobolDataItem") -> None:
        """Add a data item to this section."""
        self.add_child(data_item)
        self.data_items.append(data_item)

    def get_paragraph_by_name(self, name: str) -> Optional["CobolParagraph"]:
        """Find a paragraph by name in this section."""
        for paragraph in self.paragraphs:
            if (
                isinstance(paragraph, CobolParagraph)
                and paragraph.paragraph_name == name
            ):
                return paragraph
        return None

    def to_dict(self) -> dict[str, Any]:
        """Convert section to dictionary representation."""
        result = {
            "node_type": self.node_type,
            "section_name": self.section_name,  # Use property
            "location": self.location.to_dict(),
            "paragraphs": [p.to_dict() for p in self.paragraphs],
            "data_items": [d.to_dict() for d in self.data_items],
            "metadata": self._metadata or {},
        }
        # Level-66 RENAMES items are attached as plain children (they are not
        # CobolDataItem instances) and were historically dropped at the JSON
        # boundary.
        renames_items = [
            child.to_dict()
            for child in self.children
            if getattr(child, "node_type", None) == "RenamesItem"
        ]
        if renames_items:
            result["renames_items"] = renames_items
        return result


class CobolDivision(ASTNode):
    """AST node for COBOL divisions (IDENTIFICATION, DATA, PROCEDURE, etc.)."""

    def __init__(self, division_name: str, location: SourceLocation):
        super().__init__("Division", location)
        self._own_division_name = (
            division_name  # Use _own_ prefix to avoid property conflict
        )
        self._sections: dict[str, CobolSection] = {}
        self.paragraphs: list[CobolParagraph] = []
        # Set own division context
        self.set_division_context(division_name, None)

    @property
    def sections(self) -> list[Union[CobolSection, "CobolParagraph"]]:
        """List-like access for sections (tests iterate over 'sections').

        For PROCEDURE divisions without explicit sections, returns paragraphs
        wrapped as section-like entities since they serve the same purpose.
        """
        if self.division_name == "PROCEDURE" and not self._sections:
            # Return paragraphs as sections for PROCEDURE division without sections
            return cast(list[Union[CobolSection, "CobolParagraph"]], self.paragraphs)
        return list(self._sections.values())

    @property
    def division_name(self) -> str:
        """Returns the name of the division."""
        return self._own_division_name

    def add_section(self, section: CobolSection) -> None:
        """Add a section to this division."""
        self.add_child(section)
        self._sections[section.section_name or ""] = section

    def add_paragraph(self, paragraph: "CobolParagraph") -> None:
        """Add a paragraph directly to this division (procedure division)."""
        self.add_child(paragraph)
        self.paragraphs.append(paragraph)

    def add_data_item(self, data_item: "CobolDataItem") -> None:
        """Add a data item to this division (creates a working storage section if needed)."""
        # For DATA divisions, add to working storage section
        if not self.has_section("WORKING-STORAGE"):
            ws_section = CobolSection("WORKING-STORAGE", SourceLocation(1, 1))
            self.add_section(ws_section)

        ws_section_node = self.get_section_by_name("WORKING-STORAGE")
        if isinstance(ws_section_node, CobolSection):
            ws_section_node.add_data_item(data_item)

    def add_statement(self, statement: "CobolStatement") -> None:
        """Add a statement to this division (procedure division)."""
        # For PROCEDURE divisions, add to default paragraph if none exists
        if not self.paragraphs:
            default_paragraph = CobolParagraph("MAIN", SourceLocation(1, 1))
            self.add_paragraph(default_paragraph)

        # Add to the last paragraph
        if self.paragraphs:
            self.paragraphs[-1].add_statement(statement)

    def add_procedure(self, procedure: Union["CobolParagraph", "CobolSection"]) -> None:
        """Add a procedure (paragraph or section) to this division."""
        if isinstance(procedure, CobolParagraph):
            self.add_paragraph(procedure)
        elif isinstance(procedure, CobolSection):
            self.add_section(procedure)

    def get_section_by_name(
        self, name: str
    ) -> Union[CobolSection, "CobolParagraph"] | None:
        """Get a section by name.

        In PROCEDURE division, also searches paragraphs since they are treated
        as section-like entities for navigation purposes.
        """
        # First check actual sections
        section = self._sections.get(name)
        if section:
            return section

        # For PROCEDURE division, also check paragraphs
        if self.division_name == "PROCEDURE":
            for para in self.paragraphs:
                if isinstance(para, CobolParagraph) and para.paragraph_name == name:
                    return para

        return None

    def has_section(self, name: str) -> bool:
        """Check if division has a specific section."""
        return name in self._sections

    def to_dict(self) -> dict[str, Any]:
        """Convert division to dictionary representation."""
        return {
            "node_type": self.node_type,
            "division_name": self.division_name,
            "location": self.location.to_dict(),
            "sections": {
                name: section.to_dict() for name, section in self._sections.items()
            },
            "paragraphs": [p.to_dict() for p in self.paragraphs],
            "metadata": self._metadata or {},
        }


class CobolParagraph(ASTNode):
    """AST node for COBOL paragraphs within sections or divisions."""

    def __init__(self, paragraph_name: str, location: SourceLocation):
        super().__init__("Paragraph", location)
        self.paragraph_name = paragraph_name
        self.statements: list[CobolStatement] = []
        # For paragraphs in procedure division, section_name is the same as paragraph_name
        self._own_section_name = paragraph_name

    @property
    def section_name(self) -> str | None:
        """Get the section name (for paragraphs, this is the paragraph name)."""
        return self._own_section_name

    def add_statement(self, statement: "CobolStatement") -> None:
        """Add a statement to this paragraph."""
        self.add_child(statement)
        self.statements.append(statement)

    def to_dict(self) -> dict[str, Any]:
        """Convert paragraph to dictionary representation."""
        return {
            "node_type": self.node_type,
            "paragraph_name": self.paragraph_name,
            "location": self.location.to_dict(),
            "statements": [stmt.to_dict() for stmt in self.statements],
            "metadata": self._metadata or {},
        }


def _strip_locations(node: Any) -> None:
    """Drop every nested ``location`` key in place.

    Division, section, paragraph and statement nodes each serialize their own
    ``location``; ``SerializationConfig(include_source_locations=False)`` has
    to reach all of them, not only the program's.
    """
    if isinstance(node, dict):
        node.pop("location", None)
        for value in node.values():
            _strip_locations(value)
    elif isinstance(node, list):
        for value in node:
            _strip_locations(value)


#: A quoted COBOL literal (a doubled quote inside is part of it).
_QUOTED_LITERAL_RE = re.compile(r"'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"")


def _exec_kind(stmt: Any) -> str | None:
    """``"SQL"`` / ``"CICS"`` / ``"IMS"`` for an EXEC block, else None.

    The statement parser builds ``ExecCicsStatement`` / ``ExecImsStatement``
    with ``statement_type`` ``"EXEC CICS"`` / ``"EXEC IMS"`` (blank), the
    dialect module's hand-built nodes use ``"EXEC-CICS"`` / ``"EXEC-IMS"``
    (hyphen), and the typed EXEC SQL subclasses (``FetchStatement``, ...)
    carry the SQL verb (``"FETCH"``) -- so a plain ``statement_type ==
    "EXEC-CICS"`` test matched none of the statements a real parse builds.
    """
    from .sql_statements import ExecSQLStatement

    if isinstance(stmt, ExecSQLStatement):
        return "SQL"
    kind = str(getattr(stmt, "statement_type", "") or "").upper().replace(" ", "-")
    if kind in ("EXEC-SQL", "EXEC-CICS", "EXEC-IMS"):
        return kind[5:]
    return None


class CobolProgram(ASTNode):
    """AST node representing a complete COBOL program."""

    def __init__(self, program_name: str, location: SourceLocation):
        super().__init__("Program", location)
        self.program_name = program_name
        # Internal mapping of division name -> division object
        self._divisions: dict[str, CobolDivision] = {}
        # Additional program units from the same compilation unit (stacked or
        # nested programs delimited by END PROGRAM). Historically everything
        # after the first program was silently dropped.
        self.contained_programs: list[CobolProgram] = []
        #: The program unit this one is *nested* in (its ``END PROGRAM``
        #: comes before the enclosing one's), or None for an outermost
        #: program and for a *stacked* one (a separate compilation unit
        #: written after the previous one's ``END PROGRAM``). Every unit
        #: hangs off the first program's ``contained_programs`` whatever its
        #: nesting, so the tree does not say this; the parser does (#532).
        #: ``add_contained_program`` defaults it to the containing unit.
        self.enclosing_program: CobolProgram | None = None
        # from_json only: the serialized ``enclosing_program`` name ("" for
        # a stacked unit) until _restore_nesting() resolves it.
        self._enclosing_name: str | None = None
        #: What kind of compilation unit this is: ``"PROGRAM"`` (a
        #: PROGRAM-ID, the default) or, for IBM object-oriented COBOL, one
        #: of ``"CLASS"`` (CLASS-ID), ``"FACTORY"``, ``"OBJECT"`` and
        #: ``"METHOD"`` (METHOD-ID). A class unit contains its factory and
        #: object units, which contain their method units, all through
        #: ``contained_programs`` -- so ``program_units()`` enumerates every
        #: method like it enumerates every nested program.
        self.unit_kind: str = "PROGRAM"
        # The SerializationConfig the building parser was constructed with;
        # to_dict()/to_json() fall back to it when called without one.
        self.serialization_config: SerializationConfig | None = None
        # Cached statistics
        self._statistics: dict[str, Any] | None = None
        # S1 optimization: cache get_all_statements() result. Multiple
        # extractors (call/copy/sql/file_io) call this method 1-2 times each
        # — ~7 traversals per program. Memoizing converts that into one
        # traversal + 6 O(1) returns. Invalidated by add_division().
        self._cached_all_statements: list[CobolStatement] | None = None
        #: ``(first, last)`` source lines of COPY statements the parser
        #: could not expand and left out. Not serialized; a rule that would
        #: read a missing declaration as an error (lint's ``undefined-name``)
        #: stays quiet when it is non-empty.
        self.omitted_copy_lines: tuple[tuple[int, int], ...] = ()

    @property
    def divisions(self) -> list[CobolDivision]:
        """Get all divisions as a list."""
        return list(self._divisions.values())

    @property
    def identification_division(self) -> CobolDivision | None:
        """Get the IDENTIFICATION DIVISION."""
        return self.get_division("IDENTIFICATION")

    @property
    def environment_division(self) -> CobolDivision | None:
        """Get the ENVIRONMENT DIVISION."""
        return self.get_division("ENVIRONMENT")

    @property
    def data_division(self) -> CobolDivision | None:
        """Get the DATA DIVISION."""
        return self.get_division("DATA")

    @property
    def procedure_division(self) -> CobolDivision | None:
        """Get the PROCEDURE DIVISION."""
        return self.get_division("PROCEDURE")

    def add_division(self, division: CobolDivision) -> None:
        """Add a division to the program (keeps both dict and list representations)."""
        self.add_child(division)
        self._divisions[division.division_name] = division
        # Invalidate S1 statement cache — a new division may add statements.
        self._cached_all_statements = None

    @property
    def program_attributes(self) -> list[str]:
        """The PROGRAM-ID attributes (``INITIAL``, ``COMMON``, ``RECURSIVE``)
        this unit declared, in source order; empty when it declared none."""
        division = self.identification_division
        attrs = division.get_metadata("program_attributes") if division else None
        return list(attrs or [])

    @property
    def is_recursive(self) -> bool:
        """True when the unit declared ``PROGRAM-ID. name IS RECURSIVE``:
        it may legally be re-entered while still active."""
        return "RECURSIVE" in self.program_attributes

    @property
    def is_common(self) -> bool:
        """True when the unit declared ``PROGRAM-ID. name IS COMMON``: the
        programs nested in its own container may CALL it, not only that
        container."""
        return "COMMON" in self.program_attributes

    @property
    def is_nested(self) -> bool:
        """True for a program nested in another (not outermost, not
        stacked): only programs of its own compilation unit can CALL it."""
        return self.enclosing_program is not None

    @property
    def nesting_depth(self) -> int:
        """0 for an outermost or stacked unit, 1 for one nested in it, ..."""
        depth = 0
        unit = self.enclosing_program
        while unit is not None and depth < 10_000:
            depth += 1
            unit = unit.enclosing_program
        return depth

    def nested_program_called(self, name: str) -> "CobolProgram | None":
        """The nested program a ``CALL 'name'`` written in this unit reaches
        by COBOL scope, or None when the CALL goes to a separately compiled
        (external) program of that name (#532).

        A program nested directly in this unit is visible; so is a
        ``COMMON`` program nested directly in any unit enclosing this one
        (not one of its own enclosing units), and a nested unit's own name
        (a RECURSIVE program calling itself).
        """
        wanted = name.strip().strip("\"'").strip().upper()
        if not wanted:
            return None
        if self.is_nested and (self.program_name or "").upper() == wanted:
            return self
        root: CobolProgram = self
        while isinstance(getattr(root, "parent", None), CobolProgram):
            root = root.parent  # type: ignore[assignment]
        units = [
            u
            for u in root.program_units()
            if u.unit_kind == "PROGRAM" and (u.program_name or "").upper() == wanted
        ]
        for unit in units:
            if unit.enclosing_program is self:
                return unit
        ancestors: list[CobolProgram] = []
        unit_up = self.enclosing_program
        while unit_up is not None and len(ancestors) < 10_000:
            ancestors.append(unit_up)
            unit_up = unit_up.enclosing_program
        for ancestor in ancestors:
            for unit in units:
                if (
                    unit.enclosing_program is ancestor
                    and unit.is_common
                    and unit is not self
                    and unit not in ancestors
                ):
                    return unit
        return None

    def program_units(self) -> list["CobolProgram"]:
        """This program and every program contained in it, outermost first.

        A source file holding several ``PROGRAM-ID``s parses into one outer
        program with the rest hanging off ``contained_programs``. Every
        analyzer here is *program*-scoped by definition -- a paragraph in the
        contained program is not reachable from the outer one, and grading it
        against the outer one's references would call live code dead -- so
        analyzing a multi-program file means running the analyzer once per
        unit. This is that list, in the order the units appear in the source.
        """
        units: list[CobolProgram] = [self]
        for contained in self.contained_programs:
            units.extend(contained.program_units())
        return units

    def find_program_unit(self, name: str) -> "CobolProgram | None":
        """The unit whose PROGRAM-ID is *name*, case-insensitively."""
        wanted = name.strip().upper()
        for unit in self.program_units():
            if (unit.program_name or "").upper() == wanted:
                return unit
        return None

    def add_contained_program(self, program: "CobolProgram") -> None:
        """Attach an additional program unit from the same compilation unit."""
        self.add_child(program)
        self.contained_programs.append(program)
        program.enclosing_program = self
        # A contained program brings its own statements.
        self._cached_all_statements = None

    def get_division(self, name: str) -> CobolDivision | None:
        """Get a division by name."""
        return self._divisions.get(name)

    def has_division(self, name: str) -> bool:
        """Check if program has a specific division."""
        return name in self._divisions

    def repository(self) -> dict[str, Any] | None:
        """This unit's CONFIGURATION SECTION ``REPOSITORY`` paragraph, or None.

        ``{"functions": [{"name", "external_name"}], "intrinsic": [...],
        "all_intrinsic": bool, "classes": [{"name", "external_name"}]}``;
        ``functions`` are the user-defined functions (FUNCTION-ID units)
        the unit declares it invokes.
        """
        environment = self.get_division("ENVIRONMENT")
        if environment is None:
            return None
        section = environment._sections.get("CONFIGURATION")
        repository = section.get_metadata("repository") if section else None
        return repository if isinstance(repository, dict) else None

    def user_function_names(self) -> list[str]:
        """Names of the user-defined functions the REPOSITORY declares."""
        repository = self.repository() or {}
        return [
            str(entry["name"]).upper()
            for entry in repository.get("functions") or []
            if isinstance(entry, dict) and entry.get("name")
        ]

    def get_data_items(self) -> list["CobolDataItem"]:
        """Get all data items defined in the program."""
        data_items = []

        # Look in DATA division sections
        data_division = self.get_division("DATA")
        if data_division:
            for section in data_division._sections.values():
                data_items.extend(section.data_items)
                # Also look for nested data items
                for item in section.data_items:
                    data_items.extend(item.get_all_children())

        return data_items

    def find_data_items(
        self, name_pattern: str | None = None, level: int | None = None
    ) -> list["CobolDataItem"]:
        """Find data items by name pattern and/or level number."""

        all_items = self.get_data_items()
        results = []

        for item in all_items:
            # Apply name pattern filter
            if name_pattern is not None:
                if not fnmatch.fnmatch(item.name, name_pattern):
                    continue

            # Apply level filter
            if level is not None:
                if item.level != level:
                    continue

            results.append(item)

        return results

    def find_procedures(
        self, proc_type: str | None = None, name_pattern: str | None = None
    ) -> list["CobolProcedure"]:
        """Find procedures by type (PARAGRAPH/SECTION) and/or name pattern."""

        all_procedures = self.get_procedures()
        results = []

        for proc in all_procedures:
            # Apply type filter
            if proc_type is not None:
                if proc_type == "PARAGRAPH" and not isinstance(proc, CobolParagraph):
                    continue
                elif proc_type == "SECTION" and not isinstance(proc, CobolSection):
                    continue

            # Apply name pattern filter
            if name_pattern is not None:
                proc_name = getattr(proc, "paragraph_name", None) or getattr(
                    proc, "section_name", None
                )
                if proc_name and not fnmatch.fnmatch(proc_name, name_pattern):
                    continue

            results.append(proc)

        return results

    def get_all_statements(self) -> list["CobolStatement"]:
        """Get all statements in the program (typically in PROCEDURE division).

        Recursively traverses nested structures to extract ALL statements.
        Handles both AST children and specific statement attributes that
        might hold nested statements (e.g. invalid_key_clause, on_exception).

        Result is cached on the program instance (invalidated by
        add_division). The AST is immutable post-parse in the production
        path, so the cached list is safe to share across all callers.
        """
        if self._cached_all_statements is not None:
            return self._cached_all_statements

        from .statements import NESTED_BODY_ATTRS, CobolStatement

        statements = []
        visited = set()

        def traverse(node: Any) -> None:
            # Handle list of nodes
            if isinstance(node, list):
                for item in node:
                    traverse(item)
                return

            # Must be an ASTNode/valid object to continue (check for node_type)
            if not hasattr(node, "node_type"):
                return

            # Cycle detection
            if id(node) in visited:
                return
            visited.add(id(node))

            # Collect statement
            if isinstance(node, CobolStatement):
                statements.append(node)

            # 1. Recurse children (primary mechanism)
            if hasattr(node, "children"):
                for child in node.children:
                    traverse(child)

            # 2. Recurse paragraph statements (new architecture)
            # Paragraphs store statements in a separate list
            if hasattr(node, "statements") and node.node_type == "Paragraph":
                for stmt in node.statements:
                    traverse(stmt)

            # 3. Recurse every nested-body attribute (handle orphans/non-children):
            # the one canonical list, next to the statement node classes.
            for attr in NESTED_BODY_ATTRS:
                if hasattr(node, attr):
                    val = getattr(node, attr)
                    if val:
                        traverse(val)

        # Start traversal from PROCEDURE division
        proc_division = self.get_division("PROCEDURE")
        if proc_division:
            traverse(proc_division)

        # Include statements from additional program units in this
        # compilation unit (stacked/nested programs).
        for contained in self.contained_programs:
            statements.extend(contained.get_all_statements())

        self._cached_all_statements = statements
        return statements

    def find_statements(self, stmt_type: str | None = None) -> list["CobolStatement"]:
        """Find statements by type."""
        all_statements = self.get_all_statements()

        if stmt_type is None:
            return all_statements

        return [stmt for stmt in all_statements if stmt.statement_type == stmt_type]

    def find_statements_using_variable(
        self, variable_name: str
    ) -> list["CobolStatement"]:
        """Find statements that use a specific variable.

        An operand uses *variable_name* when it holds that name as a whole
        COBOL word (case-insensitively), outside any quoted literal -- so
        ``WS-A`` matches ``WS-A``, ``WS-A(IX)`` and ``WS-A OF GRP``, but not
        ``WS-AMOUNT``, ``TOTAL-WS-A`` or ``'WS-A'``. A plain substring test
        used to report every statement touching a longer name that merely
        contained this one.
        """
        name = variable_name.strip()
        if not name:
            return []
        pattern = re.compile(
            rf"(?<![A-Za-z0-9_-]){re.escape(name)}(?![A-Za-z0-9_-])", re.IGNORECASE
        )
        using_variable = []

        for stmt in self.get_all_statements():
            for operand in stmt.operands:
                if pattern.search(_QUOTED_LITERAL_RE.sub(" ", operand)):
                    using_variable.append(stmt)
                    break

        return using_variable

    def find_dead_code(self) -> "DeadCodeReport":
        """Find unreferenced paragraphs and sections (dead code).

        Returns:
            A DeadCodeReport listing all unreferenced procedures.
        """
        from ..analysis.dead_code import DeadCodeAnalyzer

        analyzer = DeadCodeAnalyzer()
        return analyzer.analyze(self)

    def has_sql(self) -> bool:
        """Check if program uses EXEC SQL statements."""
        return bool(self.get_sql_statements())

    def has_cics(self) -> bool:
        """Check if program uses EXEC CICS statements."""
        return bool(self.get_cics_statements())

    def has_ims(self) -> bool:
        """Check if program uses EXEC IMS statements or declares ENTRY 'DLITCBL'."""
        return bool(self.get_ims_statements()) or self.is_ims_dlitcbl_program()

    def get_sql_statements(self) -> list["CobolStatement"]:
        """Get all EXEC SQL statements in the program.

        Includes the typed EXEC SQL subclasses (``FETCH``, ``DECLARE CURSOR``,
        ``COMMIT``/``ROLLBACK``, dynamic SQL), whose ``statement_type`` names
        the SQL verb rather than ``"EXEC-SQL"``.
        """
        return [s for s in self.get_all_statements() if _exec_kind(s) == "SQL"]

    def get_cics_statements(self) -> list["CobolStatement"]:
        """Get all EXEC CICS statements in the program."""
        return [s for s in self.get_all_statements() if _exec_kind(s) == "CICS"]

    def get_ims_statements(self) -> list["CobolStatement"]:
        """Get all EXEC IMS / EXEC DLI statements in the program."""
        return [s for s in self.get_all_statements() if _exec_kind(s) == "IMS"]

    def uses_ims_interface(self) -> bool:
        """Check if program uses IMS language interface (CBLTDLI, AIBTDLI, CEETDLI)."""
        all_statements = self.get_all_statements()
        ims_interfaces = {"CBLTDLI", "AIBTDLI", "CEETDLI"}

        for stmt in all_statements:
            if stmt.statement_type == "CALL":
                # Check if any operand contains an IMS interface call
                for operand in stmt.operands:
                    if any(
                        interface in operand.upper() for interface in ims_interfaces
                    ):
                        return True
        return False

    def get_ims_interface_calls(self) -> list["CobolStatement"]:
        """Get all CALL statements to IMS language interfaces."""
        all_statements = self.get_all_statements()
        ims_interfaces = {"CBLTDLI", "AIBTDLI", "CEETDLI"}
        ims_calls = []

        for stmt in all_statements:
            if stmt.statement_type == "CALL":
                for operand in stmt.operands:
                    if any(
                        interface in operand.upper() for interface in ims_interfaces
                    ):
                        ims_calls.append(stmt)
                        break

        return ims_calls

    def get_entry_statements(self) -> list["CobolStatement"]:
        """Return all ENTRY statements in the program."""
        from .statements import EntryStatement

        return [s for s in self.get_all_statements() if isinstance(s, EntryStatement)]

    def is_ims_dlitcbl_program(self) -> bool:
        """True if program declares ENTRY 'DLITCBL' (IMS DL/I batch entry point)."""
        return any(
            (s.entry_name or "").upper() == "DLITCBL"  # type: ignore[attr-defined]
            for s in self.get_entry_statements()
        )

    def get_le_callable_service_calls(self) -> list["CobolStatement"]:
        """Get all CALL statements targeting IBM Language Environment services.

        Detects any CALL whose static program name starts with ``CEE`` (the
        IBM LE service naming prefix).  For dynamic calls, any entry in
        ``CallStatement.possible_values`` (populated by
        :class:`~cobolparser.analysis.value_tracker.DynamicCallAnalyzer`)
        that is CEE-prefixed also qualifies.
        """

        def _is_cee(name: object) -> bool:
            return isinstance(name, str) and name.strip("\"'").upper().startswith("CEE")

        all_statements = self.get_all_statements()
        le_calls = []
        for stmt in all_statements:
            if stmt.statement_type != "CALL":
                continue
            called = getattr(stmt, "called_program", None)
            if _is_cee(called):
                le_calls.append(stmt)
                continue
            if getattr(stmt, "is_dynamic", False):
                possible = getattr(stmt, "possible_values", []) or []
                if any(_is_cee(v) for v in possible):
                    le_calls.append(stmt)
        return le_calls

    def uses_language_environment(self) -> bool:
        """Return True if the program calls any IBM Language Environment service."""
        return bool(self.get_le_callable_service_calls())

    def get_intrinsic_function_usages(self) -> list[str]:
        """Return a list of intrinsic function names referenced by the program.

        Each ``FUNCTION <name>`` reference in the program's statements, in
        the order it appears (duplicates included). Delegates to
        :class:`~cobolparser.analysis.language_env_analyzer.LanguageEnvironmentAnalyzer`,
        the one detector: this method used to run its own looser regex,
        which took ``FUNCTION`` inside a data name (``DLI-FUNCTION OF REC``
        -> ``OF``) or inside a quoted literal (``DISPLAY 'NO FUNCTION
        HERE'`` -> ``HERE``) for an intrinsic-function call.
        """
        from ..analysis.language_env_analyzer import LanguageEnvironmentAnalyzer

        report = LanguageEnvironmentAnalyzer().analyze(self)
        return [usage.function_name for usage in report.intrinsic_usages]

    def uses_intrinsic_functions(self) -> bool:
        """Return True if the program uses any COBOL intrinsic functions."""
        return bool(self.get_intrinsic_function_usages())

    def get_procedures(self) -> list["CobolProcedure"]:
        """Get all procedure paragraphs/sections in the program."""
        procedures: list[CobolProcedure] = []

        # Look in PROCEDURE division
        proc_division = self.get_division("PROCEDURE")
        if proc_division:
            # Add sections as procedures
            for section in proc_division._sections.values():
                procedures.append(section)

            # Add paragraphs as procedures
            procedures.extend(proc_division.paragraphs)

            # Also look in sections for paragraphs
            for section in proc_division._sections.values():
                procedures.extend(section.paragraphs)

        return procedures

    def get_nodes_in_division(
        self, division_name: str, node_type: str | None = None
    ) -> list[ASTNode]:
        """Get all nodes belonging to a specific division.

        Args:
            division_name: Name of the division (e.g., 'PROCEDURE', 'DATA')
            node_type: Optional filter by node type (e.g., 'Statement')

        Returns:
            List of nodes in the specified division
        """
        results = []
        for node in self.traverse_depth_first():
            if node.division_name == division_name:
                if node_type is None or node.node_type == node_type:
                    results.append(node)
        return results

    def get_statements_in_division(self, division_name: str) -> list["CobolStatement"]:
        """Get all statements in a specific division.

        Args:
            division_name: Name of the division (e.g., 'PROCEDURE')

        Returns:
            List of statements in the specified division
        """
        from .statements import CobolStatement

        results = []
        for node in self.traverse_depth_first():
            if isinstance(node, CobolStatement) and node.division_name == division_name:
                results.append(node)
        return results

    def validate(self) -> ValidationResult:
        """Validate the COBOL program structure."""
        result = ValidationResult()

        # Check for required IDENTIFICATION division
        if not self.has_division("IDENTIFICATION"):
            result.add_error("Missing required IDENTIFICATION DIVISION")

        # Check for PROGRAM-ID if IDENTIFICATION division exists
        id_division = self.get_division("IDENTIFICATION")
        if id_division and not self.program_name:
            result.add_error("Missing PROGRAM-ID in IDENTIFICATION DIVISION")

        # Validate division order (IDENTIFICATION should come first)
        division_order = ["IDENTIFICATION", "ENVIRONMENT", "DATA", "PROCEDURE"]
        found_divisions = []

        for division_name in division_order:
            if self.has_division(division_name):
                found_divisions.append(division_name)

        # Check if divisions are in correct order
        expected_order = [d for d in division_order if self.has_division(d)]
        if found_divisions != expected_order:
            result.add_warning(
                f"Divisions not in standard order. Found: {found_divisions}, Expected: {expected_order}"
            )

        # Validate each division
        for division in self._divisions.values():
            division_result = self._validate_division(division)
            result.errors.extend(division_result.errors)
            result.warnings.extend(division_result.warnings)

        return result

    def _validate_division(self, division: CobolDivision) -> ValidationResult:
        """Validate a specific division."""
        result = ValidationResult()

        if division.division_name == "DATA":
            # DATA division should have at least one section
            if not division.sections:
                result.add_warning("DATA DIVISION has no sections")

        elif division.division_name == "PROCEDURE":
            # PROCEDURE division should have statements
            if not division.paragraphs and not division.sections:
                result.add_warning("PROCEDURE DIVISION is empty")

        return result

    def get_statistics(self) -> dict[str, int | float]:
        """Calculate and return program statistics."""
        if self._statistics is None:
            self._calculate_statistics()
        # Type assertion: _calculate_statistics ensures _statistics is not None
        assert self._statistics is not None
        return self._statistics

    def _calculate_statistics(self) -> None:
        """Calculate program statistics in a single depth-first traversal."""
        from .data_items import CobolDataItem  # avoid circular at module level
        from .statements import CobolStatement

        total_lines = 0
        data_item_count = 0
        procedure_count = 0
        statement_count = 0

        for node in self.traverse_depth_first():
            if hasattr(node, "location") and node.location:
                total_lines = max(total_lines, node.location.line)
            if isinstance(node, CobolDataItem):
                data_item_count += 1
            elif isinstance(node, (CobolParagraph, CobolSection)):
                # Only PROCEDURE DIVISION procedures: WORKING-STORAGE,
                # LOCAL-STORAGE, LINKAGE and FILE are sections too (#508).
                if node.division_name in (None, "PROCEDURE"):
                    procedure_count += 1
            elif isinstance(node, CobolStatement):
                # By class, not ``node_type == "Statement"``: EXEC CICS /
                # EXEC IMS keep their historical ``EXEC_CICS`` / ``EXEC_IMS``
                # node_type and were left out of the count.
                statement_count += 1

        self._statistics = {
            "total_lines": total_lines,
            "data_item_count": data_item_count,
            "procedure_count": procedure_count,
            "statement_count": statement_count,
            "division_count": len(self._divisions),
        }

    def to_dict(self, config: SerializationConfig | None = None) -> dict[str, Any]:
        """Convert program to dictionary representation.

        With no explicit *config*, the one the parser that built this program
        was constructed with applies (``CobolParser(serialization_config=...)``),
        so the constructor option is honoured by every ``to_dict()``/``to_json()``
        call rather than only by callers who pass it again.
        """
        if config is None:
            config = self.serialization_config or SerializationConfig()

        result: dict[str, Any] = {
            "node_type": self.node_type,
            "program_name": self.program_name,
            "divisions": {
                name: division.to_dict() for name, division in self._divisions.items()
            },
        }
        if self.unit_kind != "PROGRAM":
            result["unit_kind"] = self.unit_kind
        container = getattr(self, "parent", None)
        if (
            isinstance(container, CobolProgram)
            and self.enclosing_program is not container
        ):
            # Nesting the tree does not show (#532): None for a stacked
            # unit, else the name of the unit it is nested in.
            result["enclosing_program"] = (
                self.enclosing_program.program_name
                if self.enclosing_program is not None
                else None
            )

        if self.contained_programs:
            result["contained_programs"] = [
                p.to_dict(config) for p in self.contained_programs
            ]

        if config.include_source_locations:
            result["location"] = self.location.to_dict()
        else:
            _strip_locations(result["divisions"])

        if config.include_metadata:
            from cobolparser import __version__

            # No ``created_at``: a timestamp would make the JSON of the same
            # input differ run to run, and the placeholder one was a lie (#508).
            metadata = {
                "statistics": self.get_statistics(),
                "parser_version": __version__,
                **(self._metadata or {}),
            }

            # Add source_locations if requested
            if config.include_source_locations:
                metadata["source_locations"] = True

            result["metadata"] = metadata

        return result

    def to_json(self, config_or_indent: SerializationConfig | int | None = None) -> str:
        """Convert program to JSON representation with configuration options."""
        if isinstance(config_or_indent, SerializationConfig):
            config = config_or_indent
            indent = None if config.compact_format else 2
        else:
            config = self.serialization_config or SerializationConfig()
            if config_or_indent is not None:
                indent = config_or_indent
            else:
                indent = None if config.compact_format else 2
        data = self.to_dict(config)
        return json.dumps(data, indent=indent)

    def _comparable_dict(self) -> dict[str, Any]:
        """``to_dict()`` without locations and without the derived metadata
        block (statistics, parser version, timestamp) -- only this program's
        own metadata takes part in :meth:`equals`."""
        data = self.to_dict(
            SerializationConfig(include_metadata=False, include_source_locations=False)
        )
        data["metadata"] = dict(self._metadata)
        return data

    @classmethod
    def from_json(cls, json_str: str) -> "CobolProgram":
        """Rebuild a program from :meth:`to_json` output -- as a structural
        skeleton, not a full AST.

        Restored, with source locations and per-node metadata:

        * the program name, ``unit_kind``, own metadata and every contained
          program unit (recursively);
        * every division and every section in it;
        * every paragraph (name, location, metadata) -- but **not** its
          PROCEDURE DIVISION statements;
        * every FILE-CONTROL ``SELECT`` entry with all its clauses
          (organization, access mode, record / alternate / relative keys,
          FILE STATUS, ...), which is flat and so rebuilt whole;
        * every data item with all its serialized clauses (level, USAGE,
          PICTURE, VALUE, OCCURS, REDEFINES, SIGN, SYNC, JUSTIFIED, BLANK
          WHEN ZERO, EXTERNAL / GLOBAL / VOLATILE, BYTE-LENGTH, DYNAMIC
          LENGTH, OBJECT REFERENCE, GROUP-USAGE), its subordinate items, its
          level-88 condition names, and each section's level-66 RENAMES
          entries.

        **Dropped:** every PROCEDURE DIVISION statement (and so everything
        nested in one). There are some hundred statement node types and no
        generic way to rebuild them from their dicts, so the restored
        paragraphs are empty. Whenever statements are dropped a
        :class:`LossyDeserializationWarning` names how many, so the loss is
        never silent. Anything ``to_dict()`` never serializes (FD/SD
        entries, whether a USAGE was written explicitly) cannot come back
        either. Reparse the source when a full AST is needed.
        """
        dropped: dict[str, int] = {}
        program = cls._from_dict(json.loads(json_str), dropped)
        program._restore_nesting()
        if dropped.get("statements"):
            warnings.warn(
                f"CobolProgram.from_json restored a structural skeleton of "
                f"{program.program_name or '<unnamed>'}: dropped "
                f"{dropped['statements']} PROCEDURE DIVISION statement(s) "
                f"from {dropped['paragraphs']} paragraph(s); divisions, "
                f"sections, paragraphs and data items were restored",
                LossyDeserializationWarning,
                stacklevel=2,
            )
        return program

    @classmethod
    def _from_dict(
        cls, data: dict[str, Any], dropped: dict[str, int] | None = None
    ) -> "CobolProgram":
        """Rebuild one program unit (and, recursively, the units it contains)
        from its ``to_dict()`` form. Counts of what could not be rebuilt are
        accumulated into *dropped*."""
        if dropped is None:
            dropped = {}
        program = cls(data.get("program_name", ""), _location_from(data))

        for div_name, div_data in data.get("divisions", {}).items():
            division = CobolDivision(
                div_data.get("division_name", div_name), _location_from(div_data)
            )
            _restore_metadata(division, div_data)
            for section_data in div_data.get("sections", {}).values():
                division.add_section(_section_from(section_data, dropped))
            for para_data in div_data.get("paragraphs", []):
                division.add_paragraph(_paragraph_from(para_data, dropped))
            program.add_division(division)

        # Set metadata if present
        if "metadata" in data:
            metadata = data["metadata"]
            for key, value in metadata.items():
                if key not in [
                    "statistics",
                    "parser_version",
                    "created_at",
                    "source_locations",
                ]:
                    program.set_metadata(key, value)

        # The unit structure: a CLASS-ID came back as a PROGRAM and every
        # nested / stacked / method unit was dropped, so program_units() of
        # the restored program no longer matched the one serialized.
        program.unit_kind = data.get("unit_kind", "PROGRAM")
        for contained in data.get("contained_programs", []):
            program.add_contained_program(cls._from_dict(contained, dropped))
        if "enclosing_program" in data:
            program._enclosing_name = data["enclosing_program"] or ""

        return program

    def _restore_nesting(self) -> None:
        """Point each unit ``to_dict`` marked with ``enclosing_program`` at
        the nearest preceding unit of that name ("" = stacked)."""
        seen: list[CobolProgram] = []
        for unit in self.program_units():
            name, unit._enclosing_name = unit._enclosing_name, None
            if name is not None:
                unit.enclosing_program = (
                    next(
                        (
                            u
                            for u in reversed(seen)
                            if (u.program_name or "").upper() == name.upper()
                        ),
                        None,
                    )
                    if name
                    else None
                )
            seen.append(unit)


class LossyDeserializationWarning(UserWarning):
    """``CobolProgram.from_json`` could not restore part of the serialized
    program (PROCEDURE DIVISION statements); the message says what and how
    many."""


def _location_from(data: dict[str, Any]) -> SourceLocation:
    """A ``SourceLocation`` from a node dict's ``location`` (1:1 if absent)."""
    loc = data.get("location") or {}
    return SourceLocation(loc.get("line", 1), loc.get("column", 1), loc.get("length"))


def _restore_metadata(node: ASTNode, data: dict[str, Any]) -> None:
    for key, value in (data.get("metadata") or {}).items():
        node.set_metadata(key, value)


def _paragraph_from(data: dict[str, Any], dropped: dict[str, int]) -> "CobolParagraph":
    paragraph = CobolParagraph(data.get("paragraph_name", ""), _location_from(data))
    _restore_metadata(paragraph, data)
    lost = 0
    for stmt_data in data.get("statements") or []:
        if stmt_data.get("statement_type") == "SELECT":
            paragraph.add_statement(_select_from(stmt_data))
        else:
            lost += 1
    if lost:
        dropped["statements"] = dropped.get("statements", 0) + lost
        dropped["paragraphs"] = dropped.get("paragraphs", 0) + 1
    return paragraph


#: Keys of a statement dict written by ``CobolStatement.to_dict()`` itself;
#: every other key of a SELECT dict is one ``SelectStatement`` attribute.
_STATEMENT_BASE_KEYS = frozenset(
    {"node_type", "statement_type", "operands", "location", "metadata"}
)


def _select_from(data: dict[str, Any]) -> "CobolStatement":
    """A FILE-CONTROL ``SelectStatement`` from its ``to_dict()`` form.

    Unlike PROCEDURE DIVISION statements a SELECT entry is flat -- every
    clause is one scalar or list attribute -- so it is rebuilt whole: the
    file's organization, access mode, keys and FILE STATUS survive a
    ``to_json()`` / ``from_json()`` round trip (``ProgramLayoutIndex`` and
    the IO analyzers read them).
    """
    from .statements.misc import SelectStatement

    select = SelectStatement(_location_from(data))
    _restore_metadata(select, data)
    select.operands = list(data.get("operands") or [])
    for key, value in data.items():
        if key in _STATEMENT_BASE_KEYS or not hasattr(select, key):
            continue
        if isinstance(value, list):
            value = [dict(v) if isinstance(v, dict) else v for v in value]
        setattr(select, key, value)
    return select


def _section_from(data: dict[str, Any], dropped: dict[str, int]) -> CobolSection:
    from .data_items import RenamesItem

    section = CobolSection(data.get("section_name", ""), _location_from(data))
    _restore_metadata(section, data)
    for para_data in data.get("paragraphs", []):
        section.add_paragraph(_paragraph_from(para_data, dropped))
    for item_data in data.get("data_items", []):
        section.add_data_item(_data_item_from(item_data))
    for ren in data.get("renames_items", []):
        renames = RenamesItem(
            ren.get("name", ""),
            ren.get("renames_from", ""),
            _location_from(ren),
            ren.get("renames_through"),
        )
        renames.renames_from_qualifiers = list(ren.get("renames_from_qualifiers", []))
        renames.renames_through_qualifiers = list(
            ren.get("renames_through_qualifiers", [])
        )
        _restore_metadata(renames, ren)
        section.add_child(renames)
    return section


#: CobolDataItem attributes ``to_dict()`` writes under the same key, only
#: when set (so absent means the constructor default).
_DATA_ITEM_OPTIONAL_FIELDS = (
    "value_clause",
    "sign_clause",
    "synchronized",
    "justified",
    "blank_when_zero",
    "is_external",
    "is_global",
    "is_volatile",
    "byte_length",
    "is_dynamic_length",
    "dynamic_length_limit",
    "object_class",
    "group_usage",
    "redefines",
)

#: PictureClause attributes computed from the pattern; restored verbatim from
#: the dict so a size adjusted after construction (BYTE-LENGTH) survives.
_PICTURE_FIELDS = (
    "size",
    "integer_digits",
    "decimal_digits",
    "total_digits",
    "is_signed",
    "has_scaling_factor",
    "scaling_factor",
    "is_edited",
    "is_numeric_edited",
    "is_alphanumeric_edited",
    "is_national",
    "is_national_edited",
    "is_valid",
)


def _data_item_from(data: dict[str, Any]) -> "CobolDataItem":
    from .data_items import (
        CobolDataItem,
        ConditionNameItem,
        OccursClause,
        PictureClause,
    )

    item = CobolDataItem(
        data.get("name", ""), data.get("level", 1), _location_from(data)
    )
    _restore_metadata(item, data)

    pic = data.get("picture_clause")
    if pic is not None:
        pic_meta = pic.get("metadata") or {}
        picture = PictureClause(
            pic.get("pattern", ""),
            _location_from(pic),
            currency_symbols=set(pic_meta.get("currency_symbols", ())),
            decimal_point_is_comma=bool(pic_meta.get("decimal_point_is_comma")),
            currency_signs=dict(pic_meta.get("currency_signs") or {}),
        )
        for field in _PICTURE_FIELDS:
            if field in pic:
                setattr(picture, field, pic[field])
        picture.validation_errors = list(pic.get("validation_errors", []))
        _restore_metadata(picture, pic)
        item.set_picture_clause(picture)

    occ = data.get("occurs_clause")
    if occ is not None:
        occurs = OccursClause(_location_from(occ))
        occurs.min_times = occ.get("min_times")
        occurs.max_times = occ.get("max_times")
        occurs.depending_on = occ.get("depending_on")
        occurs.indexed_by = occ.get("indexed_by")
        occurs.index_names = list(occ.get("index_names", []))
        occurs.key_clauses = [dict(kc) for kc in occ.get("key_clauses", [])]
        occurs.is_unbounded = bool(occ.get("is_unbounded", False))
        occurs.depending_on_qualifiers = list(occ.get("depending_on_qualifiers", []))
        _restore_metadata(occurs, occ)
        item.set_occurs_clause(occurs)

    # USAGE last: set_picture_clause may have implied one. Whether it was
    # written explicitly is not serialized; a usage other than the one the
    # PICTURE alone implies (or DISPLAY) must have been.
    usage = data.get("usage", "DISPLAY")
    item.usage = usage
    item.usage_explicit = usage not in ("DISPLAY", _implied_usage(item))
    if "is_filler" in data:
        item.is_filler = bool(data["is_filler"])
    for field in _DATA_ITEM_OPTIONAL_FIELDS:
        if field in data:
            setattr(item, field, data[field])

    # A level-88 entry on a group immediately follows the group's own entry,
    # so condition names come before the subordinate items.
    for cond in data.get("condition_names", []):
        condition = ConditionNameItem(cond.get("name", ""), _location_from(cond))
        condition.values = list(cond.get("values", []))
        condition.false_value = cond.get("false_value")
        _restore_metadata(condition, cond)
        item.add_child(condition)
    for child in data.get("children", []):
        item.add_child(_data_item_from(child))
    return item


def _implied_usage(item: "CobolDataItem") -> str | None:
    from .data_items import _implied_picture_usage

    if item.picture_clause is None:
        return None
    return _implied_picture_usage(item.picture_clause)


class CobolFileDescription(ASTNode):
    """AST node for FD (File Description) and SD (Sort Description) in FILE SECTION.

    Supports comprehensive FD/SD clause variations:
    - BLOCK CONTAINS with fixed/dynamic record count
    - RECORD CONTAINS with fixed and variable length specifications
    - LABEL RECORDS specifications
    - VALUE OF clauses
    - DATA RECORDS declarations
    - LINAGE with FOOTING and TOP/BOTTOM specifications
    - CODE-SET for character encoding
    - RECORDING MODE (F, V, U, S)
    - EXTERNAL and GLOBAL attributes
    - IBM Enterprise COBOL extensions
    """

    def __init__(
        self, file_name: str, location: SourceLocation, record_type: str = "FD"
    ):
        super().__init__("FileDescription", location)
        self.file_name = file_name
        self.record_type = record_type  # FD or SD
        self.data_records: list[CobolDataItem] = []

        # BLOCK CONTAINS clause
        self.block_contains: int | None = None
        self.block_contains_min: int | None = None  # For range: min TO max
        self.block_contains_max: int | None = None
        self.block_contains_unit: str | None = None  # RECORDS or CHARACTERS

        # RECORD CONTAINS clause
        self.record_contains: int | None = None  # Fixed length
        self.record_contains_min: int | None = None  # Variable: min TO max
        self.record_contains_max: int | None = None
        self.record_varying_depending_on: str | None = None

        # LABEL RECORDS clause
        self.label_records: str | None = None  # STANDARD, OMITTED, or data-name

        # VALUE OF clause
        self.value_of: list[dict[str, str]] = []  # [{system_name, value}]

        # DATA RECORDS clause
        self.data_record_names: list[str] = []

        # LINAGE clause
        self.linage_value: int | str | None = None  # Number or data-name
        self.linage_footing: int | str | None = None
        self.linage_top: int | str | None = None
        self.linage_bottom: int | str | None = None

        # CODE-SET clause
        self.code_set: str | None = None
        self.code_set_for_alphanumeric: str | None = None
        self.code_set_for_national: str | None = None  # IBM extension

        # RECORDING MODE clause
        self.recording_mode: str | None = None  # F, V, U, S

        # EXTERNAL/GLOBAL attributes
        self.is_external: bool = False
        self.is_global: bool = False

        # REPORT IS clause (Report Writer)
        self.report_names: list[str] = []

    def set_block_contains(
        self,
        count: int | None = None,
        min_count: int | None = None,
        max_count: int | None = None,
        unit: str | None = None,
    ) -> None:
        """Set the BLOCK CONTAINS clause."""
        if min_count is not None and max_count is not None:
            self.block_contains_min = min_count
            self.block_contains_max = max_count
        else:
            self.block_contains = count
        self.block_contains_unit = unit

    def set_record_contains(
        self,
        count: int | None = None,
        min_count: int | None = None,
        max_count: int | None = None,
        depending_on: str | None = None,
    ) -> None:
        """Set the RECORD CONTAINS clause."""
        if min_count is not None and max_count is not None:
            self.record_contains_min = min_count
            self.record_contains_max = max_count
        else:
            self.record_contains = count
        self.record_varying_depending_on = depending_on

    def set_label_records(self, value: str) -> None:
        """Set the LABEL RECORDS clause."""
        self.label_records = value

    def set_linage(
        self,
        value: int | str | None,
        footing: int | str | None = None,
        top: int | str | None = None,
        bottom: int | str | None = None,
    ) -> None:
        """Set the LINAGE clause with optional footing and margins."""
        self.linage_value = value
        self.linage_footing = footing
        self.linage_top = top
        self.linage_bottom = bottom

    def set_code_set(
        self,
        code_set: str,
        for_alphanumeric: str | None = None,
        for_national: str | None = None,
    ) -> None:
        """Set the CODE-SET clause."""
        self.code_set = code_set
        self.code_set_for_alphanumeric = for_alphanumeric
        self.code_set_for_national = for_national

    def set_recording_mode(self, mode: str) -> None:
        """Set the RECORDING MODE clause."""
        self.recording_mode = mode.upper()

    def set_external(self, is_external: bool = True) -> None:
        """Set the EXTERNAL attribute."""
        self.is_external = is_external

    def set_global(self, is_global: bool = True) -> None:
        """Set the GLOBAL attribute."""
        self.is_global = is_global

    def to_dict(self) -> dict[str, Any]:
        """Convert FD/SD to dictionary representation."""
        result = {
            "node_type": self.node_type,
            "file_name": self.file_name,
            "record_type": self.record_type,
            "data_records": len(self.data_records),
            "data_record_details": [d.to_dict() for d in self.data_records],
            "location": self.location.to_dict(),
            "metadata": self._metadata or {},
        }

        # BLOCK CONTAINS
        if self.block_contains is not None:
            result["block_contains"] = {
                "count": self.block_contains,
                "unit": self.block_contains_unit,
            }
        elif self.block_contains_min is not None:
            result["block_contains"] = {
                "min": self.block_contains_min,
                "max": self.block_contains_max,
                "unit": self.block_contains_unit,
            }

        # RECORD CONTAINS
        if self.record_contains is not None:
            result["record_contains"] = {"count": self.record_contains}
        elif self.record_contains_min is not None:
            result["record_contains"] = {
                "min": self.record_contains_min,
                "max": self.record_contains_max,
                "depending_on": self.record_varying_depending_on,
            }

        # Other clauses
        if self.label_records:
            result["label_records"] = self.label_records
        if self.value_of:
            result["value_of"] = self.value_of
        if self.data_record_names:
            result["data_record_names"] = self.data_record_names
        if self.linage_value is not None:
            result["linage"] = {
                "value": self.linage_value,
                "footing": self.linage_footing,
                "top": self.linage_top,
                "bottom": self.linage_bottom,
            }
        if self.code_set:
            result["code_set"] = {
                "name": self.code_set,
                "for_alphanumeric": self.code_set_for_alphanumeric,
                "for_national": self.code_set_for_national,
            }
        if self.recording_mode:
            result["recording_mode"] = self.recording_mode
        if self.is_external:
            result["is_external"] = True
        if self.is_global:
            result["is_global"] = True
        if self.report_names:
            result["report_names"] = self.report_names

        return result


# Forward references - actual implementations in data_items.py and statements.py
# These are imported at runtime to avoid circular imports


# Module exports
__all__ = [
    "CobolProgram",
    "CobolDivision",
    "CobolSection",
    "CobolParagraph",
    "CobolFileDescription",
]
