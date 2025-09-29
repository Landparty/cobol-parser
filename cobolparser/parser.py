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
        plugin_manager: Optional[PluginManager] = None
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
            lexer = CobolLexer(source, filename, self.dialect)
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
        if not self.match_token(TokenType.IDENTIFICATION_DIVISION):
            self.add_error(self.create_error("Expected IDENTIFICATION DIVISION"))
            return False
        
        if not self.match_token(TokenType.IDENTIFIER):  # DIVISION keyword
            self.add_error(self.create_error("Expected DIVISION after IDENTIFICATION"))
        
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
        
        # Parse ASSIGN TO clause
        if (self.current_token and 
            self.current_token.value.upper() == "ASSIGN"):
            self.advance_token()  # Skip ASSIGN
            if (self.current_token and 
                self.current_token.value.upper() == "TO"):
                self.advance_token()  # Skip TO
                if self.current_token:
                    # Preserve quotes for string literals
                    if self.current_token.type == TokenType.STRING_LITERAL:
                        assign_to = f'"{self.current_token.value}"'
                    else:
                        assign_to = self.current_token.value
                    select_stmt.set_assign_to(assign_to)
                    self.advance_token()
        
        # Parse optional clauses (ORGANIZATION, ACCESS MODE, etc.)
        while (self.current_token and 
               self.current_token.type != TokenType.PERIOD):
            if self.current_token.value.upper() == "ORGANIZATION":
                self.advance_token()  # Skip ORGANIZATION
                if (self.current_token and self.current_token.value.upper() == "IS"):
                    self.advance_token()  # Skip IS
                if self.current_token:
                    select_stmt.set_organization(self.current_token.value)
                    self.advance_token()
            elif self.current_token.value.upper() == "ACCESS":
                self.advance_token()  # Skip ACCESS
                if (self.current_token and self.current_token.value.upper() == "MODE"):
                    self.advance_token()  # Skip MODE
                    if (self.current_token and self.current_token.value.upper() == "IS"):
                        self.advance_token()  # Skip IS
                    if self.current_token:
                        select_stmt.set_access_mode(self.current_token.value)
                        self.advance_token()
            else:
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
        
        if not self.match_token(TokenType.IDENTIFIER):  # DIVISION keyword
            self.add_error(ParseError(
                "Expected DIVISION after DATA",
                self.get_current_location()
            ))
        
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
        
        level = int(self.current_token.value)
        location = self.current_token.location
        self.advance_token()
        
        # Get data name
        if not self.current_token or self.current_token.type != TokenType.IDENTIFIER:
            self.add_error(self.create_error(
                "Expected data name after level number"
            ))
            return None
        
        name = self.current_token.value
        self.advance_token()
        
        # Create data item
        data_item = CobolDataItem(name, level, location)
        
        # Parse clauses in any order until period
        period_consumed_by_picture = False
        while self.current_token and self.current_token.type != TokenType.PERIOD:
            
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
                    # Preserve quotes for string literals
                    if self.current_token.type == TokenType.STRING_LITERAL:
                        data_item.initial_value = f'"{self.current_token.value}"'
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
            
            else:
                # Skip unknown tokens or advance on unrecognized clause
                self.advance_token()
        
        # Expect period (unless it was already consumed by PICTURE parsing)
        if not period_consumed_by_picture and not self.expect_token(TokenType.PERIOD):
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
            times = int(self.current_token.value)
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
            statement = None
            
            if self.current_token.type == TokenType.MOVE:
                statement = self.parse_move_statement()
            elif self.current_token.type == TokenType.DISPLAY:
                statement = self.parse_display_statement()
            elif self.current_token.type == TokenType.PERFORM:
                statement = self.parse_perform_statement()
            elif self.current_token.type == TokenType.CALL:
                statement = self.parse_call_statement()
            elif self.current_token.type == TokenType.STOP:
                statement = self.parse_stop_statement()
            elif self.current_token.type == TokenType.IDENTIFIER:
                # Check if this is a paragraph name (for labels)
                self.parse_paragraph_or_statement()
            else:
                # Skip newlines and other tokens
                if not self.match_token(TokenType.NEWLINE):
                    self.advance_token()
            
            # Add statement to current section if we have one
            if statement and self.current_section:
                self.current_section.add_child(statement)
    
    def parse_paragraph_or_statement(self) -> None:
        """Parse paragraph names or other statement types."""
        if self.peek_token() and self.peek_token().type == TokenType.PERIOD:
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
        
        # Get source
        if not self.current_token:
            return None
        
        source = self.current_token.value
        self.advance_token()
        
        # Expect TO
        if not self.current_token or self.current_token.value.upper() != "TO":
            self.add_error(ParseError(
                "Expected TO in MOVE statement",
                self.get_current_location()
            ))
            return None
        self.advance_token()
        
        # Get target
        if not self.current_token:
            return None
        
        target = self.current_token.value
        self.advance_token()
        
        # Expect period
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
            # Parse condition (simplified)
            if self.current_token:
                condition = self.current_token.value
                self.advance_token()
        
        # Expect period
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
    error_recovery: ErrorRecoveryMode = ErrorRecoveryMode.FAIL_FAST
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
    parser = CobolParser(dialect=dialect, error_recovery=error_recovery)
    return parser.parse(source, filename)