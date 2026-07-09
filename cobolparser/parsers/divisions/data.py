"""Data Division parser for COBOL programs.

This module implements parsing of the Data Division which contains:
- FILE SECTION: File descriptions and records
- WORKING-STORAGE SECTION: Working variable definitions
- LOCAL-STORAGE SECTION: Local variable definitions
- LINKAGE SECTION: Program parameter definitions
"""

from typing import Any

from cobolparser.core.interfaces import ITokenStream
from cobolparser.lexer import TokenType
from cobolparser.models.ast_base import ASTNode, SourceLocation
from cobolparser.models.data_items import (
    CobolDataItem,
    ConditionNameItem,
    OccursClause,
    PictureClause,
    RenamesItem,
)
from cobolparser.models.program import CobolDivision, CobolSection
from cobolparser.models.sql_statements import ExecSQLStatement, parse_exec_sql
from cobolparser.parsers.statements._utils import collect_exec_sql_text

from .base import BaseDivisionParser, at_division_boundary

# Constants for COMP/COMPUTATIONAL usage keywords and token types.
# These appear in multiple parsing methods; keeping them in one place avoids
# duplication and makes adding new variants trivial.
_COMP_KEYWORDS: frozenset[str] = frozenset(
    {
        "COMP",
        "COMP-1",
        "COMP-2",
        "COMP-3",
        "COMP-4",
        "COMP-5",
        "COMPUTATIONAL",
        "COMPUTATIONAL-1",
        "COMPUTATIONAL-2",
        "COMPUTATIONAL-3",
        "COMPUTATIONAL-4",
        "COMPUTATIONAL-5",
        "BINARY",
        "PACKED-DECIMAL",
    }
)

_COMP_TOKEN_TYPES: frozenset[TokenType] = frozenset(
    {
        TokenType.COMP_1,
        TokenType.COMP_2,
        TokenType.COMP_3,
        TokenType.COMP_4,
        TokenType.COMP_5,
    }
)

_POINTER_KEYWORDS: frozenset[str] = frozenset(
    {
        "POINTER",
        "PROCEDURE-POINTER",
        "FUNCTION-POINTER",
    }
)

# Hoisted out of _parse_picture_clause -- the union was being rebuilt on
# every iteration of that method's inner loop.
_PICTURE_TERMINATOR_KEYWORDS: frozenset[str] = frozenset(
    _COMP_KEYWORDS
    | _POINTER_KEYWORDS
    | {
        "VALUE",
        "USAGE",
        "OCCURS",
        "REDEFINES",
        "SIGN",
        "SYNCHRONIZED",
        "SYNC",
        "JUSTIFIED",
        "JUST",
        "BLANK",
        "EXTERNAL",
        "GLOBAL",
    }
)
_PICTURE_PATTERN_TOKEN_TYPES: frozenset[TokenType] = frozenset(
    {
        TokenType.IDENTIFIER,
        TokenType.NUMERIC_LITERAL,
        TokenType.STRING_LITERAL,
        TokenType.LEVEL_NUMBER,
    }
)
# Editing symbols that the lexer emits as their own token types (rather than
# folding into an IDENTIFIER): currency ($), fixed/floating sign (+/-), and the
# check-protect (*) and stroke (/) insertion characters. Collected verbatim so
# edited pictures such as ``$$$,$$9.99`` or ``ZZ9.99-`` survive extraction.
_PICTURE_SYMBOL_TOKEN_TYPES: frozenset[TokenType] = frozenset(
    {
        TokenType.CURRENCY,
        TokenType.MINUS,
        TokenType.PLUS,
        TokenType.MULTIPLY_OP,  # '*' check-protect symbol -- NOT the MULTIPLY
        TokenType.DIVIDE_OP,  # '/' stroke/slash editing symbol -- NOT the DIVIDE
        # *statement* keyword tokens (see reports/open-findings.md M16: using
        # the statement tokens here silently truncated slash/asterisk-edited
        # PICTURE patterns at the first edit symbol).
    }
)
# Token types that may legitimately follow an *interior* decimal point in a
# picture (i.e. the fractional digits / edit symbols).
_PICTURE_DECIMAL_FOLLOW_TYPES: frozenset[TokenType] = (
    _PICTURE_PATTERN_TOKEN_TYPES | _PICTURE_SYMBOL_TOKEN_TYPES
)

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
_SECTION_BREAK_HEADERS: frozenset[str] = frozenset(
    {"FILE", "WORKING-STORAGE", "LOCAL-STORAGE", "LINKAGE"}
)
_DIVISION_TOKEN_TYPES: frozenset[TokenType] = frozenset(
    {
        TokenType.IDENTIFICATION_DIVISION,
        TokenType.ENVIRONMENT_DIVISION,
        TokenType.DATA_DIVISION,
        TokenType.PROCEDURE_DIVISION,
    }
)

# Non-meaningful tokens (layout only) that the clause loop skips silently —
# warning on these would be noise.
_WHITESPACE_TOKEN_TYPES: frozenset[TokenType] = frozenset(
    {
        TokenType.NEWLINE,
        TokenType.WHITESPACE,
        TokenType.COMMENT,
        TokenType.CONTINUATION,
    }
)

# Keywords that begin an FD/SD file-description clause. Used to segment the
# clause tokens captured by ``_parse_fd_clauses``.
_FD_CLAUSE_STARTS: frozenset[str] = frozenset(
    {
        "BLOCK",
        "RECORD",
        "LABEL",
        "RECORDING",
        "CODE-SET",
        "DATA",
        "LINAGE",
        "VALUE",
        "GLOBAL",
        "EXTERNAL",
    }
)

# Optional Cython acceleration for the picture-clause inner loop. The
# pure-Python implementation in ``_parse_picture_clause`` below remains
# the authoritative behaviour; we only delegate when the extension is
# available and the token stream is the standard ``TokenStream`` (so we
# can safely poke its underlying token list and cursor).
try:
    from cobolparser._data_fast import (  # type: ignore[import-not-found]
        parse_data_item_clauses_fast as _fast_data_item_clauses,
    )

    _HAS_DATA_FAST = True
except ImportError:
    _fast_data_item_clauses = None
    _HAS_DATA_FAST = False


class DataDivisionParser(BaseDivisionParser):
    """Parser for COBOL Data Division.

    Handles data structure definitions with section support.
    Supports FILE, WORKING-STORAGE, LOCAL-STORAGE, and LINKAGE sections.
    """

    division_name: str | None = "DATA"
    division_keywords: tuple = ()

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
            if value_upper in _SECTION_BREAK_HEADERS:
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
                token_stream.consume()  # consume FD/SD
                fd_name_tok = token_stream.peek()
                if fd_name_tok and fd_name_tok.type == TokenType.IDENTIFIER:
                    current_fd_name = fd_name_tok.value
                    token_stream.consume()  # consume file name
                # Capture the FD/SD clauses (instead of discarding them) so the
                # file's physical layout (block/record sizes, recording mode,
                # labels, code set, EXTERNAL/GLOBAL) is preserved in the AST.
                current_fd_clauses = self._parse_fd_clauses(token_stream)
                continue

            # Parse EXEC SQL blocks that appear in the data division
            # (e.g. DCLGEN-generated DECLARE TABLE or INCLUDE SQLCA)
            is_exec = tok_type == TokenType.EXEC or (
                tok_type == TokenType.IDENTIFIER and value_upper == "EXEC"
            )
            if is_exec and paren_depth == 0:
                next_tok = token_stream.peek(1)
                is_sql = next_tok and (
                    next_tok.type == TokenType.SQL
                    or (
                        next_tok.type == TokenType.IDENTIFIER
                        and next_tok.value
                        and next_tok.value.upper() == "SQL"
                    )
                )
                if is_sql:
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
                    data_item = self._parse_data_item(token_stream)
                    if data_item:
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

    @staticmethod
    def _level_starts_record(token_stream: ITokenStream) -> bool:
        """Return True if the LEVEL_NUMBER at the cursor begins a record entry.

        A record description is a level number immediately followed by a
        data-name (an IDENTIFIER, or FILLER), e.g. ``01 IN-REC``. A bare
        integer that is merely a clause operand (``RECORD CONTAINS 77``) is
        followed by a keyword or another number instead, so it must not be
        mistaken for the start of a record. NEWLINE tokens between the level
        and the name are skipped.
        """
        offset = 1
        while True:
            nxt = token_stream.peek(offset)
            if nxt is None:
                return False
            if nxt.type == TokenType.NEWLINE:
                offset += 1
                continue
            if nxt.type == TokenType.IDENTIFIER:
                return True
            return bool(nxt.value and nxt.value.upper() == "FILLER")

    def _parse_fd_clauses(self, token_stream: ITokenStream) -> dict[str, Any]:
        """Parse the clauses of an FD/SD file description entry.

        Walks tokens from just after the file name up to (and consuming) the
        terminating period, or up to the next level number / division header.
        Recognized clauses (BLOCK CONTAINS, RECORD/RECORD VARYING, LABEL
        RECORDS, RECORDING MODE, CODE-SET, DATA RECORDS, LINAGE, VALUE OF,
        GLOBAL, EXTERNAL) are returned as a structured, JSON-serializable
        mapping. Unrecognized tokens for a clause are preserved as raw text so
        nothing is silently lost.
        """
        raw: dict[str, list[str]] = {}
        current_key: str | None = None

        while not token_stream.is_empty():
            t = token_stream.peek()
            if t is None:
                break
            if t.type == TokenType.PERIOD:
                token_stream.consume()
                break
            if t.type in _DIVISION_TOKEN_TYPES:
                break
            # The lexer tags every bare integer as LEVEL_NUMBER, so a clause
            # operand such as the 77 in "RECORD CONTAINS 77 CHARACTERS" or the
            # 1 in "BLOCK CONTAINS 1 RECORDS" is indistinguishable from a record
            # level by value alone. A real record description is a level number
            # immediately followed by a data-name (IDENTIFIER/FILLER); operands
            # are followed by a keyword (RECORDS/CHARACTERS/...) or a number.
            # Only the former should stop clause capture.
            if t.type == TokenType.LEVEL_NUMBER:
                if self._level_starts_record(token_stream):
                    break
                if current_key is not None and t.value:
                    raw[current_key].append(t.value)
                token_stream.consume()
                continue
            if t.type == TokenType.NEWLINE:
                token_stream.consume()
                continue

            value_upper = t.value.upper() if t.value else ""
            # "RECORD" is also the second word of the LABEL RECORD / DATA RECORD
            # clauses; don't let it start a fresh RECORD clause in that context.
            starts_clause = value_upper in _FD_CLAUSE_STARTS and not (
                value_upper == "RECORD" and current_key in ("LABEL", "DATA")
            )
            if starts_clause:
                current_key = value_upper
                raw.setdefault(current_key, [])
            elif current_key is not None and t.value:
                raw[current_key].append(t.value)
            token_stream.consume()

        return self._structure_fd_clauses(raw)

    @staticmethod
    def _structure_fd_clauses(raw: dict[str, list[str]]) -> dict[str, Any]:
        """Normalize raw FD clause tokens into structured fields."""

        def _ints(tokens: list[str]) -> list[int]:
            out: list[int] = []
            for tok in tokens:
                try:
                    out.append(int(tok))
                except (TypeError, ValueError):
                    continue
            return out

        clauses: dict[str, Any] = {}

        for key, tokens in raw.items():
            upper = [tok.upper() for tok in tokens]

            if key in ("GLOBAL", "EXTERNAL"):
                clauses[key.lower().replace("-", "_")] = True

            elif key == "BLOCK":
                nums = _ints(tokens)
                unit = (
                    "RECORDS"
                    if "RECORDS" in upper
                    else ("CHARACTERS" if "CHARACTERS" in upper else None)
                )
                clauses["block_contains"] = {
                    "min": nums[0] if len(nums) > 1 else None,
                    "max": nums[-1] if nums else None,
                    "unit": unit,
                }

            elif key == "RECORD":
                if "VARYING" in upper:
                    nums = _ints(tokens)
                    depending = None
                    if "DEPENDING" in upper:
                        # data-name follows DEPENDING [ON]
                        idx = upper.index("DEPENDING")
                        rest = [tok for tok in tokens[idx + 1 :] if tok.upper() != "ON"]
                        depending = rest[0] if rest else None
                    clauses["record"] = {
                        "varying": True,
                        "min": nums[0] if nums else None,
                        "max": (
                            nums[1] if len(nums) > 1 else (nums[0] if nums else None)
                        ),
                        "depending_on": depending,
                    }
                else:
                    nums = _ints(tokens)
                    clauses["record"] = {
                        "varying": False,
                        "min": nums[0] if len(nums) > 1 else None,
                        "max": nums[-1] if nums else None,
                    }

            elif key == "LABEL":
                if "OMITTED" in upper:
                    clauses["label_records"] = "OMITTED"
                elif "STANDARD" in upper:
                    clauses["label_records"] = "STANDARD"
                elif tokens:
                    clauses["label_records"] = " ".join(tokens)

            elif key == "RECORDING":
                mode = [tok for tok in tokens if tok.upper() not in ("MODE", "IS")]
                if mode:
                    clauses["recording_mode"] = mode[0]

            elif key == "CODE-SET":
                names = [tok for tok in tokens if tok.upper() != "IS"]
                if names:
                    clauses["code_set"] = names[0]

            elif key == "DATA":
                names = [
                    tok
                    for tok in tokens
                    if tok.upper() not in ("RECORD", "RECORDS", "IS", "ARE")
                ]
                if names:
                    clauses["data_records"] = names

            elif key == "LINAGE":
                clauses["linage"] = " ".join(tokens)

            elif key == "VALUE":
                clauses["value_of"] = " ".join(tokens)

        return clauses

    def _parse_data_item(self, token_stream: ITokenStream) -> CobolDataItem | None:
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
        elif token and token.value and token.value.upper() == "FILLER":
            name = "FILLER"
            token_stream.consume()
        else:
            # Anonymous data item; ``location`` is always a SourceLocation.
            name = f"ANONYMOUS-{level}-{location.line}"

        # Create data item
        data_item = CobolDataItem(name, level, location)

        # Fast path: drive the common-clause loop in Cython. VALUE and
        # USAGE clauses call back into the Python helpers below via
        # ``parser_self``. The fast helper handles only the hot clauses
        # (PICTURE, VALUE, USAGE, COMP, REDEFINES, OCCURS) and bails back
        # on any clause it does not recognize (SIGN, SYNCHRONIZED,
        # JUSTIFIED, BLANK, POINTER, EXTERNAL, GLOBAL, ...). We then fall
        # through to the pure-Python loop below, which is the single
        # source of truth for those clauses -- so the two implementations
        # can never drift on the rarer clauses.
        if _HAS_DATA_FAST:
            tokens_list = getattr(token_stream, "_tokens", None)
            if tokens_list is not None:
                new_pos = _fast_data_item_clauses(
                    tokens_list,
                    token_stream._pos,  # type: ignore[attr-defined]
                    data_item,
                    location,
                    self,
                    token_stream,
                    _PICTURE_TERMINATOR_KEYWORDS,
                    _PICTURE_PATTERN_TOKEN_TYPES,
                    _COMP_KEYWORDS,
                    _COMP_TOKEN_TYPES,
                    _DIVISION_TOKEN_TYPES,
                    PictureClause,
                    OccursClause,
                    TokenType.PERIOD,
                    TokenType.LEVEL_NUMBER,
                    TokenType.IDENTIFIER,
                    TokenType.NUMERIC_LITERAL,
                    TokenType.NEWLINE,
                )
                token_stream._pos = new_pos  # type: ignore[attr-defined]
                # Fall through (no early return): the Python loop below
                # finishes any clauses the fast helper handed back.

        # Parse clauses until period or next item
        while not token_stream.is_empty():
            token = token_stream.peek()
            if not token:
                break

            tok_type = token.type

            # Period ends this data item
            if tok_type == TokenType.PERIOD:
                token_stream.consume()
                break

            # Level number starts next item
            if tok_type == TokenType.LEVEL_NUMBER:
                break

            # Division tokens end this data item (don't consume them)
            if tok_type in _DIVISION_TOKEN_TYPES:
                break

            # Compute upper-cased token value once -- the chain of clause
            # checks below would otherwise call ``.upper()`` up to six times
            # per loop iteration on the same string.
            value_upper = token.value.upper() if token.value else ""

            #  PICTURE/PIC clause
            if value_upper == "PICTURE" or value_upper == "PIC":
                token_stream.consume()  # Consume PIC keyword
                picture_pattern = self._parse_picture_clause(token_stream)
                if picture_pattern:
                    data_item.set_picture_clause(
                        PictureClause(picture_pattern, location)
                    )

            # VALUE clause
            elif value_upper == "VALUE":
                token_stream.consume()  # Consume VALUE keyword
                value = self._parse_value_clause(token_stream)
                if value:
                    data_item.set_value_clause(value)

            # USAGE clause
            elif value_upper == "USAGE":
                token_stream.consume()  # Consume USAGE keyword
                usage = self._parse_usage_clause(token_stream)
                if usage:
                    data_item.set_usage(usage)

            # COMP, COMP-3, etc. without USAGE keyword
            elif value_upper in _COMP_KEYWORDS:
                data_item.set_usage(value_upper)
                token_stream.consume()

            # Also check for COMP token types (COMP_1, COMP_2, COMP_3, etc.)
            elif token.type in _COMP_TOKEN_TYPES:
                data_item.set_usage(token.value.upper())
                token_stream.consume()

            # POINTER, PROCEDURE-POINTER, FUNCTION-POINTER without USAGE keyword
            elif value_upper in _POINTER_KEYWORDS:
                data_item.set_usage(value_upper)
                token_stream.consume()

            # SIGN clause: SIGN [IS] LEADING|TRAILING [SEPARATE [CHARACTER]]
            elif value_upper == "SIGN":
                token_stream.consume()
                nxt = token_stream.peek()
                if nxt and nxt.value and nxt.value.upper() == "IS":
                    token_stream.consume()
                dir_tok = token_stream.peek()
                if dir_tok and dir_tok.value:
                    direction = dir_tok.value.upper()
                    token_stream.consume()
                    sep = token_stream.peek()
                    if sep and sep.value and sep.value.upper() == "SEPARATE":
                        token_stream.consume()
                        ch = token_stream.peek()
                        if ch and ch.value and ch.value.upper() == "CHARACTER":
                            token_stream.consume()
                        direction = direction + " SEPARATE"
                    data_item.sign_clause = direction

            # SYNCHRONIZED / SYNC clause
            elif value_upper in {"SYNCHRONIZED", "SYNC"}:
                data_item.synchronized = True
                token_stream.consume()
                nxt = token_stream.peek()
                if nxt and nxt.value and nxt.value.upper() in {"LEFT", "RIGHT"}:
                    token_stream.consume()

            # JUSTIFIED / JUST [RIGHT] clause
            elif value_upper in {"JUSTIFIED", "JUST"}:
                data_item.justified = True
                token_stream.consume()
                nxt = token_stream.peek()
                if nxt and nxt.value and nxt.value.upper() == "RIGHT":
                    token_stream.consume()

            # BLANK WHEN ZERO clause
            elif value_upper == "BLANK":
                token_stream.consume()
                nxt = token_stream.peek()
                if nxt and nxt.value and nxt.value.upper() == "WHEN":
                    token_stream.consume()
                nxt = token_stream.peek()
                if (
                    nxt
                    and nxt.value
                    and nxt.value.upper() in {"ZERO", "ZEROS", "ZEROES"}
                ):
                    token_stream.consume()
                data_item.blank_when_zero = True

            # EXTERNAL clause: [IS] EXTERNAL [AS literal]
            elif value_upper == "EXTERNAL":
                data_item.is_external = True
                token_stream.consume()
                nxt = token_stream.peek()
                if nxt and nxt.value and nxt.value.upper() == "AS":
                    token_stream.consume()
                    lit = token_stream.peek()
                    if lit and lit.type in (
                        TokenType.STRING_LITERAL,
                        TokenType.IDENTIFIER,
                    ):
                        token_stream.consume()

            # GLOBAL clause: [IS] GLOBAL
            elif value_upper == "GLOBAL":
                data_item.is_global = True
                token_stream.consume()

            # REDEFINES clause
            elif value_upper == "REDEFINES":
                token_stream.consume()  # Consume REDEFINES keyword
                redef_token = token_stream.peek()
                if redef_token and redef_token.type == TokenType.IDENTIFIER:
                    data_item.set_redefines(redef_token.value)
                    token_stream.consume()

            # OCCURS clause
            elif value_upper == "OCCURS":
                token_stream.consume()  # Consume OCCURS keyword
                occurs = OccursClause(location)

                # Read first (minimum or fixed) count
                min_count = 0
                max_count = 0
                count_token = token_stream.peek()
                if count_token and count_token.type in [
                    TokenType.NUMERIC_LITERAL,
                    TokenType.LEVEL_NUMBER,
                ]:
                    try:
                        min_count = int(count_token.value)
                        max_count = min_count
                    except (TypeError, ValueError):
                        pass
                    token_stream.consume()

                # Variable OCCURS: OCCURS min TO max [TIMES] DEPENDING ON var
                nxt = token_stream.peek()
                if nxt and nxt.value and nxt.value.upper() == "TO":
                    token_stream.consume()  # consume TO
                    max_token = token_stream.peek()
                    if max_token and max_token.type in [
                        TokenType.NUMERIC_LITERAL,
                        TokenType.LEVEL_NUMBER,
                    ]:
                        try:
                            max_count = int(max_token.value)
                        except (TypeError, ValueError):
                            max_count = min_count
                        token_stream.consume()

                # Skip optional TIMES keyword (may be preceded by newlines)
                self._skip_newlines(token_stream)
                nxt = token_stream.peek()
                if nxt and nxt.value and nxt.value.upper() == "TIMES":
                    token_stream.consume()

                # DEPENDING ON clause
                depending_var = None
                self._skip_newlines(token_stream)
                nxt = token_stream.peek()
                if nxt and nxt.value and nxt.value.upper() == "DEPENDING":
                    token_stream.consume()  # consume DEPENDING
                    on_token = token_stream.peek()
                    if on_token and on_token.value and on_token.value.upper() == "ON":
                        token_stream.consume()  # consume ON
                    dep_token = token_stream.peek()
                    if dep_token and dep_token.type == TokenType.IDENTIFIER:
                        depending_var = dep_token.value
                        token_stream.consume()

                # ASCENDING / DESCENDING KEY IS key-1 [key-2 ...] clauses
                # (may repeat). These sit between DEPENDING ON and INDEXED BY
                # in standard COBOL and are what makes a table valid for
                # SEARCH ALL (binary search), so dropping them loses real
                # semantics — and previously it also cascaded into dropping a
                # following INDEXED BY clause.
                self._skip_newlines(token_stream)
                nxt = token_stream.peek()
                while (
                    nxt
                    and nxt.value
                    and nxt.value.upper()
                    in (
                        "ASCENDING",
                        "DESCENDING",
                    )
                ):
                    direction = nxt.value.upper()
                    token_stream.consume()  # consume ASCENDING/DESCENDING
                    self._skip_newlines(token_stream)
                    key_kw = token_stream.peek()
                    if key_kw and key_kw.value and key_kw.value.upper() == "KEY":
                        token_stream.consume()  # consume KEY
                    self._skip_newlines(token_stream)
                    is_kw = token_stream.peek()
                    if is_kw and is_kw.value and is_kw.value.upper() == "IS":
                        token_stream.consume()  # consume optional IS
                    keys: list[str] = []
                    while True:
                        self._skip_newlines(token_stream)
                        key_token = token_stream.peek()
                        if (
                            key_token
                            and key_token.type == TokenType.IDENTIFIER
                            and key_token.value
                            and key_token.value.upper()
                            not in ("ASCENDING", "DESCENDING", "INDEXED", "KEY")
                        ):
                            keys.append(key_token.value)
                            token_stream.consume()
                        else:
                            break
                    if keys:
                        occurs.add_key_clause(direction, keys)
                    self._skip_newlines(token_stream)
                    nxt = token_stream.peek()

                # INDEXED BY clause (one or more index names)
                self._skip_newlines(token_stream)
                nxt = token_stream.peek()
                if nxt and nxt.value and nxt.value.upper() == "INDEXED":
                    token_stream.consume()  # consume INDEXED
                    by_token = token_stream.peek()
                    if by_token and by_token.value and by_token.value.upper() == "BY":
                        token_stream.consume()  # consume BY
                    while True:
                        self._skip_newlines(token_stream)
                        idx_token = token_stream.peek()
                        if idx_token and idx_token.type == TokenType.IDENTIFIER:
                            occurs.add_index_name(idx_token.value)
                            token_stream.consume()
                        else:
                            break

                if depending_var:
                    occurs.set_variable_occurs(min_count, max_count, depending_var)
                else:
                    occurs.set_fixed_occurs(max_count)

                if occurs.max_times is not None:
                    data_item.set_occurs_clause(occurs)

            else:
                # Skip unknown tokens/clauses. PERIOD, LEVEL_NUMBER, and
                # division tokens are already handled at the top of the
                # loop (they ``break`` before we get here), so the only
                # remaining case is "consume and continue". Record a warning
                # for meaningful (non-whitespace) tokens so a data-item clause
                # this parser does not yet support (GROUP-USAGE, VOLATILE,
                # DYNAMIC LENGTH, ...) is not dropped completely silently —
                # symmetric with the ENVIRONMENT division's SELECT handling.
                self._warn_dropped_data_token(token, data_item)
                token_stream.consume()

        return data_item

    def _warn_dropped_data_token(self, token: Any, data_item: Any) -> None:
        """Record a warning for an unrecognized data-item clause token."""
        if token is None or token.type in _WHITESPACE_TOKEN_TYPES:
            return
        value = (token.value or "").strip() if token.value else ""
        if not value:
            return
        line = getattr(getattr(token, "location", None), "line", None)
        where = f" at line {line}" if line else ""
        item_name = getattr(data_item, "name", None) or "?"
        host = getattr(self, "host", None)
        add_warning = getattr(host, "add_warning", None)
        if callable(add_warning):
            add_warning(
                f"Unparsed token '{value}'{where} in data item '{item_name}' "
                "skipped: clause not fully supported; content dropped from the AST"
            )

    def _parse_condition_name_item(
        self, token_stream: ITokenStream
    ) -> ConditionNameItem | None:
        """Parse a level-88 condition name item.

        Format: 88 condition-name VALUE [IS] literal {literal | THROUGH literal}...
        """
        level_token = token_stream.consume()  # consume '88'
        location = getattr(level_token, "location", None)
        if location is None:
            from cobolparser.models.ast_base import SourceLocation

            location = SourceLocation(0, 0)

        name_token = token_stream.peek()
        if not name_token or not name_token.value:
            return None
        name = name_token.value
        token_stream.consume()

        item = ConditionNameItem(name, location)

        # Skip tokens until VALUE keyword
        while not token_stream.is_empty():
            t = token_stream.peek()
            if not t:
                break
            if t.type == TokenType.PERIOD or t.type == TokenType.LEVEL_NUMBER:
                break
            if t.value and t.value.upper() == "VALUE":
                token_stream.consume()
                # optional IS / ARE
                nxt = token_stream.peek()
                if nxt and nxt.value and nxt.value.upper() in ("IS", "ARE"):
                    token_stream.consume()
                break
            token_stream.consume()

        # Collect value literals. LEVEL_NUMBER is accepted as a numeric
        # literal (the lexer types 1-2 digit integers as LEVEL_NUMBER even
        # in value position); the item terminator is the PERIOD, so this
        # cannot swallow a following item's level number in well-formed
        # source. A MINUS/PLUS token followed by a numeric is a signed
        # literal.
        while not token_stream.is_empty():
            t = token_stream.peek()
            if not t:
                break
            if t.type == TokenType.PERIOD:
                break
            if t.type in (
                TokenType.STRING_LITERAL,
                TokenType.NUMERIC_LITERAL,
                TokenType.FIGURATIVE_CONSTANT,
                TokenType.LEVEL_NUMBER,
            ):
                item.add_value(t.value)
                token_stream.consume()
            elif t.type in (TokenType.MINUS, TokenType.PLUS):
                sign_value = t.value
                next_token = token_stream.peek(1)
                if next_token and next_token.type in (
                    TokenType.NUMERIC_LITERAL,
                    TokenType.LEVEL_NUMBER,
                ):
                    item.add_value(f"{sign_value}{next_token.value}")
                    token_stream.consume()
                    token_stream.consume()
                else:
                    break
            elif t.value == ",":
                token_stream.consume()
            elif t.type == TokenType.NEWLINE:
                token_stream.consume()
            elif t.value and t.value.upper() in ("THROUGH", "THRU"):
                token_stream.consume()
                end_token = token_stream.peek()
                if end_token and end_token.type in (
                    TokenType.STRING_LITERAL,
                    TokenType.NUMERIC_LITERAL,
                    TokenType.LEVEL_NUMBER,
                ):
                    item.add_value(f"THROUGH:{end_token.value}")
                    token_stream.consume()
            else:
                break

        # Consume trailing period
        if not token_stream.is_empty():
            t = token_stream.peek()
            if t and t.type == TokenType.PERIOD:
                token_stream.consume()

        return item

    def _parse_exec_sql_in_data(
        self, token_stream: ITokenStream
    ) -> ExecSQLStatement | None:
        """Parse an EXEC SQL...END-EXEC block appearing in the Data Division.

        This handles DCLGEN-generated ``DECLARE TABLE`` blocks and
        ``INCLUDE SQLCA`` / ``INCLUDE SQLDA`` directives that are placed in
        the Working-Storage or Linkage sections.

        The token-to-SQL-text reconstruction is shared with the procedure-
        division EXEC SQL parser via :func:`collect_exec_sql_text`.

        Args:
            token_stream: Token stream positioned at the EXEC token.

        Returns:
            An :class:`ExecSQLStatement` (or subclass) node, or *None* if the
            block cannot be parsed.
        """
        start_token = token_stream.consume()  # EXEC
        start_location = start_token.location if start_token else SourceLocation(0, 0)

        # Consume SQL keyword
        if not token_stream.is_empty():
            token_stream.consume()

        sql_text = collect_exec_sql_text(token_stream)
        if not sql_text.strip():
            return None
        return parse_exec_sql(sql_text, start_location)

    def _parse_renames_item(self, token_stream: ITokenStream) -> RenamesItem | None:
        """Parse a level-66 RENAMES item.

        Format: 66 data-name RENAMES data-name-1 [THROUGH|THRU data-name-2].
        """
        level_token = token_stream.consume()  # consume '66'
        location = getattr(level_token, "location", None)
        if location is None:
            from cobolparser.models.ast_base import SourceLocation

            location = SourceLocation(0, 0)

        name_token = token_stream.peek()
        if not name_token or not name_token.value:
            return None
        name = name_token.value
        token_stream.consume()

        # Expect RENAMES keyword
        renames_kw = token_stream.peek()
        if (
            not renames_kw
            or not renames_kw.value
            or renames_kw.value.upper() != "RENAMES"
        ):
            # Not a valid RENAMES — skip to period
            while not token_stream.is_empty():
                t = token_stream.peek()
                if not t or t.type in (TokenType.PERIOD, TokenType.LEVEL_NUMBER):
                    break
                token_stream.consume()
            return None
        token_stream.consume()  # consume RENAMES

        from_token = token_stream.peek()
        if not from_token or not from_token.value:
            return None
        renames_from = from_token.value
        token_stream.consume()

        renames_through = None
        nxt = token_stream.peek()
        if nxt and nxt.value and nxt.value.upper() in ("THROUGH", "THRU"):
            token_stream.consume()
            thru_token = token_stream.peek()
            if thru_token and thru_token.value:
                renames_through = thru_token.value
                token_stream.consume()

        # Consume trailing period
        if not token_stream.is_empty():
            t = token_stream.peek()
            if t and t.type == TokenType.PERIOD:
                token_stream.consume()

        return RenamesItem(name, renames_from, location, renames_through)

    @staticmethod
    def _skip_newlines(token_stream: ITokenStream) -> None:
        """Consume any NEWLINE tokens at the current position."""
        while not token_stream.is_empty():
            t = token_stream.peek()
            if t and t.type == TokenType.NEWLINE:
                token_stream.consume()
            else:
                break

    @staticmethod
    def _period_is_picture_decimal(period: Any, nxt: Any) -> bool:
        """Decide whether a PERIOD token is an editing decimal point.

        An interior decimal point is written with no surrounding space, so the
        next token sits on the same line in the immediately adjacent column and
        is itself a picture symbol (e.g. the ``.`` in ``ZZ9.99``). The entry's
        terminating period, by contrast, is followed by whitespace, a newline,
        or a different construct.
        """
        if nxt is None or nxt.type in (TokenType.NEWLINE, TokenType.EOF):
            return False
        if nxt.type not in _PICTURE_DECIMAL_FOLLOW_TYPES:
            return False
        ploc = period.location
        nloc = nxt.location
        if ploc is None or nloc is None:
            return False
        return bool(nloc.line == ploc.line and nloc.column == ploc.column + 1)

    def _parse_picture_clause(self, token_stream: ITokenStream) -> str | None:
        """Parse PICTURE clause pattern.

        Returns the picture pattern string (e.g., 'X(10)', '9(5)', '9(7)V99',
        'ZZ,ZZ9.99-', '$$$,$$9.99'). This is the single implementation used by
        both the pure-Python and Cython-accelerated data-item paths; the fast
        clause loop delegates here so the two can never drift.
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
                    # An interior '.' is an editing decimal point and stays in
                    # the pattern; the terminating period ends the clause.
                    if self._period_is_picture_decimal(token, token_stream.peek(1)):
                        pattern_parts.append(".")
                        token_stream.consume()
                        continue
                    break
                # Stop at keywords that follow picture clause
                if token.value and token.value.upper() in _PICTURE_TERMINATOR_KEYWORDS:
                    break
                # Also stop at COMP token types
                if token.type in _COMP_TOKEN_TYPES:
                    break

            # Collect picture pattern tokens
            if token.type in _PICTURE_PATTERN_TOKEN_TYPES:
                # All these token types can be part of a picture pattern
                token_value = token.value
                if paren_depth == 0 and token_value.endswith("."):
                    pattern_parts.append(token_value[:-1])
                    token_stream.consume()
                    break
                pattern_parts.append(token_value)
                token_stream.consume()
            # Editing symbols emitted as their own token types ($ + - * /)
            elif token.type in _PICTURE_SYMBOL_TOKEN_TYPES:
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

    def _parse_value_clause(self, token_stream: ITokenStream) -> str | None:
        """Parse VALUE clause value.

        Returns the value string.

        The lexer types 1-2 digit integers as LEVEL_NUMBER everywhere (even
        after VALUE), so LEVEL_NUMBER is accepted as a numeric literal here —
        after a consumed VALUE keyword a level number can only be a literal.
        A MINUS/PLUS token followed by a numeric is a signed literal.
        """
        token = token_stream.peek()
        if not token:
            return None

        # Optional IS: VALUE IS <literal>
        if token.type == TokenType.IS:
            token_stream.consume()
            token = token_stream.peek()
            if not token:
                return None

        sign = ""
        if token.type in (TokenType.MINUS, TokenType.PLUS):
            next_token = token_stream.peek(1)
            if next_token and next_token.type in (
                TokenType.NUMERIC_LITERAL,
                TokenType.LEVEL_NUMBER,
            ):
                sign = token.value
                token_stream.consume()
                token = next_token
            else:
                return None

        if token.type in [
            TokenType.STRING_LITERAL,
            TokenType.NUMERIC_LITERAL,
            TokenType.FIGURATIVE_CONSTANT,
            TokenType.LEVEL_NUMBER,
        ]:
            value = (
                f'"{token.value}"'
                if token.type == TokenType.STRING_LITERAL
                else f"{sign}{token.value}"
            )
            token_stream.consume()
            return value
        elif token.type == TokenType.IDENTIFIER:
            value = token.value
            token_stream.consume()
            return value

        return None

    def _parse_usage_clause(self, token_stream: ITokenStream) -> str | None:
        """Parse USAGE clause value.

        Returns the usage type (e.g., COMP-3, COMP-5, DISPLAY).
        """
        token = token_stream.peek()
        if not token:
            return None

        # Check for COMP token types first (COMP_1, COMP_2, etc.)
        if token.type in _COMP_TOKEN_TYPES:
            usage = token.value.upper()
            token_stream.consume()
            return usage

        # Check for regular IDENTIFIER
        if token.type == TokenType.IDENTIFIER:
            usage = token.value.upper()
            token_stream.consume()
            return usage

        # Check for COMP variations that are tokenized differently
        if token.value and token.value.upper() in _COMP_KEYWORDS:
            usage = token.value.upper()
            token_stream.consume()
            return usage

        return None

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

                division_node.add_section(section)

        # Store metadata
        division_node.metadata.update(
            {
                "has_file": "file" in division_content,
                "has_working_storage": "working_storage" in division_content,
                "has_local_storage": "local_storage" in division_content,
                "has_linkage": "linkage" in division_content,
            }
        )

        return division_node
