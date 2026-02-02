"""Data Division parser for COBOL programs.

This module implements parsing of the Data Division which contains:
- FILE SECTION: File descriptions and records
- WORKING-STORAGE SECTION: Working variable definitions
- LOCAL-STORAGE SECTION: Local variable definitions
- LINKAGE SECTION: Program parameter definitions
"""

from typing import Dict, Any

from cobolparser.core.interfaces import ITokenStream
from cobolparser.models.ast_base import ASTNode, SourceLocation
from cobolparser.models.program import CobolDivision, CobolSection
from .base import BaseDivisionParser


class DataDivisionParser(BaseDivisionParser):
    """Parser for COBOL Data Division.
    
    Handles data structure definitions with section support.
    Supports FILE, WORKING-STORAGE, LOCAL-STORAGE, and LINKAGE sections.
    """

    division_name = "DATA"
    division_keywords = ()

    def parse_division(self, token_stream: ITokenStream) -> Dict[str, Any]:
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
        sections: Dict[str, Any] = {}
        
        # Parse sections until we reach next division or EOF
        while not token_stream.is_empty():
            token = token_stream.peek(0)
            if not token:
                break
            
            token_value = token.value.upper()
            
            # Check if we've reached next division
            if token_value in ("IDENTIFICATION", "ENVIRONMENT", "PROCEDURE"):
                break
            
            # Parse specific sections
            if token_value == "FILE":
                sections["file"] = self._parse_section(token_stream, "FILE")
            elif token_value == "WORKING-STORAGE":
                sections["working_storage"] = self._parse_section(token_stream, "WORKING-STORAGE")
            elif token_value == "LOCAL-STORAGE":
                sections["local_storage"] = self._parse_section(token_stream, "LOCAL-STORAGE")
            elif token_value == "LINKAGE":
                sections["linkage"] = self._parse_section(token_stream, "LINKAGE")
            else:
                # Unknown section - skip it for error recovery
                token_stream.consume()
        
        return sections

    def _parse_section(self, token_stream: ITokenStream, section_name: str) -> Dict[str, Any]:
        """Parse a data section.
        
        Format: SECTION-NAME SECTION. [data-items]
        
        Args:
            token_stream: Token stream positioned at section keyword
            section_name: Name of the section (FILE, WORKING-STORAGE, etc.)
            
        Returns:
            Dictionary containing section content
        """
        # Consume section keyword
        token_stream.consume()
        
        # Skip remaining tokens until next SECTION or division
        section_keywords = {"SECTION", "FILE", "WORKING-STORAGE", "LOCAL-STORAGE", "LINKAGE",
                           "DATA", "PROCEDURE", "ENVIRONMENT", "IDENTIFICATION"}
        while not token_stream.is_empty():
            token = token_stream.peek(0)
            if token and token.value.upper() in section_keywords:
                break
            token_stream.consume()
        
        return {"type": section_name.lower().replace("-", "_")}

    def _create_ast_node(
        self,
        division_token,
        division_content: Dict[str, Any],
        start_location: SourceLocation
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
            "linkage": "LINKAGE"
        }
        
        for key, section_name in section_map.items():
            if key in division_content:
                section = CobolSection(section_name, start_location)
                division_node.add_section(section)
        
        # Store metadata
        division_node._metadata.update({
            "has_file": "file" in division_content,
            "has_working_storage": "working_storage" in division_content,
            "has_local_storage": "local_storage" in division_content,
            "has_linkage": "linkage" in division_content,
        })
        
        return division_node

