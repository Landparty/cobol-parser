"""
COBOL program structure nodes including programs, divisions, and sections.

This module implements the high-level structural elements of COBOL programs
including program nodes, division nodes, and section nodes with full
JSON serialization support.
"""

import fnmatch
import json
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
        return {
            "node_type": self.node_type,
            "section_name": self.section_name,  # Use property
            "location": self.location.to_dict(),
            "paragraphs": [p.to_dict() for p in self.paragraphs],
            "data_items": [d.to_dict() for d in self.data_items],
            "metadata": self._metadata or {},
        }


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


class CobolProgram(ASTNode):
    """AST node representing a complete COBOL program."""

    def __init__(self, program_name: str, location: SourceLocation):
        super().__init__("Program", location)
        self.program_name = program_name
        # Internal mapping of division name -> division object
        self._divisions: dict[str, CobolDivision] = {}
        # Cached statistics
        self._statistics: dict[str, Any] | None = None
        # S1 optimization: cache get_all_statements() result. Multiple
        # extractors (call/copy/sql/file_io) call this method 1-2 times each
        # — ~7 traversals per program. Memoizing converts that into one
        # traversal + 6 O(1) returns. Invalidated by add_division().
        self._cached_all_statements: list[CobolStatement] | None = None

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

    def get_division(self, name: str) -> CobolDivision | None:
        """Get a division by name."""
        return self._divisions.get(name)

    def has_division(self, name: str) -> bool:
        """Check if program has a specific division."""
        return name in self._divisions

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

        from .statements import CobolStatement

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

            # 3. Recurse known attribute lists (handle orphans/non-children)
            # COBOL statements often have conditional blocks in attributes
            orphan_attrs = [
                "at_end_clause",
                "not_at_end_clause",
                "invalid_key_clause",
                "not_invalid_key_clause",
                "at_eop_clause",
                "on_exception",
                "not_on_exception",
                "on_overflow",
                "not_on_overflow",
                "on_size_error",
                "not_on_size_error",
                "when_clauses",
                "default_when",
                "then_statements",
                "else_statements",
                "inline_statements",
            ]

            for attr in orphan_attrs:
                if hasattr(node, attr):
                    val = getattr(node, attr)
                    if val:
                        traverse(val)

        # Start traversal from PROCEDURE division
        proc_division = self.get_division("PROCEDURE")
        if proc_division:
            traverse(proc_division)

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
        """Find statements that use a specific variable."""
        all_statements = self.get_all_statements()
        using_variable = []

        for stmt in all_statements:
            # Check operands for variable usage
            for operand in stmt.operands:
                if variable_name in operand:
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
        all_statements = self.get_all_statements()
        for stmt in all_statements:
            if stmt.statement_type == "EXEC-SQL":
                return True
        return False

    def has_cics(self) -> bool:
        """Check if program uses EXEC CICS statements."""
        all_statements = self.get_all_statements()
        for stmt in all_statements:
            if stmt.statement_type == "EXEC-CICS":
                return True
        return False

    def has_ims(self) -> bool:
        """Check if program uses EXEC IMS statements or declares ENTRY 'DLITCBL'."""
        all_statements = self.get_all_statements()
        for stmt in all_statements:
            if stmt.statement_type == "EXEC-IMS":
                return True
        return self.is_ims_dlitcbl_program()

    def get_sql_statements(self) -> list["CobolStatement"]:
        """Get all EXEC SQL statements in the program."""
        all_statements = self.get_all_statements()
        return [stmt for stmt in all_statements if stmt.statement_type == "EXEC-SQL"]

    def get_cics_statements(self) -> list["CobolStatement"]:
        """Get all EXEC CICS statements in the program."""
        all_statements = self.get_all_statements()
        return [stmt for stmt in all_statements if stmt.statement_type == "EXEC-CICS"]

    def get_ims_statements(self) -> list["CobolStatement"]:
        """Get all EXEC IMS statements in the program."""
        all_statements = self.get_all_statements()
        return [stmt for stmt in all_statements if stmt.statement_type == "EXEC-IMS"]

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

        Scans all statement operand and expression strings for the ``FUNCTION``
        keyword followed by an identifier, returning each matched function name
        in the order it appears (duplicates included).
        """
        import re

        pattern = re.compile(r"FUNCTION\s*([A-Z][A-Z0-9-]*)", re.IGNORECASE)
        found: list[str] = []
        for stmt in self.get_all_statements():
            seen_texts: set[str] = set()
            texts: list[str] = []
            for op in stmt.operands:
                if op and op not in seen_texts:
                    seen_texts.add(op)
                    texts.append(op)
            expr = getattr(stmt, "expression", None)
            if isinstance(expr, str) and expr not in seen_texts:
                seen_texts.add(expr)
                texts.append(expr)
            # MoveStatement.source is inserted into operands by set_source(),
            # so only scan it when it is not already covered above.
            source = getattr(stmt, "source", None)
            if isinstance(source, str) and source not in seen_texts:
                texts.append(source)
            for text in texts:
                for m in pattern.finditer(text):
                    found.append(m.group(1).upper())
        return found

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

        total_lines = 0
        data_item_count = 0
        procedure_count = 0
        statement_count = 0

        for node in self.traverse_depth_first():
            if hasattr(node, "location") and node.location:
                total_lines = max(total_lines, node.location.line)
            nt = getattr(node, "node_type", "")
            if isinstance(node, CobolDataItem):
                data_item_count += 1
            elif isinstance(node, (CobolParagraph, CobolSection)):
                procedure_count += 1
            elif nt == "Statement":
                statement_count += 1

        self._statistics = {
            "total_lines": total_lines,
            "data_item_count": data_item_count,
            "procedure_count": procedure_count,
            "statement_count": statement_count,
            "division_count": len(self._divisions),
        }

    def to_dict(self, config: SerializationConfig | None = None) -> dict[str, Any]:
        """Convert program to dictionary representation."""
        if config is None:
            config = SerializationConfig()

        result = {
            "node_type": self.node_type,
            "program_name": self.program_name,
            "divisions": {
                name: division.to_dict() for name, division in self._divisions.items()
            },
        }

        if config.include_source_locations:
            result["location"] = self.location.to_dict()

        if config.include_metadata:
            metadata = {
                "statistics": self.get_statistics(),
                "parser_version": "1.0.0",
                "created_at": "2024-01-01T00:00:00Z",  # Would be actual timestamp
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
            indent = 2
        else:
            config = SerializationConfig()
            indent = config_or_indent if config_or_indent is not None else 2
        data = self.to_dict(config)
        return json.dumps(data, indent=indent)

    @classmethod
    def from_json(cls, json_str: str) -> "CobolProgram":
        """Create a CobolProgram instance from JSON representation."""
        data = json.loads(json_str)

        # Extract basic program information
        program_name = data.get("program_name", "")

        # Reconstruct location
        location_data = data.get("location", {"line": 1, "column": 1})
        location = SourceLocation(location_data["line"], location_data["column"])

        # Create program instance
        program = cls(program_name, location)

        # Reconstruct divisions
        divisions_data = data.get("divisions", {})
        for div_name, div_data in divisions_data.items():
            div_location_data = div_data.get("location", {"line": 1, "column": 1})
            div_location = SourceLocation(
                div_location_data["line"], div_location_data["column"]
            )
            division = CobolDivision(div_name, div_location)
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

        return program


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
