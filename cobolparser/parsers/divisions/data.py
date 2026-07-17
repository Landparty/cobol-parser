"""Data Division parser for COBOL programs.

This module implements parsing of the Data Division which contains:
- FILE SECTION: File descriptions and records
- WORKING-STORAGE SECTION: Working variable definitions
- LOCAL-STORAGE SECTION: Local variable definitions
- LINKAGE SECTION: Program parameter definitions

The :class:`DataDivisionParser` owns the section scan loop, the level-number
hierarchy building, and the AST node creation. The detailed entry parsing is
delegated to focused collaborators:

- :class:`~.data_clauses.DataItemClauseParser` — data-description entries and
  their clauses (PICTURE, VALUE, USAGE, OCCURS, ...), including the optional
  Cython fast path
- :class:`~.data_file_description.FileDescriptionClauseParser` — FD/SD
  file-description clause capture
- :class:`~.data_special_entries.SpecialEntryParser` — level-88 condition
  names, level-66 RENAMES, and data-division EXEC SQL blocks
"""

from typing import Any

from cobolparser.core.interfaces import ITokenStream
from cobolparser.lexer import TokenType
from cobolparser.models.ast_base import ASTNode, SourceLocation
from cobolparser.models.data_items import (
    CobolDataItem,
    ConditionNameItem,
    RenamesItem,
)
from cobolparser.models.program import CobolDivision, CobolSection
from cobolparser.models.sql_statements import ExecSQLStatement

from .base import BaseDivisionParser, at_division_boundary
from .data_clauses import _DIVISION_TOKEN_TYPES, DataItemClauseParser
from .data_file_description import FileDescriptionClauseParser
from .data_special_entries import SpecialEntryParser

# Hoisted out of _parse_section -- these were being rebuilt as set
# literals on every call.
_SECTION_KEYWORDS: frozenset[str] = frozenset(
    {
        "SECTION",
        "FILE",
        "WORKING-STORAGE",
        "LOCAL-STORAGE",
        "LINKAGE",
        "DATA",
        "PROCEDURE",
        "ENVIRONMENT",
        "IDENTIFICATION",
    }
)
_SECTION_BREAK_HEADERS: frozenset[str] = frozenset(
    {"FILE", "WORKING-STORAGE", "LOCAL-STORAGE", "LINKAGE"}
)


class DataDivisionParser(BaseDivisionParser):
    """Parser for COBOL Data Division.

    Handles data structure definitions with section support.
    Supports FILE, WORKING-STORAGE, LOCAL-STORAGE, and LINKAGE sections.
    """

    division_name: str | None = "DATA"
    division_keywords: tuple = ()

    def __init__(self) -> None:
        """Initialize the Data Division parser and its entry collaborators."""
        super().__init__()
        self._clause_parser = DataItemClauseParser(self)
        self._fd_parser = FileDescriptionClauseParser()
        self._special_entries = SpecialEntryParser()

    def parse_division(self, token_stream: ITokenStream) -> dict[str, Any]:
        """Parse Data Division content.

        Parses optional sections:
        - FILE SECTION
        - WORKING-STORAGE SECTION
        - LOCAL-STORAGE SECTION
        - LINKAGE SECTION

        Args:
            token_stream: Token stream positioned after division header

        Returns:
            Dictionary containing parsed data sections
        """
        sections: dict[str, Any] = {}

        # Parse sections until we reach next division or EOF
        while not token_stream.is_empty():
            token = token_stream.peek(0)
            if not token:
                break

            token_value = token.value.upper()

            # Check if we've reached next division
            # Handle both bare keywords and composite tokens (e.g. "PROCEDURE DIVISION")
            _stop_div = ("IDENTIFICATION", "ENVIRONMENT", "PROCEDURE")
            if token_value in _stop_div:
                break
            if any(token_value == f"{kw} DIVISION" for kw in _stop_div):
                break

            # Parse specific sections
            if token_value == "FILE":
                sections["file"] = self._parse_section(token_stream, "FILE")
            elif token_value == "WORKING-STORAGE":
                sections["working_storage"] = self._parse_section(
                    token_stream, "WORKING-STORAGE"
                )
            elif token_value == "LOCAL-STORAGE":
                sections["local_storage"] = self._parse_section(
                    token_stream, "LOCAL-STORAGE"
                )
            elif token_value == "LINKAGE":
                sections["linkage"] = self._parse_section(token_stream, "LINKAGE")
            else:
                # Unknown section - skip it for error recovery
                token_stream.consume()

        return sections

    def _parse_section(
        self, token_stream: ITokenStream, section_name: str
    ) -> dict[str, Any]:
        """Parse a data section.

        Format: SECTION-NAME SECTION. [data-items]

        Args:
            token_stream: Token stream positioned at section keyword
            section_name: Name of the section (FILE, WORKING-STORAGE, etc.)

        Returns:
            Dictionary containing section content with parsed data items
        """
        # Capture the section keyword's own location before consuming it (the
        # AST node must report where this section actually starts, not its
        # parent division's location).
        section_token = token_stream.peek(0)
        section_location = section_token.location if section_token else None

        # Consume section keyword
        token_stream.consume()

        # Consume 'SECTION' keyword if present
        _dt = token_stream.peek()
        if _dt and _dt.value and _dt.value.upper() == "SECTION":
            token_stream.consume()

        # Consume period if present
        _dp = token_stream.peek()
        if _dp and _dp.type == TokenType.PERIOD:
            token_stream.consume()

        # Parse data items until we reach next section or division
        data_items: list[ConditionNameItem | RenamesItem | CobolDataItem] = []
        exec_sql_items: list[ExecSQLStatement] = []
        paren_depth = 0  # Track nesting depth of parentheses
        current_fd_name: str | None = None  # FD/SD file name for FILE SECTION items
        # FD/SD clauses (BLOCK CONTAINS, RECORD, LABEL, etc.) for the file the
        # current 01-level records belong to. Captured rather than discarded so
        # the record layout's physical attributes survive into the AST.
        current_fd_clauses: dict[str, Any] = {}

        while not token_stream.is_empty():
            token = token_stream.peek()
            if not token:
                break

            tok_type = token.type
            tok_value = token.value

            # Check if we've reached next section/division (by token type, not just value check)
            if tok_type in _DIVISION_TOKEN_TYPES:
                break

            # Cheap parenthesis tracking before any keyword work.
            if tok_value == "(":
                paren_depth += 1
                token_stream.consume()
                continue
            if tok_value == ")":
                paren_depth -= 1
                token_stream.consume()
                continue

            # Compute upper-cased value once per iteration -- the next two
            # checks each need it (and several deeper branches also do).
            value_upper = tok_value.upper() if tok_value else ""

            # Stop when we encounter the next section header or division header.
            if value_upper in _SECTION_BREAK_HEADERS:
                next_token = token_stream.peek(1)
                if (
                    next_token
                    and next_token.value
                    and next_token.value.upper() == "SECTION"
                ):
                    break

            # Also check for section keywords that appear as identifiers
            if value_upper in _SECTION_KEYWORDS and tok_type != TokenType.IDENTIFIER:
                break

            # A division header split across source lines ("PROCEDURE" at the
            # end of one line, "DIVISION." on the next) reaches this scanner
            # as plain IDENTIFIER tokens — stop without consuming it.
            if value_upper in ("IDENTIFICATION", "ENVIRONMENT", "PROCEDURE"):
                if at_division_boundary(token_stream):
                    break

            # In FILE SECTION, detect FD/SD declarations to build record-to-file mapping
            if (
                section_name == "FILE"
                and paren_depth == 0
                and (
                    tok_type in (TokenType.FD, TokenType.SD)
                    or (
                        tok_type == TokenType.IDENTIFIER and value_upper in ("FD", "SD")
                    )
                )
            ):
                token_stream.consume()  # consume FD/SD
                fd_name_tok = token_stream.peek()
                if fd_name_tok and fd_name_tok.type == TokenType.IDENTIFIER:
                    current_fd_name = fd_name_tok.value
                    token_stream.consume()  # consume file name
                # Capture the FD/SD clauses (instead of discarding them) so the
                # file's physical layout (block/record sizes, recording mode,
                # labels, code set, EXTERNAL/GLOBAL) is preserved in the AST.
                current_fd_clauses = self._parse_fd_clauses(token_stream)
                continue

            # Parse EXEC SQL blocks that appear in the data division
            # (e.g. DCLGEN-generated DECLARE TABLE or INCLUDE SQLCA)
            is_exec = tok_type == TokenType.EXEC or (
                tok_type == TokenType.IDENTIFIER and value_upper == "EXEC"
            )
            if is_exec and paren_depth == 0:
                next_tok = token_stream.peek(1)
                is_sql = next_tok and (
                    next_tok.type == TokenType.SQL
                    or (
                        next_tok.type == TokenType.IDENTIFIER
                        and next_tok.value
                        and next_tok.value.upper() == "SQL"
                    )
                )
                if is_sql:
                    sql_stmt = self._parse_exec_sql_in_data(token_stream)
                    if sql_stmt is not None:
                        exec_sql_items.append(sql_stmt)
                    continue

            # Try to parse a data item (should start with level number, but not inside parentheses)
            if tok_type == TokenType.LEVEL_NUMBER and paren_depth == 0:
                try:
                    lvl = int(tok_value)
                except (ValueError, TypeError):
                    lvl = -1

                if lvl == 88:
                    cond_item = self._parse_condition_name_item(token_stream)
                    if cond_item:
                        data_items.append(cond_item)
                elif lvl == 66:
                    renames_item = self._parse_renames_item(token_stream)
                    if renames_item:
                        data_items.append(renames_item)
                else:
                    data_item = self._parse_data_item(token_stream)
                    if data_item:
                        # Tag 01-level FILE SECTION records with their parent FD name
                        if (
                            section_name == "FILE"
                            and data_item.level == 1
                            and current_fd_name is not None
                        ):
                            data_item.set_metadata("fd_file_name", current_fd_name)
                            if current_fd_clauses:
                                data_item.set_metadata(
                                    "fd_clauses", dict(current_fd_clauses)
                                )
                        data_items.append(data_item)
            else:
                # Skip unexpected tokens
                token_stream.consume()

        # Build hierarchical structure based on level numbers
        hierarchical_items = self._build_data_hierarchy(data_items)

        result: dict[str, Any] = {
            "type": section_name.lower().replace("-", "_"),
            "data_items": hierarchical_items,
            "exec_sql_items": exec_sql_items,
        }
        if section_location is not None:
            result["location"] = section_location
        return result

    def _build_data_hierarchy(self, data_items: list) -> list:
        """Build hierarchical structure from flat list of data items.

        This arranges data items into parent-child relationships based on
        level numbers. Items with higher level numbers become children of
        items with lower level numbers.

        Args:
            data_items: Flat list of parsed data items

        Returns:
            List of top-level data items (01 level), with nested items as children
        """
        if not data_items:
            return []

        top_level_items: list[Any] = []
        stack: list[Any] = []  # Stack of (level, item) pairs

        for item in data_items:
            # Level-88 condition names attach to the most recent item on the stack
            if isinstance(item, ConditionNameItem):
                if stack:
                    stack[-1][1].add_child(item)
                else:
                    top_level_items.append(item)
                # Do NOT push 88-level onto the stack
                continue

            # Level-66 RENAMES are always top-level aliases
            if isinstance(item, RenamesItem):
                top_level_items.append(item)
                continue

            current_level = item.level

            # Remove items from stack that have higher or equal level
            while stack and stack[-1][0] >= current_level:
                stack.pop()

            # If stack is empty, this is a top-level item
            if not stack:
                top_level_items.append(item)
            else:
                # Add as child to the most recent item with lower level
                parent_item = stack[-1][1]
                parent_item.add_child(item)

            # Add current item to stack
            stack.append((current_level, item))

        return top_level_items

    # ------------------------------------------------------------------
    # Delegating wrappers.
    #
    # The entry-level parsing lives in the collaborator classes (see the
    # module docstring). These wrappers keep the historical method names on
    # the division parser itself — the Cython fast path
    # (``cobolparser._data_fast``) calls ``_parse_picture_clause`` /
    # ``_parse_value_clause`` / ``_parse_usage_clause`` back on this object,
    # so those three in particular must keep their exact names/signatures.
    # ------------------------------------------------------------------

    def _parse_data_item(self, token_stream: ITokenStream) -> CobolDataItem | None:
        """Parse a single data item definition (delegates to DataItemClauseParser)."""
        return self._clause_parser.parse_data_item(token_stream)

    def _parse_picture_clause(self, token_stream: ITokenStream) -> str | None:
        """Parse PICTURE clause pattern (delegates to DataItemClauseParser)."""
        return self._clause_parser.parse_picture_clause(token_stream)

    def _parse_value_clause(self, token_stream: ITokenStream) -> str | None:
        """Parse VALUE clause value (delegates to DataItemClauseParser)."""
        return self._clause_parser.parse_value_clause(token_stream)

    def _parse_usage_clause(self, token_stream: ITokenStream) -> str | None:
        """Parse USAGE clause value (delegates to DataItemClauseParser)."""
        return self._clause_parser.parse_usage_clause(token_stream)

    def _parse_fd_clauses(self, token_stream: ITokenStream) -> dict[str, Any]:
        """Parse FD/SD clauses (delegates to FileDescriptionClauseParser)."""
        return self._fd_parser.parse_fd_clauses(token_stream)

    def _parse_condition_name_item(
        self, token_stream: ITokenStream
    ) -> ConditionNameItem | None:
        """Parse a level-88 condition name item (delegates to SpecialEntryParser)."""
        return self._special_entries.parse_condition_name_item(token_stream)

    def _parse_renames_item(self, token_stream: ITokenStream) -> RenamesItem | None:
        """Parse a level-66 RENAMES item (delegates to SpecialEntryParser)."""
        return self._special_entries.parse_renames_item(token_stream)

    def _parse_exec_sql_in_data(
        self, token_stream: ITokenStream
    ) -> ExecSQLStatement | None:
        """Parse a data-division EXEC SQL block (delegates to SpecialEntryParser)."""
        return self._special_entries.parse_exec_sql_in_data(token_stream)

    def _create_ast_node(
        self,
        division_token: Any,
        division_content: dict[str, Any],
        start_location: SourceLocation,
    ) -> ASTNode:
        """Create AST node for Data Division.

        Creates a CobolDivision node with data sections.

        Args:
            division_token: The DATA token
            division_content: Parsed content from parse_division()
            start_location: Start location for the AST node

        Returns:
            CobolDivision AST node with data sections
        """
        # Create division node
        division_node = CobolDivision("DATA", start_location)

        # Create sections as parsed
        section_map = {
            "file": "FILE",
            "working_storage": "WORKING-STORAGE",
            "local_storage": "LOCAL-STORAGE",
            "linkage": "LINKAGE",
        }

        for key, section_name in section_map.items():
            if key in division_content:
                section_content = division_content[key]
                section_location = (
                    section_content.get("location", start_location)
                    if isinstance(section_content, dict)
                    else start_location
                )
                section = CobolSection(section_name, section_location)

                # Add parsed data items to section
                if (
                    isinstance(division_content[key], dict)
                    and "data_items" in division_content[key]
                ):
                    for data_item in division_content[key]["data_items"]:
                        if isinstance(data_item, CobolDataItem):
                            section.add_data_item(data_item)
                        elif isinstance(data_item, RenamesItem):
                            # RenamesItem is not a CobolDataItem but must be in the AST tree
                            section.add_child(data_item)
                    # EXEC SQL blocks (DECLARE TABLE, INCLUDE SQLCA, etc.)
                    for sql_node in division_content[key].get("exec_sql_items", []):
                        section.add_child(sql_node)

                division_node.add_section(section)

        # Store metadata
        division_node.metadata.update(
            {
                "has_file": "file" in division_content,
                "has_working_storage": "working_storage" in division_content,
                "has_local_storage": "local_storage" in division_content,
                "has_linkage": "linkage" in division_content,
            }
        )

        return division_node
