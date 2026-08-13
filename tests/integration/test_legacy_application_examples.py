"""
Integration tests for the legacy-application banking-batch corpus.
https://github.com/Landparty/legacy-application

Real-world specimens vendored to close documented parser coverage gaps:
EXEC CICS (ACCTINQ.cbl), dynamic CALL (JOBDISP.cbl), and SORT / OCCURS /
SEARCH ALL (FEECALC.cbl). Every program must parse with no errors, both
as raw source (COPY statements left un-expanded) and with the
corpus's own copybooks expanded.
"""

from pathlib import Path

import pytest

from cobolparser import CobolParser, ErrorRecoveryMode, parse_cobol_with_expansion

pytestmark = pytest.mark.integration

LEGACY_APP_DIR = (
    Path(__file__).parent.parent.parent / "examples" / "cobol" / "legacy-application"
)
COBOL_DIR = LEGACY_APP_DIR / "cobol"
COPYBOOK_DIR = LEGACY_APP_DIR / "copybook"


def _make_param(path: Path) -> pytest.param:
    return pytest.param(path, id=path.name)


_ALL_CBL = sorted(COBOL_DIR.glob("*.cbl"))

PARAMS = [_make_param(p) for p in _ALL_CBL]


class TestLegacyApplicationExamples:
    """Parse every COBOL file from the legacy-application corpus."""

    @pytest.mark.parametrize("cbl_path", PARAMS)
    def test_parses_without_errors(self, cbl_path: Path) -> None:
        parser = CobolParser(error_recovery=ErrorRecoveryMode.FAIL_FAST)
        result = parser.parse_file(str(cbl_path))
        assert result.ast is not None, f"{cbl_path.name}: AST is None"
        assert result.errors == [], f"{cbl_path.name}: parse errors:\n" + "\n".join(
            str(e) for e in result.errors
        )

    @pytest.mark.parametrize("cbl_path", PARAMS)
    def test_parses_with_copybook_expansion(self, cbl_path: Path) -> None:
        source = cbl_path.read_text()
        result = parse_cobol_with_expansion(
            source, str(cbl_path), copybook_paths=[str(COPYBOOK_DIR)]
        )
        assert result.ast is not None, f"{cbl_path.name}: AST is None (expanded)"
        assert (
            result.errors == []
        ), f"{cbl_path.name}: parse errors (expanded):\n" + "\n".join(
            str(e) for e in result.errors
        )
