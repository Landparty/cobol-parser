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

from typing import Any

from cobolparser.core.exceptions import (
    ParseError,
    TokenMismatch,
    UnexpectedEndOfInput,
)
from cobolparser.core.interfaces import ITokenStream
from cobolparser.lexer import TokenType
from cobolparser.models.ast_base import ASTNode, SourceLocation
from cobolparser.models.program import CobolDivision

from .base import BaseDivisionParser, at_division_boundary

#: PROGRAM-ID attributes IBM Enterprise COBOL accepts after the program name.
_PROGRAM_ATTRIBUTES: frozenset[str] = frozenset({"INITIAL", "COMMON", "RECURSIVE"})


def _unit_name(raw: str | None) -> str:
    """A class/method name as written, with a literal's quotes removed.

    Method names are alphanumeric literals in IBM Enterprise COBOL
    (``METHOD-ID. "deposit".``) so the quotes are not part of the name; a
    bare word is returned unchanged (case preserved -- Java names are
    case-sensitive).
    """
    text = (raw or "").strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ("'", '"'):
        return text[1:-1]
    return text


class IdentificationDivisionParser(BaseDivisionParser):
    """Parser for COBOL Identification Division.

    Handles extraction and parsing of program identification metadata including
    PROGRAM-ID, AUTHOR, INSTALLATION, DATE-WRITTEN, DATE-COMPILED, REMARKS,
    and SECURITY clauses.

    Implements the parse_division() and _create_ast_node() abstract methods
    from BaseDivisionParser.
    """

    division_name: str | None = "IDENTIFICATION"
    division_keywords: tuple = ("ID",)

    #: Clause keywords whose value is a COBOL-74 comment-entry (free
    #: documentation text). PROGRAM-ID deliberately excluded — its value is
    #: structured, not a comment-entry.
    _COMMENT_ENTRY_CLAUSES: frozenset = frozenset(
        {
            "AUTHOR",
            "INSTALLATION",
            "DATE-WRITTEN",
            "DATE-COMPILED",
            "REMARKS",
            "SECURITY",
        }
    )

    def _token_in_area_a(self, token: Any) -> bool:
        """True when *token* starts at or left of this division's own header
        column — the Area A position after ``normalize_fixed_format``
        (which preserves the fixed-format Area A/B split as indentation).
        Unknown columns conservatively count as Area A."""
        header_col = getattr(self, "_division_header_column", None)
        col = getattr(getattr(token, "location", None), "column", None)
        if header_col is None or col is None:
            return True
        return bool(col <= header_col)

    @staticmethod
    def _at_oo_unit_start(token_stream: ITokenStream, token_value: str) -> bool:
        """True at ``METHOD-ID`` or at a ``FACTORY.`` / ``OBJECT.`` paragraph
        header (the word immediately followed by the separator period)."""
        if token_value == "METHOD-ID":
            return True
        if token_value in ("FACTORY", "OBJECT"):
            nxt = token_stream.peek(1)
            return bool(nxt is not None and nxt.value == ".")
        return False

    def _at_comment_entry_aware_boundary(
        self, token_stream: ITokenStream, in_comment_entry: bool
    ) -> bool:
        """True at a *real* division boundary, honouring comment-entries.

        COBOL-74 comment-entry paragraphs (AUTHOR, SECURITY, REMARKS, ...)
        are pure documentation that ends only at the next entry starting in
        Area A — they may legally contain an entire phony program written in
        Area B (NIST OBNC1M does exactly that). So while a comment-entry is
        active, a division header indented into Area B (deeper than this
        division's own header) is documentation, not a boundary. Outside a
        comment-entry the column is deliberately ignored: free-form and
        loosely indented sources routinely place real division headers
        deeper than the IDENTIFICATION header, and those must keep
        terminating the division exactly as before.
        """
        if not at_division_boundary(token_stream):
            return False
        if not in_comment_entry:
            return True
        return self._token_in_area_a(token_stream.peek(0))

    def parse_division(self, token_stream: ITokenStream) -> dict[str, Any]:
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
        content: dict[str, Any] = {
            "program_id": None,
            # "PROGRAM" for a PROGRAM-ID unit, "CLASS" for a CLASS-ID unit
            # and "METHOD" for a METHOD-ID unit (IBM Enterprise COBOL
            # object-oriented syntax for Java interoperability), "FUNCTION"
            # for a FUNCTION-ID unit (a user-defined function, Enterprise
            # COBOL 6.4).
            "unit_kind": "PROGRAM",
            # PROGRAM-ID attributes in source order: INITIAL, COMMON,
            # RECURSIVE. Empty for a plain program.
            "program_attributes": [],
            # CLASS-ID only: the INHERITS class name, if any.
            "inherits": None,
            # FUNCTION-ID only: the ``AS literal`` external name, if any.
            "external_name": None,
            "author": None,
            "installation": None,
            "date_written": None,
            "date_compiled": None,
            "remarks": None,
            "security": None,
        }

        # Parse clauses until we reach next division or EOF. A COBOL-74
        # comment-entry (opened by an Area A AUTHOR/SECURITY/REMARKS/...
        # entry) stays "active" until the next Area A entry, so that
        # division-header-shaped documentation written in Area B inside it
        # (NIST OBNC1M embeds an entire phony program that way) is consumed
        # as comment text instead of terminating the division.
        in_comment_entry = False
        while not token_stream.is_empty():
            token = token_stream.peek(0)
            if not token:
                break

            token_value = token.value.upper()

            # Check if we've reached the next division. A bare keyword such
            # as DATA only counts when actually followed by DIVISION — the
            # word may appear inside a comment-entry — and while a
            # comment-entry is active, a header indented into Area B is
            # comment-entry documentation, not a boundary.
            if self._at_comment_entry_aware_boundary(token_stream, in_comment_entry):
                break

            # Parse specific clauses
            if token_value == "PROGRAM-ID":
                in_comment_entry = False
                content["program_id"] = self._parse_program_id(token_stream)
                content["program_attributes"] = list(self._program_attributes)
            elif token_value == "CLASS-ID":
                in_comment_entry = False
                class_name, inherits = self.parse_class_id_clause(token_stream)
                content["program_id"] = class_name
                content["unit_kind"] = "CLASS"
                content["inherits"] = inherits
            elif token_value == "METHOD-ID":
                in_comment_entry = False
                content["program_id"] = self.parse_method_id_clause(token_stream)
                content["unit_kind"] = "METHOD"
            elif token_value == "FUNCTION-ID":
                in_comment_entry = False
                name, external = self.parse_function_id_clause(token_stream)
                content["program_id"] = name
                content["unit_kind"] = "FUNCTION"
                content["external_name"] = external
            elif self._at_oo_unit_start(token_stream, token_value):
                # ``FACTORY.`` / ``OBJECT.`` / ``METHOD-ID.`` open the next
                # unit of a class definition (a class with no ENVIRONMENT
                # DIVISION goes straight from CLASS-ID to FACTORY); the
                # program-level parser takes over there.
                break
            elif token_value in self._COMMENT_ENTRY_CLAUSES:
                # Only an entry that itself starts in Area A opens an
                # Area B–swallowing comment-entry; a loosely indented source
                # that puts everything in "Area B" keeps today's behavior.
                in_comment_entry = self._token_in_area_a(token)
                key = token_value.lower().replace("-", "_")
                content[key] = self._parse_clause_value(
                    token_stream, in_comment_entry=in_comment_entry
                )
            else:
                # Unknown clause - skip it for error recovery. Per COBOL-74,
                # *any* entry starting in Area A ends an active
                # comment-entry — not just recognized clause keywords — so
                # an unknown Area A word closes the state before being
                # consumed (comment-entry continuation text is Area B).
                if in_comment_entry and self._token_in_area_a(token):
                    in_comment_entry = False
                token_stream.consume()

        # Validate mandatory PROGRAM-ID (or CLASS-ID / METHOD-ID for an
        # object-oriented unit, FUNCTION-ID for a user-defined function)
        if not content["program_id"]:
            raise ParseError(
                "PROGRAM-ID (or CLASS-ID / METHOD-ID / FUNCTION-ID) is mandatory "
                "in IDENTIFICATION DIVISION"
            )

        return content

    def _parse_program_id(self, token_stream: ITokenStream) -> str:
        """Parse PROGRAM-ID clause.

        Format: PROGRAM-ID[.] program-name [[IS] INITIAL|COMMON|RECURSIVE]...
                [PROGRAM] [.]

        In fixed-format COBOL, the elements may be on different lines:
            000200 PROGRAM-ID.
            000300     program-name.

        Supports the optional IS INITIAL / IS COMMON / IS RECURSIVE
        attributes (and the trailing PROGRAM word) of IBM Enterprise COBOL;
        the attributes seen are left in ``self._program_attributes``.

        Args:
            token_stream: Token stream positioned at PROGRAM-ID keyword

        Returns:
            Program name extracted from clause

        Raises:
            ParseError: If PROGRAM-ID syntax is invalid
        """
        # Consume PROGRAM-ID keyword
        token_stream.consume()
        self._program_attributes = []

        # The period after PROGRAM-ID is optional in IBM Enterprise COBOL
        # (``PROGRAM-ID program-name.`` is accepted by the compiler), so
        # accept both spellings rather than raising on the shorter one.
        token_stream.skip_whitespace_and_comments()
        period = token_stream.peek(0)
        if period is not None and period.value == ".":
            token_stream.consume()

        # Skip newlines and whitespace after the period (for fixed-format COBOL)
        token_stream.skip_whitespace_and_comments()

        # Get program name (next non-period token)
        if token_stream.is_empty():
            raise ParseError("Expected program name after PROGRAM-ID.")

        name_token = token_stream.consume()
        program_name = name_token.value

        # Optional attributes: ``[IS] INITIAL | COMMON | RECURSIVE``
        # (repeatable, in any order) followed by the optional word
        # ``PROGRAM`` -- ``PROGRAM-ID. X IS INITIAL PROGRAM.`` is the full
        # IBM form. Every attribute is recorded, in source order, so
        # analyzers can tell a program that *declared* itself re-entrant
        # (RECURSIVE) from one that merely calls itself.
        token_stream.skip_whitespace_and_comments()
        while not token_stream.is_empty():
            token = token_stream.peek(0)
            val = token.value.upper() if token and token.value else ""
            if val == "IS":
                token_stream.consume()
                token_stream.skip_whitespace_and_comments()
                continue
            if val in _PROGRAM_ATTRIBUTES:
                self._program_attributes.append(val)
                token_stream.consume()
                token_stream.skip_whitespace_and_comments()
                continue
            if val == "PROGRAM" and self._program_attributes:
                token_stream.consume()
                token_stream.skip_whitespace_and_comments()
                continue
            break

        # Expect period after program name (or after IS clause if present).
        # IBM Enterprise COBOL tolerates a missing period here (verified
        # against real mainframe compiler behavior) -- treating it as a hard
        # error instead of a warning previously cascaded into "No
        # recognizable COBOL division found near 'AUTHOR'" for every such
        # program, since the raised ParseError aborted IDENTIFICATION
        # DIVISION parsing before the following clauses (AUTHOR,
        # DATE-WRITTEN, ...) were ever reached. Both exceptions
        # token_stream.expect() can raise here are tolerated: TokenMismatch
        # (something else follows the name) and UnexpectedEndOfInput (the
        # stream ends right after the name -- the same truncated-file shape
        # the missing-period tolerance is meant to cover).
        try:
            token_stream.expect(".")
        except (TokenMismatch, UnexpectedEndOfInput):
            add_warning = getattr(self.host, "add_warning", None)
            if callable(add_warning):
                add_warning(
                    f"Missing '.' after program name '{program_name}' "
                    "in PROGRAM-ID clause (tolerated)"
                )

        return program_name

    @staticmethod
    def parse_class_id_clause(token_stream: ITokenStream) -> tuple[str, str | None]:
        """Parse ``CLASS-ID[.] class-name [INHERITS [FROM] class-name-2] [.]``.

        The stream is positioned at the ``CLASS-ID`` word. Returns
        ``(class_name, inherits)``. Shared with :class:`CobolParser`, which
        meets the same clause without a preceding ``IDENTIFICATION
        DIVISION`` header (the header is optional in front of every unit of
        an object-oriented compilation unit).
        """
        token_stream.consume()  # CLASS-ID
        token_stream.skip_whitespace_and_comments()
        period = token_stream.peek(0)
        if period is not None and period.value == ".":
            token_stream.consume()
        token_stream.skip_whitespace_and_comments()
        if token_stream.is_empty():
            raise ParseError("Expected class name after CLASS-ID.")
        class_name = _unit_name(token_stream.consume().value)
        inherits: str | None = None
        token_stream.skip_whitespace_and_comments()
        while not token_stream.is_empty():
            token = token_stream.peek(0)
            val = token.value.upper() if token and token.value else ""
            if val in ("IS", "FROM"):
                token_stream.consume()
            elif val == "INHERITS":
                token_stream.consume()
                token_stream.skip_whitespace_and_comments()
                nxt = token_stream.peek(0)
                if nxt is not None and nxt.value and nxt.value.upper() == "FROM":
                    token_stream.consume()
                    token_stream.skip_whitespace_and_comments()
                    nxt = token_stream.peek(0)
                if nxt is not None and nxt.value and nxt.value != ".":
                    inherits = _unit_name(nxt.value)
                    token_stream.consume()
            elif val == ".":
                token_stream.consume()
                break
            else:
                break
            token_stream.skip_whitespace_and_comments()
        return class_name, inherits

    @staticmethod
    def parse_method_id_clause(token_stream: ITokenStream) -> str:
        """Parse ``METHOD-ID[.] method-name [.]``.

        The stream is positioned at the ``METHOD-ID`` word. IBM requires
        the method name to be an alphanumeric literal (Java method names
        are case-sensitive); a bare word is accepted too. Returns the
        name with its quotes stripped.
        """
        token_stream.consume()  # METHOD-ID
        token_stream.skip_whitespace_and_comments()
        period = token_stream.peek(0)
        if period is not None and period.value == ".":
            token_stream.consume()
        token_stream.skip_whitespace_and_comments()
        if token_stream.is_empty():
            raise ParseError("Expected method name after METHOD-ID.")
        method_name = _unit_name(token_stream.consume().value)
        token_stream.skip_whitespace_and_comments()
        # ``METHOD-ID. "name" OVERRIDE.`` (COBOL 2002; tolerated)
        nxt = token_stream.peek(0)
        if nxt is not None and nxt.value and nxt.value.upper() == "OVERRIDE":
            token_stream.consume()
            token_stream.skip_whitespace_and_comments()
            nxt = token_stream.peek(0)
        if nxt is not None and nxt.value == ".":
            token_stream.consume()
        return method_name

    @staticmethod
    def parse_function_id_clause(
        token_stream: ITokenStream,
    ) -> tuple[str, str | None]:
        """Parse ``FUNCTION-ID[.] function-name [AS literal] [.]``.

        A user-defined function (IBM Enterprise COBOL 6.4). The stream is
        positioned at the ``FUNCTION-ID`` word. Returns ``(name,
        external_name)``, the latter the ``AS`` literal without its quotes,
        or None.
        """
        token_stream.consume()  # FUNCTION-ID
        token_stream.skip_whitespace_and_comments()
        period = token_stream.peek(0)
        if period is not None and period.value == ".":
            token_stream.consume()
        token_stream.skip_whitespace_and_comments()
        if token_stream.is_empty():
            raise ParseError("Expected function name after FUNCTION-ID.")
        name = _unit_name(token_stream.consume().value)
        external: str | None = None
        token_stream.skip_whitespace_and_comments()
        nxt = token_stream.peek(0)
        if nxt is not None and nxt.value and nxt.value.upper() == "AS":
            token_stream.consume()
            token_stream.skip_whitespace_and_comments()
            literal = token_stream.peek(0)
            if literal is not None and literal.value and literal.value != ".":
                external = _unit_name(token_stream.consume().value)
            token_stream.skip_whitespace_and_comments()
            nxt = token_stream.peek(0)
        if nxt is not None and nxt.value == ".":
            token_stream.consume()
        return name, external

    def _parse_clause_value(
        self, token_stream: ITokenStream, in_comment_entry: bool = False
    ) -> str:
        """Parse a general clause value.

        Format: CLAUSE-KEYWORD. value-text.

        Collects all tokens between the keyword and period as the clause value.

        Args:
            token_stream: Token stream positioned at clause keyword
            in_comment_entry: True when the clause is an Area A
                comment-entry: Area B division-header-shaped text inside the
                value is documentation rather than a boundary, and — per
                COBOL-74, where a comment-entry ends at the next entry
                starting in Area A — any line-starting Area A token ends the
                value (comment-entry continuation text is Area B)

        Returns:
            Clause value as a string

        Raises:
            ParseError: If clause syntax is invalid
        """
        # Consume clause keyword (AUTHOR, INSTALLATION, etc.)
        keyword_token = token_stream.consume()
        last_line = getattr(getattr(keyword_token, "location", None), "line", None)

        # Expect period after clause keyword
        try:
            token_stream.expect(".")
        except TokenMismatch as e:
            _t220 = token_stream.peek(0)
            raise ParseError(
                "Expected '.' after clause keyword",
                line_number=(
                    (_t220.location.line if _t220 is not None else 1)
                    if not token_stream.is_empty()
                    else 1
                ),
            ) from e

        # The lexer hands a comment-entry over verbatim, one COMMENT_ENTRY
        # token per line (see lexer._comment_entry_starts): free text such
        # as ``JOHN O'BRIEN`` or ``01/02/99`` is not COBOL words and must not
        # be re-tokenized. Lines are joined with one space; the entry's own
        # closing period is dropped (as the token path below always has),
        # but interior periods (``J. SMITH``) are part of the text.
        entry_lines: list[str] = []
        while not token_stream.is_empty():
            token_stream.skip_whitespace_and_comments()
            token = token_stream.peek(0)
            if token is None or token.type != TokenType.COMMENT_ENTRY:
                break
            entry_lines.append(token.value)
            token_stream.consume()
            last_line = getattr(getattr(token, "location", None), "line", last_line)
        if entry_lines:
            text = " ".join(entry_lines)
            if text.endswith(".") or in_comment_entry:
                return text[:-1].rstrip() if text.endswith(".") else text
            # A loosely indented, unterminated entry: fall through and keep
            # collecting ordinary tokens up to the period, as before.

        # Collect value tokens until period
        # Also stop at division boundaries to avoid consuming the next division header
        value_tokens = entry_lines[:]
        while not token_stream.is_empty():
            token = token_stream.peek(0)
            if token and token.value == ".":
                token_stream.consume()
                break
            # A comment-entry ends at the next entry starting in Area A
            # (COBOL-74). Only a *line-starting* token counts: in loosely
            # indented free-form sources, mid-line tokens can sit at or left
            # of the header column without being entries.
            if token and in_comment_entry:
                cur_line = getattr(getattr(token, "location", None), "line", None)
                starts_line = (
                    cur_line is not None
                    and last_line is not None
                    and cur_line != last_line
                )
                if starts_line and self._token_in_area_a(token):
                    break
            # Stop at division boundaries without consuming them. A bare
            # keyword such as DATA only counts when actually followed by
            # DIVISION — comment-entries are free text and may contain it —
            # and inside an Area A comment-entry, an Area B header-shaped
            # sequence is comment text too.
            if token and self._at_comment_entry_aware_boundary(
                token_stream, in_comment_entry
            ):
                break
            if token:
                value_tokens.append(token.value)
                token_stream.consume()
                cur_line = getattr(getattr(token, "location", None), "line", None)
                if cur_line is not None:
                    last_line = cur_line
            else:
                break

        # Return collected value or empty string
        return " ".join(value_tokens) if value_tokens else ""

    def _create_ast_node(
        self,
        division_token: Any,
        division_content: dict[str, Any],
        start_location: SourceLocation,
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
        division_node.metadata.update(
            {
                "program_id": division_content.get("program_id"),
                "unit_kind": division_content.get("unit_kind", "PROGRAM"),
                "program_attributes": list(
                    division_content.get("program_attributes") or []
                ),
                "inherits": division_content.get("inherits"),
                "author": division_content.get("author"),
                "installation": division_content.get("installation"),
                "date_written": division_content.get("date_written"),
                "date_compiled": division_content.get("date_compiled"),
                "remarks": division_content.get("remarks"),
                "security": division_content.get("security"),
            }
        )
        if division_content.get("unit_kind") == "FUNCTION":
            division_node.metadata["external_name"] = division_content.get(
                "external_name"
            )

        return division_node
