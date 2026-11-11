"""COBOL parser implementation with factory-based architecture.

This module provides delegating CobolParser that orchestrates parsing through:
- DivisionParserFactory for IDENTIFICATION, ENVIRONMENT, DATA, PROCEDURE divisions
- ProcedureDivisionParser with its own StatementParserRegistry for statement parsing
- TokenStream abstraction for lookahead and error recovery
"""

import logging
import re
import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, overload

# Core parsing infrastructure
from ._lines import split_source_lines
from ._source_text.normalize import ID_DIVISION_HEADER_RE
from ._source_text.source_format import (
    _sequence_area_is_fixed_like,  # noqa: F401
    debug_line_numbers,
    detect_fixed_format,
    normalize_with_recovery,
)
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
    SerializationConfig,
)
from .preprocess import (
    copybook_expander,
    preprocess_conditional_compilation,
    strip_compiler_directives,
)
from .preprocess.replace_statement import (
    apply_replace_statements,
    find_replace_statement_spans,
    strip_unexpanded_copy_statements,
)
from .profiling import ProfilerContext, ProfilingResult

logger = logging.getLogger(__name__)


#: IDENTIFICATION DIVISION comment-entry paragraphs, as the AST's metadata
#: keys them.
_COMMENT_ENTRY_KEYS = (
    "author",
    "installation",
    "date_written",
    "date_compiled",
    "security",
    "remarks",
)
#: DATA DIVISION text where a comment-entry should hold prose.
_SWALLOWED_DATA_RE = re.compile(
    r"\b(?:DATA\s+DIVISION|(?:WORKING-STORAGE|LINKAGE|LOCAL-STORAGE|FILE)"
    r"\s+SECTION)\b",
    re.IGNORECASE,
)


def _debugging_mode_on(unit: CobolProgram) -> bool:
    """Whether *unit*'s SOURCE-COMPUTER paragraph says WITH DEBUGGING MODE."""
    env = unit.environment_division
    if env is None:
        return False
    for section in env.sections:
        if section.section_name != "CONFIGURATION":
            continue
        entry = section.get_metadata("source_computer")
        if isinstance(entry, dict) and entry.get("debugging_mode"):
            return True
    return False


def dropped_debug_lines_warning(location: str, count: int) -> str:
    """The warning for *count* debugging lines dropped under DEBUGGING MODE.

    *location* names the first of them (``"Line 12"``, or with a file in
    front when copybook expansion places it in a member). One spelling for
    the parser and ``parse_cobol_with_expansion``, which both raise it.
    """
    return (
        f"{location}: SOURCE-COMPUTER is WITH DEBUGGING MODE, but {count} "
        f"{DROPPED_DEBUG_LINES_MARKER} were dropped as comments; parse with "
        "debug_lines=True (CLI --debug-lines, cobol.yml project.debug_lines: "
        "true) to compile them as code, as the compiler does"
    )


#: The words every dropped-debugging-lines warning carries (see above).
DROPPED_DEBUG_LINES_MARKER = "debugging line(s) (D in column 7)"


def debugging_mode_on(program: CobolProgram) -> bool:
    """Whether any unit of *program* declares SOURCE-COMPUTER WITH DEBUGGING MODE."""
    return any(_debugging_mode_on(unit) for unit in program.program_units())


#: Unit kinds whose contained units nest under them (see
#: ``CobolParser._attach_new_unit``): a class holds its factory and object
#: units, and those hold their methods.
_OO_CONTAINER_KINDS: frozenset[str] = frozenset({"CLASS", "FACTORY", "OBJECT"})

# Pre-compiled regex for ID division detection (avoids re-compilation per parse call).
# Fixed-format source may carry a sequence area in columns 1-6, so an optional
# exactly-6-character prefix followed by a blank column 7 is allowed before the
# usual leading whitespace ("000100 IDENTIFICATION DIVISION."). The prefix may
# be any six characters -- a change tag ("CHG001") included: accepting only
# digits/blanks there skipped a tagged outer header and blanked the whole
# outer program up to a nested program's header (#252).
_ID_DIV_RE = ID_DIVISION_HEADER_RE

#: Former home of the format detector (now
#: ``preprocess.source_format.detect_fixed_format``), kept importable
#: under its old name, as is ``_sequence_area_is_fixed_like`` above.
_detect_fixed_format = detect_fixed_format


@dataclass
class ParseResult:
    """Result of parsing operation with AST and metadata.

    ``ast`` is ``None`` only when lexing, preprocessing, file I/O or the
    parser itself failed (or a ``FAIL_FAST`` error stopped the parse). Text
    in which no division is recognised still yields a ``CobolProgram``
    named ``"UNKNOWN"`` with no divisions, next to a "No recognizable COBOL
    division found" error -- callers that partially report on failed
    parses (``lint``, ``health``) rely on it. Test ``ast.divisions``, not
    just ``ast is not None``, for "something usable exists" (#368).
    """

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
    #: Every copybook file ``parse_cobol_with_expansion`` opened, in order --
    #: including a member that contributed no line of its own (one that only
    #: COPYs another, or holds only comments), which the source map never
    #: names. What a cache must stamp (#763).
    expansion_copybooks: list[str] = field(default_factory=list)

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

    Supports multiple dialects, error recovery modes, and a recorded-error cap
    (``MemoryConfiguration.max_error_count``; its memory fields are not
    enforced).
    """

    def __init__(
        self,
        dialect: DialectType = DialectType.IBM_ENTERPRISE,
        error_recovery: ErrorRecoveryMode = ErrorRecoveryMode.FAIL_FAST,
        memory_config: MemoryConfiguration | None = None,
        serialization_config: SerializationConfig | None = None,
        free_form: bool = False,
        initial_warnings: list[str] | None = None,
        preprocess_fixed: bool | None = None,
        debug_lines: bool = False,
    ):
        """Initialize the COBOL parser with required configurations.

        `initial_warnings`, when given, is added (via `add_warning`) at the
        top of the *first* `parse()` call, after `self.warnings` is cleared
        -- for diagnostics a caller already collected before constructing
        this parser. Consumed (cleared) after that first call so a `CobolParser`
        instance reused to `parse()` multiple sources doesn't keep
        re-appending warnings about a source it no longer reflects.

        `preprocess_fixed` mirrors `parse_cobol`'s parameter of the same
        name: None (the default) auto-detects fixed format when `free_form`
        is False -- the historical behavior; True always normalizes,
        regardless of what `detect_fixed_format` would say (the
        `--source-format=fixed` escape hatch for layouts the detector
        declines); False never normalizes.

        `debug_lines` mirrors `parse_cobol`'s parameter of the same name:
        False (the default) drops fixed-format debugging lines (``D`` in
        column 7) as comments; True compiles them as code, the way IBM
        Enterprise COBOL does under ``SOURCE-COMPUTER ... WITH DEBUGGING
        MODE``.
        """
        self.dialect = dialect
        self.error_recovery = error_recovery
        self.memory_config = memory_config or MemoryConfiguration()
        self.serialization_config = serialization_config or SerializationConfig()
        self.free_form = free_form
        self.preprocess_fixed = preprocess_fixed
        self.debug_lines = debug_lines
        self._initial_warnings = list(initial_warnings) if initial_warnings else []

        # Parser state
        self.tokens: list[Token] = []
        #: 1-based numbers of the debugging lines the fixed-format
        #: normalization of the current parse dropped as comments.
        self._dropped_debug_lines: list[int] = []
        self._omitted_copy_lines: list[tuple[int, int]] = []
        self.errors: list[ParseError] = []
        self.warnings: list[str] = []
        self.statistics = ParseStatistics()
        self.current_program: CobolProgram | None = None
        self.stream: TokenStream | None = None
        self._error_limit_reached: bool = False
        #: ``SPECIAL-NAMES. DECIMAL-POINT IS COMMA`` (decided by the lexer
        #: from the whole source): PICTURE strings exchange ``,`` and ``.``.
        self.decimal_point_is_comma: bool = False
        #: ``SPECIAL-NAMES. CURRENCY SIGN``: each declared PICTURE currency
        #: symbol's currency string (decided by the lexer), ``{"#": "EUR"}``.
        self.currency_signs: dict[str, str] = {}
        #: True when this parse normalized fixed-format source to free-form
        #: text: column 1 of every lexed line is then the old column 8, so
        #: Area A is columns 1-4 and Area B starts at
        #: :data:`~cobolparser.parsers.statements._utils.NORMALIZED_AREA_B_COLUMN`.
        self.source_is_fixed_format: bool = False

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

        A ``REPLACE`` statement is kept too: COBOL-85 and IBM allow it as
        the first statement of a compilation unit, ahead of the header, and
        ``apply_replace_statements`` only runs later (#254). Every line a
        well-formed REPLACE statement touches is kept whole.
        """
        lines = split_source_lines(content, keepends=True)

        for i, line in enumerate(lines):
            if _ID_DIV_RE.search(line):
                replace_lines = CobolParser._replace_statement_lines(lines[:i])
                kept = [
                    (
                        preceding
                        if index in replace_lines
                        or preceding.strip().startswith(">>")
                        or preceding.strip()[6:8].strip().startswith(">>")
                        or preceding.strip().upper().startswith(("CBL", "PROCESS"))
                        else "\n"
                    )
                    for index, preceding in enumerate(lines[:i])
                ]
                return "".join(kept + lines[i:])

        return content

    @staticmethod
    def _replace_statement_lines(lines: list[str]) -> set[int]:
        """Indexes of the *lines* a well-formed REPLACE statement spans."""
        prefix = "".join(lines)
        if "REPLACE" not in prefix.upper():
            return set()
        spans = find_replace_statement_spans(prefix)
        if not spans:
            return set()
        indexes: set[int] = set()
        for start, end in spans:
            first = prefix.count("\n", 0, start)
            last = prefix.count("\n", 0, max(start, end - 1))
            indexes.update(range(first, last + 1))
        return indexes

    def _parse_core(
        self,
        source: str,
        filename: str = "<string>",
        error_recovery: ErrorRecoveryMode | None = None,
    ) -> ParseResult:
        """Parse COBOL source code into AST (core implementation).

        Runs the three pipeline stages in order -- ``_preprocess_source``
        (source-text passes), ``_tokenize`` (lexing into ``self.stream``)
        and ``parse_program`` (division dispatch) -- and turns whatever
        stops early into a ``ParseResult``.

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

        self._begin_parse()
        # A stream left over from an earlier parse() must not lend its
        # position to an error raised before this parse tokenizes.
        self.stream = None
        self.decimal_point_is_comma = False
        self.currency_signs = {}
        self.source_is_fixed_format = False
        # Set up front, not only on the success path: a FAIL_FAST lexer
        # error or a propagated ParseError returns early, and its result
        # used to report ``lines_parsed == 0`` for a non-empty source.
        self.statistics.lines_parsed = len(split_source_lines(source))
        # The CLI's --stats reports lines_processed; keep both counters in step.
        self.statistics.lines_processed = self.statistics.lines_parsed
        for _initial_warning in self._initial_warnings:
            self.add_warning(_initial_warning)
        # Consume once: these describe the source passed to the *first*
        # parse() call, not any later reuse of this instance.
        self._initial_warnings = []

        try:
            prepared = self._preprocess_source(source, filename)
            if prepared is None:
                return self._create_result(None)
            cleaned_source, free_form = prepared

            if not self._tokenize(cleaned_source, filename, free_form):
                return self._create_result(None)

            program = self.parse_program()
            if program is not None:
                for unit in program.program_units():
                    unit.serialization_config = self.serialization_config
                    unit.omitted_copy_lines = tuple(self._omitted_copy_lines)
                self._warn_dropped_debug_lines(program)
                self._warn_data_without_data_division(program)

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
            self.add_error(self._unexpected_error("Parser error", e))
            return self._create_result(None)

    def _preprocess_source(self, source: str, filename: str) -> tuple[str, bool] | None:
        """Run every source-text pass that precedes lexing.

        Returns ``(cleaned_source, free_form)`` -- the text to lex and the
        layout to lex it in -- or ``None`` when a FAIL_FAST error (recorded
        already) means parsing stops here. Every pass preserves the line
        count, so locations still point into *source*.
        """
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
            # Detect on the raw source, as the lexer does: the banner that
            # _skip_to_identification_division blanked is often the only
            # part laid out in columns (tab-indented code fails the
            # column-7 test).
            detected_fixed = (
                True
                if self.preprocess_fixed
                else detect_fixed_format(strip_compiler_directives(source))
            )
            if detected_fixed:
                normalized = self._normalize_fixed_source(
                    cleaned_source, preprocess_warnings
                )
                if normalized is None:
                    return None
                cleaned_source = normalized
                self.source_is_fixed_format = True
            # Normalized output is free-form, and so is source the detector
            # judged free-form already: lex it as free-form (mirrors
            # parse_cobol, which flips free_form on for undetected-fixed
            # input). Lexing it with the fixed-format column rules instead
            # sliced the first seven characters off every line.
            actual_free_form = True
            logger.debug(
                "Format auto-detection for %s: %s",
                filename,
                "fixed (normalized to free-form)" if detected_fixed else "free-form",
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
        self._omitted_copy_lines = []
        cleaned_source = strip_unexpanded_copy_statements(
            cleaned_source,
            warnings=preprocess_warnings,
            omitted_lines=self._omitted_copy_lines,
        )
        cleaned_source = apply_replace_statements(
            cleaned_source, warnings=preprocess_warnings
        )
        for _warning in preprocess_warnings:
            self.add_warning(_warning)

        return cleaned_source, actual_free_form

    def _normalize_fixed_source(
        self, source: str, preprocess_warnings: list[str]
    ) -> str | None:
        """Normalize fixed-format *source* to free-form text.

        An unterminated literal at EOF is recorded as an error; unless
        failing fast, the best-effort normalization stands in so a single
        bad literal does not lose the whole program under COLLECT_ALL.
        Returns ``None`` when FAIL_FAST stops the parse.
        """
        source_lines = split_source_lines(source)
        fail_fast = self.error_recovery == ErrorRecoveryMode.FAIL_FAST
        text, error = normalize_with_recovery(
            source_lines,
            preprocess_warnings,
            recover=not fail_fast,
            debug_lines_as_comments=not self.debug_lines,
        )
        if not self.debug_lines:
            self._dropped_debug_lines = debug_line_numbers(source_lines)
        if error is not None:
            self.add_error(ParseError(error, line_number=len(source_lines), column=1))
        return text

    def _warn_dropped_debug_lines(self, program: CobolProgram) -> None:
        """Warn when ``WITH DEBUGGING MODE`` is on but its D-lines were dropped.

        IBM Enterprise COBOL compiles debugging lines as code under
        ``SOURCE-COMPUTER ... WITH DEBUGGING MODE``. This parser keeps
        dropping them unless asked (``debug_lines=True``), so the AST then
        lacks statements the compiled program runs -- and every analyzer
        reading it (unused variables, xref, lineage) is short of them too.
        That gap is reported rather than left silent.
        """
        if not self._dropped_debug_lines:
            return
        if not debugging_mode_on(program):
            return
        self.add_warning(
            dropped_debug_lines_warning(
                f"Line {self._dropped_debug_lines[0]}",
                len(self._dropped_debug_lines),
            )
        )

    def _warn_data_without_data_division(self, program: CobolProgram) -> None:
        """Warn when a comment-entry swallowed the program's DATA DIVISION.

        A program with no DATA DIVISION whose IDENTIFICATION DIVISION
        comment-entry (``DATE-COMPILED.``, ``REMARKS.``, ...) holds DATA
        DIVISION or storage-section text has lost its declarations into the
        entry -- an indented ``COPY`` of a member holding the ENVIRONMENT and
        DATA DIVISIONs did exactly that. The parse used to succeed with zero
        data items and nothing said so; xref then reported every name the
        PROCEDURE DIVISION uses as undefined.
        """
        for unit in program.program_units():
            if unit.data_division is not None:
                continue
            identification = unit.identification_division
            metadata = getattr(identification, "metadata", None) or {}
            for key in _COMMENT_ENTRY_KEYS:
                text = metadata.get(key)
                if isinstance(text, str) and _SWALLOWED_DATA_RE.search(text):
                    paragraph = key.upper().replace("_", "-")
                    self.add_warning(
                        f"Program {unit.program_name or '?'} has no DATA "
                        f"DIVISION, but its {paragraph} comment-entry holds "
                        f"data-division text ('{text[:60]}'); its "
                        "declarations were read as part of the comment-entry"
                    )
                    break

    def _tokenize(self, cleaned_source: str, filename: str, free_form: bool) -> bool:
        """Lex *cleaned_source* into ``self.tokens`` and ``self.stream``.

        Records the lexer's errors and warnings. Returns False when a lexer
        error under FAIL_FAST means parsing stops here.
        """
        lexer = CobolLexer(cleaned_source, filename, self.dialect, free_form=free_form)
        self.tokens = lexer.tokenize()
        self.statistics.tokens_processed = len(self.tokens)
        self.decimal_point_is_comma = bool(
            getattr(lexer, "decimal_point_is_comma", False)
        )
        self.currency_signs = dict(getattr(lexer, "currency_signs", {}) or {})
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
                return False

        if lexer.has_warnings():
            for warning in lexer.get_warnings():
                self.add_warning(f"Lexer warning: {warning}")

        # A `*>` floating comment (IBM Enterprise COBOL 6.x) is layout
        # wherever it sits: it may end any line, including one that stops
        # between a clause keyword and its operand (``OCCURS 10 *> rows`` /
        # ``INDEXED BY IX``). Every sub-clause reader that skips line breaks
        # would otherwise have to skip COMMENT tokens too, and most did not
        # -- the operand after the comment was dropped as an "unparsed
        # token", or (``OCCURS *> n`` / ``10 TIMES``) read as a new item's
        # level number. The lexer's own token list keeps them.
        self.stream = TokenStream(
            [t for t in self.tokens if t.type is not TokenType.COMMENT]
        )
        # Lines whose COPY text was blanked before lexing: the tokens alone
        # cannot tell that something was written there (see
        # EvaluateStatementParser._at_stacked_when).
        self.stream.omitted_source_lines = tuple(self._omitted_copy_lines)
        return True

    # The @overload stubs below are for static type checkers only; gating them
    # on TYPE_CHECKING keeps them visible to mypy/IDEs and out of the runtime
    # class body.
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
        """Parse COBOL *source*; never raises on bad input.

        Errors land on ``ParseResult.errors``. With *enable_profiling*,
        returns ``(result, ProfilingResult)`` -- see ``ProfilerContext``.
        """
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
            # A fresh result: without the reset, this one carried the errors,
            # warnings and statistics of whatever this instance parsed last.
            self._begin_parse()
            self.add_error(ParseError(f"File error: {str(e)}", line_number=1, column=1))
            return self._create_result(None)

    def parse_program(self) -> CobolProgram | None:
        """Parse a complete COBOL program delegating to division parsers.

        Uses DivisionParserFactory to parse IDENTIFICATION, ENVIRONMENT, DATA,
        and PROCEDURE divisions in sequence. Implements error recovery modes
        and coordinated error handling across divisions.
        """
        # Created up front; the IDENTIFICATION division fills in the name.
        primary_program = CobolProgram("UNKNOWN", self.get_current_location())
        self.current_program = primary_program
        # Object-oriented units nest: a CLASS-ID unit holds its FACTORY and
        # OBJECT units, each holding METHOD-ID units. ``END METHOD`` / ``END
        # FACTORY`` / ``END OBJECT`` / ``END CLASS`` pop back to the parent.
        self._unit_stack: list[CobolProgram] = []
        # PROGRAM-ID units not yet closed by their END PROGRAM, outermost
        # first: a new PROGRAM-ID is nested in the last of them, or stacked
        # (a separate compilation unit) when they are all closed (#532).
        self._open_programs: list[CobolProgram] = [primary_program]

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
                if self._handle_headerless_unit(primary_program, divisions_parsed):
                    continue

                # Try to find a parser for the current token
                parser = self._division_factory.find_parser(self.stream)
                if not parser:
                    if self._handle_unmatched_token(divisions_parsed):
                        continue
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
                    self._parse_division(parser, divisions_parsed)
                except Exception as e:
                    # A ParseError is already formatted by a division or
                    # statement parser: record it verbatim so its location
                    # info is preserved.
                    logger.debug(
                        "Error from %s: %s",
                        type(parser).__name__,
                        e,
                        exc_info=True,
                    )
                    if not isinstance(e, ParseError):
                        self.add_error(
                            self._unexpected_error("Division parsing error", e)
                        )
                    elif e not in self.errors:
                        self.add_error(e)
                    if self.error_recovery == ErrorRecoveryMode.FAIL_FAST:
                        logger.debug("FAIL_FAST: aborting division loop")
                        return primary_program if divisions_parsed else None

        except ParseError as pe:
            if pe not in self.errors:
                self.add_error(pe)
            if self.error_recovery == ErrorRecoveryMode.FAIL_FAST:
                return primary_program if divisions_parsed else None
        except Exception as e:
            self.add_error(self._unexpected_error("Division parsing error", e))
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

    def _handle_unmatched_token(self, divisions_parsed: list[Any]) -> bool:
        """Deal with a stream head no division parser matched.

        Returns True when the division loop should continue (an ``END
        PROGRAM`` marker was consumed) and False when it should stop -- at
        a clean end of input, or after recording a "no recognizable
        division" error.
        """
        assert self.stream is not None
        current_token = self.stream.peek()
        current_value = (
            current_token.value.upper()
            if current_token and current_token.value
            else "EOF"
        )
        logger.debug(
            "No division parser matched near %r (divisions parsed so far: %d)",
            current_value,
            len(divisions_parsed),
        )
        # END PROGRAM closes the current program unit; consume it and keep
        # parsing — the compilation unit may contain more (stacked or
        # nested) programs. Historically the loop broke here and everything
        # after the first END PROGRAM was silently dropped.
        if divisions_parsed and current_value == "END" and self._peek_is_end_program():
            self._consume_end_program_marker()
            if self._open_programs:
                self._open_programs.pop()
            return True
        # Only the end-of-input marker remains after at least one division
        # parsed — a clean end, not an error.
        if divisions_parsed and current_value == "EOF":
            return False
        if not divisions_parsed or current_value not in ("END", "PROGRAM"):
            near = (
                current_token.value if current_token and current_token.value else "EOF"
            )
            self.add_error(
                self.create_error(
                    f"No recognizable COBOL division found near '{near}'",
                    self.get_current_location(),
                )
            )
        return False

    def _parse_division(self, parser: Any, divisions_parsed: list[Any]) -> None:
        """Run one division *parser* and add its node to the current unit.

        The IDENTIFICATION division's ``program_id`` / ``unit_kind``
        metadata names the current unit.
        """
        assert self.stream is not None and self.current_program is not None
        # Set host on ProcedureDivisionParser for ParseContext creation
        set_host = getattr(parser, "set_host", None)
        if callable(set_host):
            set_host(self)
        elif hasattr(parser, "host"):
            parser.host = self

        logger.debug("Dispatching to %s", type(parser).__name__)
        division_ast = parser.parse(self.stream)
        if not division_ast:
            return
        divisions_parsed.append(division_ast)
        if isinstance(division_ast, CobolDivision):
            self.current_program.add_division(division_ast)

        metadata = getattr(division_ast, "metadata", None)
        if isinstance(metadata, dict) and "program_id" in metadata:
            self.current_program.program_name = metadata["program_id"]
            unit_kind = metadata.get("unit_kind")
            if unit_kind:
                self.current_program.unit_kind = str(unit_kind)

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
            # The tree stays flat; the source nesting is recorded apart.
            enclosing = self._open_programs[-1] if self._open_programs else None
            new_program.enclosing_program = (
                enclosing
                if enclosing is not None and enclosing.unit_kind == "PROGRAM"
                else None
            )
            self._open_programs.append(new_program)
        self.current_program = new_program

    def _handle_headerless_unit(
        self, primary_program: CobolProgram, divisions_parsed: list[Any]
    ) -> bool:
        """Open a unit at a ``PROGRAM-ID`` / ``FUNCTION-ID`` written without
        an IDENTIFICATION DIVISION header (optional in COBOL 2002, GnuCOBOL
        and Micro Focus). Returns True when one was parsed.

        Nested in another program it used to be read as that program's
        paragraphs and divisions: the enclosing PROCEDURE DIVISION was
        replaced, silently.
        """
        if not self.stream:
            return False
        token = self.stream.peek()
        value = (token.value or "").upper() if token else ""
        if value not in ("PROGRAM-ID", "FUNCTION-ID"):
            return False
        unit = self.current_program or primary_program
        if unit.has_division("IDENTIFICATION") or divisions_parsed:
            self._attach_new_unit(
                primary_program, CobolProgram("UNKNOWN", self.get_current_location())
            )
        parser = self._division_factory.get_parser(DivisionType.IDENTIFICATION)
        assert isinstance(parser, IdentificationDivisionParser)
        division_ast = parser.parse_headerless(self.stream)
        assert isinstance(division_ast, CobolDivision)
        assert self.current_program is not None
        divisions_parsed.append(division_ast)
        self.current_program.add_division(division_ast)
        metadata = division_ast.metadata
        self.current_program.program_name = metadata["program_id"]
        if metadata.get("unit_kind"):
            self.current_program.unit_kind = str(metadata["unit_kind"])
        return True

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
        if value in ("CLASS-ID", "METHOD-ID"):
            self._open_id_clause_unit(value, primary_program, divisions_parsed)
            return True
        if value in ("FACTORY", "OBJECT"):
            return self._open_factory_or_object_unit(
                value, primary_program, divisions_parsed
            )
        if value == "END":
            return self._close_oo_unit(primary_program)
        return False

    def _open_id_clause_unit(
        self, value: str, primary_program: CobolProgram, divisions_parsed: list[Any]
    ) -> None:
        """Open a unit from a header-less ``CLASS-ID.`` / ``METHOD-ID.``."""
        assert self.stream is not None
        location = self.get_current_location()
        inherits: str | None = None
        if value == "CLASS-ID":
            name, inherits = IdentificationDivisionParser.parse_class_id_clause(
                self.stream
            )
            kind = "CLASS"
        else:
            name = IdentificationDivisionParser.parse_method_id_clause(self.stream)
            kind = "METHOD"
        unit = self.current_program or primary_program
        if unit.has_division("IDENTIFICATION") or divisions_parsed:
            unit = CobolProgram(name, location)
            self._attach_new_unit(primary_program, unit)
        self._add_oo_identification(
            unit, name, kind, location, divisions_parsed, inherits=inherits
        )

    def _open_factory_or_object_unit(
        self, value: str, primary_program: CobolProgram, divisions_parsed: list[Any]
    ) -> bool:
        """Open a unit from a ``FACTORY.`` / ``OBJECT.`` paragraph."""
        assert self.stream is not None
        nxt = self.stream.peek(1)
        if nxt is None or nxt.value != ".":
            return False
        location = self.get_current_location()
        self.stream.consume()  # FACTORY | OBJECT
        self.stream.consume()  # .
        unit = CobolProgram(value, location)
        self._attach_new_unit(primary_program, unit)
        self._add_oo_identification(unit, value, value, location, divisions_parsed)
        return True

    def _add_oo_identification(
        self,
        unit: CobolProgram,
        name: str,
        kind: str,
        location: SourceLocation,
        divisions_parsed: list[Any],
        **extra_metadata: Any,
    ) -> None:
        """Name *unit* and give it the IDENTIFICATION division it implies."""
        unit.program_name = name
        unit.unit_kind = kind
        ident = CobolDivision("IDENTIFICATION", location)
        ident.metadata.update(
            {
                "program_id": name,
                "unit_kind": kind,
                "program_attributes": [],
                **extra_metadata,
            }
        )
        unit.add_division(ident)
        divisions_parsed.append(ident)

    def _close_oo_unit(self, primary_program: CobolProgram) -> bool:
        """Consume ``END METHOD|FACTORY|OBJECT|CLASS [name] [.]``."""
        assert self.stream is not None
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

    def _peek_is_end_program(self) -> bool:
        """True if the stream is at an ``END PROGRAM`` / ``END FUNCTION`` marker."""
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
            return bool(token.value) and token.value.upper() in ("PROGRAM", "FUNCTION")
        return False

    def _consume_end_program_marker(self) -> None:
        """Consume ``END PROGRAM|FUNCTION [name] [.]`` from the stream."""
        if not self.stream:
            return
        self.stream.consume()  # END
        self.stream.skip_whitespace_and_comments()
        token = self.stream.peek()
        if token and token.value and token.value.upper() in ("PROGRAM", "FUNCTION"):
            self.stream.consume()
        self.stream.skip_whitespace_and_comments()
        token = self.stream.peek()
        if token and token.value and token.value != ".":
            self.stream.consume()  # program name (identifier or literal)
        self.stream.skip_whitespace_and_comments()
        token = self.stream.peek()
        if token and token.value == ".":
            self.stream.consume()

    def _unexpected_error(self, prefix: str, exc: Exception) -> ParseError:
        """A ParseError recording an unexpected (non-ParseError) exception.

        The message keeps the exception's type name (``RuntimeError: ...``)
        and the error is chained to *exc* through ``__cause__``. The location
        is the exception's own when it carries one (a ``line_number`` /
        ``column`` pair or a ``location`` with ``line`` / ``column``),
        otherwise the token the stream is positioned at; ``line 1, column 1``
        only when neither is available.
        """
        line, column = self._exception_position(exc)
        err = ParseError(
            f"{prefix}: {type(exc).__name__}: {exc}", line_number=line, column=column
        )
        err.__cause__ = exc
        return err

    def _exception_position(self, exc: Exception) -> tuple[int, int]:
        """(line, column) for :meth:`_unexpected_error`; see there."""
        line = getattr(exc, "line_number", None)
        column = getattr(exc, "column", None)
        location = getattr(exc, "location", None)
        if not isinstance(line, int) and location is not None:
            line = getattr(location, "line", None)
            column = getattr(location, "column", None)
        if isinstance(line, int) and line > 0:
            return line, column if isinstance(column, int) and column > 0 else 1
        try:
            current = self.get_current_location()
        except Exception:
            # The stream itself may be what failed; fall back to the start.
            return 1, 1
        return current.line, current.column

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

    def _begin_parse(self) -> None:
        """Reset the per-parse state (errors, warnings, statistics, timer)."""
        self.statistics.reset()
        self.statistics.start_timing()
        self.errors.clear()
        self.warnings.clear()
        self._error_limit_reached = False
        self._dropped_debug_lines = []

    def _create_result(self, ast: CobolProgram | None) -> ParseResult:
        """Create parse result with current state."""
        # Every return path stops the clock here -- the early ones (a
        # FAIL_FAST lexer error, a propagated ParseError, the safety net)
        # used to hand back ``parse_time_seconds == 0``.
        self.statistics.end_timing()
        return ParseResult(
            ast=ast,
            errors=self.errors.copy(),
            warnings=self.warnings.copy(),
            # Snapshot: self.statistics is reset in place on the next
            # parse() call, which would clobber this result's statistics.
            statistics=self.statistics.copy(),
        )


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
        debug_lines: bool = ...,
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
        debug_lines: bool = ...,
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
    debug_lines: bool = False,
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
        debug_lines: Compile fixed-format debugging lines (``D`` in column
            7) as code instead of dropping them as comments -- what IBM
            Enterprise COBOL does under ``SOURCE-COMPUTER ... WITH DEBUGGING
            MODE``. Off by default; a program that declares the clause while
            it is off gets a warning saying how many lines were dropped

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

    # Fixed-format detection, normalization and its unterminated-literal
    # recovery all happen inside CobolParser -- one code path for both entry
    # points. ``preprocess_fixed=None`` here means "auto-detect even when
    # free_form is set", which is the parser's None with free_form=False:
    # it lexes free-form whichever way detection goes.
    parser = CobolParser(
        dialect=dialect,
        error_recovery=error_recovery,
        free_form=free_form and preprocess_fixed is not None,
        preprocess_fixed=preprocess_fixed,
        debug_lines=debug_lines,
    )
    return parser.parse(  # type: ignore[no-any-return]
        source_str,
        filename,
        enable_profiling=enable_profiling,  # type: ignore[call-overload]
        top_n=top_n,
        prof_output=prof_output,
    )


# -- expand, then parse ------------------------------------------------------


def warn_dropped_debug_lines(result: Any, expansion: Any, filename: str) -> None:
    """Warn on *result* about debugging lines *expansion* blanked.

    Expansion blanks ``D`` lines with the comments before the parser sees
    the text, so the parser's own ``WITH DEBUGGING MODE`` warning cannot
    count them; this raises the same warning from the expansion's list
    instead, in the coordinates of the file they were written in. Nothing
    happens when the expansion kept them (``debug_lines=True``), when no
    unit declares the clause, or when the parser already warned (nothing
    was expanded, so the source reached it untouched).
    """
    # getattr: stand-in expansions in tests carry only the fields they need.
    dropped = list(getattr(expansion, "dropped_debug_lines", None) or [])
    if (
        not dropped
        or result.ast is None
        or not debugging_mode_on(result.ast)
        or any(DROPPED_DEBUG_LINES_MARKER in w for w in result.warnings)
    ):
        return
    first_file, first_line = dropped[0]
    location = f"Line {first_line}"
    if first_file != filename:
        location = f"{first_file}: {location}"
    result.warnings.append(dropped_debug_lines_warning(location, len(dropped)))


def parse_cobol_with_expansion(
    source_code: str,
    filename: str,
    copybook_paths: list[str],
    max_nesting_depth: int = 100,
    process_conditionals: bool = True,
    defined_symbols: dict[str, str] | None = None,
    skip_missing_copybooks: bool = False,
    **parser_kwargs: Any,
) -> Any:
    """
    Convenience function that expands copybooks and parses in one step.

    This function combines copybook expansion with COBOL parsing, providing
    a seamless workflow for parsing COBOL programs with copybook dependencies.

    Args:
        source_code: COBOL source code containing COPY statements
        filename: Source filename for error reporting
        copybook_paths: List of directory paths to search for copybooks
        max_nesting_depth: Maximum allowed nesting depth (default: 100)
        process_conditionals: Whether to process >>DEFINE/>>IF/>>EVALUATE
            conditional compilation directives during expansion (default:
            True). The parser runs the same directive pass over whatever
            text it is given anyway, so this changes *when* it happens,
            not whether: during expansion, a COPY inside an excluded
            ``>>IF`` block is never resolved (it used to be expanded first,
            and a member that only exists for the other branch -- a CICS
            ``COPY DFHAID`` under ``>>IF CICS DEFINED`` -- failed the whole
            parse), and a ``>>DEFINE`` reaches the copybooks below it.
            False keeps the old order.
        defined_symbols: Pre-defined symbols for conditional compilation
        skip_missing_copybooks: Leave a COPY whose member cannot be found as
            written instead of failing (default False); see
            ``expand_copybooks``. The other members are still expanded.
        **parser_kwargs: Additional arguments passed to parse_cobol()

    Returns:
        ParseResult from the COBOL parser with expanded source

    Raises:
        CircularReferenceError: If circular copybook dependency detected
        CopybookNotFoundError: If referenced copybook file not found
        ParseError: If parsing fails after expansion

    Example:
        >>> from cobolparser import parse_cobol_with_expansion
        >>> result = parse_cobol_with_expansion(
        ...     source_code="COPY EMPLOYEE.",
        ...     filename="payroll.cbl",
        ...     copybook_paths=["/copybooks"]
        ... )
        >>> print(result.ast.program_name)
    """
    debug_lines = bool(parser_kwargs.get("debug_lines", False))

    # Expand copybooks first
    # Looked up on the module at call time, so a test that patches
    # ``copybook_expander.expand_copybooks`` reaches this call.
    expansion = copybook_expander.expand_copybooks(
        source_code=source_code,
        copybook_paths=copybook_paths,
        max_nesting_depth=max_nesting_depth,
        # The parser tracks its own locations, but they count lines in the
        # EXPANDED text -- so the map is what any consumer needs to put a
        # finding back on the line a human edits. Carried on the ParseResult.
        preserve_source_locations=True,
        process_conditionals=process_conditionals,
        defined_symbols=defined_symbols,
        source_file=filename,
        # Expansion blanks comment lines before the parser sees the text;
        # debugging lines compiled as code have to survive it.
        debug_lines=debug_lines,
        skip_missing_copybooks=skip_missing_copybooks,
        # ``preprocess_fixed=True`` (``--source-format fixed``) is a statement
        # about every file of the program, members included.
        source_format=(
            "fixed" if parser_kwargs.get("preprocess_fixed") is True else "auto"
        ),
    )

    # Parse the expanded source
    parse_result = parse_cobol(
        source=expansion.expanded_source, filename=filename, **parser_kwargs
    )

    # With enable_profiling=True, parse_cobol returns
    # (ParseResult, ProfilingResult) — the warnings live on the first element.
    result_obj = parse_result[0] if isinstance(parse_result, tuple) else parse_result

    # Propagate expansion warnings (lossy encoding decodes, copybook content
    # validation, level-number mismatches). They lived only on the discarded
    # CopybookExpansion object before, so callers of this convenience entry
    # point never saw them.
    source_map = getattr(expansion, "source_location_map", None)
    located: list[str] = []
    for warning in result_obj.warnings:
        moved = copybook_expander._locate_strip_pass_warning(warning, source_map)
        if moved is warning or moved not in located:
            located.append(moved)
    result_obj.warnings[:] = located
    expansion_warnings = list(getattr(expansion.statistics, "warnings", []) or [])
    for warning in expansion_warnings:
        if warning not in result_obj.warnings:
            result_obj.warnings.append(warning)

    warn_dropped_debug_lines(result_obj, expansion, filename)

    # getattr, not attribute access: callers monkeypatch `expand_copybooks`
    # with stand-ins that carry only the fields they care about, and a map
    # that is merely absent must not take the whole parse down.
    result_obj.expansion_source_map = source_map
    result_obj.expansion_copybooks = list(
        getattr(expansion, "included_copybooks", None) or []
    )

    return parse_result
