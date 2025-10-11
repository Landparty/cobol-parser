"""COBOL parser implementation for parsing COBOL source code into AST.

This module provides the core parsing functionality that converts tokenized COBOL
source code into Abstract Syntax Trees (AST) representing the program structure.
"""

from typing import List, Optional, Dict, Any, Union, Iterator
from dataclasses import dataclass
from enum import Enum, auto

from .lexer import CobolLexer, Token, TokenType, LexerError
from .models.ast_base import SourceLocation, ASTNode
from .models.program import CobolProgram, CobolDivision, CobolSection, CobolParagraph, CobolFileDescription
from .models.statements import (
    CobolStatement, CobolExpression, MoveStatement, DisplayStatement, 
    PerformStatement, CallStatement, SelectStatement, ArithmeticExpression, ConditionalExpression
)
from .models.data_items import CobolDataItem, PictureClause, OccursClause
from .plugins.core import (
    ParseError, ParseStatistics, ErrorRecoveryMode, DialectType,
    MemoryConfiguration, SerializationConfig, PluginManager
)


class ParseState(Enum):
    """Parser state tracking for COBOL divisions and sections."""
    
    INITIAL = auto()
    IDENTIFICATION_DIVISION = auto()
    ENVIRONMENT_DIVISION = auto()
    DATA_DIVISION = auto()
    PROCEDURE_DIVISION = auto()
    
    PROGRAM_ID_SECTION = auto()
    CONFIGURATION_SECTION = auto()
    INPUT_OUTPUT_SECTION = auto()
    FILE_SECTION = auto()
    WORKING_STORAGE_SECTION = auto()
    LOCAL_STORAGE_SECTION = auto()
    LINKAGE_SECTION = auto()
    
    STATEMENT_PARSING = auto()
    EXPRESSION_PARSING = auto()
    DATA_ITEM_PARSING = auto()


@dataclass
class ParseResult:
    """Result of parsing operation with AST and metadata."""
    
    ast: Optional[CobolProgram]
    errors: List[ParseError]
    warnings: List[str]
    statistics: ParseStatistics
    
    @property
    def success(self) -> bool:
        """Check if parsing was successful."""
        return self.ast is not None and not self.errors
    
    @property
    def has_warnings(self) -> bool:
        """Check if there are any warnings."""
        return bool(self.warnings)

    def __repr__(self) -> str:  # pragma: no cover - formatting helper
        prog = self.ast.program_name if (self.ast and hasattr(self.ast, 'program_name')) else 'None'
        divs = len(self.ast.divisions) if (self.ast and hasattr(self.ast, 'divisions')) else 0
        return (
            f"ParseResult(success={self.success}, program='{prog}', divisions={divs}, "
            f"errors={len(self.errors)}, warnings={len(self.warnings)})"
        )


class CobolParser:
    """COBOL parser with support for multiple dialects and error recovery.
    
    This parser converts tokenized COBOL source code into Abstract Syntax Trees
    with advanced features:
    - Memory management with configurable limits
    - Error recovery modes (fail-fast vs collect-all)  
    - Support for IBM Enterprise COBOL extensions
    - JSON serialization with metadata
    - Plugin architecture for extensibility
    """
    
    def __init__(
        self,
        dialect: DialectType = DialectType.IBM_ENTERPRISE,
        error_recovery: ErrorRecoveryMode = ErrorRecoveryMode.FAIL_FAST,
        memory_config: Optional[MemoryConfiguration] = None,
        serialization_config: Optional[SerializationConfig] = None,
        plugin_manager: Optional[PluginManager] = None,
        free_form: bool = False,
    ):
        """Initialize the COBOL parser.
        
        Args:
            dialect: COBOL dialect to use for parsing
            error_recovery: Error recovery strategy
            memory_config: Memory management configuration
            serialization_config: JSON serialization configuration
            plugin_manager: Plugin manager for extensions
        """
        self.dialect = dialect
        self.error_recovery = error_recovery
        self.memory_config = memory_config or MemoryConfiguration()
        self.serialization_config = serialization_config or SerializationConfig()
        self.plugin_manager = plugin_manager or PluginManager()
        self.free_form = free_form
        
        # Parser state
        self.tokens: List[Token] = []
        self.current_token_index = 0
        self.current_token: Optional[Token] = None
        self.parse_state = ParseState.INITIAL
        self.errors: List[ParseError] = []
        self.warnings: List[str] = []
        
        # Statistics tracking
        self.statistics = ParseStatistics()
        
        # Current parsing context
        self.current_program: Optional[CobolProgram] = None
        self.current_division: Optional[CobolDivision] = None
        self.current_section: Optional[CobolSection] = None
        
    def parse(self, source: str, filename: str = "<string>") -> ParseResult:
        """Parse COBOL source code into AST.
        
        Args:
            source: COBOL source code
            filename: Source filename for error reporting
            
        Returns:
            ParseResult with AST and metadata
        """
        self.statistics.reset()
        self.statistics.start_timing()
        
        try:
            # Tokenize source
            lexer = CobolLexer(source, filename, self.dialect, free_form=self.free_form)
            self.tokens = lexer.tokenize()
            
            if lexer.has_errors():
                for error in lexer.get_errors():
                    self.add_error(self.create_error(f"Lexer error: {error.message}", error.location))
                
                if self.error_recovery == ErrorRecoveryMode.FAIL_FAST:
                    return self._create_result(None)
            
            # Initialize parser state
            self.current_token_index = 0
            self.current_token = self.tokens[0] if self.tokens else None
            self.parse_state = ParseState.INITIAL
            
            # Parse program structure
            program = self.parse_program()
            
            self.statistics.end_timing()
            self.statistics.lines_parsed = len(source.splitlines())
            self.statistics.tokens_processed = len(self.tokens)
            
            return self._create_result(program)
            
        except Exception as e:
            self.add_error(self.create_error(f"Parser error: {str(e)}"))
            return self._create_result(None)
    
    def parse_file(self, filepath: str) -> ParseResult:
        """Parse COBOL source code from a file.
        
        Args:
            filepath: Path to COBOL source file
            
        Returns:
            ParseResult with AST and metadata
        """
        try:
            with open(filepath, 'r', encoding='utf-8') as file:
                source = file.read()
            return self.parse(source, filepath)
        except IOError as e:
            self.add_error(self.create_error(f"File error: {str(e)}"))
            return self._create_result(None)
    
    def _create_result(self, ast: Optional[CobolProgram]) -> ParseResult:
        """Create parse result with current state."""
        return ParseResult(
            ast=ast,
            errors=self.errors.copy(),
            warnings=self.warnings.copy(),
            statistics=self.statistics
        )
    
    def get_current_location(self) -> SourceLocation:
        """Get current source location."""
        if self.current_token:
            return self.current_token.location
        return SourceLocation("<unknown>", 1, 1)
    
    def add_error(self, error: ParseError) -> None:
        """Add a parse error."""
        self.errors.append(error)
        self.statistics.error_count += 1
    
    def create_error(self, message: str, location: Optional[SourceLocation] = None) -> ParseError:
        """Create a parse error with proper location handling."""
        if location is None:
            location = self.get_current_location()
        return ParseError(message, location.line, location.column)
    
    def add_warning(self, message: str) -> None:
        """Add a warning message."""
        self.warnings.append(message)
        self.statistics.warning_count += 1
    
    def advance_token(self) -> bool:
        """Advance to next token."""
        self.current_token_index += 1
        if self.current_token_index < len(self.tokens):
            self.current_token = self.tokens[self.current_token_index]
            return True
        else:
            self.current_token = None
            return False
    
    def peek_token(self, offset: int = 1) -> Optional[Token]:
        """Peek at token at current position + offset."""
        index = self.current_token_index + offset
        if 0 <= index < len(self.tokens):
            return self.tokens[index]
        return None
    
    def expect_token(self, token_type: TokenType) -> Optional[Token]:
        """Expect a specific token type."""
        if self.current_token and self.current_token.type == token_type:
            token = self.current_token
            self.advance_token()
            return token
        # Special handling: if expecting PERIOD, skip intervening NEWLINEs and COMMENTs
        elif token_type == TokenType.PERIOD:
            while self.current_token and self.current_token.type in (TokenType.NEWLINE, TokenType.COMMENT):
                self.advance_token()
            if self.current_token and self.current_token.type == TokenType.PERIOD:
                token = self.current_token
                self.advance_token()
                return token
            else:
                expected = token_type.name
                actual = self.current_token.type.name if self.current_token else "EOF"
                self.add_error(self.create_error(f"Expected {expected}, got {actual}"))
                return None
        else:
            expected = token_type.name
            actual = self.current_token.type.name if self.current_token else "EOF"
            self.add_error(self.create_error(f"Expected {expected}, got {actual}"))
            return None
    
    def match_token(self, *token_types: TokenType) -> Optional[Token]:
        """Match one of several token types."""
        if self.current_token and self.current_token.type in token_types:
            token = self.current_token
            self.advance_token()
            return token
        return None
    
    def skip_to_token(self, *token_types: TokenType) -> bool:
        """Skip tokens until one of the specified types is found."""
        while self.current_token and self.current_token.type not in token_types:
            if not self.advance_token():
                break
        return self.current_token is not None and self.current_token.type in token_types
    
    def parse_program(self) -> Optional[CobolProgram]:
        """Parse a complete COBOL program."""
        program_name = None
        program_location = self.get_current_location()
        
        # Parse IDENTIFICATION DIVISION first to get program name
        if self.parse_identification_division():
            program_name = self.current_program.program_name if self.current_program else "UNKNOWN"
        else:
            program_name = "UNKNOWN"
            if self.error_recovery == ErrorRecoveryMode.FAIL_FAST:
                return None
        
        # Create program if not already created
        if not self.current_program:
            self.current_program = CobolProgram(program_name, program_location)
        
        # Parse remaining divisions
        self.parse_environment_division()
        self.parse_data_division()  
        self.parse_procedure_division()
        
        return self.current_program
    
    def parse_identification_division(self) -> bool:
        """Parse IDENTIFICATION DIVISION."""
        # Skip any leading comments or newlines before the first division header
        while self.current_token and self.current_token.type in (TokenType.COMMENT, TokenType.NEWLINE):
            self.advance_token()
        if not self.match_token(TokenType.IDENTIFICATION_DIVISION):
            self.add_error(self.create_error("Expected IDENTIFICATION DIVISION"))
            return False

        # Some lexers (and our current lexer) produce IDENTIFICATION then a generic IDENTIFIER token 'DIVISION'
        # rather than a combined IDENTIFICATION_DIVISION token. Accept either form gracefully.
        if self.current_token and self.current_token.type == TokenType.IDENTIFIER and self.current_token.value.upper() == 'DIVISION':
            self.advance_token()
        else:
            # It's permissible (though uncommon) for a combined token already to include DIVISION; in that case
            # the next token should be a period. If another identifier appears, still attempt recovery.
            pass

        if not self.expect_token(TokenType.PERIOD):
            return False
        
        # Skip newlines
        while self.match_token(TokenType.NEWLINE):
            pass
        
        # Parse PROGRAM-ID
        program_name = "UNKNOWN"
        location = self.get_current_location()
        
        if self.match_token(TokenType.PROGRAM_ID):
            if self.expect_token(TokenType.PERIOD):
                # Skip newlines
                while self.match_token(TokenType.NEWLINE):
                    pass
                
                # Get program name
                if self.current_token and self.current_token.type == TokenType.IDENTIFIER:
                    program_name = self.current_token.value
                    location = self.current_token.location
                    self.advance_token()
                    
                    # Handle optional PROGRAM-ID clauses (IS INITIAL, IS COMMON, etc.)
                    while (self.current_token and 
                           self.current_token.type == TokenType.IDENTIFIER and 
                           self.current_token.value.upper() == 'IS'):
                        self.advance_token()  # Skip 'IS'
                        # Skip the clause value (INITIAL, COMMON, etc.)
                        if (self.current_token and 
                            self.current_token.type == TokenType.IDENTIFIER):
                            self.advance_token()
                    
                    # Expect period
                    if not self.expect_token(TokenType.PERIOD):
                        return False
        
        # Create program and division
        self.current_program = CobolProgram(program_name, location)
        id_division = CobolDivision("IDENTIFICATION", location)
        self.current_program.add_division(id_division)
        self.current_division = id_division
        
        # Skip all remaining identification division entries until next division
        self.skip_to_next_division()
        
        return True
    
    def parse_environment_division(self) -> bool:
        """Parse ENVIRONMENT DIVISION (optional)."""
        if not self.match_token(TokenType.ENVIRONMENT_DIVISION):
            return True  # Optional division
        
        if not self.match_token(TokenType.IDENTIFIER):  # DIVISION keyword
            self.add_error(self.create_error(
                "Expected DIVISION after ENVIRONMENT"
            ))
        
        if not self.expect_token(TokenType.PERIOD):
            return False
        
        # Create environment division
        env_division = CobolDivision("ENVIRONMENT", self.get_current_location())
        if self.current_program:
            self.current_program.add_division(env_division)
        self.current_division = env_division
        
        # Parse environment sections
        self.parse_environment_sections()
        return True
    
    def parse_environment_sections(self) -> None:
        """Parse environment division sections."""
        while self.current_token and self.current_token.type not in [
            TokenType.DATA_DIVISION, TokenType.PROCEDURE_DIVISION, TokenType.EOF
        ]:
            if self.match_token(TokenType.CONFIGURATION_SECTION):
                self.parse_configuration_section()
            elif self.match_token(TokenType.INPUT_OUTPUT_SECTION):
                self.parse_input_output_section()
            else:
                # Skip unknown tokens
                if not self.match_token(TokenType.NEWLINE):
                    self.advance_token()
    
    def parse_configuration_section(self) -> None:
        """Parse CONFIGURATION SECTION."""
        if not self.match_token(TokenType.IDENTIFIER):  # SECTION keyword
            return
        
        if not self.expect_token(TokenType.PERIOD):
            return
        
        # Create configuration section
        config_section = CobolSection("CONFIGURATION", self.get_current_location())
        if self.current_division:
            self.current_division.add_section(config_section)
        self.current_section = config_section
        
        # Skip content for now - could parse SOURCE-COMPUTER, OBJECT-COMPUTER, etc.
        self.skip_to_next_section()
    
    def parse_input_output_section(self) -> None:
        """Parse INPUT-OUTPUT SECTION."""
        if not self.match_token(TokenType.IDENTIFIER):  # SECTION keyword
            return
        
        if not self.expect_token(TokenType.PERIOD):
            return
        
        # Create input-output section
        io_section = CobolSection("INPUT-OUTPUT", self.get_current_location())
        if self.current_division:
            self.current_division.add_section(io_section)
        self.current_section = io_section
        
        # Parse FILE-CONTROL paragraph
        while self.current_token and self.current_token.type not in [
            TokenType.DATA_DIVISION, TokenType.PROCEDURE_DIVISION, 
            TokenType.CONFIGURATION_SECTION, TokenType.EOF
        ]:
            if (self.current_token and 
                self.current_token.value.upper() == "FILE-CONTROL"):
                self.parse_file_control_paragraph()
            else:
                # Skip other content
                if not self.match_token(TokenType.NEWLINE):
                    self.advance_token()
    
    def parse_file_control_paragraph(self) -> None:
        """Parse FILE-CONTROL paragraph with SELECT statements."""
        # Expect FILE-CONTROL
        if (not self.current_token or 
            self.current_token.value.upper() != "FILE-CONTROL"):
            return
        
        location = self.current_token.location
        self.advance_token()  # Skip FILE-CONTROL
        
        if not self.expect_token(TokenType.PERIOD):
            return
        
        # Create FILE-CONTROL paragraph
        file_control_paragraph = CobolParagraph("FILE-CONTROL", location)
        if self.current_section:
            self.current_section.add_paragraph(file_control_paragraph)
        
        # Parse SELECT statements
        while (self.current_token and 
               self.current_token.type != TokenType.EOF and
               self.current_token.type not in [TokenType.DATA_DIVISION, TokenType.PROCEDURE_DIVISION]):
            
            if (self.current_token.value.upper() == "SELECT"):
                self.parse_select_statement()
            else:
                # Break on next section/division
                if (self.current_token.type in [TokenType.DATA_DIVISION, TokenType.PROCEDURE_DIVISION] or
                    (self.current_token.type == TokenType.IDENTIFIER and 
                     self.current_token.value.upper() in ["CONFIGURATION", "INPUT-OUTPUT", "DATA", "PROCEDURE"])):
                    break
                # Skip other tokens
                if not self.match_token(TokenType.NEWLINE):
                    self.advance_token()
    
    def parse_select_statement(self) -> None:
        """Parse SELECT statement in FILE-CONTROL."""
        if (not self.current_token or 
            self.current_token.value.upper() != "SELECT"):
            return
        
        location = self.current_token.location
        self.advance_token()  # Skip SELECT
        
        # Get file name
        if not self.current_token or self.current_token.type != TokenType.IDENTIFIER:
            return
        
        file_name = self.current_token.value
        self.advance_token()
        
        # Create SELECT statement
        select_stmt = SelectStatement(location)
        select_stmt.set_file_name(file_name)
        
        # Parse ASSIGN (TO) clause. In many codebases ASSIGN and TO can be
        # split across lines, and the target device/filename may appear on
        # the following line (as in the CCVS85 test suite). We therefore:
        # 1. Treat ASSIGN as a keyword even if tokenized as IDENTIFIER.
        # 2. Allow optional TO.
        # 3. Skip intervening NEWLINE tokens before capturing the target.
        if self.current_token and self.current_token.value.upper() == "ASSIGN":
            self.advance_token()  # consume ASSIGN
            # Optional TO keyword
            if self.current_token and self.current_token.value.upper() == "TO":
                self.advance_token()
            # Skip blank lines
            while self.current_token and self.current_token.type == TokenType.NEWLINE:
                self.advance_token()
            # Capture target (identifier or string literal)
            if self.current_token and self.current_token.type in (TokenType.IDENTIFIER, TokenType.STRING_LITERAL):
                if self.current_token.type == TokenType.STRING_LITERAL:
                    assign_to = f'"{self.current_token.value}"'
                else:
                    assign_to = self.current_token.value
                select_stmt.set_assign_to(assign_to)
                self.advance_token()
        
        # Parse optional clauses (ORGANIZATION, ACCESS MODE, etc.)
        while self.current_token and self.current_token.type != TokenType.PERIOD:
            current_val = self.current_token.value.upper() if self.current_token.value else ""
            if current_val == "ORGANIZATION":
                self.advance_token()  # ORGANIZATION
                if self.current_token and self.current_token.value.upper() == "IS":
                    self.advance_token()
                if self.current_token and self.current_token.type == TokenType.IDENTIFIER:
                    select_stmt.set_organization(self.current_token.value)
                    self.advance_token()
            elif current_val == "ACCESS":
                # ACCESS [MODE] [IS] <type>
                self.advance_token()  # ACCESS
                if self.current_token and self.current_token.value.upper() == "MODE":
                    self.advance_token()
                if self.current_token and self.current_token.value.upper() == "IS":
                    self.advance_token()
                if self.current_token and self.current_token.type == TokenType.IDENTIFIER:
                    select_stmt.set_access_mode(self.current_token.value)
                    self.advance_token()
            else:
                # Break on start of another SELECT (defensive) or division/section keywords
                if current_val in ("SELECT", "DATA", "PROCEDURE", "INPUT-OUTPUT", "CONFIGURATION"):
                    break
                self.advance_token()
        
        # Consume period
        if self.current_token and self.current_token.type == TokenType.PERIOD:
            self.advance_token()  # Skip period
        
        # Add SELECT statement to current paragraph
        if hasattr(self.current_section, 'paragraphs') and self.current_section.paragraphs:
            # Get the last paragraph (should be FILE-CONTROL)
            last_paragraph = self.current_section.paragraphs[-1]
            last_paragraph.add_statement(select_stmt)
    
    def parse_data_division(self) -> bool:
        """Parse DATA DIVISION (optional)."""
        if not self.match_token(TokenType.DATA_DIVISION):
            return True  # Optional division
        
        # Skip any newlines between DATA and DIVISION (COBOL allows this)
        while self.current_token and self.current_token.type == TokenType.NEWLINE:
            self.advance_token()
        
        if not self.current_token or self.current_token.type != TokenType.IDENTIFIER or self.current_token.value.upper() != "DIVISION":
            # This might be a false positive DATA token (e.g., in comments)
            # For robustness, just skip this apparent DATA DIVISION and continue parsing
            # This handles cases where DATA appears in descriptive text
            return True  # Continue parsing as if no DATA DIVISION encountered
        
        # Consume DIVISION token
        self.advance_token()
        
        if not self.expect_token(TokenType.PERIOD):
            return False
        
        # Create data division
        data_division = CobolDivision("DATA", self.get_current_location())
        if self.current_program:
            self.current_program.add_division(data_division)
        self.current_division = data_division
        
        # Parse data sections
        self.parse_data_sections()
        return True
    
    def parse_data_sections(self) -> None:
        """Parse data division sections."""
        while self.current_token and self.current_token.type not in [
            TokenType.PROCEDURE_DIVISION, TokenType.EOF
        ]:
            if self.match_token(TokenType.WORKING_STORAGE_SECTION):
                self.parse_working_storage_section()
            elif self.match_token(TokenType.LOCAL_STORAGE_SECTION):
                self.parse_local_storage_section()
            elif self.match_token(TokenType.LINKAGE_SECTION):
                self.parse_linkage_section()
            elif self.match_token(TokenType.FILE_SECTION):
                self.parse_file_section()
            else:
                # Skip unknown tokens
                self.advance_token()
    
    def parse_working_storage_section(self) -> None:
        """Parse WORKING-STORAGE SECTION."""
        if not self.match_token(TokenType.IDENTIFIER):  # SECTION keyword
            self.add_error(ParseError(
                "Expected SECTION after WORKING-STORAGE",
                self.get_current_location()
            ))
            return
        
        if not self.expect_token(TokenType.PERIOD):
            return
        
        # Create working storage section
        ws_section = CobolSection("WORKING-STORAGE", self.get_current_location())
        if self.current_division:
            self.current_division.add_section(ws_section)
        self.current_section = ws_section
        
        # Parse data items
        self.parse_data_items()
    
    def parse_local_storage_section(self) -> None:
        """Parse LOCAL-STORAGE SECTION."""
        if not self.match_token(TokenType.IDENTIFIER):  # SECTION keyword
            return
        
        if not self.expect_token(TokenType.PERIOD):
            return
        
        # Create local storage section
        ls_section = CobolSection("LOCAL-STORAGE", self.get_current_location())
        if self.current_division:
            self.current_division.add_section(ls_section)
        self.current_section = ls_section
        
        # Parse data items
        self.parse_data_items()
    
    def parse_linkage_section(self) -> None:
        """Parse LINKAGE SECTION."""
        if not self.match_token(TokenType.IDENTIFIER):  # SECTION keyword
            return
        
        if not self.expect_token(TokenType.PERIOD):
            return
        
        # Create linkage section
        linkage_section = CobolSection("LINKAGE", self.get_current_location())
        if self.current_division:
            self.current_division.add_section(linkage_section)
        self.current_section = linkage_section
        
        # Parse data items
        self.parse_data_items()
    
    def parse_file_section(self) -> None:
        """Parse FILE SECTION with FD records."""
        if not self.match_token(TokenType.IDENTIFIER):  # SECTION keyword
            return
        
        if not self.expect_token(TokenType.PERIOD):
            return
        
        # Create file section
        file_section = CobolSection("FILE", self.get_current_location())
        if self.current_division:
            self.current_division.add_section(file_section)
        self.current_section = file_section
        
        # Parse FD records and data items
        while self.current_token and self.current_token.type not in [
            TokenType.PROCEDURE_DIVISION, TokenType.WORKING_STORAGE_SECTION,
            TokenType.LOCAL_STORAGE_SECTION, TokenType.LINKAGE_SECTION, TokenType.EOF
        ]:
            if (self.current_token and 
                self.current_token.value.upper() == "FD"):
                self.parse_fd_record()
            elif self.current_token.type == TokenType.LEVEL_NUMBER:
                self.parse_data_item()
            else:
                # Skip newlines and other tokens
                if not self.match_token(TokenType.NEWLINE):
                    self.advance_token()
    
    def parse_fd_record(self) -> None:
        """Parse FD (File Description) record."""
        if (not self.current_token or 
            self.current_token.value.upper() != "FD"):
            return
        
        location = self.current_token.location
        self.advance_token()  # Skip FD
        
        # Get file name
        if not self.current_token or self.current_token.type != TokenType.IDENTIFIER:
            return
        
        file_name = self.current_token.value
        self.advance_token()
        
        # Create FD record
        fd_record = CobolFileDescription(file_name, location)
        
        # Parse optional clauses until period
        while (self.current_token and 
               self.current_token.type != TokenType.PERIOD):
            # Could parse RECORD CONTAINS, BLOCK CONTAINS, LABEL RECORDS here
            self.advance_token()
        
        if self.current_token and self.current_token.type == TokenType.PERIOD:
            self.advance_token()  # Skip period
        
        # Add FD to current section
        if self.current_section:
            self.current_section.add_child(fd_record)
    
    def parse_data_items(self) -> None:
        """Parse data item definitions with hierarchical structure support."""
        data_item_stack = []  # Stack to maintain hierarchy
        
        while self.current_token and self.current_token.type not in [
            TokenType.PROCEDURE_DIVISION, TokenType.WORKING_STORAGE_SECTION,
            TokenType.LOCAL_STORAGE_SECTION, TokenType.LINKAGE_SECTION,
            TokenType.FILE_SECTION, TokenType.EOF
        ]:
            if self.current_token.type == TokenType.LEVEL_NUMBER:
                data_item = self.parse_data_item()
                if data_item:
                    # Manage hierarchy based on level numbers
                    current_level = data_item.level
                    
                    # Remove items from stack that are at same or higher level
                    while (data_item_stack and 
                           data_item_stack[-1].level >= current_level):
                        data_item_stack.pop()
                    
                    # If stack is not empty, add as child to parent
                    if data_item_stack:
                        parent = data_item_stack[-1]
                        parent.add_child(data_item)
                    else:
                        # This is a top-level item, add to section
                        if self.current_section:
                            self.current_section.add_data_item(data_item)
                    
                    # Add current item to stack
                    data_item_stack.append(data_item)
            else:
                # Skip newlines and other tokens
                if not self.match_token(TokenType.NEWLINE):
                    self.advance_token()
    
    def parse_data_item(self) -> Optional[CobolDataItem]:
        """Parse a single data item definition."""
        if not self.current_token or self.current_token.type != TokenType.LEVEL_NUMBER:
            return None
        
        # Heuristic: Check if this LEVEL_NUMBER is likely a false positive
        # (e.g., '1' from a broken string like '5.4(1)' being tokenized incorrectly)
        if (self.current_token.value in ['1', '2', '3', '4', '5', '6', '7', '8', '9'] and
            self.current_token.location.column > 30):  # Not in typical level number position
            # This might be a broken string - skip this token
            self.advance_token()
            return None
        
        level = int(self.current_token.value)
        location = self.current_token.location
        self.advance_token()
        
        # Get data name (or handle anonymous data items)
        name = None
        
        # Enhanced data name detection with better error recovery
        if self.current_token:
            # Check if current token is directly a clause keyword (anonymous item)
            if self.current_token.value.upper() in ['REDEFINES', 'VALUE', 'OCCURS', 'USAGE', 'COMP', 'COMP-3', 'SYNC', 'SYNCHRONIZED']:
                name = f"ANONYMOUS-{level}-{location.line}"
            elif self.current_token.type in [TokenType.PIC, TokenType.PICTURE]:
                # Anonymous data item: level number directly followed by PIC clause
                name = f"ANONYMOUS-{level}-{location.line}"
            elif self.current_token.type == TokenType.IDENTIFIER:
                # Normal data name
                name = self.current_token.value
                self.advance_token()
            else:
                # Handle complex cases where tokenization might be off
                # Try to construct a reasonable data name from available tokens
                constructed_name = ""
                
                # Look ahead a few tokens to see if we can piece together a data name
                lookahead_tokens = []
                temp_index = self.current_token_index
                for i in range(min(3, len(self.tokens) - temp_index)):
                    if temp_index + i < len(self.tokens):
                        token = self.tokens[temp_index + i]
                        lookahead_tokens.append(token)
                
                # Try to construct name from consecutive alphanumeric tokens/identifiers
                for token in lookahead_tokens:
                    if token.type in [TokenType.NUMERIC_LITERAL, TokenType.IDENTIFIER] and token.location.line == location.line:
                        # Only include if it's on the same line and looks like part of identifier
                        if constructed_name and not constructed_name.endswith('-'):
                            # Don't concatenate unless there's a hyphen connection
                            break
                        constructed_name += token.value
                        self.advance_token()
                    elif token.type == TokenType.MINUS and token.location.line == location.line:
                        constructed_name += "-"
                        self.advance_token()
                    elif token.type in [TokenType.PIC, TokenType.PICTURE, TokenType.VALUE]:
                        # Found a clause, stop constructing name
                        break
                    else:
                        break
                
                if constructed_name and len(constructed_name) > 0:
                    name = constructed_name
                else:
                    # Fallback: check if we're in middle of line (malformed continuation)
                    if (self.current_token.location.line == location.line and
                        self.current_token.location.column > 20):
                        # Skip this malformed data item
                        return None
                    
                    # Create anonymous item and continue parsing
                    name = f"ANONYMOUS-{level}-{location.line}"
        else:
            self.add_error(self.create_error(
                "Expected data name after level number"
            ))
            return None
        
        # Create data item
        data_item = CobolDataItem(name, level, location)
        
        # Parse clauses in any order until period or semicolon (some dialects)
        period_consumed_by_picture = False
        while self.current_token and self.current_token.type not in [TokenType.PERIOD, TokenType.SEMICOLON]:
            
            # PICTURE clause
            if self.match_token(TokenType.PIC, TokenType.PICTURE):
                picture_pattern, picture_location, consumed_period = self._parse_picture_pattern()
                if picture_pattern:
                    picture_clause = PictureClause(picture_pattern, picture_location)
                    data_item.picture_clause = picture_clause
                    period_consumed_by_picture = consumed_period
            
            # VALUE clause
            elif self.match_token(TokenType.VALUE):
                if self.current_token and self.current_token.type in [
                    TokenType.STRING_LITERAL, TokenType.NUMERIC_LITERAL, 
                    TokenType.FIGURATIVE_CONSTANT, TokenType.IDENTIFIER
                ]:
                    # Refined multi-line string literal handling for VALUE clause
                    if self.current_token.type == TokenType.STRING_LITERAL:
                        string_value = self.current_token.value
                        end_quote_found = '"' in string_value
                        while not end_quote_found and self.current_token_index + 1 < len(self.tokens):
                            next_token = self.tokens[self.current_token_index + 1]
                            # Heuristic: continuation line if column 7 is '-'
                            if hasattr(next_token, 'source_line') and next_token.source_line[6] == '-':
                                string_value += next_token.value
                                self.current_token_index += 1
                                end_quote_found = '"' in next_token.value
                            else:
                                break
                        data_item.initial_value = f'"{string_value}"'
                        self.advance_token()
                    else:
                        data_item.initial_value = self.current_token.value
                        self.advance_token()
            
            # USAGE clause
            elif self.match_token(TokenType.USAGE):
                usage_type = self._parse_usage_clause()
                if usage_type:
                    data_item.usage = usage_type
            
            # COMPUTATIONAL variations (without USAGE keyword)
            elif self.match_token(TokenType.COMP, TokenType.COMP_1, TokenType.COMP_2, 
                                TokenType.COMP_3, TokenType.COMP_4, TokenType.COMP_5, 
                                TokenType.COMPUTATIONAL):
                data_item.usage = self.tokens[self.current_token_index - 1].value
            
            # REDEFINES clause
            elif self.match_token(TokenType.REDEFINES):
                if self.current_token and self.current_token.type == TokenType.IDENTIFIER:
                    data_item.redefines = self.current_token.value
                    self.advance_token()
            
            # OCCURS clause
            elif self.match_token(TokenType.OCCURS):
                occurs_clause = self._parse_occurs_clause()
                if occurs_clause:
                    data_item.occurs_clause = occurs_clause
            
            # SYNC/SYNCHRONIZED clause
            elif self.current_token and self.current_token.value.upper() in ['SYNC', 'SYNCHRONIZED']:
                self.advance_token()  # Skip SYNC
                # Handle optional RIGHT/LEFT
                if (self.current_token and 
                    self.current_token.value.upper() in ['RIGHT', 'LEFT']):
                    self.advance_token()
            
            # Other clauses (skip for now)
            elif (self.current_token and self.current_token.type == TokenType.IDENTIFIER and
                  self.current_token.value.upper() in ['COMP', 'COMP-1', 'COMP-2', 'COMP-3', 'COMP-4', 'COMP-5', 'COMPUTATIONAL', 'DISPLAY', 'BINARY', 'PACKED-DECIMAL']):
                self.advance_token()  # Skip usage type
            
            else:
                # Skip unknown tokens or advance on unrecognized clause
                self.advance_token()
        
        # Expect period or semicolon (unless it was already consumed by PICTURE parsing)
        if not period_consumed_by_picture:
            if self.current_token and self.current_token.type in [TokenType.PERIOD, TokenType.SEMICOLON]:
                self.advance_token()  # Consume the terminator
            else:
                self.expect_token(TokenType.PERIOD)  # Still expect period by default
                return data_item
        
        # Top-level items will be added to section in parse_data_items
        # This method just creates and returns the data item
        
        return data_item
    
    def _parse_usage_clause(self) -> Optional[str]:
        """Parse USAGE clause and return usage type."""
        if self.match_token(TokenType.COMP, TokenType.COMP_1, TokenType.COMP_2, 
                          TokenType.COMP_3, TokenType.COMP_4, TokenType.COMP_5, 
                          TokenType.COMPUTATIONAL, TokenType.DISPLAY):
            return self.tokens[self.current_token_index - 1].value
        elif self.current_token and self.current_token.type == TokenType.IDENTIFIER:
            # Handle IS COMPUTATIONAL, IS DISPLAY, etc.
            if self.current_token.value.upper() == "IS":
                self.advance_token()
                if self.current_token and self.current_token.value.upper() in [
                    "COMPUTATIONAL", "COMP", "COMP-1", "COMP-2", "COMP-3", 
                    "COMP-4", "COMP-5", "DISPLAY"
                ]:
                    usage = self.current_token.value
                    self.advance_token()
                    return usage
        return None
    
    def _parse_occurs_clause(self) -> Optional[OccursClause]:
        """Parse OCCURS clause."""
        if not self.current_token:
            return None
            
        occurs_clause = OccursClause(self.get_current_location())
        
        # Get the number (could be NUMERIC_LITERAL or LEVEL_NUMBER)
        if self.current_token.type in [TokenType.NUMERIC_LITERAL, TokenType.LEVEL_NUMBER]:
            # Handle case where numeric literal includes trailing period (e.g., "10.")
            value_str = self.current_token.value
            if value_str.endswith('.'):
                value_str = value_str[:-1]  # Remove trailing period
            times = int(value_str)
            occurs_clause.set_fixed_occurs(times)
            self.advance_token()
            
            # Optional TIMES keyword
            if self.current_token and self.current_token.type == TokenType.TIMES:
                self.advance_token()
            elif self.current_token and self.current_token.value.upper() == "TIMES":
                self.advance_token()
            
            # Check for DEPENDING ON
            if (self.current_token and 
                self.current_token.value.upper() == "DEPENDING"):
                self.advance_token()
                if (self.current_token and 
                    self.current_token.value.upper() == "ON"):
                    self.advance_token()
                    if (self.current_token and 
                        self.current_token.type == TokenType.IDENTIFIER):
                        depending_var = self.current_token.value
                        occurs_clause.depending_on = depending_var
                        self.advance_token()
            
            return occurs_clause
        
        return None
    
    def _parse_picture_pattern(self) -> tuple[Optional[str], SourceLocation, bool]:
        """Parse a complete PICTURE pattern, including parentheses."""
        if not self.current_token:
            return None, self.get_current_location()
        
        pattern = ""
        location = self.current_token.location
        
        # Collect all tokens that make up the picture pattern
        # For display edited patterns, we need to handle periods within the pattern differently
        # than the period that ends the statement
        while (self.current_token and 
               self.current_token.type not in [TokenType.VALUE, TokenType.USAGE, 
                                             TokenType.OCCURS, TokenType.REDEFINES]):
            
            if self.current_token.type == TokenType.IDENTIFIER:
                pattern += self.current_token.value
            elif self.current_token.type == TokenType.LEFT_PAREN:
                pattern += "("
            elif self.current_token.type == TokenType.RIGHT_PAREN:
                pattern += ")"
            elif self.current_token.type == TokenType.LEVEL_NUMBER:
                # In PICTURE context, level numbers are actually pattern characters
                pattern += self.current_token.value
            elif self.current_token.type == TokenType.NUMERIC_LITERAL:
                pattern += self.current_token.value
            elif self.current_token.type == TokenType.MINUS:
                pattern += "-"
            elif self.current_token.type == TokenType.PERIOD:
                # Check if this is part of a numeric edited pattern or statement end
                next_token_idx = self.current_token_index + 1
                if (next_token_idx < len(self.tokens) and 
                    (self.tokens[next_token_idx].type == TokenType.LEVEL_NUMBER or
                     (self.tokens[next_token_idx].type == TokenType.IDENTIFIER and
                      self.tokens[next_token_idx].value.startswith('9')))):
                    # This period is part of the pattern (e.g., -9(9).9(9))
                    pattern += "."
                else:
                    # This period ends the statement
                    break
            else:
                # Stop on unexpected token
                break
            
            self.advance_token()
        
        # Clean up pattern - remove trailing period if it was incorrectly included
        period_consumed = False
        if pattern and pattern.endswith('.'):
            pattern = pattern[:-1]
            period_consumed = True
        
        return pattern if pattern else None, location, period_consumed
    
    def parse_procedure_division(self) -> bool:
        """Parse PROCEDURE DIVISION."""
        if not self.match_token(TokenType.PROCEDURE_DIVISION):
            return True  # Optional division
        
        if not self.match_token(TokenType.IDENTIFIER):  # DIVISION keyword
            self.add_error(ParseError(
                "Expected DIVISION after PROCEDURE",
                self.get_current_location()
            ))
        
        # Handle optional USING clause: PROCEDURE DIVISION USING data-name-1 [data-name-2 ...]
        if self.current_token and self.current_token.type == TokenType.IDENTIFIER and self.current_token.value.upper() == "USING":
            self.advance_token()  # consume USING
            # Parse one or more data names until we reach a period
            while (self.current_token and 
                   self.current_token.type != TokenType.PERIOD):
                if self.current_token.type == TokenType.IDENTIFIER:
                    self.advance_token()  # consume data name
                elif self.current_token.type == TokenType.COMMA:
                    self.advance_token()  # consume comma
                elif self.current_token.type in (TokenType.NEWLINE, TokenType.COMMENT):
                    self.advance_token()  # skip newlines/comments in multi-line USING clause
                else:
                    # Unexpected token, break to avoid infinite loop
                    break
        
        if not self.expect_token(TokenType.PERIOD):
            return False
        
        # Create procedure division
        proc_division = CobolDivision("PROCEDURE", self.get_current_location())
        if self.current_program:
            self.current_program.add_division(proc_division)
        self.current_division = proc_division
        
        # Parse statements
        self.parse_statements()
        return True
    
    def parse_statements(self) -> None:
        """Parse procedure division statements."""
        while self.current_token and self.current_token.type != TokenType.EOF:
            # Check for paragraph/section patterns:
            # - Paragraph: IDENTIFIER PERIOD
            # - Section: IDENTIFIER "SECTION" PERIOD
            if self.current_token.type == TokenType.IDENTIFIER:
                next_token = self.peek_token()
                if next_token and next_token.type == TokenType.PERIOD:
                    # Paragraph pattern: NAME.
                    self.parse_paragraph_or_statement()
                    continue
                elif (next_token and next_token.type == TokenType.IDENTIFIER and 
                      next_token.value.upper() == "SECTION" and
                      self.peek_token(2) and self.peek_token(2).type == TokenType.PERIOD):
                    # Section pattern: NAME SECTION.
                    self.parse_paragraph_or_statement()
                    continue
            # Skip solitary newlines/comments
            if self.current_token.type in (TokenType.NEWLINE, TokenType.COMMENT):
                self.advance_token()
                continue
            # Assemble a sentence: collect tokens until PERIOD or EOF
            # Handle complex cases where periods/newlines don't necessarily end sentences
            sentence_tokens = []
            start_pos_token = self.current_token
            paren_depth = 0
            expecting_to = False  # Track if we've seen MOVE and are expecting TO
            
            while self.current_token and self.current_token.type != TokenType.EOF:
                current_type = self.current_token.type
                current_value = self.current_token.value.upper() if self.current_token.value else ""
                
                # Track parentheses depth
                if current_type == TokenType.LEFT_PAREN:
                    paren_depth += 1
                elif current_type == TokenType.RIGHT_PAREN:
                    paren_depth -= 1
                
                # Track if we're expecting TO (after MOVE statement)
                if current_type == TokenType.MOVE or current_value == 'MOVE':
                    expecting_to = True
                elif expecting_to and (current_value == 'TO'):
                    expecting_to = False
                
                if current_type == TokenType.PERIOD:
                    # Check if this period is part of a decimal literal
                    is_decimal_point = False
                    
                    # Case 1: Period after PLUS/MINUS (e.g., "+.999")
                    if (sentence_tokens and 
                        sentence_tokens[-1].type in (TokenType.PLUS, TokenType.MINUS)):
                        is_decimal_point = True
                    
                    # Case 2: Period at start of decimal literal (e.g., "MOVE .82")
                    # Check if next token is a number
                    next_token = None
                    if hasattr(self, 'tokens') and hasattr(self, 'current_token_index'):
                        if self.current_token_index + 1 < len(self.tokens):
                            next_token = self.tokens[self.current_token_index + 1]
                    
                    if (next_token and 
                        next_token.type in (TokenType.NUMERIC_LITERAL, TokenType.LEVEL_NUMBER)):
                        is_decimal_point = True
                    
                    # Don't end sentence if:
                    # 1. Period is part of decimal literal
                    # 2. We're inside parentheses
                    # 3. We're expecting TO for a MOVE statement
                    if not is_decimal_point and paren_depth == 0 and not expecting_to:
                        # This is a sentence-ending period
                        break
                
                sentence_tokens.append(self.current_token)
                self.advance_token()
            
            # Consume the ending period if present
            if self.current_token and self.current_token.type == TokenType.PERIOD:
                self.advance_token()
            # Parse the sentence for multiple verbs
            self.parse_sentence(sentence_tokens, start_pos_token.location)

    def parse_sentence(self, tokens: list, location) -> None:
        """Parse a sentence that may contain multiple simple verbs in sequence."""
        # Ensure there's a current section to receive statements. If none (e.g., code before first paragraph),
        # create an implicit section named 'IMPLICIT-SECTION'. This mirrors how some COBOL dialects allow
        # straight-line code at top of PROCEDURE DIVISION before any paragraph labels.
        if self.current_division and (self.current_division.division_name == "PROCEDURE") and self.current_section is None:
            implicit = CobolSection("IMPLICIT-SECTION", location)
            self.current_division.add_section(implicit)
            self.current_section = implicit
        i = 0
        length = len(tokens)
        active_if = False
        while i < length:
            tok = tokens[i]
            ttype = tok.type
            upper_val = tok.value.upper()
            # Skip NEWLINE/COMMENT inside sentence (should be rare since we stripped periods boundaries, but keep defensive)
            if ttype in (TokenType.NEWLINE, TokenType.COMMENT):
                i += 1
                continue
            if ttype == TokenType.MOVE or upper_val == 'MOVE':
                # Hand off by temporarily setting current_token pointer logic? For simplicity, parse inline here.
                i = self._parse_move_inline(tokens, i)
                continue
            if ttype == TokenType.PERFORM or upper_val == 'PERFORM':
                i = self._parse_perform_inline(tokens, i)
                continue
            if ttype == TokenType.DISPLAY or upper_val == 'DISPLAY':
                i = self._parse_display_inline(tokens, i)
                continue
            if ttype == TokenType.WRITE or upper_val == 'WRITE':
                i = self._parse_write_inline(tokens, i)
                continue
            if ttype in (TokenType.GO, TokenType.GOTO) or upper_val in ('GO', 'GOTO'):
                i = self._parse_goto_inline(tokens, i)
                continue
            if ttype == TokenType.IF or upper_val == 'IF':
                i = self._parse_if_inline(tokens, i)
                active_if = True
                continue
            if ttype == TokenType.ELSE or upper_val == 'ELSE':
                if not active_if:
                    # Recovery: skip to next recognized verb
                    i = self._skip_to_next_verb(tokens, i+1)
                else:
                    # Consume simple ELSE clause (no nested parsing yet)
                    i = self._skip_to_next_verb(tokens, i+1)
                    active_if = False
                continue
            if ttype == TokenType.SORT or upper_val == 'SORT':
                i = self._parse_sort_inline(tokens, i)
                continue
            # Unrecognized inside sentence: skip token
            i += 1

    def _skip_to_next_verb(self, tokens, start):
        verbs = {TokenType.MOVE, TokenType.PERFORM, TokenType.DISPLAY, TokenType.WRITE, TokenType.GO, TokenType.GOTO, TokenType.IF}
        i = start
        while i < len(tokens) and tokens[i].type not in verbs:
            i += 1
        return i

    def _parse_move_inline(self, tokens, i):
        # i points to the MOVE token
        start = tokens[i]
        i += 1  # Move past MOVE token
        
        if i >= len(tokens):
            # MOVE at end of token stream - add error and return
            self.add_error(ParseError("Expected source operand in MOVE statement (no more tokens)", start.location))
            return i
        
        # Skip optional separators before source (multi-line MOVE support)
        while i < len(tokens) and tokens[i].type in (TokenType.NEWLINE, TokenType.COMMENT, TokenType.CONTINUATION):
            i += 1
            
        if i >= len(tokens):
            # Still no tokens after skipping separators - add error and return
            self.add_error(ParseError("Expected source operand in MOVE statement (no more tokens)", start.location))
            return i
        
        # Parse source operand
        source_operand = None
        
        # Handle PLUS/MINUS signs (with possible continuation lines)
        if (i < len(tokens) and tokens[i].type in (TokenType.PLUS, TokenType.MINUS)):
            sign_token = tokens[i]
            i += 1
            
            # Skip any continuation tokens and newlines after the sign
            while i < len(tokens) and tokens[i].type in (TokenType.CONTINUATION, TokenType.NEWLINE):
                i += 1
            
            # Check what follows the sign (after any continuations)
            if i >= len(tokens):
                self.add_error(ParseError(f"Expected number after {sign_token.value} in MOVE statement (no more tokens)", start.location))
                return i
            elif tokens[i].type in (TokenType.LEVEL_NUMBER, TokenType.NUMERIC_LITERAL):
                # Direct number: +123, -456
                source_operand = sign_token.value + tokens[i].value
                i += 1
                
                # Handle continuation lines that extend the signed number (e.g., -9\n-9 becomes "-99")
                while i < len(tokens):
                    # Skip newlines and continuation tokens
                    while i < len(tokens) and tokens[i].type in (TokenType.NEWLINE, TokenType.CONTINUATION):
                        i += 1
                    # Check if there's a number following
                    if i < len(tokens) and tokens[i].type in (TokenType.LEVEL_NUMBER, TokenType.NUMERIC_LITERAL):
                        source_operand += tokens[i].value
                        i += 1
                    else:
                        break  # No more numbers, stop here
            elif (tokens[i].type == TokenType.PERIOD and
                  i + 1 < len(tokens) and tokens[i + 1].type in (TokenType.NUMERIC_LITERAL, TokenType.LEVEL_NUMBER)):
                # Decimal literal: +.999, -.5
                source_operand = sign_token.value + tokens[i].value + tokens[i + 1].value
                i += 2
            else:
                self.add_error(ParseError(f"Expected number after {sign_token.value} in MOVE statement (found {tokens[i].type.name})", start.location))
                return i
        # Handle PERIOD + NUMBER (decimal literals like .82, .999)
        elif (i < len(tokens) and tokens[i].type == TokenType.PERIOD and
              i + 1 < len(tokens) and tokens[i + 1].type in (TokenType.NUMERIC_LITERAL, TokenType.LEVEL_NUMBER)):
            # Decimal literal: .999, .5
            source_operand = tokens[i].value + tokens[i + 1].value
            i += 2
        # Handle LEVEL_NUMBER as numeric literal (e.g., MOVE 1 TO ...)
        elif i < len(tokens) and tokens[i].type == TokenType.LEVEL_NUMBER:
            source_operand = tokens[i].value
            i += 1
            
            # Handle continuation lines that extend the number (e.g., 4\n-5\n-6 becomes "456")
            while i < len(tokens):
                # Skip newlines and continuation tokens
                while i < len(tokens) and tokens[i].type in (TokenType.NEWLINE, TokenType.CONTINUATION):
                    i += 1
                # Check if there's a number following
                if i < len(tokens) and tokens[i].type in (TokenType.LEVEL_NUMBER, TokenType.NUMERIC_LITERAL):
                    source_operand += tokens[i].value
                    i += 1
                else:
                    break  # No more numbers, stop here
        # Handle NUMERIC_LITERAL with possible continuations
        elif i < len(tokens) and tokens[i].type == TokenType.NUMERIC_LITERAL:
            source_operand = tokens[i].value
            i += 1
            
            # Handle continuation lines that extend the number
            while i < len(tokens):
                # Skip newlines and continuation tokens
                while i < len(tokens) and tokens[i].type in (TokenType.NEWLINE, TokenType.CONTINUATION):
                    i += 1
                # Check if there's a number following
                if i < len(tokens) and tokens[i].type in (TokenType.LEVEL_NUMBER, TokenType.NUMERIC_LITERAL):
                    source_operand += tokens[i].value
                    i += 1
                else:
                    break  # No more numbers, stop here
        # Handle regular tokens (identifiers, literals, etc.)
        elif i < len(tokens):
            source_operand = tokens[i].value
            i += 1
        else:
            self.add_error(ParseError("Expected source operand in MOVE statement (no more tokens)", start.location))
            return i
        
        # Handle comma-separated numeric literals (COBOL allows commas in large numbers)
        # e.g., MOVE 211113411,114311112 TO LONG-NUMBER
        if (i < len(tokens) and tokens[i].type == TokenType.COMMA and
            i + 1 < len(tokens) and tokens[i + 1].type in [TokenType.NUMERIC_LITERAL, TokenType.LEVEL_NUMBER]):
            # Combine with comma
            source_operand += tokens[i].value  # Add comma
            i += 1
            source_operand += tokens[i].value  # Add next number
            i += 1
            
            # Handle multiple comma-separated numbers
            while (i < len(tokens) and tokens[i].type == TokenType.COMMA and
                   i + 1 < len(tokens) and tokens[i + 1].type in [TokenType.NUMERIC_LITERAL, TokenType.LEVEL_NUMBER]):
                source_operand += tokens[i].value  # Add comma
                i += 1
                source_operand += tokens[i].value  # Add next number
                i += 1
        
        # Handle array subscripts and substring operations (may have multiple parentheses)
        # e.g., TABLE-1 (3 2) (2: 5) means element (3,2) substring (2:5)
        while i < len(tokens) and tokens[i].type == TokenType.LEFT_PAREN:
            # Add the opening parenthesis
            source_operand += tokens[i].value
            i += 1
            
            # Include everything until the matching RIGHT_PAREN
            paren_depth = 1
            while i < len(tokens) and paren_depth > 0:
                if tokens[i].type == TokenType.LEFT_PAREN:
                    paren_depth += 1
                elif tokens[i].type == TokenType.RIGHT_PAREN:
                    paren_depth -= 1
                
                source_operand += tokens[i].value
                i += 1
            
            # Skip any whitespace/newlines between consecutive parentheses
            while i < len(tokens) and tokens[i].type in (TokenType.NEWLINE, TokenType.COMMENT, TokenType.CONTINUATION):
                i += 1
        
        # Skip optional separators after source operand (handles multi-line string literals and continuations)
        while i < len(tokens) and tokens[i].type in (TokenType.NEWLINE, TokenType.COMMENT, TokenType.CONTINUATION):
            i += 1
            
        # Look for TO keyword
        target = None
        if i < len(tokens) and tokens[i].value.upper() == 'TO':
            i += 1
            # Skip interstitials after TO (including continuation lines)
            while i < len(tokens) and tokens[i].type in (TokenType.NEWLINE, TokenType.COMMENT, TokenType.CONTINUATION):
                i += 1
            if i < len(tokens):
                target = tokens[i].value
                i += 1
        else:
            # Enhanced debug info for MOVE statement issues
            debug_info = f"Expected TO in MOVE statement"
            if i < len(tokens):
                debug_info += f" (found: {tokens[i].type.name}='{tokens[i].value}')"
            else:
                debug_info += " (no more tokens)"
            
            # Special handling for tokens that suggest we're not actually in a MOVE statement context
            problematic_tokens = {
                TokenType.LEVEL_NUMBER,  # Data definitions (04, 05, etc.)
                TokenType.PERIOD,        # Statement terminators
                TokenType.MULTIPLY_OP,   # Arithmetic operators (*) 
                TokenType.ASSIGN,        # Assignment operators (=)
                TokenType.PLUS,          # Addition operators (+) - might be legitimate but often suggests wrong context
                TokenType.MINUS          # Subtraction operators (-) - might be legitimate but often suggests wrong context
            }
            
            if i < len(tokens) and tokens[i].type in problematic_tokens:
                # These tokens suggest we mistakenly started parsing a MOVE statement
                # when we should be parsing something else (data definitions, arithmetic, etc.)
                # Don't create an error - this is likely a false positive
                # Instead, skip back and let the normal parsing continue
                return i - 1  # Return to the position before advancing past the presumed source operand
            
            # Heuristic: if next token is plausible target (identifier, literal), treat as MOVE
            elif i < len(tokens) and tokens[i].type in (TokenType.IDENTIFIER, TokenType.NUMERIC_LITERAL, TokenType.STRING_LITERAL):
                target = tokens[i].value
                i += 1
                self.add_warning(f"MOVE statement missing TO; treated '{target}' as target at {start.location}")
            else:
                self.add_error(ParseError(debug_info, start.location))
                # Advance index to avoid infinite loop in sentence parsing
                if i < len(tokens):
                    i += 1
        if target is not None:
            mv = MoveStatement(start.location)
            mv.set_source(source_operand)
            mv.add_target(target)
            if self.current_section:
                self.current_section.add_child(mv)
        return i

    def _parse_display_inline(self, tokens, i):
        start = tokens[i]
        i += 1
        if i < len(tokens):
            disp = DisplayStatement(start.location)
            disp.add_display_item(tokens[i].value)
            i += 1
            if self.current_section:
                self.current_section.add_child(disp)
        return i

    def _parse_perform_inline(self, tokens, i):
        start = tokens[i]
        i += 1
        if i < len(tokens):
            pf = PerformStatement(start.location)
            pf.set_target_paragraph(tokens[i].value)
            i += 1
            if self.current_section:
                self.current_section.add_child(pf)
        return i

    def _parse_write_inline(self, tokens, i):
        start = tokens[i]
        i += 1
        if i < len(tokens):
            # WRITE <identifier>
            ws = CobolStatement("WRITE", start.location)
            ws.add_operand(tokens[i].value)
            i += 1
            if self.current_section:
                self.current_section.add_child(ws)
        return i

    def _parse_goto_inline(self, tokens, i):
        start = tokens[i]
        # Support GO TO form (GO token then maybe TO) or GOTO token
        if start.type == TokenType.GO and i + 1 < len(tokens) and tokens[i+1].value.upper() == 'TO':
            i += 2
        else:
            i += 1
        
        gt = CobolStatement("GOTO", start.location)
        
        # Parse targets (could be multiple for DEPENDING ON)
        targets = []
        while i < len(tokens):
            token = tokens[i]
            
            # Check for DEPENDING ON clause
            if token.value.upper() == 'DEPENDING':
                # Add all collected targets
                for target in targets:
                    gt.add_operand(target)
                
                # Skip DEPENDING
                i += 1
                # Skip ON
                if i < len(tokens) and tokens[i].value.upper() == 'ON':
                    i += 1
                # Add the DEPENDING variable
                if i < len(tokens):
                    gt.add_operand(f"DEPENDING ON {tokens[i].value}")
                    i += 1
                break
            
            # Collect targets (paragraph names, numeric labels, etc.)
            if (token.type in [TokenType.IDENTIFIER, TokenType.LEVEL_NUMBER, TokenType.NUMERIC_LITERAL] or
                token.value.isdigit()):
                targets.append(token.value)
                i += 1
            else:
                # End of GO TO statement
                break
        
        # If no DEPENDING clause, add collected targets
        if not any('DEPENDING' in op for op in gt.operands):
            for target in targets:
                gt.add_operand(target)
        
        if self.current_section:
            self.current_section.add_child(gt)
        return i

    def _parse_if_inline(self, tokens, i):
        start = tokens[i]
        i += 1
        cond_parts = []
        # Parse condition up to THEN or first verb/ELSE
        while i < len(tokens) and tokens[i].type not in (TokenType.THEN, TokenType.ELSE, TokenType.MOVE, TokenType.PERFORM, TokenType.DISPLAY, TokenType.WRITE, TokenType.GO, TokenType.GOTO, TokenType.IF):
            cond_parts.append(tokens[i].value)
            i += 1
        condition = ' '.join(cond_parts).strip()
        if_stmt = CobolStatement("IF", start.location)
        if_stmt.add_operand(condition)
        # Parse THEN block (if THEN present, else treat next verb as THEN)
        then_stmts = []
        if i < len(tokens) and tokens[i].type == TokenType.THEN:
            i += 1
        # Parse statements until ELSE or next IF or end
        while i < len(tokens) and tokens[i].type not in (TokenType.ELSE, TokenType.IF):
            verb_tok = tokens[i]
            verb_type = verb_tok.type
            verb_val = verb_tok.value.upper()
            # Only parse known verbs
            if verb_type == TokenType.MOVE or verb_val == 'MOVE':
                j = self._parse_move_inline(tokens, i)
                # Find last statement added to section
                if self.current_section and self.current_section.children:
                    then_stmts.append(self.current_section.children[-1])
                i = j
                continue
            if verb_type == TokenType.PERFORM or verb_val == 'PERFORM':
                j = self._parse_perform_inline(tokens, i)
                if self.current_section and self.current_section.children:
                    then_stmts.append(self.current_section.children[-1])
                i = j
                continue
            if verb_type == TokenType.DISPLAY or verb_val == 'DISPLAY':
                j = self._parse_display_inline(tokens, i)
                if self.current_section and self.current_section.children:
                    then_stmts.append(self.current_section.children[-1])
                i = j
                continue
            if verb_type == TokenType.WRITE or verb_val == 'WRITE':
                j = self._parse_write_inline(tokens, i)
                if self.current_section and self.current_section.children:
                    then_stmts.append(self.current_section.children[-1])
                i = j
                continue
            if verb_type in (TokenType.GO, TokenType.GOTO) or verb_val in ('GO', 'GOTO'):
                j = self._parse_goto_inline(tokens, i)
                if self.current_section and self.current_section.children:
                    then_stmts.append(self.current_section.children[-1])
                i = j
                continue
            # Unknown or non-verb: skip
            i += 1
        # Attach THEN statements to IF node
        if_stmt._metadata['then'] = then_stmts
        # Parse ELSE block if present
        else_stmts = []
        if i < len(tokens) and tokens[i].type == TokenType.ELSE:
            i += 1
            while i < len(tokens) and tokens[i].type not in (TokenType.IF,):
                verb_tok = tokens[i]
                verb_type = verb_tok.type
                verb_val = verb_tok.value.upper()
                if verb_type == TokenType.MOVE or verb_val == 'MOVE':
                    j = self._parse_move_inline(tokens, i)
                    if self.current_section and self.current_section.children:
                        else_stmts.append(self.current_section.children[-1])
                    i = j
                    continue
                if verb_type == TokenType.PERFORM or verb_val == 'PERFORM':
                    j = self._parse_perform_inline(tokens, i)
                    if self.current_section and self.current_section.children:
                        else_stmts.append(self.current_section.children[-1])
                    i = j
                    continue
                if verb_type == TokenType.DISPLAY or verb_val == 'DISPLAY':
                    j = self._parse_display_inline(tokens, i)
                    if self.current_section and self.current_section.children:
                        else_stmts.append(self.current_section.children[-1])
                    i = j
                    continue
                if verb_type == TokenType.WRITE or verb_val == 'WRITE':
                    j = self._parse_write_inline(tokens, i)
                    if self.current_section and self.current_section.children:
                        else_stmts.append(self.current_section.children[-1])
                    i = j
                    continue
                if verb_type in (TokenType.GO, TokenType.GOTO) or verb_val in ('GO', 'GOTO'):
                    j = self._parse_goto_inline(tokens, i)
                    if self.current_section and self.current_section.children:
                        else_stmts.append(self.current_section.children[-1])
                    i = j
                    continue
                i += 1
        if_stmt._metadata['else'] = else_stmts
        if self.current_section:
            self.current_section.add_child(if_stmt)
        return i
    
    def _parse_sort_inline(self, tokens, i):
        """Parse SORT statement inline (basic support)."""
        start = tokens[i]
        i += 1  # Skip SORT
        
        # Skip to find file name (first non-newline/comment token)
        while i < len(tokens) and tokens[i].type in (TokenType.NEWLINE, TokenType.COMMENT):
            i += 1
        
        if i >= len(tokens):
            return i
        
        # Get sort file name
        if tokens[i].type == TokenType.IDENTIFIER:
            sort_file = tokens[i].value
            i += 1
        else:
            return i
        
        # Parse SORT clauses until we find INPUT/OUTPUT PROCEDURE or end
        while i < len(tokens):
            # Skip newlines and comments
            while i < len(tokens) and tokens[i].type in (TokenType.NEWLINE, TokenType.COMMENT):
                i += 1
            
            if i >= len(tokens):
                break
                
            token = tokens[i]
            upper_val = token.value.upper() if token.value else ""
            
            # Handle ASCENDING/DESCENDING KEY clauses
            if upper_val in ('ASCENDING', 'DESCENDING'):
                i += 1  # Skip ASCENDING/DESCENDING
                # Skip KEY
                if i < len(tokens) and tokens[i].value and tokens[i].value.upper() == 'KEY':
                    i += 1
                # Skip key field name
                if i < len(tokens) and tokens[i].type == TokenType.IDENTIFIER:
                    i += 1
                continue
            
            # Handle INPUT PROCEDURE IS
            elif upper_val == 'INPUT':
                i += 1  # Skip INPUT
                # PROCEDURE can be either IDENTIFIER or PROCEDURE_DIVISION token type
                if (i < len(tokens) and 
                    ((tokens[i].value and tokens[i].value.upper() == 'PROCEDURE') or
                     tokens[i].type == TokenType.PROCEDURE_DIVISION)):
                    i += 1  # Skip PROCEDURE
                    if (i < len(tokens) and tokens[i].value and 
                        tokens[i].value.upper() == 'IS'):
                        i += 1  # Skip IS
                        # Skip procedure name
                        if i < len(tokens) and tokens[i].type == TokenType.IDENTIFIER:
                            i += 1
                continue
            
            # Handle OUTPUT PROCEDURE IS  
            elif upper_val == 'OUTPUT':
                i += 1  # Skip OUTPUT
                # PROCEDURE can be either IDENTIFIER or PROCEDURE_DIVISION token type
                if (i < len(tokens) and 
                    ((tokens[i].value and tokens[i].value.upper() == 'PROCEDURE') or
                     tokens[i].type == TokenType.PROCEDURE_DIVISION)):
                    i += 1  # Skip PROCEDURE
                    if (i < len(tokens) and tokens[i].value and 
                        tokens[i].value.upper() == 'IS'):
                        i += 1  # Skip IS
                        # Skip procedure name
                        if i < len(tokens) and tokens[i].type == TokenType.IDENTIFIER:
                            i += 1
                continue
            
            # End of SORT statement
            else:
                break
        
        # Create a basic SORT statement representation
        from cobolparser.models.statements import CobolStatement
        sort_stmt = CobolStatement("SORT", start.location)
        sort_stmt.add_operand(sort_file)
        
        if self.current_section:
            self.current_section.add_child(sort_stmt)
        
        return i
    
    def parse_paragraph_or_statement(self) -> None:
        """Parse paragraph names, section names, or other statement types."""
        # Check for section pattern: NAME SECTION.
        if (self.peek_token() and 
            self.peek_token().value and self.peek_token().value.upper() == "SECTION" and
            self.peek_token(2) and self.peek_token(2).type == TokenType.PERIOD):
            # This is a section declaration: NAME SECTION.
            section_name = self.current_token.value
            location = self.current_token.location
            self.advance_token()  # Skip section name
            self.advance_token()  # Skip SECTION keyword
            self.advance_token()  # Skip period
            
            # Create section in the procedure division
            procedure_section = CobolSection(section_name, location)
            if self.current_division:
                self.current_division.add_section(procedure_section)
            
            # Set this section as current section to collect statements
            self.current_section = procedure_section
            
        # Check for paragraph pattern: NAME.
        elif self.peek_token() and self.peek_token().type == TokenType.PERIOD:
            # This is a paragraph name - create paragraph and parse its statements
            paragraph_name = self.current_token.value
            location = self.current_token.location
            self.advance_token()  # Skip paragraph name
            self.advance_token()  # Skip period
            
            # Create paragraph as a section in the procedure division
            # In COBOL, paragraphs in procedure division are treated as sections
            paragraph_section = CobolSection(paragraph_name, location)
            if self.current_division:
                self.current_division.add_section(paragraph_section)
            
            # Set this paragraph as current section to collect statements
            self.current_section = paragraph_section
        else:
            # Unknown statement, skip
            self.advance_token()
    
    def parse_move_statement(self) -> Optional[MoveStatement]:
        """Parse MOVE statement."""
        if not self.match_token(TokenType.MOVE):
            return None
        
        location = self.get_current_location()
        
        # Allow intervening NEWLINE/COMMENT tokens before source (COBOL multi-line MOVE)
        while self.current_token and self.current_token.type in (TokenType.NEWLINE, TokenType.COMMENT):
            self.advance_token()
        
        # Parse source operand with enhanced logic for COBOL continuation lines
        if not self.current_token:
            # Check if this is the issue - no source token, expecting TO immediately
            if (self.current_token_index + 1 < len(self.tokens) and 
                self.tokens[self.current_token_index + 1].value.upper() == "TO"):
                # This is a malformed MOVE with missing source - create placeholder
                source = "MISSING-SOURCE"
                # Don't advance token, let the TO logic handle it
            else:
                return None
        else:
            source = None
            
            # Handle PLUS/MINUS + LEVEL_NUMBER/NUMERIC_LITERAL combinations (signed numeric literals)
            if (self.current_token.type in (TokenType.PLUS, TokenType.MINUS) and 
                self.peek_token() and 
                self.peek_token().type in (TokenType.LEVEL_NUMBER, TokenType.NUMERIC_LITERAL)):
                # Combine sign with number
                source = self.current_token.value + self.peek_token().value
                self.advance_token()  # Skip sign
                self.advance_token()  # Skip number
            # Handle LEVEL_NUMBER as numeric literal (e.g., MOVE 1 TO ...) or part of continuation
            elif self.current_token.type == TokenType.LEVEL_NUMBER:
                source = self.current_token.value
                self.advance_token()
                
                # Check if this is followed by continuation lines (COBOL multi-line numeric literals)
                # Pattern: LEVEL_NUMBER, NEWLINE, CONTINUATION, LEVEL_NUMBER, ...
                while (self.current_token and self.current_token.type == TokenType.NEWLINE):
                    # Look ahead to see if next token is CONTINUATION
                    next_idx = self.current_token_index + 1
                    if (next_idx < len(self.tokens) and 
                        self.tokens[next_idx].type == TokenType.CONTINUATION):
                        # Skip NEWLINE and CONTINUATION
                        self.advance_token()  # Skip NEWLINE
                        self.advance_token()  # Skip CONTINUATION
                        
                        # Now get the next part of the numeric literal
                        if (self.current_token and 
                            self.current_token.type in (TokenType.LEVEL_NUMBER, TokenType.NUMERIC_LITERAL)):
                            source += self.current_token.value
                            self.advance_token()
                        else:
                            # End of continuation, break out
                            break
                    else:
                        # No continuation, break out
                        break
            # Check if we're seeing TO immediately (missing source value)
            elif (self.current_token.value.upper() == "TO" or 
                  self.current_token.type == TokenType.TO):
                # Missing source - this is a common lexer issue with certain numeric patterns
                source = "MISSING-NUMERIC-LITERAL"
                # Don't advance token, let the TO logic handle it
            # Handle regular tokens (identifiers, literals, etc.)
            else:
                source = self.current_token.value
                self.advance_token()
        
        # Handle array subscripts: if next token is LEFT_PAREN, include the subscript
        if self.current_token and self.current_token.type == TokenType.LEFT_PAREN:
            # Add the opening parenthesis
            source += self.current_token.value
            self.advance_token()
            
            # Include everything until the matching RIGHT_PAREN
            paren_depth = 1
            while self.current_token and paren_depth > 0:
                if self.current_token.type == TokenType.LEFT_PAREN:
                    paren_depth += 1
                elif self.current_token.type == TokenType.RIGHT_PAREN:
                    paren_depth -= 1
                
                source += self.current_token.value
                self.advance_token()

        # Allow intervening NEWLINE/COMMENT tokens before TO
        while self.current_token and self.current_token.type in (TokenType.NEWLINE, TokenType.COMMENT):
            self.advance_token()

        # Expect TO (case-insensitive literal) but be tolerant
        # Accept both IDENTIFIER tokens with value "TO" and actual TO tokens
        found_to = False
        if self.current_token and (
            self.current_token.value.upper() == "TO" or 
            self.current_token.type == TokenType.TO
        ):
            found_to = True
            self.advance_token()
        
        if not found_to:
            # Debug: print current token info
            current_info = f"None" if not self.current_token else f"{self.current_token.type.name}='{self.current_token.value}'"
            # Soft failure: record error, skip to period to reduce cascade
            self.add_error(ParseError(
                f"Expected TO in MOVE statement (found: {current_info})",
                self.get_current_location()
            ))
            # Skip until PERIOD or next verb to allow continued parsing
            while self.current_token and self.current_token.type not in (TokenType.PERIOD, TokenType.MOVE, TokenType.PERFORM, TokenType.DISPLAY, TokenType.CALL, TokenType.STOP, TokenType.EOF):
                self.advance_token()
            # If at a period consume it (end of malformed sentence)
            if self.current_token and self.current_token.type == TokenType.PERIOD:
                self.advance_token()
            return None

        # Allow whitespace/comments before target
        while self.current_token and self.current_token.type in (TokenType.NEWLINE, TokenType.COMMENT):
            self.advance_token()

        # Get target
        if not self.current_token:
            return None
        target = self.current_token.value
        self.advance_token()

        # Optional additional identifiers separated by commas could be supported later.

        # Expect period (tolerate NEWLINE sequence then PERIOD)
        while self.current_token and self.current_token.type == TokenType.NEWLINE:
            self.advance_token()
        if not self.expect_token(TokenType.PERIOD):
            return None

        move_stmt = MoveStatement(location)
        move_stmt.set_source(source)
        move_stmt.add_target(target)
        if self.current_division:
            self.current_division.add_child(move_stmt)
        return move_stmt
    
    def parse_display_statement(self) -> Optional[DisplayStatement]:
        """Parse DISPLAY statement."""
        if not self.match_token(TokenType.DISPLAY):
            return None
        
        location = self.get_current_location()
        
        # Get what to display
        if not self.current_token:
            return None
        
        item = self.current_token.value
        self.advance_token()
        
        # Expect period
        if not self.expect_token(TokenType.PERIOD):
            return None
        
        display_stmt = DisplayStatement(location)
        display_stmt.add_display_item(item)
        if self.current_division:
            self.current_division.add_child(display_stmt)
        
        return display_stmt
    
    def parse_perform_statement(self) -> Optional[PerformStatement]:
        """Parse PERFORM statement."""
        if not self.match_token(TokenType.PERFORM):
            return None
        
        location = self.get_current_location()
        
        # Get paragraph name
        if not self.current_token:
            return None
        
        paragraph = self.current_token.value
        self.advance_token()
        
        # Check for UNTIL clause
        condition = None
        if self.match_token(TokenType.UNTIL):
            # Start building a textual condition until we hit a terminating period.
            cond_tokens = []
            # Gather at least one token (identifier, numeric, etc.)
            while self.current_token and self.current_token.type not in (TokenType.PERIOD, TokenType.NEWLINE):
                # Stop early if we encounter another statement keyword (defensive)
                if self.current_token.type in (TokenType.PERFORM, TokenType.MOVE, TokenType.DISPLAY, TokenType.CALL, TokenType.STOP):
                    break
                cond_tokens.append(self.current_token.value)
                # If we see '=', treat it as part of expression even though token type is ASSIGN
                self.advance_token()
            condition = " ".join(cond_tokens).strip() if cond_tokens else None
            # After condition, allow optional NEWLINE(s)
            while self.current_token and self.current_token.type == TokenType.NEWLINE:
                self.advance_token()
        
        # Expect terminal period (may follow immediately or after condition).
        # Some numeric literals in test inputs include trailing '.' inside the token
        # (e.g., '0.') so we treat a condition ending with such a token as sentence-terminated.
        if not (condition and condition.endswith('.')):
            if not self.expect_token(TokenType.PERIOD):
                return None
        
        perform_stmt = PerformStatement(location)
        perform_stmt.set_target_paragraph(paragraph)
        if condition:
            perform_stmt.perform_type = "UNTIL"
            perform_stmt.until_condition = condition  # TODO: Parse as expression
        if self.current_division:
            self.current_division.add_child(perform_stmt)
        
        return perform_stmt
    
    def parse_call_statement(self) -> Optional[CallStatement]:
        """Parse CALL statement."""
        if not self.match_token(TokenType.CALL):
            return None
        
        location = self.get_current_location()
        
        # Get program name
        if not self.current_token:
            return None
        
        # Preserve quotes for string literals
        if self.current_token.type == TokenType.STRING_LITERAL:
            program_name = f'"{self.current_token.value}"'
        else:
            program_name = self.current_token.value
        self.advance_token()
        
        call_stmt = CallStatement(location)
        call_stmt.set_called_program(program_name)
        
        # Check for USING clause
        if (self.current_token and 
            self.current_token.value.upper() == "USING"):
            self.advance_token()
            
            # Parse USING parameters
            while (self.current_token and 
                   self.current_token.type == TokenType.IDENTIFIER and
                   self.current_token.type != TokenType.PERIOD):
                param_name = self.current_token.value
                call_stmt.add_using_parameter(param_name)
                self.advance_token()
                
                # Break if we hit period or other statement terminators
                if (self.current_token and 
                    self.current_token.type in [TokenType.PERIOD, TokenType.IF, TokenType.MOVE]):
                    break
        
        # Skip other optional clauses for now (GIVING, ON EXCEPTION, etc.)
        
        # Expect period (may already be consumed by paragraph parsing)
        if self.current_token and self.current_token.type == TokenType.PERIOD:
            self.advance_token()
        
        # Add to current division
        if self.current_division:
            self.current_division.add_child(call_stmt)
        
        return call_stmt
    
    def parse_stop_statement(self) -> None:
        """Parse STOP RUN statement."""
        if not self.match_token(TokenType.STOP):
            return
        
        # Expect RUN
        if self.current_token and self.current_token.value.upper() == "RUN":
            self.advance_token()
        
        # Expect period
        self.expect_token(TokenType.PERIOD)
    
    def skip_to_next_division(self) -> None:
        """Skip tokens until next division is found."""
        division_tokens = [
            TokenType.ENVIRONMENT_DIVISION,
            TokenType.DATA_DIVISION,
            TokenType.PROCEDURE_DIVISION,
            TokenType.EOF
        ]
        self.skip_to_token(*division_tokens)
    
    def skip_to_next_section(self) -> None:
        """Skip tokens until next section is found."""
        section_tokens = [
            TokenType.CONFIGURATION_SECTION,
            TokenType.INPUT_OUTPUT_SECTION,
            TokenType.WORKING_STORAGE_SECTION,
            TokenType.LOCAL_STORAGE_SECTION, 
            TokenType.LINKAGE_SECTION,
            TokenType.FILE_SECTION,
            TokenType.PROCEDURE_DIVISION,
            TokenType.EOF
        ]
        self.skip_to_token(*section_tokens)


# Convenience function for simple parsing
def parse_cobol(
    source: str, 
    filename: str = "<string>",
    dialect: DialectType = DialectType.IBM_ENTERPRISE,
    error_recovery: ErrorRecoveryMode = ErrorRecoveryMode.FAIL_FAST,
    free_form: bool = False,
    preprocess_fixed: bool = False,
) -> ParseResult:
    """Convenience function to parse COBOL source code.
    
    Args:
        source: COBOL source code
        filename: Source filename for error reporting
        dialect: COBOL dialect
        error_recovery: Error recovery mode
        
    Returns:
        ParseResult with AST and metadata
    """
    if preprocess_fixed:
        try:
            from .preprocess import normalize_fixed_format
            source = normalize_fixed_format(source.splitlines())
            free_form = True  # normalize produces free-form text
        except Exception:
            pass  # fallback silently
    parser = CobolParser(dialect=dialect, error_recovery=error_recovery, free_form=free_form)
    return parser.parse(source, filename)