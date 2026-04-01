"""Procedure Division parser for COBOL programs.

This module implements parsing of the Procedure Division which contains:
- Paragraphs and sections: Named executable units
- Statements: Program logic and control flow

Uses StatementParserRegistry for pluggable statement parsing and dispatch.
"""

from typing import Any

from cobolparser.core.interfaces import ITokenStream, ParseContext
from cobolparser.core.registry import StatementParserRegistry
from cobolparser.models.ast_base import ASTNode, SourceLocation
from cobolparser.models.program import CobolDivision, CobolParagraph, CobolSection
from cobolparser.parsers.statements import (
    AddStatementParser,
    CallStatementParser,
    CloseStatementParser,
    ComputeStatementParser,
    DeleteStatementParser,
    DisplayStatementParser,
    DivideStatementParser,
    EntryStatementParser,
    EvaluateStatementParser,
    ExecCicsStatementParser,
    ExecSqlStatementParser,
    GoStatementParser,
    IfStatementParser,
    MoveStatementParser,
    MultiplyStatementParser,
    OpenStatementParser,
    PerformStatementParser,
    ReadStatementParser,
    RewriteStatementParser,
    StartStatementParser,
    SubtractStatementParser,
)
from cobolparser.parsers.statements._utils import skip_whitespace
from cobolparser.parsers.statements.stop_parser import StopStatementParser
from cobolparser.parsers.statements.write_parser import WriteStatementParser

from .base import BaseDivisionParser


class ProcedureDivisionParser(BaseDivisionParser):
    """Parser for COBOL Procedure Division with registry-based statement parsing.

    Handles paragraphs, sections, and program logic statements using the
    StatementParserRegistry for pluggable statement type recognition and parsing.

    Supports PERFORM, IF, EVALUATE, MOVE, DISPLAY, arithmetic statements, and others.
    """

    division_name: str | None = "PROCEDURE"
    division_keywords: tuple = ()

    def __init__(self, host: Any = None) -> None:
        """Initialize Procedure Division parser with statement registry.

        Args:
            host: Parent parser (CobolParser) for creating ParseContext
        """
        super().__init__()
        self.host = host
        self._statement_registry = self._create_statement_registry()

    def set_host(self, host: Any) -> None:
        """Set the host parser after initialization.

        Args:
            host: Parent parser (CobolParser) for creating ParseContext
        """
        self.host = host

    def _create_statement_registry(self) -> StatementParserRegistry:
        """Create and populate statement registry with all available parsers.

        Registers statement parsers in priority order (first-match strategy).
        Order matters - more specific parsers should come before general ones.

        IBM Enterprise COBOL extensions (EXEC SQL, EXEC CICS) are registered first
        since they require multi-token lookahead matching.

        Returns:
            StatementParserRegistry with all statement parsers registered
        """
        registry = StatementParserRegistry()

        # IBM Enterprise COBOL extensions first - more specific matching
        registry.register(ExecSqlStatementParser())
        registry.register(ExecCicsStatementParser())

        # Core control flow statements - more specific first
        registry.register(IfStatementParser())
        registry.register(PerformStatementParser())
        registry.register(EvaluateStatementParser())

        # Statement types
        registry.register(DisplayStatementParser())
        registry.register(MoveStatementParser())
        registry.register(CallStatementParser())
        registry.register(StopStatementParser())
        registry.register(EntryStatementParser())
        registry.register(GoStatementParser())

        # IO statements
        registry.register(ReadStatementParser())
        registry.register(OpenStatementParser())
        registry.register(CloseStatementParser())
        registry.register(RewriteStatementParser())
        registry.register(DeleteStatementParser())
        registry.register(StartStatementParser())
        registry.register(WriteStatementParser())

        # Arithmetic statements
        registry.register(ComputeStatementParser())
        registry.register(AddStatementParser())
        registry.register(SubtractStatementParser())
        registry.register(MultiplyStatementParser())
        registry.register(DivideStatementParser())

        return registry

    def parse_division(self, token_stream: ITokenStream) -> dict[str, Any]:
        """Parse Procedure Division content using registry-based statement parsing.

        Parses paragraphs and sections containing executable statements.
        Each paragraph contains statements parsed using the StatementParserRegistry.

        Structure:
        - Paragraphs with or without sections
        - Each paragraph contains statements terminated by periods

        Args:
            token_stream: Token stream positioned after division header

        Returns:
            Dictionary containing parsed paragraphs, sections, and statements
        """
        procedures: dict[str, Any] = {}
        paragraphs: list[dict[str, Any]] = []
        sections: dict[str, Any] = {}

        # Skip initial whitespace and comments
        skip_whitespace(token_stream)

        # Parse paragraphs and sections until EOF
        while not token_stream.is_empty():
            # Skip whitespace/comments at start of each iteration
            skip_whitespace(token_stream)

            token = token_stream.peek(0)
            if not token:
                break

            token_value = token.value.upper() if token.value else ""

            # Check for next division start or END PROGRAM/DIVISION
            # Handle both bare keywords and composite tokens (e.g. "DATA DIVISION")
            _stop_div = ("IDENTIFICATION", "ENVIRONMENT", "DATA")
            if token_value in _stop_div:
                break
            if any(token_value == f"{kw} DIVISION" for kw in _stop_div):
                break

            # Check for END PROGRAM or END DIVISION
            if token_value == "END":
                next_token = token_stream.peek(1)
                if next_token and next_token.value and next_token.value.upper() in ("PROGRAM", "DIVISION"):
                    break

            # Skip stray control markers so following statements can be recovered.
            if token_value in ("ELSE", "WHEN", "END-IF", "END-PERFORM", "END-EVALUATE"):
                token_stream.consume()
                continue

            # Check for SECTION keyword
            if self._is_section_marker(token_stream):
                section_name = token.value or ""
                token_stream.consume()  # consume section name

                # Skip to SECTION keyword
                _ps = token_stream.peek(0)
                while not token_stream.is_empty() and _ps and _ps.value and _ps.value.upper() != "SECTION":
                    token_stream.consume()
                    _ps = token_stream.peek(0)

                if not token_stream.is_empty():
                    token_stream.consume()  # consume SECTION

                _pp = token_stream.peek(0)
                if not token_stream.is_empty() and _pp and _pp.value == ".":
                    token_stream.consume()  # consume period

                section_dict = {
                    "type": "section",
                    "name": section_name,
                    "paragraphs": []
                }
                sections[section_name] = section_dict

            elif self._is_statement_keyword(token_value):
                # This is a statement keyword without an explicit paragraph
                # Create implicit paragraph if needed (only if no paragraphs or last is named)
                if not paragraphs or not paragraphs[-1].get("_is_implicit_paragraph"):
                    # Create new implicit paragraph
                    para_dict = {
                        "type": "paragraph",
                        "name": "",  # Implicit paragraph has empty name
                        "location": token.location if hasattr(token, 'location') else SourceLocation(0, 0),
                        "statements": [],
                        "_is_implicit_paragraph": True
                    }
                    paragraphs.append(para_dict)

                # Try to parse the statement
                parser = self._statement_registry.find_parser(token_stream)
                if parser:
                    try:
                        # Attach registry to stream for nested statement parsing
                        if not hasattr(token_stream, '_registry'):
                            token_stream._registry = self._statement_registry  # type: ignore[attr-defined]

                        # Attach context to stream for error reporting
                        context = ParseContext(self.host, self._statement_registry)
                        token_stream.context = context
                        token_stream._context = context  # type: ignore[attr-defined]

                        statement = parser.parse(token_stream)
                        paragraphs[-1]["statements"].append({
                            "type": "statement",
                            "node_type": type(statement).__name__,
                            "statement": statement
                        })
                    except Exception:
                        # Skip to next statement on error
                        self._skip_to_next_statement(token_stream)
                else:
                    # No parser found, skip the statement
                    self._skip_to_next_statement(token_stream)

            elif token_value not in ("SECTION", "IDENTIFICATION", "ENVIRONMENT", "DATA", "END", "PROGRAM", "DIVISION"):
                # Treat as paragraph name (only if not a keyword)
                para_name = token_value
                para_location = token.location if hasattr(token, 'location') else SourceLocation(0, 0)
                token_stream.consume()  # consume paragraph name

                # Skip period after paragraph name if present
                _pn = token_stream.peek(0)
                if not token_stream.is_empty() and _pn and _pn.value == ".":
                    token_stream.consume()

                # Parse statements in paragraph until next paragraph/section or EOF
                statements = self._parse_paragraph_statements(token_stream)

                para_dict = {
                    "type": "paragraph",
                    "name": para_name,
                    "location": para_location,
                    "statements": statements,
                    "_is_implicit_paragraph": False
                }
                paragraphs.append(para_dict)
            else:
                token_stream.consume()

        # Clean up: remove empty implicit paragraphs at the end
        while paragraphs and paragraphs[-1].get("_is_implicit_paragraph") and not paragraphs[-1].get("statements"):
            paragraphs.pop()

        procedures["paragraphs"] = paragraphs
        procedures["sections"] = sections
        return procedures

    def _parse_paragraph_statements(self, token_stream: ITokenStream) -> list[dict[str, Any]]:
        """Parse all statements within a paragraph until next paragraph/section.

        Uses StatementParserRegistry to dispatch to appropriate statement parser.
        Collects statements until encountering:
        - Next paragraph (identifier followed by period)
        - Next section (identifier followed by SECTION)
        - End of stream

        Args:
            token_stream: Token stream positioned at start of statements

        Returns:
            List of parsed statement dictionaries
        """
        statements: list[dict[str, Any]] = []

        while not token_stream.is_empty():
            # Skip whitespace/comments
            skip_whitespace(token_stream)

            if token_stream.is_empty():
                break

            token = token_stream.peek(0)
            if not token:
                break

            # Check for next paragraph or section
            if self._is_paragraph_or_section_start(token_stream):
                break

            # Check for division end marker
            if token.value and token.value.upper() in ("END", "IDENTIFICATION", "ENVIRONMENT", "DATA"):
                break

            # Debug: Show what we're about to parse
            _DEBUG = False
            if _DEBUG:
                import sys
                print(f"DEBUG PROC: Looking for parser for token: {token.type.name} = {repr(token.value)}", file=sys.stderr)

            # Try to find and use statement parser
            parser = self._statement_registry.find_parser(token_stream)
            if parser:
                if _DEBUG:
                    import sys
                    print(f"DEBUG PROC: Found parser: {type(parser).__name__}", file=sys.stderr)
                try:
                    # Attach registry to stream for nested statement parsing
                    if not hasattr(token_stream, '_registry'):
                        token_stream._registry = self._statement_registry  # type: ignore[attr-defined]

                    # Attach context to stream for error reporting
                    context = ParseContext(self.host, self._statement_registry)
                    token_stream.context = context
                    token_stream._context = context  # type: ignore[attr-defined]

                    statement = parser.parse(token_stream)
                    statements.append({
                        "type": "statement",
                        "node_type": type(statement).__name__,
                        "statement": statement
                    })
                except Exception:
                    # If parsing fails, skip statement and continue
                    self._skip_to_next_statement(token_stream)
            elif token.value == ".":
                # Period terminates statement - consume it and continue
                token_stream.consume()
            else:
                if _DEBUG:
                    import sys
                    print(f"DEBUG PROC: No parser found for {token.type.name} = {repr(token.value)}", file=sys.stderr)
                # No parser found for this statement - skip it
                self._skip_to_next_statement(token_stream)

        return statements

    def _is_paragraph_or_section_start(self, token_stream: ITokenStream) -> bool:
        """Check if current position starts a new paragraph or section.

        A paragraph/section starts when an identifier is followed by either:
        - A period (paragraph end/start)
        - SECTION keyword (section definition)

        Handles the case where current position is at a period (end of previous
        paragraph), and next token is a paragraph name identifier.

        Args:
            token_stream: Token stream to check

        Returns:
            True if at paragraph/section start
        """
        if token_stream.is_empty():
            return False

        token = token_stream.peek(0)
        if not token:
            return False

        # Case 1: If current token is a PERIOD, check if the next token after it
        # is an IDENTIFIER (new paragraph name)
        if token.value == ".":
            # Skip the period and any whitespace/newlines
            next_idx = 1
            while next_idx < 10:  # Reasonable lookahead
                next_token = token_stream.peek(next_idx)
                if not next_token:
                    return False
                if next_token.type.name in ("NEWLINE", "WHITESPACE", "COMMENT"):
                    next_idx += 1
                    continue
                # Found a non-whitespace token
                if next_token.type.name == "IDENTIFIER":
                    # Check if it's followed by SECTION or a period (paragraph name pattern)
                    next_next_idx = next_idx + 1
                    while next_next_idx < 10:
                        next_next_token = token_stream.peek(next_next_idx)
                        if not next_next_token:
                            return True  # Assume it's a paragraph name
                        if next_next_token.type.name in ("NEWLINE", "WHITESPACE"):
                            next_next_idx += 1
                            continue
                        # Check for SECTION or period after identifier
                        if next_next_token.value == "." or (next_next_token.value and next_next_token.value.upper() == "SECTION"):
                            return True
                        break
                    return False
                return False
            return False

        # Case 2: Original logic - current token is an IDENTIFIER
        if token.type.name != 'IDENTIFIER':
            return False

        # Look ahead for SECTION or period
        next_token = token_stream.peek(1)
        if not next_token:
            return False

        if next_token.value == ".":
            return True

        if next_token.value and next_token.value.upper() == "SECTION":
            return True

        return False

    def _is_section_marker(self, token_stream: ITokenStream) -> bool:
        """Check if current token starts a section definition.

        A section marker is followed by SECTION keyword.

        Args:
            token_stream: Token stream to check

        Returns:
            True if current position marks a section start
        """
        if token_stream.is_empty():
            return False

        token = token_stream.peek(0)
        if not token:
            return False

        # Look ahead for SECTION keyword
        for offset in range(1, 3):
            next_tok = token_stream.peek(offset)
            if next_tok and next_tok.value.upper() == "SECTION":
                return True

        return False

    def _skip_to_next_statement(self, token_stream: ITokenStream) -> None:
        """Skip to start of next statement or paragraph.

        Skips tokens until finding a period (statement end) or
        a likely statement keyword.

        Args:
            token_stream: Token stream to advance
        """
        while not token_stream.is_empty():
            token = token_stream.peek(0)
            if not token:
                break

            if token.value == ".":
                token_stream.consume()
                break

            if self._is_paragraph_or_section_start(token_stream):
                break

            # Stop if we hit a statement keyword that has a registered parser.
            # Do NOT break for keywords (READ, OPEN, CLOSE, etc.) that have no
            # registered parser — consuming them is required to avoid an infinite
            # loop where _skip_to_next_statement keeps breaking on the same token.
            if token.value and self._is_statement_keyword(token.value):
                if self._statement_registry.find_parser(token_stream) is not None:
                    break

            token_stream.consume()

    @staticmethod
    def _is_statement_keyword(word: str) -> bool:
        """Check if word is a known statement keyword.

        Args:
            word: Word to check

        Returns:
            True if word is a statement keyword
        """
        keywords = {
            "DISPLAY", "MOVE", "IF", "PERFORM", "EVALUATE",
            "CALL", "ADD", "SUBTRACT", "MULTIPLY", "DIVIDE", "COMPUTE",
            "ACCEPT", "STOP", "EXIT", "GO", "GOBACK",
            "RETURN", "OPEN", "CLOSE", "READ", "WRITE", "DELETE",
            "SEARCH", "STRING", "UNSTRING", "INSPECT", "EXECUTE", "ENTRY"
        }
        return word.upper() in keywords

    def _create_ast_node(
        self,
        division_token: Any,
        division_content: dict[str, Any],
        start_location: SourceLocation
    ) -> ASTNode:
        """Create AST node for Procedure Division.

        Creates a CobolDivision node with paragraphs and sections containing parsed statements.

        Args:
            division_token: The PROCEDURE token
            division_content: Parsed content from parse_division()
            start_location: Start location for the AST node

        Returns:
            CobolDivision AST node with procedure structure and statements
        """
        # Create division node
        division_node = CobolDivision("PROCEDURE", start_location)

        # Add paragraphs with their statements
        for para_info in division_content.get("paragraphs", []):
            para = CobolParagraph(para_info.get("name", ""),
                                 para_info.get("location", start_location))

            # Add statements to paragraph
            for stmt_info in para_info.get("statements", []):
                if stmt_info.get("statement"):
                    para.add_statement(stmt_info["statement"])

            division_node.add_paragraph(para)

        # Add sections with their paragraphs
        for section_name, _section_info in division_content.get("sections", {}).items():
            section = CobolSection(section_name, start_location)
            division_node.add_section(section)

        # Store metadata
        division_node.metadata.update({
            "paragraph_count": len(division_content.get("paragraphs", [])),
            "section_count": len(division_content.get("sections", {})),
            "statement_count": sum(
                len(p.get("statements", [])) for p in division_content.get("paragraphs", [])
            ),
        })

        return division_node

