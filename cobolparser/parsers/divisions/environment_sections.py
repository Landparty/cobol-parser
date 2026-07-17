"""Section parsing for the ENVIRONMENT DIVISION.

Collaborators of
:class:`~cobolparser.parsers.divisions.environment.EnvironmentDivisionParser`:

- :class:`ConfigurationSectionParser` — CONFIGURATION SECTION, including the
  SPECIAL-NAMES paragraph (CURRENCY SIGN, DECIMAL-POINT IS COMMA, CLASS,
  ALPHABET)
- :class:`InputOutputSectionParser` — INPUT-OUTPUT SECTION with the
  FILE-CONTROL paragraph, delegating each SELECT statement to
  :class:`~.environment_select.SelectClauseParser`
"""

from typing import Any

from cobolparser.core.interfaces import ITokenStream
from cobolparser.models.ast_base import SourceLocation

from .environment_select import SelectClauseParser


class ConfigurationSectionParser:
    """Parses the CONFIGURATION SECTION and its SPECIAL-NAMES paragraph."""

    def __init__(self, parser: Any) -> None:
        """Initialize with the owning division parser.

        Args:
            parser: The ``EnvironmentDivisionParser`` this collaborator
                belongs to (used to reach the host warning channel).
        """
        self._parser = parser

    def parse_configuration_section(self, token_stream: ITokenStream) -> dict[str, Any]:
        """Parse CONFIGURATION SECTION including SPECIAL-NAMES paragraph.

        Recognises SPECIAL-NAMES clauses:
        - CURRENCY SIGN IS 'x'
        - DECIMAL-POINT IS COMMA
        - CLASS name IS range
        - ALPHABET name IS ...
        Unknown clauses are consumed until the next period.
        """
        # Capture the CONFIGURATION keyword's own location before consuming it
        # (the AST node must report where this section actually starts, not
        # its parent division's location).
        config_token = token_stream.peek(0)
        config_location = config_token.location if config_token else None

        # Consume CONFIGURATION keyword
        token_stream.consume()

        _stop_divs = ("DATA", "PROCEDURE", "IDENTIFICATION")
        # "SECTION" by itself marks the next paragraph/section header — but we
        # must first skip the current "SECTION." header before entering the body.
        _body_stop = {"INPUT-OUTPUT", "DATA", "PROCEDURE", "IDENTIFICATION"}

        # Consume the "SECTION" keyword and optional period that follow CONFIGURATION
        pk = token_stream.peek(0)
        if pk and pk.value.upper() == "SECTION":
            token_stream.consume()
        pk = token_stream.peek(0)
        if pk and pk.value == ".":
            token_stream.consume()

        special_names: dict[str, Any] = {}

        def _at_stop() -> bool:
            token = token_stream.peek(0)
            if not token:
                return True
            v = token.value.upper()
            if v in _body_stop:
                return True
            return any(v == f"{kw} DIVISION" for kw in _stop_divs)

        # Scan configuration section body for SPECIAL-NAMES paragraph
        while not token_stream.is_empty() and not _at_stop():
            token = token_stream.peek(0)
            if not token:
                break
            v = token.value.upper()
            if v == "SPECIAL-NAMES":
                token_stream.consume()
                # consume optional period after paragraph header
                pk = token_stream.peek(0)
                if pk and pk.value == ".":
                    token_stream.consume()
                special_names = self._parse_special_names_paragraph(
                    token_stream, _body_stop, _stop_divs
                )
            else:
                token_stream.consume()

        result: dict[str, Any] = {"type": "configuration"}
        if config_location is not None:
            result["location"] = config_location
        if special_names:
            result["special_names"] = special_names
        return result

    def _parse_special_names_paragraph(
        self,
        token_stream: ITokenStream,
        stop_sections: set[str],
        stop_divs: tuple[str, ...],
    ) -> dict[str, Any]:
        """Parse clauses inside SPECIAL-NAMES paragraph."""
        currency_sign: str | None = None
        decimal_point_is_comma: bool = False
        class_definitions: list[dict[str, Any]] = []
        alphabet_definitions: list[dict[str, Any]] = []

        def _at_para_end() -> bool:
            token = token_stream.peek(0)
            if not token:
                return True
            v = token.value.upper()
            if v in stop_sections:
                return True
            return any(v == f"{kw} DIVISION" for kw in stop_divs)

        while not token_stream.is_empty() and not _at_para_end():
            token = token_stream.peek(0)
            if not token:
                break
            v = token.value.upper()

            if v == "CURRENCY":
                token_stream.consume()
                # skip optional SIGN / IS
                for _kw in ("SIGN", "IS"):
                    pk = token_stream.peek(0)
                    if pk and pk.value.upper() == _kw:
                        token_stream.consume()
                pk = token_stream.peek(0)
                if pk and pk.value:
                    currency_sign = pk.value.strip("'\"")
                    token_stream.consume()

            elif v == "DECIMAL-POINT":
                token_stream.consume()
                # skip optional IS
                pk = token_stream.peek(0)
                if pk and pk.value.upper() == "IS":
                    token_stream.consume()
                pk = token_stream.peek(0)
                if pk and pk.value.upper() == "COMMA":
                    decimal_point_is_comma = True
                    token_stream.consume()
                    # The lexer has already tokenized the program with `.` as
                    # the decimal point and `,` as a separator, so this clause
                    # is recorded but NOT honored (audit 2026-07-07 H4):
                    # `VALUE 3,14` / `COMPUTE X = 3,14` misparse. Make the
                    # degradation caller-visible instead of silent.
                    host = getattr(self._parser, "host", None)
                    add_warning = getattr(host, "add_warning", None)
                    if callable(add_warning):
                        add_warning(
                            "DECIMAL-POINT IS COMMA is recorded in metadata but "
                            "not honored by the lexer: numeric literals using a "
                            "comma decimal point (e.g. VALUE 3,14) will misparse"
                        )

            elif v == "CLASS":
                token_stream.consume()
                name_tok = token_stream.peek(0)
                class_name = name_tok.value if name_tok else ""
                if name_tok:
                    token_stream.consume()
                # skip IS
                pk = token_stream.peek(0)
                if pk and pk.value.upper() == "IS":
                    token_stream.consume()
                # collect range values until period or next keyword
                ranges: list[str] = []
                while not token_stream.is_empty():
                    pk = token_stream.peek(0)
                    if (
                        not pk
                        or pk.value == "."
                        or pk.value.upper()
                        in {
                            "CURRENCY",
                            "DECIMAL-POINT",
                            "CLASS",
                            "ALPHABET",
                        }
                        | stop_sections
                    ):
                        break
                    ranges.append(pk.value)
                    token_stream.consume()
                class_definitions.append({"name": class_name, "ranges": ranges})

            elif v == "ALPHABET":
                token_stream.consume()
                name_tok = token_stream.peek(0)
                alpha_name = name_tok.value if name_tok else ""
                if name_tok:
                    token_stream.consume()
                # skip IS
                pk = token_stream.peek(0)
                if pk and pk.value.upper() == "IS":
                    token_stream.consume()
                # collect until period or next paragraph keyword
                values: list[str] = []
                while not token_stream.is_empty():
                    pk = token_stream.peek(0)
                    if (
                        not pk
                        or pk.value == "."
                        or pk.value.upper()
                        in {
                            "CURRENCY",
                            "DECIMAL-POINT",
                            "CLASS",
                            "ALPHABET",
                        }
                        | stop_sections
                    ):
                        break
                    values.append(pk.value)
                    token_stream.consume()
                alphabet_definitions.append({"name": alpha_name, "values": values})

            elif token.value == ".":
                token_stream.consume()  # clause separator

            else:
                # Unknown clause — consume to next period
                token_stream.consume()

        result: dict[str, Any] = {}
        if currency_sign is not None:
            result["currency_sign"] = currency_sign
        if decimal_point_is_comma:
            result["decimal_point_is_comma"] = True
        if class_definitions:
            result["class_definitions"] = class_definitions
        if alphabet_definitions:
            result["alphabet_definitions"] = alphabet_definitions
        return result


class InputOutputSectionParser:
    """Parses the INPUT-OUTPUT SECTION and its FILE-CONTROL paragraph."""

    def __init__(self, select_parser: SelectClauseParser) -> None:
        """Initialize with the SELECT statement collaborator.

        Args:
            select_parser: Parses each FILE-CONTROL SELECT statement.
        """
        self._select_parser = select_parser

    def parse_input_output_section(self, token_stream: ITokenStream) -> dict[str, Any]:
        """Parse INPUT-OUTPUT SECTION.

        Format: INPUT-OUTPUT SECTION. [io-content]
                FILE-CONTROL. [select-statements]

        Args:
            token_stream: Token stream positioned at INPUT-OUTPUT keyword

        Returns:
            Dictionary containing I/O definitions including SELECT statements
        """
        # Capture the INPUT-OUTPUT keyword's own location before consuming it.
        io_token = token_stream.peek(0)
        io_location = io_token.location if io_token else None

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
        select_statements: list[dict[str, Any]] = []
        file_control_location: SourceLocation | None = None

        while not token_stream.is_empty():
            token = token_stream.peek(0)
            if not token:
                break

            token_value = token.value.upper()

            # Check if we've reached next SECTION or division
            _stop = ("CONFIGURATION", "DATA", "PROCEDURE", "IDENTIFICATION")
            if token_value in _stop:
                break
            if any(
                token_value == f"{kw} DIVISION"
                for kw in ("DATA", "PROCEDURE", "IDENTIFICATION")
            ):
                break

            # Parse FILE-CONTROL paragraph (may appear as "NTROL" due to tokenizer)
            if token_value == "FILE-CONTROL" or token_value.endswith("CONTROL"):
                file_control_data = self._parse_file_control_paragraph(token_stream)
                select_statements.extend(file_control_data.get("selects", []))
                file_control_location = file_control_data.get("location")
            else:
                # Skip other content
                token_stream.consume()

        result: dict[str, Any] = {
            "type": "input_output",
            "select_statements": select_statements,
        }
        if io_location is not None:
            result["location"] = io_location
        if file_control_location is not None:
            result["file_control_location"] = file_control_location
        return result

    def _parse_file_control_paragraph(
        self, token_stream: ITokenStream
    ) -> dict[str, Any]:
        """Parse FILE-CONTROL paragraph with SELECT statements.

        Format: FILE-CONTROL. [SELECT statements]

        Args:
            token_stream: Token stream positioned at FILE-CONTROL keyword

        Returns:
            Dictionary containing parsed SELECT statements
        """
        # Capture the FILE-CONTROL keyword's own location before consuming it.
        fc_token = token_stream.peek(0)
        fc_location = fc_token.location if fc_token else None

        # Consume FILE-CONTROL keyword (may appear as "NTROL" due to tokenizer)
        token = token_stream.peek(0)
        if token and token.value.upper().endswith("CONTROL"):
            token_stream.consume()

        # Expect period
        token = token_stream.peek(0)
        if token and token.value == ".":
            token_stream.consume()

        # Parse SELECT statements
        select_statements: list[dict[str, Any]] = []

        while not token_stream.is_empty():
            token = token_stream.peek(0)
            if not token:
                break

            token_value = token.value.upper()

            # Check for end of FILE-CONTROL (next section/division or paragraph)
            section_keywords = {
                "CONFIGURATION",
                "DATA",
                "PROCEDURE",
                "IDENTIFICATION",
                "FILE-CONTROL",
            }
            if token_value in section_keywords:
                break
            if any(
                token_value == f"{kw} DIVISION"
                for kw in ("DATA", "PROCEDURE", "IDENTIFICATION")
            ):
                break

            # Parse SELECT statement (may appear as "ECT" due to tokenizer)
            if token_value == "SELECT" or token_value.startswith("ECT"):
                select_data = self._select_parser.parse_select_statement(token_stream)
                if select_data:
                    select_statements.append(select_data)
            else:
                # Skip other tokens
                token_stream.consume()

        result: dict[str, Any] = {"selects": select_statements}
        if fc_location is not None:
            result["location"] = fc_location
        return result
