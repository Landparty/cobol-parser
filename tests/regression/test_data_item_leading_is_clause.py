"""Regression tests: leading "IS" before EXTERNAL / GLOBAL / a bare
USAGE-family keyword (POINTER, PROCEDURE-POINTER, FUNCTION-POINTER) in a
data-description entry (`data_clauses.py`).

EXTERNAL and GLOBAL are standard "[IS] EXTERNAL" / "[IS] GLOBAL" clauses --
the leading IS is optional, legal COBOL. The USAGE-omitted POINTER forms
("IS POINTER." with no "USAGE" keyword) are a common real-world IBM
Enterprise COBOL convention. Before this fix, `DataItemClauseParser`'s
per-item clause dispatch loop only recognized the bare keyword (EXTERNAL /
GLOBAL / POINTER / PROCEDURE-POINTER / FUNCTION-POINTER) and had no branch
for a leading "IS" token, so it fell into the generic "unknown clause"
fallback: the IS token was silently dropped with a
"clause not fully supported; content dropped from the AST" warning, even
though the very next token (the real keyword) was then parsed correctly and
nothing was actually lost from the AST. That misleading warning was enough
to make at least one downstream consumer (a splicing tool that treats any
such warning as "the AST may not reflect real program behavior") refuse to
proceed on otherwise cleanly-parsed source.

Fixed by adding a dedicated "IS" branch to the clause dispatch loop: when
the token following "IS" is EXTERNAL, GLOBAL, or one of the POINTER-family
keywords, the "IS" is consumed silently (the keyword itself is handled by
its own branch on the very next loop iteration); any other use of "IS" (not
recognized as this pattern) keeps the original warn-and-drop behavior.
"""

from cobolparser import parse_cobol

HEADER = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. LEADISREG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
"""

FOOTER = """\
       PROCEDURE DIVISION.
       MAIN-PARA.
           STOP RUN.
"""


def _parse(ws_source: str):
    result = parse_cobol(HEADER + ws_source + FOOTER, filename="leadisreg.cbl")
    assert result.success, result.errors
    return result


def _find_item(result, name: str):
    for item in result.ast.find_all_by_type("DataItem"):
        if getattr(item, "name", None) and item.name.upper() == name.upper():
            return item
    return None


class TestLeadingIsBeforeBarePointerUsage:
    """ "IS POINTER." / "IS PROCEDURE-POINTER." / "IS FUNCTION-POINTER."
    with no USAGE keyword must not warn and must still set the usage."""

    def test_is_pointer_no_usage_keyword(self):
        result = _parse("       01  WS-PTR  IS POINTER.\n")
        assert result.warnings == []
        item = _find_item(result, "WS-PTR")
        assert item is not None
        assert item.usage == "POINTER"

    def test_is_procedure_pointer_no_usage_keyword(self):
        result = _parse("       01  WS-PPTR  IS PROCEDURE-POINTER.\n")
        assert result.warnings == []
        item = _find_item(result, "WS-PPTR")
        assert item is not None
        assert item.usage == "PROCEDURE-POINTER"

    def test_is_function_pointer_no_usage_keyword(self):
        result = _parse("       01  WS-FPTR  IS FUNCTION-POINTER.\n")
        assert result.warnings == []
        item = _find_item(result, "WS-FPTR")
        assert item is not None
        assert item.usage == "FUNCTION-POINTER"

    def test_usage_is_pointer_still_unaffected(self):
        """The already-working "USAGE IS POINTER" form must keep working."""
        result = _parse("       01  WS-PTR  USAGE IS POINTER.\n")
        assert result.warnings == []
        item = _find_item(result, "WS-PTR")
        assert item is not None
        assert item.usage == "POINTER"


class TestLeadingIsBeforeExternalGlobal:
    """ "[IS] EXTERNAL" / "[IS] GLOBAL" clauses, standard COBOL grammar."""

    def test_is_global_before_pointer(self):
        result = _parse("       01  WS-GPTR  IS GLOBAL POINTER.\n")
        assert result.warnings == []
        item = _find_item(result, "WS-GPTR")
        assert item is not None
        assert item.is_global is True
        assert item.usage == "POINTER"

    def test_is_external_before_pointer(self):
        result = _parse("       01  WS-EPTR  IS EXTERNAL POINTER.\n")
        assert result.warnings == []
        item = _find_item(result, "WS-EPTR")
        assert item is not None
        assert item.is_external is True
        assert item.usage == "POINTER"

    def test_bare_global_still_unaffected(self):
        """The already-working bare "GLOBAL" form (no leading IS) keeps working."""
        result = _parse("       01  WS-GRP  PIC X(5) GLOBAL.\n")
        assert result.warnings == []
        item = _find_item(result, "WS-GRP")
        assert item is not None
        assert item.is_global is True

    def test_bare_external_still_unaffected(self):
        result = _parse("       01  WS-GRP  PIC X(5) EXTERNAL.\n")
        assert result.warnings == []
        item = _find_item(result, "WS-GRP")
        assert item is not None
        assert item.is_external is True


class TestLeadingIsUnrecognizedStillWarns:
    """An "IS" that does not precede EXTERNAL/GLOBAL/a POINTER-family keyword
    is not this pattern -- it should still be reported as an unsupported
    clause rather than silently swallowed, preserving prior behavior for
    genuinely unknown constructs."""

    def test_stray_is_before_unknown_keyword_still_warns(self):
        result = _parse("       01  WS-ODD  PIC X(5) IS BOGUS-CLAUSE.\n")
        assert any("IS" in w and "WS-ODD" in w for w in result.warnings)
