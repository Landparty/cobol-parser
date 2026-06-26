"""COBOL parser implementation with factory-based architecture.

This module provides delegating CobolParser that orchestrates parsing through:
- DivisionParserFactory for IDENTIFICATION, ENVIRONMENT, DATA, PROCEDURE divisions
- ProcedureDivisionParser with its own StatementParserRegistry for statement parsing
- TokenStream abstraction for lookahead and error recovery
"""

import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Literal, overload

# Core parsing infrastructure
from .core.token_stream import TokenStream
from .lexer import CobolLexer, Token
from .models.ast_base import SourceLocation
from .models.program import CobolDivision, CobolProgram
from .parsers.divisions.data import DataDivisionParser
from .parsers.divisions.environment import EnvironmentDivisionParser
from .parsers.divisions.factory import DivisionParserFactory, DivisionType
from .parsers.divisions.identification import IdentificationDivisionParser
from .parsers.divisions.procedure import ProcedureDivisionParser
from .plugins.core import (
    DialectType,
    ErrorRecoveryMode,
    MemoryConfiguration,
    ParseError,
    ParseStatistics,
    PluginManager,
    SerializationConfig,
)
from .preprocess import normalize_fixed_format, strip_compiler_directives
from .profiling import ProfilerContext, ProfilingResult

logger = logging.getLogger(__name__)

# Pre-compiled regex for ID division detection (avoids re-compilation per parse call)
_ID_DIV_RE = re.compile(r"^\s*(IDENTIFICATION|ID)\s+(DIVISION|DIV)", re.IGNORECASE)


@dataclass
class ParseResult:
    """Result of parsing operation with AST and metadata."""

    ast: CobolProgram | None
    errors: list[ParseError]
    warnings: list[str]
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
        memory_config: MemoryConfiguration | None = None,
        serialization_config: SerializationConfig | None = None,
        plugin_manager: PluginManager | None = None,
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
        self.tokens: list[Token] = []
        self.errors: list[ParseError] = []
        self.warnings: list[str] = []
        self.statistics = ParseStatistics()
        self.current_program: CobolProgram | None = None
        self.stream: TokenStream | None = None
        self._error_limit_reached: bool = False

        # Initialize division parser factory
        self._division_factory = DivisionParserFactory()
        self._register_division_parsers()

    def _register_division_parsers(self) -> None:
        """Register all division parsers in the factory."""
        self._division_factory.register_parser(
            DivisionType.IDENTIFICATION, IdentificationDivisionParser, instantiate=True
        )
        self._division_factory.register_parser(
            DivisionType.ENVIRONMENT, EnvironmentDivisionParser, instantiate=True
        )
        self._division_factory.register_parser(
            DivisionType.DATA, DataDivisionParser, instantiate=True
        )
        self._division_factory.register_parser(
            DivisionType.PROCEDURE, ProcedureDivisionParser, instantiate=True
        )

    @staticmethod
    def _skip_to_identification_division(content: str) -> str:
        """Skip all lines before IDENTIFICATION DIVISION, preserving line numbers."""
        lines = content.splitlines(keepends=True)

        for i, line in enumerate(lines):
            if _ID_DIV_RE.search(line):
                blank_lines = ["\n"] * i
                return "".join(blank_lines + lines[i:])

        return content

    def _parse_core(
        self,
        source: str,
        filename: str = "<string>",
        error_recovery: ErrorRecoveryMode | None = None,
    ) -> ParseResult:
        """Parse COBOL source code into AST (core implementation).

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

        logger.info(
            "Parsing %s: %d chars, dialect=%s, recovery=%s, free_form=%s",
            filename,
            len(source),
            getattr(self.dialect, "name", self.dialect),
            getattr(self.error_recovery, "name", self.error_recovery),
            self.free_form,
        )

        self.statistics.reset()
        self.statistics.start_timing()
        self.errors.clear()
        self.warnings.clear()
        self._error_limit_reached = False

        try:
            # Preprocess and tokenize
            cleaned_source = self._skip_to_identification_division(source)

            # Strip CBL/PROCESS compiler directives before fixed-format detection
            cleaned_source = strip_compiler_directives(cleaned_source)

            # Auto-detect fixed-format if not explicitly specified
            actual_free_form = self.free_form
            if (
                not self.free_form
            ):  # Only auto-detect if not explicitly set to free-form
                detected_fixed = _detect_fixed_format(cleaned_source)
                if detected_fixed:
                    # Preprocess fixed-format source to free-form
                    cleaned_source = normalize_fixed_format(cleaned_source.splitlines())
                    actual_free_form = True
                else:
                    # Source is already free-form, no preprocessing needed
                    actual_free_form = False
                logger.debug(
                    "Format auto-detection for %s: %s",
                    filename,
                    (
                        "fixed (normalized to free-form)"
                        if detected_fixed
                        else "free-form"
                    ),
                )

            lexer = CobolLexer(
                cleaned_source, filename, self.dialect, free_form=actual_free_form
            )
            self.tokens = lexer.tokenize()
            logger.debug("Lexer produced %d tokens for %s", len(self.tokens), filename)

            if lexer.has_errors():
                lexer_errors = lexer.get_errors()
                logger.debug(
                    "Lexer reported %d error(s) for %s", len(lexer_errors), filename
                )
                for error in lexer_errors:
                    self.add_error(
                        ParseError(
                            f"Lexer error: {error.message}",
                            line_number=error.location.line if error.location else 1,
                            column=error.location.column if error.location else 1,
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

            logger.info(
                "Finished parsing %s: success=%s, errors=%d, warnings=%d, "
                "divisions=%d",
                filename,
                program is not None and not self.errors,
                len(self.errors),
                len(self.warnings),
                len(program.divisions) if program is not None else 0,
            )

            return self._create_result(program)

        except ParseError as pe:
            # Already-located parse errors propagate verbatim so callers see
            # the original line/column rather than a generic line-1 message.
            logger.debug(
                "ParseError propagated to _parse_core for %s: %s",
                filename,
                pe,
                exc_info=True,
            )
            if pe not in self.errors:
                self.add_error(pe)
            return self._create_result(None)
        except Exception as e:
            # Top-level safety net: ``parse()`` must not raise unexpected
            # exceptions. Preserve the cause chain so tracebacks can be
            # recovered during debugging.
            logger.debug(
                "Unexpected exception caught by _parse_core safety net for %s: %s",
                filename,
                e,
                exc_info=True,
            )
            err = ParseError(f"Parser error: {e}", line_number=1, column=1)
            err.__cause__ = e
            self.add_error(err)
            return self._create_result(None)

    @overload
    def parse(
        self,
        source: str,
        filename: str = ...,
        error_recovery: ErrorRecoveryMode | None = ...,
        enable_profiling: Literal[False] = ...,
        top_n: int = ...,
        prof_output: str | None = ...,
    ) -> ParseResult: ...

    @overload
    def parse(
        self,
        source: str,
        filename: str = ...,
        error_recovery: ErrorRecoveryMode | None = ...,
        enable_profiling: Literal[True] = ...,
        top_n: int = ...,
        prof_output: str | None = ...,
    ) -> tuple[ParseResult, ProfilingResult]: ...

    def parse(
        self,
        source: str,
        filename: str = "<string>",
        error_recovery: ErrorRecoveryMode | None = None,
        enable_profiling: bool = False,
        top_n: int = 50,
        prof_output: str | None = None,
    ) -> "ParseResult | tuple[ParseResult, ProfilingResult]":
        if not enable_profiling:
            return self._parse_core(source, filename, error_recovery)
        ctx = ProfilerContext(top_n=top_n, prof_output=prof_output)
        with ctx:
            result = self._parse_core(source, filename, error_recovery)
        assert ctx.result is not None
        # Keep ParseStatistics timing consistent with profiler wall-clock measurement
        result.statistics.parse_time_seconds = ctx.result.wall_clock_s
        result.statistics.total_time_ms = ctx.result.wall_clock_s * 1000.0
        return result, ctx.result

    def parse_file(self, filepath: str) -> ParseResult:
        """Parse COBOL source code from a file.

        Args:
            filepath: Path to COBOL source file

        Returns:
            ParseResult with AST and metadata
        """
        try:
            with open(filepath, encoding="utf-8") as file:
                source = file.read()
            return self.parse(source, filepath)
        except OSError as e:
            self.add_error(ParseError(f"File error: {str(e)}", line_number=1, column=1))
            return self._create_result(None)

    def parse_program(self) -> CobolProgram | None:
        """Parse a complete COBOL program delegating to division parsers.

        Uses DivisionParserFactory to parse IDENTIFICATION, ENVIRONMENT, DATA,
        and PROCEDURE divisions in sequence. Implements error recovery modes
        and coordinated error handling across divisions.
        """
        program_name = "UNKNOWN"
        program_location = self.get_current_location()

        # Create initial program (will be updated with metadata from ID division)
        self.current_program = CobolProgram(program_name, program_location)

        # Parse divisions in order: IDENTIFICATION -> ENVIRONMENT -> DATA -> PROCEDURE
        divisions_parsed: list[Any] = []

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
                    current_token = self.stream.peek()
                    current_value = (
                        current_token.value.upper()
                        if current_token and current_token.value
                        else "EOF"
                    )
                    logger.debug(
                        "No division parser matched near %r (divisions parsed so "
                        "far: %d)",
                        current_value,
                        len(divisions_parsed),
                    )
                    if not divisions_parsed or current_value not in ("END", "PROGRAM"):
                        self.add_error(
                            self.create_error(
                                f"No recognizable COBOL division found near '{current_token.value if current_token and current_token.value else 'EOF'}'",
                                self.get_current_location(),
                            )
                        )
                    break

                try:
                    # Set host on ProcedureDivisionParser for ParseContext creation
                    set_host = getattr(parser, "set_host", None)
                    if callable(set_host):
                        set_host(self)
                    elif hasattr(parser, "host"):
                        parser.host = self

                    logger.debug("Dispatching to %s", type(parser).__name__)
                    division_ast = parser.parse(self.stream)
                    if division_ast:
                        divisions_parsed.append(division_ast)
                        # Cast to CobolDivision - parser.parse should return compatible type
                        if isinstance(division_ast, CobolDivision):
                            self.current_program.add_division(division_ast)

                        # Update program name from IDENTIFICATION division
                        if hasattr(division_ast, "metadata"):
                            metadata = getattr(division_ast, "metadata", {})
                            if isinstance(metadata, dict) and "program_id" in metadata:
                                program_name = metadata["program_id"]
                                self.current_program.program_name = program_name

                except ParseError as pe:
                    # Already-formatted parse error from a division/statement
                    # parser; record verbatim so location info is preserved.
                    logger.debug(
                        "ParseError from %s: %s",
                        type(parser).__name__,
                        pe,
                        exc_info=True,
                    )
                    if pe not in self.errors:
                        self.add_error(pe)
                    if self.error_recovery == ErrorRecoveryMode.FAIL_FAST:
                        logger.debug("FAIL_FAST: aborting division loop")
                        return self.current_program if divisions_parsed else None
                except Exception as e:
                    logger.debug(
                        "Unexpected exception from %s: %s",
                        type(parser).__name__,
                        e,
                        exc_info=True,
                    )
                    error = ParseError(str(e), line_number=1, column=1)
                    self.add_error(error)
                    if self.error_recovery == ErrorRecoveryMode.FAIL_FAST:
                        logger.debug("FAIL_FAST: aborting division loop")
                        return self.current_program if divisions_parsed else None

        except ParseError as pe:
            if pe not in self.errors:
                self.add_error(pe)
            if self.error_recovery == ErrorRecoveryMode.FAIL_FAST:
                return self.current_program if divisions_parsed else None
        except Exception as e:
            self.add_error(
                ParseError(f"Division parsing error: {str(e)}", line_number=1, column=1)
            )
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

    def create_error(
        self, message: str, location: SourceLocation | None = None
    ) -> ParseError:
        """Create a ParseError from a source location."""
        if location and hasattr(location, "line") and hasattr(location, "column"):
            return ParseError(
                message,
                line_number=location.line,
                column=location.column,
                location=location,
            )
        return ParseError(message, line_number=1, column=1)

    def add_error(self, error: ParseError) -> None:
        """Add a parse error, respecting the configured max_error_count limit."""
        if self._error_limit_reached:
            return
        max_errors = self.memory_config.max_error_count
        if self.statistics.error_count >= max_errors:
            self._error_limit_reached = True
            logger.info(
                "Error limit reached (%d); further errors suppressed", max_errors
            )
            # Use the triggering error's location so users can see where
            # suppression began rather than being pointed at line 1.
            self.errors.append(
                ParseError(
                    f"Error limit reached ({max_errors}); further errors suppressed",
                    line_number=getattr(error, "line_number", None),
                    column=getattr(error, "column", None),
                    file_path=getattr(error, "file_path", None),
                )
            )
            self.statistics.error_count += 1
            return
        logger.info(
            "Parse error at line %s, column %s: %s",
            getattr(error, "line_number", None),
            getattr(error, "column", None),
            error,
        )
        self.errors.append(error)
        self.statistics.error_count += 1

    def add_warning(self, message: str) -> None:
        """Add a warning message."""
        self.warnings.append(message)
        self.statistics.warning_count += 1

    def _create_result(self, ast: CobolProgram | None) -> ParseResult:
        """Create parse result with current state."""
        return ParseResult(
            ast=ast,
            errors=self.errors.copy(),
            warnings=self.warnings.copy(),
            statistics=self.statistics,
        )


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
        indicator = line[6] if len(line) > 6 else " "

        seq_is_spaces_or_digits = (
            seq_area.strip() == "" or seq_area.replace(" ", "").isdigit()
        )

        valid_indicator = indicator in (" ", "*", "/", "-", "D", "d")

        if seq_is_spaces_or_digits and valid_indicator:
            fixed_format_indicators += 1

    threshold = sample_size * 0.6
    return fixed_format_indicators >= threshold


@overload
def parse_cobol(
    source: str | os.PathLike[str],
    filename: str = ...,
    dialect: DialectType = ...,
    error_recovery: ErrorRecoveryMode = ...,
    free_form: bool = ...,
    preprocess_fixed: bool | None = ...,
    enable_profiling: Literal[False] = ...,
    top_n: int = ...,
    prof_output: str | None = ...,
) -> ParseResult: ...


@overload
def parse_cobol(
    source: str | os.PathLike[str],
    filename: str = ...,
    dialect: DialectType = ...,
    error_recovery: ErrorRecoveryMode = ...,
    free_form: bool = ...,
    preprocess_fixed: bool | None = ...,
    enable_profiling: Literal[True] = ...,
    top_n: int = ...,
    prof_output: str | None = ...,
) -> tuple[ParseResult, ProfilingResult]: ...


def parse_cobol(
    source: str | os.PathLike[str],
    filename: str = "<string>",
    dialect: DialectType = DialectType.IBM_ENTERPRISE,
    error_recovery: ErrorRecoveryMode = ErrorRecoveryMode.FAIL_FAST,
    free_form: bool = False,
    preprocess_fixed: bool | None = None,
    enable_profiling: bool = False,
    top_n: int = 50,
    prof_output: str | None = None,
) -> "ParseResult | tuple[ParseResult, ProfilingResult]":
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
    # Normalize PathLike to str before applying the "looks like a path" heuristics.
    # This preserves compatibility with pathlib.Path and other os.PathLike inputs
    # while still avoiding syscalls on large/multi-line source strings.
    try:
        source_str = os.fspath(source)
        is_pathlike = True
    except TypeError:
        # source is already a str (or something else that's not PathLike)
        source_str = source  # type: ignore[assignment]
        is_pathlike = False

    # Handle file paths. The check is gated on the input "looking like" a path
    # before touching the filesystem so we don't (a) issue an `os.path.isfile`
    # syscall on every parse_cobol() call against a multi-KB source string, or
    # (b) silently read from disk if a COBOL source happens to contain a
    # newline-free prefix that resolves to a real file. A real path is short,
    # has no embedded newlines, and is plausibly a single-line string.
    # PathLike objects always go through the file-path branch.
    if (
        is_pathlike
        or (
            isinstance(source_str, str)
            and len(source_str) < 4096
            and "\n" not in source_str
            and "\r" not in source_str
        )
    ) and os.path.isfile(source_str):
        with open(source_str, encoding="utf-8", errors="replace") as f:
            file_content = f.read()
        if filename == "<string>":
            filename = source_str
        source_str = file_content

    # Strip CBL/PROCESS compiler directives before fixed-format detection
    source_str = strip_compiler_directives(source_str)

    # Auto-detect fixed-format if not explicitly specified
    if preprocess_fixed is None:
        detected_fixed = _detect_fixed_format(source_str)
        preprocess_fixed = detected_fixed
        # If we detected free-format (not fixed), ensure free_form is True
        if not detected_fixed and not free_form:
            free_form = True

    if preprocess_fixed:
        try:
            source_str = normalize_fixed_format(source_str.splitlines())
        except ValueError as exc:
            # Preprocessing failed (e.g. unterminated string literal at EOF).
            # Return a result with no AST and the preprocessing error so callers
            # can handle it gracefully under COLLECT_ALL error recovery.
            logger.debug(
                "Fixed-format preprocessing failed for %s: %s",
                filename,
                exc,
                exc_info=True,
            )
            err = ParseError(str(exc), line_number=0, column=0)
            stats = ParseStatistics()
            return ParseResult(ast=None, errors=[err], warnings=[], statistics=stats)
        free_form = True

    parser = CobolParser(
        dialect=dialect, error_recovery=error_recovery, free_form=free_form
    )
    return parser.parse(  # type: ignore[no-any-return]
        source_str,
        filename,
        enable_profiling=enable_profiling,  # type: ignore[call-overload]
        top_n=top_n,
        prof_output=prof_output,
    )
