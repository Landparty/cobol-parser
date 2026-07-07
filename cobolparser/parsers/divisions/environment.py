"""Environment Division parser for COBOL programs.

This module implements parsing of the Environment Division which contains:
- CONFIGURATION SECTION: Compiler options and configurations
- INPUT-OUTPUT SECTION: File control and I/O definitions
"""

from typing import Any

from cobolparser.core.interfaces import ITokenStream
from cobolparser.models.ast_base import ASTNode, SourceLocation
from cobolparser.models.program import CobolDivision, CobolParagraph, CobolSection
from cobolparser.models.statements import SelectStatement

from .base import BaseDivisionParser

#: Keywords that start a SELECT clause (or end the statement) — used to tell
#: a second FILE STATUS variable apart from the next clause.
_SELECT_CLAUSE_KEYWORDS: frozenset[str] = frozenset(
    {
        "ASSIGN",
        "ORGANIZATION",
        "ACCESS",
        "RECORD",
        "RELATIVE",
        "FILE",
        "ALTERNATE",
        "PADDING",
        "RESERVE",
        "SHARING",
        "LOCK",
        "PASSWORD",
        "SELECT",
        "CONFIGURATION",
        "DATA",
        "PROCEDURE",
        "I-O-CONTROL",
    }
)

#: Device words recognized in ASSIGN TO clauses (populates assign_device).
_ASSIGN_DEVICE_WORDS: frozenset[str] = frozenset(
    {
        "DISK",
        "TAPE",
        "PRINTER",
        "DISPLAY",
        "KEYBOARD",
        "CONSOLE",
        "SYSIN",
        "SYSOUT",
        "SYSPRINT",
        "SYSPUNCH",
    }
)


class EnvironmentDivisionParser(BaseDivisionParser):
    """Parser for COBOL Environment Division.

    Handles extraction and parsing of environment configuration and I/O definitions.
    Processes CONFIGURATION SECTION and INPUT-OUTPUT SECTION.
    """

    division_name: str | None = "ENVIRONMENT"
    division_keywords: tuple = ()

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

    def _parse_configuration_section(
        self, token_stream: ITokenStream
    ) -> dict[str, Any]:
        """Parse CONFIGURATION SECTION including SPECIAL-NAMES paragraph.

        Recognises SPECIAL-NAMES clauses:
        - CURRENCY SIGN IS 'x'
        - DECIMAL-POINT IS COMMA
        - CLASS name IS range
        - ALPHABET name IS ...
        Unknown clauses are consumed until the next period.
        """
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
                    host = getattr(self, "host", None)
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

    def _parse_input_output_section(self, token_stream: ITokenStream) -> dict[str, Any]:
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
        select_statements: list[dict[str, Any]] = []

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
            else:
                # Skip other content
                token_stream.consume()

        return {"type": "input_output", "select_statements": select_statements}

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
                select_data = self._parse_select_statement(token_stream)
                if select_data:
                    select_statements.append(select_data)
            else:
                # Skip other tokens
                token_stream.consume()

        return {"selects": select_statements}

    def _parse_select_statement(
        self, token_stream: ITokenStream
    ) -> dict[str, Any] | None:
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
        if not token or (
            token.value.upper() != "SELECT" and not token.value.upper().endswith("ECT")
        ):
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
        select_data: dict[str, Any] = {
            "type": "SELECT",
            "file_name": file_name,
            "is_optional": is_optional,
            "location": location,
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

            # ALTERNATE RECORD KEY clause (secondary indexes — may repeat)
            elif token_value == "ALTERNATE":
                self._parse_select_alternate_key_clause(token_stream, select_data)

            # PADDING CHARACTER clause
            elif token_value == "PADDING":
                self._parse_select_padding_clause(token_stream, select_data)

            # RESERVE n AREAS clause
            elif token_value == "RESERVE":
                self._parse_select_reserve_clause(token_stream, select_data)

            # SHARING WITH clause
            elif token_value == "SHARING":
                self._parse_select_sharing_clause(token_stream, select_data)

            # LOCK MODE clause
            elif token_value == "LOCK":
                self._parse_select_lock_mode_clause(token_stream, select_data)

            # PASSWORD clause
            elif token_value == "PASSWORD":
                self._parse_select_password_clause(token_stream, select_data)

            else:
                # Unknown SELECT clause token: dropped content must be
                # caller-visible (audit 2026-07-07 H5) — warn, don't just skip.
                self._warn_dropped_select_token(token, select_data)
                token_stream.consume()

        return select_data

    def _warn_dropped_select_token(
        self, token: Any, select_data: dict[str, Any]
    ) -> None:
        """Record a warning for a SELECT clause token that was skipped."""
        value = (token.value or "").strip() if token else ""
        if not value:
            return
        line = getattr(getattr(token, "location", None), "line", None)
        where = f" at line {line}" if line else ""
        file_name = select_data.get("file_name", "?")
        host = getattr(self, "host", None)
        add_warning = getattr(host, "add_warning", None)
        message = (
            f"Unparsed token '{value}'{where} in SELECT {file_name} skipped: "
            "clause not fully supported; content dropped from the AST"
        )
        if callable(add_warning):
            add_warning(message)

    @staticmethod
    def _skip_select_blanks(token_stream: ITokenStream) -> None:
        """Skip whitespace/newline tokens inside a SELECT clause."""
        while not token_stream.is_empty():
            token = token_stream.peek(0)
            if not token or (token.value and token.value.strip()):
                break
            token_stream.consume()

    @staticmethod
    def _try_consume_word(token_stream: ITokenStream, *words: str) -> bool:
        """Consume the next token if its upper-cased value is in *words*."""
        EnvironmentDivisionParser._skip_select_blanks(token_stream)
        token = token_stream.peek(0)
        if token and token.value and token.value.upper() in words:
            token_stream.consume()
            return True
        return False

    def _parse_select_alternate_key_clause(
        self, token_stream: ITokenStream, select_data: dict[str, Any]
    ) -> None:
        """Parse ALTERNATE RECORD KEY IS data-name [WITH DUPLICATES]."""
        token_stream.consume()  # Skip ALTERNATE
        self._try_consume_word(token_stream, "RECORD")
        self._try_consume_word(token_stream, "KEY")
        self._try_consume_word(token_stream, "IS")
        self._skip_select_blanks(token_stream)

        token = token_stream.peek(0)
        if not token or not token.value or not token.value.strip():
            return
        key_name = token.value
        token_stream.consume()

        duplicates = False
        if self._try_consume_word(token_stream, "WITH"):
            if self._try_consume_word(token_stream, "DUPLICATES"):
                duplicates = True
        elif self._try_consume_word(token_stream, "DUPLICATES"):
            duplicates = True

        select_data.setdefault("alternate_keys", []).append(
            {"key": key_name, "duplicates_allowed": duplicates, "password": None}
        )

    def _parse_select_padding_clause(
        self, token_stream: ITokenStream, select_data: dict[str, Any]
    ) -> None:
        """Parse PADDING [CHARACTER] [IS] literal-or-data-name."""
        token_stream.consume()  # Skip PADDING
        self._try_consume_word(token_stream, "CHARACTER")
        self._try_consume_word(token_stream, "IS")
        self._skip_select_blanks(token_stream)
        token = token_stream.peek(0)
        if token and token.value and token.value.strip():
            select_data["padding_character"] = token.value
            token_stream.consume()

    def _parse_select_reserve_clause(
        self, token_stream: ITokenStream, select_data: dict[str, Any]
    ) -> None:
        """Parse RESERVE integer [AREA | AREAS]."""
        token_stream.consume()  # Skip RESERVE
        self._skip_select_blanks(token_stream)
        token = token_stream.peek(0)
        if token and token.value and token.value.strip():
            try:
                select_data["reserve_areas"] = int(token.value)
            except ValueError:
                select_data["reserve_areas"] = token.value
            token_stream.consume()
        self._try_consume_word(token_stream, "AREA", "AREAS")

    def _parse_select_sharing_clause(
        self, token_stream: ITokenStream, select_data: dict[str, Any]
    ) -> None:
        """Parse SHARING [WITH] {ALL [OTHER] | NO OTHER | READ ONLY}."""
        token_stream.consume()  # Skip SHARING
        self._try_consume_word(token_stream, "WITH")
        self._skip_select_blanks(token_stream)
        token = token_stream.peek(0)
        if not token or not token.value or not token.value.strip():
            return
        first = token.value.upper()
        if first == "ALL":
            token_stream.consume()
            self._try_consume_word(token_stream, "OTHER")
            select_data["sharing_mode"] = "ALL"
        elif first == "NO":
            token_stream.consume()
            self._try_consume_word(token_stream, "OTHER")
            select_data["sharing_mode"] = "NO OTHER"
        elif first == "READ":
            token_stream.consume()
            self._try_consume_word(token_stream, "ONLY")
            select_data["sharing_mode"] = "READ ONLY"

    def _parse_select_lock_mode_clause(
        self, token_stream: ITokenStream, select_data: dict[str, Any]
    ) -> None:
        """Parse LOCK [MODE] [IS] {MANUAL|AUTOMATIC|EXCLUSIVE} [WITH LOCK ON [MULTIPLE] RECORD[S]] [WITH ROLLBACK]."""
        token_stream.consume()  # Skip LOCK
        self._try_consume_word(token_stream, "MODE")
        self._try_consume_word(token_stream, "IS")
        self._skip_select_blanks(token_stream)
        token = token_stream.peek(0)
        if not token or not token.value:
            return
        mode = token.value.upper()
        if mode not in ("MANUAL", "AUTOMATIC", "EXCLUSIVE"):
            return
        token_stream.consume()
        select_data["lock_mode"] = mode

        # Optional WITH LOCK ON [MULTIPLE] RECORD[S] / WITH ROLLBACK
        while self._try_consume_word(token_stream, "WITH"):
            if self._try_consume_word(token_stream, "LOCK"):
                self._try_consume_word(token_stream, "ON")
                lock_on_parts = []
                if self._try_consume_word(token_stream, "MULTIPLE"):
                    lock_on_parts.append("MULTIPLE")
                self._skip_select_blanks(token_stream)
                token = token_stream.peek(0)
                if (
                    token
                    and token.value
                    and token.value.upper()
                    in (
                        "RECORD",
                        "RECORDS",
                    )
                ):
                    lock_on_parts.append(token.value.upper())
                    token_stream.consume()
                if lock_on_parts:
                    select_data["lock_on"] = " ".join(lock_on_parts)
            elif self._try_consume_word(token_stream, "ROLLBACK"):
                select_data["lock_with_rollback"] = True
            else:
                break

    def _parse_select_password_clause(
        self, token_stream: ITokenStream, select_data: dict[str, Any]
    ) -> None:
        """Parse PASSWORD [IS] data-name."""
        token_stream.consume()  # Skip PASSWORD
        self._try_consume_word(token_stream, "IS")
        self._skip_select_blanks(token_stream)
        token = token_stream.peek(0)
        if token and token.value and token.value.strip():
            select_data["password"] = token.value
            token_stream.consume()

    def _parse_select_assign_clause(
        self, token_stream: ITokenStream, select_data: dict[str, Any]
    ) -> None:
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
            if upper_val == "." or upper_val in _SELECT_CLAUSE_KEYWORDS:
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

            # Populate the device type when recognizable (audit 2026-07-07
            # H5: assign_device was never populated). Covers bare device
            # words (ASSIGN TO DISK) and IBM organization-prefixed names
            # (ASSIGN TO UT-S-DDNAME -> device "UT-S").
            first = assign_to_parts[0].upper()
            if first in _ASSIGN_DEVICE_WORDS:
                select_data["assign_device"] = first
            else:
                parts = first.split("-")
                if len(parts) >= 3 and parts[0] in ("UT", "UR", "DA"):
                    select_data["assign_device"] = "-".join(parts[:2])

    def _parse_select_organization_clause(
        self, token_stream: ITokenStream, select_data: dict[str, Any]
    ) -> None:
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

    def _parse_select_access_mode_clause(
        self, token_stream: ITokenStream, select_data: dict[str, Any]
    ) -> None:
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

    def _parse_select_record_key_clause(
        self, token_stream: ITokenStream, select_data: dict[str, Any]
    ) -> None:
        """Parse RECORD KEY IS clause (or RECORD DELIMITER IS ...)."""
        # Skip RECORD
        token_stream.consume()

        # RECORD DELIMITER IS STANDARD-1/data-name is a different clause that
        # shares the RECORD prefix — capture it instead of misparsing it as a
        # record key.
        if self._try_consume_word(token_stream, "DELIMITER"):
            self._try_consume_word(token_stream, "IS")
            self._skip_select_blanks(token_stream)
            token = token_stream.peek(0)
            if token and token.value and token.value.strip():
                select_data["record_delimiter"] = token.value
                token_stream.consume()
            return

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

    def _parse_select_relative_key_clause(
        self, token_stream: ITokenStream, select_data: dict[str, Any]
    ) -> None:
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

    def _parse_select_file_status_clause(
        self, token_stream: ITokenStream, select_data: dict[str, Any]
    ) -> None:
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

        # Optional second status variable (VSAM return code, IBM extension):
        # FILE STATUS IS ws-status ws-vsam-status
        self._skip_select_blanks(token_stream)
        token = token_stream.peek(0)
        if (
            token
            and token.value
            and token.value.strip()
            and token.value != "."
            and token.value.upper() not in _SELECT_CLAUSE_KEYWORDS
        ):
            select_data["file_status_vsam"] = token.value
            token_stream.consume()

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
            config_section = CobolSection("CONFIGURATION", start_location)
            config_data = division_content["configuration"]
            if isinstance(config_data, dict) and "special_names" in config_data:
                config_section.set_metadata(
                    "special_names", config_data["special_names"]
                )
            division_node.add_section(config_section)

        # Create INPUT-OUTPUT SECTION if present
        if "input_output" in division_content:
            io_section = CobolSection("INPUT-OUTPUT", start_location)

            # Add FILE-CONTROL paragraph with SELECT statements
            select_statements = division_content.get("input_output", {}).get(
                "select_statements", []
            )
            if select_statements:
                file_control_para = CobolParagraph("FILE-CONTROL", start_location)

                # Convert select data dicts to SelectStatement AST nodes
                for select_data in select_statements:
                    select_stmt = self._create_select_statement_node(select_data)
                    file_control_para.add_statement(select_stmt)

                io_section.add_paragraph(file_control_para)

            division_node.add_section(io_section)

        return division_node

    def _create_select_statement_node(
        self, select_data: dict[str, Any]
    ) -> SelectStatement:
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

        # Set FILE STATUS clause (with optional VSAM second status variable)
        file_status = select_data.get("file_status")
        if file_status:
            select_stmt.set_file_status(
                file_status, select_data.get("file_status_vsam")
            )

        # ALTERNATE RECORD KEY clauses (secondary indexes)
        for alt in select_data.get("alternate_keys", []):
            select_stmt.add_alternate_key(
                alt["key"],
                duplicates_allowed=alt.get("duplicates_allowed", False),
                password=alt.get("password"),
            )

        # RESERVE / PADDING / RECORD DELIMITER / SHARING / LOCK / PASSWORD
        reserve_areas = select_data.get("reserve_areas")
        if isinstance(reserve_areas, int):
            select_stmt.set_reserve_areas(reserve_areas)
        elif reserve_areas is not None:
            select_stmt.reserve_areas = reserve_areas

        padding = select_data.get("padding_character")
        if padding is not None:
            select_stmt.set_padding_character(padding)

        delimiter = select_data.get("record_delimiter")
        if delimiter is not None:
            select_stmt.set_record_delimiter(delimiter)

        sharing = select_data.get("sharing_mode")
        if sharing is not None:
            select_stmt.set_sharing_mode(sharing)

        lock_mode = select_data.get("lock_mode")
        if lock_mode is not None:
            select_stmt.set_lock_mode(
                lock_mode,
                lock_on=select_data.get("lock_on"),
                with_rollback=select_data.get("lock_with_rollback", False),
            )

        password = select_data.get("password")
        if password is not None:
            select_stmt.set_password(password)

        return select_stmt
