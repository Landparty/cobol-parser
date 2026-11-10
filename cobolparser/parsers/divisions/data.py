"""Data Division parser for COBOL programs.

This module implements parsing of the Data Division which contains:
- FILE SECTION: File descriptions and records
- WORKING-STORAGE SECTION: Working variable definitions
- LOCAL-STORAGE SECTION: Local variable definitions
- LINKAGE SECTION: Program parameter definitions

The :class:`DataDivisionParser` owns the section scan loop, the level-number
hierarchy building, and the AST node creation. The detailed entry parsing is
delegated to focused collaborators:

- :class:`~.data_clauses.DataItemClauseParser` — data-description entries and
  their clauses (PICTURE, VALUE, USAGE, OCCURS, ...)
- :class:`~.data_file_description.FileDescriptionClauseParser` — FD/SD
  file-description clause capture
- :class:`~.data_special_entries.SpecialEntryParser` — level-88 condition
  names, level-66 RENAMES, and data-division EXEC SQL blocks
"""

import re
from typing import Any

from cobolparser.core.interfaces import ITokenStream
from cobolparser.lexer import TokenType
from cobolparser.models.ast_base import ASTNode, SourceLocation
from cobolparser.models.data_items import (
    CobolDataItem,
    ConditionNameItem,
    RenamesItem,
)
from cobolparser.models.program import CobolDivision, CobolSection
from cobolparser.models.sql_statements import ExecSQLStatement
from cobolparser.parsers.statements._utils import (
    exec_sql_interface,
    peek_past_noise,
    skip_whitespace,
)

from .base import BaseDivisionParser, at_division_boundary
from .data_clauses import _DIVISION_TOKEN_TYPES, DataItemClauseParser
from .data_file_description import FileDescriptionClauseParser
from .data_report_description import ReportDescriptionClauseParser
from .data_special_entries import SpecialEntryParser

# Usages that only make sense on a numeric item.  A group USAGE of one of
# these is not pushed onto an alphanumeric child (which the compiler would
# reject anyway): leaving it DISPLAY keeps its width the PICTURE's width
# instead of inventing a packed/binary size for a PIC X.
_NUMERIC_ONLY_USAGES: frozenset[str] = frozenset(
    {
        "BINARY",
        "COMP",
        "COMP-3",
        "COMP-4",
        "COMP-5",
        "COMPUTATIONAL",
        "COMPUTATIONAL-3",
        "COMPUTATIONAL-4",
        "COMPUTATIONAL-5",
        "PACKED-DECIMAL",
    }
)
_REPEAT_COUNT_RE = re.compile(r"\(\d+\)")
_NUMERIC_PIC_CHARS = frozenset("S9VP")


def _at_unit_boundary(token_stream: ITokenStream, value_upper: str) -> bool:
    """True at ``END PROGRAM`` / ``END FUNCTION`` or a header-less
    ``PROGRAM-ID`` / ``FUNCTION-ID``: the end of this program's DATA
    DIVISION when it has no PROCEDURE DIVISION. Reading past them swallowed
    the next unit."""
    if value_upper in ("PROGRAM-ID", "FUNCTION-ID"):
        return True
    if value_upper != "END":
        return False
    nxt = token_stream.peek(1)
    offset = 1
    while nxt is not None and nxt.type.name == "NEWLINE":
        offset += 1
        nxt = token_stream.peek(offset)
    return nxt is not None and (nxt.value or "").upper() in ("PROGRAM", "FUNCTION")


def _is_numeric_picture(item: CobolDataItem) -> bool:
    """True when *item* has a plain (unedited) numeric PICTURE."""
    picture = item.picture_clause
    if picture is None or picture.is_edited:
        return False
    body = _REPEAT_COUNT_RE.sub("", picture.pattern.upper())
    return bool(body) and set(body) <= _NUMERIC_PIC_CHARS


def propagate_group_usage_and_sign(
    items: list[Any],
    usage: str | None = None,
    sign_clause: str | None = None,
) -> None:
    """Push a group's USAGE and SIGN clauses down to its subordinates.

    IBM Enterprise COBOL: a USAGE (or SIGN) clause written on a group item
    applies to every subordinate elementary item, and an entry that states
    its own clause overrides it for itself and everything below it.  Without
    this, ``05 G COMP-3. 10 A PIC S9(5).`` sized ``A`` as five DISPLAY
    bytes instead of three packed ones, and every offset after it drifted.

    Decided after clause parsing (``usage_explicit`` is set by
    ``CobolDataItem.set_usage``, which the clause loop calls).  Only entries with
    no USAGE clause of their own inherit; a subordinate group that inherits
    is re-labelled too so the AST says what the storage is, but its
    ``usage_explicit`` stays False.  SIGN is only stamped on signed numeric
    elementary items, the only ones it can describe.
    """
    for item in items:
        if not isinstance(item, CobolDataItem):
            continue
        item_usage = usage
        if item.group_usage is not None:
            # ``GROUP-USAGE NATIONAL``: the group and everything below it
            # that states no USAGE of its own is national.
            item_usage = item.group_usage
            if not item.usage_explicit:
                item.usage = item.group_usage
        elif item.usage_explicit:
            item_usage = item.usage
        elif usage is not None and (
            usage.upper() not in _NUMERIC_ONLY_USAGES
            or item.picture_clause is None
            or _is_numeric_picture(item)
        ):
            item.usage = usage
        children = [c for c in item.children if isinstance(c, CobolDataItem)]
        if children:
            propagate_group_usage_and_sign(
                children, item_usage, item.sign_clause or sign_clause
            )
        elif (
            item.sign_clause is None
            and sign_clause is not None
            and item.picture_clause is not None
            and item.picture_clause.is_signed
        ):
            item.sign_clause = sign_clause


# Hoisted out of _parse_section -- these were being rebuilt as set
# literals on every call.
_SECTION_KEYWORDS: frozenset[str] = frozenset(
    {
        "SECTION",
        "FILE",
        "WORKING-STORAGE",
        "LOCAL-STORAGE",
        "LINKAGE",
        "DATA",
        "PROCEDURE",
        "ENVIRONMENT",
        "IDENTIFICATION",
    }
)
# REPORT SECTION joined this set on 2026-09-02: its RD entries and report
# groups are parsed (see _parse_section's ``section_name == "REPORT"``
# branches and data_report_description.py) instead of skipped.
_SECTION_BREAK_HEADERS: frozenset[str] = frozenset(
    {"FILE", "WORKING-STORAGE", "LOCAL-STORAGE", "LINKAGE", "REPORT"}
)
# SCREEN SECTION and COMMUNICATION SECTION have their own grammars
# (screen-field clauses, CD entries) that this parser does not model. They
# must still break any section scan that's currently in progress --
# otherwise their content (which also starts with level numbers) is
# silently absorbed as bogus nested items of whatever section preceded them
# (usually WORKING-STORAGE). See _skip_section.
_UNSUPPORTED_SECTION_HEADERS: frozenset[str] = frozenset({"SCREEN", "COMMUNICATION"})

#: Screen-description clause words that can follow a level number in place of
#: a screen-item name (``05 LINE 1 COLUMN 7 ...``). The lexer makes several
#: of them plain identifiers, so they are told apart by spelling.
_SCREEN_CLAUSE_WORDS: frozenset[str] = frozenset(
    {
        "FILLER",
        "LINE",
        "LINES",
        "COLUMN",
        "COL",
        "PLUS",
        "BLANK",
        "BELL",
        "BEEP",
        "BLINK",
        "HIGHLIGHT",
        "LOWLIGHT",
        "REVERSE-VIDEO",
        "UNDERLINE",
        "FOREGROUND-COLOR",
        "FOREGROUND-COLOUR",
        "BACKGROUND-COLOR",
        "BACKGROUND-COLOUR",
        "VALUE",
        "PIC",
        "PICTURE",
        "USING",
        "FROM",
        "TO",
        "AUTO",
        "AUTO-SKIP",
        "SECURE",
        "NO-ECHO",
        "REQUIRED",
        "FULL",
        "ERASE",
        "EOL",
        "EOS",
        "SIGN",
        "JUSTIFIED",
        "JUST",
        "BLANK-WHEN-ZERO",
        "USAGE",
        "OCCURS",
        "GLOBAL",
        "PROMPT",
        "SIZE",
        "CONTROL",
    }
)
_NOISE_TOKEN_TYPES: frozenset[TokenType] = frozenset(
    {TokenType.NEWLINE, TokenType.WHITESPACE, TokenType.COMMENT}
)
#: Screen-field clauses whose operand is a data item: ``FROM`` is DISPLAYed,
#: ``TO`` is stored by ACCEPT, ``USING`` is both.
_SCREEN_DATA_CLAUSES: frozenset[str] = frozenset({"USING", "FROM", "TO"})
#: Screen-field clauses whose value may be a data item rather than a literal
#: (``LINE WS-ROW``, ``FOREGROUND-COLOR IS WS-COLOR``): read when the screen
#: is displayed, so the item is used.
_SCREEN_VALUE_CLAUSES: frozenset[str] = frozenset(
    {
        "LINE",
        "COLUMN",
        "COL",
        "FOREGROUND-COLOR",
        "FOREGROUND-COLOUR",
        "BACKGROUND-COLOR",
        "BACKGROUND-COLOUR",
        "SIZE",
        "CONTROL",
    }
)
#: Words that may sit between such a clause and its value.
_SCREEN_VALUE_NOISE: frozenset[str] = frozenset({"NUMBER", "IS", "PLUS", "+", "-"})


class DataDivisionParser(BaseDivisionParser):
    """Parser for COBOL Data Division.

    Handles data structure definitions with section support.
    Supports FILE, WORKING-STORAGE, LOCAL-STORAGE, and LINKAGE sections.
    """

    division_name: str | None = "DATA"
    division_keywords: tuple = ()

    def __init__(self) -> None:
        """Initialize the Data Division parser and its entry collaborators."""
        super().__init__()
        self._clause_parser = DataItemClauseParser(self)
        self._fd_parser = FileDescriptionClauseParser()
        self._rd_parser = ReportDescriptionClauseParser()
        self._special_entries = SpecialEntryParser(self)

    def parse_division(self, token_stream: ITokenStream) -> dict[str, Any]:
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
        sections: dict[str, Any] = {}

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
            if _at_unit_boundary(token_stream, token_value):
                break

            # Parse specific sections
            if token_value == "FILE":
                sections["file"] = self._parse_section(token_stream, "FILE")
            elif token_value == "WORKING-STORAGE":
                sections["working_storage"] = self._parse_section(
                    token_stream, "WORKING-STORAGE"
                )
            elif token_value == "LOCAL-STORAGE":
                sections["local_storage"] = self._parse_section(
                    token_stream, "LOCAL-STORAGE"
                )
            elif token_value == "LINKAGE":
                sections["linkage"] = self._parse_section(token_stream, "LINKAGE")
            elif token_value == "REPORT" and self._next_is_section_keyword(
                token_stream
            ):
                sections["report"] = self._parse_section(token_stream, "REPORT")
            elif token_value in _UNSUPPORTED_SECTION_HEADERS and (
                self._next_is_section_keyword(token_stream)
            ):
                sections[token_value.lower()] = self._skip_section(
                    token_stream, token_value
                )
            else:
                # Unknown section - skip it for error recovery
                token_stream.consume()

        return sections

    def _parse_section(
        self, token_stream: ITokenStream, section_name: str
    ) -> dict[str, Any]:
        """Parse a data section.

        Format: SECTION-NAME SECTION. [data-items]

        Args:
            token_stream: Token stream positioned at section keyword
            section_name: Name of the section (FILE, WORKING-STORAGE, etc.)

        Returns:
            Dictionary containing section content with parsed data items
        """
        # Capture the section keyword's own location before consuming it (the
        # AST node must report where this section actually starts, not its
        # parent division's location).
        section_token = token_stream.peek(0)
        section_location = section_token.location if section_token else None

        # Consume section keyword
        token_stream.consume()

        # Consume 'SECTION' keyword if present
        _dt = token_stream.peek()
        if _dt and _dt.value and _dt.value.upper() == "SECTION":
            token_stream.consume()

        # Consume period if present
        _dp = token_stream.peek()
        if _dp and _dp.type == TokenType.PERIOD:
            token_stream.consume()

        # Parse data items until we reach next section or division
        data_items: list[ConditionNameItem | RenamesItem | CobolDataItem] = []
        exec_sql_items: list[ExecSQLStatement] = []
        paren_depth = 0  # Track nesting depth of parentheses
        current_fd_name: str | None = None  # FD/SD file name for FILE SECTION items
        # FD/SD clauses (BLOCK CONTAINS, RECORD, LABEL, etc.) for the file the
        # current 01-level records belong to. Captured rather than discarded so
        # the record layout's physical attributes survive into the AST.
        current_fd_clauses: dict[str, Any] = {}
        # Whether the current record's file description used "FD" or "SD" --
        # an SD (sort/merge work file) is not a real file a program OPENs, and
        # downstream tooling (e.g. a boundary inventory) needs to tell the two
        # apart rather than treating every FILE SECTION entry as an FD.
        current_fd_record_type: str | None = None
        # REPORT SECTION: the RD every following report group belongs to,
        # and its captured clauses (PAGE LIMIT, CONTROLS, ...).
        current_rd_name: str | None = None
        current_rd_clauses: dict[str, Any] = {}
        report_group = section_name == "REPORT"
        # FILE SECTION: report name (upper) -> the FD whose ``REPORT IS``
        # names it. A report file has no record description, so this is the
        # only place the link survives into the AST (section metadata
        # ``report_files``).
        report_files: dict[str, str] = {}

        while not token_stream.is_empty():
            token = token_stream.peek()
            if not token:
                break

            tok_type = token.type
            tok_value = token.value

            # Check if we've reached next section/division (by token type, not just value check)
            if tok_type in _DIVISION_TOKEN_TYPES:
                break

            # Cheap parenthesis tracking before any keyword work.
            if tok_value == "(":
                paren_depth += 1
                token_stream.consume()
                continue
            if tok_value == ")":
                paren_depth -= 1
                token_stream.consume()
                continue

            # Compute upper-cased value once per iteration -- the next two
            # checks each need it (and several deeper branches also do).
            value_upper = tok_value.upper() if tok_value else ""

            # Stop when we encounter the next section header or division header.
            if value_upper in _SECTION_BREAK_HEADERS or value_upper in (
                _UNSUPPORTED_SECTION_HEADERS
            ):
                next_token = token_stream.peek(1)
                if (
                    next_token
                    and next_token.value
                    and next_token.value.upper() == "SECTION"
                ):
                    break

            # Also check for section keywords that appear as identifiers
            if value_upper in _SECTION_KEYWORDS and tok_type != TokenType.IDENTIFIER:
                break

            # A division header split across source lines ("PROCEDURE" at the
            # end of one line, "DIVISION." on the next) reaches this scanner
            # as plain IDENTIFIER tokens — stop without consuming it.
            if value_upper in ("IDENTIFICATION", "ENVIRONMENT", "PROCEDURE"):
                if at_division_boundary(token_stream):
                    break
            if _at_unit_boundary(token_stream, value_upper):
                break

            # In FILE SECTION, detect FD/SD declarations to build record-to-file mapping
            if (
                section_name == "FILE"
                and paren_depth == 0
                and (
                    tok_type in (TokenType.FD, TokenType.SD)
                    or (
                        tok_type == TokenType.IDENTIFIER and value_upper in ("FD", "SD")
                    )
                )
            ):
                current_fd_record_type = "SD" if value_upper == "SD" else "FD"
                token_stream.consume()  # consume FD/SD
                # The file name may start the next line (``FD`` alone on a
                # line); a bare peek saw the NEWLINE and lost the name.
                skip_whitespace(token_stream)
                fd_name_tok = token_stream.peek()
                if fd_name_tok and fd_name_tok.type == TokenType.IDENTIFIER:
                    current_fd_name = fd_name_tok.value
                    token_stream.consume()  # consume file name
                # Capture the FD/SD clauses (instead of discarding them) so the
                # file's physical layout (block/record sizes, recording mode,
                # labels, code set, EXTERNAL/GLOBAL) is preserved in the AST.
                current_fd_clauses = self._parse_fd_clauses(token_stream)
                if current_fd_name is not None:
                    for report in current_fd_clauses.get("report_names", []):
                        report_files[report.upper()] = current_fd_name
                continue

            # In REPORT SECTION, an RD entry introduces the report the
            # following 01-level report groups describe.
            if (
                report_group
                and paren_depth == 0
                and tok_type == TokenType.IDENTIFIER
                and value_upper == "RD"
            ):
                token_stream.consume()  # RD
                skip_whitespace(token_stream)
                rd_name_tok = token_stream.peek()
                if rd_name_tok and rd_name_tok.type == TokenType.IDENTIFIER:
                    current_rd_name = rd_name_tok.value
                    token_stream.consume()
                current_rd_clauses = self._rd_parser.parse_rd_clauses(token_stream)
                continue

            # Parse EXEC SQL blocks that appear in the data division
            # (e.g. DCLGEN-generated DECLARE TABLE or INCLUDE SQLCA)
            is_exec = tok_type == TokenType.EXEC or (
                tok_type == TokenType.IDENTIFIER and value_upper == "EXEC"
            )
            if is_exec and paren_depth == 0:
                next_tok, _ = peek_past_noise(token_stream, 1)
                if exec_sql_interface(next_tok) is not None:
                    sql_stmt = self._parse_exec_sql_in_data(token_stream)
                    if sql_stmt is not None:
                        exec_sql_items.append(sql_stmt)
                    continue

            # Try to parse a data item (should start with level number, but not inside parentheses)
            if tok_type == TokenType.LEVEL_NUMBER and paren_depth == 0:
                try:
                    lvl = int(tok_value)
                except (ValueError, TypeError):
                    lvl = -1

                if lvl == 88:
                    cond_item = self._parse_condition_name_item(token_stream)
                    if cond_item:
                        data_items.append(cond_item)
                elif lvl == 66:
                    renames_item = self._parse_renames_item(token_stream)
                    if renames_item:
                        data_items.append(renames_item)
                else:
                    data_item = self._parse_data_item(
                        token_stream, report_group=report_group
                    )
                    if data_item:
                        if report_group and data_item.level == 1:
                            if current_rd_name is not None:
                                data_item.set_metadata(
                                    "rd_report_name", current_rd_name
                                )
                            data_item.set_metadata(
                                "rd_clauses", dict(current_rd_clauses)
                            )
                        # Tag 01-level FILE SECTION records with their parent FD name
                        if (
                            section_name == "FILE"
                            and data_item.level == 1
                            and current_fd_name is not None
                        ):
                            data_item.set_metadata("fd_file_name", current_fd_name)
                            if current_fd_clauses:
                                data_item.set_metadata(
                                    "fd_clauses", dict(current_fd_clauses)
                                )
                            if current_fd_record_type is not None:
                                data_item.set_metadata(
                                    "fd_record_type", current_fd_record_type
                                )
                        data_items.append(data_item)
            else:
                # Skip unexpected tokens
                token_stream.consume()

        # Build hierarchical structure based on level numbers
        hierarchical_items = self._build_data_hierarchy(data_items)

        result: dict[str, Any] = {
            "type": section_name.lower().replace("-", "_"),
            "data_items": hierarchical_items,
            "exec_sql_items": exec_sql_items,
        }
        if report_files:
            result["report_files"] = report_files
        if section_location is not None:
            result["location"] = section_location
        return result

    @staticmethod
    def _next_is_section_keyword(token_stream: ITokenStream) -> bool:
        """True if the token after the current one is the SECTION keyword.

        Guards SCREEN/REPORT/COMMUNICATION dispatch against a same-spelled
        non-header use reaching this top-level scan (e.g. an FD's
        ``REPORT IS name`` clause) -- mirrors the lookahead
        ``_parse_section``'s own break check already uses for these headers.
        """
        next_token = token_stream.peek(1)
        return bool(
            next_token and next_token.value and next_token.value.upper() == "SECTION"
        )

    def _skip_section(
        self, token_stream: ITokenStream, section_name: str
    ) -> dict[str, Any]:
        """Consume a SCREEN/REPORT/COMMUNICATION SECTION header and its body.

        These sections have their own grammars (screen-field clauses,
        RD/report-group entries, CD entries) that this parser does not
        model. Rather than let their level-numbered content fall through to
        the generic data-item scanner -- which would misparse screen/report
        clause keywords (COLUMN, TYPE, LINE, ...) as bogus nested data items
        -- the header is consumed and the body is discarded token-by-token up
        to the next section or division boundary, so downstream consumers
        see an (empty) section keyed by its real name instead of corrupted
        WORKING-STORAGE data.

        Args:
            token_stream: Token stream positioned at the section keyword
            section_name: Name of the section (SCREEN, REPORT, COMMUNICATION)

        Returns:
            Dictionary containing an empty section body (no data items)
        """
        section_token = token_stream.peek(0)
        section_location = section_token.location if section_token else None

        # errors=0/warnings=0 must not imply a complete AST (repo convention
        # -- see parser.md's silent-drop audits): flag the discard so
        # consumers relying on the warnings channel see it, even though the
        # section is intentionally unparsed rather than a parse failure.
        add_warning = getattr(self.host, "add_warning", None)
        if callable(add_warning):
            line = getattr(section_location, "line", None)
            where = f" at line {line}" if line else ""
            add_warning(
                f"{section_name} SECTION{where} is not supported; its "
                "content (including any data item declared under it) is "
                "skipped and not represented in the AST"
            )

        # Consume section keyword, optional 'SECTION' keyword, and period --
        # same header shape as _parse_section.
        token_stream.consume()
        _dt = token_stream.peek()
        if _dt and _dt.value and _dt.value.upper() == "SECTION":
            token_stream.consume()
        _dp = token_stream.peek()
        if _dp and _dp.type == TokenType.PERIOD:
            token_stream.consume()

        # Discard the body until the next section/division header. A SCREEN
        # SECTION still says which data items its fields display and accept
        # (USING / FROM / TO) and what its screen items are called, so those
        # are kept (#501): without them every bound WORKING-STORAGE item
        # read as unused and every DISPLAY/ACCEPT of a screen as undefined.
        screen = section_name.upper() == "SCREEN"
        screen_items: list[dict[str, Any]] = []
        screen_references: list[dict[str, Any]] = []
        entry_start = True  # the next level number starts an entry
        expect_name: int | None = None  # level number just seen
        expect_operand: str | None = None  # USING / FROM / TO just seen
        reference: dict[str, Any] | None = None  # operand being collected
        while not token_stream.is_empty():
            token = token_stream.peek()
            if not token:
                break

            tok_type = token.type
            tok_value = token.value

            if tok_type in _DIVISION_TOKEN_TYPES:
                break

            value_upper = tok_value.upper() if tok_value else ""

            if value_upper in _SECTION_BREAK_HEADERS or value_upper in (
                _UNSUPPORTED_SECTION_HEADERS
            ):
                next_token = token_stream.peek(1)
                if (
                    next_token
                    and next_token.value
                    and next_token.value.upper() == "SECTION"
                ):
                    break

            if value_upper in ("IDENTIFICATION", "ENVIRONMENT", "PROCEDURE"):
                if at_division_boundary(token_stream):
                    break
            if _at_unit_boundary(token_stream, value_upper):
                break

            if screen and tok_type not in _NOISE_TOKEN_TYPES:
                if reference is not None and (
                    reference["depth"]
                    or (tok_type == TokenType.LEFT_PAREN and not reference["open"])
                ):
                    # A subscript / reference modifier of the operand
                    # (``USING WS-E(I)``): its names are data uses too.
                    if tok_type == TokenType.LEFT_PAREN:
                        reference["depth"] += 1
                    elif tok_type == TokenType.RIGHT_PAREN:
                        reference["depth"] -= 1
                    reference["text"] += f" {tok_value}"
                    entry_start = False
                    token_stream.consume()
                    continue
                if reference is not None:
                    if value_upper in ("OF", "IN") and not reference["open"]:
                        reference["text"] += f" {value_upper} "
                        reference["open"] = True
                    elif reference["open"] and tok_type == TokenType.IDENTIFIER:
                        reference["text"] += tok_value
                        reference["open"] = False
                    else:
                        screen_references.append(
                            {
                                k: v
                                for k, v in reference.items()
                                if k not in ("open", "depth")
                            }
                        )
                        reference = None
                if expect_operand is not None:
                    positional = expect_operand not in _SCREEN_DATA_CLAUSES
                    if positional and value_upper in _SCREEN_VALUE_NOISE:
                        pass  # LINE NUMBER IS ..., LINE PLUS ...: keep waiting
                    else:
                        if tok_type == TokenType.IDENTIFIER and not (
                            positional and value_upper in _SCREEN_CLAUSE_WORDS
                        ):
                            reference = {
                                "clause": expect_operand,
                                "text": tok_value,
                                "line": getattr(token.location, "line", None),
                                "column": getattr(token.location, "column", 1),
                                "open": False,
                                "depth": 0,
                            }
                        expect_operand = None
                elif expect_name is not None:
                    if (
                        tok_type == TokenType.IDENTIFIER
                        and value_upper not in _SCREEN_CLAUSE_WORDS
                    ):
                        screen_items.append(
                            {
                                "name": tok_value,
                                "level": expect_name,
                                "line": getattr(token.location, "line", None),
                                "column": getattr(token.location, "column", 1),
                            }
                        )
                    expect_name = None
                elif entry_start and tok_type == TokenType.LEVEL_NUMBER:
                    expect_name = int(tok_value) if tok_value.isdigit() else 0
                if (
                    reference is None
                    and expect_operand is None
                    and (
                        value_upper in _SCREEN_DATA_CLAUSES
                        or value_upper in _SCREEN_VALUE_CLAUSES
                    )
                ):
                    expect_operand = value_upper
                entry_start = tok_type == TokenType.PERIOD

            token_stream.consume()

        if reference is not None:
            screen_references.append(
                {k: v for k, v in reference.items() if k not in ("open", "depth")}
            )

        result: dict[str, Any] = {
            "type": section_name.lower(),
            "data_items": [],
            "exec_sql_items": [],
        }
        if screen_items:
            result["screen_items"] = screen_items
        if screen_references:
            result["screen_references"] = screen_references
        if section_location is not None:
            result["location"] = section_location
        return result

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

        top_level_items: list[Any] = []
        stack: list[Any] = []  # Stack of (level, item) pairs

        for item in data_items:
            # Level-88 condition names attach to the most recent item on the stack
            if isinstance(item, ConditionNameItem):
                if stack:
                    stack[-1][1].add_child(item)
                else:
                    top_level_items.append(item)
                # Do NOT push 88-level onto the stack
                continue

            # Level-66 RENAMES are always top-level aliases
            if isinstance(item, RenamesItem):
                top_level_items.append(item)
                continue

            current_level = item.level

            # Level 01 and level 77 always start a new top-level entry.
            # A 77 is, by COBOL's level-number rules, never subordinate to
            # anything, but a plain numeric pop (``stack[-1][0] >= 77``)
            # left it attached under whatever elementary item happened to be
            # open (``01 REC. 05 Y1 PIC X. 77 STANDALONE PIC 9.`` nested
            # STANDALONE under Y1).
            if current_level in (1, 77):
                stack.clear()

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

        propagate_group_usage_and_sign(top_level_items)
        return top_level_items

    # ------------------------------------------------------------------
    # Delegating wrappers.
    #
    # The entry-level parsing lives in the collaborator classes (see the
    # module docstring). These wrappers keep the historical method names on
    # the division parser itself.
    # ------------------------------------------------------------------

    def _parse_data_item(
        self, token_stream: ITokenStream, report_group: bool = False
    ) -> CobolDataItem | None:
        """Parse a single data item definition (delegates to DataItemClauseParser)."""
        return self._clause_parser.parse_data_item(
            token_stream, report_group=report_group
        )

    def _parse_fd_clauses(self, token_stream: ITokenStream) -> dict[str, Any]:
        """Parse FD/SD clauses (delegates to FileDescriptionClauseParser)."""
        return self._fd_parser.parse_fd_clauses(token_stream)

    def _parse_condition_name_item(
        self, token_stream: ITokenStream
    ) -> ConditionNameItem | None:
        """Parse a level-88 condition name item (delegates to SpecialEntryParser)."""
        return self._special_entries.parse_condition_name_item(token_stream)

    def _parse_renames_item(self, token_stream: ITokenStream) -> RenamesItem | None:
        """Parse a level-66 RENAMES item (delegates to SpecialEntryParser)."""
        return self._special_entries.parse_renames_item(token_stream)

    def _parse_exec_sql_in_data(
        self, token_stream: ITokenStream
    ) -> ExecSQLStatement | None:
        """Parse a data-division EXEC SQL block (delegates to SpecialEntryParser)."""
        return self._special_entries.parse_exec_sql_in_data(token_stream)

    def _create_ast_node(
        self,
        division_token: Any,
        division_content: dict[str, Any],
        start_location: SourceLocation,
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
            "linkage": "LINKAGE",
            "screen": "SCREEN",
            "report": "REPORT",
            "communication": "COMMUNICATION",
        }

        for key, section_name in section_map.items():
            if key in division_content:
                section_content = division_content[key]
                section_location = (
                    section_content.get("location", start_location)
                    if isinstance(section_content, dict)
                    else start_location
                )
                section = CobolSection(section_name, section_location)

                # Add parsed data items to section
                if (
                    isinstance(division_content[key], dict)
                    and "data_items" in division_content[key]
                ):
                    for data_item in division_content[key]["data_items"]:
                        if isinstance(data_item, CobolDataItem):
                            section.add_data_item(data_item)
                        elif isinstance(data_item, RenamesItem):
                            # RenamesItem is not a CobolDataItem but must be in the AST tree
                            section.add_child(data_item)
                    # EXEC SQL blocks (DECLARE TABLE, INCLUDE SQLCA, etc.)
                    for sql_node in division_content[key].get("exec_sql_items", []):
                        section.add_child(sql_node)
                    report_files = division_content[key].get("report_files")
                    if report_files:
                        section.set_metadata("report_files", dict(report_files))
                    for screen_key in ("screen_items", "screen_references"):
                        screen_value = division_content[key].get(screen_key)
                        if screen_value:
                            section.set_metadata(screen_key, list(screen_value))

                division_node.add_section(section)

        # Store metadata
        division_node.metadata.update(
            {
                "has_file": "file" in division_content,
                "has_working_storage": "working_storage" in division_content,
                "has_local_storage": "local_storage" in division_content,
                "has_linkage": "linkage" in division_content,
                "has_screen": "screen" in division_content,
                "has_report": "report" in division_content,
                "has_communication": "communication" in division_content,
            }
        )

        return division_node
