"""COBOL lexer implementation for tokenizing COBOL source code.

This module provides comprehensive tokenization of COBOL source code including:
- COBOL keywords and reserved words
- Identifiers and user-defined names
- Numeric and string literals
- Operators and punctuation
- IBM Enterprise COBOL specific tokens
- Division and section headers
- Picture clauses and data definitions
"""

import re
import sys
from dataclasses import dataclass
from enum import IntEnum, auto

from ._accel import accelerators_enabled
from ._lines import split_source_lines
from .models.ast_base import SourceLocation
from .plugins.core import DialectType, ParseError

# Fixed-format COBOL column layout (0-based indices)
_FF_SEQ_END = 6  # columns 1-6: sequence number area (indices 0-5)
_FF_INDICATOR = 6  # column 7: indicator (* / - space) — index 6
_FF_AREA_A = 7  # column 8: Area A start — index 7
_FF_LINE_END = 72  # column 73+: identification area (ignored) — index 72

_LEVEL_NUM_RE = re.compile(r"^\d{2}$")

# First characters of any COBOL division keyword (upper + lower)
_DIVISION_FIRST = frozenset("IEDPiedp")

# ---------------------------------------------------------------------------
# IDENTIFICATION DIVISION comment-entries (AUTHOR. / INSTALLATION. / ...)
# ---------------------------------------------------------------------------
# A comment-entry is free documentation text, not COBOL words: IBM
# Enterprise COBOL accepts *any* character in it, up to the next entry that
# starts in Area A. Tokenizing it like program text read the apostrophe of
# ``AUTHOR. JOHN O'BRIEN.`` as an unterminated literal (a spurious lexer
# warning) and split ``DATE-WRITTEN. 01/02/99.`` into ``01 / 02 / 99``. The
# lexer therefore hands each comment-entry line to the parser verbatim, as a
# single COMMENT_ENTRY token.
_COMMENT_ENTRY_KEYWORDS = (
    "AUTHOR|INSTALLATION|DATE-WRITTEN|DATE-COMPILED|SECURITY|REMARKS"
)
_COMMENT_ENTRY_RE = re.compile(
    r"[ \t]*(?:" + _COMMENT_ENTRY_KEYWORDS + r")[ \t]*\.(?=[ \t]|$)",
    re.IGNORECASE,
)
_COMMENT_ENTRY_ANY_RE = re.compile(
    r"^[ \t]*(?:" + _COMMENT_ENTRY_KEYWORDS + r")[ \t]*\.",
    re.IGNORECASE | re.MULTILINE,
)
_DIVISION_HEADER_RE = re.compile(
    r"[ \t]*(IDENTIFICATION|ID|ENVIRONMENT|DATA|PROCEDURE)[ \t]+DIVISION\b",
    re.IGNORECASE,
)


def _comment_entry_starts(source: str, lines: list[str]) -> dict[int, int]:
    """Map each free-form line index holding comment-entry text to the
    offset in that line where the text starts.

    Only IDENTIFICATION DIVISION lines count. A line *starting* with one of
    the comment-entry paragraph names (``AUTHOR.``) contributes the rest of
    that line; when that paragraph name sits in Area A (at or left of the
    ``IDENTIFICATION DIVISION`` header's own indentation -- the fixed-format
    Area A/B split ``normalize_fixed_format`` preserves) every following
    line indented into Area B is comment text too, up to the next Area A
    line. That includes division-header-shaped text: NIST OBNC1M embeds an
    entire phony program inside a SECURITY comment-entry. A paragraph name
    indented deeper than the header (a loosely indented free-form source)
    contributes only its own line, exactly as the IDENTIFICATION DIVISION
    parser treats it.
    """
    if not _COMMENT_ENTRY_ANY_RE.search(source):
        return {}
    starts: dict[int, int] = {}
    in_identification = False
    header_indent = 0
    in_area_b_entry = False
    for index, line in enumerate(lines):
        body = line.rstrip("\r\n")
        text = body.lstrip(" \t")
        if not text.strip():
            continue
        indent = len(body) - len(text)
        if in_area_b_entry:
            if indent > header_indent:
                starts[index] = indent
                continue
            in_area_b_entry = False
        header = _DIVISION_HEADER_RE.match(body) if text[0] in _DIVISION_FIRST else None
        if header is not None:
            in_identification = header.group(1).upper() in ("IDENTIFICATION", "ID")
            header_indent = indent
            continue
        if not in_identification:
            continue
        entry = _COMMENT_ENTRY_RE.match(body)
        if entry is not None:
            starts[index] = entry.end()
            in_area_b_entry = indent <= header_indent
    return starts


def mask_comment_entries(source: str) -> str:
    """*source* with every comment-entry's text blanked to spaces.

    Same length, same line breaks, so offsets and line numbers into the
    result are offsets and line numbers into *source*. The COPY and REPLACE
    text scanners run over this: a comment-entry is opaque documentation
    text, so a quote in ``AUTHOR. JOHN O'BRIEN.`` must not open a literal
    there, and a ``COPY`` in ``REMARKS. SEE COPY PAYREC.`` is prose (#251).
    The paragraph names themselves (``AUTHOR.``) are kept.
    """
    if not _COMMENT_ENTRY_ANY_RE.search(source):
        return source
    lines = split_source_lines(source, keepends=True)
    starts = _comment_entry_starts(source, lines)
    if not starts:
        return source
    out: list[str] = []
    for index, line in enumerate(lines):
        start = starts.get(index)
        if start is None:
            out.append(line)
            continue
        body = line.rstrip("\r\n")
        out.append(body[:start] + " " * (len(body) - start) + line[len(body) :])
    return "".join(out)


# ---------------------------------------------------------------------------
# SPECIAL-NAMES CURRENCY SIGN: the PICTURE symbols a program declares
# ---------------------------------------------------------------------------
# ``CURRENCY SIGN IS '£'`` (or ``CURRENCY SIGN IS 'EUR' WITH PICTURE SYMBOL
# '#'``) makes that character a PICTURE editing symbol exactly like ``$``.
# Characters that are otherwise not COBOL characters at all (``£``, ``€``,
# ``#``, ``@``, ...) would hit the lexer's "Invalid character" error inside
# the PICTURE string, so the declared symbols are collected up front and
# lexed as CURRENCY tokens.
_CURRENCY_CLAUSE_RE = re.compile(
    r"\bCURRENCY(?:[ \t\r\n]+SIGN)?(?:[ \t\r\n]+IS)?[ \t\r\n]+"
    r"(?:\"([^\"\r\n]+)\"|'([^'\r\n]+)')"
    r"(?:[ \t\r\n]+(?:WITH[ \t\r\n]+)?PICTURE[ \t\r\n]+SYMBOL[ \t\r\n]+"
    r"(?:\"([^\"\r\n])\"|'([^'\r\n])'))?",
    re.IGNORECASE,
)


def _code_text(source: str, *, blank_literals: bool, fixed_format: bool) -> str:
    """*source* with everything that is not program text blanked out.

    The SPECIAL-NAMES scans below run over the whole source up front, so a
    clause that only appears in a comment must not count: a commented-out
    ``*> DECIMAL-POINT IS COMMA.`` made ``MOVE 2.5 TO X`` lex as ``2`` PERIOD
    ``5`` and cost the statement. Drops a ``*>`` floating comment (outside a
    literal) to end of line, a whole fixed-format comment line when
    *fixed_format* (the raw-layout lexer), and -- when *blank_literals* --
    the text of every literal (``DISPLAY "DECIMAL-POINT IS COMMA"``). Line
    breaks are kept, so a clause split across lines still matches.
    """
    out: list[str] = []
    for line in split_source_lines(source):
        if fixed_format and len(line) > _FF_INDICATOR and line[_FF_INDICATOR] in "*/":
            out.append("")
            continue
        if "*>" not in line and not (blank_literals and ("'" in line or '"' in line)):
            out.append(line)
            continue
        chars: list[str] = []
        quote: str | None = None
        index = 0
        while index < len(line):
            ch = line[index]
            if quote is not None:
                if ch == quote:
                    quote = None  # a doubled quote reopens on the next char
                chars.append(" " if blank_literals else ch)
            elif ch in "'\"":
                quote = ch
                chars.append(" " if blank_literals else ch)
            elif line.startswith("*>", index):
                break
            else:
                chars.append(ch)
            index += 1
        out.append("".join(chars))
    return "\n".join(out)


def _declared_currency_symbols(
    source: str, fixed_format: bool = False
) -> frozenset[str]:
    """The PICTURE currency symbols a SPECIAL-NAMES paragraph declares.

    A clause without ``PICTURE SYMBOL`` declares its sign as the symbol, so
    only a one-character sign counts there. Alphanumeric symbols are left
    out -- they already lex as (part of) a word. A clause inside a comment
    declares nothing.
    """
    return frozenset(declared_currency_signs(source, fixed_format))


def declared_currency_signs(source: str, fixed_format: bool = False) -> dict[str, str]:
    """Each declared PICTURE currency symbol (as
    :func:`_declared_currency_symbols` picks them) mapped to the currency
    string it stands for: ``CURRENCY SIGN IS 'EUR' WITH PICTURE SYMBOL '#'``
    is ``{"#": "EUR"}``, and ``CURRENCY SIGN IS '#'`` is ``{"#": "#"}``.
    What an edited picture's currency positions display."""
    signs: dict[str, str] = {}
    if "CURRENCY" not in source.upper():
        return signs
    code = _code_text(source, blank_literals=False, fixed_format=fixed_format)
    for match in _CURRENCY_CLAUSE_RE.finditer(code):
        sign = match.group(1) or match.group(2) or ""
        symbol = match.group(3) or match.group(4)
        if symbol is None and len(sign) == 1:
            symbol = sign
        if symbol and not symbol.isalnum() and not symbol.isspace():
            signs.setdefault(symbol, sign)
    return signs


# ---------------------------------------------------------------------------
# SPECIAL-NAMES DECIMAL-POINT IS COMMA: which character is the decimal point
# ---------------------------------------------------------------------------
# ``DECIMAL-POINT IS COMMA`` exchanges the roles of ``,`` and ``.`` in numeric
# literals and PICTURE character-strings. Like the currency symbols above it
# is decided from the whole source up front, before any literal is read: the
# clause sits in the ENVIRONMENT DIVISION, ahead of every literal it governs.
# The scope is the whole compilation unit (a nested program inherits its
# container's SPECIAL-NAMES; stacked programs that disagree are not modelled).
_DECIMAL_POINT_COMMA_RE = re.compile(
    r"(?<![A-Za-z0-9-])DECIMAL-POINT(?:[ \t\r\n]+IS)?[ \t\r\n]+COMMA(?![A-Za-z0-9-])",
    re.IGNORECASE,
)


def declares_decimal_point_comma(source: str, fixed_format: bool = False) -> bool:
    """True when *source* declares ``SPECIAL-NAMES. DECIMAL-POINT IS COMMA``.

    Only program text counts: the clause in a comment or inside a literal
    declares nothing (see :func:`_code_text`).
    """
    if "DECIMAL-POINT" not in source.upper():
        return False
    code = _code_text(source, blank_literals=True, fixed_format=fixed_format)
    return _DECIMAL_POINT_COMMA_RE.search(code) is not None


class TokenType(IntEnum):
    """Token types for COBOL lexical analysis.

    Using ``IntEnum`` (vs plain ``Enum``) makes membership tests and
    ``hash()`` lookups significantly cheaper -- these are on the hot path
    of every ``TokenStream.match`` and registry-cache key construction.
    """

    # Literals
    STRING_LITERAL = auto()
    NUMERIC_LITERAL = auto()
    BOOLEAN_LITERAL = auto()
    FIGURATIVE_CONSTANT = auto()

    # Identifiers
    IDENTIFIER = auto()
    QUALIFIED_IDENTIFIER = auto()

    # Keywords - Divisions
    IDENTIFICATION_DIVISION = auto()
    ENVIRONMENT_DIVISION = auto()
    DATA_DIVISION = auto()
    PROCEDURE_DIVISION = auto()

    # Keywords - Sections
    PROGRAM_ID = auto()
    AUTHOR = auto()
    DATE_WRITTEN = auto()
    CONFIGURATION_SECTION = auto()
    INPUT_OUTPUT_SECTION = auto()
    FILE_SECTION = auto()
    WORKING_STORAGE_SECTION = auto()
    LOCAL_STORAGE_SECTION = auto()
    LINKAGE_SECTION = auto()

    # File Description
    FD = auto()
    SD = auto()  # Sort Description

    # FILE CONTROL keywords
    ASSIGN_TO = auto()  # ASSIGN keyword in FILE-CONTROL
    ORGANIZATION = auto()
    ACCESS = auto()
    MODE = auto()
    RECORD = auto()
    KEY = auto()
    ALTERNATE = auto()
    DUPLICATES = auto()
    FILE_STATUS = auto()
    RESERVE = auto()
    AREA = auto()
    AREAS = auto()
    PADDING = auto()
    CHARACTER = auto()
    RECORD_DELIMITER = auto()
    STANDARD_1 = auto()
    PASSWORD = auto()
    LOCK = auto()
    SHARING = auto()
    WITH = auto()
    ALL = auto()
    OTHER = auto()
    NO = auto()
    READ_ONLY = auto()
    SEQUENTIAL = auto()
    INDEXED = auto()
    RELATIVE = auto()
    LINE = auto()
    RANDOM = auto()
    DYNAMIC = auto()
    OPTIONAL = auto()

    # FD/SD clause keywords
    BLOCK = auto()
    CONTAINS = auto()
    RECORDS = auto()
    CHARACTERS = auto()
    LABEL = auto()
    STANDARD = auto()
    OMITTED = auto()
    DATA = auto()
    LINAGE = auto()
    LINES = auto()
    FOOTING = auto()
    AT = auto()
    TOP = auto()
    BOTTOM = auto()
    CODE_SET = auto()
    RECORDING = auto()
    EXTERNAL = auto()
    GLOBAL = auto()
    IS = auto()
    ARE = auto()
    IN = auto()
    OF = auto()
    DEPENDING = auto()

    # Keywords - Data Definition
    PIC = auto()
    PICTURE = auto()
    USAGE = auto()
    VALUE = auto()
    OCCURS = auto()
    REDEFINES = auto()
    THEN = auto()
    SYNC = auto()
    SYNCHRONIZED = auto()
    COMP = auto()
    COMP_1 = auto()
    COMP_2 = auto()
    COMP_3 = auto()
    COMP_4 = auto()
    COMP_5 = auto()
    COMPUTATIONAL = auto()
    DISPLAY = auto()

    # Keywords - Statements
    MOVE = auto()
    ADD = auto()
    SUBTRACT = auto()
    MULTIPLY = auto()
    DIVIDE = auto()
    COMPUTE = auto()
    PERFORM = auto()
    IF = auto()
    ELSE = auto()
    END_IF = auto()
    EVALUATE = auto()
    WHEN = auto()
    END_EVALUATE = auto()
    CALL = auto()
    RETURN = auto()
    GO = auto()
    GOTO = auto()
    STOP = auto()
    EXIT = auto()
    CONTINUE = auto()

    # Additional COBOL Verbs
    ALTER = auto()
    CANCEL = auto()
    CHAIN = auto()
    COMMIT = auto()
    DELETE = auto()
    DISABLE = auto()
    DISPLAY_1 = auto()
    EJECT = auto()
    SKIP1 = auto()
    SKIP2 = auto()
    SKIP3 = auto()
    ENABLE = auto()
    END_INVOKE = auto()
    END_PERFORM = auto()
    END_SET = auto()
    ENTER = auto()
    ENTRY = auto()
    EXAMINE = auto()
    EXECUTE = auto()
    EXHIBIT = auto()
    GENERATE = auto()
    GOBACK = auto()
    INITIALIZE = auto()
    INITIATE = auto()
    INSPECT = auto()
    INVOKE = auto()
    MERGE = auto()
    NEXT = auto()
    NOTE = auto()
    ON = auto()
    OTHERWISE = auto()
    READY = auto()
    RECEIVE = auto()
    RECOVER = auto()
    RELEASE = auto()
    RESET = auto()
    REWRITE = auto()
    ROLLBACK = auto()
    SEARCH = auto()
    SEND = auto()
    SERVICE = auto()
    SET = auto()
    SORT = auto()
    START = auto()
    STRING = auto()
    SUPPRESS = auto()
    TERMINATE = auto()
    TRANSFORM = auto()
    UNLOCK = auto()
    UNSTRING = auto()
    USE = auto()

    # Keywords - I/O
    SELECT = auto()
    READ = auto()
    WRITE = auto()
    OPEN = auto()
    CLOSE = auto()
    ACCEPT = auto()
    DISPLAY_STMT = auto()  # Different from USAGE DISPLAY

    # Keywords - I/O Statement Clauses
    # INTO, FROM, USING handled in Control Flow section
    # AFTER, BEFORE, TEST handled in Control Flow section
    AT_EOL = auto()  # AT END-OF-LINE
    VARYING_REC = auto()  # VARYING (for READ)
    NEXT_REC = auto()  # NEXT (for READ)
    FIRST_REC = auto()  # FIRST (for READ)
    LAST_REC = auto()  # LAST (for READ)
    PREV_REC = auto()  # PREV (for READ)
    CURRENT_REC = auto()  # CURRENT (for READ)
    NULL_TERM = auto()  # NULL (for null termination)
    RETRY = auto()

    # IO Statement Clause Keywords (additional for IBM Enterprise COBOL)
    INVALID = auto()  # INVALID KEY
    KEY_IS = auto()  # KEY IS
    END_OF_PAGE = auto()  # END-OF-PAGE or EOP
    WITH_LOCK = auto()  # WITH LOCK
    NO_REWIND = auto()  # NO REWIND
    REEL = auto()  # REEL (for CLOSE)
    UNIT = auto()  # UNIT (for CLOSE)
    ADVANCING = auto()  # ADVANCING (for WRITE/DISPLAY)
    BEFORE_ADV = auto()  # BEFORE ADVANCING
    AFTER_ADV = auto()  # AFTER ADVANCING
    NO_ADVANCING = auto()  # NO ADVANCING
    END_OF_FILE = auto()  # END-OF-FILE
    POSITION = auto()  # POSITION (for START)

    # Keywords - Control Flow
    TIMES = auto()
    UNTIL = auto()
    VARYING = auto()
    FROM = auto()
    TO = auto()
    BY = auto()
    AFTER = auto()
    BEFORE = auto()
    TEST = auto()
    INTO = auto()
    USING = auto()

    # Keywords - Conditions
    EQUAL = auto()
    NOT = auto()
    AND = auto()
    OR = auto()
    GREATER = auto()
    LESS = auto()
    THAN = auto()

    # Operators
    PLUS = auto()
    MINUS = auto()
    MULTIPLY_OP = auto()
    DIVIDE_OP = auto()
    POWER = auto()
    ASSIGN = auto()

    # Punctuation
    PERIOD = auto()
    COMMA = auto()
    SEMICOLON = auto()
    COLON = auto()
    LEFT_PAREN = auto()
    RIGHT_PAREN = auto()
    CURRENCY = auto()  # Dollar sign in PICTURE clauses
    QUOTATION_MARK = auto()
    APOSTROPHE = auto()
    BANG = auto()  # '!', not a COBOL operator on its own -- appears as the
    # left half of embedded SQL's '!=' (not-equal); see SINGLE_CHAR_TOKENS.
    PIPE = auto()  # '|', likewise the half of embedded SQL's '||' (concat).
    NOT_SIGN = auto()  # '¬' (logical-NOT glyph), the left half of
    # embedded SQL's '¬=' (not-equal) on EBCDIC-derived mainframe
    # source; see SINGLE_CHAR_TOKENS.

    # Special tokens
    NEWLINE = auto()
    EOF = auto()
    WHITESPACE = auto()
    COMMENT = auto()
    CONTINUATION = auto()

    # IBM Enterprise COBOL specific
    EXEC = auto()
    SQL = auto()
    CICS = auto()
    END_EXEC = auto()
    INCLUDE = auto()
    COPY = auto()
    REPLACING = auto()
    # NOTE: FUNCTION is intentionally NOT added to the KEYWORDS mapping.
    # Registering it as a keyword would cause statement parsers that only
    # accept IDENTIFIER tokens in operand positions to reject expressions
    # like `DISPLAY FUNCTION CURRENT-DATE` or `MOVE FUNCTION LENGTH(x) TO y`.
    # The LanguageEnvironmentAnalyzer detects FUNCTION usage by scanning the
    # text values of operand/expression strings, so a distinct token type is
    # not required for correct detection.
    FUNCTION = auto()

    # Level numbers
    LEVEL_NUMBER = auto()

    # Error tokens
    INVALID_TOKEN = auto()

    # One line of an IDENTIFICATION DIVISION comment-entry (AUTHOR. ...,
    # REMARKS. ...), verbatim -- free documentation text, not COBOL words.
    COMMENT_ENTRY = auto()


@dataclass(slots=True)
class Token:
    """Represents a lexical token in COBOL source code."""

    type: TokenType
    value: str
    location: SourceLocation
    raw_value: str | None = None  # Original source text if different from value

    def __str__(self) -> str:
        return f"{self.type.name}({self.value})"

    def __repr__(self) -> str:
        return f"Token({self.type.name}, '{self.value}', {self.location})"


class LexerError(ParseError):
    """Error during lexical analysis."""

    def __init__(self, message: str, location: SourceLocation, token_value: str = ""):
        super().__init__(message, line_number=location.line, column=location.column)
        self.location = location
        self.token_value = token_value


# Pre-compiled regex patterns for hot-path performance
_LEVEL_NUMBER_2DIGIT_RE = re.compile(r"^\d{2}$")
_LEVEL_NUMBER_1_2DIGIT_RE = re.compile(r"^\d{1,2}$")


class _CobolLexerPure:
    """COBOL lexical analyzer with support for multiple dialects.

    This lexer handles the complexities of COBOL tokenization including:
    - Fixed-format source lines (columns 7-72)
    - Continuation lines and literals
    - Case-insensitive keywords
    - IBM Enterprise COBOL extensions
    - Embedded SQL and CICS statements
    """

    # Single character token mapping (class-level to avoid per-call dict creation)
    SINGLE_CHAR_TOKENS = {
        ".": TokenType.PERIOD,
        ",": TokenType.COMMA,
        ";": TokenType.SEMICOLON,
        ":": TokenType.COLON,
        "(": TokenType.LEFT_PAREN,
        ")": TokenType.RIGHT_PAREN,
        "+": TokenType.PLUS,
        "-": TokenType.MINUS,
        "*": TokenType.MULTIPLY_OP,
        "/": TokenType.DIVIDE_OP,
        "=": TokenType.ASSIGN,
        "$": TokenType.CURRENCY,
        ">": TokenType.GREATER,
        "<": TokenType.LESS,
        # '!' and '|' are not COBOL operators, but embedded EXEC SQL text
        # legitimately uses '!=' (not-equal) and '||' (concatenation) --
        # without dedicated tokens these hit the "Invalid character" branch
        # below, which records a hard LexerError and fails the *entire*
        # parse (result.ast is None) over two characters the parser only
        # ever needed to round-trip as opaque SQL text.
        "!": TokenType.BANG,
        "|": TokenType.PIPE,
        # '¬' (U+00AC NOT SIGN) is how some EBCDIC-derived mainframe source
        # renders logical NOT; embedded EXEC SQL text legitimately uses
        # '¬=' as an alternate not-equal spelling, mirroring '!=' above.
        "¬": TokenType.NOT_SIGN,
    }

    # COBOL keywords mapping
    KEYWORDS = {
        # Divisions - NOTE: Individual division names should NOT be mapped here
        # They need contextual parsing to distinguish from regular identifiers
        # 'IDENTIFICATION': TokenType.IDENTIFICATION_DIVISION,
        # 'ID': TokenType.IDENTIFICATION_DIVISION,
        # 'ENVIRONMENT': TokenType.ENVIRONMENT_DIVISION,
        # 'DATA': TokenType.DATA_DIVISION,
        # 'PROCEDURE': TokenType.PROCEDURE_DIVISION,
        # Sections and entries
        "PROGRAM-ID": TokenType.PROGRAM_ID,
        "AUTHOR": TokenType.AUTHOR,
        "DATE-WRITTEN": TokenType.DATE_WRITTEN,
        "CONFIGURATION": TokenType.CONFIGURATION_SECTION,
        "INPUT-OUTPUT": TokenType.INPUT_OUTPUT_SECTION,
        "FILE": TokenType.FILE_SECTION,
        "WORKING-STORAGE": TokenType.WORKING_STORAGE_SECTION,
        "LOCAL-STORAGE": TokenType.LOCAL_STORAGE_SECTION,
        "LINKAGE": TokenType.LINKAGE_SECTION,
        # File Description
        "FD": TokenType.FD,
        "SD": TokenType.SD,
        # FILE CONTROL keywords
        "ASSIGN": TokenType.ASSIGN_TO,
        "ORGANIZATION": TokenType.ORGANIZATION,
        "ACCESS": TokenType.ACCESS,
        "MODE": TokenType.MODE,
        "RECORD": TokenType.RECORD,
        "KEY": TokenType.KEY,
        "ALTERNATE": TokenType.ALTERNATE,
        "DUPLICATES": TokenType.DUPLICATES,
        # NOTE: "FILE-STATUS", "RECORD-DELIMITER", and "READ-ONLY" are
        # deliberately NOT mapped here. Real COBOL syntax always writes these
        # as separate words (FILE STATUS, RECORD DELIMITER, READ ONLY) --
        # every clause parser that recognizes them (environment_select.py's
        # _parse_file_status_clause / _parse_record_key_clause /
        # _parse_sharing_clause) already dispatches on the leading word
        # ("FILE"/"RECORD"/"READ") and consumes the second word as plain
        # text, never as one of these fused tokens. Reserving the hyphenated
        # spelling as a single keyword therefore never matches real syntax --
        # it only ever fires when a program legitimately names a data item or
        # paragraph "FILE-STATUS"/"RECORD-DELIMITER"/"READ-ONLY" (all common
        # in real IBM COBOL), silently corrupting that name. See
        # tests/regression/test_dead_keyword_removal.py.
        "RESERVE": TokenType.RESERVE,
        "AREA": TokenType.AREA,
        "AREAS": TokenType.AREAS,
        "PADDING": TokenType.PADDING,
        "CHARACTER": TokenType.CHARACTER,
        "STANDARD-1": TokenType.STANDARD_1,
        "PASSWORD": TokenType.PASSWORD,
        "LOCK": TokenType.LOCK,
        "SHARING": TokenType.SHARING,
        "WITH": TokenType.WITH,
        "OTHER": TokenType.OTHER,
        "NO": TokenType.NO,
        "SEQUENTIAL": TokenType.SEQUENTIAL,
        "INDEXED": TokenType.INDEXED,
        "RELATIVE": TokenType.RELATIVE,
        "LINE": TokenType.LINE,
        "RANDOM": TokenType.RANDOM,
        "DYNAMIC": TokenType.DYNAMIC,
        "OPTIONAL": TokenType.OPTIONAL,
        # FD/SD clause keywords
        "BLOCK": TokenType.BLOCK,
        "CONTAINS": TokenType.CONTAINS,
        "RECORDS": TokenType.RECORDS,
        "CHARACTERS": TokenType.CHARACTERS,
        "LABEL": TokenType.LABEL,
        "STANDARD": TokenType.STANDARD,
        "OMITTED": TokenType.OMITTED,
        "DATA": TokenType.DATA,
        "LINAGE": TokenType.LINAGE,
        "LINES": TokenType.LINES,
        "FOOTING": TokenType.FOOTING,
        "AT": TokenType.AT,
        "TOP": TokenType.TOP,
        "BOTTOM": TokenType.BOTTOM,
        "CODE-SET": TokenType.CODE_SET,
        "RECORDING": TokenType.RECORDING,
        "EXTERNAL": TokenType.EXTERNAL,
        "GLOBAL": TokenType.GLOBAL,
        "IS": TokenType.IS,
        "ARE": TokenType.ARE,
        "IN": TokenType.IN,
        "OF": TokenType.OF,
        "DEPENDING": TokenType.DEPENDING,
        # Data definition
        "PIC": TokenType.PIC,
        "PICTURE": TokenType.PICTURE,
        "USAGE": TokenType.USAGE,
        "VALUE": TokenType.VALUE,
        "OCCURS": TokenType.OCCURS,
        "REDEFINES": TokenType.REDEFINES,
        "SYNC": TokenType.SYNC,
        "SYNCHRONIZED": TokenType.SYNCHRONIZED,
        "COMP": TokenType.COMP,
        "COMP-1": TokenType.COMP_1,
        "COMP-2": TokenType.COMP_2,
        "COMP-3": TokenType.COMP_3,
        "COMP-4": TokenType.COMP_4,
        "COMP-5": TokenType.COMP_5,
        "COMPUTATIONAL": TokenType.COMPUTATIONAL,
        "DISPLAY": TokenType.DISPLAY,
        # Statements
        "MOVE": TokenType.MOVE,
        "ADD": TokenType.ADD,
        "SUBTRACT": TokenType.SUBTRACT,
        "MULTIPLY": TokenType.MULTIPLY,
        "DIVIDE": TokenType.DIVIDE,
        "COMPUTE": TokenType.COMPUTE,
        "PERFORM": TokenType.PERFORM,
        "IF": TokenType.IF,
        "THEN": TokenType.THEN,
        "ELSE": TokenType.ELSE,
        "END-IF": TokenType.END_IF,
        "EVALUATE": TokenType.EVALUATE,
        "WHEN": TokenType.WHEN,
        "END-EVALUATE": TokenType.END_EVALUATE,
        "CALL": TokenType.CALL,
        "RETURN": TokenType.RETURN,
        "GO": TokenType.GO,
        "GOTO": TokenType.GOTO,
        "STOP": TokenType.STOP,
        "EXIT": TokenType.EXIT,
        "CONTINUE": TokenType.CONTINUE,
        # Additional COBOL Verbs
        "ALTER": TokenType.ALTER,
        "CANCEL": TokenType.CANCEL,
        "CHAIN": TokenType.CHAIN,
        "COMMIT": TokenType.COMMIT,
        "DELETE": TokenType.DELETE,
        "DISABLE": TokenType.DISABLE,
        "DISPLAY-1": TokenType.DISPLAY_1,
        "EJECT": TokenType.EJECT,
        # SKIP1/SKIP2/SKIP3 are compiler-directing listing no-ops, the same
        # class of statement as EJECT (skip 1/2/3 lines in the source
        # listing, no runtime effect). Without a dedicated token type they
        # lexed as plain IDENTIFIERs, fell to the PROCEDURE DIVISION's
        # unrecognized-statement recovery, and dropped both the directive
        # and adjacent tokens from the AST.
        "SKIP1": TokenType.SKIP1,
        "SKIP2": TokenType.SKIP2,
        "SKIP3": TokenType.SKIP3,
        "ENABLE": TokenType.ENABLE,
        "END-INVOKE": TokenType.END_INVOKE,
        "END-PERFORM": TokenType.END_PERFORM,
        # NOTE: "END-SET" is deliberately NOT mapped -- SET has no scope
        # terminator in real COBOL grammar (it carries no conditional/nested
        # body), so this entry never matched real syntax; it only stole a
        # legitimate data-name/paragraph-name spelled "END-SET".
        "ENTER": TokenType.ENTER,
        "ENTRY": TokenType.ENTRY,
        "EXAMINE": TokenType.EXAMINE,
        "EXECUTE": TokenType.EXECUTE,
        "EXHIBIT": TokenType.EXHIBIT,
        "GENERATE": TokenType.GENERATE,
        "GOBACK": TokenType.GOBACK,
        "INITIALIZE": TokenType.INITIALIZE,
        "INITIATE": TokenType.INITIATE,
        "INSPECT": TokenType.INSPECT,
        "INVOKE": TokenType.INVOKE,
        "MERGE": TokenType.MERGE,
        "NEXT": TokenType.NEXT,
        "NOTE": TokenType.NOTE,
        "ON": TokenType.ON,
        # NOTE: "OTHERWISE" is deliberately NOT mapped -- it is not a COBOL
        # reserved word (EVALUATE's default branch is "WHEN OTHER", not
        # "OTHERWISE"); this entry never matched real syntax and only stole
        # a legitimate data-name/paragraph-name spelled "OTHERWISE".
        "READY": TokenType.READY,
        "RECEIVE": TokenType.RECEIVE,
        "RECOVER": TokenType.RECOVER,
        "RELEASE": TokenType.RELEASE,
        "RESET": TokenType.RESET,
        "REWRITE": TokenType.REWRITE,
        "ROLLBACK": TokenType.ROLLBACK,
        "SEARCH": TokenType.SEARCH,
        "SEND": TokenType.SEND,
        "SERVICE": TokenType.SERVICE,
        "SET": TokenType.SET,
        "SORT": TokenType.SORT,
        "START": TokenType.START,
        "STRING": TokenType.STRING,
        "SUPPRESS": TokenType.SUPPRESS,
        "TERMINATE": TokenType.TERMINATE,
        "TRANSFORM": TokenType.TRANSFORM,
        "UNLOCK": TokenType.UNLOCK,
        "UNSTRING": TokenType.UNSTRING,
        "USE": TokenType.USE,
        # I/O
        "SELECT": TokenType.SELECT,
        "READ": TokenType.READ,
        "WRITE": TokenType.WRITE,
        "OPEN": TokenType.OPEN,
        "CLOSE": TokenType.CLOSE,
        "ACCEPT": TokenType.ACCEPT,
        # IO Clause Keywords (additional for IBM Enterprise COBOL)
        "INVALID": TokenType.INVALID,
        # NOTE: multi-word entries ("KEY IS", "WITH LOCK", "NO REWIND",
        # "NO ADVANCING") are deliberately NOT mapped. KEYWORDS is only ever
        # consulted with a single word (read_word_from_text/read_identifier
        # build one word at a time), so a key containing a space can never
        # match -- such entries are unreachable dead weight; the parsers
        # recognize these phrases word by word.
        "END-OF-PAGE": TokenType.END_OF_PAGE,
        "EOP": TokenType.END_OF_PAGE,
        "REWIND": TokenType.NO_REWIND,
        "REEL": TokenType.REEL,
        "UNIT": TokenType.UNIT,
        "ADVANCING": TokenType.ADVANCING,
        # NOTE: "END-OF-FILE" and "EOF" are deliberately NOT mapped. Neither
        # is a COBOL reserved word -- end-of-file testing is done via a
        # READ statement's AT END clause plus a programmer-defined
        # condition-name (level-88), and "EOF"/"END-OF-FILE" are exactly the
        # names real IBM COBOL programs conventionally give that condition
        # (or its backing flag). Reserving them here only ever stole that
        # legitimate name -- see the bare-condition-name handling this
        # breaks in parsers/statements/_conditions.py.
        "POSITION": TokenType.POSITION,
        # Control flow
        "TIMES": TokenType.TIMES,
        "UNTIL": TokenType.UNTIL,
        "VARYING": TokenType.VARYING,
        "FROM": TokenType.FROM,
        "TO": TokenType.TO,
        "BY": TokenType.BY,
        "AFTER": TokenType.AFTER,
        "BEFORE": TokenType.BEFORE,
        "TEST": TokenType.TEST,
        "INTO": TokenType.INTO,
        "USING": TokenType.USING,
        # Conditions
        "EQUAL": TokenType.EQUAL,
        "NOT": TokenType.NOT,
        "AND": TokenType.AND,
        "OR": TokenType.OR,
        "GREATER": TokenType.GREATER,
        "LESS": TokenType.LESS,
        "THAN": TokenType.THAN,
        # IBM Extensions
        "EXEC": TokenType.EXEC,
        "SQL": TokenType.SQL,
        "CICS": TokenType.CICS,
        "END-EXEC": TokenType.END_EXEC,
        "INCLUDE": TokenType.INCLUDE,
        "COPY": TokenType.COPY,
        "REPLACING": TokenType.REPLACING,
        # FUNCTION is deliberately absent – see TokenType.FUNCTION comment.
    }
    KEYWORDS = {sys.intern(k): v for k, v in KEYWORDS.items()}

    # Figurative constants
    FIGURATIVE_CONSTANTS = {
        "ZERO",
        "ZEROS",
        "ZEROES",
        "SPACE",
        "SPACES",
        "HIGH-VALUE",
        "HIGH-VALUES",
        "LOW-VALUE",
        "LOW-VALUES",
        "QUOTE",
        "QUOTES",
        "ALL",
        # NULL/NULLS: the VALUE of USAGE POINTER / PROCEDURE-POINTER /
        # FUNCTION-POINTER data items (VALUE IS NULL) and the operand of
        # SET ptr TO NULL / relational pointer comparisons. Several
        # analysis modules (analysis/move_type_checker.py,
        # analysis/constraints.py, generators/data/values.py) already
        # carried their own private NULL/NULLS figurative-constant lists in
        # anticipation of this; the lexer is the single source of truth for
        # token classification, so it belongs here too.
        "NULL",
        "NULLS",
    }

    # Typed-literal prefixes (IBM Enterprise COBOL and ISO COBOL).
    # A single letter (or the two-letter ``NX``) immediately followed by a
    # quote/apostrophe introduces a typed literal rather than an identifier:
    #   X"1F"    hexadecimal (alphanumeric)        Z"abc"   null-terminated
    #   N"abc"   national                          U"abc"   UTF-8
    #   NX"00C1" national hexadecimal              G"<dbcs>" DBCS / graphic
    #   B"1010"  boolean
    # The single-letter prefixes; ``NX`` is handled as a special two-char case.
    LITERAL_PREFIXES = frozenset({"X", "N", "G", "Z", "U", "B"})

    def __init__(
        self,
        source: str,
        filename: str = "<string>",
        dialect: DialectType = DialectType.IBM_ENTERPRISE,
        free_form: bool = False,
    ):
        """Initialize the COBOL lexer.

        Args:
            source: COBOL source code to tokenize
            filename: Source filename for error reporting
            dialect: COBOL dialect for lexing rules
        """
        self.source = source
        self.filename = filename
        self.dialect = dialect
        self.lines = split_source_lines(source)
        self.current_line = 0
        self.current_column = 0
        self.current_pos = 0
        self.tokens: list[Token] = []
        self.errors: list[LexerError] = []
        self.warnings: list[str] = []
        self.free_form = free_form
        # Multi-line string continuation state
        self._open_string_quote: str | None = None
        self._open_string_value: list[str] = []
        self._open_string_location: SourceLocation | None = None
        # PICTURE currency symbols declared by SPECIAL-NAMES CURRENCY SIGN
        # clauses (lexed as CURRENCY tokens, like ``$``).
        #: Each one's currency string (``{"#": "EUR"}``), for the parser to
        #: hand to the PICTURE clauses that use it.
        self.currency_signs: dict[str, str] = declared_currency_signs(
            source, fixed_format=not free_form
        )
        self._currency_symbols: frozenset[str] = frozenset(self.currency_signs)
        # ``DECIMAL-POINT IS COMMA``: ``,`` between digits is the decimal
        # point of a numeric literal and ``.`` is not. A decimal literal's
        # token keeps the canonical ``.`` spelling in ``value`` (every
        # consumer reads it as a number) and the source text in
        # ``raw_value``.
        self.decimal_point_is_comma: bool = declares_decimal_point_comma(
            source, fixed_format=not free_form
        )
        self._decimal_char: str = "," if self.decimal_point_is_comma else "."

    def _comment_entry_line_tokens(
        self, text: str, line_num: int, start_col: int, entry_start: int
    ) -> list[Token]:
        """Tokenize one line holding comment-entry text.

        Whatever precedes *entry_start* (the ``AUTHOR.`` paragraph name, or
        nothing on a continuation line) is ordinary program text; the rest
        of the line is one COMMENT_ENTRY token holding the text verbatim.
        """
        tokens: list[Token] = self.tokenize_program_text(
            text[:entry_start], line_num, start_col
        )
        rest = text[entry_start:]
        body = rest.strip()
        if body:
            offset = entry_start + (len(rest) - len(rest.lstrip()))
            tokens.append(
                Token(
                    TokenType.COMMENT_ENTRY,
                    body,
                    SourceLocation(line_num + 1, start_col + offset, len(body)),
                )
            )
        return tokens

    def _is_figurative_constant(self, word: str) -> bool:
        """Check if word is a COBOL figurative constant.

        Args:
            word: The word to check (will be uppercased)

        Returns:
            True if word is a figurative constant, False otherwise
        """
        return word.upper().strip() in self.FIGURATIVE_CONSTANTS

    def get_current_location(self) -> SourceLocation:
        """Get current source location."""
        return SourceLocation(self.current_line + 1, self.current_column + 1, 1)

    def peek_char(self, offset: int = 0) -> str | None:
        """Peek at character at current position + offset."""
        pos = self.current_pos + offset
        if pos >= len(self.source):
            return None
        return self.source[pos]

    def advance_char(self) -> str | None:
        """Advance to next character and return it."""
        if self.current_pos >= len(self.source):
            return None

        char = self.source[self.current_pos]
        self.current_pos += 1

        if char == "\n":
            self.current_line += 1
            self.current_column = 0
        else:
            self.current_column += 1

        return char

    def skip_whitespace(self) -> None:
        """Skip whitespace characters except newlines."""
        while True:
            char = self.peek_char()
            if char is None or char not in " \t\r":
                break
            self.advance_char()

    def read_string_literal(self, quote_char: str) -> Token:
        """Read a string literal enclosed in quotes or apostrophes, with COBOL multi-line support."""
        start_location = self.get_current_location()
        # Accumulate characters into a list and join once. ``s += c`` in a
        # loop is amortised O(n) only when the interpreter can prove the
        # string has refcount 1 — fragile, and worst-case O(n²) on long
        # literals. Lists give us a guaranteed O(n) construction.
        chars: list[str] = []
        self.advance_char()  # Skip opening quote

        while True:
            char = self.peek_char()
            if char is None:
                # Unterminated string - add error
                self.errors.append(
                    LexerError(
                        "Unterminated string literal",
                        start_location,
                        quote_char + "".join(chars),
                    )
                )
                break

            if char == quote_char:
                self.advance_char()  # Skip closing quote
                # Check for doubled quote (escape sequence)
                if self.peek_char() == quote_char:
                    chars.append(quote_char)
                    self.advance_char()
                else:
                    break
            else:
                chars.append(char)
                self.advance_char()

        return Token(TokenType.STRING_LITERAL, "".join(chars), start_location)

    def read_numeric_literal(self) -> Token:
        """Read a numeric literal (integer or decimal)."""
        start_location = self.get_current_location()
        # See ``read_string_literal`` for the rationale on list+join vs ``+=``.
        chars: list[str] = []
        has_decimal = False
        has_exponent = False
        has_digit = False

        while True:
            char = self.peek_char()
            if char is None:
                break

            if char.isdigit():
                chars.append(char)
                has_digit = True
                self.advance_char()
            elif char == "." and not has_decimal and not has_exponent:
                has_decimal = True
                chars.append(char)
                self.advance_char()
            elif char in "Ee" and has_digit and not has_exponent:
                # Scientific notation: require at least one digit before E.
                has_exponent = True
                chars.append(char)
                self.advance_char()
                next_char = self.peek_char()
                if next_char and next_char in "+-":
                    chars.append(next_char)
                    self.advance_char()
            else:
                break

        return Token(TokenType.NUMERIC_LITERAL, "".join(chars), start_location)

    def read_identifier(self) -> Token:
        """Read an identifier or keyword."""
        start_location = self.get_current_location()
        chars = []

        while True:
            char = self.peek_char()
            if char is None:
                break

            if char.isalnum() or char in "-_":
                chars.append(char)
                self.advance_char()
            else:
                break

        value = "".join(chars)

        # Check if it's a keyword
        upper_value = sys.intern(value.upper())
        if upper_value in self.KEYWORDS:
            token_type = self.KEYWORDS[upper_value]
        elif upper_value in self.FIGURATIVE_CONSTANTS:
            token_type = TokenType.FIGURATIVE_CONSTANT
        elif _LEVEL_NUM_RE.match(value):  # Level numbers 01-99
            token_type = TokenType.LEVEL_NUMBER
        else:
            token_type = TokenType.IDENTIFIER

        return Token(token_type, value, start_location)

    def read_comment(self) -> Token:
        """Read a comment (line starting with * in column 7 or inline)."""
        start_location = self.get_current_location()
        chars = []

        # Read until end of line
        while True:
            char = self.peek_char()
            if char is None or char == "\n":
                break
            chars.append(char)
            self.advance_char()

        return Token(TokenType.COMMENT, "".join(chars), start_location)

    def handle_cobol_line_format(self, line: str, line_num: int) -> list[Token]:
        """Handle COBOL fixed-format line structure.

        COBOL lines have specific column meanings:
        - Columns 1-6: Sequence number
        - Column 7: Indicator (*, /, D, -, space)
        - Columns 8-72: Program text
        - Columns 73-80: Identification (ignored)
        """
        line_tokens: list[Token] = []

        if len(line) < 7:
            return line_tokens

        # Check column 7 indicator
        indicator = line[_FF_INDICATOR] if len(line) > _FF_INDICATOR else " "

        if indicator == "*":
            # Comment line
            comment_text = (
                line[_FF_INDICATOR:_FF_LINE_END].rstrip()
                if len(line) > _FF_INDICATOR
                else ""
            )
            location = SourceLocation(line_num + 1, 7, 1)
            line_tokens.append(Token(TokenType.COMMENT, comment_text, location))
            return line_tokens

        if indicator == "/":
            # Page break - treat as comment
            location = SourceLocation(line_num + 1, 7, 1)
            line_tokens.append(Token(TokenType.COMMENT, "/ PAGE BREAK", location))
            return line_tokens

        if indicator == "-":
            # Continuation line
            location = SourceLocation(line_num + 1, 7, 1)
            line_tokens.append(Token(TokenType.CONTINUATION, "-", location))

        # Extract program text (columns 8-72)
        program_text = line[_FF_AREA_A:_FF_LINE_END] if len(line) > _FF_AREA_A else ""

        # Special handling for VALUE clause with unterminated string pattern
        program_text_upper = program_text.upper()
        if (
            not self._open_string_quote
            and "VALUE" in program_text_upper
            and '"' in program_text
        ):
            # Check if this line has VALUE followed by unterminated string and next line is continuation
            value_upper = program_text_upper
            value_pos = value_upper.find("VALUE")
            if value_pos != -1:
                after_value = program_text[value_pos + 5 :].strip()
                # Skip "IS" if present
                if after_value.upper().startswith("IS"):  # short string, cheap
                    after_value = after_value[2:].strip()

                # Check if VALUE is followed by a figurative constant - if so, skip string mode
                first_word = after_value.split()[0] if after_value.split() else ""
                if self._is_figurative_constant(first_word):
                    # VALUE with figurative constant, not a string literal - proceed normally
                    pass
                elif after_value.startswith('"'):
                    # Find if there's a closing quote
                    content_after_quote = after_value[1:]
                    if '"' not in content_after_quote:  # Unterminated string
                        # Check if next line is continuation
                        if line_num + 1 < len(self.lines):
                            next_line = self.lines[line_num + 1]
                            if (
                                len(next_line) > _FF_INDICATOR
                                and next_line[_FF_INDICATOR] == "-"
                            ):
                                # This is a VALUE with unterminated string - start multi-line mode
                                self._open_string_quote = '"'
                                self._open_string_location = SourceLocation(
                                    line_num + 1, 8 + value_pos + 5, 1
                                )
                                self._open_string_value = [content_after_quote]

                                # Tokenize everything up to but not including the string
                                before_string = (
                                    program_text[: value_pos + 5].strip() + " "
                                )
                                if before_string.strip():
                                    before_tokens = self.tokenize_program_text(
                                        before_string, line_num, 8
                                    )
                                    line_tokens.extend(before_tokens)
                                return line_tokens

        # Check for multi-line string pattern: current line starts with quote and next line has continuation
        if not self._open_string_quote and program_text.strip().startswith('"'):
            # Look ahead to see if next line has continuation marker
            if line_num + 1 < len(self.lines):
                next_line = self.lines[line_num + 1]
                if len(next_line) > _FF_INDICATOR and next_line[_FF_INDICATOR] == "-":
                    # This is the start of a multi-line string literal
                    quote_char = '"'
                    quote_pos = program_text.find(quote_char)
                    self._open_string_quote = quote_char
                    self._open_string_location = SourceLocation(
                        line_num + 1, 8 + quote_pos, 1
                    )
                    self._open_string_value = []
                    # Add content after opening quote on this line
                    content_after_quote = program_text[quote_pos + 1 :]
                    if content_after_quote:
                        self._open_string_value.append(content_after_quote)
                    return line_tokens

            # Also check if this could be a multi-line string even without continuation on next line
            # This handles cases where the string continues but the structure is complex
            prev_line = self.lines[line_num - 1] if line_num > 0 else ""
            if "VALUE" in prev_line.upper():
                # Create a complete string token from this line, looking for closing quote
                quote_pos = program_text.find('"')
                if quote_pos != -1:
                    # Try to find closing quote on same line first
                    remaining_text = program_text[quote_pos + 1 :]
                    closing_quote_pos = remaining_text.find('"')
                    if closing_quote_pos == -1:
                        # No closing quote on this line - create a string token anyway for COBOL compatibility
                        string_content = remaining_text
                        string_token = Token(
                            TokenType.STRING_LITERAL,
                            string_content,
                            SourceLocation(line_num + 1, 8 + quote_pos, 1),
                        )
                        line_tokens.append(string_token)
                        return line_tokens

        # If continuing a multi-line string, check if this line is actually a comment
        # If so, clear the string state and process as comment instead
        if self._open_string_quote is not None:
            # Check if continuation line is a comment - if so, clear string state
            if indicator == "*" or indicator == "/":
                # This is a comment line interrupting the multi-line string
                # Clear the string state
                self._open_string_quote = None
                self._open_string_value = []
                self._open_string_location = None
                # Process as normal comment line
                comment_text = (
                    line[_FF_INDICATOR:_FF_LINE_END].rstrip()
                    if len(line) > _FF_INDICATOR
                    else ""
                )
                location = SourceLocation(line_num + 1, 7, 1)
                line_tokens.append(Token(TokenType.COMMENT, comment_text, location))
                return line_tokens

            # Not a comment - continue with multi-line string processing
            closed, remainder_tokens = self._continue_multiline_string(
                program_text, line_num
            )
            if remainder_tokens:
                line_tokens.extend(remainder_tokens)
            if not closed:
                # Entire line consumed as part of string
                return line_tokens
        else:
            # Check if this is a line that starts a multi-line string that we missed
            # This happens when a VALUE clause spans multiple lines
            stripped_text = program_text.strip()
            if stripped_text.startswith('"'):
                # Check if this looks like a string continuation (either has '-' marker or follows VALUE)
                is_continuation = indicator == "-"
                if not is_continuation and line_num > 0:
                    prev_line = self.lines[line_num - 1]
                    if prev_line.strip().upper().endswith("VALUE"):
                        is_continuation = True

                if is_continuation:
                    # This is a continuation line starting with a quote - handle as string continuation
                    quote_char = stripped_text[0]
                    # Find where the quote actually starts in the program text
                    quote_pos = program_text.find(quote_char)
                    if quote_pos >= 0:
                        # Start multi-line string handling from this position
                        self._open_string_quote = quote_char
                        self._open_string_location = SourceLocation(
                            line_num + 1, 8 + quote_pos, 1
                        )
                        self._open_string_value = []
                        # Process this line as a continuation
                        closed, remainder_tokens = self._continue_multiline_string(
                            program_text, line_num
                        )
                        if remainder_tokens:
                            line_tokens.extend(remainder_tokens)
                        return line_tokens

            # Normal tokenization when not inside a continued string
            program_tokens = self.tokenize_program_text(program_text, line_num, 8)
            line_tokens.extend(program_tokens)

        return line_tokens

    def tokenize_program_text(
        self, text: str, line_num: int, start_col: int
    ) -> list[Token]:
        """Tokenize COBOL program text from a line."""
        tokens: list[Token] = []
        pos = 0
        length = len(text)

        while pos < length:
            char = text[pos]

            # Skip whitespace (no location needed)
            if char in " \t":
                pos += 1
                continue

            location = SourceLocation(line_num + 1, start_col + pos, 1)

            # String literals
            if char in "\"'":
                # Check if this line starts with a quote - could be continuation from previous VALUE.
                # Use a short-circuit scan rather than allocating ``text[:pos].strip()``.
                if pos == 0:
                    is_line_start_quote = True
                else:
                    is_line_start_quote = True
                    for _ws_i in range(pos):
                        if text[_ws_i] not in " \t":
                            is_line_start_quote = False
                            break

                token, new_pos, unterminated = self._try_single_line_string(
                    text, pos, line_num, start_col
                )
                if unterminated:
                    # Check if next line has continuation marker OR if current line might be continuation of VALUE
                    next_line_index = line_num + 1
                    current_line = (
                        self.lines[line_num] if line_num < len(self.lines) else ""
                    )
                    start_continuation = False

                    if not self.free_form:
                        # Check if next line has continuation marker
                        if next_line_index < len(self.lines):
                            next_line = self.lines[next_line_index]
                            if (
                                len(next_line) > _FF_INDICATOR
                                and next_line[_FF_INDICATOR] == "-"
                            ):
                                start_continuation = True

                        # Also check if current line is a continuation of a VALUE clause
                        # (string starts at beginning of line after whitespace)
                        if (
                            is_line_start_quote
                            and len(current_line) > 6
                            and current_line[_FF_INDICATOR] == "-"
                        ):
                            start_continuation = True

                        # Special case: VALUE clause spanning lines
                        # Check if this line has VALUE followed by unterminated string
                        current_line_upper = current_line.upper()
                        if (
                            "VALUE" in current_line_upper
                            and next_line_index < len(self.lines)
                            and len(self.lines[next_line_index]) > _FF_INDICATOR
                            and self.lines[next_line_index][_FF_INDICATOR] == "-"
                        ):
                            start_continuation = True

                    if start_continuation:
                        self._open_string_quote = char
                        self._open_string_location = SourceLocation(
                            line_num + 1, start_col + pos, 1
                        )
                        # Append partial value (excluding opening quote)
                        if new_pos > pos + 1:
                            self._open_string_value.append(text[pos + 1 : new_pos])
                        else:
                            # No content on this line after the quote, just the opening quote
                            pass
                        # Stop tokenizing remaining of this line (all considered part of literal)
                        return tokens
                    else:
                        # This is clearly an unterminated string.
                        # However, for free-form COBOL, an isolated quote in a comment
                        # (e.g., COMPILER"S) should not cause the entire lexing to fail.
                        # We emit it as a loose string token but don't add a LexerError
                        # if free_form is true, to make the parser more robust.
                        partial_value = (
                            text[pos + 1 : new_pos] if new_pos > pos + 1 else ""
                        )
                        err_location = SourceLocation(line_num + 1, start_col + pos, 1)
                        if not self.free_form:
                            self.errors.append(
                                LexerError(
                                    "Unterminated string literal",
                                    err_location,
                                    char + partial_value,
                                )
                            )
                        else:
                            # Not promoted to a hard error (H7): a lone
                            # quote can legitimately appear in a free-form
                            # comment (e.g. COMPILER"S) and forcing that to
                            # fail would be worse than the silence being
                            # fixed here. Surface it as a warning instead so
                            # a caller checking ParseResult.warnings is no
                            # longer blind to the literal being silently
                            # closed at the line boundary.
                            self.warnings.append(
                                f"Unterminated string literal at line "
                                f"{line_num + 1}, column {start_col + pos}: "
                                "closed at end of line instead of a matching "
                                "quote"
                            )
                        tokens.append(
                            Token(TokenType.STRING_LITERAL, partial_value, err_location)
                        )
                        pos = new_pos
                        continue
                else:
                    if token is not None:
                        tokens.append(token)
                    pos = new_pos
                    continue

            # Check for identifiers that start with digits (e.g., 42-DATANAMES)
            if char.isdigit():
                # Advance past leading digits (position only — no string needed)
                lookahead_pos = pos
                while lookahead_pos < length and (text[lookahead_pos].isdigit()):
                    lookahead_pos += 1

                # If a scientific-notation-shaped exponent (E/e, optional
                # sign, digits) follows immediately, skip past it too before
                # deciding identifier vs number -- a bare `43E00` is a
                # number, but `43E00-PROD` is a single hyphenated
                # paragraph/data name whose first segment merely happens to
                # look like an exponent. Checking only the character right
                # after the leading digit run (as below) misread every such
                # name as a numeric literal followed by a stray MINUS and
                # identifier.
                exponent_end = lookahead_pos
                if exponent_end < length and text[exponent_end].upper() == "E":
                    probe = exponent_end + 1
                    if probe < length and text[probe] in ("+", "-"):
                        probe += 1
                    digits_start = probe
                    while probe < length and text[probe].isdigit():
                        probe += 1
                    if probe > digits_start:
                        exponent_end = probe

                # Walk any further hyphen-joined segments (each a digit run
                # or a letter run) looking for a letter anywhere in the rest
                # of the word -- a single one-hop lookahead misses names
                # like `22310-01-TRAITE`, where the first letter only
                # appears two hyphens in. The first letter found settles the
                # question, so both loops stop there -- read_word_from_text
                # re-scans the whole word anyway.
                has_alpha = False
                scan_pos = exponent_end
                while (
                    not has_alpha
                    and scan_pos < length
                    and text[scan_pos] == "-"
                    and scan_pos + 1 < length
                    and text[scan_pos + 1].isalnum()
                ):
                    scan_pos += 1
                    while scan_pos < length and text[scan_pos].isalnum():
                        if text[scan_pos].isalpha():
                            has_alpha = True
                            break
                        scan_pos += 1

                # Check if after the digits (and any exponent-shaped suffix)
                # we have a direct letter (identifier patterns like 25COUNT,
                # 45A). The dash-then-letter case (42-DATANAMES) is already
                # covered: the hyphen-segment scan above sets has_alpha for
                # it, and when an exponent was consumed the character at
                # lookahead_pos is E/e, never a dash.
                # Scientific notation (3E2, 1E+5) is excluded: E/e followed by
                # a digit or sign+digit stays on the read_number_from_text path.
                if has_alpha or (
                    lookahead_pos < length
                    and text[lookahead_pos].isalpha()
                    and not (
                        text[lookahead_pos].upper() == "E"
                        and (
                            (
                                lookahead_pos + 1 < length
                                and text[lookahead_pos + 1].isdigit()
                            )
                            or (
                                lookahead_pos + 2 < length
                                and text[lookahead_pos + 1] in ("+", "-")
                                and text[lookahead_pos + 2].isdigit()
                            )
                        )
                    )
                ):
                    # This looks like an identifier starting with digits
                    token, new_pos = self.read_word_from_text(
                        text, pos, line_num, start_col
                    )
                    tokens.append(token)
                    pos = new_pos
                    continue
                else:
                    # Regular numeric literal
                    token, new_pos = self.read_number_from_text(
                        text, pos, line_num, start_col
                    )
                    tokens.append(token)
                    pos = new_pos
                    continue

            # Typed literals (X"..", N"..", G"..", Z"..", U"..", B"..", NX"..").
            # These must be checked before the identifier path, otherwise the
            # leading prefix letter would be consumed as a separate identifier.
            if char.upper() in self.LITERAL_PREFIXES:
                prefixed = self.read_prefixed_literal_from_text(
                    text, pos, line_num, start_col
                )
                if prefixed is not None:
                    token, new_pos = prefixed
                    tokens.append(token)
                    pos = new_pos
                    continue

            # Identifiers and keywords
            if char.isalpha() or char == "_":
                token, new_pos = self.read_word_from_text(
                    text, pos, line_num, start_col
                )
                tokens.append(token)
                pos = new_pos
                continue

            # Free-form inline comment: `*>` marks everything from here to
            # end of line as a comment (COBOL free-form syntax, legal in
            # both fixed- and free-form source). Checked before the
            # single-character-token dispatch below so `*` isn't read as
            # MULTIPLY_OP when followed by `>`. Emitted as a COMMENT token
            # (rather than dropped outright) to match the whole-line
            # comment handling elsewhere in the lexer — statement parsers
            # already skip COMMENT tokens via skip_whitespace().
            if char == "*" and pos + 1 < length and text[pos + 1] == ">":
                tokens.append(Token(TokenType.COMMENT, text[pos:], location))
                pos = length
                continue

            # Single character tokens (class-level dict for performance)
            if char in self.SINGLE_CHAR_TOKENS:
                # Leading-decimal numeric literals: .7  .25  .003 — valid COBOL.
                # A period followed immediately by a digit is a number, not a
                # statement terminator (terminators are always trailed by whitespace
                # or end-of-line in normalised free-form text).
                # Under DECIMAL-POINT IS COMMA the leading decimal is ``,5``
                # -- written after a space (``VALUE ,5``); a comma glued to
                # the word before it (``A,5``) stays a separator.
                if (
                    char == self._decimal_char
                    and pos + 1 < length
                    and text[pos + 1].isdigit()
                    and (char == "." or pos == 0 or text[pos - 1] in " \t")
                ):
                    token, new_pos = self.read_number_from_text(
                        text, pos, line_num, start_col
                    )
                    tokens.append(token)
                    pos = new_pos
                else:
                    tokens.append(Token(self.SINGLE_CHAR_TOKENS[char], char, location))
                    pos += 1
                continue

            # Allow ampersand as a benign separator (appears in some validation suites)
            if char == "&":
                # COBOL does not normally use '&' outside of some compiler directives or text
                # concatenations in vendor extensions. We treat it as an ignorable separator so
                # it doesn't raise a hard lexer error. If future semantics are needed we can
                # introduce a specific token type.
                pos += 1
                continue

            # A PICTURE currency symbol declared by SPECIAL-NAMES
            # (``CURRENCY SIGN IS '£'``) -- an editing symbol like ``$``.
            if char in self._currency_symbols:
                tokens.append(Token(TokenType.CURRENCY, char, location))
                pos += 1
                continue

            # Unknown character – record an error and advance
            self.errors.append(LexerError(f"Invalid character: {char}", location, char))
            pos += 1

        return tokens

    def read_prefixed_literal_from_text(
        self, text: str, start_pos: int, line_num: int, start_col: int
    ) -> tuple[Token, int] | None:
        """Read a typed literal such as ``X"1F"``, ``N'abc'`` or ``NX"00C1"``.

        Returns ``(token, new_pos)`` when ``text[start_pos]`` begins a typed
        literal (a recognised prefix immediately followed by a quote), or
        ``None`` when it does not — in which case the caller falls back to the
        normal identifier/keyword path.

        The resulting token keeps the literal *content* in ``value`` (so every
        existing consumer of ``STRING_LITERAL`` continues to work unchanged)
        and the original prefixed source text in ``raw_value`` (e.g. ``X"1F"``)
        so downstream analysis can still recover the literal kind.

        Unterminated typed literals are handled exactly like an unterminated
        plain string in the main loop: a ``LexerError`` is recorded only in
        fixed-format mode, while free-form mode stays lenient (a stray quote
        must not turn into a hard lexer failure).
        """
        length = len(text)
        first = text[start_pos]
        if first.upper() not in self.LITERAL_PREFIXES:
            return None

        # Determine prefix length: the two-letter ``NX`` national-hex or
        # ``UX`` UTF-8-hex form, or a single-letter prefix. The prefix must be
        # immediately followed by a quote character with no intervening
        # whitespace. ``UX`` used to fall through to the identifier path, so
        # ``UX"C3A9"`` lexed as the word ``UX`` plus the text literal "C3A9".
        prefix_len = 1
        if (
            first.upper() in ("N", "U")
            and start_pos + 1 < length
            and text[start_pos + 1].upper() == "X"
        ):
            prefix_len = 2

        quote_pos = start_pos + prefix_len
        if quote_pos >= length or text[quote_pos] not in "\"'":
            return None

        location = SourceLocation(line_num + 1, start_col + start_pos, 1)
        # Use the same fast single-line reader as the plain-string path so the
        # error-suppression behaviour matches and we avoid the slower
        # ``read_string_from_text``.
        token, new_pos, unterminated = self._try_single_line_string(
            text, quote_pos, line_num, start_col
        )
        if unterminated:
            partial = text[quote_pos + 1 : new_pos] if new_pos > quote_pos + 1 else ""
            if not self.free_form:
                self.errors.append(
                    LexerError(
                        "Unterminated string literal",
                        location,
                        text[start_pos:new_pos],
                    )
                )
            else:
                # Same non-fatal diagnostic the plain-literal path emits
                # (H7): free-form closes the literal at end of line, but a
                # caller checking warnings must not be blind to it.
                self.warnings.append(
                    f"Unterminated string literal at line {line_num + 1}, "
                    f"column {start_col + start_pos}: closed at end of line "
                    "instead of a matching quote"
                )
            token = Token(TokenType.STRING_LITERAL, partial, location)

        assert token is not None
        token.raw_value = text[start_pos:new_pos]
        token.location = location

        # Hex-content validation for X'..'/NX'..' typed literals only
        # (G'..'/N'..' have different, codepage-dependent validity rules
        # that this parser does not attempt to decode -- M7 scopes this
        # fix to the unambiguous hex case).
        is_hex_prefix = (first.upper() == "X" and prefix_len == 1) or prefix_len == 2
        if is_hex_prefix and not unterminated:
            hex_content = token.value or ""
            if hex_content:
                invalid_chars = set(hex_content) - set("0123456789ABCDEFabcdef")
                if invalid_chars:
                    self.warnings.append(
                        f"Invalid hex digit(s) {sorted(invalid_chars)!r} in "
                        f"typed literal {token.raw_value} at line "
                        f"{location.line}, column {location.column}"
                    )
                elif len(hex_content) % 2 != 0:
                    self.warnings.append(
                        f"Typed literal {token.raw_value} at line "
                        f"{location.line}, column {location.column} has an "
                        "odd number of hex digits (each byte needs two)"
                    )
        return token, new_pos

    def read_string_from_text(
        self, text: str, start_pos: int, line_num: int, start_col: int
    ) -> tuple[Token, int]:
        """Read string literal from text starting at position."""
        quote_char = text[start_pos]
        location = SourceLocation(line_num + 1, start_col + start_pos, 1)
        value = ""
        pos = start_pos + 1

        while pos < len(text):
            char = text[pos]
            if char == quote_char:
                pos += 1
                # Check for doubled quote
                if pos < len(text) and text[pos] == quote_char:
                    value += quote_char
                    pos += 1
                else:
                    break
            else:
                value += char
                pos += 1

        # Check if string was unterminated
        if pos >= len(text) and (pos == start_pos + 1 or text[pos - 1] != quote_char):
            # For COBOL multi-line strings, be more permissive only in specific contexts
            # Check if this could be a legitimate multi-line continuation
            current_line = self.lines[line_num] if line_num < len(self.lines) else ""
            is_multi_line_context = (
                not self.free_form
                and len(current_line) > 6
                and current_line[_FF_INDICATOR] == "-"  # Continuation line
                and line_num > 0  # Not the first line
                and (
                    "VALUE"
                    in self.lines[line_num - 1].upper()  # Previous line has VALUE
                    or any(
                        '"' in line or "'" in line
                        for line in self.lines[max(0, line_num - 2) : line_num]
                    )
                )  # Recent quotes
            )

            if is_multi_line_context:
                # Be permissive: this is a legitimate fixed-format continuation line
                pass
            else:
                # Emit error for truly unterminated strings
                self.errors.append(
                    LexerError(
                        "Unterminated string literal", location, quote_char + value
                    )
                )

        return Token(TokenType.STRING_LITERAL, value, location), pos

    def _try_single_line_string(
        self, text: str, start_pos: int, line_num: int, start_col: int
    ) -> tuple[Token | None, int, bool]:
        """Attempt to read a single-line string, detecting unterminated case without error.
        Returns (token_or_None, new_pos, unterminated_flag)."""
        quote = text[start_pos]
        location = SourceLocation(line_num + 1, start_col + start_pos, 1)
        # Accumulate characters into a list and join once. ``s += c`` in a
        # loop is amortised O(n) only when the interpreter can prove the
        # string has refcount 1 — fragile, and worst-case O(n²) on long
        # literals. Lists give us a guaranteed O(n) construction.
        chars: list[str] = []
        pos = start_pos + 1
        while pos < len(text):
            ch = text[pos]
            if ch == quote:
                # doubled quote escape
                if pos + 1 < len(text) and text[pos + 1] == quote:
                    chars.append(quote)
                    pos += 2
                    continue
                pos += 1
                return (
                    Token(TokenType.STRING_LITERAL, "".join(chars), location),
                    pos,
                    False,
                )
            else:
                chars.append(ch)
                pos += 1
        # Not closed on this line - check if this could be a multi-line string
        return None, pos, True

    def _compress_doubled_quotes(self, text: str, quote_char: str) -> str:
        """Compress doubled quotes in string content (COBOL escape sequence).

        In COBOL, doubled quotes of the same type as the delimiter represent a single quote.
        Additionally, for continuation line compatibility, doubled single quotes are also
        compressed to single quotes when inside double-quoted strings.
        """
        if '"' not in text and "'" not in text:
            return text

        result = []
        i = 0
        while i < len(text):
            # Check for doubled delimiter quotes (standard COBOL escaping)
            if (
                text[i] == quote_char
                and i + 1 < len(text)
                and text[i + 1] == quote_char
            ):
                result.append(quote_char)
                i += 2
            # Special case: compress doubled single quotes in double-quoted strings (continuation compatibility)
            elif (
                quote_char == '"'
                and text[i] == "'"
                and i + 1 < len(text)
                and text[i + 1] == "'"
            ):
                result.append("'")
                i += 2
            else:
                result.append(text[i])
                i += 1
        return "".join(result)

    def _continue_multiline_string(
        self, program_text: str, line_num: int
    ) -> tuple[bool, list[Token]]:
        """Continue scanning a multi-line string; return (closed, remainder_tokens)."""
        remainder_tokens: list[Token] = []
        quote = self._open_string_quote
        assert quote is not None

        # Skip leading whitespace on continuation lines but preserve the quote structure
        stripped_text = program_text.lstrip()

        # For continuation lines starting with quotes, skip the opening quote first
        # before looking for the closing quote
        search_text = stripped_text
        if stripped_text.startswith(quote):
            # This is a continuation line that starts with the same quote character
            # Skip it and search for the closing quote in the rest of the line
            search_text = stripped_text[1:]

        # Scan character by character to find the closing quote, handling doubled quotes
        pos = 0
        content_chars = []
        found_closing_quote = False

        while pos < len(search_text):
            char = search_text[pos]

            if char == quote:
                # Check if this is a doubled quote (escape sequence)
                if pos + 1 < len(search_text) and search_text[pos + 1] == quote:
                    # Doubled quote - add single quote to content and skip both
                    content_chars.append(quote)
                    pos += 2
                    continue
                else:
                    # Single quote - this is the closing quote
                    found_closing_quote = True
                    pos += 1  # Move past the closing quote
                    break
            else:
                # Regular character
                content_chars.append(char)
                pos += 1

        if found_closing_quote:
            # Found closing quote - add accumulated content
            if content_chars:
                self._open_string_value.append("".join(content_chars))

            token = Token(
                TokenType.STRING_LITERAL,
                "".join(self._open_string_value),
                self._open_string_location or SourceLocation(line_num + 1, 8, 1),
            )
            self._open_string_quote = None
            self._open_string_value = []
            self._open_string_location = None
            remainder_tokens.append(token)
            # Tokenize rest of line after quote
            remainder_text = search_text[pos:]
            if remainder_text:
                # Calculate correct column position for remainder
                whitespace_len = len(program_text) - len(stripped_text)
                # Account for the skipped opening quote if present
                quote_offset = 1 if stripped_text.startswith(quote) else 0
                remainder_tokens.extend(
                    self.tokenize_program_text(
                        remainder_text,
                        line_num,
                        8 + whitespace_len + quote_offset + pos,
                    )
                )
            return True, remainder_tokens

        # No closing quote found - append entire content as continuation
        if content_chars:
            self._open_string_value.append("".join(content_chars))

        # Validate that this physical line is actually marked as a continuation ('-' in column 7)
        if not self.free_form:
            src_line = self.lines[line_num] if line_num < len(self.lines) else ""
            if not (len(src_line) > _FF_INDICATOR and src_line[_FF_INDICATOR] == "-"):
                # Not a valid continuation line -> emit token without error for robust parsing
                loc = self._open_string_location or SourceLocation(line_num + 1, 8, 1)
                # For COBOL robustness, emit the string token even if continuation is imperfect
                # Only emit error if the string content is very short (likely truly malformed)
                string_content = "".join(self._open_string_value)
                if len(string_content) <= 3:  # Very short strings are likely errors
                    self.errors.append(
                        LexerError(
                            "Unterminated string literal (missing continuation line)",
                            loc,
                            string_content,
                        )
                    )
                # Emit partial token so far
                token = Token(TokenType.STRING_LITERAL, string_content, loc)
                self._open_string_quote = None
                self._open_string_value = []
                self._open_string_location = None
                remainder_tokens.append(token)
                # Now tokenize rest of line normally since it's not part of the string
                if program_text:
                    remainder_tokens.extend(
                        self.tokenize_program_text(program_text, line_num, 8)
                    )
                return True, remainder_tokens
        # Not closed yet; whole line consumed
        return False, remainder_tokens

    def read_number_from_text(
        self, text: str, start_pos: int, line_num: int, start_col: int
    ) -> tuple[Token, int]:
        """Read numeric literal from text starting at position."""
        location = SourceLocation(line_num + 1, start_col + start_pos, 1)
        pos = start_pos
        has_decimal = False
        has_exponent = False
        # ``,`` under DECIMAL-POINT IS COMMA, ``.`` otherwise.
        decimal_char = self._decimal_char

        while pos < len(text):
            char = text[pos]
            if char.isdigit():
                pos += 1
            elif (
                char == decimal_char
                and not has_decimal
                and not has_exponent
                and pos + 1 < len(text)
                and text[pos + 1].isdigit()
            ):
                # A period is only a decimal point when followed by a digit:
                # a COBOL numeric literal cannot end with a decimal point, so
                # "16." at end of sentence is the literal 16 followed by the
                # sentence-terminating period separator.
                has_decimal = True
                pos += 1
            elif char in "Ee" and pos > start_pos and not has_exponent:
                # Scientific notation
                has_exponent = True
                pos += 1
                # Check for optional sign after E/e
                if pos < len(text) and text[pos] in "+-":
                    pos += 1
            else:
                break

        value = text[start_pos:pos]

        # Check if this should be a level number (01-99 without decimal or exponent)
        if (
            not has_decimal
            and not has_exponent
            and _LEVEL_NUMBER_1_2DIGIT_RE.match(value)
            and 1 <= int(value) <= 99
        ):
            # Only treat as level number if it's a valid COBOL level number
            return Token(TokenType.LEVEL_NUMBER, value, location), pos

        if has_decimal and decimal_char == ",":
            # DECIMAL-POINT IS COMMA: canonical ``.`` value, source in raw_value.
            return (
                Token(
                    TokenType.NUMERIC_LITERAL,
                    value.replace(",", "."),
                    location,
                    value,
                ),
                pos,
            )
        return Token(TokenType.NUMERIC_LITERAL, value, location), pos

    def check_division_header(
        self, text: str, start_pos: int
    ) -> tuple[TokenType | None, int]:
        """Check if text at position starts a division header and return appropriate token type."""
        if start_pos >= len(text) or text[start_pos] not in _DIVISION_FIRST:
            return None, start_pos
        remaining = text[start_pos : start_pos + 24].upper()

        # Check for complete division headers
        if remaining.startswith("IDENTIFICATION DIVISION"):
            return TokenType.IDENTIFICATION_DIVISION, start_pos + len("IDENTIFICATION")
        elif remaining.startswith("ID DIVISION"):
            return TokenType.IDENTIFICATION_DIVISION, start_pos + len("ID")
        elif remaining.startswith("ENVIRONMENT DIVISION"):
            return TokenType.ENVIRONMENT_DIVISION, start_pos + len("ENVIRONMENT")
        elif remaining.startswith("DATA DIVISION"):
            return TokenType.DATA_DIVISION, start_pos + len("DATA")
        elif remaining.startswith("PROCEDURE DIVISION"):
            return TokenType.PROCEDURE_DIVISION, start_pos + len("PROCEDURE")

        return None, start_pos

    def read_word_from_text(
        self, text: str, start_pos: int, line_num: int, start_col: int
    ) -> tuple[Token, int]:
        """Read word (identifier/keyword) from text starting at position."""
        location = SourceLocation(line_num + 1, start_col + start_pos, 1)
        pos = start_pos
        length = len(text)

        # Only check for division header when the first char could match
        if pos < length and text[pos] in _DIVISION_FIRST:
            division_type, division_end = self.check_division_header(text, start_pos)
            if division_type:
                division_word = text[start_pos:division_end].strip().split()[0]
                return Token(division_type, division_word, location), division_end

        # Read the token boundary, then slice once to avoid per-character allocations.
        while pos < length:
            char = text[pos]
            if char.isalnum() or char in "-_":
                pos += 1
            else:
                break

        value = text[start_pos:pos]
        upper_value = sys.intern(value.upper())
        if upper_value in self.KEYWORDS:
            token_type = self.KEYWORDS[upper_value]
        elif upper_value in self.FIGURATIVE_CONSTANTS:
            token_type = TokenType.FIGURATIVE_CONSTANT
        elif _LEVEL_NUM_RE.match(value):
            token_type = TokenType.LEVEL_NUMBER
        else:
            token_type = TokenType.IDENTIFIER

        return Token(token_type, value, location), pos

    def tokenize(self) -> list[Token]:
        """Tokenize the entire COBOL source code."""
        self.tokens = []
        self.errors = []
        self.warnings = []

        # Comment-entry lines (free-form only: the parser always lexes the
        # normalized free-form text).
        comment_entries = (
            _comment_entry_starts(self.source, self.lines) if self.free_form else {}
        )

        # Process line by line: fixed-format or free-form
        for line_num, line in enumerate(self.lines):
            if self.free_form:
                # In free-form, treat entire line (minus trailing newline) as program text starting column 1
                program_text = line.rstrip("\n")
                if comment_entries and line_num in comment_entries:
                    tokens = self._comment_entry_line_tokens(
                        program_text, line_num, 1, comment_entries[line_num]
                    )
                else:
                    tokens = self.tokenize_program_text(program_text, line_num, 1)
                self.tokens.extend(tokens)
                if tokens:
                    location = SourceLocation(line_num + 1, len(line) + 1, 1)
                    self.tokens.append(Token(TokenType.NEWLINE, "\n", location))
            else:
                line_tokens = self.handle_cobol_line_format(line, line_num)
                self.tokens.extend(line_tokens)
                if line_tokens and line_tokens[0].type != TokenType.COMMENT:
                    location = SourceLocation(line_num + 1, len(line) + 1, 1)
                    self.tokens.append(Token(TokenType.NEWLINE, "\n", location))

        # Add EOF token
        final_location = SourceLocation(len(self.lines) + 1, 1, 1)
        self.tokens.append(Token(TokenType.EOF, "", final_location))

        self._post_tokenize()
        return self.tokens

    def _post_tokenize(self) -> None:
        """Token-list post-passes shared by the pure-Python and Cython paths.

        Both ``tokenize()`` implementations call this once, after the EOF
        token is appended; it rewrites ``self.tokens`` in place (the Cython
        path returns the same list object).
        """
        self._merge_concatenated_literals()
        self._flag_stray_sql_chars()
        self._retype_operator_currency_symbols()

    #: Single-character operator tokens a SPECIAL-NAMES ``CURRENCY SIGN``
    #: clause can declare as a PICTURE symbol (``CURRENCY SIGN IS "<"``).
    _OPERATOR_CURRENCY_TYPES = frozenset(
        {TokenType.LESS, TokenType.GREATER, TokenType.ASSIGN}
    )

    def _retype_operator_currency_symbols(self) -> None:
        """Lex a declared operator-shaped currency symbol as CURRENCY
        inside a PICTURE character-string.

        ``CURRENCY SIGN IS "<"`` makes ``<`` a PICTURE editing symbol, but
        the character-level lexer emits it as the ``LESS`` operator (it is
        one everywhere else), so ``PIC <(3),<<<.99`` lost its picture and
        spawned bogus ANONYMOUS items (NIST NC108M). A picture string is the
        run of abutting tokens right after ``PIC``/``PICTURE`` [``IS``]; only
        operator tokens inside that run are retyped, so ``IF A < B`` keeps
        its operator.
        """
        symbols = self._currency_symbols & {"<", ">", "="}
        if not symbols:
            return
        tokens = self.tokens
        count = len(tokens)
        index = 0
        while index < count:
            token = tokens[index]
            index += 1
            if token.type not in (TokenType.PICTURE, TokenType.PIC):
                continue
            nxt = tokens[index] if index < count else None
            if nxt is not None and nxt.type == TokenType.IS:
                index += 1
            # The picture string: abutting tokens on one line.
            prev: Token | None = None
            while index < count:
                cur = tokens[index]
                if cur.type in (TokenType.NEWLINE, TokenType.EOF):
                    break
                if prev is not None and (
                    cur.location.line != prev.location.line
                    or cur.location.column
                    != prev.location.column + len(prev.raw_value or prev.value)
                ):
                    break
                if cur.type in self._OPERATOR_CURRENCY_TYPES and cur.value in symbols:
                    tokens[index] = Token(
                        TokenType.CURRENCY, cur.value, cur.location, cur.raw_value
                    )
                prev = cur
                index += 1

    #: Literal prefixes whose literals may be joined with ``&`` (IBM:
    #: alphanumeric, national and DBCS literals). ``Z`` (null-terminated) and
    #: ``B`` (boolean) literals may not be concatenated.
    _CONCATENABLE_PREFIXES = frozenset({"", "X", "N", "NX", "G", "U", "UX"})

    @staticmethod
    def _literal_prefix(token: Token) -> str:
        raw = token.raw_value
        if not raw:
            return ""
        for index, ch in enumerate(raw):
            if ch in "\"'":
                return raw[:index].upper()
        return raw.upper()

    def _ampersand_joins(self, prev: Token, token: Token) -> bool:
        """Whether the source between two literal tokens is ``&`` alone.

        ``&`` never becomes a token (the lexer skips it), so the source text
        is read back: scanning left from *token*'s first character, only
        whitespace, exactly one ``&``, more whitespace, then the closing
        quote of *prev* may appear. A fixed-format line is read in columns
        8-72 only, so a sequence number never reads as program text.
        """
        lines = self.lines
        lo = 0 if self.free_form else _FF_AREA_A
        prev_line = prev.location.line - 1
        prev_col = prev.location.column - 1
        line_idx = token.location.line - 1
        if line_idx >= len(lines):
            return False
        pos = token.location.column - 2
        seen_amp = False
        while True:
            line = lines[line_idx].rstrip("\n")
            pos = min(pos, len(line) - 1)
            while pos >= lo:
                ch = line[pos]
                if ch.isspace():
                    pos -= 1
                elif ch == "&" and not seen_amp:
                    seen_amp = True
                    pos -= 1
                else:
                    return (
                        seen_amp
                        and ch in "\"'"
                        and (line_idx, pos) > (prev_line, prev_col)
                    )
            line_idx -= 1
            if line_idx < prev_line:
                return False
            # An earlier line may end in a ``*>`` comment (or be one): only
            # the program text before it counts.
            pos = self._code_end(lines[line_idx], lo) - 1
            if not self.free_form:
                pos = min(pos, _FF_LINE_END - 1)

    def _code_end(self, line: str, lo: int) -> int:
        """Index where *line*'s program text ends: at a ``*>`` comment.

        The ``*>`` must sit outside a literal (``"A*>B"`` is text). A
        fixed-format comment line (``*`` or ``/`` in column 7) has no
        program text at all.
        """
        line = line.rstrip("\n")
        if not self.free_form and len(line) > _FF_INDICATOR:
            if line[_FF_INDICATOR] in "*/":
                return lo
        if "*>" not in line:
            return len(line)
        quote: str | None = None
        for index in range(lo, len(line)):
            ch = line[index]
            if quote is not None:
                if ch == quote:
                    quote = None  # a doubled quote reopens on the next char
            elif ch in "'\"":
                quote = ch
            elif line.startswith("*>", index):
                return index
        return len(line)

    def _merge_concatenated_literals(self) -> None:
        """Join ``lit-1 & lit-2 [& ...]`` into one STRING_LITERAL token.

        IBM Enterprise COBOL allows alphanumeric / national / DBCS literals
        of one kind to be concatenated with ``&``: ``"AB" & "CD"`` is the
        literal ``"ABCD"`` wherever a literal may appear (a VALUE clause, a
        MOVE source, ...). The lexer drops ``&`` as a separator, so before
        this every consumer saw two literals -- a data item kept only the
        first and warned, a MOVE source read ``"AB" "CD"``. Merging here
        means every consumer sees the one literal the compiler does.
        Literals of different kinds are left as they are.
        """
        tokens = self.tokens
        if not any("&" in line for line in self.lines):
            return
        merged: list[Token] = []
        last_index = -1  # index in *merged* of the last non-NEWLINE, non-COMMENT token
        for token in tokens:
            prev = merged[last_index] if last_index >= 0 else None
            if (
                token.type == TokenType.STRING_LITERAL
                and prev is not None
                and prev.type == TokenType.STRING_LITERAL
            ):
                prefix = self._literal_prefix(token)
                if (
                    prefix == self._literal_prefix(prev)
                    and prefix in self._CONCATENABLE_PREFIXES
                    and self._ampersand_joins(prev, token)
                ):
                    value = prev.value + token.value
                    raw_value: str | None = None
                    if prefix:
                        quote = prev.raw_value[len(prefix)]  # type: ignore[index]
                        raw_value = (
                            prefix + quote + value.replace(quote, quote * 2) + quote
                        )
                    merged[last_index] = Token(
                        TokenType.STRING_LITERAL, value, prev.location, raw_value
                    )
                    continue
            merged.append(token)
            # A line break or an inline ``*>`` comment may sit between the
            # two literals; neither ends the run.
            if token.type not in (TokenType.NEWLINE, TokenType.COMMENT):
                last_index = len(merged) - 1
        tokens[:] = merged

    def _flag_stray_sql_chars(self) -> None:
        """Record an "Invalid character" error for '!' / '|' / '¬' tokens
        outside any ``EXEC ... END-EXEC`` block.

        These characters lex to BANG/PIPE/NOT_SIGN tokens solely so embedded
        EXEC SQL text (``!=``, ``||``, ``¬=``) round-trips instead of
        failing the whole parse -- see SINGLE_CHAR_TOKENS. Outside an EXEC
        block they are exactly as invalid as before those tokens existed,
        and silently folding them into a statement's operand text would turn
        garbage input into a "successful" parse with no diagnostic at all.
        A single linear post-pass (shared verbatim by the Cython fast path,
        which inherits this method) restores the old error for that case.
        """
        in_exec = False
        for token in self.tokens:
            ttype = token.type
            if ttype == TokenType.EXEC:
                in_exec = True
            elif ttype == TokenType.END_EXEC:
                in_exec = False
            elif not in_exec and ttype in (
                TokenType.BANG,
                TokenType.PIPE,
                TokenType.NOT_SIGN,
            ):
                self.errors.append(
                    LexerError(f"Invalid character: {token.value}", token.location)
                )

    def get_tokens(self) -> list[Token]:
        """Get the list of tokens (tokenize if not already done)."""
        if not self.tokens:
            self.tokenize()
        return self.tokens

    def get_errors(self) -> list[LexerError]:
        """Get lexer errors encountered during tokenization."""
        return self.errors

    def has_errors(self) -> bool:
        """Check if there were any lexer errors."""
        return bool(self.errors)

    def get_warnings(self) -> list[str]:
        """Get lexer warnings encountered during tokenization."""
        return self.warnings

    def has_warnings(self) -> bool:
        """Check if there were any lexer warnings."""
        return bool(self.warnings)


def _fixed_format_comment_tokens(
    physical_lines: list[str], normalized: str, *, debug_lines_as_comments: bool = True
) -> list[Token]:
    """Recover COMMENT tokens for comment lines dropped by normalization.

    ``normalize_fixed_format`` emits an empty placeholder line for every
    comment line (indicator ``*``, ``/``, debug ``D``/``d``, or version-tag
    ``V``/``v``) and every blank/short line so later lines keep their line
    numbers, but the comment text itself is dropped before the free-form
    lexer runs. This helper re-scans the original physical lines, pairs each
    empty line in *normalized* with the physical comment/blank line that
    produced it (they correspond 1:1, in order), and builds COMMENT tokens
    whose line numbers use the same (normalized) coordinate system as the
    tokens lexed from *normalized* — so the two streams interleave
    consistently. With *debug_lines_as_comments* False -- the
    normalization compiled the ``D`` lines as code -- they are not comments.
    """
    # Deferred import: keeping preprocess out of module scope avoids import
    # cycles (same rationale as the tokenize helper below). The constant is
    # the shared home for the comment-indicator set — see _normalize.py.
    from ._source_directive import free_format_flags
    from .preprocess import ALL_COMMENT_INDICATORS
    from .preprocess._normalize import DEBUG_INDICATORS

    comment_indicators = (
        ALL_COMMENT_INDICATORS
        if debug_lines_as_comments
        else ALL_COMMENT_INDICATORS - DEBUG_INDICATORS
    )

    physical = [raw.rstrip("\n").expandtabs(8) for raw in physical_lines]
    # Lines after ``>>SOURCE FORMAT IS FREE`` have no indicator column: a
    # ``D``/``*``/``/`` that merely happens to sit in column 7 of a free line
    # (``    ADD A TO B``) is code, which the normalizer passed through whole.
    # Reading it as an indicator fabricated a COMMENT token beside the
    # line's real tokens.
    free = free_format_flags(physical) if any(">>" in ln for ln in physical) else None

    def _comment_text(line: str) -> str | None:
        if len(line) < _FF_AREA_A:
            return None
        indicator = line[_FF_INDICATOR]
        if indicator == "/":
            # Page eject — same token value the legacy fixed-format
            # lexer path emitted.
            return "/ PAGE BREAK"
        if indicator in comment_indicators:
            return line[_FF_INDICATOR:_FF_LINE_END].rstrip()
        return None

    comments: list[Token] = []
    if normalized.count("\n") == len(physical):
        # normalize_fixed_format emits exactly one output line per physical
        # line, in physical order: a logical line at its first record's
        # index, then one empty placeholder for every continuation, comment
        # or blank record merged into or deferred behind it. A comment
        # line's normalized number is therefore its own physical number.
        for idx, line in enumerate(physical):
            if free is not None and free[idx]:
                continue
            text = _comment_text(line)
            if text is not None:
                location = SourceLocation(idx + 1, _FF_INDICATOR + 1, 1)
                comments.append(Token(TokenType.COMMENT, text, location))
        return comments

    # Fallback should a normalizer ever not keep the line count: pair each
    # empty line in *normalized* with the physical line that produced it
    # (they correspond 1:1, in order). One entry per placeholder-producing
    # physical line: the COMMENT token value, or None for a line that
    # normalizes to an empty line without a token -- a blank/short line, a
    # continuation record (merged into its logical line, its placeholder
    # deferred behind it), or a full-width blank code line.
    placeholders: list[str | None] = []
    for idx, line in enumerate(physical):
        if free is not None and free[idx]:
            # The normalizer passes a free line through whole: only a blank
            # one comes out as an empty line.
            if not line.strip():
                placeholders.append(None)
            continue
        text = _comment_text(line)
        if text is not None:
            placeholders.append(text)
        elif (
            len(line) < _FF_AREA_A
            or line[_FF_INDICATOR] == "-"
            or not line[_FF_AREA_A:_FF_LINE_END].strip()
        ):
            placeholders.append(None)
        # Code lines with program text produce no placeholder.

    next_placeholder = 0
    for norm_idx, norm_line in enumerate(split_source_lines(normalized)):
        if norm_line:
            continue
        if next_placeholder >= len(placeholders):
            break
        text = placeholders[next_placeholder]
        next_placeholder += 1
        if text is not None:
            location = SourceLocation(norm_idx + 1, _FF_INDICATOR + 1, 1)
            comments.append(Token(TokenType.COMMENT, text, location))
    return comments


def _merge_comment_tokens(tokens: list[Token], comments: list[Token]) -> list[Token]:
    """Interleave COMMENT *comments* into *tokens* by source line order.

    Both lists are already sorted by line; comment lines never carry code
    tokens (they are empty in the normalized text), so a simple line-number
    merge is sufficient. Any trailing comments land just before EOF because
    the EOF token's line number is past the last source line.
    """
    if not comments:
        return tokens
    merged: list[Token] = []
    next_comment = 0
    for token in tokens:
        while (
            next_comment < len(comments)
            and comments[next_comment].location.line < token.location.line
        ):
            merged.append(comments[next_comment])
            next_comment += 1
        merged.append(token)
    merged.extend(comments[next_comment:])
    return merged


def _tokenize_source(
    source: str,
    filename: str = "<string>",
    dialect: DialectType = DialectType.IBM_ENTERPRISE,
    free_form: bool = False,
    keep_comments: bool = True,
    preprocess_fixed: bool | None = None,
    debug_lines: bool = False,
) -> tuple[list[Token], list[LexerError], list[str]]:
    """Tokenize *source* on the same pipeline ``parse_cobol`` uses (M6).

    When *free_form* is False and the source is auto-detected as
    fixed-format (same detection ``CobolParser.parse`` performs), it is
    normalized via ``normalize_fixed_format`` and lexed with
    ``free_form=True`` — so the token stream agrees with the parser's on
    every non-COMMENT token. Because normalization drops comment lines,
    *keep_comments* (default True) re-emits them as COMMENT tokens with
    line numbers in the normalized coordinate system, interleaved at their
    original positions. Free-form (or non-fixed-detected) input is lexed
    directly, unchanged.

    *preprocess_fixed* overrides that auto-detection when not None: True
    always normalizes -- even when *free_form* is True, matching
    ``parse_cobol``, which honors an explicit ``preprocess_fixed=True``
    regardless of ``free_form`` -- and False never does. Mirrors
    ``parse_cobol``'s parameter of the same name, so ``cobol-parser
    tokenize --source-format=fixed`` agrees with ``cobol-parser parse
    --source-format=fixed`` on source whose layout the detector cannot
    infer on its own.

    Returns:
        Tuple of (tokens, lexer errors, lexer warnings).
    """
    if not free_form or preprocess_fixed:
        # Deferred imports: parser.py imports this module at load time, and
        # keeping preprocess out of module scope avoids import cycles.
        from .preprocess.source_format import (
            detect_fixed_format,
            normalize_with_recovery,
        )

        should_normalize = (
            detect_fixed_format(source)
            if preprocess_fixed is None
            else preprocess_fixed
        )
        if should_normalize:
            physical_lines = split_source_lines(source)
            errors: list[LexerError] = []
            normalize_warnings: list[str] = []
            # An unterminated literal at EOF is recorded and the
            # never-raising normalization stands in, mirroring
            # CobolParser.parse under COLLECT_ALL.
            normalized, error = normalize_with_recovery(
                physical_lines,
                normalize_warnings,
                debug_lines_as_comments=not debug_lines,
            )
            assert normalized is not None  # recover=True always yields text
            if error is not None:
                errors.append(
                    LexerError(error, SourceLocation(max(len(physical_lines), 1), 1, 1))
                )
            lexer = CobolLexer(normalized, filename, dialect, free_form=True)
            tokens: list[Token] = lexer.tokenize()
            if keep_comments:
                tokens = _merge_comment_tokens(
                    tokens,
                    _fixed_format_comment_tokens(
                        physical_lines,
                        normalized,
                        debug_lines_as_comments=not debug_lines,
                    ),
                )
            errors.extend(lexer.get_errors())
            return tokens, errors, normalize_warnings + lexer.get_warnings()

    lexer = CobolLexer(source, filename, dialect, free_form=free_form)
    direct_tokens: list[Token] = lexer.tokenize()
    return direct_tokens, lexer.get_errors(), lexer.get_warnings()


def tokenize_cobol(
    source: str,
    filename: str = "<string>",
    dialect: DialectType = DialectType.IBM_ENTERPRISE,
    free_form: bool = False,
    keep_comments: bool = True,
) -> list[Token]:
    """Convenience function to tokenize COBOL source code.

    Fixed-format source is auto-detected and normalized through the same
    ``normalize_fixed_format`` + free-form lexing pipeline ``parse_cobol``
    uses, so both paths agree on all non-COMMENT tokens (M6). Comment lines
    are preserved as COMMENT tokens unless *keep_comments* is False.

    Args:
        source: COBOL source code
        filename: Source filename for error reporting
        dialect: COBOL dialect
        free_form: Treat source as free-form (skip fixed-format detection
            and normalization)
        keep_comments: Emit fixed-format comment lines as COMMENT tokens

    Returns:
        List of tokens

    Raises:
        LexerError: If there are lexing errors
    """
    tokens, errors, _warnings = _tokenize_source(
        source, filename, dialect, free_form=free_form, keep_comments=keep_comments
    )

    if errors:
        # Raise first error
        raise errors[0]

    return tokens


# ---------------------------------------------------------------------------
# Optional Cython fast path – opt-in drop-in for CobolLexer.
# The Cython subclass is defined in _lexer_fast.pyx and overrides the three
# innermost hot-path methods. The pure-Python class is the default; the
# compiled one is used only under COBOLPARSER_ACCEL=1 (see cobolparser._accel),
# and even then falls back silently if the extension was not compiled.
# ---------------------------------------------------------------------------
CobolLexer = _CobolLexerPure
if accelerators_enabled():
    try:
        from cobolparser._lexer_fast import (  # type: ignore[import-not-found,no-redef]
            CobolLexer,
        )
    except ImportError:
        pass
