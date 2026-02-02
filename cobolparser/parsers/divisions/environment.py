"""Environment Division parser for COBOL programs.

This module implements parsing of the Environment Division which contains:
- CONFIGURATION SECTION: Compiler options and configurations
- INPUT-OUTPUT SECTION: File control and I/O definitions
"""

from typing import Dict, Any

from cobolparser.core.interfaces import ITokenStream
from cobolparser.models.ast_base import ASTNode, SourceLocation
from cobolparser.models.program import CobolDivision, CobolSection
from .base import BaseDivisionParser


class EnvironmentDivisionParser(BaseDivisionParser):
    """Parser for COBOL Environment Division.
    
    Handles extraction and parsing of environment configuration and I/O definitions.
    Processes CONFIGURATION SECTION and INPUT-OUTPUT SECTION.
    """

    division_name = "ENVIRONMENT"
    division_keywords = ()

    def parse_division(self, token_stream: ITokenStream) -> Dict[str, Any]:
        """Parse Environment Division content.
        
        Parses optional sections:
        - CONFIGURATION SECTION
        - INPUT-OUTPUT SECTION
        
        Args:
            token_stream: Token stream positioned after division header
            
        Returns:
            Dictionary containing parsed sections and their content
        """
        sections: Dict[str, Any] = {}
        
        # Parse sections until we reach next division or EOF
        while not token_stream.is_empty():
            token = token_stream.peek(0)
            if not token:
                break
            
            token_value = token.value.upper()
            
            # Check if we've reached next division
            if token_value in ("IDENTIFICATION", "DATA", "PROCEDURE"):
                break
            
            # Parse specific sections
            if token_value == "CONFIGURATION":
                sections["configuration"] = self._parse_configuration_section(token_stream)
            elif token_value == "INPUT-OUTPUT":
                sections["input_output"] = self._parse_input_output_section(token_stream)
            else:
                # Unknown section - skip it for error recovery
                token_stream.consume()
        
        return sections

    def _parse_configuration_section(self, token_stream: ITokenStream) -> Dict[str, Any]:
        """Parse CONFIGURATION SECTION.
        
        Format: CONFIGURATION SECTION. [configuration-content]
        
        Args:
            token_stream: Token stream positioned at CONFIGURATION keyword
            
        Returns:
            Dictionary containing configuration content
        """
        # Consume CONFIGURATION keyword
        token_stream.consume()
        
        # Skip remaining tokens until next SECTION or division
        section_keywords = {"SECTION", "INPUT-OUTPUT", "DATA", "PROCEDURE", "IDENTIFICATION"}
        while not token_stream.is_empty():
            token = token_stream.peek(0)
            if token and token.value.upper() in section_keywords:
                break
            token_stream.consume()
        
        return {"type": "configuration"}

    def _parse_input_output_section(self, token_stream: ITokenStream) -> Dict[str, Any]:
        """Parse INPUT-OUTPUT SECTION.
        
        Format: INPUT-OUTPUT SECTION. [io-content]
        
        Args:
            token_stream: Token stream positioned at INPUT-OUTPUT keyword
            
        Returns:
            Dictionary containing I/O definitions
        """
        # Consume INPUT-OUTPUT keyword
        token_stream.consume()
        
        # Skip remaining tokens until next SECTION or division
        section_keywords = {"SECTION", "CONFIGURATION", "DATA", "PROCEDURE", "IDENTIFICATION"}
        while not token_stream.is_empty():
            token = token_stream.peek(0)
            if token and token.value.upper() in section_keywords:
                break
            token_stream.consume()
        
        return {"type": "input_output"}

    def _create_ast_node(
        self,
        division_token,
        division_content: Dict[str, Any],
        start_location: SourceLocation
    ) -> ASTNode:
        """Create AST node for Environment Division.
        
        Creates a CobolDivision node with environment metadata.
        
        Args:
            division_token: The ENVIRONMENT token
            division_content: Parsed content from parse_division()
            start_location: Start location for the AST node
            
        Returns:
            CobolDivision AST node with environment metadata
        """
        # Create division node
        division_node = CobolDivision("ENVIRONMENT", start_location)
        
        # Store environment metadata
        division_node._metadata.update({
            "has_configuration": "configuration" in division_content,
            "has_input_output": "input_output" in division_content,
        })
        
        # Create sections if content was parsed
        if "configuration" in division_content:
            config_section = CobolSection("CONFIGURATION", start_location)
            division_node.add_section(config_section)
        
        if "input_output" in division_content:
            io_section = CobolSection("INPUT-OUTPUT", start_location)
            division_node.add_section(io_section)
        
        return division_node

