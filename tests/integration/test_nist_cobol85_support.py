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
    # OBNC1M.CBL removed: the IDENTIFICATION DIVISION parser's boundary
    # checks are now comment-entry aware — normalize_fixed_format preserves
    # Area A/B as indentation, so the phony program its SECURITY
    # comment-entry embeds in Area B no longer terminates the division. See
    # tests/regression/test_comment_entry_area_b.py.
    # SM101A.CBL removed from KNOWN_ISSUES: it requires copybook expansion by
    # design (its COPY members are statement fragments that complete the
    # surrounding code), so the strict parametrized test now parses it through
    # the copybook-expansion pipeline — the way a compiler must — via
    # REQUIRES_COPYBOOK_EXPANSION below, and requires zero errors there.
    # SM206A.CBL removed: COPY ... REPLACING with pseudo-text no longer leaks.
    # The non-expansion parse now strips un-expanded COPY statements (including
    # their REPLACING pseudo-text) before lexing. See
    # tests/regression/test_replace_and_copy_pseudo_text.py.
    # SM208A.CBL removed: the REPLACE compiler-directing statement is now
    # applied as a source-text pseudo-text substitution pass before lexing.
    # See tests/regression/test_replace_and_copy_pseudo_text.py.
    # NC205A.CBL removed: its continued numeric literal `-999.777` now
    # normalizes correctly (fixed-format continuation-line join no longer
    # injects a space). See tests/regression/test_continued_literal_normalization.py.
}

# Copybooks the content validator currently flags. Marked strict-xfail so a
# validator improvement is flagged and this list only ever shrinks.
KNOWN_COPYBOOK_ISSUES: dict[str, str] = {}

# Programs that are incomplete as standalone text by design: their COPY
# members are statement *fragments* that complete the surrounding code, so no
# COBOL compiler could process them without expansion either. The strict
# parametrized test parses these through the copybook-expansion pipeline
# (against the suite's own copybooks) and still requires zero errors — a
# stronger guarantee than the strict-xfail these entries used to carry.
REQUIRES_COPYBOOK_EXPANSION: frozenset = frozenset({"SM101A.CBL"})


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
        for name in [
            *KNOWN_ISSUES,
            *KNOWN_COPYBOOK_ISSUES,
            *REQUIRES_COPYBOOK_EXPANSION,
        ]:
            assert (NIST_DIR / name).exists(), f"stale KNOWN_ISSUES entry: {name}"


class TestNistProgramsParseErrorFree:
    """Every NIST COBOL-85 program parses to an AST with zero errors."""

    @pytest.mark.parametrize("cbl_path", _cbl_params())
    def test_parses_error_free(self, cbl_path: Path) -> None:
        if cbl_path.name in REQUIRES_COPYBOOK_EXPANSION:
            from cobolparser.parser import parse_cobol_with_expansion

            result = parse_cobol_with_expansion(
                _read(cbl_path),
                filename=cbl_path.name,
                copybook_paths=[str(NIST_DIR)],
                error_recovery=ErrorRecoveryMode.COLLECT_ALL,
            )
        else:
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
        from cobolparser.parser import parse_cobol_with_expansion

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

    def test_sm207a_library_qualified_copy_expands_clean(self) -> None:
        """COPY member OF library falls back to the plain search path when
        the library has no subdirectory equivalent (SM207A uses
        ``COPY ALTLB OF X1-LIB`` with ALTLB.CPY in the suite directory)."""
        from cobolparser.parser import parse_cobol_with_expansion

        source = _read(NIST_DIR / "SM207A.CBL")
        result = parse_cobol_with_expansion(
            source,
            filename="SM207A.CBL",
            copybook_paths=[str(NIST_DIR)],
            error_recovery=ErrorRecoveryMode.COLLECT_ALL,
        )
        assert result.ast is not None
        assert result.errors == [], "SM207A with expansion:\n" + "\n".join(
            str(e) for e in result.errors
        )


class TestNistCopybooksValidate:
    """Every NIST copybook passes copybook content validation."""

    @pytest.mark.parametrize("cpy_path", _cpy_params())
    def test_copybook_content_is_valid(self, cpy_path: Path) -> None:
        from cobolparser.preprocess import validate_copybook_content

        issues = validate_copybook_content(_read(cpy_path), str(cpy_path))
        assert issues == [], f"{cpy_path.name}: validation issues: {issues}"
