"""Procedure Division parser for COBOL programs.

This module implements parsing of the Procedure Division which contains:
- Paragraphs and sections: Named executable units
- Statements: Program logic and control flow

Uses StatementParserRegistry for pluggable statement parsing and dispatch.

The :class:`ProcedureDivisionParser` owns the paragraph/section dispatch loop
and the AST node creation. The supporting concerns are delegated to focused
collaborator modules:

- :mod:`~.procedure_registry` — builds the shared
  :class:`StatementParserRegistry` with every statement parser
- :mod:`~.procedure_boundaries` — paragraph/section/statement boundary
  lookahead predicates
- :mod:`~.procedure_recovery` — :class:`StatementRecoveryHandler`:
  unsupported-statement warnings, error recording (FAIL_FAST/COLLECT_ALL),
  and stream resynchronization
"""

import logging
from typing import Any

from cobolparser._errors import ParseError
from cobolparser.core.interfaces import ITokenStream, ParseContext
from cobolparser.core.registry import StatementParserRegistry
from cobolparser.lexer import TokenType
from cobolparser.models.ast_base import ASTNode, SourceLocation
from cobolparser.models.program import CobolDivision, CobolParagraph, CobolSection
from cobolparser.parsers.statements._utils import (
    peek_past_noise,
    skip_statement_separators,
    skip_whitespace,
)

from .base import BaseDivisionParser
from .procedure_boundaries import (
    is_leftover_word,
    is_paragraph_or_section_start,
    is_section_marker,
    is_statement_keyword,
)
from .procedure_recovery import (
    STRAY_MARKERS,
    UNSUPPORTED_VERBS,
    StatementRecoveryHandler,
)
from .procedure_registry import create_statement_registry

logger = logging.getLogger(__name__)


#: The word after ``END`` that closes an object-oriented unit (IBM Enterprise
#: COBOL ``END METHOD`` / ``END FACTORY`` / ``END OBJECT`` / ``END CLASS``).
_OO_UNIT_END_WORDS: frozenset[str] = frozenset({"METHOD", "FACTORY", "OBJECT", "CLASS"})


class ProcedureDivisionParser(BaseDivisionParser):
    """Parser for COBOL Procedure Division with registry-based statement parsing.

    Handles paragraphs, sections, and program logic statements using the
    StatementParserRegistry for pluggable statement type recognition and parsing.

    Supports PERFORM, IF, EVALUATE, MOVE, DISPLAY, arithmetic statements, and others.
    """

    division_name: str | None = "PROCEDURE"
    division_keywords: tuple = ()

    # Class-level cache for the shared statement registry. The set of
    # statement parsers is identical for every ProcedureDivisionParser
    # instance and the parsers themselves are stateless, so a single
    # registry can be reused across parses -- letting the registry's
    # dispatch cache warm up across batches instead of starting empty
    # for every program.
    _SHARED_REGISTRY: StatementParserRegistry | None = None

    # Kept as class-level aliases for discoverability/introspection; the
    # authoritative sets live in procedure_recovery.py.
    _STRAY_MARKERS: frozenset = STRAY_MARKERS
    _UNSUPPORTED_VERBS: frozenset = UNSUPPORTED_VERBS

    def __init__(self, host: Any = None) -> None:
        """Initialize Procedure Division parser with statement registry.

        Args:
            host: Parent parser (CobolParser) for creating ParseContext
        """
        super().__init__()
        self.host = host
        if ProcedureDivisionParser._SHARED_REGISTRY is None:
            ProcedureDivisionParser._SHARED_REGISTRY = self._create_statement_registry()
        self._statement_registry = ProcedureDivisionParser._SHARED_REGISTRY
        self._recovery = StatementRecoveryHandler(self)

    def set_host(self, host: Any) -> None:
        """Set the host parser after initialization.

        Args:
            host: Parent parser (CobolParser) for creating ParseContext
        """
        self.host = host

    def _collect_condition_names(self) -> frozenset:
        """Upper-cased level-88 condition-names of the DATA DIVISION, so the
        condition builder keeps the CONDITION_NAME reading for them and
        expands any other declared data name in an abbreviated combined
        relation (#562). Best-effort, like :meth:`_collect_known_data_names`.
        """
        program = getattr(self.host, "current_program", None)
        data_division = getattr(program, "data_division", None) if program else None
        if data_division is None:
            return frozenset()
        return frozenset(
            item.name.upper()
            for item in data_division.find_all_by_type("ConditionNameItem")
            if getattr(item, "name", None)
        )

    def _collect_known_data_names(self) -> frozenset:
        """Upper-cased DATA DIVISION item names, for H9's paragraph-boundary
        disambiguation (see ``looks_like_paragraph_boundary`` in
        ``parsers/statements/_utils.py``). Best-effort: a name declared only
        via an unexpanded COPY member won't be here, since ``parse_cobol()``
        doesn't expand copybooks -- callers that need full coverage should
        parse with copybook expansion enabled.
        """
        program = getattr(self.host, "current_program", None)
        data_division = getattr(program, "data_division", None) if program else None
        if data_division is None:
            return frozenset()
        names = set()
        for item in data_division.find_all_by_type("CobolDataItem"):
            name = getattr(item, "name", None)
            if name:
                names.add(name.upper())
        return frozenset(names)

    def _create_statement_registry(self) -> StatementParserRegistry:
        """Create and populate statement registry with all available parsers.

        Delegates to :func:`~.procedure_registry.create_statement_registry`,
        which registers every statement parser in priority order.

        Returns:
            StatementParserRegistry with all statement parsers registered
        """
        return create_statement_registry()

    def parse_division(self, token_stream: ITokenStream) -> dict[str, Any]:
        """Parse Procedure Division content using registry-based statement parsing.

        Parses paragraphs and sections containing executable statements.
        Each paragraph contains statements parsed using the StatementParserRegistry.

        Structure:
        - Paragraphs with or without sections
        - Each paragraph contains statements terminated by periods

        Args:
            token_stream: Token stream positioned after division header

        Returns:
            Dictionary containing parsed paragraphs, sections, and statements
        """
        procedures: dict[str, Any] = {}
        paragraphs: list[dict[str, Any]] = []
        sections: dict[str, Any] = {}
        # Track ordered list of section names for AST creation
        section_order: list[str] = []
        # Track the current section so paragraphs are associated correctly
        current_section: dict[str, Any] | None = None
        # True between ``DECLARATIVES.`` and ``END DECLARATIVES.``: every
        # section opened in that span is a declarative (USE) procedure the
        # runtime invokes, not one the program's own control flow reaches.
        in_declaratives = False

        # H9 paragraph-boundary disambiguation: computed once per division
        # parse and threaded to statement parsers via ParseContext.
        self._known_data_names = self._collect_known_data_names()
        self._condition_names = self._collect_condition_names()

        # Helper: get the paragraph list that new paragraphs should be added to.
        # If we're inside a section, add to that section's paragraphs; otherwise
        # add to the top-level paragraphs list.
        def _active_paragraphs() -> list[dict[str, Any]]:
            if current_section is not None:
                paras: list[dict[str, Any]] = current_section["paragraphs"]
                return paras
            return paragraphs

        # Skip initial whitespace and comments
        skip_whitespace(token_stream)

        # Parse paragraphs and sections until EOF
        while not token_stream.is_empty():
            # Skip whitespace/comments (and stray ``,``/``;`` separators)
            # at start of each iteration
            skip_statement_separators(token_stream)

            token = token_stream.peek(0)
            if not token:
                break

            # The EOF sentinel token has an empty value, which isn't in the
            # keyword-exclusion tuple below, so without this check it falls
            # through to the "unknown token -> paragraph name" branch and
            # manufactures a spurious empty-named, zero-statement trailing
            # paragraph on every program.
            if token.type == TokenType.EOF:
                break

            # A bare period ends a sentence, exactly as in
            # ``_parse_paragraph_statements``. Statements before the first
            # paragraph header (an implicit paragraph, or the start of a
            # SECTION) are dispatched one at a time from this loop, and the
            # EXEC / EVALUATE / CALL parsers leave the period after their
            # scope terminator (``END-EXEC.``) in the stream; it then fell
            # through to the paragraph-name branch and opened a phantom
            # paragraph named ``.`` holding the rest of the code (#503).
            if token.type == TokenType.PERIOD or token.value == ".":
                token_stream.consume()
                continue

            token_value = token.value.upper() if token.value else ""

            # Check for next division start or END PROGRAM/DIVISION
            # Handle both bare keywords and composite tokens (e.g. "DATA DIVISION")
            _stop_div = ("IDENTIFICATION", "ENVIRONMENT", "DATA")
            if token_value in _stop_div:
                break
            if any(token_value == f"{kw} DIVISION" for kw in _stop_div):
                break

            # ``DECLARATIVES.`` opens the declaratives span; the marker is
            # not a paragraph (previously it produced one named
            # DECLARATIVES, and ``END DECLARATIVES.`` a second one).
            if token_value == "DECLARATIVES" and self._next_is_period(token_stream):
                token_stream.consume()  # DECLARATIVES
                token_stream.consume()  # .
                in_declaratives = True
                current_section = None
                continue

            # Check for END PROGRAM / END DIVISION (unit ends), END
            # DECLARATIVES (span ends), and the object-oriented unit ends
            # END METHOD / END FACTORY / END OBJECT / END CLASS.
            if token_value == "END":
                # The second word may start the next line (``END`` alone on
                # a line): a bare peek(1) saw the NEWLINE, so END
                # DECLARATIVES never closed the span.
                next_token, _ = peek_past_noise(token_stream, 1)
                next_value = (
                    next_token.value.upper() if next_token and next_token.value else ""
                )
                if next_value in ("PROGRAM", "FUNCTION", "DIVISION"):
                    break
                if next_value in _OO_UNIT_END_WORDS:
                    break
                if next_value == "DECLARATIVES":
                    token_stream.consume()  # END
                    skip_whitespace(token_stream)
                    token_stream.consume()  # DECLARATIVES
                    if self._next_is_period(token_stream, offset=0):
                        token_stream.consume()  # .
                    in_declaratives = False
                    current_section = None
                    continue

            # A METHOD-ID / CLASS-ID header ends the (usually empty)
            # PROCEDURE DIVISION of a FACTORY / OBJECT paragraph and starts
            # the next unit; the program-level parser takes over from here.
            if token_value in ("METHOD-ID", "CLASS-ID"):
                break
            # A FUNCTION-ID with no IDENTIFICATION DIVISION header in front
            # starts the next unit the same way.
            if token_value == "FUNCTION-ID":
                break

            # Skip stray control markers so following statements can be recovered.
            if token_value in ("ELSE", "WHEN", "END-IF", "END-PERFORM", "END-EVALUATE"):
                token_stream.consume()
                continue

            # Check for SECTION keyword
            if self._is_section_marker(token_stream):
                section_name = token_value  # Normalize to uppercase (like paragraphs)
                section_location = (
                    token.location
                    if hasattr(token, "location")
                    else SourceLocation(0, 0)
                )
                token_stream.consume()  # consume section name

                # Skip to SECTION keyword
                _ps = token_stream.peek(0)
                while (
                    not token_stream.is_empty()
                    and _ps
                    and _ps.value
                    and _ps.value.upper() != "SECTION"
                ):
                    token_stream.consume()
                    _ps = token_stream.peek(0)

                if not token_stream.is_empty():
                    token_stream.consume()  # consume SECTION

                # ``S1 SECTION 50.``: a COBOL-85 segment-number (priority).
                # It was left in the stream and became a paragraph named
                # ``50`` (NIST SG101A).
                _seg = token_stream.peek(0)
                if (
                    _seg is not None
                    and _seg.type in (TokenType.LEVEL_NUMBER, TokenType.NUMERIC_LITERAL)
                    and (_seg.value or "").isdigit()
                    and self._next_is_period(token_stream, offset=1)
                ):
                    token_stream.consume()

                _pp = token_stream.peek(0)
                if not token_stream.is_empty() and _pp and _pp.value == ".":
                    token_stream.consume()  # consume period

                section_dict = {
                    "type": "section",
                    "name": section_name,
                    "location": section_location,
                    "paragraphs": [],
                    "declarative": in_declaratives,
                }
                if section_name not in section_order:
                    section_order.append(section_name)
                sections[section_name] = section_dict
                current_section = section_dict

            elif self._is_statement_keyword(token_value):
                # This is a statement keyword without an explicit paragraph
                active = _active_paragraphs()
                # Create implicit paragraph if needed (only if no paragraphs or last is named)
                if not active or not active[-1].get("_is_implicit_paragraph"):
                    # Create new implicit paragraph
                    para_dict = {
                        "type": "paragraph",
                        "name": "",  # Implicit paragraph has empty name
                        "location": (
                            token.location
                            if hasattr(token, "location")
                            else SourceLocation(0, 0)
                        ),
                        "statements": [],
                        "_is_implicit_paragraph": True,
                    }
                    active.append(para_dict)

                # Try to parse the statement
                parser = self._statement_registry.find_parser(token_stream)
                if parser:
                    logger.debug(
                        "Dispatch %s -> %s",
                        token.value,
                        type(parser).__name__,
                    )
                    self._attach_context(token_stream)
                    try:
                        statement = parser.parse(token_stream)
                        active[-1]["statements"].append(
                            {
                                "type": "statement",
                                "node_type": type(statement).__name__,
                                "statement": statement,
                            }
                        )
                    except ParseError as e:
                        self._handle_statement_error(e, token, token_stream)
                    except Exception as e:
                        self._handle_statement_error(
                            self._wrap_unexpected(e, token), token, token_stream
                        )
                else:
                    # No parser found, skip the statement — but tell the
                    # caller about it so the drop is not silent.
                    logger.debug(
                        "No statement parser matched %s=%r; skipping",
                        token.type.name,
                        token.value,
                    )
                    self._warn_unsupported_statement(token)
                    self._skip_to_next_statement(token_stream)

            elif token_value not in (
                "SECTION",
                "IDENTIFICATION",
                "ENVIRONMENT",
                "DATA",
                "END",
                "PROGRAM",
                "DIVISION",
            ):
                if self._drop_leftover_word(token_stream):
                    continue
                # Treat as paragraph name (only if not a keyword)
                para_name = token_value
                para_location = (
                    token.location
                    if hasattr(token, "location")
                    else SourceLocation(0, 0)
                )
                token_stream.consume()  # consume paragraph name

                # Skip period after paragraph name if present
                _pn = token_stream.peek(0)
                if not token_stream.is_empty() and _pn and _pn.value == ".":
                    token_stream.consume()

                # Parse statements in paragraph until next paragraph/section or EOF
                statements = self._parse_paragraph_statements(token_stream)

                para_dict = {
                    "type": "paragraph",
                    "name": para_name,
                    "location": para_location,
                    "statements": statements,
                    "_is_implicit_paragraph": False,
                }
                _active_paragraphs().append(para_dict)
            else:
                token_stream.consume()

        # Clean up: remove empty implicit paragraphs from top-level and sections
        def _clean_implicit(para_list: list[dict[str, Any]]) -> None:
            while (
                para_list
                and para_list[-1].get("_is_implicit_paragraph")
                and not para_list[-1].get("statements")
            ):
                para_list.pop()

        _clean_implicit(paragraphs)
        for sec in sections.values():
            _clean_implicit(sec["paragraphs"])

        procedures["paragraphs"] = paragraphs
        procedures["sections"] = sections
        procedures["section_order"] = section_order
        return procedures

    def _parse_paragraph_statements(
        self, token_stream: ITokenStream
    ) -> list[dict[str, Any]]:
        """Parse all statements within a paragraph until next paragraph/section.

        Uses StatementParserRegistry to dispatch to appropriate statement parser.
        Collects statements until encountering:
        - Next paragraph (identifier followed by period)
        - Next section (identifier followed by SECTION)
        - End of stream

        Args:
            token_stream: Token stream positioned at start of statements

        Returns:
            List of parsed statement dictionaries
        """
        statements: list[dict[str, Any]] = []

        while not token_stream.is_empty():
            # Skip whitespace/comments and the optional ``,``/``;``
            # separators COBOL allows between statements (``PERFORM A, GO
            # TO B.``) -- previously each one was reported as dropped
            # "unparsed tokens".
            skip_statement_separators(token_stream)

            if token_stream.is_empty():
                break

            token = token_stream.peek(0)
            if not token:
                break

            # Check for next paragraph or section. A word a statement parser
            # left behind (``STOP RUN 33.``) is dropped with a warning
            # instead: it is not a header, and the statements after it stay
            # in this paragraph.
            if self._is_paragraph_or_section_start(token_stream):
                if not self._drop_leftover_word(token_stream):
                    break
                continue

            # Check for division end marker
            if token.value and token.value.upper() in (
                "END",
                "IDENTIFICATION",
                "ENVIRONMENT",
                "DATA",
            ):
                break

            logger.debug(
                "Looking for parser for token %s=%r",
                token.type.name,
                token.value,
            )

            # Try to find and use statement parser
            parser = self._statement_registry.find_parser(token_stream)
            if parser:
                logger.debug("Dispatch %r -> %s", token.value, type(parser).__name__)
                self._attach_context(token_stream)
                try:
                    statement = parser.parse(token_stream)
                    statements.append(
                        {
                            "type": "statement",
                            "node_type": type(statement).__name__,
                            "statement": statement,
                        }
                    )
                except ParseError as e:
                    self._handle_statement_error(e, token, token_stream)
                except Exception as e:
                    self._handle_statement_error(
                        self._wrap_unexpected(e, token), token, token_stream
                    )
            elif token.value == ".":
                # Period terminates statement - consume it and continue
                token_stream.consume()
            else:
                # No parser found for this statement - skip it, but record a
                # warning so callers can tell content was dropped.
                logger.debug(
                    "No statement parser matched %s=%r; skipping",
                    token.type.name,
                    token.value,
                )
                self._warn_unsupported_statement(token)
                self._skip_to_next_statement(token_stream)

        return statements

    def _attach_context(self, token_stream: ITokenStream) -> None:
        """Attach the statement registry and a fresh ParseContext to the stream.

        Statement parsers retrieve this context via ``_utils.get_parse_context``
        to report recoverable errors. Recreating the context on each statement
        keeps recovery decisions tied to the host parser's current state.
        """
        if not hasattr(token_stream, "_registry"):
            token_stream._registry = self._statement_registry  # type: ignore[attr-defined]
        context = ParseContext(
            self.host,
            self._statement_registry,
            known_data_names=getattr(self, "_known_data_names", frozenset()),
            condition_names=getattr(self, "_condition_names", frozenset()),
        )
        token_stream.context = context
        token_stream._context = context  # type: ignore[attr-defined]

    # ------------------------------------------------------------------
    # Delegating wrappers.
    #
    # Boundary detection lives in procedure_boundaries.py and the
    # warn/record/recover logic in procedure_recovery.py (see the module
    # docstring). These wrappers keep the historical method names on the
    # division parser itself.
    # ------------------------------------------------------------------

    def _warn_unsupported_statement(self, token: Any) -> None:
        """Warn about skipped content (delegates to StatementRecoveryHandler)."""
        self._recovery.warn_unsupported_statement(token)

    @staticmethod
    def _next_is_period(token_stream: ITokenStream, offset: int = 1) -> bool:
        """True when the token at *offset* is the separator period."""
        token = token_stream.peek(offset)
        return bool(token is not None and token.value == ".")

    def _is_paragraph_or_section_start(self, token_stream: ITokenStream) -> bool:
        """Check for a paragraph/section start (delegates to procedure_boundaries)."""
        return is_paragraph_or_section_start(token_stream)

    def _drop_leftover_word(self, token_stream: ITokenStream) -> bool:
        """Consume and warn about a word a statement parser left behind.

        Returns False (consuming nothing) when the word at the cursor can
        be a paragraph header; see ``procedure_boundaries.is_leftover_word``.
        """
        nxt = token_stream.peek(1)
        if nxt is not None and (nxt.value or "").upper() == "SECTION":
            return False
        if not is_leftover_word(token_stream):
            return False
        self._warn_unsupported_statement(token_stream.peek(0))
        token_stream.consume()
        return True

    def _is_section_marker(self, token_stream: ITokenStream) -> bool:
        """Check for a section marker (delegates to procedure_boundaries)."""
        return is_section_marker(token_stream)

    @staticmethod
    def _is_statement_keyword(word: str) -> bool:
        """Check for a statement keyword (delegates to procedure_boundaries)."""
        return is_statement_keyword(word)

    def _wrap_unexpected(self, exc: BaseException, token: Any) -> ParseError:
        """Wrap an unexpected exception (delegates to StatementRecoveryHandler)."""
        return self._recovery.wrap_unexpected(exc, token)

    def _handle_statement_error(
        self,
        error: ParseError,
        token: Any,
        token_stream: ITokenStream,
    ) -> None:
        """Record/recover a statement error (delegates to StatementRecoveryHandler)."""
        self._recovery.handle_statement_error(error, token, token_stream)

    def _skip_to_next_statement(self, token_stream: ITokenStream) -> None:
        """Resynchronize the stream (delegates to StatementRecoveryHandler)."""
        self._recovery.skip_to_next_statement(token_stream)

    def _create_ast_node(
        self,
        division_token: Any,
        division_content: dict[str, Any],
        start_location: SourceLocation,
    ) -> ASTNode:
        """Create AST node for Procedure Division.

        Creates a CobolDivision node with paragraphs and sections containing parsed statements.

        Args:
            division_token: The PROCEDURE token
            division_content: Parsed content from parse_division()
            start_location: Start location for the AST node

        Returns:
            CobolDivision AST node with procedure structure and statements
        """
        # Create division node
        division_node = CobolDivision("PROCEDURE", start_location)

        # Add top-level paragraphs (those not inside any section)
        for para_info in division_content.get("paragraphs", []):
            para = CobolParagraph(
                para_info.get("name", ""), para_info.get("location", start_location)
            )

            # Add statements to paragraph
            for stmt_info in para_info.get("statements", []):
                if stmt_info.get("statement"):
                    para.add_statement(stmt_info["statement"])

            division_node.add_paragraph(para)

        # Add sections in parse order, each with their paragraphs
        section_order = division_content.get("section_order", [])
        sections_data = division_content.get("sections", {})
        # Fall back to dict key order if section_order not present
        ordered_names = section_order if section_order else list(sections_data.keys())

        for section_name in ordered_names:
            section_info = sections_data.get(section_name, {})
            section_location = section_info.get("location", start_location)
            section = CobolSection(section_name, section_location)
            if section_info.get("declarative"):
                section.set_metadata("declarative", True)

            # Add paragraphs belonging to this section
            for para_info in section_info.get("paragraphs", []):
                para = CobolParagraph(
                    para_info.get("name", ""),
                    para_info.get("location", section_location),
                )
                for stmt_info in para_info.get("statements", []):
                    if stmt_info.get("statement"):
                        para.add_statement(stmt_info["statement"])
                section.add_paragraph(para)

            division_node.add_section(section)

        # Count all statements across top-level paragraphs and section paragraphs
        total_paragraphs = len(division_content.get("paragraphs", []))
        total_statements = sum(
            len(p.get("statements", [])) for p in division_content.get("paragraphs", [])
        )
        for sec_info in sections_data.values():
            sec_paras = sec_info.get("paragraphs", [])
            total_paragraphs += len(sec_paras)
            total_statements += sum(len(p.get("statements", [])) for p in sec_paras)

        # Store metadata
        division_node.metadata.update(
            {
                "paragraph_count": total_paragraphs,
                "section_count": len(sections_data),
                "statement_count": total_statements,
            }
        )

        return division_node
