"""Environment Division parser for COBOL programs.

This module implements parsing of the Environment Division which contains:
- CONFIGURATION SECTION: Compiler options and configurations
- INPUT-OUTPUT SECTION: File control and I/O definitions
"""

from typing import Dict, Any, Optional, List

from cobolparser.core.interfaces import ITokenStream
from cobolparser.models.ast_base import ASTNode, SourceLocation
from cobolparser.models.program import CobolDivision, CobolSection, CobolParagraph
from cobolparser.models.statements import SelectStatement
from .base import BaseDivisionParser


class EnvironmentDivisionParser(BaseDivisionParser):
    """Parser for COBOL Environment Division.
    
    Handles extraction and parsing of environment configuration and I/O definitions.
    Processes CONFIGURATION SECTION and INPUT-OUTPUT SECTION.
    """

    division_name: Optional[str] = "ENVIRONMENT"
    division_keywords: tuple = ()

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
            # Handle both bare keywords and composite tokens (e.g. "DATA DIVISION")
            _stop_div = ("IDENTIFICATION", "DATA", "PROCEDURE")
            if token_value in _stop_div:
                break
            if any(token_value == f"{kw} DIVISION" for kw in _stop_div):
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
        _stop_div = ("DATA", "PROCEDURE", "IDENTIFICATION")
        while not token_stream.is_empty():
            token = token_stream.peek(0)
            if token and token.value.upper() in section_keywords:
                break
            if token and any(token.value.upper() == f"{kw} DIVISION" for kw in _stop_div):
                break
            token_stream.consume()
        
        return {"type": "configuration"}

    def _parse_input_output_section(self, token_stream: ITokenStream) -> Dict[str, Any]:
        """Parse INPUT-OUTPUT SECTION.
        
        Format: INPUT-OUTPUT SECTION. [io-content]
                FILE-CONTROL. [select-statements]
        
        Args:
            token_stream: Token stream positioned at INPUT-OUTPUT keyword
            
        Returns:
            Dictionary containing I/O definitions including SELECT statements
        """
        # Consume INPUT-OUTPUT keyword
        token_stream.consume()
        
        # Expect SECTION keyword
        token = token_stream.peek(0)
        if token and token.value.upper() == "SECTION":
            token_stream.consume()
        
        # Expect period
        token = token_stream.peek(0)
        if token and token.value == ".":
            token_stream.consume()
        
        # Parse FILE-CONTROL and other paragraphs
        select_statements: List[Dict[str, Any]] = []
        
        while not token_stream.is_empty():
            token = token_stream.peek(0)
            if not token:
                break
            
            token_value = token.value.upper()
            
            # Check if we've reached next SECTION or division
            _stop = ("CONFIGURATION", "DATA", "PROCEDURE", "IDENTIFICATION")
            if token_value in _stop:
                break
            if any(token_value == f"{kw} DIVISION" for kw in ("DATA", "PROCEDURE", "IDENTIFICATION")):
                break
            
            # Parse FILE-CONTROL paragraph (may appear as "NTROL" due to tokenizer)
            if token_value == "FILE-CONTROL" or token_value.endswith("CONTROL"):
                file_control_data = self._parse_file_control_paragraph(token_stream)
                select_statements.extend(file_control_data.get("selects", []))
            else:
                # Skip other content
                token_stream.consume()
        
        return {
            "type": "input_output",
            "select_statements": select_statements
        }

    def _parse_file_control_paragraph(self, token_stream: ITokenStream) -> Dict[str, Any]:
        """Parse FILE-CONTROL paragraph with SELECT statements.
        
        Format: FILE-CONTROL. [SELECT statements]
        
        Args:
            token_stream: Token stream positioned at FILE-CONTROL keyword
            
        Returns:
            Dictionary containing parsed SELECT statements
        """
        # Consume FILE-CONTROL keyword (may appear as "NTROL" due to tokenizer)
        token = token_stream.peek(0)
        if token and token.value.upper().endswith("CONTROL"):
            token_stream.consume()
        
        # Expect period
        token = token_stream.peek(0)
        if token and token.value == ".":
            token_stream.consume()
        
        # Parse SELECT statements
        select_statements: List[Dict[str, Any]] = []
        
        while not token_stream.is_empty():
            token = token_stream.peek(0)
            if not token:
                break
            
            token_value = token.value.upper()
            
            # Check for end of FILE-CONTROL (next section/division or paragraph)
            section_keywords = {"CONFIGURATION", "DATA", "PROCEDURE", "IDENTIFICATION", "FILE-CONTROL"}
            if token_value in section_keywords:
                break
            if any(token_value == f"{kw} DIVISION" for kw in ("DATA", "PROCEDURE", "IDENTIFICATION")):
                break
            
            # Parse SELECT statement (may appear as "ECT" due to tokenizer)
            if token_value == "SELECT" or token_value.startswith("ECT"):
                select_data = self._parse_select_statement(token_stream)
                if select_data:
                    select_statements.append(select_data)
            else:
                # Skip other tokens
                token_stream.consume()
        
        return {"selects": select_statements}

    def _parse_select_statement(self, token_stream: ITokenStream) -> Optional[Dict[str, Any]]:
        """Parse SELECT statement with comprehensive clause support.
        
        Supports:
        - SELECT [OPTIONAL] file-name
        - ASSIGN TO assignment-name/device-name/literal
        - ORGANIZATION IS SEQUENTIAL/INDEXED/RELATIVE/LINE SEQUENTIAL
        - ACCESS MODE IS SEQUENTIAL/RANDOM/DYNAMIC
        - RECORD KEY IS data-name
        - RELATIVE KEY IS data-name
        - FILE STATUS IS data-name
        
        Args:
            token_stream: Token stream positioned at SELECT keyword (may appear as "ECT")
            
        Returns:
            Dictionary containing parsed SELECT statement data
        """
        # Consume SELECT keyword (may appear as "ECT" due to tokenizer)
        token = token_stream.peek(0)
        if not token or (token.value.upper() != "SELECT" and not token.value.upper().endswith("ECT")):
            return None
        
        location = token.location
        token_stream.consume()
        
        # Skip newlines and whitespace
        while not token_stream.is_empty():
            token = token_stream.peek(0)
            if not token or token.value.strip():
                break
            token_stream.consume()
        
        # Check for OPTIONAL keyword
        is_optional = False
        token = token_stream.peek(0)
        if token and token.value.upper() == "OPTIONAL":
            is_optional = True
            token_stream.consume()
            # Skip whitespace
            while not token_stream.is_empty():
                token = token_stream.peek(0)
                if not token or token.value.strip():
                    break
                token_stream.consume()
        
        # Get file name
        token = token_stream.peek(0)
        if not token:
            return None
        
        file_name = token.value
        token_stream.consume()
        
        # Build SELECT statement data
        select_data: Dict[str, Any] = {
            "type": "SELECT",
            "file_name": file_name,
            "is_optional": is_optional,
            "location": location
        }
        
        # Parse clauses until period
        while not token_stream.is_empty():
            token = token_stream.peek(0)
            if not token:
                break
            
            # Skip whitespace/newlines
            if not token.value.strip():
                token_stream.consume()
                continue
            
            # End of SELECT statement
            if token.value == ".":
                token_stream.consume()
                break
            
            token_value = token.value.upper()
            
            # ASSIGN TO clause
            if token_value == "ASSIGN":
                self._parse_select_assign_clause(token_stream, select_data)
            
            # ORGANIZATION IS clause
            elif token_value == "ORGANIZATION":
                self._parse_select_organization_clause(token_stream, select_data)
            
            # ACCESS MODE clause
            elif token_value == "ACCESS":
                self._parse_select_access_mode_clause(token_stream, select_data)
            
            # RECORD KEY clause
            elif token_value == "RECORD":
                self._parse_select_record_key_clause(token_stream, select_data)
            
            # RELATIVE KEY clause
            elif token_value == "RELATIVE":
                self._parse_select_relative_key_clause(token_stream, select_data)
            
            # FILE STATUS clause
            elif token_value == "FILE":
                self._parse_select_file_status_clause(token_stream, select_data)
            
            else:
                # Skip unknown tokens
                token_stream.consume()
        
        return select_data

    def _parse_select_assign_clause(self, token_stream: ITokenStream, select_data: Dict[str, Any]) -> None:
        """Parse ASSIGN TO clause."""
        # Skip ASSIGN
        token_stream.consume()
        
        # Skip optional TO
        token = token_stream.peek(0)
        if token and token.value.upper() == "TO":
            token_stream.consume()
        
        # Skip whitespace
        token = token_stream.peek(0)
        if token and not token.value.strip():
            token_stream.consume()
        
        # Collect tokens until next keyword or period
        assign_to_parts = []
        while not token_stream.is_empty():
            token = token_stream.peek(0)
            if not token:
                break
            
            # Skip whitespace
            if not token.value.strip():
                token_stream.consume()
                continue
            
            # Check for next clause or end
            upper_val = token.value.upper()
            if upper_val in ("ORGANIZATION", "ACCESS", "RECORD", "RELATIVE", "FILE", "SELECT", ".") or upper_val in ("CONFIGURATION", "DATA", "PROCEDURE"):
                break
            
            # Handle string literals - need to reconstruct quotes
            if token.type.name == "STRING_LITERAL":
                # String literals come without quotes from tokenizer, add them back
                assign_to_parts.append(f'"{token.value}"')
            else:
                assign_to_parts.append(token.value)
            token_stream.consume()
        
        if assign_to_parts:
            assign_to = " ".join(assign_to_parts)
            select_data["assign_to"] = assign_to

    def _parse_select_organization_clause(self, token_stream: ITokenStream, select_data: Dict[str, Any]) -> None:
        """Parse ORGANIZATION IS clause."""
        # Skip ORGANIZATION
        token_stream.consume()
        
        # Skip optional IS
        token = token_stream.peek(0)
        if token and token.value.upper() == "IS":
            token_stream.consume()
        
        # Skip whitespace
        token = token_stream.peek(0)
        if token and not token.value.strip():
            token_stream.consume()
        
        # Get organization type
        token = token_stream.peek(0)
        if token:
            org_val = token.value.upper()
            token_stream.consume()
            
            # Check for LINE SEQUENTIAL
            if org_val == "LINE":
                token = token_stream.peek(0)
                if token and token.value.upper() == "SEQUENTIAL":
                    select_data["organization"] = "LINE SEQUENTIAL"
                    token_stream.consume()
                else:
                    select_data["organization"] = "LINE"
            elif org_val in ("SEQUENTIAL", "INDEXED", "RELATIVE"):
                select_data["organization"] = org_val

    def _parse_select_access_mode_clause(self, token_stream: ITokenStream, select_data: Dict[str, Any]) -> None:
        """Parse ACCESS MODE IS clause."""
        # Skip ACCESS
        token_stream.consume()
        
        # Skip optional MODE
        token = token_stream.peek(0)
        if token and token.value.upper() == "MODE":
            token_stream.consume()
        
        # Skip optional IS
        token = token_stream.peek(0)
        if token and token.value.upper() == "IS":
            token_stream.consume()
        
        # Skip whitespace
        token = token_stream.peek(0)
        if token and not token.value.strip():
            token_stream.consume()
        
        # Get access mode
        token = token_stream.peek(0)
        if token:
            access_val = token.value.upper()
            if access_val in ("SEQUENTIAL", "RANDOM", "DYNAMIC"):
                select_data["access_mode"] = access_val
                token_stream.consume()

    def _parse_select_record_key_clause(self, token_stream: ITokenStream, select_data: Dict[str, Any]) -> None:
        """Parse RECORD KEY IS clause."""
        # Skip RECORD
        token_stream.consume()
        
        # Skip optional KEY
        token = token_stream.peek(0)
        if token and token.value.upper() == "KEY":
            token_stream.consume()
        
        # Skip optional IS
        token = token_stream.peek(0)
        if token and token.value.upper() == "IS":
            token_stream.consume()
        
        # Skip whitespace
        token = token_stream.peek(0)
        if token and not token.value.strip():
            token_stream.consume()
        
        # Get key name
        token = token_stream.peek(0)
        if token:
            select_data["record_key"] = token.value
            token_stream.consume()

    def _parse_select_relative_key_clause(self, token_stream: ITokenStream, select_data: Dict[str, Any]) -> None:
        """Parse RELATIVE KEY IS clause."""
        # Skip RELATIVE
        token_stream.consume()
        
        # Skip optional KEY
        token = token_stream.peek(0)
        if token and token.value.upper() == "KEY":
            token_stream.consume()
        
        # Skip optional IS
        token = token_stream.peek(0)
        if token and token.value.upper() == "IS":
            token_stream.consume()
        
        # Skip whitespace
        token = token_stream.peek(0)
        if token and not token.value.strip():
            token_stream.consume()
        
        # Get key name
        token = token_stream.peek(0)
        if token:
            select_data["relative_key"] = token.value
            token_stream.consume()

    def _parse_select_file_status_clause(self, token_stream: ITokenStream, select_data: Dict[str, Any]) -> None:
        """Parse FILE STATUS IS clause."""
        # Skip FILE
        token_stream.consume()
        
        # Skip optional STATUS
        token = token_stream.peek(0)
        if token and token.value.upper() == "STATUS":
            token_stream.consume()
        
        # Skip optional IS
        token = token_stream.peek(0)
        if token and token.value.upper() == "IS":
            token_stream.consume()
        
        # Skip whitespace
        token = token_stream.peek(0)
        if token and not token.value.strip():
            token_stream.consume()
        
        # Get status variable(s)
        token = token_stream.peek(0)
        if token:
            select_data["file_status"] = token.value
            token_stream.consume()

    def _create_ast_node(
        self,
        division_token: Any,
        division_content: Dict[str, Any],
        start_location: SourceLocation
    ) -> ASTNode:
        """Create AST node for Environment Division.
        
        Creates a CobolDivision node with environment metadata and sections.
        Also creates FILE-CONTROL paragraphs with SELECT statements.
        
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
        division_node.metadata.update({
            "has_configuration": "configuration" in division_content,
            "has_input_output": "input_output" in division_content,
        })
        
        # Create CONFIGURATION SECTION if present
        if "configuration" in division_content:
            config_section = CobolSection("CONFIGURATION", start_location)
            division_node.add_section(config_section)
        
        # Create INPUT-OUTPUT SECTION if present
        if "input_output" in division_content:
            io_section = CobolSection("INPUT-OUTPUT", start_location)
            
            # Add FILE-CONTROL paragraph with SELECT statements
            select_statements = division_content.get("input_output", {}).get("select_statements", [])
            if select_statements:
                file_control_para = CobolParagraph("FILE-CONTROL", start_location)
                
                # Convert select data dicts to SelectStatement AST nodes
                for select_data in select_statements:
                    select_stmt = self._create_select_statement_node(select_data)
                    file_control_para.add_statement(select_stmt)
                
                io_section.add_paragraph(file_control_para)
            
            division_node.add_section(io_section)
        
        return division_node

    def _create_select_statement_node(self, select_data: Dict[str, Any]) -> SelectStatement:
        """Create a SelectStatement AST node from parsed data.
        
        Args:
            select_data: Dictionary containing parsed SELECT statement data
            
        Returns:
            SelectStatement AST node
        """
        location = select_data.get("location") or SourceLocation(0, 0)
        select_stmt = SelectStatement(location)
        
        # Set file name
        file_name = select_data.get("file_name")
        is_optional = select_data.get("is_optional", False)
        if file_name:
            select_stmt.set_file_name(file_name, is_optional)
        
        # Set ASSIGN TO clause
        assign_to = select_data.get("assign_to")
        device = select_data.get("assign_device")
        if assign_to:
            select_stmt.set_assign_to(assign_to, device)
        
        # Set ORGANIZATION clause
        organization = select_data.get("organization")
        if organization:
            select_stmt.set_organization(organization)
        
        # Set ACCESS MODE clause
        access_mode = select_data.get("access_mode")
        if access_mode:
            select_stmt.set_access_mode(access_mode)
        
        # Set RECORD KEY clause
        record_key = select_data.get("record_key")
        if record_key:
            select_stmt.set_record_key(record_key)
        
        # Set RELATIVE KEY clause
        relative_key = select_data.get("relative_key")
        if relative_key:
            select_stmt.relative_key = relative_key
        
        # Set FILE STATUS clause
        file_status = select_data.get("file_status")
        if file_status:
            select_stmt.file_status = file_status
        
        return select_stmt

