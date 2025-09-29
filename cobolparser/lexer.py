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
from enum import Enum, auto
from typing import List, Optional, Iterator, NamedTuple
from dataclasses import dataclass

from .models.ast_base import SourceLocation
from .plugins.core import ParseError, DialectType


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
    
    # Keywords - Data Definition
    PIC = auto()
    PICTURE = auto()
    USAGE = auto()
    VALUE = auto()
    OCCURS = auto()
    REDEFINES = auto()
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
    
    # Keywords - I/O
    SELECT = auto()
    READ = auto()
    WRITE = auto()
    OPEN = auto()
    CLOSE = auto()
    ACCEPT = auto()
    DISPLAY_STMT = auto()  # Different from USAGE DISPLAY
    
    # Keywords - Control Flow
    TIMES = auto()
    UNTIL = auto()
    VARYING = auto()
    FROM = auto()
    BY = auto()
    AFTER = auto()
    BEFORE = auto()
    
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
    raw_value: Optional[str] = None  # Original source text if different from value
    
    def __str__(self) -> str:
        return f"{self.type.name}({self.value})"
    
    def __repr__(self) -> str:
        return f"Token({self.type.name}, '{self.value}', {self.location})"


class LexerError(ParseError):
    """Error during lexical analysis."""
    
    def __init__(self, message: str, location: SourceLocation, token_value: str = ""):
        super().__init__(message, location.line, location.column)
        self.location = location
        self.token_value = token_value


class CobolLexer:
    """COBOL lexical analyzer with support for multiple dialects.
    
    This lexer handles the complexities of COBOL tokenization including:
    - Fixed-format source lines (columns 7-72)
    - Continuation lines and literals
    - Case-insensitive keywords
    - IBM Enterprise COBOL extensions
    - Embedded SQL and CICS statements
    """
    
    # COBOL keywords mapping
    KEYWORDS = {
        # Divisions
        'IDENTIFICATION': TokenType.IDENTIFICATION_DIVISION,
        'ID': TokenType.IDENTIFICATION_DIVISION,
        'ENVIRONMENT': TokenType.ENVIRONMENT_DIVISION,
        'DATA': TokenType.DATA_DIVISION,
        'PROCEDURE': TokenType.PROCEDURE_DIVISION,
        
        # Sections and entries
        'PROGRAM-ID': TokenType.PROGRAM_ID,
        'AUTHOR': TokenType.AUTHOR,
        'DATE-WRITTEN': TokenType.DATE_WRITTEN,
        'CONFIGURATION': TokenType.CONFIGURATION_SECTION,
        'INPUT-OUTPUT': TokenType.INPUT_OUTPUT_SECTION,
        'FILE': TokenType.FILE_SECTION,
        'WORKING-STORAGE': TokenType.WORKING_STORAGE_SECTION,
        'LOCAL-STORAGE': TokenType.LOCAL_STORAGE_SECTION,
        'LINKAGE': TokenType.LINKAGE_SECTION,
        
        # File Description
        'FD': TokenType.FD,
        
        # Data definition
        'PIC': TokenType.PIC,
        'PICTURE': TokenType.PICTURE,
        'USAGE': TokenType.USAGE,
        'VALUE': TokenType.VALUE,
        'OCCURS': TokenType.OCCURS,
        'REDEFINES': TokenType.REDEFINES,
        'SYNC': TokenType.SYNC,
        'SYNCHRONIZED': TokenType.SYNCHRONIZED,
        'COMP': TokenType.COMP,
        'COMP-1': TokenType.COMP_1,
        'COMP-2': TokenType.COMP_2,
        'COMP-3': TokenType.COMP_3,
        'COMP-4': TokenType.COMP_4,
        'COMP-5': TokenType.COMP_5,
        'COMPUTATIONAL': TokenType.COMPUTATIONAL,
        'DISPLAY': TokenType.DISPLAY,
        
        # Statements
        'MOVE': TokenType.MOVE,
        'ADD': TokenType.ADD,
        'SUBTRACT': TokenType.SUBTRACT,
        'MULTIPLY': TokenType.MULTIPLY,
        'DIVIDE': TokenType.DIVIDE,
        'COMPUTE': TokenType.COMPUTE,
        'PERFORM': TokenType.PERFORM,
        'IF': TokenType.IF,
        'ELSE': TokenType.ELSE,
        'END-IF': TokenType.END_IF,
        'EVALUATE': TokenType.EVALUATE,
        'WHEN': TokenType.WHEN,
        'END-EVALUATE': TokenType.END_EVALUATE,
        'CALL': TokenType.CALL,
        'RETURN': TokenType.RETURN,
        'GO': TokenType.GO,
        'GOTO': TokenType.GOTO,
        'STOP': TokenType.STOP,
        'EXIT': TokenType.EXIT,
        'CONTINUE': TokenType.CONTINUE,
        
        # Additional COBOL Verbs
        'ALTER': TokenType.ALTER,
        'CANCEL': TokenType.CANCEL,
        'CHAIN': TokenType.CHAIN,
        'COMMIT': TokenType.COMMIT,
        'DELETE': TokenType.DELETE,
        'DISABLE': TokenType.DISABLE,
        'DISPLAY-1': TokenType.DISPLAY_1,
        'ENABLE': TokenType.ENABLE,
        'END-INVOKE': TokenType.END_INVOKE,
        'END-PERFORM': TokenType.END_PERFORM,
        'END-SET': TokenType.END_SET,
        'ENTER': TokenType.ENTER,
        'ENTRY': TokenType.ENTRY,
        'EXAMINE': TokenType.EXAMINE,
        'EXECUTE': TokenType.EXECUTE,
        'EXHIBIT': TokenType.EXHIBIT,
        'GENERATE': TokenType.GENERATE,
        'GOBACK': TokenType.GOBACK,
        'INITIALIZE': TokenType.INITIALIZE,
        'INITIATE': TokenType.INITIATE,
        'INSPECT': TokenType.INSPECT,
        'INVOKE': TokenType.INVOKE,
        'MERGE': TokenType.MERGE,
        'NEXT': TokenType.NEXT,
        'NOTE': TokenType.NOTE,
        'ON': TokenType.ON,
        'OTHERWISE': TokenType.OTHERWISE,
        'READY': TokenType.READY,
        'RECEIVE': TokenType.RECEIVE,
        'RECOVER': TokenType.RECOVER,
        'RELEASE': TokenType.RELEASE,
        'RESET': TokenType.RESET,
        'REWRITE': TokenType.REWRITE,
        'ROLLBACK': TokenType.ROLLBACK,
        'SEARCH': TokenType.SEARCH,
        'SEND': TokenType.SEND,
        'SERVICE': TokenType.SERVICE,
        'SET': TokenType.SET,
        'SORT': TokenType.SORT,
        'START': TokenType.START,
        'STRING': TokenType.STRING,
        'SUPPRESS': TokenType.SUPPRESS,
        'TERMINATE': TokenType.TERMINATE,
        'TRANSFORM': TokenType.TRANSFORM,
        'UNLOCK': TokenType.UNLOCK,
        'UNSTRING': TokenType.UNSTRING,
        
        # I/O
        'SELECT': TokenType.SELECT,
        'READ': TokenType.READ,
        'WRITE': TokenType.WRITE,
        'OPEN': TokenType.OPEN,
        'CLOSE': TokenType.CLOSE,
        'ACCEPT': TokenType.ACCEPT,
        
        # Control flow
        'TIMES': TokenType.TIMES,
        'UNTIL': TokenType.UNTIL,
        'VARYING': TokenType.VARYING,
        'FROM': TokenType.FROM,
        'BY': TokenType.BY,
        'AFTER': TokenType.AFTER,
        'BEFORE': TokenType.BEFORE,
        
        # Conditions
        'EQUAL': TokenType.EQUAL,
        'NOT': TokenType.NOT,
        'AND': TokenType.AND,
        'OR': TokenType.OR,
        'GREATER': TokenType.GREATER,
        'LESS': TokenType.LESS,
        'THAN': TokenType.THAN,
        
        # IBM Extensions
        'EXEC': TokenType.EXEC,
        'SQL': TokenType.SQL,
        'CICS': TokenType.CICS,
        'END-EXEC': TokenType.END_EXEC,
        'INCLUDE': TokenType.INCLUDE,
        'COPY': TokenType.COPY,
        'REPLACING': TokenType.REPLACING,
    }
    
    # Figurative constants
    FIGURATIVE_CONSTANTS = {
        'ZERO', 'ZEROS', 'ZEROES',
        'SPACE', 'SPACES',
        'HIGH-VALUE', 'HIGH-VALUES',
        'LOW-VALUE', 'LOW-VALUES',
        'QUOTE', 'QUOTES',
        'ALL'
    }
    
    def __init__(self, source: str, filename: str = "<string>", dialect: DialectType = DialectType.IBM_ENTERPRISE):
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
        self.tokens: List[Token] = []
        self.errors: List[LexerError] = []
        
    def get_current_location(self) -> SourceLocation:
        """Get current source location."""
        return SourceLocation(self.current_line + 1, self.current_column + 1, 1)
    
    def peek_char(self, offset: int = 0) -> Optional[str]:
        """Peek at character at current position + offset."""
        pos = self.current_pos + offset
        if pos >= len(self.source):
            return None
        return self.source[pos]
    
    def advance_char(self) -> Optional[str]:
        """Advance to next character and return it."""
        if self.current_pos >= len(self.source):
            return None
        
        char = self.source[self.current_pos]
        self.current_pos += 1
        
        if char == '\n':
            self.current_line += 1
            self.current_column = 0
        else:
            self.current_column += 1
        
        return char
    
    def skip_whitespace(self) -> None:
        """Skip whitespace characters except newlines."""
        while self.peek_char() and self.peek_char() in ' \t\r':
            self.advance_char()
    
    def read_string_literal(self, quote_char: str) -> Token:
        """Read a string literal enclosed in quotes or apostrophes."""
        start_location = self.get_current_location()
        value = ""
        self.advance_char()  # Skip opening quote
        
        while True:
            char = self.peek_char()
            if char is None:
                self.errors.append(LexerError(
                    "Unterminated string literal",
                    start_location,
                    quote_char + value
                ))
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
            elif char == '.' and not has_decimal and not has_exponent:
                has_decimal = True
                value += char
                self.advance_char()
            elif char in 'Ee' and value and not has_exponent:
                # Scientific notation
                has_exponent = True
                value += char
                self.advance_char()
                if self.peek_char() in '+-':
                    value += self.peek_char()
                    self.advance_char()
            else:
                break
        
        return Token(TokenType.NUMERIC_LITERAL, value, start_location)
    
    def read_identifier(self) -> Token:
        """Read an identifier or keyword."""
        start_location = self.get_current_location()
        value = ""
        
        while True:
            char = self.peek_char()
            if char is None:
                break
            
            if char.isalnum() or char in '-_':
                value += char
                self.advance_char()
            else:
                break
        
        # Check if it's a keyword
        upper_value = value.upper()
        if upper_value in self.KEYWORDS:
            token_type = self.KEYWORDS[upper_value]
        elif upper_value in self.FIGURATIVE_CONSTANTS:
            token_type = TokenType.FIGURATIVE_CONSTANT
        elif re.match(r'^\d{2}$', value):  # Level numbers 01-99
            token_type = TokenType.LEVEL_NUMBER
        else:
            token_type = TokenType.IDENTIFIER
        
        return Token(token_type, value, start_location)
    
    def read_comment(self) -> Token:
        """Read a comment (line starting with * in column 7 or inline)."""
        start_location = self.get_current_location()
        value = ""
        
        # Read until end of line
        while self.peek_char() and self.peek_char() != '\n':
            value += self.peek_char()
            self.advance_char()
        
        return Token(TokenType.COMMENT, value, start_location)
    
    def handle_cobol_line_format(self, line: str, line_num: int) -> List[Token]:
        """Handle COBOL fixed-format line structure.
        
        COBOL lines have specific column meanings:
        - Columns 1-6: Sequence number
        - Column 7: Indicator (*, /, D, -, space)
        - Columns 8-72: Program text
        - Columns 73-80: Identification (ignored)
        """
        line_tokens = []
        
        if len(line) < 7:
            return line_tokens
        
        # Check column 7 indicator
        indicator = line[6] if len(line) > 6 else ' '
        
        if indicator == '*':
            # Comment line
            comment_text = line[6:72].rstrip() if len(line) > 6 else ""
            location = SourceLocation(line_num + 1, 7, 1)
            line_tokens.append(Token(TokenType.COMMENT, comment_text, location))
            return line_tokens
        
        if indicator == '/':
            # Page break - treat as comment
            location = SourceLocation(line_num + 1, 7, 1)
            line_tokens.append(Token(TokenType.COMMENT, "/ PAGE BREAK", location))
            return line_tokens
        
        if indicator == '-':
            # Continuation line
            location = SourceLocation(line_num + 1, 7, 1)
            line_tokens.append(Token(TokenType.CONTINUATION, "-", location))
        
        # Extract program text (columns 8-72)
        program_text = line[7:72] if len(line) > 7 else ""
        
        # Tokenize the program text and add to existing line_tokens
        program_tokens = self.tokenize_program_text(program_text, line_num, 8)
        line_tokens.extend(program_tokens)
        
        return line_tokens
    
    def tokenize_program_text(self, text: str, line_num: int, start_col: int) -> List[Token]:
        """Tokenize COBOL program text from a line."""
        tokens = []
        pos = 0
        
        while pos < len(text):
            char = text[pos]
            location = SourceLocation(line_num + 1, start_col + pos, 1)
            
            # Skip whitespace
            if char in ' \t':
                pos += 1
                continue
            
            # String literals
            if char in '"\'':
                token, new_pos = self.read_string_from_text(text, pos, line_num, start_col)
                tokens.append(token)
                pos = new_pos
                continue
            
            # Numeric literals
            if char.isdigit():
                token, new_pos = self.read_number_from_text(text, pos, line_num, start_col)
                tokens.append(token)
                pos = new_pos
                continue
            
            # Identifiers and keywords
            if char.isalpha() or char == '_':
                token, new_pos = self.read_word_from_text(text, pos, line_num, start_col)
                tokens.append(token)
                pos = new_pos
                continue
            
            # Single character tokens
            single_char_tokens = {
                '.': TokenType.PERIOD,
                ',': TokenType.COMMA,
                ';': TokenType.SEMICOLON,
                ':': TokenType.COLON,
                '(': TokenType.LEFT_PAREN,
                ')': TokenType.RIGHT_PAREN,
                '+': TokenType.PLUS,
                '-': TokenType.MINUS,
                '*': TokenType.MULTIPLY_OP,
                '/': TokenType.DIVIDE_OP,
                '=': TokenType.ASSIGN,
            }
            
            if char in single_char_tokens:
                tokens.append(Token(single_char_tokens[char], char, location))
                pos += 1
                continue
            
            # Unknown character
            self.errors.append(LexerError(f"Invalid character: {char}", location, char))
            pos += 1
        
        return tokens
    
    def read_string_from_text(self, text: str, start_pos: int, line_num: int, start_col: int) -> tuple[Token, int]:
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
            self.errors.append(LexerError(
                "Unterminated string literal",
                location,
                quote_char + value
            ))
        
        return Token(TokenType.STRING_LITERAL, value, location), pos
    
    def read_number_from_text(self, text: str, start_pos: int, line_num: int, start_col: int) -> tuple[Token, int]:
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
            elif char == '.' and not has_decimal and not has_exponent:
                has_decimal = True
                value += char
                pos += 1
            elif char in 'Ee' and value and not has_exponent:
                # Scientific notation
                has_exponent = True
                value += char
                pos += 1
                # Check for optional sign after E/e
                if pos < len(text) and text[pos] in '+-':
                    value += text[pos]
                    pos += 1
            else:
                break
        
        # Check if this should be a level number (01-99 without decimal or exponent)
        if (not has_decimal and not has_exponent and re.match(r'^\d{1,2}$', value) and 
            1 <= int(value) <= 99):
            # Only treat as level number if it's a valid COBOL level number
            return Token(TokenType.LEVEL_NUMBER, value, location), pos
        
        return Token(TokenType.NUMERIC_LITERAL, value, location), pos
    
    def read_word_from_text(self, text: str, start_pos: int, line_num: int, start_col: int) -> tuple[Token, int]:
        """Read word (identifier/keyword) from text starting at position."""
        location = SourceLocation(line_num + 1, start_col + start_pos, 1)
        value = ""
        pos = start_pos
        
        while pos < len(text):
            char = text[pos]
            if char.isalnum() or char in '-_':
                value += char
                pos += 1
            else:
                break
        
        # Determine token type
        upper_value = value.upper()
        if upper_value in self.KEYWORDS:
            token_type = self.KEYWORDS[upper_value]
        elif upper_value in self.FIGURATIVE_CONSTANTS:
            token_type = TokenType.FIGURATIVE_CONSTANT
        elif re.match(r'^\d{2}$', value):
            token_type = TokenType.LEVEL_NUMBER
        else:
            token_type = TokenType.IDENTIFIER
        
        return Token(token_type, value, location), pos
    
    def tokenize(self) -> List[Token]:
        """Tokenize the entire COBOL source code."""
        self.tokens = []
        self.errors = []
        
        # Process line by line for COBOL format
        for line_num, line in enumerate(self.lines):
            line_tokens = self.handle_cobol_line_format(line, line_num)
            self.tokens.extend(line_tokens)
            
            # Add newline token if not a comment-only line
            if line_tokens and line_tokens[0].type != TokenType.COMMENT:
                location = SourceLocation(line_num + 1, len(line) + 1, 1)
                self.tokens.append(Token(TokenType.NEWLINE, "\\n", location))
        
        # Add EOF token
        final_location = SourceLocation(len(self.lines) + 1, 1, 1)
        self.tokens.append(Token(TokenType.EOF, "", final_location))
        
        return self.tokens
    
    def get_tokens(self) -> List[Token]:
        """Get the list of tokens (tokenize if not already done)."""
        if not self.tokens:
            self.tokenize()
        return self.tokens
    
    def get_errors(self) -> List[LexerError]:
        """Get lexer errors encountered during tokenization."""
        return self.errors
    
    def has_errors(self) -> bool:
        """Check if there were any lexer errors."""
        return bool(self.errors)


def tokenize_cobol(source: str, filename: str = "<string>", dialect: DialectType = DialectType.IBM_ENTERPRISE) -> List[Token]:
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