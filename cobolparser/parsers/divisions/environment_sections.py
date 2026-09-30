"""Section parsing for the ENVIRONMENT DIVISION.

Collaborators of
:class:`~cobolparser.parsers.divisions.environment.EnvironmentDivisionParser`:

- :class:`ConfigurationSectionParser` — CONFIGURATION SECTION, including the
  SPECIAL-NAMES paragraph (CURRENCY SIGN, DECIMAL-POINT IS COMMA, CLASS,
  ALPHABET, SYMBOLIC CHARACTERS, mnemonic-name clauses)
- :class:`InputOutputSectionParser` — INPUT-OUTPUT SECTION with the
  FILE-CONTROL paragraph, delegating each SELECT statement to
  :class:`~.environment_select.SelectClauseParser`
"""

from typing import Any

from cobolparser.core.interfaces import ITokenStream
from cobolparser.lexer import TokenType
from cobolparser.models.ast_base import SourceLocation

from .environment_select import SelectClauseParser

#: CONFIGURATION SECTION paragraph headers: each one ends SPECIAL-NAMES.
_CONFIGURATION_PARAGRAPHS: frozenset[str] = frozenset(
    {"SOURCE-COMPUTER", "OBJECT-COMPUTER", "SPECIAL-NAMES", "REPOSITORY"}
)
#: Words that open a SPECIAL-NAMES clause (besides ``name IS mnemonic``).
_SPECIAL_NAMES_CLAUSES: frozenset[str] = frozenset(
    {"CURRENCY", "DECIMAL-POINT", "CLASS", "ALPHABET", "SYMBOLIC", "XML-SCHEMA"}
)
# Small integers lex as LEVEL_NUMBER tokens.
_LITERAL_TYPES: frozenset[TokenType] = frozenset(
    {TokenType.STRING_LITERAL, TokenType.NUMERIC_LITERAL, TokenType.LEVEL_NUMBER}
)
_NOISE_TYPES: frozenset[TokenType] = frozenset(
    {
        TokenType.NEWLINE,
        TokenType.WHITESPACE,
        TokenType.COMMENT,
        TokenType.CONTINUATION,
    }
)
#: Words that open an I-O-CONTROL entry (IBM, plus COBOL-85's MULTIPLE FILE).
_IO_CONTROL_CLAUSES: frozenset[str] = frozenset(
    {"RERUN", "SAME", "MULTIPLE", "APPLY", "COMMITMENT"}
)


def _entry_text(tokens: list[Any]) -> str:
    """The words of a paragraph entry joined back into one line of text,
    string literals keeping their quotes."""
    words: list[str] = []
    for token in tokens:
        value = str(token.value)
        if token.type == TokenType.STRING_LITERAL and not value.startswith(("'", '"')):
            value = f"'{value}'"
        words.append(value)
    return " ".join(words)


def _computer_paragraph(name: str, tokens: list[Any]) -> dict[str, Any]:
    """SOURCE-COMPUTER / OBJECT-COMPUTER entry as metadata.

    Neither changes how this parser reads the program, but both carry
    meaning a consumer may need -- ``WITH DEBUGGING MODE`` switches on the
    D-lines, and ``PROGRAM COLLATING SEQUENCE IS alphabet`` changes the
    result of every nonnumeric comparison -- so the entry is recorded rather
    than consumed without a trace.
    """
    words = [str(t.value).upper() for t in tokens]
    entry: dict[str, Any] = {
        "computer_name": (
            str(tokens[0].value)
            if tokens and words[0] not in ("WITH", "DEBUGGING", "MEMORY", "PROGRAM")
            else None
        ),
        "text": _entry_text(tokens),
    }
    if name == "SOURCE-COMPUTER":
        entry["debugging_mode"] = "DEBUGGING" in words
    else:
        collating: str | None = None
        if "COLLATING" in words:
            i = words.index("COLLATING") + 1
            if i < len(words) and words[i] == "SEQUENCE":
                i += 1
            if i < len(words) and words[i] == "IS":
                i += 1
            if i < len(words):
                collating = str(tokens[i].value)
        entry["collating_sequence"] = collating
    return entry


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
        - implementor-name IS mnemonic-name [ON STATUS IS cond]
          [OFF STATUS IS cond] (e.g. `C01 IS TOP-OF-PAGE`, `CONSOLE IS CRT`)
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
        computers: dict[str, dict[str, Any]] = {}

        def _at_stop() -> bool:
            token = token_stream.peek(0)
            if not token:
                return True
            v = token.value.upper()
            if v in _body_stop:
                return True
            # In a CLASS-ID unit the REPOSITORY paragraph is the last thing
            # before ``FACTORY.`` / ``OBJECT.`` (or a ``METHOD-ID``) opens
            # the next unit; those belong to the program-level parser.
            if v == "METHOD-ID":
                return True
            if v in ("FACTORY", "OBJECT"):
                nxt = token_stream.peek(1)
                if nxt is not None and nxt.value == ".":
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
            elif v in ("SOURCE-COMPUTER", "OBJECT-COMPUTER"):
                token_stream.consume()
                pk = token_stream.peek(0)
                if pk and pk.value == ".":
                    token_stream.consume()
                # The entry is one sentence; it ends at its period (or at
                # the next paragraph header when the period is missing).
                entry_tokens: list[Any] = []
                while not token_stream.is_empty() and not _at_stop():
                    tok = token_stream.peek(0)
                    if tok is None or tok.type == TokenType.EOF:
                        break
                    if tok.value == ".":
                        token_stream.consume()
                        break
                    if tok.value.upper() in _CONFIGURATION_PARAGRAPHS:
                        break
                    token_stream.consume()
                    if tok.type not in _NOISE_TYPES:
                        entry_tokens.append(tok)
                computers[v] = _computer_paragraph(v, entry_tokens)
            else:
                token_stream.consume()

        result: dict[str, Any] = {"type": "configuration"}
        if config_location is not None:
            result["location"] = config_location
        if special_names:
            result["special_names"] = special_names
        if "SOURCE-COMPUTER" in computers:
            result["source_computer"] = computers["SOURCE-COMPUTER"]
        if "OBJECT-COMPUTER" in computers:
            result["object_computer"] = computers["OBJECT-COMPUTER"]
        return result

    def _parse_special_names_paragraph(
        self,
        token_stream: ITokenStream,
        stop_sections: set[str],
        stop_divs: tuple[str, ...],
    ) -> dict[str, Any]:
        """Parse clauses inside SPECIAL-NAMES paragraph.

        IBM Enterprise COBOL writes the whole paragraph as one sentence --
        ``C01 IS TOP-OF-PAGE CLASS HEX IS '0' THRU '9' SYMBOLIC CHARACTERS
        NUL IS 1 ...`` with a single closing period -- so a clause ends where
        the next clause starts, never merely at a period. Every clause's
        operand collection therefore stops at :func:`_at_clause_start`, and
        the paragraph itself ends at the next CONFIGURATION SECTION
        paragraph header (``REPOSITORY.`` in particular, whose own ``CLASS
        name IS 'java.class'`` entries are not SPECIAL-NAMES class
        conditions).
        """
        currency_sign: str | None = None
        currency_signs: list[dict[str, Any]] = []
        decimal_point_is_comma: bool = False
        class_definitions: list[dict[str, Any]] = []
        alphabet_definitions: list[dict[str, Any]] = []
        symbolic_characters: list[dict[str, Any]] = []
        mnemonic_definitions: list[dict[str, Any]] = []

        def _skip_noise() -> None:
            token_stream.skip_whitespace_and_comments()

        def _word(offset: int = 0) -> str:
            token = token_stream.peek(offset)
            return token.value.upper() if token is not None and token.value else ""

        def _at_para_end() -> bool:
            token = token_stream.peek(0)
            if not token or token.type == TokenType.EOF:
                return True
            v = token.value.upper()
            if v in stop_sections or v in _CONFIGURATION_PARAGRAPHS:
                return True
            return any(v == f"{kw} DIVISION" for kw in stop_divs)

        def _mnemonic_start(offset: int = 0) -> bool:
            # ``environment-name IS mnemonic-name`` or the name-less
            # ``UPSI-0 ON STATUS IS condition`` form.
            token = token_stream.peek(offset)
            if token is None or token.type in _LITERAL_TYPES or token.value == ".":
                return False
            nxt = _word(offset + 1)
            if nxt == "IS":
                return True
            return nxt in ("ON", "OFF") and _word(offset + 2) in ("STATUS", "IS")

        def _at_clause_start() -> bool:
            if _at_para_end():
                return True
            v = _word()
            return v == "." or v in _SPECIAL_NAMES_CLAUSES or _mnemonic_start()

        def _collect_operands() -> list[str]:
            values: list[str] = []
            while True:
                _skip_noise()
                if token_stream.is_empty() or _at_clause_start():
                    return values
                values.append(token_stream.consume().value)

        def _literal_value(token: Any) -> str:
            return str(token.value).strip("'\"")

        while True:
            _skip_noise()
            if token_stream.is_empty() or _at_para_end():
                break
            token = token_stream.peek(0)
            if not token:
                break
            v = token.value.upper()

            if v == "CURRENCY":
                token_stream.consume()
                # skip optional SIGN / IS
                for _kw in ("SIGN", "IS"):
                    _skip_noise()
                    if _word() == _kw:
                        token_stream.consume()
                _skip_noise()
                pk = token_stream.peek(0)
                if pk and pk.value and not _at_clause_start():
                    sign = _literal_value(pk)
                    token_stream.consume()
                    entry_currency: dict[str, Any] = {
                        "sign": sign,
                        "picture_symbol": None,
                    }
                    # [WITH] PICTURE SYMBOL literal
                    _skip_noise()
                    if _word() == "WITH" and _word(1) == "PICTURE":
                        token_stream.consume()
                        _skip_noise()
                    if _word() == "PICTURE" and _word(1) == "SYMBOL":
                        token_stream.consume()
                        token_stream.consume()
                        _skip_noise()
                        sym = token_stream.peek(0)
                        if sym is not None and sym.type in _LITERAL_TYPES:
                            entry_currency["picture_symbol"] = _literal_value(sym)
                            token_stream.consume()
                    currency_sign = sign
                    currency_signs.append(entry_currency)

            elif v == "DECIMAL-POINT":
                token_stream.consume()
                # skip optional IS
                _skip_noise()
                if _word() == "IS":
                    token_stream.consume()
                _skip_noise()
                if _word() == "COMMA":
                    decimal_point_is_comma = True
                    token_stream.consume()
                    # Honoured by the lexer (comma-decimal numeric literals)
                    # and by PictureClause (``,``/``.`` exchanged), both of
                    # which read the clause from the source up front.

            elif v in ("CLASS", "ALPHABET"):
                token_stream.consume()
                _skip_noise()
                name_tok = token_stream.peek(0)
                clause_name = name_tok.value if name_tok else ""
                if name_tok:
                    token_stream.consume()
                # [FOR ALPHANUMERIC | FOR NATIONAL] (IBM) and IS
                _skip_noise()
                if _word() == "FOR" and _word(1) in ("ALPHANUMERIC", "NATIONAL"):
                    token_stream.consume()
                    token_stream.consume()
                    _skip_noise()
                if _word() == "IS":
                    token_stream.consume()
                values = _collect_operands()
                if v == "CLASS":
                    class_definitions.append({"name": clause_name, "ranges": values})
                else:
                    alphabet_definitions.append({"name": clause_name, "values": values})

            elif v == "SYMBOLIC":
                token_stream.consume()
                _skip_noise()
                if _word() in ("CHARACTERS", "CHARACTER"):
                    token_stream.consume()
                    _skip_noise()
                if _word() == "FOR" and _word(1) in ("ALPHANUMERIC", "NATIONAL"):
                    token_stream.consume()
                    token_stream.consume()
                symbolic_characters.extend(
                    self._parse_symbolic_characters(token_stream)
                )

            elif token.value != "." and _mnemonic_start():
                # Mnemonic-name clause: implementor-name-1 IS mnemonic-name-1
                # [ON STATUS IS condition-1] [OFF STATUS IS condition-2]
                # e.g. `C01 IS TOP-OF-PAGE`, `CONSOLE IS CRT`,
                # `UPSI-0 IS SWITCH-1 ON STATUS IS SW1-ON OFF STATUS IS SW1-OFF`,
                # or, without a mnemonic-name, `UPSI-0 ON STATUS IS SW1-ON`.
                environment_name = token.value
                token_stream.consume()  # implementor-name
                entry: dict[str, Any] = {"environment_name": environment_name}
                _skip_noise()
                if _word() == "IS":
                    token_stream.consume()  # IS
                    _skip_noise()
                    name_tok = token_stream.peek(0)
                    entry["mnemonic_name"] = name_tok.value if name_tok else ""
                    if name_tok:
                        token_stream.consume()
                while True:
                    _skip_noise()
                    if _word() not in ("ON", "OFF"):
                        break
                    status_key = "on_status" if _word() == "ON" else "off_status"
                    token_stream.consume()  # ON / OFF
                    _skip_noise()
                    if _word() == "STATUS":
                        token_stream.consume()
                        _skip_noise()
                    if _word() == "IS":
                        token_stream.consume()
                        _skip_noise()
                    cond_tok = token_stream.peek(0)
                    if cond_tok:
                        entry[status_key] = cond_tok.value
                        token_stream.consume()
                mnemonic_definitions.append(entry)

            elif token.value == ".":
                token_stream.consume()  # clause separator

            elif v == "XML-SCHEMA":
                # XML-SCHEMA xml-schema-name IS {environment-name | literal}
                token_stream.consume()
                for _ in range(3):
                    _skip_noise()
                    if token_stream.is_empty() or _word() == "." or _at_para_end():
                        break
                    token_stream.consume()

            else:
                # Unknown clause -- skip its words.
                token_stream.consume()

        result: dict[str, Any] = {}
        if currency_sign is not None:
            result["currency_sign"] = currency_sign
            result["currency_signs"] = currency_signs
        if decimal_point_is_comma:
            result["decimal_point_is_comma"] = True
        if class_definitions:
            result["class_definitions"] = class_definitions
        if alphabet_definitions:
            result["alphabet_definitions"] = alphabet_definitions
        if symbolic_characters:
            result["symbolic_characters"] = symbolic_characters
        if mnemonic_definitions:
            result["mnemonic_definitions"] = mnemonic_definitions
        return result

    @staticmethod
    def _parse_symbolic_characters(token_stream: ITokenStream) -> list[dict[str, Any]]:
        """Parse the body of ``SYMBOLIC CHARACTERS``.

        ``{symbolic-character-1 ... {IS|ARE} integer-1 ...}... [IN
        alphabet-name]`` -- the n-th name takes the n-th ordinal position.
        A group is only taken when an integer follows its IS/ARE, so a
        following ``C01 IS TOP-OF-PAGE`` mnemonic clause (also ``word IS
        ...``) is left for the caller.
        """
        entries: list[dict[str, Any]] = []
        while True:
            token_stream.skip_whitespace_and_comments()
            # Look ahead over one group without consuming it.
            offset = 0
            names: list[str] = []
            while True:
                tok = token_stream.peek(offset)
                if tok is None or tok.value == "." or tok.type in _LITERAL_TYPES:
                    break
                if tok.type in _NOISE_TYPES:
                    offset += 1
                    continue
                if tok.value.upper() in ("IS", "ARE"):
                    break
                if tok.value.upper() in _SPECIAL_NAMES_CLAUSES:
                    # The next clause (``... TAB IS 10 CLASS HEX IS "0"
                    # THRU "9"``) is not a symbolic-character name.
                    break
                names.append(tok.value)
                offset += 1
            verb = token_stream.peek(offset)
            if not names or verb is None or verb.value.upper() not in ("IS", "ARE"):
                break
            offset += 1
            ordinals: list[int] = []
            while True:
                tok = token_stream.peek(offset)
                if tok is None:
                    break
                if tok.type in _NOISE_TYPES:
                    offset += 1
                    continue
                if (
                    tok.type not in _LITERAL_TYPES
                    or tok.type == TokenType.STRING_LITERAL
                    or not tok.value.isdigit()
                ):
                    # An ordinal is an integer, never the string literal
                    # ``"0"`` of a following CLASS clause.
                    break
                ordinals.append(int(tok.value))
                offset += 1
            if not ordinals:
                break
            for _ in range(offset):
                token_stream.consume()
            for name, ordinal in zip(names, ordinals, strict=False):
                entries.append({"name": name, "ordinal": ordinal, "alphabet": None})
        token_stream.skip_whitespace_and_comments()
        in_tok = token_stream.peek(0)
        if in_tok is not None and in_tok.value.upper() == "IN":
            token_stream.consume()
            token_stream.skip_whitespace_and_comments()
            alpha = token_stream.peek(0)
            if alpha is not None and alpha.value != ".":
                token_stream.consume()
                for entry in entries:
                    entry["alphabet"] = alpha.value
        return entries


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
        io_control: list[dict[str, Any]] | None = None

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

            if token_value == "I-O-CONTROL":
                # Its RERUN / SAME AREA / MULTIPLE FILE / APPLY entries were
                # read as a second FILE-CONTROL paragraph (the check below
                # matches any word ending in CONTROL) and dropped unseen.
                io_control = self._parse_io_control_paragraph(token_stream)
                continue

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
        if io_control is not None:
            result["io_control"] = io_control
        return result

    @staticmethod
    def _parse_io_control_paragraph(token_stream: ITokenStream) -> list[dict[str, Any]]:
        """Parse the I-O-CONTROL paragraph into one record per entry.

        Each entry (``RERUN ...``, ``SAME [RECORD|SORT|SORT-MERGE] AREA
        ...``, ``MULTIPLE FILE ...``, ``APPLY ...``) is kept as its clause
        word, its text and its line; an entry starts at a clause word and
        runs to the next one or to a period. The paragraph ends at the next
        section, division or FILE-CONTROL header.
        """
        token_stream.consume()  # I-O-CONTROL
        pk = token_stream.peek(0)
        if pk and pk.value == ".":
            token_stream.consume()

        entries: list[dict[str, Any]] = []
        current: list[Any] = []

        def _flush() -> None:
            if current:
                first = current[0]
                entries.append(
                    {
                        "clause": str(first.value).upper(),
                        "text": _entry_text(current),
                        "line": first.location.line if first.location else None,
                    }
                )
                current.clear()

        stop_words = {
            "CONFIGURATION",
            "INPUT-OUTPUT",
            "DATA",
            "PROCEDURE",
            "IDENTIFICATION",
            "FILE-CONTROL",
        }
        while not token_stream.is_empty():
            token = token_stream.peek(0)
            if token is None or token.type == TokenType.EOF:
                break
            value = token.value.upper()
            if value in stop_words or any(
                value == f"{kw} DIVISION"
                for kw in ("DATA", "PROCEDURE", "IDENTIFICATION")
            ):
                break
            token_stream.consume()
            if token.type in _NOISE_TYPES or value in (";", ","):
                continue
            if value == ".":
                _flush()
                continue
            if value in _IO_CONTROL_CLAUSES and current:
                _flush()
            current.append(token)
        _flush()
        return entries

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
                "I-O-CONTROL",
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
