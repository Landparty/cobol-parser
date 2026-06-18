"""
Integration tests for the shamrice/COBOL-Examples corpus.
https://github.com/shamrice/COBOL-Examples

All IBM COBOL files must parse with no errors (strict).
GnuCOBOL-specific files are marked xfail.
"""

from pathlib import Path

import pytest

from cobolparser import CobolParser, ErrorRecoveryMode

pytestmark = pytest.mark.integration

SHAMRICE_DIR = Path(__file__).parent.parent.parent / "examples" / "cobol" / "shamrice"

def _make_param(path: Path) -> pytest.param:
    return pytest.param(path, id=path.name)


_ALL_CBL = sorted(SHAMRICE_DIR.glob("*.cbl"))

PARAMS = [_make_param(p) for p in _ALL_CBL]


class TestShamriceExamples:
    """Parse every COBOL file from shamrice/COBOL-Examples."""

    @pytest.mark.parametrize("cbl_path", PARAMS)
    def test_parses_without_errors(self, cbl_path: Path) -> None:
        parser = CobolParser(error_recovery=ErrorRecoveryMode.FAIL_FAST)
        result = parser.parse_file(str(cbl_path))
        assert result.ast is not None, (
            f"{cbl_path.name}: AST is None"
        )
        assert result.errors == [], (
            f"{cbl_path.name}: parse errors:\n"
            + "\n".join(str(e) for e in result.errors)
        )
