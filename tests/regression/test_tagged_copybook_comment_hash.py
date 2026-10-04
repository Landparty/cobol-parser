"""Regression tests: a ``#`` in a comment line of a change-tagged copybook.

A copybook whose sequence area (columns 1-6) holds change-tracking tags
(``BNC#01``, ``CHG001``) instead of blanks or digits was classified free-form:
the tagged-sequence-area rule of ``_detect_fixed_format`` needs a division
header to corroborate it, and a copybook has none. The member was then spliced
into the program without its column-7 comment lines being blanked, and the
first ``#`` in a comment banner reached the lexer:

    Lexer error: Invalid character: #

It surfaced on a nested copybook (COPY FDSIGFOR -> COPY BNC1AP01), but any
tagged copybook was affected. A comment indicator or a data-description entry
right after a tag now corroborates the tagged sequence area instead.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cobolparser import parse_cobol
from cobolparser.parser import _detect_fixed_format
from cobolparser.preprocess import expand_copybooks

_PROGRAM = "\n".join(
    [
        "000100 IDENTIFICATION DIVISION.",
        "000200 PROGRAM-ID. TESTP.",
        "000300*# PROGRAM BANNER ## WITH HASHES #",
        "000400 DATA DIVISION.",
        "000500 WORKING-STORAGE SECTION.",
        "000600     COPY FDSIGFOR.",
        "000700 PROCEDURE DIVISION.",
        "000800     STOP RUN.",
    ]
)

_FDSIGFOR = "\n".join(
    [
        "000100*#### FDSIGFOR ####",
        "000200 01  WS-REC.",
        "000300     05  WS-X  PIC X.",
        "000400     COPY BNC1AP01.",
    ]
)

_BNC1AP01 = "\n".join(
    [
        "BNC#01*################################################",
        "BNC#01* BNC1AP01 - NO # 123",
        "BNC#01     05  WS-A  PIC X(10).",
        "BNC#02*#",
        "BNC#02     05  WS-B  PIC 9(3).",
    ]
)


def _parse(tmp_path: Path, bnc1ap01: str = _BNC1AP01):
    (tmp_path / "FDSIGFOR.cpy").write_text(_FDSIGFOR + "\n")
    (tmp_path / "BNC1AP01.cpy").write_text(bnc1ap01 + "\n")
    expansion = expand_copybooks(_PROGRAM + "\n", copybook_paths=[str(tmp_path)])
    return expansion, parse_cobol(expansion.expanded_source, filename="TESTP.cbl")


def _data_names(result) -> list[str]:
    return [item.name for item in result.ast.find_all_by_type("CobolDataItem")]


class TestNestedTaggedCopybook:
    def test_hash_in_comment_of_nested_tagged_copybook_parses(self, tmp_path):
        _, result = _parse(tmp_path)
        assert result.success, [str(e) for e in result.errors]
        assert result.warnings == []
        assert _data_names(result) == ["WS-REC", "WS-X", "WS-A", "WS-B"]

    def test_comment_text_and_tags_are_not_spliced_in(self, tmp_path):
        expansion, _ = _parse(tmp_path)
        assert "#" not in expansion.expanded_source
        assert "BNC#0" not in expansion.expanded_source

    @pytest.mark.parametrize(
        "member",
        [
            # Two lines: judged by the short-member path, not the 60% rule.
            "CHG001*### SHORT ###\nCHG001     05  WS-A  PIC X(10).",
            # One data line, no comment at all.
            "CHG001     05  WS-A  PIC X(10).",
            # A sequence area that opens with a national character.
            "#00100*### HASH TAG ###\n#00200     05  WS-A  PIC X(10).",
        ],
    )
    def test_short_tagged_members(self, tmp_path, member):
        _, result = _parse(tmp_path, member)
        assert result.success, [str(e) for e in result.errors]
        assert "WS-A" in _data_names(result)

    def test_tagged_data_entries_without_comments(self, tmp_path):
        member = "\n".join(
            [
                "CHG001     05  WS-A  PIC X(10).",
                "CHG001     05  WS-B  PIC X(10).",
                "CHG001     05  WS-C.",
                "CHG001         10  WS-D PIC 9.",
            ]
        )
        _, result = _parse(tmp_path, member)
        assert result.success, [str(e) for e in result.errors]
        assert _data_names(result) == ["WS-REC", "WS-X", "WS-A", "WS-B", "WS-C", "WS-D"]


class TestDirectSource:
    @pytest.mark.parametrize(
        "comment",
        [
            "000300*#",
            "000300*# HASH AT COLUMN 8",
            "000300*   ## HASH ### LATER ####",
            "000300/# PAGE EJECT COMMENT",
            "CHG001*# TAGGED COMMENT",
        ],
    )
    def test_hash_in_fixed_format_comment_is_ignored(self, comment):
        source = "\n".join(
            [
                "000100 IDENTIFICATION DIVISION.",
                "000200 PROGRAM-ID. TESTP.",
                comment,
                "000400 DATA DIVISION.",
                "000500 WORKING-STORAGE SECTION.",
                "000600 01  WS-A  PIC X.",
                "000700 PROCEDURE DIVISION.",
                "000800     STOP RUN.",
            ]
        )
        result = parse_cobol(source, filename="TESTP.cbl")
        assert result.success, [str(e) for e in result.errors]

    def test_hash_in_floating_comment_is_ignored(self):
        source = "\n".join(
            [
                "       IDENTIFICATION DIVISION.",
                "       PROGRAM-ID. TESTP.",
                "       DATA DIVISION.",
                "       WORKING-STORAGE SECTION.",
                "       01  WS-A  PIC X. *> # INLINE",
                "       PROCEDURE DIVISION.",
                "           STOP RUN.",
            ]
        )
        result = parse_cobol(source, filename="TESTP.cbl")
        assert result.success, [str(e) for e in result.errors]


class TestDetection:
    def test_tagged_copybook_detected_as_fixed(self):
        assert _detect_fixed_format(_BNC1AP01) is True

    def test_free_form_verb_and_number_not_an_anchor(self):
        """``DIVIDE 10 INTO X.`` must not pass for a level-10 data entry."""
        source = "\n".join(
            [
                "DIVIDE 10 INTO WS-A.",
                "ACCEPT WS-A",
                "SEARCH WS-T",
                "CANCEL WS-P",
                "RETURN WS-R",
            ]
        )
        assert _detect_fixed_format(source) is False
