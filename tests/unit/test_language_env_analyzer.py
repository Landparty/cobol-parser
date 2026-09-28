"""
Unit tests for LanguageEnvironmentAnalyzer and related types.

Coverage:
- LEFunctionUsage / LEServiceCall / LEAnalysisResult dataclasses
- LanguageEnvironmentAnalyzer.analyze():
    * COMPUTE statement with FUNCTION expression
    * MOVE statement with FUNCTION source (no-space concatenation)
    * Multiple FUNCTION references in one program
    * CALL to known LE service (CEEDATM, CEEGMT, CEEGTST, CEEHDLR …)
    * CALL to unknown CEE-prefixed name (treated as LE service)
    * CALL to non-LE program (ignored)
    * Program with no language-environment usage
    * Dynamic CALL to CEE service via possible_values (is_dynamic=True)
    * USING parameter extraction
    * LEAnalysisResult properties: unique_functions, unique_services,
      service_categories, uses_intrinsic_functions, uses_language_environment
    * to_dict() on all result objects
- CobolProgram convenience methods:
    * get_le_callable_service_calls()
    * uses_language_environment()
    * get_intrinsic_function_usages()
    * uses_intrinsic_functions()
- IBMEnterpriseCobol dialect helpers:
    * is_le_callable_service()
    * get_le_service_info()
    * IBM_LE_CALLABLE_SERVICES set membership
    * get_dialect_info() includes le_callable_services count
- analysis/__init__.py lazy-import paths
- cobolparser top-level import paths
"""

from cobolparser import parse_cobol
from cobolparser.analysis.language_env_analyzer import (
    LanguageEnvironmentAnalyzer,
    LEAnalysisResult,
    LEFunctionUsage,
    LEServiceCall,
)
from cobolparser.dialects.ibm_enterprise import IBMEnterpriseCobol

# ── COBOL source helpers ───────────────────────────────────────────────────────

_MINIMAL_HEADER = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST-PROG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
"""

_PROCEDURE_HEADER = """\
       PROCEDURE DIVISION.
       MAIN-LOGIC.
"""


def _parse(source: str):
    """Parse COBOL source and return the resulting CobolProgram."""
    result = parse_cobol(source)
    assert result.ast is not None, f"Parse failed: {result.errors}"
    return result.ast


# ── Helper programs ────────────────────────────────────────────────────────────

_COMPUTE_WITH_FUNCTION = (
    _MINIMAL_HEADER
    + """\
       01 WS-LEN   PIC 9(4).
       01 WS-STR   PIC X(20).
"""
    + _PROCEDURE_HEADER
    + """\
           COMPUTE WS-LEN = FUNCTION LENGTH(WS-STR).
           STOP RUN.
"""
)

_MOVE_WITH_FUNCTION = (
    _MINIMAL_HEADER
    + """\
       01 WS-NAME  PIC X(20).
       01 WS-UPPER PIC X(20).
"""
    + _PROCEDURE_HEADER
    + """\
           MOVE FUNCTION UPPER-CASE(WS-NAME) TO WS-UPPER.
           STOP RUN.
"""
)

_CALL_LE_SERVICE = (
    _MINIMAL_HEADER
    + """\
       01 WS-SECS  PIC S9(9) COMP.
       01 WS-DATE  PIC X(21).
       01 WS-FC    PIC X(12).
"""
    + _PROCEDURE_HEADER
    + """\
           CALL "CEEDATM" USING WS-SECS WS-DATE WS-FC.
           STOP RUN.
"""
)

_CALL_MULTIPLE_LE = (
    _MINIMAL_HEADER
    + """\
       01 WS-SECS  PIC S9(9) COMP.
       01 WS-DATE  PIC X(21).
       01 WS-FC    PIC X(12).
"""
    + _PROCEDURE_HEADER
    + """\
           CALL "CEEGMT" USING WS-SECS WS-FC.
           CALL "CEEDATM" USING WS-SECS WS-DATE WS-FC.
           STOP RUN.
"""
)

_NO_LE_USAGE = (
    _MINIMAL_HEADER
    + """\
       01 WS-A PIC 9(4).
       01 WS-B PIC 9(4).
"""
    + _PROCEDURE_HEADER
    + """\
           MOVE 10 TO WS-A.
           CALL "MYSUBR" USING WS-A.
           STOP RUN.
"""
)

_BOTH_FUNCTION_AND_SERVICE = (
    _MINIMAL_HEADER
    + """\
       01 WS-LEN  PIC 9(4).
       01 WS-STR  PIC X(20).
       01 WS-SECS PIC S9(9) COMP.
       01 WS-FC   PIC X(12).
"""
    + _PROCEDURE_HEADER
    + """\
           COMPUTE WS-LEN = FUNCTION LENGTH(WS-STR).
           CALL "CEEGMT" USING WS-SECS WS-FC.
           STOP RUN.
"""
)

_UNKNOWN_CEE_SERVICE = _MINIMAL_HEADER + _PROCEDURE_HEADER + """\
           CALL "CEECUSTOM" USING WS-A.
           STOP RUN.
"""


# ── Test: dialect helpers ──────────────────────────────────────────────────────


class TestIBMEnterpriseCobolDialect:
    def setup_method(self):
        self.dialect = IBMEnterpriseCobol()

    def test_is_le_callable_service_known(self):
        assert self.dialect.is_le_callable_service("CEEDATM")
        assert self.dialect.is_le_callable_service("ceedatm")  # case-insensitive

    def test_is_le_callable_service_unknown(self):
        assert not self.dialect.is_le_callable_service("MYSUBR")
        assert not self.dialect.is_le_callable_service("CBLTDLI")

    def test_is_le_callable_service_ceetdli_known(self):
        # CEETDLI is both IMS and LE interface
        assert self.dialect.is_le_callable_service("CEETDLI")

    def test_get_le_service_info_known(self):
        info = self.dialect.get_le_service_info("CEEDATM")
        assert info is not None
        assert info["category"] == "datetime"
        assert "description" in info
        assert "parameters" in info

    def test_get_le_service_info_unknown(self):
        assert self.dialect.get_le_service_info("NONEXISTENT") is None

    def test_get_le_service_info_case_insensitive(self):
        assert self.dialect.get_le_service_info("ceegmt") is not None

    def test_le_services_set_non_empty(self):
        assert len(self.dialect.IBM_LE_CALLABLE_SERVICES) >= 40

    def test_get_dialect_info_includes_le_count(self):
        info = self.dialect.get_dialect_info()
        assert "le_callable_services" in info
        assert info["le_callable_services"] >= 40

    def test_supported_features_includes_le(self):
        assert "le_callable_services" in self.dialect.supported_features

    def test_known_services_sampling(self):
        services = self.dialect.IBM_LE_CALLABLE_SERVICES
        for name in ("CEEGMT", "CEELOCT", "CEEGTST", "CEEHDLR", "CEETERM"):
            assert name in services, f"{name} missing from IBM_LE_CALLABLE_SERVICES"


# ── Test: LEFunctionUsage dataclass ───────────────────────────────────────────


class TestLEFunctionUsage:
    def test_to_dict_basic(self):
        usage = LEFunctionUsage(
            function_name="LENGTH",
            is_ibm_function=True,
            statement_type="COMPUTE",
            context_text="FUNCTION LENGTH ( WS-STR )",
        )
        d = usage.to_dict()
        assert d["function_name"] == "LENGTH"
        assert d["is_ibm_function"] is True
        assert d["statement_type"] == "COMPUTE"
        assert d["context_text"] == "FUNCTION LENGTH ( WS-STR )"
        assert d["location"] is None

    def test_non_ibm_function_flagged(self):
        usage = LEFunctionUsage(
            function_name="CUSTOM-FUNC",
            is_ibm_function=False,
            statement_type="COMPUTE",
        )
        assert not usage.is_ibm_function


# ── Test: LEServiceCall dataclass ─────────────────────────────────────────────


class TestLEServiceCall:
    def test_to_dict_basic(self):
        call = LEServiceCall(
            service_name="CEEDATM",
            is_known_service=True,
            is_dynamic=False,
            using_params=["WS-SECS", "WS-DATE", "WS-FC"],
            category="datetime",
        )
        d = call.to_dict()
        assert d["service_name"] == "CEEDATM"
        assert d["is_known_service"] is True
        assert d["is_dynamic"] is False
        assert d["using_params"] == ["WS-SECS", "WS-DATE", "WS-FC"]
        assert d["category"] == "datetime"
        assert d["location"] is None


# ── Test: LEAnalysisResult properties ─────────────────────────────────────────


class TestLEAnalysisResult:
    def test_empty_result(self):
        result = LEAnalysisResult()
        assert not result.uses_intrinsic_functions
        assert not result.uses_language_environment
        assert result.unique_functions == []
        assert result.unique_services == []
        assert result.service_categories == set()

    def test_unique_functions_deduplicates(self):
        result = LEAnalysisResult(
            intrinsic_usages=[
                LEFunctionUsage("LENGTH", True, "COMPUTE"),
                LEFunctionUsage("LENGTH", True, "MOVE"),
                LEFunctionUsage("UPPER-CASE", True, "MOVE"),
            ]
        )
        assert result.unique_functions == ["LENGTH", "UPPER-CASE"]

    def test_unique_services_deduplicates(self):
        result = LEAnalysisResult(
            le_service_calls=[
                LEServiceCall("CEEGMT", True, False, category="datetime"),
                LEServiceCall("CEEGMT", True, False, category="datetime"),
                LEServiceCall("CEEDATM", True, False, category="datetime"),
            ]
        )
        assert result.unique_services == ["CEEDATM", "CEEGMT"]

    def test_service_categories(self):
        result = LEAnalysisResult(
            le_service_calls=[
                LEServiceCall("CEEGMT", True, False, category="datetime"),
                LEServiceCall("CEEGTST", True, False, category="storage"),
            ]
        )
        assert result.service_categories == {"datetime", "storage"}

    def test_to_dict_keys(self):
        result = LEAnalysisResult()
        d = result.to_dict()
        for key in (
            "uses_intrinsic_functions",
            "uses_language_environment",
            "unique_functions",
            "unique_services",
            "service_categories",
            "intrinsic_usages",
            "le_service_calls",
        ):
            assert key in d, f"Missing key: {key}"


# ── Test: COMPUTE with FUNCTION expression ────────────────────────────────────


class TestComputeWithFunction:
    def setup_method(self):
        self.program = _parse(_COMPUTE_WITH_FUNCTION)
        self.analyzer = LanguageEnvironmentAnalyzer()

    def test_detects_length_function(self):
        report = self.analyzer.analyze(self.program)
        assert report.uses_intrinsic_functions
        assert "LENGTH" in report.unique_functions

    def test_length_is_ibm_function(self):
        report = self.analyzer.analyze(self.program)
        usage = next(u for u in report.intrinsic_usages if u.function_name == "LENGTH")
        assert usage.is_ibm_function

    def test_no_le_services_detected(self):
        report = self.analyzer.analyze(self.program)
        assert not report.uses_language_environment

    def test_statement_type_recorded(self):
        report = self.analyzer.analyze(self.program)
        types = {u.statement_type for u in report.intrinsic_usages}
        assert "COMPUTE" in types


# ── Test: MOVE with FUNCTION source ───────────────────────────────────────────


class TestMoveWithFunction:
    def setup_method(self):
        self.program = _parse(_MOVE_WITH_FUNCTION)
        self.analyzer = LanguageEnvironmentAnalyzer()

    def test_detects_upper_case_function(self):
        report = self.analyzer.analyze(self.program)
        assert report.uses_intrinsic_functions
        assert "UPPER-CASE" in report.unique_functions

    def test_upper_case_is_ibm_function(self):
        report = self.analyzer.analyze(self.program)
        usage = next(
            u for u in report.intrinsic_usages if u.function_name == "UPPER-CASE"
        )
        assert usage.is_ibm_function


# ── Test: CALL to known LE service ────────────────────────────────────────────


class TestCallLEService:
    def setup_method(self):
        self.program = _parse(_CALL_LE_SERVICE)
        self.analyzer = LanguageEnvironmentAnalyzer()

    def test_detects_ceedatm(self):
        report = self.analyzer.analyze(self.program)
        assert report.uses_language_environment
        assert "CEEDATM" in report.unique_services

    def test_ceedatm_is_known(self):
        report = self.analyzer.analyze(self.program)
        call = next(c for c in report.le_service_calls if c.service_name == "CEEDATM")
        assert call.is_known_service

    def test_ceedatm_category_is_datetime(self):
        report = self.analyzer.analyze(self.program)
        call = next(c for c in report.le_service_calls if c.service_name == "CEEDATM")
        assert call.category == "datetime"

    def test_using_params_extracted(self):
        report = self.analyzer.analyze(self.program)
        call = next(c for c in report.le_service_calls if c.service_name == "CEEDATM")
        assert "WS-SECS" in call.using_params
        assert "WS-DATE" in call.using_params
        assert "WS-FC" in call.using_params

    def test_no_intrinsic_functions(self):
        report = self.analyzer.analyze(self.program)
        assert not report.uses_intrinsic_functions


# ── Test: multiple LE service calls ───────────────────────────────────────────


class TestMultipleLEServiceCalls:
    def setup_method(self):
        self.program = _parse(_CALL_MULTIPLE_LE)
        self.analyzer = LanguageEnvironmentAnalyzer()

    def test_detects_both_services(self):
        report = self.analyzer.analyze(self.program)
        assert "CEEGMT" in report.unique_services
        assert "CEEDATM" in report.unique_services

    def test_two_service_calls_recorded(self):
        report = self.analyzer.analyze(self.program)
        assert len(report.le_service_calls) == 2


# ── Test: no LE usage ─────────────────────────────────────────────────────────


class TestNoLEUsage:
    def setup_method(self):
        self.program = _parse(_NO_LE_USAGE)
        self.analyzer = LanguageEnvironmentAnalyzer()

    def test_no_intrinsic_functions(self):
        report = self.analyzer.analyze(self.program)
        assert not report.uses_intrinsic_functions

    def test_no_le_services(self):
        report = self.analyzer.analyze(self.program)
        assert not report.uses_language_environment

    def test_non_cee_call_ignored(self):
        report = self.analyzer.analyze(self.program)
        # MYSUBR must not be flagged as an LE service
        assert all(c.service_name != "MYSUBR" for c in report.le_service_calls)


# ── Test: both FUNCTION and LE service ────────────────────────────────────────


class TestBothFunctionAndService:
    def setup_method(self):
        self.program = _parse(_BOTH_FUNCTION_AND_SERVICE)
        self.analyzer = LanguageEnvironmentAnalyzer()

    def test_reports_both(self):
        report = self.analyzer.analyze(self.program)
        assert report.uses_intrinsic_functions
        assert report.uses_language_environment

    def test_to_dict_complete(self):
        report = self.analyzer.analyze(self.program)
        d = report.to_dict()
        assert d["uses_intrinsic_functions"] is True
        assert d["uses_language_environment"] is True
        assert len(d["intrinsic_usages"]) >= 1
        assert len(d["le_service_calls"]) >= 1


# ── Test: unknown CEE-prefixed service ────────────────────────────────────────


class TestUnknownCEEService:
    def setup_method(self):
        self.program = _parse(_UNKNOWN_CEE_SERVICE)
        self.analyzer = LanguageEnvironmentAnalyzer()

    def test_cee_prefixed_unknown_detected(self):
        report = self.analyzer.analyze(self.program)
        assert report.uses_language_environment
        assert "CEECUSTOM" in report.unique_services

    def test_unknown_service_flagged_not_known(self):
        report = self.analyzer.analyze(self.program)
        call = next(c for c in report.le_service_calls if c.service_name == "CEECUSTOM")
        assert not call.is_known_service

    def test_unknown_service_category_is_unknown(self):
        report = self.analyzer.analyze(self.program)
        call = next(c for c in report.le_service_calls if c.service_name == "CEECUSTOM")
        assert call.category == "unknown"


# ── Test: CobolProgram convenience methods ────────────────────────────────────


class TestCobolProgramMethods:
    def test_get_le_callable_service_calls_found(self):
        program = _parse(_CALL_LE_SERVICE)
        calls = program.get_le_callable_service_calls()
        assert len(calls) == 1
        assert calls[0].called_program == "CEEDATM"

    def test_get_le_callable_service_calls_none(self):
        program = _parse(_NO_LE_USAGE)
        assert program.get_le_callable_service_calls() == []

    def test_uses_language_environment_true(self):
        program = _parse(_CALL_LE_SERVICE)
        assert program.uses_language_environment()

    def test_uses_language_environment_false(self):
        program = _parse(_NO_LE_USAGE)
        assert not program.uses_language_environment()

    def test_get_intrinsic_function_usages_compute(self):
        program = _parse(_COMPUTE_WITH_FUNCTION)
        usages = program.get_intrinsic_function_usages()
        assert "LENGTH" in usages

    def test_get_intrinsic_function_usages_move(self):
        program = _parse(_MOVE_WITH_FUNCTION)
        usages = program.get_intrinsic_function_usages()
        assert "UPPER-CASE" in usages

    def test_get_intrinsic_function_usages_none(self):
        program = _parse(_NO_LE_USAGE)
        assert program.get_intrinsic_function_usages() == []

    def test_uses_intrinsic_functions_true(self):
        program = _parse(_COMPUTE_WITH_FUNCTION)
        assert program.uses_intrinsic_functions()

    def test_uses_intrinsic_functions_false(self):
        program = _parse(_NO_LE_USAGE)
        assert not program.uses_intrinsic_functions()


# ── Test: dynamic CALL detection ─────────────────────────────────────────────
#
# Dynamic calls use a variable as the called program name.  The
# LanguageEnvironmentAnalyzer (and CobolProgram helpers) detect LE services
# by inspecting CallStatement.possible_values, which is populated by
# DynamicCallAnalyzer.  We simulate this by manually injecting possible_values
# into the CallStatement after parsing.


class TestDynamicCallDetection:
    def _parse_and_inject(self, source: str, service_name: str):
        """Parse *source*, find the dynamic CALL, and inject *service_name*
        into its possible_values to simulate DynamicCallAnalyzer output."""
        program = _parse(source)
        for stmt in program.get_all_statements():
            if stmt.statement_type == "CALL" and getattr(stmt, "is_dynamic", False):
                stmt.add_possible_value(service_name)
        return program

    _DYNAMIC_CALL_SOURCE = (
        _MINIMAL_HEADER
        + """\
       01 WS-PGMNAME PIC X(8) VALUE "CEEGMT".
       01 WS-SECS    PIC S9(9) COMP.
       01 WS-FC      PIC X(12).
"""
        + _PROCEDURE_HEADER
        + """\
           CALL WS-PGMNAME USING WS-SECS WS-FC.
           STOP RUN.
"""
    )

    def test_analyzer_detects_dynamic_le_call(self):
        program = self._parse_and_inject(self._DYNAMIC_CALL_SOURCE, "CEEGMT")
        analyzer = LanguageEnvironmentAnalyzer()
        report = analyzer.analyze(program)
        assert report.uses_language_environment
        assert "CEEGMT" in report.unique_services

    def test_dynamic_call_is_flagged_as_dynamic(self):
        program = self._parse_and_inject(self._DYNAMIC_CALL_SOURCE, "CEEGMT")
        analyzer = LanguageEnvironmentAnalyzer()
        report = analyzer.analyze(program)
        call = next(c for c in report.le_service_calls if c.service_name == "CEEGMT")
        assert call.is_dynamic is True

    def test_dynamic_call_category_resolved(self):
        program = self._parse_and_inject(self._DYNAMIC_CALL_SOURCE, "CEEGMT")
        analyzer = LanguageEnvironmentAnalyzer()
        report = analyzer.analyze(program)
        call = next(c for c in report.le_service_calls if c.service_name == "CEEGMT")
        assert call.category == "datetime"

    def test_program_method_detects_dynamic_le_call(self):
        program = self._parse_and_inject(self._DYNAMIC_CALL_SOURCE, "CEEDATM")
        assert program.uses_language_environment()

    def test_dynamic_call_unknown_program_ignored(self):
        """A dynamic CALL with no CEE-prefixed possible_values is not reported."""
        program = _parse(self._DYNAMIC_CALL_SOURCE)
        # Do NOT inject any possible_values → nothing to detect
        analyzer = LanguageEnvironmentAnalyzer()
        report = analyzer.analyze(program)
        assert not report.uses_language_environment


# ── Test: lazy import paths ────────────────────────────────────────────────────


class TestLazyImports:
    def test_import_from_analysis_package(self):
        from cobolparser.analysis import (  # noqa: F401
            LanguageEnvironmentAnalyzer,
            LEAnalysisResult,
            LEFunctionUsage,
            LEServiceCall,
        )

    def test_import_from_top_level(self):
        from cobolparser import (  # noqa: F401
            LanguageEnvironmentAnalyzer,
            LEAnalysisResult,
            LEFunctionUsage,
            LEServiceCall,
        )

    def test_analyzer_instantiation(self):
        from cobolparser import LanguageEnvironmentAnalyzer

        analyzer = LanguageEnvironmentAnalyzer()
        assert analyzer is not None


class TestIntrinsicReferenceBoundaries:
    """A data name containing FUNCTION is not a function reference, and a
    reference in a condition or a STRING sending field is still one."""

    _SRC = (
        _MINIMAL_HEADER
        + """\
       01 WS-FUNCTIONAL PIC X(8).
       01 DLI-FUNCTIONS PIC X(8).
       01 FUNCTIONAL-CODE PIC X(8).
       01 WS-X PIC X(8).
"""
        + _PROCEDURE_HEADER
        + """\
           MOVE WS-FUNCTIONAL TO WS-X.
           MOVE DLI-FUNCTIONS TO WS-X.
           MOVE FUNCTIONAL-CODE TO WS-X.
           IF FUNCTION LENGTH(WS-X) > 3 AND FUNCTION MAX(1 2) = 2
              CONTINUE
           END-IF.
           PERFORM UNTIL FUNCTION MOD(3 2) = 1 CONTINUE END-PERFORM.
           STRING FUNCTION UPPER-CASE(WS-X) DELIMITED SIZE INTO WS-X.
           GOBACK.
"""
    )

    def test_only_real_references_reported(self):
        report = LanguageEnvironmentAnalyzer().analyze(_parse(self._SRC))
        found = [(u.function_name, u.statement_type) for u in report.intrinsic_usages]
        assert found == [
            ("LENGTH", "IF"),
            ("MAX", "IF"),
            ("MOD", "PERFORM"),
            ("UPPER-CASE", "STRING"),
        ]
        assert all(u.is_ibm_function for u in report.intrinsic_usages)


class TestEnterpriseSixIntrinsics:
    """Intrinsics added after COBOL-85 (Enterprise COBOL 3.x-6.4) are IBM
    functions too; TRIM, NUMVAL-F, FORMATTED-DATETIME and BYTE-LENGTH used
    to be reported with is_ibm_function False."""

    _SRC = (
        _MINIMAL_HEADER
        + """\
       01 WS-A PIC X(20).
       01 WS-N PIC 9(8).
       01 WS-TS PIC X(40).
"""
        + _PROCEDURE_HEADER
        + """\
           MOVE FUNCTION TRIM(WS-A) TO WS-A.
           COMPUTE WS-N = FUNCTION NUMVAL-F(WS-A).
           MOVE FUNCTION FORMATTED-DATETIME('YYYYMMDDThhmmss' WS-N 1)
             TO WS-TS.
           COMPUTE WS-N = FUNCTION BYTE-LENGTH(WS-A).
           GOBACK.
"""
    )

    def test_reported_as_ibm_functions(self):
        report = LanguageEnvironmentAnalyzer().analyze(_parse(self._SRC))
        found = {u.function_name: u.is_ibm_function for u in report.intrinsic_usages}
        assert found == {
            "TRIM": True,
            "NUMVAL-F": True,
            "FORMATTED-DATETIME": True,
            "BYTE-LENGTH": True,
        }
