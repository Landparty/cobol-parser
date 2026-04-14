"""
Language Environment (LE) function and service analyzer.

Detects two categories of IBM Language Environment usage in COBOL programs:

1. **COBOL intrinsic functions** – expressions of the form
   ``FUNCTION <name>(<args>)`` (e.g. ``FUNCTION LENGTH(WS-VAR)``,
   ``FUNCTION UPPER-CASE(WS-NAME)``).

2. **IBM LE callable services** – ``CALL "CEExxxx"`` statements that invoke
   IBM Language Environment runtime services such as ``CEEDATM``,
   ``CEEGMT``, ``CEEGTST``, ``CEEHDLR``, etc.

The analyzer works entirely on the already-parsed AST – no re-tokenization is
required.  Intrinsic function references are found by scanning every statement's
text fields (operands, expression strings, source fields) with a regex that
recognises both ``FUNCTION LENGTH`` (space-separated, as stored by the COMPUTE
parser) and ``FUNCTIONLENGTH`` (concatenated, as stored by the MOVE parser).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..models.program import CobolProgram
    from ..models.statements.base import CobolStatement

# Matches FUNCTION followed immediately or with spaces by an identifier name.
# Handles both concatenated form (MOVE parser) and space-separated form
# (COMPUTE parser).
_FUNCTION_RE = re.compile(
    r"FUNCTION\s*([A-Z][A-Z0-9-]*)",
    re.IGNORECASE,
)

# IBM intrinsic function names from the IBM Enterprise COBOL dialect
_IBM_INTRINSIC_FUNCTIONS: frozenset[str] = frozenset(
    {
        "ACOS",
        "ANNUITY",
        "ASIN",
        "ATAN",
        "CHAR",
        "COS",
        "CURRENT-DATE",
        "DATE-OF-INTEGER",
        "DATE-TO-YYYYMMDD",
        "DAY-OF-INTEGER",
        "DAY-TO-YYYYDDD",
        "FACTORIAL",
        "INTEGER",
        "INTEGER-OF-DATE",
        "INTEGER-OF-DAY",
        "LENGTH",
        "LOG",
        "LOG10",
        "LOWER-CASE",
        "MAX",
        "MEAN",
        "MEDIAN",
        "MIDRANGE",
        "MIN",
        "MOD",
        "NUMVAL",
        "NUMVAL-C",
        "ORD",
        "ORD-MAX",
        "ORD-MIN",
        "PRESENT-VALUE",
        "RANDOM",
        "RANGE",
        "REM",
        "REVERSE",
        "SIN",
        "SQRT",
        "STANDARD-DEVIATION",
        "SUM",
        "TAN",
        "UPPER-CASE",
        "VARIANCE",
        "WHEN-COMPILED",
        "YEAR-TO-YYYY",
    }
)

# IBM LE callable service names (CEE prefix)
_IBM_LE_SERVICES: frozenset[str] = frozenset(
    {
        "CEEDATM",
        "CEEDATE",
        "CEETIME",
        "CEEGMT",
        "CEELOCT",
        "CEESECS",
        "CEEFMTDT",
        "CEEDTTM",
        "CEEDYWK",
        "CEEGMTO",
        "CEEGMTCO",
        "CEEFMTVF",
        "CEEGTST",
        "CEEFRMST",
        "CEECREH",
        "CEEDSHP",
        "CEECRHP",
        "CEEZLNG",
        "CEEHDLR",
        "CEETREC",
        "CEEHOOK",
        "CEEMRCR",
        "CEENDUC",
        "CEERADR",
        "CEESGL",
        "CEEDUMP",
        "CEEABND",
        "CEENVST",
        "CEEENV",
        "CEEGPID",
        "CEEGPIL",
        "CEEGMEM",
        "CEEGLS",
        "CEETERM",
        "CEEBINIT",
        "CEEPCMD",
        "CEEMSG",
        "CEEGLOB",
        "CEEGSS",
        "CEESST",
        "CEESG",
        "CEESQ",
        "CEECZST",
        "CEETDLI",
    }
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


# ── Service category lookup ────────────────────────────────────────────────────

_LE_SERVICE_CATEGORY: dict[str, str] = {
    "CEEDATM": "datetime",
    "CEEDATE": "datetime",
    "CEETIME": "datetime",
    "CEEGMT": "datetime",
    "CEELOCT": "datetime",
    "CEESECS": "datetime",
    "CEEFMTDT": "datetime",
    "CEEDTTM": "datetime",
    "CEEDYWK": "datetime",
    "CEEGMTO": "datetime",
    "CEEGMTCO": "datetime",
    "CEEFMTVF": "datetime",
    "CEEGTST": "storage",
    "CEEFRMST": "storage",
    "CEECREH": "storage",
    "CEEDSHP": "storage",
    "CEECRHP": "storage",
    "CEEZLNG": "string",
    "CEEHDLR": "condition",
    "CEETREC": "condition",
    "CEEHOOK": "condition",
    "CEEMRCR": "condition",
    "CEENDUC": "condition",
    "CEERADR": "condition",
    "CEESGL": "condition",
    "CEEDUMP": "condition",
    "CEEABND": "condition",
    "CEENVST": "environment",
    "CEEENV": "environment",
    "CEEGPID": "environment",
    "CEEGPIL": "environment",
    "CEEGMEM": "environment",
    "CEEGLS": "string",
    "CEETERM": "runtime",
    "CEEBINIT": "runtime",
    "CEEPCMD": "runtime",
    "CEEMSG": "runtime",
    "CEEGLOB": "runtime",
    "CEEGSS": "storage",
    "CEESST": "storage",
    "CEESG": "string",
    "CEESQ": "string",
    "CEECZST": "string",
    "CEETDLI": "ims",
}


def _is_le_service(name: str) -> bool:
    """Return True if *name* is a known IBM LE callable service."""
    return name.upper() in _IBM_LE_SERVICES


def _is_cee_prefixed(name: str) -> bool:
    """Return True if *name* starts with the CEE prefix (case-insensitive)."""
    return name.upper().startswith("CEE")


def _collect_text_fields(stmt: CobolStatement) -> list[str]:
    """Collect all text fields from a statement that may contain FUNCTION refs.

    Returns a list of (non-empty) strings to scan for ``FUNCTION <name>``
    patterns.
    """
    fields: list[str] = []

    # Base operands list present on every statement
    for op in stmt.operands:
        if op:
            fields.append(op)

    # ComputeStatement.expression (stored as space-joined token values)
    expr = getattr(stmt, "expression", None)
    if isinstance(expr, str) and expr:
        fields.append(expr)

    # MoveStatement.source (stored as concatenated token values, no spaces)
    source = getattr(stmt, "source", None)
    if isinstance(source, str) and source:
        fields.append(source)

    # DisplayStatement items
    items = getattr(stmt, "items", None)
    if isinstance(items, list):
        for item in items:
            if isinstance(item, str) and item:
                fields.append(item)

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
                func_name = match.group(1).upper()
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
        """Detect CALL statements that target IBM LE callable services."""
        if stmt.statement_type != "CALL":
            return

        called = getattr(stmt, "called_program", None)
        if not called:
            return

        # Strip surrounding quotes if present (static call literals are stored
        # without quotes by the parser, but defensive strip is harmless)
        service_name = called.strip("\"'").upper()

        # Accept either a known LE service or any CEE-prefixed name
        if not (_is_le_service(service_name) or _is_cee_prefixed(service_name)):
            return

        is_dynamic = getattr(stmt, "_is_dynamic", False)
        using_params = [
            p.name
            for p in getattr(stmt, "using_parameters", [])
        ]

        result.le_service_calls.append(
            LEServiceCall(
                service_name=service_name,
                is_known_service=_is_le_service(service_name),
                is_dynamic=is_dynamic,
                using_params=using_params,
                location=getattr(stmt, "location", None),
                category=_LE_SERVICE_CATEGORY.get(service_name, "unknown"),
            )
        )
