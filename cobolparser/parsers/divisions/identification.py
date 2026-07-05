"""Identification Division parser for COBOL programs.

This module implements parsing of the Identification Division which contains:
- PROGRAM-ID: Program name (mandatory)
- AUTHOR: Author information (optional)
- INSTALLATION: Installation details (optional)
- DATE-WRITTEN: Write date (optional)
- DATE-COMPILED: Compile date (optional)
- REMARKS: Free-form remarks (optional)
- SECURITY: Security level (optional)
"""

from typing import Any

from cobolparser.core.exceptions import ParseError, TokenMismatch
from cobolparser.core.interfaces import ITokenStream
from cobolparser.models.ast_base import ASTNode, SourceLocation
from cobolparser.models.program import CobolDivision

from .base import BaseDivisionParser, at_division_boundary


class IdentificationDivisionParser(BaseDivisionParser):
    """Parser for COBOL Identification Division.

    Handles extraction and parsing of program identification metadata including
    PROGRAM-ID, AUTHOR, INSTALLATION, DATE-WRITTEN, DATE-COMPILED, REMARKS,
    and SECURITY clauses.

    Implements the parse_division() and _create_ast_node() abstract methods
    from BaseDivisionParser.
    """

    division_name: str | None = "IDENTIFICATION"
    division_keywords: tuple = ("ID",)

    def parse_division(self, token_stream: ITokenStream) -> dict[str, str | None]:
        """Parse Identification Division content.

        Parses all identification clauses (PROGRAM-ID is mandatory, others optional):
        - PROGRAM-ID. value.
        - AUTHOR. value.
        - INSTALLATION. value.
        - DATE-WRITTEN. value.
        - DATE-COMPILED. value.
        - REMARKS. value.
        - SECURITY. value.

        Args:
            token_stream: Token stream positioned after division header

        Returns:
            Dictionary containing parsed identification metadata with keys:
            - program_id: str (always present)
            - author: Optional[str]
            - installation: Optional[str]
            - date_written: Optional[str]
            - date_compiled: Optional[str]
            - remarks: Optional[str]
            - security: Optional[str]
        """
        content: dict[str, str | None] = {
            "program_id": None,
            "author": None,
            "installation": None,
            "date_written": None,
            "date_compiled": None,
            "remarks": None,
            "security": None,
        }

        # Parse clauses until we reach next division or EOF
        while not token_stream.is_empty():
            token = token_stream.peek(0)
            if not token:
                break

            token_value = token.value.upper()

            # Check if we've reached the next division. A bare keyword such
            # as DATA only counts when actually followed by DIVISION — the
            # word may appear inside a comment-entry.
            if at_division_boundary(token_stream):
                break

            # Parse specific clauses
            if token_value == "PROGRAM-ID":
                content["program_id"] = self._parse_program_id(token_stream)
            elif token_value == "AUTHOR":
                content["author"] = self._parse_clause_value(token_stream)
            elif token_value == "INSTALLATION":
                content["installation"] = self._parse_clause_value(token_stream)
            elif token_value == "DATE-WRITTEN":
                content["date_written"] = self._parse_clause_value(token_stream)
            elif token_value == "DATE-COMPILED":
                content["date_compiled"] = self._parse_clause_value(token_stream)
            elif token_value == "REMARKS":
                content["remarks"] = self._parse_clause_value(token_stream)
            elif token_value == "SECURITY":
                content["security"] = self._parse_clause_value(token_stream)
            else:
                # Unknown clause - skip it for error recovery
                token_stream.consume()

        # Validate mandatory PROGRAM-ID
        if not content["program_id"]:
            raise ParseError("PROGRAM-ID is mandatory in IDENTIFICATION DIVISION")

        return content

    def _parse_program_id(self, token_stream: ITokenStream) -> str:
        """Parse PROGRAM-ID clause.

        Format: PROGRAM-ID. program-name [IS INITIAL|COMMON].

        In fixed-format COBOL, the elements may be on different lines:
            000200 PROGRAM-ID.
            000300     program-name.

        Supports optional IS INITIAL or IS COMMON clauses for IBM Enterprise COBOL.

        Args:
            token_stream: Token stream positioned at PROGRAM-ID keyword

        Returns:
            Program name extracted from clause

        Raises:
            ParseError: If PROGRAM-ID syntax is invalid
        """
        # Consume PROGRAM-ID keyword
        token_stream.consume()

        # Expect period after PROGRAM-ID
        try:
            token_stream.expect(".")
        except TokenMismatch as e:
            _t147 = token_stream.peek(0)
            raise ParseError(
                "Expected '.' after PROGRAM-ID keyword",
                line_number=(
                    (_t147.location.line if _t147 is not None else 1)
                    if not token_stream.is_empty()
                    else 1
                ),
            ) from e

        # Skip newlines and whitespace after the period (for fixed-format COBOL)
        token_stream.skip_whitespace_and_comments()

        # Get program name (next non-period token)
        if token_stream.is_empty():
            raise ParseError("Expected program name after PROGRAM-ID.")

        name_token = token_stream.consume()
        program_name = name_token.value

        # Check for optional repeated IS INITIAL / IS COMMON clauses.
        token_stream.skip_whitespace_and_comments()
        while not token_stream.is_empty():
            token = token_stream.peek(0)
            if not token or not token.value or token.value.upper() != "IS":
                break

            token_stream.consume()
            token_stream.skip_whitespace_and_comments()

            if token_stream.is_empty():
                break

            next_token = token_stream.peek(0)
            if not next_token or not next_token.value:
                break

            val = next_token.value.upper()
            if val in ("INITIAL", "COMMON"):
                token_stream.consume()
                token_stream.skip_whitespace_and_comments()
                continue
            break

        # Expect period after program name (or after IS clause if present)
        try:
            token_stream.expect(".")
        except TokenMismatch as e:
            raise ParseError(
                f"Expected '.' after program name '{program_name}'",
                line_number=name_token.location.line,
            ) from e

        return program_name

    def _parse_clause_value(self, token_stream: ITokenStream) -> str:
        """Parse a general clause value.

        Format: CLAUSE-KEYWORD. value-text.

        Collects all tokens between the keyword and period as the clause value.

        Args:
            token_stream: Token stream positioned at clause keyword

        Returns:
            Clause value as a string

        Raises:
            ParseError: If clause syntax is invalid
        """
        # Consume clause keyword (AUTHOR, INSTALLATION, etc.)
        token_stream.consume()

        # Expect period after clause keyword
        try:
            token_stream.expect(".")
        except TokenMismatch as e:
            _t220 = token_stream.peek(0)
            raise ParseError(
                "Expected '.' after clause keyword",
                line_number=(
                    (_t220.location.line if _t220 is not None else 1)
                    if not token_stream.is_empty()
                    else 1
                ),
            ) from e

        # Collect value tokens until period
        # Also stop at division boundaries to avoid consuming the next division header
        value_tokens = []
        while not token_stream.is_empty():
            token = token_stream.peek(0)
            if token and token.value == ".":
                token_stream.consume()
                break
            # Stop at division boundaries without consuming them. A bare
            # keyword such as DATA only counts when actually followed by
            # DIVISION — comment-entries are free text and may contain it.
            if token and at_division_boundary(token_stream):
                break
            if token:
                value_tokens.append(token.value)
                token_stream.consume()
            else:
                break

        # Return collected value or empty string
        return " ".join(value_tokens) if value_tokens else ""

    def _create_ast_node(
        self,
        division_token: Any,
        division_content: dict[str, Any],
        start_location: SourceLocation,
    ) -> ASTNode:
        """Create AST node for Identification Division.

        Creates a CobolDivision node with metadata from parsed content.

        Args:
            division_token: The IDENTIFICATION token
            division_content: Parsed content from parse_division()
            start_location: Start location for the AST node

        Returns:
            CobolDivision AST node with identification metadata
        """
        # Create division node
        division_node = CobolDivision("IDENTIFICATION", start_location)

        # Store identification metadata in division metadata
        division_node.metadata.update(
            {
                "program_id": division_content.get("program_id"),
                "author": division_content.get("author"),
                "installation": division_content.get("installation"),
                "date_written": division_content.get("date_written"),
                "date_compiled": division_content.get("date_compiled"),
                "remarks": division_content.get("remarks"),
                "security": division_content.get("security"),
            }
        )

        return division_node
