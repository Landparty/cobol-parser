"""Strict support tests for the NIST COBOL-85 validation suite.

``examples/cobol/`` contains the real-life NIST COBOL-85 test suite (459
``.CBL`` programs plus their ``.CPY`` copybooks). The pre-existing
``test_all_cobol_examples.py`` only checks that parsing does not crash; this
module pins the actual support level so it can never silently regress:

* Every ``.CBL`` program must parse **error-free**. The few programs the
  parser cannot yet handle are listed in ``KNOWN_ISSUES`` and marked
  ``xfail(strict=True)`` — when the parser learns to handle one, the xfail
  turns into a failure and the entry must be removed, ratcheting support
  forward.
* ``SM101A.CBL`` (the COPY-statement test program) must additionally parse
  error-free *with* copybook expansion against the suite's own copybooks.
* Every ``.CPY`` copybook must pass copybook content validation.
"""

from pathlib import Path

import pytest

from cobolparser import CobolParser
from cobolparser.plugins.core import ErrorRecoveryMode

pytestmark = [pytest.mark.integration, pytest.mark.slow]

NIST_DIR = Path(__file__).parent.parent.parent / "examples" / "cobol"

# Programs the parser cannot yet handle error-free. Marked strict-xfail so
# any improvement is flagged and this list only ever shrinks.
KNOWN_ISSUES: dict[str, str] = {
    "NC113M.CBL": (
        "division header split across source lines ('DATA' on one line, "
        "'DIVISION.' on the next) is not recognised"
    ),
    "OBNC1M.CBL": (
        "IDENTIFICATION DIVISION comment-entry containing the word 'DATA' "
        "('AUTOMATIC DATA AND TELECOMMUNICATION SERVICE') is mistaken for "
        "a DATA DIVISION header"
    ),
    "NC252A.CBL": (
        "COMPUTE with multiple receiving operands including a subscripted "
        "ROUNDED item before '=' is reported as missing the '=' operator"
    ),
    "SM101A.CBL": (
        "requires copybook expansion (COPY members live in the same "
        "directory); parses clean with expansion — see "
        "test_sm101a_parses_clean_with_copybook_expansion"
    ),
}

# Copybooks the content validator currently flags. Marked strict-xfail so a
# validator improvement is flagged and this list only ever shrinks.
KNOWN_COPYBOOK_ISSUES: dict[str, str] = {
    "K1WKA.CPY": "validator flags a lone double quote inside a literal",
    "K1WKY.CPY": "validator flags a lone double quote inside a literal",
}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def _cbl_params() -> list:
    params = []
    for path in sorted(NIST_DIR.glob("*.CBL")):
        marks = []
        if path.name in KNOWN_ISSUES:
            marks.append(pytest.mark.xfail(strict=True, reason=KNOWN_ISSUES[path.name]))
        params.append(pytest.param(path, id=path.name, marks=marks))
    return params


def _cpy_params() -> list:
    params = []
    for path in sorted(NIST_DIR.glob("*.CPY")):
        marks = []
        if path.name in KNOWN_COPYBOOK_ISSUES:
            marks.append(
                pytest.mark.xfail(strict=True, reason=KNOWN_COPYBOOK_ISSUES[path.name])
            )
        params.append(pytest.param(path, id=path.name, marks=marks))
    return params


class TestCorpusPresence:
    """The corpus itself must be intact for the support guarantee to mean
    anything."""

    def test_nist_programs_present(self) -> None:
        assert len(list(NIST_DIR.glob("*.CBL"))) >= 459

    def test_nist_copybooks_present(self) -> None:
        assert len(list(NIST_DIR.glob("*.CPY"))) >= 51

    def test_known_issues_refer_to_existing_files(self) -> None:
        for name in [*KNOWN_ISSUES, *KNOWN_COPYBOOK_ISSUES]:
            assert (NIST_DIR / name).exists(), f"stale KNOWN_ISSUES entry: {name}"


class TestNistProgramsParseErrorFree:
    """Every NIST COBOL-85 program parses to an AST with zero errors."""

    @pytest.mark.parametrize("cbl_path", _cbl_params())
    def test_parses_error_free(self, cbl_path: Path) -> None:
        parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        result = parser.parse(_read(cbl_path))
        assert result.ast is not None, f"{cbl_path.name}: AST is None"
        assert result.errors == [], f"{cbl_path.name}: parse errors:\n" + "\n".join(
            str(e) for e in result.errors
        )


class TestNistCopyStatementSupport:
    """Real-life COPY usage: the suite's COPY test program expands and
    parses clean against the suite's own copybooks."""

    def test_sm101a_parses_clean_with_copybook_expansion(self) -> None:
        from cobolparser.preprocess.copybook_expander import (
            parse_cobol_with_expansion,
        )

        source = _read(NIST_DIR / "SM101A.CBL")
        result = parse_cobol_with_expansion(
            source,
            filename="SM101A.CBL",
            copybook_paths=[str(NIST_DIR)],
            error_recovery=ErrorRecoveryMode.COLLECT_ALL,
        )
        assert result.ast is not None
        assert result.errors == [], "SM101A with expansion:\n" + "\n".join(
            str(e) for e in result.errors
        )


class TestNistCopybooksValidate:
    """Every NIST copybook passes copybook content validation."""

    @pytest.mark.parametrize("cpy_path", _cpy_params())
    def test_copybook_content_is_valid(self, cpy_path: Path) -> None:
        from cobolparser.preprocess import validate_copybook_content

        issues = validate_copybook_content(_read(cpy_path), str(cpy_path))
        assert issues == [], f"{cpy_path.name}: validation issues: {issues}"
