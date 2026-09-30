"""Environment Division parser for COBOL programs.

This module implements parsing of the Environment Division which contains:
- CONFIGURATION SECTION: Compiler options and configurations
- INPUT-OUTPUT SECTION: File control and I/O definitions

The :class:`EnvironmentDivisionParser` owns the division scan loop and the
AST node creation. The detailed section/statement parsing is delegated to
focused collaborators:

- :class:`~.environment_sections.ConfigurationSectionParser` — CONFIGURATION
  SECTION and the SPECIAL-NAMES paragraph
- :class:`~.environment_sections.InputOutputSectionParser` — INPUT-OUTPUT
  SECTION and the FILE-CONTROL paragraph
- :class:`~.environment_select.SelectClauseParser` — individual SELECT
  statements and their AST node construction
"""

from typing import Any

from cobolparser.core.interfaces import ITokenStream
from cobolparser.models.ast_base import ASTNode, SourceLocation
from cobolparser.models.program import CobolDivision, CobolParagraph, CobolSection
from cobolparser.models.statements import SelectStatement

from .base import BaseDivisionParser
from .environment_sections import ConfigurationSectionParser, InputOutputSectionParser
from .environment_select import SelectClauseParser


class EnvironmentDivisionParser(BaseDivisionParser):
    """Parser for COBOL Environment Division.

    Handles extraction and parsing of environment configuration and I/O definitions.
    Processes CONFIGURATION SECTION and INPUT-OUTPUT SECTION.
    """

    division_name: str | None = "ENVIRONMENT"
    division_keywords: tuple = ()

    def __init__(self) -> None:
        """Initialize the Environment Division parser and its collaborators."""
        super().__init__()
        self._select_parser = SelectClauseParser(self)
        self._configuration_parser = ConfigurationSectionParser(self)
        self._input_output_parser = InputOutputSectionParser(self._select_parser)

    def parse_division(self, token_stream: ITokenStream) -> dict[str, Any]:
        """Parse Environment Division content.

        Parses optional sections:
        - CONFIGURATION SECTION
        - INPUT-OUTPUT SECTION

        Args:
            token_stream: Token stream positioned after division header

        Returns:
            Dictionary containing parsed sections and their content
        """
        sections: dict[str, Any] = {}

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
            # In a CLASS-ID unit the ENVIRONMENT DIVISION (REPOSITORY) is
            # followed by the ``FACTORY.`` / ``OBJECT.`` paragraph that opens
            # the next unit, or by a ``METHOD-ID``; none of those is ours.
            if token_value == "METHOD-ID":
                break
            if token_value in ("FACTORY", "OBJECT"):
                nxt = token_stream.peek(1)
                if nxt is not None and nxt.value == ".":
                    break

            # Parse specific sections
            if token_value == "CONFIGURATION":
                sections["configuration"] = self._parse_configuration_section(
                    token_stream
                )
            elif token_value == "INPUT-OUTPUT":
                sections["input_output"] = self._parse_input_output_section(
                    token_stream
                )
            else:
                # Unknown section - skip it for error recovery
                token_stream.consume()

        return sections

    # ------------------------------------------------------------------
    # Delegating wrappers.
    #
    # The section and SELECT parsing lives in the collaborator classes (see
    # the module docstring). These wrappers keep the historical method names
    # on the division parser itself.
    # ------------------------------------------------------------------

    def _parse_configuration_section(
        self, token_stream: ITokenStream
    ) -> dict[str, Any]:
        """Parse CONFIGURATION SECTION (delegates to ConfigurationSectionParser)."""
        return self._configuration_parser.parse_configuration_section(token_stream)

    def _parse_input_output_section(self, token_stream: ITokenStream) -> dict[str, Any]:
        """Parse INPUT-OUTPUT SECTION (delegates to InputOutputSectionParser)."""
        return self._input_output_parser.parse_input_output_section(token_stream)

    def _parse_select_statement(
        self, token_stream: ITokenStream
    ) -> dict[str, Any] | None:
        """Parse a SELECT statement (delegates to SelectClauseParser)."""
        return self._select_parser.parse_select_statement(token_stream)

    def _create_select_statement_node(
        self, select_data: dict[str, Any]
    ) -> SelectStatement:
        """Create a SelectStatement AST node (delegates to SelectClauseParser)."""
        return self._select_parser.create_select_statement_node(select_data)

    def _create_ast_node(
        self,
        division_token: Any,
        division_content: dict[str, Any],
        start_location: SourceLocation,
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
        division_node.metadata.update(
            {
                "has_configuration": "configuration" in division_content,
                "has_input_output": "input_output" in division_content,
            }
        )

        # Create CONFIGURATION SECTION if present
        if "configuration" in division_content:
            config_data = division_content["configuration"]
            config_location = (
                config_data.get("location", start_location)
                if isinstance(config_data, dict)
                else start_location
            )
            config_section = CobolSection("CONFIGURATION", config_location)
            if isinstance(config_data, dict) and "special_names" in config_data:
                config_section.set_metadata(
                    "special_names", config_data["special_names"]
                )
            if isinstance(config_data, dict):
                for key in ("source_computer", "object_computer"):
                    if key in config_data:
                        config_section.set_metadata(key, config_data[key])
            division_node.add_section(config_section)

        # Create INPUT-OUTPUT SECTION if present
        if "input_output" in division_content:
            io_content = division_content["input_output"]
            io_location = io_content.get("location", start_location)
            io_section = CobolSection("INPUT-OUTPUT", io_location)
            if "io_control" in io_content:
                io_section.set_metadata("io_control", io_content["io_control"])

            # Add FILE-CONTROL paragraph with SELECT statements
            select_statements = io_content.get("select_statements", [])
            if select_statements:
                file_control_location = io_content.get(
                    "file_control_location", io_location
                )
                file_control_para = CobolParagraph(
                    "FILE-CONTROL", file_control_location
                )

                # Convert select data dicts to SelectStatement AST nodes
                for select_data in select_statements:
                    select_stmt = self._create_select_statement_node(select_data)
                    file_control_para.add_statement(select_stmt)

                io_section.add_paragraph(file_control_para)

            division_node.add_section(io_section)

        return division_node
