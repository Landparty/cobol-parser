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
from typing import TYPE_CHECKING, Any, Literal, overload

# Core parsing infrastructure
from ._lines import split_source_lines
from .core.token_stream import TokenStream
from .lexer import CobolLexer, Token, TokenType
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
from .preprocess import (
    ALL_COMMENT_INDICATORS,
    TEXT_END_COL,
    TEXT_START_COL,
    normalize_fixed_format,
    preprocess_conditional_compilation,
    strip_compiler_directives,
)
from .preprocess.replace_statement import (
    apply_replace_statements,
    strip_unexpanded_copy_statements,
)
from .profiling import ProfilerContext, ProfilingResult

logger = logging.getLogger(__name__)

#: Unit kinds whose contained units nest under them (see
#: ``CobolParser._attach_new_unit``): a class holds its factory and object
#: units, and those hold their methods.
_OO_CONTAINER_KINDS: frozenset[str] = frozenset({"CLASS", "FACTORY", "OBJECT"})

# Pre-compiled regex for ID division detection (avoids re-compilation per parse call).
# Fixed-format source may carry a sequence area in columns 1-6, so an optional
# exactly-6-character digits/spaces prefix is allowed before the usual leading
# whitespace ("000100 IDENTIFICATION DIVISION."). Requiring exactly 6 such
# characters (not "up to 6 of anything digit-shaped") keeps random text that
# merely starts with digits from matching.
_ID_DIV_RE = re.compile(
    r"^(?:[0-9 ]{6})?\s*(IDENTIFICATION|ID)\s+(DIVISION|DIV)", re.IGNORECASE
)


@dataclass
class ParseResult:
    """Result of parsing operation with AST and metadata."""

    ast: CobolProgram | None
    errors: list[ParseError]
    warnings: list[str]
    statistics: ParseStatistics
    #: Expanded-line -> ``(origin file, origin line)``, set only by
    #: ``parse_cobol_with_expansion``. Every location on this result (and on
    #: every analyzer report derived from it) counts lines in the
    #: copybook-EXPANDED text; this is what maps one back onto the file a
    #: human edits. ``None`` when no expansion ran, in which case the two
    #: numbering schemes are the same thing.
    expansion_source_map: dict[int, tuple[str, int]] | None = None

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
        initial_warnings: list[str] | None = None,
        preprocess_fixed: bool | None = None,
    ):
        """Initialize the COBOL parser with required configurations.

        `initial_warnings`, when given, is added (via `add_warning`) at the
        top of the *first* `parse()` call, after `self.warnings` is cleared
        -- for diagnostics a caller already collected before constructing
        this parser (e.g. `parse_cobol()`'s own pre-normalization of
        fixed-format source, which runs before a `CobolParser` even
        exists). Consumed (cleared) after that first call so a `CobolParser`
        instance reused to `parse()` multiple sources doesn't keep
        re-appending warnings about a source it no longer reflects.

        `preprocess_fixed` mirrors `parse_cobol`'s parameter of the same
        name: None (the default) auto-detects fixed format when `free_form`
        is False -- the historical behavior; True always normalizes,
        regardless of what `_detect_fixed_format` would say (the
        `--source-format=fixed` escape hatch for layouts the detector
        declines); False never normalizes.
        """
        self.dialect = dialect
        self.error_recovery = error_recovery
        self.memory_config = memory_config or MemoryConfiguration()
        self.serialization_config = serialization_config or SerializationConfig()
        self.plugin_manager = plugin_manager or PluginManager()
        self.free_form = free_form
        self.preprocess_fixed = preprocess_fixed
        self._initial_warnings = list(initial_warnings) if initial_warnings else []

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
        """Blank every line before the IDENTIFICATION DIVISION, preserving
        line numbers -- except compiler directives.

        JCL, listing headers and other junk ahead of the header are dropped.
        A ``>>DEFINE`` / ``>>IF`` directive line is kept where it is: IBM
        allows ``>>DEFINE`` anywhere, and the conditional-compilation pass
        that runs later must still see it, or every ``>>IF`` on the symbol
        evaluates to FALSE. (``CBL`` / ``PROCESS`` option lines are removed
        by ``strip_compiler_directives`` right after this step.)
        """
        lines = split_source_lines(content, keepends=True)

        for i, line in enumerate(lines):
            if _ID_DIV_RE.search(line):
                kept = [
                    (
                        preceding
                        if preceding.strip().startswith(">>")
                        or preceding.strip()[6:8].strip().startswith(">>")
                        or preceding.strip().upper().startswith(("CBL", "PROCESS"))
                        else "\n"
                    )
                    for preceding in lines[:i]
                ]
                return "".join(kept + lines[i:])

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
        for _initial_warning in self._initial_warnings:
            self.add_warning(_initial_warning)
        # Consume once: these describe the source passed to the *first*
        # parse() call, not any later reuse of this instance.
        self._initial_warnings = []

        try:
            # Preprocess and tokenize
            cleaned_source = self._skip_to_identification_division(source)

            # Strip CBL/PROCESS compiler directives before fixed-format detection
            cleaned_source = strip_compiler_directives(cleaned_source)

            # Collects diagnostics from every preprocessing pass below
            # (fixed-format normalization, un-expanded COPY stripping,
            # REPLACE application) so they can be added to self.warnings in
            # one place once preprocessing settles.
            preprocess_warnings: list[str] = []

            # Auto-detect fixed-format if not explicitly specified.
            # preprocess_fixed=True skips detection and always normalizes
            # (the forced-layout escape hatch -- also how parse_cobol's
            # ValueError deferral keeps its already-made fixed decision on
            # exactly the layouts the detector declines); False skips this
            # whole block, never normalizing.
            actual_free_form = self.free_form
            if self.preprocess_fixed is True or (
                self.preprocess_fixed is None and not self.free_form
            ):
                detected_fixed = (
                    True
                    if self.preprocess_fixed
                    else _detect_fixed_format(cleaned_source)
                )
                if detected_fixed:
                    # Preprocess fixed-format source to free-form. An
                    # unterminated literal at EOF makes normalization raise; in
                    # that case record the error and, unless failing fast, fall
                    # back to a best-effort normalization that never raises
                    # (merge_continued_literals=False) so a single bad literal
                    # no longer loses the whole program under COLLECT_ALL.
                    source_lines = split_source_lines(cleaned_source)
                    try:
                        cleaned_source = normalize_fixed_format(
                            source_lines, warnings=preprocess_warnings
                        )
                    except ValueError as ve:
                        self.add_error(
                            ParseError(
                                str(ve),
                                line_number=len(source_lines),
                                column=1,
                            )
                        )
                        if self.error_recovery == ErrorRecoveryMode.FAIL_FAST:
                            self.statistics.end_timing()
                            return self._create_result(None)
                        # The raise happened partway through the line scan,
                        # so `preprocess_warnings` may already hold entries
                        # from lines processed before it -- the retry below
                        # rescans the same lines from the start and would
                        # duplicate them if not cleared first.
                        preprocess_warnings.clear()
                        cleaned_source = normalize_fixed_format(
                            source_lines,
                            merge_continued_literals=False,
                            warnings=preprocess_warnings,
                        )
                    actual_free_form = True
                else:
                    # Source is already free-form, no preprocessing needed:
                    # lex it as free-form (mirrors parse_cobol, which flips
                    # free_form on for undetected-fixed input). Lexing it
                    # with the fixed-format column rules instead sliced the
                    # first seven characters off every line.
                    actual_free_form = True
                logger.debug(
                    "Format auto-detection for %s: %s",
                    filename,
                    (
                        "fixed (normalized to free-form)"
                        if detected_fixed
                        else "free-form"
                    ),
                )

            # Source-text manipulation before lexing (mirrors a compiler's
            # COPY/REPLACE text phase). Strip un-expanded COPY statements so a
            # REPLACING pseudo-text operand does not leak into the token
            # stream, then apply REPLACE compiler-directing statements. Both
            # preserve line count. In the copybook-expansion pipeline COPY is
            # already inlined before this point, so the COPY strip is a no-op
            # there.
            # Conditional compilation (``>>DEFINE`` / ``>>IF`` / ``>>EVALUATE``)
            # runs first, exactly as the compiler orders it: a directive
            # decides which lines exist before COPY/REPLACE see them. Every
            # directive line and every line of a skipped block is blanked
            # in place, so line numbers are unchanged. Gated on the two
            # characters every directive starts with, so the common case
            # (no directives at all) costs one substring scan.
            if ">>" in cleaned_source:
                cleaned_source = preprocess_conditional_compilation(
                    cleaned_source, warnings=preprocess_warnings
                )
            cleaned_source = strip_unexpanded_copy_statements(
                cleaned_source, warnings=preprocess_warnings
            )
            cleaned_source = apply_replace_statements(
                cleaned_source, warnings=preprocess_warnings
            )
            for _warning in preprocess_warnings:
                self.add_warning(_warning)

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

            if lexer.has_warnings():
                for warning in lexer.get_warnings():
                    self.add_warning(f"Lexer warning: {warning}")

            # Initialize TokenStream and parse program. A `*>` floating
            # comment (IBM Enterprise COBOL 6.x) is layout wherever it sits:
            # it may end any line, including one that stops between a clause
            # keyword and its operand (``OCCURS 10 *> rows`` / ``INDEXED BY
            # IX``). Every sub-clause reader that skips line breaks would
            # otherwise have to skip COMMENT tokens too, and most did not --
            # the operand after the comment was dropped as an "unparsed
            # token", or (``OCCURS *> n`` / ``10 TIMES``) read as a new
            # item's level number. The lexer's own token list keeps them.
            self.stream = TokenStream(
                [t for t in self.tokens if t.type is not TokenType.COMMENT]
            )
            program = self.parse_program()
            if program is not None:
                for unit in program.program_units():
                    unit.serialization_config = self.serialization_config

            self.statistics.end_timing()
            self.statistics.lines_parsed = len(split_source_lines(source))
            # The CLI's --stats reports lines_processed; keep both counters in step.
            self.statistics.lines_processed = self.statistics.lines_parsed
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

    # The @overload stubs below are for static type checkers only and must
    # never be compiled: Cython's whole-module closed-source build evaluates
    # each stub's `param: T = ...` default against its annotation at class-
    # body execution time (CPython never does this), and under the release
    # build's optimization flags that mismatch doesn't raise a clean error --
    # it corrupts the compiled method table, and the real `parse()`/
    # `parse_cobol()` crash with a native access violation on the very next
    # call. Gating on TYPE_CHECKING keeps the overloads visible to mypy/IDEs
    # while making them runtime-invisible, so Cython never sees them at all.
    # See docs/superpowers/specs/2026-08-18-overload-cython-crash-fix.md.
    if TYPE_CHECKING:

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
        primary_program = CobolProgram(program_name, program_location)
        self.current_program = primary_program
        # Object-oriented units nest: a CLASS-ID unit holds its FACTORY and
        # OBJECT units, each holding METHOD-ID units. ``END METHOD`` / ``END
        # FACTORY`` / ``END OBJECT`` / ``END CLASS`` pop back to the parent.
        self._unit_stack: list[CobolProgram] = []

        # Parse divisions in order: IDENTIFICATION -> ENVIRONMENT -> DATA -> PROCEDURE
        divisions_parsed: list[Any] = []

        try:
            if not self.stream:
                return self.current_program

            while not self.stream.is_empty():
                self.stream.skip_whitespace_and_comments()

                if self.stream.is_empty():
                    break

                # IBM object-oriented COBOL unit markers that carry no
                # division header of their own: ``CLASS-ID.`` / ``METHOD-ID.``
                # without a preceding IDENTIFICATION DIVISION, the ``FACTORY.``
                # and ``OBJECT.`` paragraphs, and the ``END METHOD|FACTORY|
                # OBJECT|CLASS`` unit terminators.
                if self._handle_oo_unit_marker(primary_program, divisions_parsed):
                    continue

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
                    # END PROGRAM closes the current program unit; consume it
                    # and keep parsing — the compilation unit may contain more
                    # (stacked or nested) programs. Historically the loop
                    # broke here and everything after the first END PROGRAM
                    # was silently dropped.
                    if (
                        divisions_parsed
                        and current_value == "END"
                        and self._peek_is_end_program()
                    ):
                        self._consume_end_program_marker()
                        continue
                    # Only the end-of-input marker remains after at least one
                    # division parsed — a clean end, not an error.
                    if divisions_parsed and current_value == "EOF":
                        break
                    if not divisions_parsed or current_value not in ("END", "PROGRAM"):
                        self.add_error(
                            self.create_error(
                                f"No recognizable COBOL division found near '{current_token.value if current_token and current_token.value else 'EOF'}'",
                                self.get_current_location(),
                            )
                        )
                    break

                # A second IDENTIFICATION DIVISION starts a new program unit
                # in the same compilation unit. Parse it into its own
                # CobolProgram attached to the primary program instead of
                # merging (and mostly discarding) its content.
                if isinstance(
                    parser, IdentificationDivisionParser
                ) and self.current_program.has_division("IDENTIFICATION"):
                    new_program = CobolProgram("UNKNOWN", self.get_current_location())
                    self._attach_new_unit(primary_program, new_program)

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
                                unit_kind = metadata.get("unit_kind")
                                if unit_kind:
                                    self.current_program.unit_kind = str(unit_kind)

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
                        return primary_program if divisions_parsed else None
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
                        return primary_program if divisions_parsed else None

        except ParseError as pe:
            if pe not in self.errors:
                self.add_error(pe)
            if self.error_recovery == ErrorRecoveryMode.FAIL_FAST:
                return primary_program if divisions_parsed else None
        except Exception as e:
            self.add_error(
                ParseError(f"Division parsing error: {str(e)}", line_number=1, column=1)
            )
            if self.error_recovery == ErrorRecoveryMode.FAIL_FAST:
                return primary_program if divisions_parsed else None

        if primary_program.contained_programs:
            # Every unit below the primary one, nested ones included (an OO
            # class holds its factory/object units, which hold its methods).
            extra_units = primary_program.program_units()[1:]
            names = ", ".join(p.program_name for p in extra_units)
            self.add_warning(
                f"Compilation unit contains "
                f"{len(extra_units) + 1} program units; "
                f"additional program(s) [{names}] attached to "
                f"contained_programs of '{primary_program.program_name}'"
            )

        return primary_program

    def _attach_new_unit(
        self, primary_program: CobolProgram, new_program: CobolProgram
    ) -> None:
        """Make *new_program* the current unit, contained by the right parent.

        A method belongs to the factory/object unit it is written in, and a
        factory/object to its class, so inside an object-oriented unit the
        parent is the current unit (pushed for ``END ...`` to pop back to).
        Nested PROGRAM-ID units keep their historical flat attachment to
        the primary program.
        """
        parent = self.current_program or primary_program
        if parent.unit_kind in _OO_CONTAINER_KINDS:
            parent.add_contained_program(new_program)
            self._unit_stack.append(parent)
        else:
            primary_program.add_contained_program(new_program)
        self.current_program = new_program

    def _handle_oo_unit_marker(
        self, primary_program: CobolProgram, divisions_parsed: list[Any]
    ) -> bool:
        """Consume one object-oriented unit marker at the stream head.

        Handles ``CLASS-ID`` / ``METHOD-ID`` clauses written without an
        IDENTIFICATION DIVISION header, the ``FACTORY.`` / ``OBJECT.``
        paragraphs that open those units, and ``END METHOD [name].`` /
        ``END FACTORY.`` / ``END OBJECT.`` / ``END CLASS [name].``. Returns
        True when a marker was consumed (the caller continues its loop).
        """
        if not self.stream:
            return False
        token = self.stream.peek()
        value = (token.value or "").upper() if token else ""
        if not value:
            return False

        if value in ("CLASS-ID", "METHOD-ID"):
            location = self.get_current_location()
            if value == "CLASS-ID":
                name, inherits = IdentificationDivisionParser.parse_class_id_clause(
                    self.stream
                )
                kind = "CLASS"
            else:
                name = IdentificationDivisionParser.parse_method_id_clause(self.stream)
                inherits = None
                kind = "METHOD"
            unit = self.current_program or primary_program
            if unit.has_division("IDENTIFICATION") or divisions_parsed:
                unit = CobolProgram(name, location)
                self._attach_new_unit(primary_program, unit)
            unit.program_name = name
            unit.unit_kind = kind
            ident = CobolDivision("IDENTIFICATION", location)
            ident.metadata.update(
                {
                    "program_id": name,
                    "unit_kind": kind,
                    "program_attributes": [],
                    "inherits": inherits,
                }
            )
            unit.add_division(ident)
            divisions_parsed.append(ident)
            return True

        if value in ("FACTORY", "OBJECT"):
            nxt = self.stream.peek(1)
            if nxt is None or nxt.value != ".":
                return False
            location = self.get_current_location()
            self.stream.consume()  # FACTORY | OBJECT
            self.stream.consume()  # .
            unit = CobolProgram(value, location)
            self._attach_new_unit(primary_program, unit)
            unit.unit_kind = value
            ident = CobolDivision("IDENTIFICATION", location)
            ident.metadata.update(
                {"program_id": value, "unit_kind": value, "program_attributes": []}
            )
            unit.add_division(ident)
            divisions_parsed.append(ident)
            return True

        if value == "END":
            nxt = self.stream.peek(1)
            nxt_value = (nxt.value or "").upper() if nxt else ""
            if nxt_value not in ("METHOD", "FACTORY", "OBJECT", "CLASS"):
                return False
            self.stream.consume()  # END
            self.stream.consume()  # METHOD | FACTORY | OBJECT | CLASS
            self.stream.skip_whitespace_and_comments()
            tail = self.stream.peek()
            if tail is not None and tail.value and tail.value != ".":
                self.stream.consume()  # optional unit name
                self.stream.skip_whitespace_and_comments()
                tail = self.stream.peek()
            if tail is not None and tail.value == ".":
                self.stream.consume()
            if self._unit_stack:
                self.current_program = self._unit_stack.pop()
            else:
                self.current_program = primary_program
            return True

        return False

    def _peek_is_end_program(self) -> bool:
        """True if the stream is at an ``END PROGRAM`` marker."""
        if not self.stream:
            return False
        idx = 1
        while idx < 8:
            token = self.stream.peek(idx)
            if token is None:
                return False
            if token.type.name in ("NEWLINE", "WHITESPACE", "COMMENT"):
                idx += 1
                continue
            return bool(token.value) and token.value.upper() == "PROGRAM"
        return False

    def _consume_end_program_marker(self) -> None:
        """Consume ``END PROGRAM [name] [.]`` from the stream."""
        if not self.stream:
            return
        self.stream.consume()  # END
        self.stream.skip_whitespace_and_comments()
        token = self.stream.peek()
        if token and token.value and token.value.upper() == "PROGRAM":
            self.stream.consume()
        self.stream.skip_whitespace_and_comments()
        token = self.stream.peek()
        if token and token.value and token.value != ".":
            self.stream.consume()  # program name (identifier or literal)
        self.stream.skip_whitespace_and_comments()
        token = self.stream.peek()
        if token and token.value == ".":
            self.stream.consume()

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
            # Snapshot: self.statistics is reset in place on the next
            # parse() call, which would clobber this result's statistics.
            statistics=self.statistics.copy(),
        )


#: A change-tracking tag as shops stamp it into the sequence area (columns
#: 1-6): a single unbroken token of letters/digits and the punctuation that
#: turns up in ticket ids (``SAPR24``, ``28486``, ``GART``, ``JSINT``,
#: ``ABC-12``). The "no internal whitespace" property is what keeps ordinary
#: free-form statement text (``MOVE A``, ``IF A =``) out -- see
#: :func:`_sequence_area_is_fixed_like`.
_CHANGE_TAG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_/#$.-]*$")

#: Area A headers used to corroborate a *tagged* sequence area. Anchored at
#: the start of the code area (column 8+), which is exactly where free-form
#: source does not put them.
_AREA_A_HEADERS = (
    "IDENTIFICATION DIVISION",
    "ID DIVISION",
    "ENVIRONMENT DIVISION",
    "DATA DIVISION",
    "PROCEDURE DIVISION",
    "PROGRAM-ID",
)

#: How far into the file to look for the Area A anchor above. Division headers
#: cluster at the top of a program, so a bounded scan keeps this O(1)-ish on a
#: 28,000-line expanded source.
_HEADER_SCAN_LIMIT = 100


def _sequence_area_is_fixed_like(seq_area: str) -> tuple[bool, bool]:
    """Classify a line's columns 1-6 as fixed-format evidence.

    Returns ``(strict, relaxed)``:

    * ``strict`` -- blank or all-digits, the two conventional sequence-area
      fills. This is the historical rule and still decides on its own.
    * ``relaxed`` -- additionally allows a change-tracking *tag*
      (:data:`_CHANGE_TAG_RE`). Only ever consulted together with the Area A
      anchor in :func:`_detect_fixed_format`, because a bare tag test alone
      would also match free-form lines whose first six characters happen to
      be a word followed by a blank column 7 (``ACCEPT X``, ``SEARCH T``).
    """
    stripped = seq_area.strip()
    if stripped == "" or seq_area.replace(" ", "").isdigit():
        return True, True
    if _CHANGE_TAG_RE.match(stripped):
        return False, True
    return False, False


def _has_area_a_division_header(non_empty_lines: list[str]) -> bool:
    """True when a division/PROGRAM-ID header starts in the code area.

    Fixed-format source puts these in Area A (columns 8-11); free-form source
    puts them at column 1, where ``line[7:]`` slices into the middle of the
    word (``IDENTIFICATION DIVISION.`` -> ``ICATION DIVISION.``) and cannot
    match. That asymmetry is what makes this a safe corroborating signal for
    a sequence area holding something other than blanks or digits.

    A header only counts at a word boundary -- followed by a period, a
    space, or end of text -- so an identifier that merely starts with a
    header string (``PROGRAM-ID-VAL``, ``DATA-DIVISION-FLAG``) in free-form
    source indented past column 8 can never anchor rule 2 and drag a
    genuine free-form program into normalization.

    Only candidate lines consume the ``_HEADER_SCAN_LIMIT`` budget: comment
    lines (column 7 indicator) and too-short lines are skipped without
    counting, because the tag-stamping shops this rule exists for are the
    same shops that open every program with a 100+-line change-history
    banner block -- counting those against the window would push the
    IDENTIFICATION DIVISION header out of reach and re-introduce the very
    misclassification rule 2 fixes.
    """
    scanned = 0
    for line in non_empty_lines:
        if scanned >= _HEADER_SCAN_LIMIT:
            break
        if len(line) < 8 or line[6] in ALL_COMMENT_INDICATORS:
            continue
        scanned += 1
        text = line[TEXT_START_COL - 1 : TEXT_END_COL].lstrip().upper()
        for header in _AREA_A_HEADERS:
            if text.startswith(header) and (
                len(text) == len(header) or text[len(header)] in " ."
            ):
                return True
    return False


def _detect_fixed_format(source: str) -> bool:
    """Detect if source appears to be in fixed-format COBOL.

    Returns True if source appears to be fixed-format, False if free-form.

    Two rules, in order:

    1. **Strict** -- at least 60% of the sampled lines carry a blank or
       all-digit sequence area with a valid indicator column. Unchanged
       historical behavior; decides on its own.
    2. **Tagged sequence area** -- the same 60% bar, but also counting lines
       whose columns 1-6 hold a change-tracking tag (``SAPR24``, ``28486``),
       *and* requiring an Area A division header to corroborate. Shops that
       stamp ticket ids into the sequence area used to fail rule 1 outright,
       so the whole file was misclassified as free-form, normalization was
       skipped, and the tag text lexed as code -- surfacing as stray
       identifier/number tokens before the first division. The corroborating
       anchor is what keeps genuine free-form source (which never puts a
       division header at column 8) from being dragged in by rule 2.
    """
    lines = split_source_lines(source)
    non_empty_lines = [line for line in lines if line.strip()]

    if len(non_empty_lines) < 3:
        return False

    sample_size = min(10, len(non_empty_lines))
    strict_hits = 0
    relaxed_hits = 0

    for line in non_empty_lines[:sample_size]:
        if len(line) < 7:
            continue

        seq_area = line[:6]
        indicator = line[6]  # the len(line) < 7 guard above makes this safe

        valid_indicator = indicator in (" ", "-") or indicator in ALL_COMMENT_INDICATORS
        if not valid_indicator:
            continue

        strict, relaxed = _sequence_area_is_fixed_like(seq_area)
        strict_hits += strict
        relaxed_hits += relaxed

    threshold = sample_size * 0.6
    if strict_hits >= threshold:
        return True
    return relaxed_hits >= threshold and _has_area_a_division_header(non_empty_lines)


# See the matching comment on CobolParser.parse -- same reason these stubs
# are TYPE_CHECKING-only rather than unconditional @overload.
if TYPE_CHECKING:

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
        preprocess_fixed: Whether to preprocess fixed-format COBOL. None
            (default) auto-detects; True always normalizes, even for layouts
            the detector declines; False never normalizes -- the source is
            lexed as-is in the mode ``free_form`` selects, with no
            auto-detection anywhere on the path

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

    # What the CobolParser instance below is told about fixed-format
    # preprocessing. None on the happy path (the source is normalized right
    # here, then lexed free-form, so the parser must not detect/normalize
    # again); False when the caller explicitly disabled normalization
    # (threaded through so CobolParser.parse does not re-run auto-detection
    # and normalize anyway); True only on the ValueError deferral below.
    parser_preprocess_fixed: bool | None = None

    # Auto-detect fixed-format if not explicitly specified
    if preprocess_fixed is None:
        detected_fixed = _detect_fixed_format(source_str)
        preprocess_fixed = detected_fixed
        # If we detected free-format (not fixed), ensure free_form is True
        if not detected_fixed and not free_form:
            free_form = True
    elif not preprocess_fixed:
        parser_preprocess_fixed = False

    # Collects normalize_fixed_format's overflow/etc. diagnostics so they can
    # reach the CobolParser instance below via `initial_warnings` -- this
    # normalization runs before that instance exists, and its own
    # `self.warnings` gets cleared at the top of `parse()`, so passing the
    # list at construction time is the only way these survive.
    normalize_warnings: list[str] = []

    if preprocess_fixed:
        try:
            source_str = normalize_fixed_format(
                split_source_lines(source_str), warnings=normalize_warnings
            )
            free_form = True
        except ValueError as exc:
            # Preprocessing hit an unterminated string literal at EOF. Rather
            # than losing the whole program here, leave the source un-normalized
            # and defer to CobolParser.parse's recovery, which records the
            # error once and, under COLLECT_ALL, retries with
            # merge_continued_literals=False for a partial AST; FAIL_FAST
            # still aborts. The fixed decision already made here (whether
            # detected or forced by the caller) is passed through as
            # preprocess_fixed=True rather than letting the parser re-run
            # auto-detection: for layouts the detector declines -- the very
            # case --source-format=fixed exists for -- re-detection would
            # return False and silently drop the forced normalization along
            # with the unterminated-literal diagnostic. free_form=False so
            # the parser's normalization path runs even if the caller passed
            # free_form=True. Discard any overflow warnings collected before
            # the raise -- CobolParser.parse() re-normalizes the same lines
            # from scratch below and will collect its own, complete set.
            normalize_warnings.clear()
            free_form = False
            parser_preprocess_fixed = True
            logger.debug(
                "Deferring fixed-format preprocessing recovery to parser for %s: %s",
                filename,
                exc,
                exc_info=True,
            )

    parser = CobolParser(
        dialect=dialect,
        error_recovery=error_recovery,
        free_form=free_form,
        initial_warnings=normalize_warnings,
        preprocess_fixed=parser_preprocess_fixed,
    )
    return parser.parse(  # type: ignore[no-any-return]
        source_str,
        filename,
        enable_profiling=enable_profiling,  # type: ignore[call-overload]
        top_n=top_n,
        prof_output=prof_output,
    )
