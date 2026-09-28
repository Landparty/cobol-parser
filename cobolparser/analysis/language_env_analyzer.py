"""
Language Environment (LE) function and service analyzer.

Detects two categories of IBM Language Environment usage in COBOL programs:

1. **COBOL intrinsic functions** – expressions of the form
   ``FUNCTION <name>(<args>)`` (e.g. ``FUNCTION LENGTH(WS-VAR)``,
   ``FUNCTION UPPER-CASE(WS-NAME)``).

2. **IBM LE callable services** – ``CALL "CEExxxx"`` statements that invoke
   IBM Language Environment runtime services such as ``CEEDATM``,
   ``CEEGMT``, ``CEEGTST``, ``CEEHDLR``, etc.  Dynamic calls whose
   ``possible_values`` (populated by :class:`~cobolparser.analysis.
   value_tracker.DynamicCallAnalyzer`) contain a CEE-prefixed name are also
   reported.

The analyzer works entirely on the already-parsed AST – no re-tokenization is
required.  Intrinsic function references are found by scanning every
statement's text fields (operands, expression strings, source fields) with a
regex that recognises both ``FUNCTION LENGTH`` (space-separated, as stored by
the COMPUTE parser) and ``FUNCTIONLENGTH`` (concatenated, as stored by the
MOVE parser).

All function-name and service-name constants are sourced from
:class:`~cobolparser.dialects.ibm_enterprise.IBMEnterpriseCobol` so that the
dialect module remains the single source of truth.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..dialects.ibm_enterprise import IBMEnterpriseCobol

if TYPE_CHECKING:
    from ..models.program import CobolProgram
    from ..models.statements.base import CobolStatement

# Matches FUNCTION followed immediately or with spaces by an identifier name.
# Handles both concatenated form (MOVE parser) and space-separated form
# (COMPUTE parser).
#
# FUNCTION must be a word of its own: a data name that merely contains it
# (WS-FUNCTIONAL, DLI-FUNCTIONS, FUNCTIONAL-CODE) is not a function
# reference, and used to be reported as intrinsic "AL", "S", "AL-CODE".
# The no-space form is accepted only for a known intrinsic name (see
# `_check_intrinsic_functions`), which is what tells FUNCTIONLENGTH from
# FUNCTIONAL-CODE.
_FUNCTION_RE = re.compile(
    r"(?<![A-Z0-9-])FUNCTION(\s*)([A-Z][A-Z0-9-]*)",
    re.IGNORECASE,
)

# Single source of truth: reference the dialect class attributes directly.
_IBM_INTRINSIC_FUNCTIONS: frozenset[str] = frozenset(
    IBMEnterpriseCobol.IBM_INTRINSIC_FUNCTIONS
)
_IBM_LE_SERVICES: frozenset[str] = frozenset(
    IBMEnterpriseCobol.IBM_LE_CALLABLE_SERVICES
)
_LE_SERVICE_CATEGORY: dict[str, str] = dict(
    IBMEnterpriseCobol.IBM_LE_SERVICE_CATEGORIES
)


@dataclass
class LEFunctionUsage:
    """A single intrinsic FUNCTION reference found in a COBOL statement.

    Attributes:
        function_name:  Upper-cased name of the intrinsic function
                        (e.g. ``"LENGTH"``, ``"UPPER-CASE"``).
        is_ibm_function: True when the name is in IBM Enterprise COBOL's
                         intrinsic-function set.
        statement_type: Statement verb in which the reference appeared
                        (e.g. ``"MOVE"``, ``"COMPUTE"``).
        context_text:   The operand / expression text where the match was
                        found (may be ``None`` when not available).
        location:       Source location of the containing statement, or
                        ``None`` when unavailable.
    """

    function_name: str
    is_ibm_function: bool
    statement_type: str
    context_text: str | None = None
    location: object = None  # SourceLocation or None

    def to_dict(self) -> dict:
        """Return a JSON-serialisable dict."""
        return {
            "function_name": self.function_name,
            "is_ibm_function": self.is_ibm_function,
            "statement_type": self.statement_type,
            "context_text": self.context_text,
            "location": (
                self.location.to_dict()
                if self.location and hasattr(self.location, "to_dict")
                else None
            ),
        }


@dataclass
class LEServiceCall:
    """A CALL statement that targets an IBM LE callable service.

    Attributes:
        service_name:  Upper-cased CEE service name (e.g. ``"CEEDATM"``).
        is_known_service: True when the name is in the known LE service set.
        is_dynamic:    True when the called name came from a variable rather
                       than a string literal.
        using_params:  List of parameter names from the USING clause.
        location:      Source location of the CALL statement, or ``None``.
        category:      Service category derived from the IBM LE service
                       catalogue (e.g. ``"datetime"``, ``"storage"``), or
                       ``"unknown"`` for unrecognised services.
    """

    service_name: str
    is_known_service: bool
    is_dynamic: bool
    using_params: list[str] = field(default_factory=list)
    location: object = None  # SourceLocation or None
    category: str = "unknown"

    def to_dict(self) -> dict:
        """Return a JSON-serialisable dict."""
        return {
            "service_name": self.service_name,
            "is_known_service": self.is_known_service,
            "is_dynamic": self.is_dynamic,
            "using_params": self.using_params,
            "category": self.category,
            "location": (
                self.location.to_dict()
                if self.location and hasattr(self.location, "to_dict")
                else None
            ),
        }


@dataclass
class LEAnalysisResult:
    """Full Language Environment analysis result for a COBOL program.

    Attributes:
        intrinsic_usages:  All FUNCTION references found.
        le_service_calls:  All CALL statements to IBM LE services.
    """

    intrinsic_usages: list[LEFunctionUsage] = field(default_factory=list)
    le_service_calls: list[LEServiceCall] = field(default_factory=list)

    @property
    def uses_intrinsic_functions(self) -> bool:
        """True if any FUNCTION reference was found."""
        return bool(self.intrinsic_usages)

    @property
    def uses_language_environment(self) -> bool:
        """True if any IBM LE callable service was found."""
        return bool(self.le_service_calls)

    @property
    def unique_functions(self) -> list[str]:
        """Sorted list of unique intrinsic function names used."""
        return sorted({u.function_name for u in self.intrinsic_usages})

    @property
    def unique_services(self) -> list[str]:
        """Sorted list of unique LE service names called."""
        return sorted({c.service_name for c in self.le_service_calls})

    @property
    def service_categories(self) -> set[str]:
        """Set of LE service categories present in the program."""
        return {c.category for c in self.le_service_calls}

    def to_dict(self) -> dict:
        """Return a JSON-serialisable summary dict."""
        return {
            "uses_intrinsic_functions": self.uses_intrinsic_functions,
            "uses_language_environment": self.uses_language_environment,
            "unique_functions": self.unique_functions,
            "unique_services": self.unique_services,
            "service_categories": sorted(self.service_categories),
            "intrinsic_usages": [u.to_dict() for u in self.intrinsic_usages],
            "le_service_calls": [c.to_dict() for c in self.le_service_calls],
        }


# ── Helper functions ───────────────────────────────────────────────────────────


def _is_le_service(name: str) -> bool:
    """Return True if *name* is a known IBM LE callable service."""
    return name.upper() in _IBM_LE_SERVICES


def _is_cee_prefixed(name: str) -> bool:
    """Return True if *name* starts with the CEE prefix (case-insensitive)."""
    return name.upper().startswith("CEE")


def _collect_text_fields(stmt: CobolStatement) -> list[str]:
    """Collect all text fields from a statement that may contain FUNCTION refs.

    Returns a list of (non-empty, non-duplicate) strings to scan for
    ``FUNCTION <name>`` patterns.
    """
    seen: set[str] = set()
    fields: list[str] = []

    def _add(text: str | None) -> None:
        if not text or text in seen:
            return
        # A quoted string literal can never contain a real intrinsic-function
        # reference — DISPLAY 'FUNCTION KEYS ARE DISABLED' is prose, not a
        # FUNCTION call — so scanning it only manufactures false positives.
        if len(text) >= 2 and text[0] == text[-1] and text[0] in ("'", '"'):
            return
        seen.add(text)
        fields.append(text)

    # Base operands list present on every statement. Some parsers (STRING)
    # split `FUNCTION UPPER-CASE(X)` into a bare "FUNCTION" operand and the
    # call that follows it; rejoin the pair so the reference is not lost.
    operands = list(stmt.operands)
    for index, op in enumerate(operands):
        if (
            isinstance(op, str)
            and op.strip().upper() == "FUNCTION"
            and index + 1 < len(operands)
        ):
            _add(f"FUNCTION {operands[index + 1]}")
        else:
            _add(op)

    # IF / PERFORM UNTIL conditions: `IF FUNCTION LENGTH(X) > 3` keeps its
    # operand text on the condition tree, not on the statement's operands.
    def _add_condition(node: object) -> None:
        raw = getattr(node, "operands", None)
        if isinstance(raw, list) and raw:
            # The whole condition's text (PERFORM UNTIL); its tree below
            # repeats the same operands, so stop here.
            for text in raw:
                if isinstance(text, str):
                    _add(text)
            return
        for attr in ("left_operand", "right_operand"):
            value = getattr(node, attr, None)
            if isinstance(value, str):
                _add(value)
        for child in getattr(node, "children", None) or []:
            _add_condition(child)

    for attr in ("condition", "until_condition"):
        condition = getattr(stmt, attr, None)
        if condition is not None and not isinstance(condition, str):
            _add_condition(condition)

    # ComputeStatement.expression (stored as space-joined token values)
    _add(getattr(stmt, "expression", None))

    # MoveStatement.source (stored as concatenated token values, no spaces).
    # Skip it when it is already present in operands to avoid double-counting
    # FUNCTION occurrences from the same canonical source text.
    source = getattr(stmt, "source", None)
    if isinstance(source, str) and source not in stmt.operands:
        _add(source)

    # DisplayStatement.display_items
    display_items = getattr(stmt, "display_items", None)
    if isinstance(display_items, list):
        for item in display_items:
            if isinstance(item, str):
                _add(item)

    return fields


class LanguageEnvironmentAnalyzer:
    """Detect COBOL intrinsic function usage and IBM LE callable service calls.

    Usage::

        from cobolparser import parse_cobol
        from cobolparser.analysis import LanguageEnvironmentAnalyzer

        result = parse_cobol(source)
        analyzer = LanguageEnvironmentAnalyzer()
        report = analyzer.analyze(result.ast)

        print(report.unique_functions)   # ['LENGTH', 'UPPER-CASE']
        print(report.unique_services)    # ['CEEDATM', 'CEEGMT']
        print(report.uses_language_environment)  # True

    For dynamic ``CALL`` detection, run
    :class:`~cobolparser.analysis.value_tracker.DynamicCallAnalyzer` on the
    program **before** calling :meth:`analyze` so that
    ``CallStatement.possible_values`` is populated.
    """

    def analyze(self, program: CobolProgram) -> LEAnalysisResult:
        """Analyse *program* and return an :class:`LEAnalysisResult`.

        Args:
            program: A parsed :class:`~cobolparser.models.program.CobolProgram`.

        Returns:
            An :class:`LEAnalysisResult` with all findings.
        """
        result = LEAnalysisResult()
        all_statements = program.get_all_statements()

        for stmt in all_statements:
            self._check_intrinsic_functions(stmt, result)
            self._check_le_service_call(stmt, result)

        return result

    # ── Private helpers ────────────────────────────────────────────────────────

    def _check_intrinsic_functions(
        self, stmt: CobolStatement, result: LEAnalysisResult
    ) -> None:
        """Scan *stmt* text fields for FUNCTION keyword usage."""
        texts = _collect_text_fields(stmt)
        for text in texts:
            for match in _FUNCTION_RE.finditer(text):
                func_name = match.group(2).upper()
                if not match.group(1) and func_name not in _IBM_INTRINSIC_FUNCTIONS:
                    continue
                result.intrinsic_usages.append(
                    LEFunctionUsage(
                        function_name=func_name,
                        is_ibm_function=func_name in _IBM_INTRINSIC_FUNCTIONS,
                        statement_type=stmt.statement_type,
                        context_text=text,
                        location=getattr(stmt, "location", None),
                    )
                )

    def _check_le_service_call(
        self, stmt: CobolStatement, result: LEAnalysisResult
    ) -> None:
        """Detect CALL statements that target IBM LE callable services.

        Static calls are matched by the literal program name.  Dynamic calls
        are matched when ``CallStatement.possible_values`` (populated by
        ``DynamicCallAnalyzer``) contains a CEE-prefixed or known LE service
        name.
        """
        if stmt.statement_type != "CALL":
            return

        is_dynamic: bool = getattr(stmt, "is_dynamic", False)
        using_params: list[str] = [
            p.name for p in getattr(stmt, "using_parameters", [])
        ]
        location = getattr(stmt, "location", None)

        candidate_names: list[str] = []

        if is_dynamic:
            # Resolve via DynamicCallAnalyzer-populated possible_values
            possible = getattr(stmt, "possible_values", None) or []
            if isinstance(possible, str):
                possible = [possible]
            for value in possible:
                if not value:
                    continue
                name = str(value).strip("\"'").upper()
                if _is_le_service(name) or _is_cee_prefixed(name):
                    candidate_names.append(name)
        else:
            called = getattr(stmt, "called_program", None)
            if not called:
                return
            name = called.strip("\"'").upper()
            if _is_le_service(name) or _is_cee_prefixed(name):
                candidate_names.append(name)

        # Deduplicate while preserving order
        seen: set[str] = set()
        for service_name in candidate_names:
            if service_name in seen:
                continue
            seen.add(service_name)
            result.le_service_calls.append(
                LEServiceCall(
                    service_name=service_name,
                    is_known_service=_is_le_service(service_name),
                    is_dynamic=is_dynamic,
                    using_params=using_params,
                    location=location,
                    category=_LE_SERVICE_CATEGORY.get(service_name, "unknown"),
                )
            )
