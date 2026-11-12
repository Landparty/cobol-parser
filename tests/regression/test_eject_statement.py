"""Regression tests: EJECT compiler-directing statements must be ignored.

``EJECT`` is a COBOL compiler-directing statement (a page-eject hint for the
source listing, no runtime effect) with no registered ``TokenType`` or
statement parser before this fix. Two concrete failures resulted:

1. Written ``EJECT.`` (a period immediately after, the common real-world
   style -- effectively indistinguishable from a paragraph name to a
   lookahead scanner), the PROCEDURE DIVISION's paragraph/section boundary
   detector (``is_paragraph_or_section_start``, keyed off a bare
   ``TokenType.IDENTIFIER`` followed by a period) mistook it for a new
   paragraph header. This silently split the enclosing paragraph in two and
   inserted a bogus empty ``EJECT`` paragraph into the AST.
2. Written without a trailing period, ``EJECT`` fell through to the
   PROCEDURE DIVISION's "unsupported statement" recovery path and emitted a
   spurious ``"Unparsed tokens starting at 'EJECT' ... clause or statement
   not fully supported"`` warning -- misleading, since EJECT is a
   well-defined no-op, not malformed input.

Both failure modes reproduce identically whether EJECT appears in the
program's own source or arrives via COPY-expanded copybook text, since by
the time the lexer/parser see it, expansion has already flattened the
copybook into the surrounding source.

Fixed by giving EJECT its own ``TokenType`` + keyword entry (so it can never
be mistaken for an ``IDENTIFIER``-typed paragraph name) and a real
``EjectStatementParser`` -> ``EjectStatement`` no-op, mirroring
``ContinueStatementParser`` / ``ContinueStatement``.

Since 2026-11-12 a line holding only ``EJECT`` (as IBM requires) is dropped
from the token stream before parsing, so it is no statement at all: kept as
one it made a paragraph ending ``STOP RUN.`` look like it fell through, and
an empty paragraph look non-empty. The statement parser still handles an
EJECT that shares its line.
"""

import textwrap

from cobolparser import parse_cobol, parse_cobol_with_expansion

_HEADER = textwrap.dedent("""\
    IDENTIFICATION DIVISION.
    PROGRAM-ID. EJECTTEST.
    PROCEDURE DIVISION.
    """)


def _paragraphs(result):
    d = result.ast.to_dict()
    return d["divisions"]["PROCEDURE"]["paragraphs"]


class TestEjectWithTrailingPeriod:
    """The primary bug: ``EJECT.`` between two paragraphs must not split them."""

    def test_does_not_create_a_bogus_paragraph(self):
        source = _HEADER + textwrap.dedent("""\
            MAIN-PARA.
                DISPLAY "BEFORE EJECT".
                EJECT.
            SECOND-PARA.
                DISPLAY "AFTER EJECT".
                STOP RUN.
            """)
        result = parse_cobol(source, filename="eject_period.cbl")

        assert result.success, f"errors={result.errors}"
        assert result.warnings == []

        paras = _paragraphs(result)
        names = [p["paragraph_name"] for p in paras]
        assert names == ["MAIN-PARA", "SECOND-PARA"], names

        main_para = paras[0]
        assert [s["statement_type"] for s in main_para["statements"]] == [
            "DISPLAY",
        ]

        second_para = paras[1]
        assert [s["statement_type"] for s in second_para["statements"]] == [
            "DISPLAY",
            "STOP",
        ]

    def test_eject_as_only_statement_in_a_paragraph(self):
        source = _HEADER + textwrap.dedent("""\
            FIRST-PARA.
                DISPLAY "ONE".
            EJECT-PARA.
                EJECT.
            LAST-PARA.
                DISPLAY "TWO".
                STOP RUN.
            """)
        result = parse_cobol(source, filename="eject_only.cbl")

        assert result.success, f"errors={result.errors}"
        assert result.warnings == []

        paras = _paragraphs(result)
        names = [p["paragraph_name"] for p in paras]
        # EJECT-PARA is a real, user-named paragraph here (unambiguous,
        # since it is followed by a period like any paragraph name) and
        # must survive distinctly from a bare EJECT statement.
        assert names == ["FIRST-PARA", "EJECT-PARA", "LAST-PARA"], names
        assert [s["statement_type"] for s in paras[1]["statements"]] == []


class TestEjectWithoutTrailingPeriod:
    """EJECT with no period must not swallow the following statement or warn."""

    def test_marker_statement_survives(self):
        source = _HEADER + textwrap.dedent("""\
            MAIN-PARA.
                DISPLAY "BEFORE EJECT".
                EJECT
                DISPLAY "AFTER EJECT".
                STOP RUN.
            """)
        result = parse_cobol(source, filename="eject_no_period.cbl")

        assert result.success, f"errors={result.errors}"
        assert result.warnings == []

        [main_para] = _paragraphs(result)
        assert [s["statement_type"] for s in main_para["statements"]] == [
            "DISPLAY",
            "DISPLAY",
            "STOP",
        ]

    def test_consecutive_ejects(self):
        source = _HEADER + textwrap.dedent("""\
            MAIN-PARA.
                DISPLAY "X".
                EJECT
                EJECT.
                DISPLAY "Y".
                STOP RUN.
            """)
        result = parse_cobol(source, filename="eject_consecutive.cbl")

        assert result.success, f"errors={result.errors}"
        assert result.warnings == []

        [main_para] = _paragraphs(result)
        assert [s["statement_type"] for s in main_para["statements"]] == [
            "DISPLAY",
            "DISPLAY",
            "STOP",
        ]


class TestEjectAstShape:
    """An EJECT that shares its line (non-conforming: IBM wants it alone on
    the line) still parses as a no-op EjectStatement node."""

    def test_eject_statement_to_dict_shape(self):
        source = _HEADER + textwrap.dedent("""\
            MAIN-PARA.
                CONTINUE EJECT.
                STOP RUN.
            """)
        result = parse_cobol(source, filename="eject_shape.cbl")

        assert result.success
        [main_para] = _paragraphs(result)
        eject_stmt = main_para["statements"][1]
        assert eject_stmt["statement_type"] == "EJECT"
        assert eject_stmt["node_type"] == "Statement"


class TestEjectInCopybook:
    """EJECT arriving via COPY expansion must behave identically to inline EJECT.

    ``expand_copybooks``' COPY-statement scanner expects real fixed-format
    column positioning (Area A starting at column 8) in the *main* source --
    unlike ``parse_cobol``, it does not lexer-normalize a zero-margin,
    free-form-shaped string first. So this test (unlike the others in this
    module) writes literal fixed-format-columned source, matching every
    other ``parse_cobol_with_expansion`` call site in this test suite.
    """

    def test_eject_in_expanded_copybook_does_not_split_paragraph(self, tmp_path):
        # Real fixed-format columns matter here: expand_copybooks strips a
        # copybook's own columns 1-6 (sequence area) before scanning its
        # content, so this literal must not be textwrap.dedent()-flattened
        # (that would shift real code left into the sequence-area window
        # and corrupt it).
        (tmp_path / "COMMONPA.CPY").write_text(
            "      * COMMON PARAGRAPHS COPYBOOK\n"
            "       COMMON-PARA-ONE.\n"
            '           DISPLAY "IN COMMON ONE".\n'
            "           EJECT.\n"
            "       COMMON-PARA-TWO.\n"
            '           DISPLAY "IN COMMON TWO".\n',
            encoding="utf-8",
        )

        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. EJECTTEST.
       PROCEDURE DIVISION.
       MAIN-PARA.
           DISPLAY "MAIN".
           PERFORM COMMON-PARA-ONE.
           STOP RUN.
       COPY COMMONPA.
"""

        result = parse_cobol_with_expansion(
            source, "copy_eject.cbl", copybook_paths=[str(tmp_path)]
        )

        assert result.success, f"errors={result.errors}"
        assert result.warnings == []

        paras = _paragraphs(result)
        names = [p["paragraph_name"] for p in paras]
        assert names == ["MAIN-PARA", "COMMON-PARA-ONE", "COMMON-PARA-TWO"], names

        common_one = paras[1]
        assert [s["statement_type"] for s in common_one["statements"]] == [
            "DISPLAY",
        ]
