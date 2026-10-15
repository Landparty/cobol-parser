"""The OKF bundle's claims, checked against the code.

``test_okf_staleness_map.py`` guarantees every source file has an OKF home;
it cannot tell whether what that home *says* is still true.  These tests run
``scripts/okf_check.py`` over every OKF file (and CLAUDE.md): imports in the
docs must run, backticked dotted names, symbols and repo paths must exist,
links and anchors must resolve, and every ``<!-- okf:gen NAME -->`` span must
equal what its generator computes from the code today.  When one fails after a
code change, ``python scripts/okf_check.py --write`` refreshes the generated
spans; anything else is a doc that needs a real edit.
"""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import okf_check  # noqa: E402

_FILES = okf_check.okf_files()


@pytest.mark.parametrize(
    "path", _FILES, ids=[p.relative_to(REPO_ROOT).as_posix() for p in _FILES]
)
def test_okf_file_claims_hold(path):
    problems = okf_check.check_file(path)
    assert not problems, "\n" + "\n".join(str(p) for p in problems)


def test_every_generated_span_names_a_known_generator():
    names = {
        m.group("name")
        for path in _FILES
        for m in okf_check.GEN_RE.finditer(path.read_text(encoding="utf-8"))
    }
    assert names <= set(okf_check.GENERATORS), sorted(names - set(okf_check.GENERATORS))


class TestCheckerCatchesDrift:
    """The checks themselves: each must flag the drift it exists for."""

    def test_stale_generated_span(self, tmp_path):
        doc = tmp_path / "x.md"
        doc.write_text("<!-- okf:gen tokentype-count -->1<!-- /okf:gen -->")
        problems = okf_check.check_generated(doc, doc.read_text())
        assert [p.kind for p in problems] == ["gen"]
        assert okf_check.write_generated(doc.read_text()) != doc.read_text()

    def test_bare_count(self, tmp_path):
        doc = tmp_path / "x.md"
        text = "The lexer has 999 TokenType values."
        assert [p.kind for p in okf_check.check_bare_counts(doc, text)] == ["count"]

    def test_broken_import(self, tmp_path):
        doc = tmp_path / "x.md"
        text = "```python\nfrom cobolparser import NoSuchThing\n```"
        assert [p.kind for p in okf_check.check_imports(doc, text)] == ["import"]

    def test_dotted_name(self):
        assert okf_check.resolve_dotted("cobolparser.lexer.TokenType") is None
        assert okf_check.resolve_dotted("cobolparser.lexer.NoSuchThing")

    def test_unknown_symbol_and_external_escape(self, tmp_path):
        doc = tmp_path / "x.md"
        text = "`ProgramFlowAnalyzer` and `MadeUpAnalyzer`"
        problems = okf_check.check_symbols(doc, text)
        assert ["MadeUpAnalyzer" in p.message for p in problems] == [True]
        text += "\n<!-- okf:external MadeUpAnalyzer -->"
        assert okf_check.check_symbols(doc, text) == []

    def test_missing_path(self, tmp_path):
        doc = tmp_path / "x.md"
        text = "`cobolparser/lexer.py` and `cobolparser/no_such_module.py`"
        assert len(okf_check.check_paths(doc, text)) == 1

    def test_broken_anchor(self, tmp_path):
        doc = tmp_path / "x.md"
        doc.write_text("# Title\n\n## Real section\n\n[a](#real-section) [b](#gone)\n")
        problems = okf_check.check_links(doc, doc.read_text())
        assert [p.message for p in problems] == ["#gone: no such heading"]
