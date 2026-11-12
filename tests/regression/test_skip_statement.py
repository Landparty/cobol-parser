"""Regression tests: SKIP1/SKIP2/SKIP3 compiler-directing statements must be
ignored, the same class of listing no-op as EJECT (see
``test_eject_statement.py``).

``SKIP1``/``SKIP2``/``SKIP3`` are compiler-directing statements (blank-line
hints for the source listing, no runtime effect). They already have their
own ``TokenType`` and a dedicated ``SkipStatementParser`` -> ``SkipStatement``
no-op node (mirroring ``EjectStatementParser`` / ``EjectStatement``), so this
file exercises the same failure modes EJECT was fixed for, to guard against
regressions: written with a trailing period (the common real-world style,
otherwise indistinguishable from a paragraph name to a lookahead scanner),
without one, back-to-back, and via COPY-expanded copybook text.
"""

import textwrap

from cobolparser import parse_cobol, parse_cobol_with_expansion

_HEADER = textwrap.dedent("""\
    IDENTIFICATION DIVISION.
    PROGRAM-ID. SKIPTEST.
    PROCEDURE DIVISION.
    """)


def _paragraphs(result):
    d = result.ast.to_dict()
    return d["divisions"]["PROCEDURE"]["paragraphs"]


class TestSkipWithTrailingPeriod:
    """The primary risk: ``SKIP1.`` between two paragraphs must not split them."""

    def test_does_not_create_a_bogus_paragraph(self):
        source = _HEADER + textwrap.dedent("""\
            MAIN-PARA.
                DISPLAY "BEFORE SKIP".
                SKIP1.
            SECOND-PARA.
                DISPLAY "AFTER SKIP".
                STOP RUN.
            """)
        result = parse_cobol(source, filename="skip_period.cbl")

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

    def test_skip_as_only_statement_in_a_paragraph(self):
        source = _HEADER + textwrap.dedent("""\
            FIRST-PARA.
                DISPLAY "ONE".
            SKIP-PARA.
                SKIP2.
            LAST-PARA.
                DISPLAY "TWO".
                STOP RUN.
            """)
        result = parse_cobol(source, filename="skip_only.cbl")

        assert result.success, f"errors={result.errors}"
        assert result.warnings == []

        paras = _paragraphs(result)
        names = [p["paragraph_name"] for p in paras]
        # SKIP-PARA is a real, user-named paragraph here (unambiguous, since
        # it is followed by a period like any paragraph name) and must
        # survive distinctly from a bare SKIP2 statement.
        assert names == ["FIRST-PARA", "SKIP-PARA", "LAST-PARA"], names
        assert [s["statement_type"] for s in paras[1]["statements"]] == []


class TestSkipWithoutTrailingPeriod:
    """SKIP with no period must not swallow the following statement or warn."""

    def test_marker_statement_survives(self):
        source = _HEADER + textwrap.dedent("""\
            MAIN-PARA.
                DISPLAY "BEFORE SKIP".
                SKIP3
                DISPLAY "AFTER SKIP".
                STOP RUN.
            """)
        result = parse_cobol(source, filename="skip_no_period.cbl")

        assert result.success, f"errors={result.errors}"
        assert result.warnings == []

        [main_para] = _paragraphs(result)
        assert [s["statement_type"] for s in main_para["statements"]] == [
            "DISPLAY",
            "DISPLAY",
            "STOP",
        ]

    def test_consecutive_skips_of_each_kind(self):
        source = _HEADER + textwrap.dedent("""\
            MAIN-PARA.
                DISPLAY "X".
                SKIP1
                SKIP2
                SKIP3.
                DISPLAY "Y".
                STOP RUN.
            """)
        result = parse_cobol(source, filename="skip_consecutive.cbl")

        assert result.success, f"errors={result.errors}"
        assert result.warnings == []

        [main_para] = _paragraphs(result)
        assert [s["statement_type"] for s in main_para["statements"]] == [
            "DISPLAY",
            "DISPLAY",
            "STOP",
        ]


class TestSkipAstShape:
    """SkipStatement is a proper no-op node, not a dropped/opaque token, and
    each variant records its own line count."""

    def test_skip_statement_to_dict_shape(self):
        source = _HEADER + textwrap.dedent("""\
            MAIN-PARA.
                CONTINUE SKIP1.
                STOP RUN.
            """)
        result = parse_cobol(source, filename="skip_shape.cbl")

        assert result.success
        [main_para] = _paragraphs(result)
        skip_stmt = main_para["statements"][1]
        assert skip_stmt["statement_type"] == "SKIP"
        assert skip_stmt["node_type"] == "Statement"

    def test_each_variant_records_its_own_line_count(self):
        source = _HEADER + textwrap.dedent("""\
            MAIN-PARA.
                CONTINUE SKIP1
                CONTINUE SKIP2
                CONTINUE SKIP3
                STOP RUN.
            """)
        result = parse_cobol(source, filename="skip_lines.cbl")

        assert result.success, f"errors={result.errors}"
        skip_stmts = result.ast.find_all_by_type("SkipStatement")
        assert [s.lines for s in skip_stmts] == [1, 2, 3]


class TestSkipInCopybook:
    """SKIP arriving via COPY expansion must behave identically to inline SKIP."""

    def test_skip_in_expanded_copybook_does_not_split_paragraph(self, tmp_path):
        # Real fixed-format columns matter here: expand_copybooks strips a
        # copybook's own columns 1-6 (sequence area) before scanning its
        # content, so this literal must not be textwrap.dedent()-flattened
        # (that would shift real code left into the sequence-area window
        # and corrupt it).
        (tmp_path / "COMMONPA.CPY").write_text(
            "      * COMMON PARAGRAPHS COPYBOOK\n"
            "       COMMON-PARA-ONE.\n"
            '           DISPLAY "IN COMMON ONE".\n'
            "           SKIP1.\n"
            "       COMMON-PARA-TWO.\n"
            '           DISPLAY "IN COMMON TWO".\n',
            encoding="utf-8",
        )

        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SKIPTEST.
       PROCEDURE DIVISION.
       MAIN-PARA.
           DISPLAY "MAIN".
           PERFORM COMMON-PARA-ONE.
           STOP RUN.
       COPY COMMONPA.
"""

        result = parse_cobol_with_expansion(
            source, "copy_skip.cbl", copybook_paths=[str(tmp_path)]
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
