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
    PerformStatement, IfStatement, StopStatement, CallStatement, SelectStatement, ArithmeticExpression, ConditionalExpression
)
from .models.data_items import CobolDataItem, PictureClause, OccursClause
from .models.sql_statements import parse_exec_sql, ExecSQLStatement
from .plugins.core import (
    ParseError, ParseStatistics, ErrorRecoveryMode, DialectType,
    MemoryConfiguration, SerializationConfig, PluginManager
)
from .preprocess import normalize_fixed_format


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
        self.parsing_nested_statement = False  # Track nested statement parsing
        
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
        return SourceLocation(1, 1, 1)
    
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
    
    def _set_node_context(self, node: ASTNode) -> None:
        """Set division and section context on a newly created node."""
        division_name = self.current_division.division_name if self.current_division else None
        section_name = self.current_section.section_name if self.current_section else None
        node.set_division_context(division_name, section_name)
    
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
                    while self.current_token and self.current_token.type == TokenType.IS:
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
        self._set_node_context(config_section)
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
        self._set_node_context(io_section)
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
        self._set_node_context(file_control_paragraph)
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
        """Parse SELECT statement in FILE-CONTROL with comprehensive clause support.
        
        Supports all SELECT clause variations:
        - SELECT [OPTIONAL] file-name
        - ASSIGN TO assignment-name/device-name/literal
        - ORGANIZATION IS SEQUENTIAL/INDEXED/RELATIVE/LINE SEQUENTIAL
        - ACCESS MODE IS SEQUENTIAL/RANDOM/DYNAMIC
        - RECORD KEY IS data-name [SOURCE IS data-name]
        - ALTERNATE RECORD KEY IS data-name [WITH DUPLICATES] [PASSWORD IS data-name]
        - RELATIVE KEY IS data-name
        - FILE STATUS IS data-name [, data-name]
        - RESERVE integer AREA(S)
        - PADDING CHARACTER IS data-name/literal
        - RECORD DELIMITER IS STANDARD-1/data-name
        - PASSWORD IS data-name
        - LOCK MODE IS {MANUAL/AUTOMATIC/EXCLUSIVE} [WITH LOCK ON {RECORD/MULTIPLE RECORDS}] [WITH ROLLBACK]
        - SHARING WITH {ALL/NO OTHER/READ ONLY}
        """
        if (not self.current_token or 
            self.current_token.value.upper() != "SELECT"):
            return
        
        location = self.current_token.location
        self.advance_token()  # Skip SELECT
        
        # Skip newlines
        while self.current_token and self.current_token.type == TokenType.NEWLINE:
            self.advance_token()
        
        # Check for OPTIONAL keyword
        is_optional = False
        if self.current_token and self.current_token.value.upper() == "OPTIONAL":
            is_optional = True
            self.advance_token()
            # Skip newlines
            while self.current_token and self.current_token.type == TokenType.NEWLINE:
                self.advance_token()
        
        # Get file name
        if not self.current_token or self.current_token.type != TokenType.IDENTIFIER:
            self.add_error(self.create_error("Expected file name after SELECT"))
            return
        
        file_name = self.current_token.value
        self.advance_token()
        
        # Create SELECT statement
        select_stmt = SelectStatement(location)
        self._set_node_context(select_stmt)
        select_stmt.set_file_name(file_name, is_optional)
        
        # Parse clauses until period
        while self.current_token and self.current_token.type != TokenType.PERIOD:
            # Skip newlines between clauses
            while self.current_token and self.current_token.type == TokenType.NEWLINE:
                self.advance_token()
            
            if not self.current_token or self.current_token.type == TokenType.PERIOD:
                break
            
            current_val = self.current_token.value.upper() if self.current_token.value else ""
            
            # ASSIGN clause
            if current_val == "ASSIGN":
                self._parse_select_assign_clause(select_stmt)
            
            # ORGANIZATION clause
            elif current_val == "ORGANIZATION":
                self._parse_select_organization_clause(select_stmt)
            
            # ACCESS MODE clause
            elif current_val == "ACCESS":
                self._parse_select_access_mode_clause(select_stmt)
            
            # RECORD KEY clause
            elif current_val == "RECORD":
                self._parse_select_record_key_clause(select_stmt)
            
            # ALTERNATE RECORD KEY clause
            elif current_val == "ALTERNATE":
                self._parse_select_alternate_key_clause(select_stmt)
            
            # RELATIVE KEY clause  
            elif current_val == "RELATIVE":
                self._parse_select_relative_key_clause(select_stmt)
            
            # FILE STATUS clause
            elif current_val == "FILE" or current_val == "FILE-STATUS":
                self._parse_select_file_status_clause(select_stmt)
            
            # RESERVE clause
            elif current_val == "RESERVE":
                self._parse_select_reserve_clause(select_stmt)
            
            # PADDING CHARACTER clause
            elif current_val == "PADDING":
                self._parse_select_padding_clause(select_stmt)
            
            # RECORD DELIMITER clause (already handled RECORD above, check for DELIMITER)
            elif current_val == "DELIMITER":
                # This could be part of RECORD DELIMITER - skip if standalone
                self.advance_token()
            
            # PASSWORD clause
            elif current_val == "PASSWORD":
                self._parse_select_password_clause(select_stmt)
            
            # LOCK MODE clause
            elif current_val == "LOCK":
                self._parse_select_lock_mode_clause(select_stmt)
            
            # SHARING clause
            elif current_val == "SHARING":
                self._parse_select_sharing_clause(select_stmt)
            
            # STATUS (alternative form of FILE STATUS)
            elif current_val == "STATUS":
                # Skip to IS and get the status variable
                self.advance_token()
                if self.current_token and self.current_token.value.upper() == "IS":
                    self.advance_token()
                if self.current_token and self.current_token.type == TokenType.IDENTIFIER:
                    select_stmt.set_file_status(self.current_token.value)
                    self.advance_token()
            
            # Break on start of another SELECT or division/section keywords
            elif current_val in ("SELECT", "DATA", "PROCEDURE", "INPUT-OUTPUT", "CONFIGURATION", "I-O-CONTROL"):
                break
            
            # Skip noise words and unknown tokens
            else:
                self.advance_token()
        
        # Consume period
        if self.current_token and self.current_token.type == TokenType.PERIOD:
            self.advance_token()
        
        # Add SELECT statement to current paragraph
        if self.current_section and hasattr(self.current_section, 'paragraphs') and self.current_section.paragraphs:
            last_paragraph = self.current_section.paragraphs[-1]
            last_paragraph.add_statement(select_stmt)
    
    def _parse_select_assign_clause(self, select_stmt: SelectStatement) -> None:
        """Parse ASSIGN TO clause with device type support."""
        self.advance_token()  # Skip ASSIGN
        
        # Optional TO keyword
        if self.current_token and self.current_token.value.upper() == "TO":
            self.advance_token()
        
        # Skip newlines
        while self.current_token and self.current_token.type == TokenType.NEWLINE:
            self.advance_token()
        
        # Check for device type (DISK, TAPE, PRINTER, etc.)
        # Device types can be followed by an actual file name, or can BE the assignment target
        device_type = None
        device_keywords = {"DISK", "TAPE", "PRINTER", "READER", "PUNCH", "KEYBOARD", 
                          "DISPLAY", "CONSOLE", "DA", "UT", "UR", "EXTERNAL", "DYNAMIC"}
        
        if self.current_token and self.current_token.value.upper() in device_keywords:
            potential_device = self.current_token.value.upper()
            # Peek ahead to see if there's an actual target after the device keyword
            saved_index = self.current_token_index
            self.advance_token()
            
            # Skip newlines to check what's next
            while self.current_token and self.current_token.type == TokenType.NEWLINE:
                self.advance_token()
            
            # If next token is an identifier or string literal, then the keyword was a device type
            # If next token is period or a new clause keyword, then the keyword IS the assignment target
            if (self.current_token and 
                self.current_token.type in (TokenType.IDENTIFIER, TokenType.STRING_LITERAL)):
                # Device keyword followed by actual target
                device_type = potential_device
                if self.current_token.type == TokenType.STRING_LITERAL:
                    assign_to = f'"{self.current_token.value}"'
                else:
                    assign_to = self.current_token.value
                select_stmt.set_assign_to(assign_to, device_type)
                self.advance_token()
            else:
                # Device keyword IS the assignment target (e.g., "ASSIGN TO PRINTER.")
                select_stmt.set_assign_to(potential_device, None)
            return
        
        # Get assignment target (identifier or string literal) - not a device keyword
        if self.current_token and self.current_token.type in (TokenType.IDENTIFIER, TokenType.STRING_LITERAL):
            if self.current_token.type == TokenType.STRING_LITERAL:
                assign_to = f'"{self.current_token.value}"'
            else:
                assign_to = self.current_token.value
            select_stmt.set_assign_to(assign_to, device_type)
            self.advance_token()
    
    def _parse_select_organization_clause(self, select_stmt: SelectStatement) -> None:
        """Parse ORGANIZATION IS clause."""
        self.advance_token()  # Skip ORGANIZATION
        
        # Optional IS keyword
        if self.current_token and self.current_token.value.upper() == "IS":
            self.advance_token()
        
        # Skip newlines
        while self.current_token and self.current_token.type == TokenType.NEWLINE:
            self.advance_token()
        
        # Get organization type
        if self.current_token:
            org_val = self.current_token.value.upper()
            
            # Handle LINE SEQUENTIAL
            if org_val == "LINE":
                self.advance_token()
                if self.current_token and self.current_token.value.upper() == "SEQUENTIAL":
                    select_stmt.set_organization("LINE SEQUENTIAL")
                    self.advance_token()
                else:
                    select_stmt.set_organization("LINE")
            elif org_val in ("SEQUENTIAL", "INDEXED", "RELATIVE"):
                select_stmt.set_organization(org_val)
                self.advance_token()
            else:
                select_stmt.set_organization(org_val)
                self.advance_token()
    
    def _parse_select_access_mode_clause(self, select_stmt: SelectStatement) -> None:
        """Parse ACCESS MODE IS clause."""
        self.advance_token()  # Skip ACCESS
        
        # Optional MODE keyword
        if self.current_token and self.current_token.value.upper() == "MODE":
            self.advance_token()
        
        # Optional IS keyword
        if self.current_token and self.current_token.value.upper() == "IS":
            self.advance_token()
        
        # Skip newlines
        while self.current_token and self.current_token.type == TokenType.NEWLINE:
            self.advance_token()
        
        # Get access mode (SEQUENTIAL, RANDOM, DYNAMIC)
        # Note: these may be tokenized as keywords rather than identifiers
        if self.current_token:
            access_val = self.current_token.value.upper() if self.current_token.value else ""
            if access_val in ("SEQUENTIAL", "RANDOM", "DYNAMIC"):
                select_stmt.set_access_mode(access_val)
                self.advance_token()
    
    def _parse_select_record_key_clause(self, select_stmt: SelectStatement) -> None:
        """Parse RECORD KEY IS clause or RECORD DELIMITER clause."""
        self.advance_token()  # Skip RECORD
        
        if not self.current_token:
            return
        
        next_val = self.current_token.value.upper() if self.current_token.value else ""
        
        # RECORD DELIMITER clause
        if next_val == "DELIMITER":
            self.advance_token()  # Skip DELIMITER
            if self.current_token and self.current_token.value.upper() == "IS":
                self.advance_token()
            if self.current_token:
                if self.current_token.value.upper() == "STANDARD-1":
                    select_stmt.set_record_delimiter("STANDARD-1")
                else:
                    select_stmt.set_record_delimiter(self.current_token.value)
                self.advance_token()
            return
        
        # RECORD KEY clause
        if next_val == "KEY":
            self.advance_token()  # Skip KEY
        
        # Optional IS keyword
        if self.current_token and self.current_token.value.upper() == "IS":
            self.advance_token()
        
        # Skip newlines
        while self.current_token and self.current_token.type == TokenType.NEWLINE:
            self.advance_token()
        
        # Get key data name
        if self.current_token and self.current_token.type == TokenType.IDENTIFIER:
            key_name = self.current_token.value
            self.advance_token()
            
            # Check for SOURCE IS clause (IBM extension)
            source = None
            if self.current_token and self.current_token.value.upper() == "SOURCE":
                self.advance_token()
                if self.current_token and self.current_token.value.upper() == "IS":
                    self.advance_token()
                if self.current_token and self.current_token.type == TokenType.IDENTIFIER:
                    source = self.current_token.value
                    self.advance_token()
            
            select_stmt.set_record_key(key_name, source)
    
    def _parse_select_alternate_key_clause(self, select_stmt: SelectStatement) -> None:
        """Parse ALTERNATE RECORD KEY IS clause."""
        self.advance_token()  # Skip ALTERNATE
        
        # RECORD keyword
        if self.current_token and self.current_token.value.upper() == "RECORD":
            self.advance_token()
        
        # KEY keyword
        if self.current_token and self.current_token.value.upper() == "KEY":
            self.advance_token()
        
        # Optional IS keyword
        if self.current_token and self.current_token.value.upper() == "IS":
            self.advance_token()
        
        # Skip newlines
        while self.current_token and self.current_token.type == TokenType.NEWLINE:
            self.advance_token()
        
        # Get key data name
        if self.current_token and self.current_token.type == TokenType.IDENTIFIER:
            key_name = self.current_token.value
            self.advance_token()
            
            # Check for WITH DUPLICATES
            duplicates_allowed = False
            password = None
            
            while self.current_token:
                word = self.current_token.value.upper() if self.current_token.value else ""
                
                if word == "WITH":
                    self.advance_token()
                    continue
                elif word == "DUPLICATES":
                    duplicates_allowed = True
                    self.advance_token()
                    continue
                elif word == "PASSWORD":
                    self.advance_token()
                    if self.current_token and self.current_token.value.upper() == "IS":
                        self.advance_token()
                    if self.current_token and self.current_token.type == TokenType.IDENTIFIER:
                        password = self.current_token.value
                        self.advance_token()
                    continue
                else:
                    break
            
            select_stmt.add_alternate_key(key_name, duplicates_allowed, password)
    
    def _parse_select_relative_key_clause(self, select_stmt: SelectStatement) -> None:
        """Parse RELATIVE KEY IS clause."""
        self.advance_token()  # Skip RELATIVE
        
        # KEY keyword
        if self.current_token and self.current_token.value.upper() == "KEY":
            self.advance_token()
        
        # Optional IS keyword
        if self.current_token and self.current_token.value.upper() == "IS":
            self.advance_token()
        
        # Skip newlines
        while self.current_token and self.current_token.type == TokenType.NEWLINE:
            self.advance_token()
        
        # Get key data name
        if self.current_token and self.current_token.type == TokenType.IDENTIFIER:
            select_stmt.set_relative_key(self.current_token.value)
            self.advance_token()
    
    def _parse_select_file_status_clause(self, select_stmt: SelectStatement) -> None:
        """Parse FILE STATUS IS clause."""
        current_val = self.current_token.value.upper() if self.current_token.value else ""
        
        if current_val == "FILE":
            self.advance_token()  # Skip FILE
            if self.current_token and self.current_token.value.upper() == "STATUS":
                self.advance_token()
        elif current_val == "FILE-STATUS":
            self.advance_token()  # Skip FILE-STATUS
        
        # Optional IS keyword
        if self.current_token and self.current_token.value.upper() == "IS":
            self.advance_token()
        
        # Skip newlines
        while self.current_token and self.current_token.type == TokenType.NEWLINE:
            self.advance_token()
        
        # Get primary status variable
        if self.current_token and self.current_token.type == TokenType.IDENTIFIER:
            primary_status = self.current_token.value
            self.advance_token()
            
            # Check for second status variable (VSAM)
            vsam_status = None
            if self.current_token and self.current_token.type == TokenType.COMMA:
                self.advance_token()
                if self.current_token and self.current_token.type == TokenType.IDENTIFIER:
                    vsam_status = self.current_token.value
                    self.advance_token()
            
            select_stmt.set_file_status(primary_status, vsam_status)
    
    def _parse_select_reserve_clause(self, select_stmt: SelectStatement) -> None:
        """Parse RESERVE clause."""
        self.advance_token()  # Skip RESERVE
        
        # Get number of areas
        if self.current_token and self.current_token.type in (TokenType.NUMERIC_LITERAL, TokenType.LEVEL_NUMBER):
            areas = int(self.current_token.value)
            select_stmt.set_reserve_areas(areas)
            self.advance_token()
            
            # Optional AREA(S) keyword
            if self.current_token and self.current_token.value.upper() in ("AREA", "AREAS"):
                self.advance_token()
    
    def _parse_select_padding_clause(self, select_stmt: SelectStatement) -> None:
        """Parse PADDING CHARACTER IS clause."""
        self.advance_token()  # Skip PADDING
        
        # CHARACTER keyword
        if self.current_token and self.current_token.value.upper() == "CHARACTER":
            self.advance_token()
        
        # Optional IS keyword
        if self.current_token and self.current_token.value.upper() == "IS":
            self.advance_token()

            if self.current_token.type == TokenType.STRING_LITERAL:
                select_stmt.set_padding_character(f'"{self.current_token.value}"')
            else:
                select_stmt.set_padding_character(self.current_token.value)
            self.advance_token()
    
    def _parse_select_password_clause(self, select_stmt: SelectStatement) -> None:
        """Parse PASSWORD IS clause."""
        self.advance_token()  # Skip PASSWORD
        
        # Optional IS keyword
        if self.current_token and self.current_token.value.upper() == "IS":
            self.advance_token()
        
        # Skip newlines
        while self.current_token and self.current_token.type == TokenType.NEWLINE:
            self.advance_token()
        
        # Get password data name
        if self.current_token and self.current_token.type == TokenType.IDENTIFIER:
            select_stmt.set_password(self.current_token.value)
            self.advance_token()
    
    def _parse_select_lock_mode_clause(self, select_stmt: SelectStatement) -> None:
        """Parse LOCK MODE IS clause."""
        self.advance_token()  # Skip LOCK
        
        # MODE keyword
        if self.current_token and self.current_token.value.upper() == "MODE":
            self.advance_token()
        
        # Optional IS keyword
        if self.current_token and self.current_token.value.upper() == "IS":
            self.advance_token()
        
        # Skip newlines
        while self.current_token and self.current_token.type == TokenType.NEWLINE:
            self.advance_token()
        
        # Get lock mode (MANUAL, AUTOMATIC, EXCLUSIVE)
        if self.current_token and self.current_token.type == TokenType.IDENTIFIER:
            lock_mode = self.current_token.value.upper()
            self.advance_token()
            
            lock_on = None
            with_rollback = False
            
            # Check for WITH LOCK ON clause
            while self.current_token:
                word = self.current_token.value.upper() if self.current_token.value else ""
                
                if word == "WITH":
                    self.advance_token()
                    if self.current_token:
                        next_word = self.current_token.value.upper()
                        if next_word == "LOCK":
                            self.advance_token()
                            if self.current_token and self.current_token.value.upper() == "ON":
                                self.advance_token()
                                # Get lock target (RECORD or MULTIPLE RECORDS)
                                if self.current_token and self.current_token.value.upper() == "MULTIPLE":
                                    self.advance_token()
                                    if self.current_token and self.current_token.value.upper() == "RECORDS":
                                        lock_on = "MULTIPLE RECORDS"
                                        self.advance_token()
                                elif self.current_token and self.current_token.value.upper() == "RECORD":
                                    lock_on = "RECORD"
                                    self.advance_token()
                        elif next_word == "ROLLBACK":
                            with_rollback = True
                            self.advance_token()
                        else:
                            break
                else:
                    break
            
            select_stmt.set_lock_mode(lock_mode, lock_on, with_rollback)
    
    def _parse_select_sharing_clause(self, select_stmt: SelectStatement) -> None:
        """Parse SHARING WITH clause."""
        self.advance_token()  # Skip SHARING
        
        # Optional WITH keyword
        if self.current_token and self.current_token.value.upper() == "WITH":
            self.advance_token()
        
        # Skip newlines
        while self.current_token and self.current_token.type == TokenType.NEWLINE:
            self.advance_token()
        
        # Get sharing mode
        if self.current_token:
            sharing_val = self.current_token.value.upper()
            
            if sharing_val == "ALL":
                self.advance_token()
                # Optional OTHER
                if self.current_token and self.current_token.value.upper() == "OTHER":
                    self.advance_token()
                select_stmt.set_sharing_mode("ALL OTHER")
            elif sharing_val == "NO":
                self.advance_token()
                # OTHER
                if self.current_token and self.current_token.value.upper() == "OTHER":
                    self.advance_token()
                select_stmt.set_sharing_mode("NO OTHER")
            elif sharing_val == "READ":
                self.advance_token()
                # ONLY
                if self.current_token and self.current_token.value.upper() == "ONLY":
                    self.advance_token()
                select_stmt.set_sharing_mode("READ ONLY")
            elif sharing_val == "READ-ONLY":
                select_stmt.set_sharing_mode("READ ONLY")
                self.advance_token()
            else:
                select_stmt.set_sharing_mode(sharing_val)
                self.advance_token()
    
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
            loc = self.get_current_location()
            self.add_error(ParseError(
                "Expected SECTION after WORKING-STORAGE",
                loc.line, loc.column
            ))
            return
        
        if not self.expect_token(TokenType.PERIOD):
            return
        
        # Create working storage section
        ws_section = CobolSection("WORKING-STORAGE", self.get_current_location())
        self._set_node_context(ws_section)
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
        self._set_node_context(ls_section)
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
        self._set_node_context(linkage_section)
        if self.current_division:
            self.current_division.add_section(linkage_section)
        self.current_section = linkage_section
        
        # Parse data items
        self.parse_data_items()
    
    def parse_file_section(self) -> None:
        """Parse FILE SECTION with FD and SD records."""
        if not self.match_token(TokenType.IDENTIFIER):  # SECTION keyword
            return
        
        if not self.expect_token(TokenType.PERIOD):
            return
        
        # Create file section
        file_section = CobolSection("FILE", self.get_current_location())
        self._set_node_context(file_section)
        if self.current_division:
            self.current_division.add_section(file_section)
        self.current_section = file_section
        
        # Parse FD/SD records and data items
        while self.current_token and self.current_token.type not in [
            TokenType.PROCEDURE_DIVISION, TokenType.WORKING_STORAGE_SECTION,
            TokenType.LOCAL_STORAGE_SECTION, TokenType.LINKAGE_SECTION, TokenType.EOF
        ]:
            if self.current_token and self.current_token.value:
                record_type = self.current_token.value.upper()
                if record_type == "FD":
                    self.parse_fd_record("FD")
                elif record_type == "SD":
                    self.parse_fd_record("SD")
                elif self.current_token.type == TokenType.LEVEL_NUMBER:
                    self.parse_data_item()
                else:
                    # Skip newlines and other tokens
                    if not self.match_token(TokenType.NEWLINE):
                        self.advance_token()
            else:
                self.advance_token()
    
    def parse_fd_record(self, record_type: str = "FD") -> None:
        """Parse FD (File Description) or SD (Sort Description) record.
        
        Supports comprehensive FD/SD clause variations:
        - EXTERNAL/GLOBAL attributes
        - BLOCK CONTAINS clause
        - RECORD CONTAINS clause (fixed and variable)
        - LABEL RECORDS clause
        - VALUE OF clause
        - DATA RECORD(S) clause
        - LINAGE clause with FOOTING and TOP/BOTTOM
        - CODE-SET clause
        - RECORDING MODE clause
        - REPORT IS clause (Report Writer)
        """
        if not self.current_token or self.current_token.value.upper() not in ("FD", "SD"):
            return
        
        location = self.current_token.location
        actual_type = self.current_token.value.upper()
        self.advance_token()  # Skip FD/SD
        
        # Skip newlines
        while self.current_token and self.current_token.type == TokenType.NEWLINE:
            self.advance_token()
        
        # Get file name
        if not self.current_token or self.current_token.type != TokenType.IDENTIFIER:
            self.add_error(self.create_error(f"Expected file name after {actual_type}"))
            return
        
        file_name = self.current_token.value
        self.advance_token()
        
        # Create FD/SD record
        fd_record = CobolFileDescription(file_name, location, actual_type)
        
        # Parse clauses until period
        while self.current_token and self.current_token.type != TokenType.PERIOD:
            # Skip newlines between clauses
            while self.current_token and self.current_token.type == TokenType.NEWLINE:
                self.advance_token()
            
            if not self.current_token or self.current_token.type == TokenType.PERIOD:
                break
            
            current_val = self.current_token.value.upper() if self.current_token.value else ""
            
            # EXTERNAL attribute
            if current_val == "EXTERNAL":
                fd_record.set_external(True)
                self.advance_token()
            
            # GLOBAL attribute
            elif current_val == "GLOBAL":
                fd_record.set_global(True)
                self.advance_token()
            
            # IS keyword (noise word)
            elif current_val == "IS":
                self.advance_token()
            
            # BLOCK CONTAINS clause
            elif current_val == "BLOCK":
                self._parse_fd_block_contains(fd_record)
            
            # RECORD clause (CONTAINS or IS VARYING)
            elif current_val == "RECORD":
                self._parse_fd_record_contains(fd_record)
            
            # LABEL RECORDS clause
            elif current_val == "LABEL":
                self._parse_fd_label_records(fd_record)
            
            # VALUE OF clause
            elif current_val == "VALUE":
                self._parse_fd_value_of(fd_record)
            
            # DATA RECORD(S) clause
            elif current_val == "DATA":
                self._parse_fd_data_records(fd_record)
            
            # LINAGE clause
            elif current_val == "LINAGE":
                self._parse_fd_linage(fd_record)
            
            # CODE-SET clause
            elif current_val == "CODE-SET":
                self._parse_fd_code_set(fd_record)
            
            # RECORDING MODE clause
            elif current_val == "RECORDING":
                self._parse_fd_recording_mode(fd_record)
            
            # REPORT IS clause
            elif current_val == "REPORT":
                self._parse_fd_report(fd_record)
            
            # Skip unknown clauses/tokens
            else:
                self.advance_token()
        
        # Consume period
        if self.current_token and self.current_token.type == TokenType.PERIOD:
            self.advance_token()
        
        # Add FD/SD to current section
        if self.current_section:
            self.current_section.add_child(fd_record)
    
    def _parse_fd_block_contains(self, fd_record: CobolFileDescription) -> None:
        """Parse BLOCK CONTAINS clause."""
        self.advance_token()  # Skip BLOCK
        
        # CONTAINS keyword
        if self.current_token and self.current_token.value.upper() == "CONTAINS":
            self.advance_token()
        
        # Skip newlines
        while self.current_token and self.current_token.type == TokenType.NEWLINE:
            self.advance_token()
        
        # Get first number
        if self.current_token and self.current_token.type in (TokenType.NUMERIC_LITERAL, TokenType.LEVEL_NUMBER):
            first_num = int(self.current_token.value)
            self.advance_token()
            
            # Check for TO (range)
            if self.current_token and self.current_token.value.upper() == "TO":
                self.advance_token()
                if self.current_token and self.current_token.type in (TokenType.NUMERIC_LITERAL, TokenType.LEVEL_NUMBER):
                    second_num = int(self.current_token.value)
                    self.advance_token()
                    
                    # Get unit (RECORDS or CHARACTERS)
                    unit = None
                    if self.current_token and self.current_token.value.upper() in ("RECORDS", "CHARACTERS"):
                        unit = self.current_token.value.upper()
                        self.advance_token()
                    
                    fd_record.set_block_contains(min_count=first_num, max_count=second_num, unit=unit)
                else:
                    fd_record.set_block_contains(count=first_num)
            else:
                # Get unit (RECORDS or CHARACTERS)
                unit = None
                if self.current_token and self.current_token.value.upper() in ("RECORDS", "CHARACTERS"):
                    unit = self.current_token.value.upper()
                    self.advance_token()
                
                fd_record.set_block_contains(count=first_num, unit=unit)
    
    def _parse_fd_record_contains(self, fd_record: CobolFileDescription) -> None:
        """Parse RECORD CONTAINS or RECORD IS VARYING clause."""
        self.advance_token()  # Skip RECORD
        
        # Skip newlines
        while self.current_token and self.current_token.type == TokenType.NEWLINE:
            self.advance_token()
        
        if not self.current_token:
            return
        
        current_val = self.current_token.value.upper() if self.current_token.value else ""
        
        # RECORD CONTAINS clause
        if current_val == "CONTAINS":
            self.advance_token()
            
            # Skip newlines
            while self.current_token and self.current_token.type == TokenType.NEWLINE:
                self.advance_token()
            
            # Get first number
            if self.current_token and self.current_token.type in (TokenType.NUMERIC_LITERAL, TokenType.LEVEL_NUMBER):
                first_num = int(self.current_token.value)
                self.advance_token()
                
                # Check for TO (variable length)
                if self.current_token and self.current_token.value.upper() == "TO":
                    self.advance_token()
                    if self.current_token and self.current_token.type in (TokenType.NUMERIC_LITERAL, TokenType.LEVEL_NUMBER):
                        second_num = int(self.current_token.value)
                        self.advance_token()
                        
                        # Skip CHARACTERS keyword
                        if self.current_token and self.current_token.value.upper() == "CHARACTERS":
                            self.advance_token()
                        
                        # Check for DEPENDING ON
                        depending_on = None
                        if self.current_token and self.current_token.value.upper() == "DEPENDING":
                            self.advance_token()
                            if self.current_token and self.current_token.value.upper() == "ON":
                                self.advance_token()
                            if self.current_token and self.current_token.type == TokenType.IDENTIFIER:
                                depending_on = self.current_token.value
                                self.advance_token()
                        
                        fd_record.set_record_contains(min_count=first_num, max_count=second_num, depending_on=depending_on)
                else:
                    # Skip CHARACTERS keyword
                    if self.current_token and self.current_token.value.upper() == "CHARACTERS":
                        self.advance_token()
                    
                    fd_record.set_record_contains(count=first_num)
        
        # RECORD IS VARYING clause
        elif current_val == "IS":
            self.advance_token()  # Skip IS
            
            if self.current_token and self.current_token.value.upper() == "VARYING":
                self.advance_token()
                
                # IN SIZE (optional)
                if self.current_token and self.current_token.value.upper() == "IN":
                    self.advance_token()
                    if self.current_token and self.current_token.value.upper() == "SIZE":
                        self.advance_token()
                
                # FROM min TO max
                min_size = None
                max_size = None
                depending_on = None
                
                if self.current_token and self.current_token.value.upper() == "FROM":
                    self.advance_token()
                    if self.current_token and self.current_token.type in (TokenType.NUMERIC_LITERAL, TokenType.LEVEL_NUMBER):
                        min_size = int(self.current_token.value)
                        self.advance_token()
                
                if self.current_token and self.current_token.value.upper() == "TO":
                    self.advance_token()
                    if self.current_token and self.current_token.type in (TokenType.NUMERIC_LITERAL, TokenType.LEVEL_NUMBER):
                        max_size = int(self.current_token.value)
                        self.advance_token()
                
                # Skip CHARACTERS keyword
                if self.current_token and self.current_token.value.upper() == "CHARACTERS":
                    self.advance_token()
                
                # DEPENDING ON
                if self.current_token and self.current_token.value.upper() == "DEPENDING":
                    self.advance_token()
                    if self.current_token and self.current_token.value.upper() == "ON":
                        self.advance_token()
                    if self.current_token and self.current_token.type == TokenType.IDENTIFIER:
                        depending_on = self.current_token.value
                        self.advance_token()
                
                if min_size is not None and max_size is not None:
                    fd_record.set_record_contains(min_count=min_size, max_count=max_size, depending_on=depending_on)
    
    def _parse_fd_label_records(self, fd_record: CobolFileDescription) -> None:
        """Parse LABEL RECORDS clause."""
        self.advance_token()  # Skip LABEL
        
        # RECORD or RECORDS keyword
        if self.current_token and self.current_token.value.upper() in ("RECORD", "RECORDS"):
            self.advance_token()
        
        # IS or ARE keyword
        if self.current_token and self.current_token.value.upper() in ("IS", "ARE"):
            self.advance_token()
        
        # Skip newlines
        while self.current_token and self.current_token.type == TokenType.NEWLINE:
            self.advance_token()
        
        # Get label records value (STANDARD, OMITTED, or data-name)
        if self.current_token:
            label_val = self.current_token.value.upper()
            if label_val in ("STANDARD", "OMITTED"):
                fd_record.set_label_records(label_val)
            else:
                fd_record.set_label_records(self.current_token.value)
            self.advance_token()
    
    def _parse_fd_value_of(self, fd_record: CobolFileDescription) -> None:
        """Parse VALUE OF clause."""
        self.advance_token()  # Skip VALUE
        
        # OF keyword
        if self.current_token and self.current_token.value.upper() == "OF":
            self.advance_token()
        
        # Skip newlines
        while self.current_token and self.current_token.type == TokenType.NEWLINE:
            self.advance_token()
        
        # Parse system-name IS data-name/literal pairs
        while self.current_token and self.current_token.type == TokenType.IDENTIFIER:
            system_name = self.current_token.value
            self.advance_token()
            
            # IS keyword
            if self.current_token and self.current_token.value.upper() == "IS":
                self.advance_token()
            
            # Get value (data-name or literal)
            if self.current_token:
                if self.current_token.type == TokenType.STRING_LITERAL:
                    value = f'"{self.current_token.value}"'
                else:
                    value = self.current_token.value
                fd_record.add_value_of(system_name, value)
                self.advance_token()
            
            # Skip comma if present
            if self.current_token and self.current_token.type == TokenType.COMMA:
                self.advance_token()
            
            # Skip newlines
            while self.current_token and self.current_token.type == TokenType.NEWLINE:
                self.advance_token()
            
            # Check if next token starts a new clause
            if self.current_token and self.current_token.value:
                next_val = self.current_token.value.upper()
                if next_val in ("DATA", "LABEL", "RECORD", "BLOCK", "LINAGE", "CODE-SET", "RECORDING", "REPORT", "EXTERNAL", "GLOBAL"):
                    break
    
    def _parse_fd_data_records(self, fd_record: CobolFileDescription) -> None:
        """Parse DATA RECORD(S) clause."""
        self.advance_token()  # Skip DATA
        
        # RECORD or RECORDS keyword
        if self.current_token and self.current_token.value.upper() in ("RECORD", "RECORDS"):
            self.advance_token()
        
        # IS or ARE keyword
        if self.current_token and self.current_token.value.upper() in ("IS", "ARE"):
            self.advance_token()
        
        # Skip newlines
        while self.current_token and self.current_token.type == TokenType.NEWLINE:
            self.advance_token()
        
        # Get record names
        while self.current_token and self.current_token.type == TokenType.IDENTIFIER:
            # Check if this is a clause keyword
            name_val = self.current_token.value.upper()
            if name_val in ("LABEL", "VALUE", "BLOCK", "RECORD", "LINAGE", "CODE-SET", "RECORDING", "REPORT", "EXTERNAL", "GLOBAL"):
                break
            
            fd_record.add_data_record_name(self.current_token.value)
            self.advance_token()
            
            # Skip comma if present
            if self.current_token and self.current_token.type == TokenType.COMMA:
                self.advance_token()
            
            # Skip newlines
            while self.current_token and self.current_token.type == TokenType.NEWLINE:
                self.advance_token()
    
    def _parse_fd_linage(self, fd_record: CobolFileDescription) -> None:
        """Parse LINAGE clause with FOOTING and TOP/BOTTOM."""
        self.advance_token()  # Skip LINAGE
        
        # IS keyword
        if self.current_token and self.current_token.value.upper() == "IS":
            self.advance_token()
        
        # Skip newlines
        while self.current_token and self.current_token.type == TokenType.NEWLINE:
            self.advance_token()
        
        # Get linage value (number or data-name)
        linage_value = None
        if self.current_token:
            if self.current_token.type in (TokenType.NUMERIC_LITERAL, TokenType.LEVEL_NUMBER):
                # Strip trailing period if present (lexer may include it)
                val_str = self.current_token.value.rstrip('.')
                linage_value = int(val_str) if val_str else 0
            else:
                linage_value = self.current_token.value
            self.advance_token()
        
        # LINES keyword (optional)
        if self.current_token and self.current_token.value.upper() == "LINES":
            self.advance_token()
        
        # Parse optional clauses
        footing = None
        top = None
        bottom = None
        
        while self.current_token:
            # Skip newlines
            while self.current_token and self.current_token.type == TokenType.NEWLINE:
                self.advance_token()
            
            if not self.current_token or self.current_token.type == TokenType.PERIOD:
                break
            
            current_val = self.current_token.value.upper() if self.current_token.value else ""
            
            # WITH FOOTING AT
            if current_val == "WITH":
                self.advance_token()
                continue
            elif current_val == "FOOTING":
                self.advance_token()
                if self.current_token and self.current_token.value.upper() == "AT":
                    self.advance_token()
                if self.current_token:
                    if self.current_token.type in (TokenType.NUMERIC_LITERAL, TokenType.LEVEL_NUMBER):
                        val_str = self.current_token.value.rstrip('.')
                        footing = int(val_str) if val_str else 0
                    else:
                        footing = self.current_token.value
                    self.advance_token()
            
            # LINES AT TOP
            elif current_val == "LINES":
                self.advance_token()
                if self.current_token and self.current_token.value.upper() == "AT":
                    self.advance_token()
                    if self.current_token and self.current_token.value.upper() == "TOP":
                        self.advance_token()
                        if self.current_token:
                            if self.current_token.type in (TokenType.NUMERIC_LITERAL, TokenType.LEVEL_NUMBER):
                                val_str = self.current_token.value.rstrip('.')
                                top = int(val_str) if val_str else 0
                            else:
                                top = self.current_token.value
                            self.advance_token()
                    elif self.current_token and self.current_token.value.upper() == "BOTTOM":
                        self.advance_token()
                        if self.current_token:
                            if self.current_token.type in (TokenType.NUMERIC_LITERAL, TokenType.LEVEL_NUMBER):
                                val_str = self.current_token.value.rstrip('.')
                                bottom = int(val_str) if val_str else 0
                            else:
                                bottom = self.current_token.value
                            self.advance_token()
            
            # AT TOP / AT BOTTOM
            elif current_val == "AT":
                self.advance_token()
                continue
            elif current_val == "TOP":
                self.advance_token()
                if self.current_token:
                    if self.current_token.type in (TokenType.NUMERIC_LITERAL, TokenType.LEVEL_NUMBER):
                        val_str = self.current_token.value.rstrip('.')
                        top = int(val_str) if val_str else 0
                    else:
                        top = self.current_token.value
                    self.advance_token()
            elif current_val == "BOTTOM":
                self.advance_token()
                if self.current_token:
                    if self.current_token.type in (TokenType.NUMERIC_LITERAL, TokenType.LEVEL_NUMBER):
                        val_str = self.current_token.value.rstrip('.')
                        bottom = int(val_str) if val_str else 0
                    else:
                        bottom = self.current_token.value
                    self.advance_token()
            
            # Check for next clause
            elif current_val in ("DATA", "LABEL", "VALUE", "BLOCK", "RECORD", "CODE-SET", "RECORDING", "REPORT", "EXTERNAL", "GLOBAL"):
                break
            else:
                break
        
        fd_record.set_linage(linage_value, footing, top, bottom)
    
    def _parse_fd_code_set(self, fd_record: CobolFileDescription) -> None:
        """Parse CODE-SET clause."""
        self.advance_token()  # Skip CODE-SET
        
        # IS keyword
        if self.current_token and self.current_token.value.upper() == "IS":
            self.advance_token()
        
        # Skip newlines
        while self.current_token and self.current_token.type == TokenType.NEWLINE:
            self.advance_token()
        
        # Get code set name
        if self.current_token and self.current_token.type == TokenType.IDENTIFIER:
            code_set = self.current_token.value
            self.advance_token()
            
            # Check for FOR clause (IBM extension)
            for_alphanumeric = None
            for_national = None
            
            while self.current_token and self.current_token.value.upper() == "FOR":
                self.advance_token()
                if self.current_token:
                    for_type = self.current_token.value.upper()
                    if for_type == "ALPHANUMERIC":
                        self.advance_token()
                        if self.current_token and self.current_token.type == TokenType.IDENTIFIER:
                            for_alphanumeric = self.current_token.value
                            self.advance_token()
                    elif for_type == "NATIONAL":
                        self.advance_token()
                        if self.current_token and self.current_token.type == TokenType.IDENTIFIER:
                            for_national = self.current_token.value
                            self.advance_token()
            
            fd_record.set_code_set(code_set, for_alphanumeric, for_national)
    
    def _parse_fd_recording_mode(self, fd_record: CobolFileDescription) -> None:
        """Parse RECORDING MODE clause."""
        self.advance_token()  # Skip RECORDING
        
        # MODE keyword
        if self.current_token and self.current_token.value.upper() == "MODE":
            self.advance_token()
        
        # IS keyword
        if self.current_token and self.current_token.value.upper() == "IS":
            self.advance_token()
        
        # Skip newlines
        while self.current_token and self.current_token.type == TokenType.NEWLINE:
            self.advance_token()
        
        # Get recording mode (F, V, U, S)
        if self.current_token:
            fd_record.set_recording_mode(self.current_token.value)
            self.advance_token()
    
    def _parse_fd_report(self, fd_record: CobolFileDescription) -> None:
        """Parse REPORT IS clause."""
        self.advance_token()  # Skip REPORT
        
        # IS or ARE keyword
        if self.current_token and self.current_token.value.upper() in ("IS", "ARE"):
            self.advance_token()
        
        # Skip newlines
        while self.current_token and self.current_token.type == TokenType.NEWLINE:
            self.advance_token()
        
        # Get report names
        while self.current_token and self.current_token.type == TokenType.IDENTIFIER:
            # Check if this is a clause keyword
            name_val = self.current_token.value.upper()
            if name_val in ("LABEL", "VALUE", "DATA", "BLOCK", "RECORD", "LINAGE", "CODE-SET", "RECORDING", "EXTERNAL", "GLOBAL"):
                break
            
            fd_record.add_report_name(self.current_token.value)
            self.advance_token()
            
            # Skip comma if present
            if self.current_token and self.current_token.type == TokenType.COMMA:
                self.advance_token()
            
            # Skip newlines
            while self.current_token and self.current_token.type == TokenType.NEWLINE:
                self.advance_token()
    
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
        self._set_node_context(data_item)
        
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
                    # If the period was consumed by PICTURE parsing, exit the clause loop
                    if period_consumed_by_picture:
                        break
            
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
                            # Note: Token doesn't have source_line attribute, skip this check
                            # if hasattr(next_token, 'source_line') and next_token.source_line[6] == '-':
                            #     string_value += next_token.value
                            #     self.current_token_index += 1
                            #     end_quote_found = '"' in next_token.value
                            # else:
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
            return None, self.get_current_location(), False
        
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
            loc = self.get_current_location()
            self.add_error(ParseError(
                "Expected DIVISION after PROCEDURE",
                loc.line, loc.column
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
        # Reset current_section so procedure statements go to the right place
        self.current_section = None
        
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
                      next_token.value.upper() == "SECTION"):
                    peek2 = self.peek_token(2)
                    if peek2 and peek2.type == TokenType.PERIOD:
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
            self._set_node_context(implicit)
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
            if ttype == TokenType.CALL or upper_val == 'CALL':
                i = self._parse_call_inline(tokens, i)
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
            # Handle EXEC SQL blocks
            if ttype == TokenType.EXEC or upper_val == 'EXEC':
                i = self._parse_exec_inline(tokens, i)
                continue
            # Unrecognized inside sentence: skip token
            i += 1

    def _skip_to_next_verb(self, tokens, start):
        verbs = {TokenType.MOVE, TokenType.PERFORM, TokenType.DISPLAY, TokenType.CALL, TokenType.WRITE, TokenType.GO, TokenType.GOTO, TokenType.IF, TokenType.EXEC}
        i = start
        while i < len(tokens) and tokens[i].type not in verbs:
            i += 1
        return i

    def _parse_exec_inline(self, tokens, i):
        """Parse EXEC SQL, EXEC CICS, or EXEC IMS block inline."""
        start = tokens[i]
        i += 1  # Move past EXEC token
        
        if i >= len(tokens):
            return i
        
        # Skip any newlines/comments
        while i < len(tokens) and tokens[i].type in (TokenType.NEWLINE, TokenType.COMMENT):
            i += 1
        
        if i >= len(tokens):
            return i
        
        # Determine EXEC type (SQL, CICS, IMS)
        exec_type = tokens[i].value.upper() if tokens[i].value else ""
        
        if exec_type == "SQL":
            i += 1  # Move past SQL token
            return self._parse_exec_sql_inline(tokens, i, start)
        elif exec_type == "CICS":
            i += 1  # Move past CICS token
            return self._parse_exec_cics_inline(tokens, i, start)
        elif exec_type == "IMS":
            i += 1  # Move past IMS token
            return self._parse_exec_ims_inline(tokens, i, start)
        else:
            # Unknown EXEC type - skip to END-EXEC
            return self._skip_to_end_exec(tokens, i)
    
    def _parse_exec_sql_inline(self, tokens, i, start_token):
        """Parse EXEC SQL block content and create ExecSQLStatement."""
        sql_tokens = []
        
        # Skip any leading newlines/comments
        while i < len(tokens) and tokens[i].type in (TokenType.NEWLINE, TokenType.COMMENT):
            i += 1
        
        # Collect all tokens until END-EXEC
        while i < len(tokens):
            tok = tokens[i]
            
            # Check for END-EXEC (can be one token or two)
            if tok.type == TokenType.END_EXEC or tok.value.upper() == "END-EXEC":
                i += 1  # Move past END-EXEC
                break
            # Handle END EXEC as two separate tokens
            if tok.value.upper() == "END":
                if i + 1 < len(tokens) and tokens[i + 1].value.upper() == "EXEC":
                    i += 2  # Move past END EXEC
                    break
            
            # Skip NEWLINE but preserve for multi-line SQL formatting
            if tok.type == TokenType.NEWLINE:
                sql_tokens.append(" ")  # Replace newline with space for SQL
            elif tok.type == TokenType.COMMENT:
                # Skip inline comments within SQL
                pass
            else:
                sql_tokens.append(tok.value if tok.value else "")
            
            i += 1
        
        # Build SQL text
        sql_text = " ".join(str(t) for t in sql_tokens if t)
        sql_text = " ".join(sql_text.split())  # Normalize whitespace
        
        # Create SQL statement node
        sql_stmt = parse_exec_sql(sql_text, start_token.location)
        
        # Add to current section
        if self.current_section:
            self.current_section.add_child(sql_stmt)
        
        return i
    
    def _parse_exec_cics_inline(self, tokens, i, start_token):
        """Parse EXEC CICS block content."""
        from .dialects.ibm_enterprise import ExecCICSStatement
        
        cics_tokens = []
        
        # Skip any leading newlines/comments
        while i < len(tokens) and tokens[i].type in (TokenType.NEWLINE, TokenType.COMMENT):
            i += 1
        
        # Collect all tokens until END-EXEC
        while i < len(tokens):
            tok = tokens[i]
            
            if tok.type == TokenType.END_EXEC or tok.value.upper() == "END-EXEC":
                i += 1
                break
            if tok.value.upper() == "END":
                if i + 1 < len(tokens) and tokens[i + 1].value.upper() == "EXEC":
                    i += 2
                    break
            
            if tok.type not in (TokenType.NEWLINE, TokenType.COMMENT):
                cics_tokens.append(tok.value if tok.value else "")
            
            i += 1
        
        # Build CICS text and parse
        cics_text = " ".join(cics_tokens)
        
        cics_stmt = ExecCICSStatement(start_token.location)
        if cics_tokens:
            cics_stmt.set_command(cics_tokens[0])
            # Parse options
            j = 1
            while j < len(cics_tokens):
                option = cics_tokens[j]
                if '(' in option:
                    opt_name, opt_value = option.split('(', 1)
                    opt_value = opt_value.rstrip(')')
                    cics_stmt.add_option(opt_name, opt_value)
                else:
                    cics_stmt.add_option(option)
                j += 1
        
        if self.current_section:
            self.current_section.add_child(cics_stmt)
        
        return i
    
    def _parse_exec_ims_inline(self, tokens, i, start_token):
        """Parse EXEC IMS block content."""
        from .dialects.ibm_enterprise import ExecIMSStatement
        
        ims_tokens = []
        
        # Skip any leading newlines/comments
        while i < len(tokens) and tokens[i].type in (TokenType.NEWLINE, TokenType.COMMENT):
            i += 1
        
        # Collect all tokens until END-EXEC
        while i < len(tokens):
            tok = tokens[i]
            
            if tok.type == TokenType.END_EXEC or tok.value.upper() == "END-EXEC":
                i += 1
                break
            if tok.value.upper() == "END":
                if i + 1 < len(tokens) and tokens[i + 1].value.upper() == "EXEC":
                    i += 2
                    break
            
            if tok.type not in (TokenType.NEWLINE, TokenType.COMMENT):
                ims_tokens.append(tok.value if tok.value else "")
            
            i += 1
        
        # Build IMS text and parse
        ims_stmt = ExecIMSStatement(start_token.location)
        if ims_tokens:
            ims_stmt.set_command(ims_tokens[0])
            # Parse options
            j = 1
            while j < len(ims_tokens):
                option = ims_tokens[j]
                if '(' in option:
                    opt_name, opt_value = option.split('(', 1)
                    opt_value = opt_value.rstrip(')')
                    ims_stmt.add_option(opt_name, opt_value)
                else:
                    ims_stmt.add_option(option)
                j += 1
        
        if self.current_section:
            self.current_section.add_child(ims_stmt)
        
        return i
    
    def _skip_to_end_exec(self, tokens, i):
        """Skip to END-EXEC token."""
        while i < len(tokens):
            tok = tokens[i]
            if tok.type == TokenType.END_EXEC or tok.value.upper() == "END-EXEC":
                return i + 1
            if tok.value.upper() == "END":
                if i + 1 < len(tokens) and tokens[i + 1].value.upper() == "EXEC":
                    return i + 2
            i += 1
        return i

    def _parse_move_inline(self, tokens, i):
        # i points to the MOVE token
        start = tokens[i]
        i += 1  # Move past MOVE token
        
        if i >= len(tokens):
            # MOVE at end of token stream - add error and return
            self.add_error(ParseError("Expected source operand in MOVE statement (no more tokens)", location=start.location))
            return i
        
        # Skip optional separators before source (multi-line MOVE support)
        while i < len(tokens) and tokens[i].type in (TokenType.NEWLINE, TokenType.COMMENT, TokenType.CONTINUATION):
            i += 1
            
        if i >= len(tokens):
            # Still no tokens after skipping separators - add error and return
            self.add_error(ParseError("Expected source operand in MOVE statement (no more tokens)", location=start.location))
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
                self.add_error(ParseError(f"Expected number after {sign_token.value} in MOVE statement (no more tokens)", location=start.location))
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
                self.add_error(ParseError(f"Expected number after {sign_token.value} in MOVE statement (found {tokens[i].type.name})", location=start.location))
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
            self.add_error(ParseError("Expected source operand in MOVE statement (no more tokens)", location=start.location))
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
                self.add_error(ParseError(debug_info, location=start.location))
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

    def _parse_call_inline(self, tokens, i):
        """Parse CALL statement from inline tokens."""
        start = tokens[i]
        i += 1  # Move past CALL token
        
        if i >= len(tokens):
            return i
        
        call_stmt = CallStatement(start.location)
        
        # Skip optional whitespace/newlines
        while i < len(tokens) and tokens[i].type in (TokenType.NEWLINE, TokenType.COMMENT):
            i += 1
        
        if i >= len(tokens):
            return i
        
        # Get program name (literal or identifier)
        program_name = tokens[i].value
        is_dynamic = tokens[i].type == TokenType.IDENTIFIER
        
        # For string literals, keep the quotes
        if tokens[i].type == TokenType.STRING_LITERAL:
            program_name = f'"{program_name}"'
        
        call_stmt.set_called_program(program_name, is_dynamic)
        i += 1
        
        # Skip optional whitespace/newlines
        while i < len(tokens) and tokens[i].type in (TokenType.NEWLINE, TokenType.COMMENT):
            i += 1
        
        # Parse optional USING clause
        if i < len(tokens) and tokens[i].type == TokenType.IDENTIFIER and \
           tokens[i].value.upper() == "USING":
            i += 1
            i = self._parse_call_using_parameters_inline(tokens, i, call_stmt)
        
        # Skip optional whitespace/newlines
        while i < len(tokens) and tokens[i].type in (TokenType.NEWLINE, TokenType.COMMENT):
            i += 1
        
        # Parse optional RETURNING clause
        if i < len(tokens) and tokens[i].type == TokenType.IDENTIFIER and \
           tokens[i].value.upper() == "RETURNING":
            i += 1
            
            # Skip optional whitespace/newlines
            while i < len(tokens) and tokens[i].type in (TokenType.NEWLINE, TokenType.COMMENT):
                i += 1
            
            if i < len(tokens) and tokens[i].type == TokenType.IDENTIFIER:
                call_stmt.set_returning_parameter(tokens[i].value)
                i += 1
        
        # Skip optional whitespace/newlines
        while i < len(tokens) and tokens[i].type in (TokenType.NEWLINE, TokenType.COMMENT):
            i += 1
        
        # Parse optional ON EXCEPTION/OVERFLOW clauses
        if i < len(tokens) and tokens[i].type == TokenType.IDENTIFIER and \
           tokens[i].value.upper() == "ON":
            i += 1
            
            # Skip optional whitespace/newlines
            while i < len(tokens) and tokens[i].type in (TokenType.NEWLINE, TokenType.COMMENT):
                i += 1
            
            if i < len(tokens) and tokens[i].type == TokenType.IDENTIFIER:
                exception_type = tokens[i].value.upper()
                
                if exception_type in ("EXCEPTION", "OVERFLOW"):
                    i += 1
                    
                    # Skip statements until END-CALL
                    exception_statements = []
                    while i < len(tokens):
                        # Check for END-CALL
                        if tokens[i].type == TokenType.IDENTIFIER and \
                           tokens[i].value.upper() == "END-CALL":
                            i += 1
                            break
                        
                        # Skip tokens in the exception handler
                        i += 1
                    
                    # Store which type of exception handler we found
                    if exception_type == "EXCEPTION":
                        call_stmt.on_exception = exception_statements
                    else:
                        call_stmt.on_overflow = exception_statements
        
        if self.current_section:
            self.current_section.add_child(call_stmt)
        
        return i
    
    def _parse_call_using_parameters_inline(self, tokens, i, call_stmt):
        """Parse USING clause parameters for inline CALL statement."""
        current_mode = "REFERENCE"  # Default mode
        
        while i < len(tokens):
            # Skip whitespace/newlines
            while i < len(tokens) and tokens[i].type in (TokenType.NEWLINE, TokenType.COMMENT):
                i += 1
            
            if i >= len(tokens):
                break
            
            # Check for RETURNING, ON (exception/overflow) - end of USING clause
            if tokens[i].type == TokenType.IDENTIFIER:
                upper_val = tokens[i].value.upper()
                
                if upper_val in ("RETURNING", "ON"):
                    break
                
                # Check for BY keyword (parameter passing mode)
                if upper_val == "BY":
                    i += 1
                    
                    # Skip whitespace/newlines
                    while i < len(tokens) and tokens[i].type in (TokenType.NEWLINE, TokenType.COMMENT):
                        i += 1
                    
                    if i < len(tokens) and tokens[i].type == TokenType.IDENTIFIER:
                        mode = tokens[i].value.upper()
                        if mode in ("REFERENCE", "CONTENT", "VALUE"):
                            current_mode = mode
                            i += 1
                            
                            # Skip whitespace/newlines
                            while i < len(tokens) and tokens[i].type in (TokenType.NEWLINE, TokenType.COMMENT):
                                i += 1
                            
                            continue
                
                # This must be a parameter name
                param_name = tokens[i].value
                call_stmt.add_using_parameter(param_name, current_mode)
                i += 1
            else:
                # End of USING clause
                break
        
        return i

    def _parse_perform_inline(self, tokens, i):
        """Parse PERFORM statement inline (sentence-level parsing).
        
        Handles:
        - PERFORM paragraph-name
        - PERFORM VARYING variable FROM value BY value UNTIL condition ... END-PERFORM
        """
        start = tokens[i]
        i += 1
        
        if i >= len(tokens):
            return i
        
        # Check if this is PERFORM VARYING
        if tokens[i].value and tokens[i].value.upper() == 'VARYING':
            import logging
            logger = logging.getLogger(__name__)
            logger.debug(f"_parse_perform_inline: Found PERFORM VARYING at token {i}")
            
            pf = PerformStatement(start.location)
            i += 1  # Skip VARYING
            
            logger.debug(f"After VARYING, token {i}: {tokens[i].type if i < len(tokens) else 'EOF'}")
            
            # Get variable name
            if i < len(tokens) and tokens[i].type == TokenType.IDENTIFIER:
                variable_name = tokens[i].value
                i += 1
                logger.debug(f"Variable name: {variable_name}, next token {i}: {tokens[i].type if i < len(tokens) else 'EOF'}")
                
                # Expect FROM
                if i < len(tokens) and tokens[i].value and tokens[i].value.upper() == 'FROM':
                    logger.debug(f"Found FROM at token {i}")
                    i += 1  # Skip FROM
                    
                    # Get FROM value
                    if i < len(tokens):
                        from_value = tokens[i].value
                        i += 1
                        
                        # Expect BY
                        if i < len(tokens) and tokens[i].value and tokens[i].value.upper() == 'BY':
                            i += 1  # Skip BY
                            
                            # Get BY value
                            if i < len(tokens):
                                by_value = tokens[i].value
                                i += 1
                                
                                # Skip newlines before UNTIL
                                while i < len(tokens) and tokens[i].type == TokenType.NEWLINE:
                                    i += 1
                                
                                # Expect UNTIL
                                if i < len(tokens) and tokens[i].value and tokens[i].value.upper() == 'UNTIL':
                                    logger.debug(f"Found UNTIL at token {i}")
                                    i += 1  # Skip UNTIL
                                    
                                    # Parse condition until newline or statement keyword
                                    cond_tokens = []
                                    while i < len(tokens) and tokens[i].type != TokenType.NEWLINE:
                                        cond_tokens.append(tokens[i].value)
                                        i += 1
                                    
                                    condition_text = " ".join(cond_tokens).strip()
                                    condition_expr = CobolExpression("IDENTIFIER", start.location)
                                    condition_expr._metadata["value"] = condition_text
                                    
                                    # Set VARYING clause
                                    pf.set_varying_clause(variable_name, from_value, by_value, condition_expr)
                                    logger.debug(f"Set VARYING clause: {variable_name} FROM {from_value} BY {by_value} UNTIL {condition_text}")
                                    
                                    # Skip newlines before inline statements
                                    while i < len(tokens) and tokens[i].type == TokenType.NEWLINE:
                                        i += 1
                                    
                                    # Parse inline statements until END-PERFORM
                                    logger.debug(f"Starting inline statement parse loop at token {i}, tokens remaining: {len(tokens) - i}")
                                    while i < len(tokens):
                                        # Check for END-PERFORM
                                        if (tokens[i].type == TokenType.IDENTIFIER and 
                                            tokens[i].value and tokens[i].value.upper() == 'END-PERFORM'):
                                            i += 1
                                            break
                                        
                                        # Check for nested statements
                                        token_type = tokens[i].type
                                        token_val = tokens[i].value.upper() if tokens[i].value else ""
                                        
                                        # Debug logging
                                        import logging
                                        logger = logging.getLogger(__name__)
                                        logger.debug(f"PERFORM inline: token {i}: {token_type} / {token_val}")
                                        
                                        # Parse nested CALL statements
                                        if token_type == TokenType.CALL or token_val == 'CALL':
                                            logger.debug(f"Found CALL at token {i}, calling _parse_inline_call_into_perform")
                                            i = self._parse_inline_call_into_perform(tokens, i, pf)
                                            continue
                                        
                                        # Parse nested IF statements
                                        if token_type == TokenType.IF or token_val == 'IF':
                                            i = self._parse_inline_if_into_perform(tokens, i, pf)
                                            continue
                                        
                                        # Skip other tokens (newlines, comments, etc.)
                                        i += 1
            
            if self.current_section:
                self.current_section.add_child(pf)
            return i
        
        # Simple PERFORM paragraph-name [THRU paragraph-name] [n TIMES]
        else:
            pf = PerformStatement(start.location)
            pf.set_target_paragraph(tokens[i].value)
            i += 1
            
            # Check for THRU clause
            if i < len(tokens) and tokens[i].value and tokens[i].value.upper() == "THRU":
                i += 1  # Skip THRU
                
                # Skip optional whitespace/newlines
                while i < len(tokens) and tokens[i].type in (TokenType.NEWLINE, TokenType.COMMENT):
                    i += 1
                
                # Get ending paragraph name
                if i < len(tokens) and tokens[i].type == TokenType.IDENTIFIER:
                    pf.set_thru_paragraph(tokens[i].value)
                    i += 1
            
            # Check for TIMES clause
            if i < len(tokens) and tokens[i].type in (TokenType.NUMERIC_LITERAL, TokenType.LEVEL_NUMBER):
                try:
                    times_count = int(tokens[i].value)
                    i += 1
                    
                    # Skip optional whitespace/newlines
                    while i < len(tokens) and tokens[i].type in (TokenType.NEWLINE, TokenType.COMMENT):
                        i += 1
                    
                    # Expect TIMES keyword
                    if i < len(tokens) and tokens[i].value and tokens[i].value.upper() in ("TIMES", "TIME"):
                        i += 1
                        pf.set_times_clause(times_count)
                except ValueError:
                    pass
            
            if self.current_section:
                self.current_section.add_child(pf)
            return i
    
    def _parse_inline_call_into_perform(self, tokens, i, perform_stmt):
        """Parse a CALL statement within a PERFORM block and add it to inline_statements."""
        if i >= len(tokens):
            return i
        
        start = tokens[i]
        i += 1  # Skip CALL
        
        if i < len(tokens):
            call_stmt = CallStatement(start.location)
            
            # Get program name
            program_name = tokens[i].value
            is_dynamic = tokens[i].type == TokenType.IDENTIFIER
            
            # For string literals, keep quotes
            if tokens[i].type == TokenType.STRING_LITERAL:
                program_name = f'"{program_name}"'
            
            call_stmt.set_called_program(program_name, is_dynamic)
            i += 1
            
            # Check for USING clause
            if i < len(tokens) and tokens[i].value and tokens[i].value.upper() == 'USING':
                i += 1  # Skip USING
                
                # Parse parameters until newline or END-PERFORM
                while i < len(tokens):
                    token_val = tokens[i].value.upper() if tokens[i].value else ""
                    
                    # Stop at END-PERFORM or newline
                    if token_val == 'END-PERFORM' or tokens[i].type == TokenType.NEWLINE:
                        break
                    
                    # Add parameter
                    if tokens[i].type == TokenType.IDENTIFIER:
                        call_stmt.add_using_parameter(tokens[i].value)
                    
                    i += 1
            
            # Add to PERFORM's inline statements
            perform_stmt.add_inline_statement(call_stmt)
        
        return i
    
    def _parse_inline_if_into_perform(self, tokens, i, perform_stmt):
        """Parse an IF statement within a PERFORM block and add it to inline_statements."""
        if i >= len(tokens):
            return i
        
        start = tokens[i]
        i += 1  # Skip IF
        
        if_stmt = IfStatement(start.location)
        
        # Parse condition until THEN or newline
        cond_tokens = []
        while i < len(tokens) and tokens[i].type != TokenType.NEWLINE:
            token_val = tokens[i].value.upper() if tokens[i].value else ""
            if token_val in ('THEN', 'END-PERFORM'):
                break
            cond_tokens.append(tokens[i].value)
            i += 1
        
        condition_text = " ".join(cond_tokens).strip()
        condition_expr = CobolExpression("COMPARISON", start.location)
        condition_expr._metadata["value"] = condition_text
        if_stmt.set_condition(condition_expr)
        
        # Skip THEN if present
        if i < len(tokens) and tokens[i].value and tokens[i].value.upper() == 'THEN':
            i += 1
        
        # Parse THEN branch until ELSE or END-IF or END-PERFORM
        while i < len(tokens):
            token_val = tokens[i].value.upper() if tokens[i].value else ""
            if token_val in ('ELSE', 'END-IF', 'END-PERFORM'):
                break
            
            # Parse nested CALL in IF
            if tokens[i].type == TokenType.CALL or token_val == 'CALL':
                i = self._parse_inline_call_into_if(tokens, i, if_stmt, True)
                continue
            
            i += 1
        
        # Check for ELSE
        if i < len(tokens) and tokens[i].value and tokens[i].value.upper() == 'ELSE':
            i += 1  # Skip ELSE
            
            # Parse ELSE branch until END-IF or END-PERFORM
            while i < len(tokens):
                token_val = tokens[i].value.upper() if tokens[i].value else ""
                if token_val in ('END-IF', 'END-PERFORM'):
                    break
                
                # Parse nested CALL in ELSE
                if tokens[i].type == TokenType.CALL or token_val == 'CALL':
                    i = self._parse_inline_call_into_if(tokens, i, if_stmt, False)
                    continue
                
                i += 1
        
        # Skip END-IF if present
        if i < len(tokens) and tokens[i].value and tokens[i].value.upper() == 'END-IF':
            i += 1
        
        # Add IF statement to PERFORM's inline statements
        perform_stmt.add_inline_statement(if_stmt)
        
        return i
    
    def _parse_inline_call_into_if(self, tokens, i, if_stmt, is_then_branch):
        """Parse a CALL statement within an IF block."""
        if i >= len(tokens):
            return i
        
        start = tokens[i]
        i += 1  # Skip CALL
        
        if i < len(tokens):
            call_stmt = CallStatement(start.location)
            
            # Get program name
            program_name = tokens[i].value
            is_dynamic = tokens[i].type == TokenType.IDENTIFIER
            
            # For string literals, keep quotes
            if tokens[i].type == TokenType.STRING_LITERAL:
                program_name = f'"{program_name}"'
            
            call_stmt.set_called_program(program_name, is_dynamic)
            i += 1
            
            # Check for USING clause
            if i < len(tokens) and tokens[i].value and tokens[i].value.upper() == 'USING':
                i += 1  # Skip USING
                
                # Parse parameters until newline, ELSE, or END-IF
                while i < len(tokens):
                    token_val = tokens[i].value.upper() if tokens[i].value else ""
                    
                    # Stop at control keywords or newline
                    if token_val in ('ELSE', 'END-IF', 'END-PERFORM') or tokens[i].type == TokenType.NEWLINE:
                        break
                    
                    # Add parameter
                    if tokens[i].type == TokenType.IDENTIFIER:
                        call_stmt.add_using_parameter(tokens[i].value)
                    
                    i += 1
            
            # Add to appropriate branch
            if is_then_branch:
                if_stmt.add_then_statement(call_stmt)
            else:
                if_stmt.add_else_statement(call_stmt)
        
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
        """Parse IF statement inline within a sentence (backward compatibility mode).
        
        This handles period-terminated IF statements like:
        - IF A > B MOVE C TO D.
        - IF A > B MOVE C TO D ELSE MOVE E TO F.
        
        Creates proper IfStatement objects with then_statements and else_statements
        populated for backward compatibility and consistent AST structure.
        """
        start = tokens[i]
        i += 1
        cond_parts = []
        # Parse condition up to THEN or first verb/ELSE
        while i < len(tokens) and tokens[i].type not in (TokenType.THEN, TokenType.ELSE, TokenType.MOVE, TokenType.PERFORM, TokenType.DISPLAY, TokenType.WRITE, TokenType.GO, TokenType.GOTO, TokenType.IF):
            if tokens[i].value:
                cond_parts.append(tokens[i].value)
            i += 1
        condition = ' '.join(cond_parts).strip()
        
        # Create proper IfStatement instead of generic CobolStatement
        if_stmt = IfStatement(start.location)
        self._set_node_context(if_stmt)
        
        # Set condition
        condition_expr = CobolExpression("COMPARISON", start.location)
        condition_expr._metadata["value"] = condition
        if_stmt.set_condition(condition_expr)
        
        # Parse THEN block (if THEN present, else treat next verb as THEN)
        if i < len(tokens) and tokens[i].type == TokenType.THEN:
            i += 1
        
        # Skip newlines after THEN
        while i < len(tokens) and tokens[i].type in (TokenType.NEWLINE, TokenType.COMMENT):
            i += 1
        
        # Parse statements until ELSE or next IF or end
        while i < len(tokens) and tokens[i].type not in (TokenType.ELSE, TokenType.IF):
            verb_tok = tokens[i]
            verb_type = verb_tok.type
            verb_val = verb_tok.value.upper() if verb_tok.value else ""
            
            # Only parse known verbs
            if verb_type == TokenType.MOVE or verb_val == 'MOVE':
                j = self._parse_move_inline(tokens, i)
                # Find last statement added to section and add to IF then_statements
                if self.current_section and self.current_section.children:
                    then_stmt = self.current_section.children[-1]
                    if_stmt.add_then_statement(then_stmt)
                i = j
                continue
            if verb_type == TokenType.PERFORM or verb_val == 'PERFORM':
                j = self._parse_perform_inline(tokens, i)
                if self.current_section and self.current_section.children:
                    then_stmt = self.current_section.children[-1]
                    if_stmt.add_then_statement(then_stmt)
                i = j
                continue
            if verb_type == TokenType.DISPLAY or verb_val == 'DISPLAY':
                j = self._parse_display_inline(tokens, i)
                if self.current_section and self.current_section.children:
                    then_stmt = self.current_section.children[-1]
                    if_stmt.add_then_statement(then_stmt)
                i = j
                continue
            if verb_type == TokenType.WRITE or verb_val == 'WRITE':
                j = self._parse_write_inline(tokens, i)
                if self.current_section and self.current_section.children:
                    then_stmt = self.current_section.children[-1]
                    if_stmt.add_then_statement(then_stmt)
                i = j
                continue
            if verb_type in (TokenType.GO, TokenType.GOTO) or verb_val in ('GO', 'GOTO'):
                j = self._parse_goto_inline(tokens, i)
                if self.current_section and self.current_section.children:
                    then_stmt = self.current_section.children[-1]
                    if_stmt.add_then_statement(then_stmt)
                i = j
                continue
            # Unknown or non-verb: skip
            i += 1
        
        # Parse ELSE block if present
        if i < len(tokens) and tokens[i].type == TokenType.ELSE:
            i += 1
            
            # Skip newlines after ELSE
            while i < len(tokens) and tokens[i].type in (TokenType.NEWLINE, TokenType.COMMENT):
                i += 1
            
            while i < len(tokens) and tokens[i].type not in (TokenType.IF,):
                verb_tok = tokens[i]
                verb_type = verb_tok.type
                verb_val = verb_tok.value.upper() if verb_tok.value else ""
                
                if verb_type == TokenType.MOVE or verb_val == 'MOVE':
                    j = self._parse_move_inline(tokens, i)
                    if self.current_section and self.current_section.children:
                        else_stmt = self.current_section.children[-1]
                        if_stmt.add_else_statement(else_stmt)
                    i = j
                    continue
                if verb_type == TokenType.PERFORM or verb_val == 'PERFORM':
                    j = self._parse_perform_inline(tokens, i)
                    if self.current_section and self.current_section.children:
                        else_stmt = self.current_section.children[-1]
                        if_stmt.add_else_statement(else_stmt)
                    i = j
                    continue
                if verb_type == TokenType.DISPLAY or verb_val == 'DISPLAY':
                    j = self._parse_display_inline(tokens, i)
                    if self.current_section and self.current_section.children:
                        else_stmt = self.current_section.children[-1]
                        if_stmt.add_else_statement(else_stmt)
                    i = j
                    continue
                if verb_type == TokenType.WRITE or verb_val == 'WRITE':
                    j = self._parse_write_inline(tokens, i)
                    if self.current_section and self.current_section.children:
                        else_stmt = self.current_section.children[-1]
                        if_stmt.add_else_statement(else_stmt)
                    i = j
                    continue
                if verb_type in (TokenType.GO, TokenType.GOTO) or verb_val in ('GO', 'GOTO'):
                    j = self._parse_goto_inline(tokens, i)
                    if self.current_section and self.current_section.children:
                        else_stmt = self.current_section.children[-1]
                        if_stmt.add_else_statement(else_stmt)
                    i = j
                    continue
                i += 1
        
        # Add IF statement to current section
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
        peek1 = self.peek_token()
        peek2 = self.peek_token(2)
        if (peek1 and peek1.value and peek1.value.upper() == "SECTION" and
            peek2 and peek2.type == TokenType.PERIOD):
            # This is a section declaration: NAME SECTION.
            if not self.current_token:
                return
            section_name = self.current_token.value
            location = self.current_token.location
            self.advance_token()  # Skip section name
            self.advance_token()  # Skip SECTION keyword
            self.advance_token()  # Skip period
            
            # Create section in the procedure division
            procedure_section = CobolSection(section_name, location)
            self._set_node_context(procedure_section)
            if self.current_division:
                self.current_division.add_section(procedure_section)
            
            # Set this section as current section to collect statements
            self.current_section = procedure_section
            
        # Check for paragraph pattern: NAME.
        else:
            peek1 = self.peek_token()
            if peek1 and peek1.type == TokenType.PERIOD:
                # This is a paragraph name - create paragraph and parse its statements
                if not self.current_token:
                    return
                paragraph_name = self.current_token.value
                location = self.current_token.location
                self.advance_token()  # Skip paragraph name
                self.advance_token()  # Skip period
            
                # Create paragraph as a section in the procedure division
                # In COBOL, paragraphs in procedure division are treated as sections
                paragraph_section = CobolSection(paragraph_name, location)
                self._set_node_context(paragraph_section)
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
            peek_tok = self.peek_token()
            if (self.current_token.type in (TokenType.PLUS, TokenType.MINUS) and 
                peek_tok and 
                peek_tok.type in (TokenType.LEVEL_NUMBER, TokenType.NUMERIC_LITERAL)):
                # Combine sign with number
                source = self.current_token.value + peek_tok.value
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
            loc = self.get_current_location()
            self.add_error(ParseError(
                f"Expected TO in MOVE statement (found: {current_info})",
                location=loc
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
        self._set_node_context(move_stmt)
        move_stmt.set_source(source)
        move_stmt.add_target(target)
        if not self.parsing_nested_statement and self.current_division:
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
        self._set_node_context(display_stmt)
        display_stmt.add_display_item(item)
        if not self.parsing_nested_statement and self.current_division:
            self.current_division.add_child(display_stmt)
        
        return display_stmt
    
    def parse_perform_statement(self) -> Optional[PerformStatement]:
        """Parse PERFORM statement.
        
        Supports:
        - PERFORM paragraph-name
        - PERFORM UNTIL condition
        - PERFORM VARYING variable FROM value BY value UNTIL condition ... END-PERFORM
        - Inline PERFORM blocks with nested statements
        """
        if not self.match_token(TokenType.PERFORM):
            return None
        
        location = self.get_current_location()
        perform_stmt = PerformStatement(location)
        self._set_node_context(perform_stmt)
        
        # Skip optional whitespace/newlines
        while self.current_token and self.current_token.type in (TokenType.NEWLINE, TokenType.COMMENT):
            self.advance_token()
        
        # Check for VARYING clause
        if self.current_token and self.current_token.value and self.current_token.value.upper() == "VARYING":
            self.advance_token()  # Skip VARYING
            
            # Skip optional whitespace/newlines
            while self.current_token and self.current_token.type in (TokenType.NEWLINE, TokenType.COMMENT):
                self.advance_token()
            
            # Get variable name
            if not self.current_token or self.current_token.type != TokenType.IDENTIFIER:
                self.add_error(ParseError("Expected variable name after VARYING", location=location))
                return None
            
            variable_name = self.current_token.value
            self.advance_token()
            
            # Skip optional whitespace/newlines
            while self.current_token and self.current_token.type in (TokenType.NEWLINE, TokenType.COMMENT):
                self.advance_token()
            
            # Expect FROM
            if not self.current_token or not self.current_token.value or self.current_token.value.upper() != "FROM":
                self.add_error(ParseError("Expected FROM after variable in VARYING clause", location=location))
                return None
            self.advance_token()
            
            # Skip optional whitespace/newlines
            while self.current_token and self.current_token.type in (TokenType.NEWLINE, TokenType.COMMENT):
                self.advance_token()
            
            # Get FROM value
            if not self.current_token:
                self.add_error(ParseError("Expected value after FROM", location=location))
                return None
            from_value = self.current_token.value
            self.advance_token()
            
            # Skip optional whitespace/newlines
            while self.current_token and self.current_token.type in (TokenType.NEWLINE, TokenType.COMMENT):
                self.advance_token()
            
            # Expect BY
            if not self.current_token or not self.current_token.value or self.current_token.value.upper() != "BY":
                self.add_error(ParseError("Expected BY in VARYING clause", location=location))
                return None
            self.advance_token()
            
            # Skip optional whitespace/newlines
            while self.current_token and self.current_token.type in (TokenType.NEWLINE, TokenType.COMMENT):
                self.advance_token()
            
            # Get BY value
            if not self.current_token:
                self.add_error(ParseError("Expected value after BY", location=location))
                return None
            by_value = self.current_token.value
            self.advance_token()
            
            # Skip optional whitespace/newlines
            while self.current_token and self.current_token.type in (TokenType.NEWLINE, TokenType.COMMENT):
                self.advance_token()
            
            # Expect UNTIL
            if not self.current_token or not self.current_token.value or self.current_token.value.upper() != "UNTIL":
                self.add_error(ParseError("Expected UNTIL in VARYING clause", location=location))
                return None
            self.advance_token()
            
            # Parse condition until newline or statement
            cond_tokens = []
            while self.current_token and self.current_token.type not in (TokenType.NEWLINE, TokenType.COMMENT):
                cond_tokens.append(self.current_token.value)
                self.advance_token()
            
            condition_text = " ".join(cond_tokens).strip()
            condition_expr = CobolExpression("IDENTIFIER", location)
            condition_expr._metadata["value"] = condition_text
            
            # Set VARYING clause
            perform_stmt.set_varying_clause(variable_name, from_value, by_value, condition_expr)
            
            # Skip newlines after condition
            while self.current_token and self.current_token.type in (TokenType.NEWLINE, TokenType.COMMENT):
                self.advance_token()
            
            # Parse inline statements until END-PERFORM
            while self.current_token and self.current_token.type != TokenType.EOF:
                # Check for END-PERFORM
                if self.current_token.type == TokenType.IDENTIFIER and \
                   self.current_token.value and self.current_token.value.upper() == "END-PERFORM":
                    self.advance_token()
                    
                    # Skip optional period
                    if self.current_token and self.current_token.type == TokenType.PERIOD:
                        self.advance_token()
                    break
                
                # Parse nested statement with flag set
                self.parsing_nested_statement = True
                nested_stmt = self.parse_statement()
                self.parsing_nested_statement = False
                
                if nested_stmt:
                    perform_stmt.add_inline_statement(nested_stmt)
                else:
                    # Skip unknown token
                    self.advance_token()
        
        # Simple PERFORM paragraph-name
        elif self.current_token and self.current_token.type == TokenType.IDENTIFIER:
            paragraph = self.current_token.value
            self.advance_token()
            
            # Check for THRU clause
            thru_paragraph = None
            if self.current_token and self.current_token.value and self.current_token.value.upper() == "THRU":
                self.advance_token()  # Skip THRU keyword
                
                # Skip optional whitespace/newlines
                while self.current_token and self.current_token.type in (TokenType.NEWLINE, TokenType.COMMENT):
                    self.advance_token()
                
                # Get ending paragraph name
                if self.current_token and self.current_token.type == TokenType.IDENTIFIER:
                    thru_paragraph = self.current_token.value
                    self.advance_token()
                else:
                    self.add_error(ParseError("Expected paragraph name after THRU", location=location))
                    return None
            
            # Check for TIMES clause (can follow THRU or paragraph name)
            times_count = None
            if self.current_token and self.current_token.type in (TokenType.NUMERIC_LITERAL, TokenType.LEVEL_NUMBER):
                # Number before TIMES keyword
                try:
                    times_count = int(self.current_token.value)
                    self.advance_token()
                    
                    # Skip optional whitespace/newlines
                    while self.current_token and self.current_token.type in (TokenType.NEWLINE, TokenType.COMMENT):
                        self.advance_token()
                    
                    # Expect TIMES keyword
                    if self.current_token and self.current_token.value and self.current_token.value.upper() in ("TIMES", "TIME"):
                        self.advance_token()
                    else:
                        # Number without TIMES - might be an error, but continue
                        pass
                except ValueError:
                    pass
            
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
                    self.advance_token()
                condition = " ".join(cond_tokens).strip() if cond_tokens else None
                # After condition, allow optional NEWLINE(s)
                while self.current_token and self.current_token.type == TokenType.NEWLINE:
                    self.advance_token()
            
            # Expect terminal period (may follow immediately or after condition).
            if not (condition and condition.endswith('.')):
                if not self.expect_token(TokenType.PERIOD):
                    return None
            
            # Set the target paragraph
            perform_stmt.set_target_paragraph(paragraph)
            
            # Set the THRU paragraph if present
            if thru_paragraph:
                perform_stmt.set_thru_paragraph(thru_paragraph)
            
            # Set TIMES count if present
            if times_count:
                perform_stmt.set_times_clause(times_count)
            
            # Set UNTIL condition if present
            if condition:
                perform_stmt.perform_type = "UNTIL"
                # Create a simple identifier expression from the condition string
                condition_expr = CobolExpression("IDENTIFIER", location)
                condition_expr._metadata["value"] = condition
                perform_stmt.until_condition = condition_expr
        
        if not self.parsing_nested_statement and self.current_division:
            self.current_division.add_child(perform_stmt)
        
        return perform_stmt
    
    def parse_stop_statement(self) -> Optional[StopStatement]:
        """Parse STOP RUN statement."""
        if not self.match_token(TokenType.STOP):
            return None
        
        location = self.get_current_location()
        
        # Expect RUN
        if self.current_token and self.current_token.value.upper() == "RUN":
            self.advance_token()
        
        # Expect period
        self.expect_token(TokenType.PERIOD)
        
        stop_stmt = StopStatement(location)
        self._set_node_context(stop_stmt)
        
        if not self.parsing_nested_statement and self.current_division:
            self.current_division.add_child(stop_stmt)
        
        return stop_stmt
    
    def parse_statement(self) -> Optional[CobolStatement]:
        """Parse a single statement (dispatcher to specific statement parsers).
        
        This method acts as a dispatcher to call the appropriate statement parser
        based on the current token type. It's used when parsing nested statements
        within PERFORM blocks, IF branches, etc.
        """
        if not self.current_token:
            return None
        
        # Skip whitespace and comments
        while self.current_token and self.current_token.type in (TokenType.NEWLINE, TokenType.COMMENT):
            self.advance_token()
        
        if not self.current_token:
            return None
        
        # Dispatch based on token type
        if self.current_token.type == TokenType.MOVE or \
           (self.current_token.value and self.current_token.value.upper() == "MOVE"):
            return self.parse_move_statement()
        elif self.current_token.type == TokenType.DISPLAY or \
             (self.current_token.value and self.current_token.value.upper() == "DISPLAY"):
            return self.parse_display_statement()
        elif self.current_token.type == TokenType.PERFORM or \
             (self.current_token.value and self.current_token.value.upper() == "PERFORM"):
            return self.parse_perform_statement()
        elif self.current_token.type == TokenType.CALL or \
             (self.current_token.value and self.current_token.value.upper() == "CALL"):
            return self.parse_call_statement()
        elif self.current_token.type == TokenType.STOP or \
             (self.current_token.value and self.current_token.value.upper() == "STOP"):
            return self.parse_stop_statement()
        elif self.current_token.type == TokenType.IF or \
             (self.current_token.value and self.current_token.value.upper() == "IF"):
            return self.parse_if_statement()
        else:
            # Unknown statement type - create generic statement
            location = self.get_current_location()
            stmt = CobolStatement(self.current_token.value.upper() if self.current_token.value else "UNKNOWN", location)
            self.advance_token()
            
            # Skip to end of statement (period)
            while self.current_token and self.current_token.type != TokenType.PERIOD:
                if self.current_token.type in (TokenType.NEWLINE, TokenType.COMMENT):
                    self.advance_token()
                    continue
                stmt.add_operand(self.current_token.value)
                self.advance_token()
            
            if self.current_token and self.current_token.type == TokenType.PERIOD:
                self.advance_token()
            
            return stmt
    
    def parse_if_statement(self) -> Optional[IfStatement]:
        """Parse IF statement with THEN/ELSE branches and END-IF terminator.
        
        Supports:
        - IF condition THEN statements END-IF
        - IF condition THEN statements ELSE statements END-IF  
        - Nested statements in both branches
        """
        if not self.match_token(TokenType.IF):
            return None
        
        location = self.get_current_location()
        if_stmt = IfStatement(location)
        self._set_node_context(if_stmt)
        
        # Skip optional whitespace/newlines
        while self.current_token and self.current_token.type in (TokenType.NEWLINE, TokenType.COMMENT):
            self.advance_token()
        
        # Parse condition until THEN or newline
        cond_tokens = []
        while self.current_token and \
              self.current_token.type not in (TokenType.NEWLINE, TokenType.COMMENT) and \
              not (self.current_token.value and self.current_token.value.upper() == "THEN"):
            cond_tokens.append(self.current_token.value)
            self.advance_token()
        
        condition_text = " ".join(cond_tokens).strip()
        condition_expr = CobolExpression("COMPARISON", location)
        condition_expr._metadata["value"] = condition_text
        if_stmt.set_condition(condition_expr)
        
        # Skip THEN keyword if present
        if self.current_token and self.current_token.value and self.current_token.value.upper() == "THEN":
            self.advance_token()
        
        # Skip newlines after condition/THEN
        while self.current_token and self.current_token.type in (TokenType.NEWLINE, TokenType.COMMENT):
            self.advance_token()
        
        # Parse THEN branch statements until ELSE or END-IF
        while self.current_token and self.current_token.type != TokenType.EOF:
            # Check for ELSE
            if self.current_token.type == TokenType.IDENTIFIER and \
               self.current_token.value and self.current_token.value.upper() == "ELSE":
                self.advance_token()
                break
            
            # Check for END-IF
            if self.current_token.type == TokenType.IDENTIFIER and \
               self.current_token.value and self.current_token.value.upper() == "END-IF":
                self.advance_token()
                # Skip optional period
                if self.current_token and self.current_token.type == TokenType.PERIOD:
                    self.advance_token()
                
                if not self.parsing_nested_statement and self.current_division:
                    self.current_division.add_child(if_stmt)
                
                return if_stmt
            
            # Skip newlines/comments
            if self.current_token.type in (TokenType.NEWLINE, TokenType.COMMENT):
                self.advance_token()
                continue
            
            # Parse nested statement with flag set
            self.parsing_nested_statement = True
            nested_stmt = self.parse_statement()
            self.parsing_nested_statement = False
            
            if nested_stmt:
                if_stmt.add_then_statement(nested_stmt)
            else:
                # Unable to parse statement, skip token
                self.advance_token()
        
        # Skip newlines after ELSE
        while self.current_token and self.current_token.type in (TokenType.NEWLINE, TokenType.COMMENT):
            self.advance_token()
        
        # Parse ELSE branch statements until END-IF
        while self.current_token and self.current_token.type != TokenType.EOF:
            # Check for END-IF
            if self.current_token.type == TokenType.IDENTIFIER and \
               self.current_token.value and self.current_token.value.upper() == "END-IF":
                self.advance_token()
                # Skip optional period
                if self.current_token and self.current_token.type == TokenType.PERIOD:
                    self.advance_token()
                break
            
            # Skip newlines/comments
            if self.current_token.type in (TokenType.NEWLINE, TokenType.COMMENT):
                self.advance_token()
                continue
            
            # Parse nested statement with flag set
            self.parsing_nested_statement = True
            nested_stmt = self.parse_statement()
            self.parsing_nested_statement = False
            
            if nested_stmt:
                if_stmt.add_else_statement(nested_stmt)
            else:
                # Unable to parse statement, skip token
                self.advance_token()
        
        if not self.parsing_nested_statement and self.current_division:
            self.current_division.add_child(if_stmt)
        
        return if_stmt
    
    def parse_call_statement(self) -> Optional[CallStatement]:
        """Parse CALL statement.
        
        Supports:
        - CALL "literal" or CALL identifier (dynamic)
        - USING clause with BY REFERENCE/CONTENT/VALUE parameters
        - RETURNING clause
        - ON EXCEPTION/OVERFLOW clauses with END-CALL terminator
        """
        if not self.match_token(TokenType.CALL):
            return None
        
        location = self.get_current_location()
        call_stmt = CallStatement(location)
        self._set_node_context(call_stmt)
        
        # Skip optional whitespace/newlines
        while self.current_token and self.current_token.type in (TokenType.NEWLINE, TokenType.COMMENT):
            self.advance_token()
        
        # Get program name (literal or identifier)
        if not self.current_token:
            self.add_error(ParseError("Expected program name after CALL", location=location))
            return None
        
        program_name = self.current_token.value
        is_dynamic = self.current_token.type == TokenType.IDENTIFIER
        
        # For string literals, keep the quotes
        if self.current_token.type == TokenType.STRING_LITERAL:
            program_name = f'"{program_name}"'
        
        call_stmt.set_called_program(program_name, is_dynamic)
        self.advance_token()
        
        # Skip optional whitespace/newlines
        while self.current_token and self.current_token.type in (TokenType.NEWLINE, TokenType.COMMENT):
            self.advance_token()
        
        # Parse optional USING clause
        if self.current_token and self.current_token.type == TokenType.IDENTIFIER and \
           self.current_token.value.upper() == "USING":
            self.advance_token()
            self._parse_call_using_parameters(call_stmt)
        
        # Skip optional whitespace/newlines
        while self.current_token and self.current_token.type in (TokenType.NEWLINE, TokenType.COMMENT):
            self.advance_token()
        
        # Parse optional RETURNING clause
        if self.current_token and self.current_token.type == TokenType.IDENTIFIER and \
           self.current_token.value.upper() == "RETURNING":
            self.advance_token()
            
            # Skip optional whitespace/newlines
            while self.current_token and self.current_token.type in (TokenType.NEWLINE, TokenType.COMMENT):
                self.advance_token()
            
            if self.current_token and self.current_token.type == TokenType.IDENTIFIER:
                call_stmt.set_returning_parameter(self.current_token.value)
                self.advance_token()
        
        # Skip optional whitespace/newlines
        while self.current_token and self.current_token.type in (TokenType.NEWLINE, TokenType.COMMENT):
            self.advance_token()
        
        # Parse optional ON EXCEPTION/OVERFLOW clauses
        if self.current_token and self.current_token.type == TokenType.IDENTIFIER and \
           self.current_token.value.upper() == "ON":
            self.advance_token()
            
            # Skip optional whitespace/newlines
            while self.current_token and self.current_token.type in (TokenType.NEWLINE, TokenType.COMMENT):
                self.advance_token()
            
            if self.current_token and self.current_token.type == TokenType.IDENTIFIER:
                exception_type = self.current_token.value.upper()
                
                if exception_type in ("EXCEPTION", "OVERFLOW"):
                    self.advance_token()
                    
                    # Parse statements until END-CALL or period
                    exception_statements = []
                    while self.current_token and self.current_token.type != TokenType.EOF:
                        # Check for END-CALL
                        if self.current_token.type == TokenType.IDENTIFIER and \
                           self.current_token.value.upper() == "END-CALL":
                            self.advance_token()
                            break
                        
                        # Check for period (alternative terminator)
                        if self.current_token.type == TokenType.PERIOD:
                            break
                        
                        # For now, skip tokens in the exception handler
                        # Full implementation would parse nested statements
                        self.advance_token()
                    
                    # Store which type of exception handler we found
                    if exception_type == "EXCEPTION":
                        call_stmt.on_exception = exception_statements
                    else:
                        call_stmt.on_overflow = exception_statements
        
        # Skip optional whitespace/newlines
        while self.current_token and self.current_token.type in (TokenType.NEWLINE, TokenType.COMMENT):
            self.advance_token()
        
        # Expect period
        if self.current_token and self.current_token.type == TokenType.PERIOD:
            self.advance_token()
        
        # Only add to division if not parsing nested statement
        if not self.parsing_nested_statement and self.current_division:
            self.current_division.add_child(call_stmt)
        
        return call_stmt
    
    def _parse_call_using_parameters(self, call_stmt: CallStatement) -> None:
        """Parse USING clause parameters for CALL statement."""
        current_mode = "REFERENCE"  # Default mode
        
        while self.current_token and self.current_token.type != TokenType.EOF:
            # Skip whitespace/newlines
            while self.current_token and self.current_token.type in (TokenType.NEWLINE, TokenType.COMMENT):
                self.advance_token()
            
            if not self.current_token:
                break
            
            # Check for end of USING clause
            if self.current_token.type == TokenType.PERIOD:
                break
            
            # Check for RETURNING, ON (exception/overflow)
            if self.current_token.type == TokenType.IDENTIFIER:
                upper_val = self.current_token.value.upper()
                
                if upper_val in ("RETURNING", "ON"):
                    break
                
                # Check for BY keyword (parameter passing mode)
                if upper_val == "BY":
                    self.advance_token()
                    
                    # Skip whitespace/newlines
                    while self.current_token and self.current_token.type in (TokenType.NEWLINE, TokenType.COMMENT):
                        self.advance_token()
                    
                    if self.current_token and self.current_token.type == TokenType.IDENTIFIER:
                        mode = self.current_token.value.upper()
                        if mode in ("REFERENCE", "CONTENT", "VALUE"):
                            current_mode = mode
                            self.advance_token()
                            
                            # Skip whitespace/newlines
                            while self.current_token and self.current_token.type in (TokenType.NEWLINE, TokenType.COMMENT):
                                self.advance_token()
                            
                            continue
                
                # This must be a parameter name
                param_name = self.current_token.value
                call_stmt.add_using_parameter(param_name, current_mode)
                self.advance_token()
            else:
                # Unexpected token, break to avoid infinite loop
                break
    
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
        source = normalize_fixed_format(source.splitlines())
        free_form = True  # normalize produces free-form text
    parser = CobolParser(dialect=dialect, error_recovery=error_recovery, free_form=free_form)
    return parser.parse(source, filename)