"""Base division parser class for COBOL parser refactoring.

This module provides the abstract base class for all division parsers,
establishing the contract that all division-specific parsers must follow.
"""

from abc import ABC, abstractmethod
from typing import Optional, Dict, Any

from cobolparser.core.interfaces import ITokenStream, IDivisionParser
from cobolparser.core.exceptions import ParseError, DivisionNotFoundError
from cobolparser.models.ast_base import ASTNode, SourceLocation
from cobolparser.lexer import TokenType


class BaseDivisionParser(IDivisionParser, ABC):
    """Abstract base class for COBOL division parsers.
    
    Implements IDivisionParser interface and provides common functionality
    for all division-specific parsers. Each subclass must implement:
    - division_name: The COBOL division keyword(s)
    - parse_division(): The division-specific parsing logic
    - _create_ast_node(): Create appropriate AST node for this division
    """

    # Must be set by subclasses
    division_name: str = None  # e.g., "IDENTIFICATION", "DATA", "PROCEDURE"
    division_keywords: tuple = ()  # e.g., ("IDENTIFICATION", "ID")
    
    def __init__(self):
        """Initialize the base division parser."""
        if not self.division_name:
            raise ValueError(
                f"{self.__class__.__name__} must set division_name class attribute"
            )

    def can_parse(self, token_stream: ITokenStream) -> bool:
        """Check if token stream starts with this division keyword.
        
        Args:
            token_stream: Token stream to check
            
        Returns:
            True if next token matches division keyword, False otherwise
        """
        if token_stream.is_empty():
            return False
        
        next_token = token_stream.peek(0)
        if not next_token:
            return False
        
        # Check if token matches any of the division keywords
        token_value = next_token.value.upper()
        division_keywords = (self.division_name,) + self.division_keywords
        
        return token_value in division_keywords

    def parse(self, token_stream: ITokenStream) -> ASTNode:
        """Parse a complete COBOL division.
        
        The division syntax follows:
            DIVISION-KEYWORD [DIVISION] .
            [optional-sections-and-content]
        
        Args:
            token_stream: Token stream to parse from
            
        Returns:
            AST node representing the parsed division
            
        Raises:
            DivisionNotFoundError: If expected division keyword not found
            ParseError: Any other parsing error
        """
        if not self.can_parse(token_stream):
            first_token = token_stream.peek(0)
            token_value = first_token.value if first_token else "EOF"
            raise DivisionNotFoundError(
                f"Expected {self.division_name} division, got {token_value}",
                first_token.location if first_token else SourceLocation(1, 1)
            )
        
        # Consume division keyword
        division_token = token_stream.consume()
        start_location = division_token.location
        
        # Check for optional "DIVISION" keyword
        if not token_stream.is_empty():
            next_token = token_stream.peek(0)
            if next_token and next_token.value.upper() == "DIVISION":
                token_stream.consume()
        
        # Expect period (.) after division header
        try:
            token_stream.expect(".")
        except Exception as e:
            raise ParseError(
                f"Expected '.' after {self.division_name} DIVISION header",
                division_token.location.line,
                division_token.location.column
            ) from e
        
        # Parse division-specific content
        division_content = self.parse_division(token_stream)
        
        # Create and return AST node
        ast_node = self._create_ast_node(
            division_token,
            division_content,
            start_location
        )
        
        return ast_node

    @abstractmethod
    def parse_division(self, token_stream: ITokenStream) -> Dict[str, Any]:
        """Parse division-specific content.
        
        Must be implemented by subclasses to handle the specific content
        and structure of each division type.
        
        Args:
            token_stream: Token stream to parse from (positioned after division header)
            
        Returns:
            Dictionary containing parsed division content
        """
        pass

    @abstractmethod
    def _create_ast_node(
        self,
        division_token,
        division_content: Dict[str, Any],
        start_location: SourceLocation
    ) -> ASTNode:
        """Create AST node for this division.
        
        Must be implemented by subclasses to return appropriate AST node type.
        
        Args:
            division_token: The division keyword token
            division_content: Content parsed by parse_division()
            start_location: Start location for the AST node
            
        Returns:
            AST node representing the parsed division
        """
        pass

    def _skip_to_next_section_or_division(self, token_stream: ITokenStream) -> None:
        """Skip tokens until reaching next section or division.
        
        Utility method for error recovery: scans forward to find a SECTION keyword
        or another division keyword, allowing parsing to continue after errors.
        
        Args:
            token_stream: Token stream to scan
        """
        section_keywords = {
            "SECTION", "FILE", "WORKING-STORAGE", "LOCAL-STORAGE", "LINKAGE",
            "IDENTIFICATION", "ENVIRONMENT", "DATA", "PROCEDURE",
            "CONFIGURATION", "INPUT-OUTPUT"
        }
        
        while not token_stream.is_empty():
            token = token_stream.peek(0)
            if token and token.value.upper() in section_keywords:
                break
            token_stream.consume()
