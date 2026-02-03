"""COBOL parser implementation with factory-based architecture.

This module provides delegating CobolParser that orchestrates parsing through:
- DivisionParserFactory for IDENTIFICATION, ENVIRONMENT, DATA, PROCEDURE divisions
- StatementRegistry for dynamic statement parsing within PROCEDURE division
- TokenStream abstraction for lookahead and error recovery
"""

import re
from typing import List, Optional, Dict, Any
from dataclasses import dataclass
from enum import Enum, auto

from .lexer import CobolLexer, Token, TokenType, LexerError
from .models.ast_base import SourceLocation, ASTNode
from .models.program import CobolProgram, CobolDivision
from .plugins.core import (
    ParseError,
    ParseStatistics,
    ErrorRecoveryMode,
    DialectType,
    MemoryConfiguration,
    SerializationConfig,
    PluginManager,
)

# Core parsing infrastructure
from .core.token_stream import TokenStream
from .core.registry import StatementRegistry
from .core.interfaces import ParseContext
from .parsers.divisions.factory import DivisionParserFactory, DivisionType
from .parsers.divisions.identification import IdentificationDivisionParser
from .parsers.divisions.environment import EnvironmentDivisionParser
from .parsers.divisions.data import DataDivisionParser
from .parsers.divisions.procedure import ProcedureDivisionParser

# Statement parsers
from .parsers.display_parser import DisplayStatementParser
from .parsers.move_parser import MoveStatementParser
from .parsers.call_parser import CallStatementParser
from .parsers.if_parser import IfStatementParser
from .parsers.perform_parser import PerformStatementParser
from .parsers.evaluate_parser import EvaluateStatementParser
from .parsers.arithmetic_parsers import (
    AddStatementParser,
    SubtractStatementParser,
    MultiplyStatementParser,
    DivideStatementParser,
    ComputeStatementParser,
)

from .preprocess import normalize_fixed_format


class ParseState(Enum):
    """Parser state tracking for COBOL divisions and sections."""
    INITIAL = auto()
    IDENTIFICATION_DIVISION = auto()
    ENVIRONMENT_DIVISION = auto()
    DATA_DIVISION = auto()
    PROCEDURE_DIVISION = auto()


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
    """COBOL parser orchestrator using factory-based architecture.
    
    Delegates parsing to specialized components:
    - DivisionParserFactory for division parsing
    - StatementRegistry for statement parsing
    - TokenStream for lookahead-enabled token navigation
    
    Supports multiple dialects, error recovery modes, and memory management.
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
        """Initialize the COBOL parser with required configurations."""
        self.dialect = dialect
        self.error_recovery = error_recovery
        self.memory_config = memory_config or MemoryConfiguration()
        self.serialization_config = serialization_config or SerializationConfig()
        self.plugin_manager = plugin_manager or PluginManager()
        self.free_form = free_form

        # Parser state
        self.tokens: List[Token] = []
        self.current_token_index = 0
        self.parse_state = ParseState.INITIAL
        self.errors: List[ParseError] = []
        self.warnings: List[str] = []
        self.statistics = ParseStatistics()
        self.current_program: Optional[CobolProgram] = None
        self.stream: Optional[TokenStream] = None

        # Initialize factories and registries
        self._division_factory = DivisionParserFactory()
        self._register_division_parsers()
        
        self.registry = StatementRegistry()
        self._register_statement_parsers()

    def _register_division_parsers(self) -> None:
        """Register all division parsers in the factory."""
        self._division_factory.register_parser(
            DivisionType.IDENTIFICATION,
            IdentificationDivisionParser,
            instantiate=True
        )
        self._division_factory.register_parser(
            DivisionType.ENVIRONMENT,
            EnvironmentDivisionParser,
            instantiate=True
        )
        self._division_factory.register_parser(
            DivisionType.DATA,
            DataDivisionParser,
            instantiate=True
        )
        self._division_factory.register_parser(
            DivisionType.PROCEDURE,
            ProcedureDivisionParser,
            instantiate=True
        )

    def _register_statement_parsers(self) -> None:
        """Register all statement parsers in the registry."""
        self.registry.register(DisplayStatementParser())
        self.registry.register(MoveStatementParser())
        self.registry.register(CallStatementParser())
        self.registry.register(IfStatementParser())
        self.registry.register(PerformStatementParser())
        self.registry.register(EvaluateStatementParser())
        self.registry.register(AddStatementParser())
        self.registry.register(SubtractStatementParser())
        self.registry.register(MultiplyStatementParser())
        self.registry.register(DivideStatementParser())
        self.registry.register(ComputeStatementParser())

    @staticmethod
    def _skip_to_identification_division(content: str) -> str:
        """Skip all lines before IDENTIFICATION DIVISION, preserving line numbers."""
        lines = content.splitlines(keepends=True)
        id_div_pattern = re.compile(
            r"^\s*(IDENTIFICATION|ID)\s+(DIVISION|DIV)", re.IGNORECASE
        )

        for i, line in enumerate(lines):
            if id_div_pattern.search(line):
                blank_lines = ["\n"] * i
                return "".join(blank_lines + lines[i:])

        return content

    def parse(self, source: str, filename: str = "<string>", error_recovery: Optional[ErrorRecoveryMode] = None) -> ParseResult:
        """Parse COBOL source code into AST.
        
        Args:
            source: COBOL source code
            filename: Source filename for error reporting
            error_recovery: Error recovery mode (FAIL_FAST or COLLECT_ALL). 
                           Defaults to FAIL_FAST if not specified.
            
        Returns:
            ParseResult with AST and metadata
        """
        # Set error recovery mode if provided
        if error_recovery is not None:
            self.error_recovery = error_recovery
        
        self.statistics.reset()
        self.statistics.start_timing()
        self.errors.clear()
        self.warnings.clear()

        try:
            # Preprocess and tokenize
            cleaned_source = self._skip_to_identification_division(source)
            
            # Auto-detect fixed-format if not explicitly specified
            actual_free_form = self.free_form
            if not self.free_form:  # Only auto-detect if not explicitly set to free-form
                detected_fixed = _detect_fixed_format(cleaned_source)
                if detected_fixed:
                    # Preprocess fixed-format source
                    cleaned_source = normalize_fixed_format(cleaned_source.splitlines())
                    actual_free_form = True
                else:
                    # Source appears to be free-form
                    actual_free_form = True
            
            lexer = CobolLexer(
                cleaned_source, filename, self.dialect, free_form=actual_free_form
            )
            self.tokens = lexer.tokenize()

            if lexer.has_errors():
                for error in lexer.get_errors():
                    self.add_error(
                        ParseError(
                            f"Lexer error: {error.message}",
                            error.location.line if error.location else 1,
                            error.location.column if error.location else 1,
                        )
                    )
                if self.error_recovery == ErrorRecoveryMode.FAIL_FAST:
                    return self._create_result(None)

            # Initialize TokenStream and parse program
            self.stream = TokenStream(self.tokens)
            program = self.parse_program()

            self.statistics.end_timing()
            self.statistics.lines_parsed = len(source.splitlines())
            self.statistics.tokens_processed = len(self.tokens)

            return self._create_result(program)

        except Exception as e:
            self.add_error(ParseError(f"Parser error: {str(e)}", 1, 1))
            return self._create_result(None)

    def parse_file(self, filepath: str) -> ParseResult:
        """Parse COBOL source code from a file.
        
        Args:
            filepath: Path to COBOL source file
            
        Returns:
            ParseResult with AST and metadata
        """
        try:
            with open(filepath, "r", encoding="utf-8") as file:
                source = file.read()
            return self.parse(source, filepath)
        except IOError as e:
            self.add_error(ParseError(f"File error: {str(e)}", 1, 1))
            return self._create_result(None)

    def parse_program(self) -> Optional[CobolProgram]:
        """Parse a complete COBOL program delegating to division parsers.
        
        Uses DivisionParserFactory to parse IDENTIFICATION, ENVIRONMENT, DATA,
        and PROCEDURE divisions in sequence. Implements error recovery modes
        and coordinated error handling across divisions.
        """
        program_name = "UNKNOWN"
        program_location = self.get_current_location()
        errors_at_start = len(self.errors)

        # Create initial program (will be updated with metadata from ID division)
        self.current_program = CobolProgram(program_name, program_location)

        # Parse divisions in order: IDENTIFICATION -> ENVIRONMENT -> DATA -> PROCEDURE
        divisions_parsed = []
        
        try:
            if not self.stream:
                return self.current_program
                
            while not self.stream.is_empty():
                self.stream.skip_whitespace_and_comments()
                
                if self.stream.is_empty():
                    break

                # Try to find a parser for the current token
                parser = self._division_factory.find_parser(self.stream)
                if not parser:
                    break

                try:
                    # Set host on ProcedureDivisionParser for ParseContext creation
                    if hasattr(parser, 'set_host'):
                        parser.set_host(self)
                    elif hasattr(parser, 'host'):
                        parser.host = self
                    
                    division_ast = parser.parse(self.stream)
                    if division_ast:
                        divisions_parsed.append(division_ast)
                        # Cast to CobolDivision - parser.parse should return compatible type
                        if isinstance(division_ast, CobolDivision):
                            self.current_program.add_division(division_ast)
                        
                        # Update program name from IDENTIFICATION division
                        if hasattr(division_ast, 'metadata'):
                            metadata = getattr(division_ast, 'metadata', {})
                            if isinstance(metadata, dict) and 'program_id' in metadata:
                                program_name = metadata['program_id']
                                self.current_program.program_name = program_name
                            
                except Exception as e:
                    error = ParseError(str(e), 1, 1)
                    self.add_error(error)
                    if self.error_recovery == ErrorRecoveryMode.FAIL_FAST:
                        return self.current_program if divisions_parsed else None

        except Exception as e:
            self.add_error(ParseError(f"Division parsing error: {str(e)}", 1, 1))
            if self.error_recovery == ErrorRecoveryMode.FAIL_FAST:
                return self.current_program if divisions_parsed else None

        return self.current_program

    def get_current_location(self) -> SourceLocation:
        """Get current source location."""
        if self.stream and not self.stream.is_empty():
            token = self.stream.peek(0)
            if token:
                return token.location
        return SourceLocation(1, 1, 1)

    def add_error(self, error: ParseError) -> None:
        """Add a parse error."""
        self.errors.append(error)
        self.statistics.error_count += 1

    def add_warning(self, message: str) -> None:
        """Add a warning message."""
        self.warnings.append(message)
        self.statistics.warning_count += 1

    def _create_result(self, ast: Optional[CobolProgram]) -> ParseResult:
        """Create parse result with current state."""
        return ParseResult(
            ast=ast,
            errors=self.errors.copy(),
            warnings=self.warnings.copy(),
            statistics=self.statistics,
        )

    # ========== Backward Compatibility Methods ==========
    # For tests that directly call statement parsing methods

    def _get_statement_parser(self):
        """Find statement parser for current stream position."""
        if not self.stream and self.current_token_index < len(self.tokens):
            self.stream = TokenStream(self.tokens)
            self.stream._pos = self.current_token_index
        return self.registry.get_parser(self.stream) if self.stream else None

    def parse_call_statement(self):
        """Parse CALL statement (backward compatibility)."""
        return self._dispatch_statement_parser(CallStatementParser())

    def parse_move_statement(self):
        """Parse MOVE statement (backward compatibility)."""
        return self._dispatch_statement_parser(MoveStatementParser())

    def parse_display_statement(self):
        """Parse DISPLAY statement (backward compatibility)."""
        return self._dispatch_statement_parser(DisplayStatementParser())

    def parse_if_statement(self):
        """Parse IF statement (backward compatibility)."""
        return self._dispatch_statement_parser(IfStatementParser())

    def parse_perform_statement(self):
        """Parse PERFORM statement (backward compatibility)."""
        return self._dispatch_statement_parser(PerformStatementParser())

    def parse_evaluate_statement(self):
        """Parse EVALUATE statement (backward compatibility)."""
        return self._dispatch_statement_parser(EvaluateStatementParser())

    def parse_add_statement(self):
        """Parse ADD statement (backward compatibility)."""
        return self._dispatch_statement_parser(AddStatementParser())

    def parse_subtract_statement(self):
        """Parse SUBTRACT statement (backward compatibility)."""
        return self._dispatch_statement_parser(SubtractStatementParser())

    def parse_multiply_statement(self):
        """Parse MULTIPLY statement (backward compatibility)."""
        return self._dispatch_statement_parser(MultiplyStatementParser())

    def parse_divide_statement(self):
        """Parse DIVIDE statement (backward compatibility)."""
        return self._dispatch_statement_parser(DivideStatementParser())

    def parse_compute_statement(self):
        """Parse COMPUTE statement (backward compatibility)."""
        return self._dispatch_statement_parser(ComputeStatementParser())

    def _dispatch_statement_parser(self, parser):
        """Common dispatcher for statement parsers."""
        if not self.stream and self.current_token_index < len(self.tokens):
            self.stream = TokenStream(self.tokens)
            self.stream._pos = self.current_token_index
        
        if self.stream:
            try:
                if not self.stream.is_empty():
                    if parser.can_parse(self.stream):
                        # Create ParseContext for statement parser
                        context = ParseContext(self, self.registry)
                        result = parser.parse(self.stream, context)
                        self.current_token_index = self.stream._pos
                        return result
            except Exception:
                return None
        return None


def _detect_fixed_format(source: str) -> bool:
    """Detect if source appears to be in fixed-format COBOL.
    
    Returns True if source appears to be fixed-format, False if free-form.
    """
    lines = source.splitlines()
    non_empty_lines = [line for line in lines if line.strip()]
    
    if len(non_empty_lines) < 3:
        return False
    
    sample_size = min(10, len(non_empty_lines))
    fixed_format_indicators = 0
    
    for line in non_empty_lines[:sample_size]:
        if len(line) < 7:
            continue
            
        seq_area = line[:6]
        indicator = line[6] if len(line) > 6 else ' '
        
        seq_is_spaces_or_digits = (
            seq_area.strip() == '' or 
            seq_area.replace(' ', '').isdigit()
        )
        
        valid_indicator = indicator in (' ', '*', '/', '-', 'D', 'd')
        
        if seq_is_spaces_or_digits and valid_indicator:
            fixed_format_indicators += 1
    
    threshold = sample_size * 0.6
    return fixed_format_indicators >= threshold


def parse_cobol(
    source: str,
    filename: str = "<string>",
    dialect: DialectType = DialectType.IBM_ENTERPRISE,
    error_recovery: ErrorRecoveryMode = ErrorRecoveryMode.FAIL_FAST,
    free_form: bool = False,
    preprocess_fixed: bool | None = None,
) -> ParseResult:
    """Convenience function to parse COBOL source code.
    
    Automatically detects fixed-format COBOL and preprocesses if needed.
    
    Args:
        source: COBOL source code or path to COBOL file
        filename: Source filename for error reporting
        dialect: COBOL dialect
        error_recovery: Error recovery mode
        free_form: Whether source is in free-form format
        preprocess_fixed: Whether to preprocess fixed-format COBOL (auto-detect if None)
        
    Returns:
        ParseResult with AST and metadata
    """
    import os
    
    # Handle file paths
    if os.path.isfile(source):
        with open(source, 'r', encoding='utf-8', errors='replace') as f:
            file_content = f.read()
        if filename == "<string>":
            filename = source
        source = file_content
    
    # Auto-detect fixed-format if not explicitly specified
    if preprocess_fixed is None:
        detected_fixed = _detect_fixed_format(source)
        preprocess_fixed = detected_fixed
        # If we detected free-format (not fixed), ensure free_form is True
        if not detected_fixed and not free_form:
            free_form = True
    
    if preprocess_fixed:
        source = normalize_fixed_format(source.splitlines())
        free_form = True
    
    parser = CobolParser(
        dialect=dialect, error_recovery=error_recovery, free_form=free_form
    )
    return parser.parse(source, filename)
