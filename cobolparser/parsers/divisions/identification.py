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

from typing import Dict, Any, Optional

from cobolparser.core.interfaces import ITokenStream
from cobolparser.core.exceptions import ParseError, TokenMismatch
from cobolparser.models.ast_base import ASTNode, SourceLocation
from cobolparser.models.program import CobolDivision
from cobolparser.lexer import TokenType
from .base import BaseDivisionParser


class IdentificationDivisionParser(BaseDivisionParser):
    """Parser for COBOL Identification Division.
    
    Handles extraction and parsing of program identification metadata including
    PROGRAM-ID, AUTHOR, INSTALLATION, DATE-WRITTEN, DATE-COMPILED, REMARKS,
    and SECURITY clauses.
    
    Implements the parse_division() and _create_ast_node() abstract methods
    from BaseDivisionParser.
    """

    division_name = "IDENTIFICATION"
    division_keywords = ("ID",)

    def parse_division(self, token_stream: ITokenStream) -> Dict[str, Optional[str]]:
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
        content: Dict[str, Optional[str]] = {
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
            
            # Check if we've reached next division
            # Handle both bare keywords ("ENVIRONMENT") and composite tokens
            # ("ENVIRONMENT DIVISION") produced by the lexer in free-form mode
            _div_keywords = ("ENVIRONMENT", "DATA", "PROCEDURE")
            if token_value in _div_keywords:
                break
            if any(
                token_value == f"{kw} DIVISION" for kw in _div_keywords
            ):
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
            raise ParseError(
                "PROGRAM-ID is mandatory in IDENTIFICATION DIVISION"
            )
        
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
        except TokenMismatch:
            raise ParseError(
                "Expected '.' after PROGRAM-ID keyword",
                token_stream.peek(0).location.line if not token_stream.is_empty() else 1
            )
        
        # Skip newlines and whitespace after the period (for fixed-format COBOL)
        token_stream.skip_whitespace_and_comments()
        
        # Get program name (next non-period token)
        if token_stream.is_empty():
            raise ParseError("Expected program name after PROGRAM-ID.")
        
        name_token = token_stream.consume()
        program_name = name_token.value
        
        # Check for optional IS INITIAL or IS COMMON clause (IBM Enterprise COBOL)
        token_stream.skip_whitespace_and_comments()
        if not token_stream.is_empty():
            token = token_stream.peek(0)
            if token and token.value and token.value.upper() == "IS":
                token_stream.consume()  # consume IS
                token_stream.skip_whitespace_and_comments()
                
                if not token_stream.is_empty():
                    next_token = token_stream.peek(0)
                    if next_token and next_token.value:
                        val = next_token.value.upper()
                        if val in ("INITIAL", "COMMON"):
                            # Store the modifier (could be extended in future)
                            token_stream.consume()  # consume INITIAL or COMMON
        
        # Expect period after program name (or after IS clause if present)
        try:
            token_stream.expect(".")
        except TokenMismatch:
            raise ParseError(
                f"Expected '.' after program name '{program_name}'",
                name_token.location.line
            )
        
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
        except TokenMismatch:
            raise ParseError(
                "Expected '.' after clause keyword",
                token_stream.peek(0).location.line if not token_stream.is_empty() else 1
            )
        
        # Collect value tokens until period
        # Also stop at division boundaries to avoid consuming the next division header
        value_tokens = []
        _div_keywords = ("IDENTIFICATION", "ENVIRONMENT", "DATA", "PROCEDURE")
        while not token_stream.is_empty():
            token = token_stream.peek(0)
            if token and token.value == ".":
                token_stream.consume()
                break
            # Stop at division boundaries without consuming them
            if token:
                tv = token.value.upper()
                if tv in _div_keywords:
                    break
                if any(tv == f"{kw} DIVISION" for kw in _div_keywords):
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
        division_token,
        division_content: Dict[str, Any],
        start_location: SourceLocation
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
        division_node._metadata.update({
            "program_id": division_content.get("program_id"),
            "author": division_content.get("author"),
            "installation": division_content.get("installation"),
            "date_written": division_content.get("date_written"),
            "date_compiled": division_content.get("date_compiled"),
            "remarks": division_content.get("remarks"),
            "security": division_content.get("security"),
        })
        
        return division_node
