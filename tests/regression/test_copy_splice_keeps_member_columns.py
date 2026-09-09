"""Regression coverage for the COPY splice adopting the COPY's own indent.

``_expand_source_recursive`` replaced the COPY *statement* -- from the
``COPY`` keyword to its terminating period -- with the member's text. On the
normal ``COPY X.`` written alone on a line, the blanks to the left of that
keyword are the COPY statement's own indentation, and splicing at the keyword
prepended them to the member's first line, whose columns are already exactly
what its author wrote. Two consequences, both silent:

**1. The member's first line lost its area.** A copybook that puts its
``01`` in Area A (columns 8-11) came out with that ``01`` in Area B, by as
many columns as the ``COPY`` was indented. The expansion still parses (the
parser reads columns 8-72 and does not enforce Area A), but the listing
``cobol-parser expand`` prints -- and that the COBOL Analyzer extension shows
as "Expanded Source" and writes with "Save Expanded Source As..." -- is no
longer valid fixed-format source to hand to a compiler.

**2. A far-right COPY pushed the line past column 72.** The shifted line then
went through ``_fit_fixed_format_width``, which squeezed its interior blank
runs to make it fit -- so the emitted text differed from the member's own,
character for character -- or, once squeezing ran out, wrapped it onto an
extra physical line, shifting every following line number in the expansion
and breaking the 1:1 correspondence the source map is built on.

A member's lines are inserted as whole source records in their own columns,
so the splice now starts at the beginning of the record. When the parent
*does* have text before the COPY on that line, those characters are program
text and the splice still starts at the keyword.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cobolparser import expand_copybooks

MEMBER = "       01  CUSTOMER-MASTER-RECORD-LAYOUT-FOR-THE-BRANCH-SYSTEM.\n           05  CM-KEY  PIC X(10).\n"


def _program(copy_indent: int, member: str = "MEMBER") -> str:
    return (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. SPLICE.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        f"{' ' * copy_indent}COPY {member}.\n"
        "       PROCEDURE DIVISION.\n"
        "       MAIN-PARA.\n"
        "           GOBACK.\n"
    )


@pytest.fixture
def copybook_dir(tmp_path: Path) -> Path:
    (tmp_path / "MEMBER.cpy").write_text(MEMBER, encoding="utf-8")
    return tmp_path


class TestCopySpliceKeepsMemberColumns:
    @pytest.mark.parametrize("copy_indent", [7, 11, 20, 40])
    def test_member_lines_keep_their_own_columns(
        self, copybook_dir: Path, copy_indent: int
    ) -> None:
        """However far right the COPY sits, the member lands in its columns."""
        result = expand_copybooks(
            _program(copy_indent), copybook_paths=[str(copybook_dir)]
        )
        lines = result.expanded_source.split("\n")

        # Line 5 (1-indexed) is where the COPY was; the member's first line
        # replaces it, and its `01` belongs in Area A exactly as written.
        assert lines[4] == MEMBER.split("\n")[0]
        assert lines[5] == MEMBER.split("\n")[1]

    def test_no_width_squeeze_from_a_far_right_copy(self, copybook_dir: Path) -> None:
        """The member is emitted character for character, not re-fitted."""
        near = expand_copybooks(_program(11), copybook_paths=[str(copybook_dir)])
        far = expand_copybooks(_program(40), copybook_paths=[str(copybook_dir)])

        assert near.expanded_source == far.expanded_source
        # And every emitted line is one the member or the program really has.
        assert "01  CUSTOMER-MASTER-RECORD-LAYOUT-FOR-THE-BRANCH-SYSTEM." in (
            near.expanded_source
        )

    def test_line_count_does_not_depend_on_the_copy_indent(
        self, copybook_dir: Path
    ) -> None:
        """A shifted line that wrapped used to add a line the source map has no
        origin for; the count must come from the member's content alone."""
        counts = {
            indent: expand_copybooks(
                _program(indent), copybook_paths=[str(copybook_dir)]
            ).expanded_source.count("\n")
            for indent in (7, 11, 20, 40)
        }
        assert len(set(counts.values())) == 1, counts

    def test_source_map_still_names_the_member_line_for_line(
        self, copybook_dir: Path
    ) -> None:
        result = expand_copybooks(
            _program(40),
            copybook_paths=[str(copybook_dir)],
            preserve_source_locations=True,
        )
        member_path = str(copybook_dir / "MEMBER.cpy")

        assert result.source_location_map[5] == (member_path, 1)
        assert result.source_location_map[6] == (member_path, 2)
        # The program's own line 6 (PROCEDURE DIVISION) follows immediately.
        assert result.source_location_map[7] == ("<main>", 6)

    def test_text_before_the_copy_on_the_same_line_survives(
        self, tmp_path: Path
    ) -> None:
        """The splice only reclaims the record when the COPY owns it alone."""
        (tmp_path / "TAIL.cpy").write_text(
            "           05  T-A  PIC X.\n", encoding="utf-8"
        )
        source = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. SPLICE.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01  REC-A.   COPY TAIL.\n"
            "       PROCEDURE DIVISION.\n"
            "       MAIN-PARA.\n"
            "           GOBACK.\n"
        )
        result = expand_copybooks(source, copybook_paths=[str(tmp_path)])

        assert "01  REC-A." in result.expanded_source.split("\n")[4]
