"""Data Division parser for COBOL programs.

This module implements parsing of the Data Division which contains:
- FILE SECTION: File descriptions and records
- WORKING-STORAGE SECTION: Working variable definitions
- LOCAL-STORAGE SECTION: Local variable definitions
- LINKAGE SECTION: Program parameter definitions
"""

from typing import Dict, Any, Optional

from cobolparser.core.interfaces import ITokenStream
from cobolparser.lexer import TokenType
from cobolparser.models.ast_base import ASTNode, SourceLocation
from cobolparser.models.program import CobolDivision, CobolSection
from cobolparser.models.data_items import CobolDataItem, PictureClause
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
            Dictionary containing section content with parsed data items
        """
        # Consume section keyword
        token_stream.consume()
        
        # Consume 'SECTION' keyword if present
        if token_stream.peek() and token_stream.peek().value.upper() == "SECTION":
            token_stream.consume()
        
        # Consume period if present
        if token_stream.peek() and token_stream.peek().type == TokenType.PERIOD:
            token_stream.consume()
        
        # Parse data items until we reach next section or division
        data_items = []
        section_keywords = {"SECTION", "FILE", "WORKING-STORAGE", "LOCAL-STORAGE", "LINKAGE",
                           "DATA", "PROCEDURE", "ENVIRONMENT", "IDENTIFICATION"}
        division_token_types = {TokenType.IDENTIFICATION_DIVISION, TokenType.ENVIRONMENT_DIVISION, 
                               TokenType.DATA_DIVISION, TokenType.PROCEDURE_DIVISION}
        paren_depth = 0  # Track nesting depth of parentheses
        
        while not token_stream.is_empty():
            token = token_stream.peek()
            if not token:
                break
            
            # Check if we've reached next section/division (by token type, not just value check)
            if token.type in division_token_types:
                break
            
            # Also check for section keywords that appear as identifiers
            if token.value and token.value.upper() in section_keywords and token.type != TokenType.IDENTIFIER:
                break
            
            # Track parentheses depth to avoid treating numbers inside parens as level numbers
            if token.value and token.value == "(":
                paren_depth += 1
                token_stream.consume()
                continue
            elif token.value and token.value == ")":
                paren_depth -= 1
                token_stream.consume()
                continue
            
            # Try to parse a data item (should start with level number, but not inside parentheses)
            if token.type == TokenType.LEVEL_NUMBER and paren_depth == 0:
                data_item = self._parse_data_item(token_stream)
                if data_item:
                    data_items.append(data_item)
            else:
                # Skip unexpected tokens
                token_stream.consume()
        
        # Build hierarchical structure based on level numbers
        hierarchical_items = self._build_data_hierarchy(data_items)
        
        return {
            "type": section_name.lower().replace("-", "_"),
            "data_items": hierarchical_items
        }    
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
        
        top_level_items = []
        stack = []  # Stack of (level, item) pairs
        
        for item in data_items:
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
    def _parse_data_item(self, token_stream: ITokenStream) -> Optional[CobolDataItem]:
        """Parse a single data item definition.
        
        Format: level-number data-name [clauses].
        
        Args:
            token_stream: Token stream positioned at level number
            
        Returns:
            CobolDataItem or None if parsing fails
        """
        token = token_stream.peek()
        if not token or token.type != TokenType.LEVEL_NUMBER:
            return None
        
        try:
            level = int(token.value)
        except (ValueError, AttributeError):
            return None
        
        location = token.location
        token_stream.consume()  # Consume level number
        
        # Get data name
        name = None
        token = token_stream.peek()
        
        if token and token.type == TokenType.IDENTIFIER:
            name = token.value
            token_stream.consume()
        elif token and token.value and token.value.upper() in ["FILLER"]:
            name = "FILLER"
            token_stream.consume()
        else:
            # Anonymous data item
            name = f"ANONYMOUS-{level}-{location.line}" if hasattr(location, 'line') else f"ANONYMOUS-{level}"
        
        # Create data item
        data_item = CobolDataItem(name, level, location)
        
        # Parse clauses until period or next item
        while not token_stream.is_empty():
            token = token_stream.peek()
            if not token:
                break
            
            # Period ends this data item
            if token.type == TokenType.PERIOD:
                token_stream.consume()
                break
            
            # Level number starts next item
            if token.type == TokenType.LEVEL_NUMBER:
                break
            
            # Division tokens end this data item (don't consume them)
            if token.type in (TokenType.IDENTIFICATION_DIVISION, TokenType.ENVIRONMENT_DIVISION,
                             TokenType.DATA_DIVISION, TokenType.PROCEDURE_DIVISION):
                break
            
            #  PICTURE/PIC clause
            if token.value and token.value.upper() in ["PICTURE", "PIC"]:
                token_stream.consume()  # Consume PIC keyword
                picture_pattern = self._parse_picture_clause(token_stream)
                if picture_pattern:
                    data_item.set_picture_clause(PictureClause(picture_pattern, location))
            
            # VALUE clause
            elif token.value and token.value.upper() == "VALUE":
                token_stream.consume()  # Consume VALUE keyword
                value = self._parse_value_clause(token_stream)
                if value:
                    data_item.set_value_clause(value)
            
            # USAGE clause
            elif token.value and token.value.upper() == "USAGE":
                token_stream.consume()  # Consume USAGE keyword
                usage = self._parse_usage_clause(token_stream)
                if usage:
                    data_item.set_usage(usage)
            
            # COMP, COMP-3, etc. without USAGE keyword
            elif token.value and token.value.upper() in ["COMP", "COMP-1", "COMP-2", "COMP-3", "COMP-4", "COMP-5"]:
                data_item.set_usage(token.value.upper())
                token_stream.consume()
            
            # Also check for COMP token types (COMP_1, COMP_2, COMP_3, etc.)
            elif token.type in [TokenType.COMP_1, TokenType.COMP_2, TokenType.COMP_3, TokenType.COMP_4, TokenType.COMP_5]:
                data_item.set_usage(token.value.upper())
                token_stream.consume()
            
            # REDEFINES clause
            elif token.value and token.value.upper() == "REDEFINES":
                token_stream.consume()  # Consume REDEFINES keyword
                redef_token = token_stream.peek()
                if redef_token and redef_token.type == TokenType.IDENTIFIER:
                    data_item.set_redefines(redef_token.value)
                    token_stream.consume()
            
            # OCCURS clause
            elif token.value and token.value.upper() == "OCCURS":
                token_stream.consume()  # Consume OCCURS keyword
                # Skip OCCURS details for now
                while token_stream.peek() and token_stream.peek().type not in [TokenType.PERIOD, TokenType.LEVEL_NUMBER]:
                    next_token = token_stream.peek()
                    if next_token.value and next_token.value.upper() in ["PIC", "PICTURE", "VALUE", "USAGE"]:
                        break
                    token_stream.consume()
            
            else:
                # Skip unknown tokens/clauses
                if token.type == TokenType.NEWLINE:
                    token_stream.consume()
                elif token.type in (TokenType.IDENTIFICATION_DIVISION, TokenType.ENVIRONMENT_DIVISION,
                                   TokenType.DATA_DIVISION, TokenType.PROCEDURE_DIVISION):
                    # Never consume division tokens
                    break
                elif token.type not in [TokenType.PERIOD, TokenType.LEVEL_NUMBER]:
                    token_stream.consume()
                else:
                    break
        
        return data_item
    
    def _parse_picture_clause(self, token_stream: ITokenStream) -> Optional[str]:
        """Parse PICTURE clause pattern.
        
        Returns the picture pattern string (e.g., 'X(10)', '9(5)', '9(7)V99').
        """
        pattern_parts = []
        paren_depth = 0  # Track parenthesis nesting
        
        while not token_stream.is_empty():
            token = token_stream.peek()
            if not token:
                break
            
            # Stop at specific keywords when outside parentheses
            if paren_depth == 0:
                if token.type == TokenType.PERIOD:
                    break
                # Stop at keywords that follow picture clause
                if token.value and token.value.upper() in ["VALUE", "USAGE", "OCCURS", "REDEFINES", 
                                                            "COMP", "COMP-1", "COMP-2", "COMP-4", "COMP-5"]:
                    break
                # Also stop at COMP token types
                if token.type in [TokenType.COMP_1, TokenType.COMP_2, TokenType.COMP_3, TokenType.COMP_4, TokenType.COMP_5]:
                    break
            
            # Collect picture pattern tokens
            if token.type in [TokenType.IDENTIFIER, TokenType.NUMERIC_LITERAL, TokenType.STRING_LITERAL, TokenType.LEVEL_NUMBER]:
                # All these token types can be part of a picture pattern
                pattern_parts.append(token.value)
                token_stream.consume()
            elif token.value == "(":
                pattern_parts.append(token.value)
                paren_depth += 1
                token_stream.consume()
            elif token.value == ")":
                pattern_parts.append(token.value)
                paren_depth -= 1
                token_stream.consume()
            elif token.value == ",":
                pattern_parts.append(token.value)
                token_stream.consume()
            elif token.type == TokenType.NEWLINE:
                token_stream.consume()
            else:
                break
        
        result = "".join(pattern_parts) if pattern_parts else None
        return result
    
    def _parse_value_clause(self, token_stream: ITokenStream) -> Optional[str]:
        """Parse VALUE clause value.
        
        Returns the value string.
        """
        token = token_stream.peek()
        if not token:
            return None
        
        if token.type in [TokenType.STRING_LITERAL, TokenType.NUMERIC_LITERAL, TokenType.FIGURATIVE_CONSTANT]:
            value = token.value
            token_stream.consume()
            return value
        elif token.type == TokenType.IDENTIFIER:
            value = token.value
            token_stream.consume()
            return value
        
        return None
    
    def _parse_usage_clause(self, token_stream: ITokenStream) -> Optional[str]:
        """Parse USAGE clause value.
        
        Returns the usage type (e.g., COMP-3, COMP-5, DISPLAY).
        """
        token = token_stream.peek()
        if not token:
            return None
        
        # Check for COMP token types first (COMP_1, COMP_2, etc.)
        if token.type in [TokenType.COMP_1, TokenType.COMP_2, TokenType.COMP_3, TokenType.COMP_4, TokenType.COMP_5]:
            usage = token.value.upper()
            token_stream.consume()
            return usage
        
        # Check for regular IDENTIFIER
        if token.type == TokenType.IDENTIFIER:
            usage = token.value.upper()
            token_stream.consume()
            return usage
        
        # Check for COMP variations that are tokenized differently
        if token.value and token.value.upper() in ["COMP", "COMP-1", "COMP-2", "COMP-3", "COMP-4", "COMP-5"]:
            usage = token.value.upper()
            token_stream.consume()
            return usage
        
        return None

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
                
                # Add parsed data items to section
                if isinstance(division_content[key], dict) and "data_items" in division_content[key]:
                    for data_item in division_content[key]["data_items"]:
                        if isinstance(data_item, CobolDataItem):
                            section.add_data_item(data_item)
                
                division_node.add_section(section)
        
        # Store metadata
        division_node._metadata.update({
            "has_file": "file" in division_content,
            "has_working_storage": "working_storage" in division_content,
            "has_local_storage": "local_storage" in division_content,
            "has_linkage": "linkage" in division_content,
        })
        
        return division_node

