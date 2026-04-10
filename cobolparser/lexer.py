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
from enum import Enum, auto

from .models.ast_base import SourceLocation
from .plugins.core import DialectType, ParseError

# Fixed-format COBOL column layout (0-based indices)
_FF_SEQ_END = 6  # columns 1-6: sequence number area (indices 0-5)
_FF_INDICATOR = 6  # column 7: indicator (* / - space) — index 6
_FF_AREA_A = 7  # column 8: Area A start — index 7
_FF_LINE_END = 72  # column 73+: identification area (ignored) — index 72

_LEVEL_NUM_RE = re.compile(r"^\d{2}$")


class TokenType(Enum):
    """Token types for COBOL lexical analysis."""

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

    # Level numbers
    LEVEL_NUMBER = auto()

    # Error tokens
    INVALID_TOKEN = auto()


@dataclass
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


class CobolLexer:
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
        "FILE-STATUS": TokenType.FILE_STATUS,
        "RESERVE": TokenType.RESERVE,
        "AREA": TokenType.AREA,
        "AREAS": TokenType.AREAS,
        "PADDING": TokenType.PADDING,
        "CHARACTER": TokenType.CHARACTER,
        "RECORD-DELIMITER": TokenType.RECORD_DELIMITER,
        "STANDARD-1": TokenType.STANDARD_1,
        "PASSWORD": TokenType.PASSWORD,
        "LOCK": TokenType.LOCK,
        "SHARING": TokenType.SHARING,
        "WITH": TokenType.WITH,
        "OTHER": TokenType.OTHER,
        "NO": TokenType.NO,
        "READ-ONLY": TokenType.READ_ONLY,
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
        "ENABLE": TokenType.ENABLE,
        "END-INVOKE": TokenType.END_INVOKE,
        "END-PERFORM": TokenType.END_PERFORM,
        "END-SET": TokenType.END_SET,
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
        "OTHERWISE": TokenType.OTHERWISE,
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
        "KEY IS": TokenType.KEY_IS,
        "END-OF-PAGE": TokenType.END_OF_PAGE,
        "EOP": TokenType.END_OF_PAGE,
        "WITH LOCK": TokenType.WITH_LOCK,
        "NO REWIND": TokenType.NO_REWIND,
        "REWIND": TokenType.NO_REWIND,
        "REEL": TokenType.REEL,
        "UNIT": TokenType.UNIT,
        "ADVANCING": TokenType.ADVANCING,
        "NO ADVANCING": TokenType.NO_ADVANCING,
        "END-OF-FILE": TokenType.END_OF_FILE,
        "EOF": TokenType.END_OF_FILE,
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
    }

    # COBOL Fixed-Format Column Constants
    SEQUENCE_AREA_START = 0
    SEQUENCE_AREA_END = 6
    INDICATOR_COLUMN = 6  # 0-indexed (column 7 in 1-indexed COBOL)
    PROGRAM_TEXT_START = 7  # 0-indexed (column 8 in 1-indexed COBOL)
    PROGRAM_TEXT_END = 72
    IDENTIFICATION_START = 72
    IDENTIFICATION_END = 80

    # Indicator characters
    CONTINUATION_INDICATOR = "-"
    COMMENT_INDICATORS = ("*", "/")
    DEBUG_INDICATOR = "D"

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
        self.lines = source.splitlines()
        self.current_line = 0
        self.current_column = 0
        self.current_pos = 0
        self.tokens: list[Token] = []
        self.errors: list[LexerError] = []
        self.free_form = free_form
        # Multi-line string continuation state
        self._open_string_quote: str | None = None
        self._open_string_value: list[str] = []
        self._open_string_location: SourceLocation | None = None

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
        value = ""
        self.advance_char()  # Skip opening quote

        while True:
            char = self.peek_char()
            if char is None:
                # Unterminated string - add error
                self.errors.append(
                    LexerError(
                        "Unterminated string literal",
                        start_location,
                        quote_char + value,
                    )
                )
                break

            if char == quote_char:
                self.advance_char()  # Skip closing quote
                # Check for doubled quote (escape sequence)
                if self.peek_char() == quote_char:
                    value += quote_char
                    self.advance_char()
                else:
                    break
            else:
                value += char
                self.advance_char()

        return Token(TokenType.STRING_LITERAL, value, start_location)

    def read_numeric_literal(self) -> Token:
        """Read a numeric literal (integer or decimal)."""
        start_location = self.get_current_location()
        value = ""
        has_decimal = False
        has_exponent = False

        while True:
            char = self.peek_char()
            if char is None:
                break

            if char.isdigit():
                value += char
                self.advance_char()
            elif char == "." and not has_decimal and not has_exponent:
                has_decimal = True
                value += char
                self.advance_char()
            elif char in "Ee" and value and not has_exponent:
                # Scientific notation
                has_exponent = True
                value += char
                self.advance_char()
                next_char = self.peek_char()
                if next_char and next_char in "+-":
                    value += next_char
                    self.advance_char()
            else:
                break

        return Token(TokenType.NUMERIC_LITERAL, value, start_location)

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

        while pos < len(text):
            char = text[pos]

            # Skip whitespace (no location needed)
            if char in " \t":
                pos += 1
                continue

            location = SourceLocation(line_num + 1, start_col + pos, 1)

            # String literals
            if char in "\"'":
                # Check if this line starts with a quote - could be continuation from previous VALUE
                is_line_start_quote = pos == 0 or text[:pos].strip() == ""

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
                # Look ahead to see if this could be an identifier starting with digits
                lookahead_pos = pos
                lookahead_value = ""
                while lookahead_pos < len(text) and (text[lookahead_pos].isdigit()):
                    lookahead_value += text[lookahead_pos]
                    lookahead_pos += 1

                # Check if after digits we have a dash followed by letters (identifier pattern)
                if (
                    lookahead_pos < len(text)
                    and text[lookahead_pos] == "-"
                    and lookahead_pos + 1 < len(text)
                    and text[lookahead_pos + 1].isalpha()
                ):
                    # This looks like an identifier starting with digits (e.g., 42-DATANAMES)
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

            # Identifiers and keywords
            if char.isalpha() or char == "_":
                token, new_pos = self.read_word_from_text(
                    text, pos, line_num, start_col
                )
                tokens.append(token)
                pos = new_pos
                continue

            # Single character tokens (class-level dict for performance)
            if char in self.SINGLE_CHAR_TOKENS:
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

            # Unknown character – record an error and advance
            self.errors.append(LexerError(f"Invalid character: {char}", location, char))
            pos += 1

        return tokens

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
        value = ""
        pos = start_pos + 1
        while pos < len(text):
            ch = text[pos]
            if ch == quote:
                # doubled quote escape
                if pos + 1 < len(text) and text[pos + 1] == quote:
                    value += quote
                    pos += 2
                    continue
                pos += 1
                return Token(TokenType.STRING_LITERAL, value, location), pos, False
            else:
                value += ch
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
        value = ""
        pos = start_pos
        has_decimal = False
        has_exponent = False

        while pos < len(text):
            char = text[pos]
            if char.isdigit():
                value += char
                pos += 1
            elif char == "." and not has_decimal and not has_exponent:
                has_decimal = True
                value += char
                pos += 1
            elif char in "Ee" and value and not has_exponent:
                # Scientific notation
                has_exponent = True
                value += char
                pos += 1
                # Check for optional sign after E/e
                if pos < len(text) and text[pos] in "+-":
                    value += text[pos]
                    pos += 1
            else:
                break

        # Check if this should be a level number (01-99 without decimal or exponent)
        if (
            not has_decimal
            and not has_exponent
            and _LEVEL_NUMBER_1_2DIGIT_RE.match(value)
            and 1 <= int(value) <= 99
        ):
            # Only treat as level number if it's a valid COBOL level number
            return Token(TokenType.LEVEL_NUMBER, value, location), pos

        return Token(TokenType.NUMERIC_LITERAL, value, location), pos

    def check_division_header(
        self, text: str, start_pos: int
    ) -> tuple[TokenType | None, int]:
        """Check if text at position starts a division header and return appropriate token type."""
        remaining = text[start_pos:].strip().upper()

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
        value = ""
        pos = start_pos

        # First check if this might be a division header
        division_type, division_end = self.check_division_header(text, start_pos)
        if division_type:
            # Preserve the division token type but keep the value to the keyword only.
            division_word = text[start_pos:division_end].strip().split()[0]
            return Token(division_type, division_word, location), division_end

        # Read regular word
        while pos < len(text):
            char = text[pos]
            if char.isalnum() or char in "-_":
                value += char
                pos += 1
            else:
                break

        # Determine token type
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

        # Process line by line: fixed-format or free-form
        for line_num, line in enumerate(self.lines):
            if self.free_form:
                # In free-form, treat entire line (minus trailing newline) as program text starting column 1
                program_text = line.rstrip("\n")
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

        return self.tokens

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


def tokenize_cobol(
    source: str,
    filename: str = "<string>",
    dialect: DialectType = DialectType.IBM_ENTERPRISE,
) -> list[Token]:
    """Convenience function to tokenize COBOL source code.

    Args:
        source: COBOL source code
        filename: Source filename for error reporting
        dialect: COBOL dialect

    Returns:
        List of tokens

    Raises:
        LexerError: If there are lexing errors
    """
    lexer = CobolLexer(source, filename, dialect)
    tokens = lexer.tokenize()

    if lexer.has_errors():
        # Raise first error
        raise lexer.get_errors()[0]

    return tokens
