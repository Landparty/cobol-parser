"""A character COBOL has no use for never fails the whole file.

An upload of a real shop's sources had 197 programs fail with
``Lexer error: Invalid character: |`` (a box-drawing comment whose ``*`` was
not in column 7) and ``Invalid character: #`` (a data name holding '#').
Every unknown character used to be a hard LexerError, so one '|' cost the
whole program. ``CobolLexer._drop_stray_chars`` now drops such a character
outside ``EXEC ... END-EXEC``, glues a '#' / '@' that abuts a word into
that name, and reports each character once as a warning with its count and
lines. Both lexer backends share the post-pass.
"""

import pytest

from cobolparser import ErrorRecoveryMode, parse_cobol
from cobolparser.lexer import CobolLexer, TokenType, _CobolLexerPure

HEAD = (
    "       IDENTIFICATION DIVISION.\n"
    "       PROGRAM-ID. STRAY.\n"
    "       DATA DIVISION.\n"
    "       WORKING-STORAGE SECTION.\n"
    "       01  WS-A PIC X(10).\n"
)
TAIL = (
    "       PROCEDURE DIVISION.\n"
    "           MOVE 'X' TO WS-A.\n"
    "           DISPLAY WS-A.\n"
    "           GOBACK.\n"
)


def _parse(middle: str = "", procedure: str = ""):
    source = (
        HEAD
        + middle
        + TAIL.replace("           GOBACK.\n", procedure + "           GOBACK.\n")
    )
    return parse_cobol(
        source, filename="stray.cbl", error_recovery=ErrorRecoveryMode.COLLECT_ALL
    )


def _assert_clean(result) -> None:
    assert result.ast is not None
    assert not result.errors, result.errors
    assert result.success


# Shapes that put a '|' outside a column-7 comment: a comment box shifted by
# a tab or a missing sequence area, a box in Area A, a '|' in program text.
@pytest.mark.parametrize(
    "middle",
    [
        "\t*| BOX                         |\n",
        "*| BOX                                                          |\n",
        "       *| COMMENT IN AREA A |\n",
        "  \t  *+----------------------+\n  \t  *| BOX |\n  \t  *+----------------------+\n",
        "       01  WS-B PIC X(5).   | NOTE |\n",
    ],
    ids=["tab-shifted", "column-1-star", "area-a-star", "box", "trailing-note"],
)
def test_box_drawing_pipes_parse_with_a_warning(middle):
    result = _parse(middle)
    _assert_clean(result)
    assert any("Ignored invalid character '|'" in w for w in result.warnings)


def test_one_warning_per_character_names_count_and_lines():
    box = "".join(f"\t*| LINE {n:02d}                |\n" for n in range(12))
    result = _parse(box)
    _assert_clean(result)
    pipe = [w for w in result.warnings if "'|'" in w]
    assert len(pipe) == 1
    assert "24 occurrences" in pipe[0]
    assert "lines 6, 7, 8" in pipe[0]
    assert "and 2 more" in pipe[0]


@pytest.mark.parametrize(
    "char", ["¦", "§", "°", "€", "│", "?", "{", "}", "[", "]", "\\", "~", "^", "%"]
)
def test_other_unknown_characters_are_dropped_with_a_warning(char):
    result = _parse(procedure=f"           DISPLAY 'A' {char} 'B'.\n")
    _assert_clean(result)
    assert any(f"Ignored invalid character {char!r}" in w for w in result.warnings)


@pytest.mark.parametrize("char", ["#", "@"])
def test_hash_and_at_in_a_data_name_are_part_of_the_name(char):
    result = _parse(
        f"       01  WS-{char}CPT PIC 9(4).\n",
        f"           MOVE 1 TO WS-{char}CPT.\n",
    )
    _assert_clean(result)
    names = [
        item.to_dict().get("name") for item in result.ast.find_all_by_type("DataItem")
    ]
    assert f"WS-{char}CPT" in names
    assert any(f"Non-standard character {char!r}" in w for w in result.warnings)


def test_a_free_standing_hash_is_dropped():
    result = _parse(procedure="           DISPLAY 'A' # 'B'.\n")
    _assert_clean(result)
    assert any("Ignored invalid character '#'" in w for w in result.warnings)


def test_characters_inside_exec_sql_are_kept_and_not_reported():
    result = _parse(
        procedure=(
            "           EXEC SQL\n"
            "               SELECT A || B INTO :WS-A FROM T#1 WHERE C ? 1\n"
            "           END-EXEC\n"
        )
    )
    assert result.ast is not None
    assert not any("invalid character" in w.lower() for w in result.warnings)


def test_a_clean_program_has_no_stray_warning():
    result = _parse()
    _assert_clean(result)
    assert not result.warnings


@pytest.mark.parametrize("char", ["|", "#", "¦", "?"])
def test_both_lexers_agree(char):
    text = HEAD + f"       01  WS-{char}B PIC X.  {char}\n" + TAIL
    fast = CobolLexer(text)
    pure = _CobolLexerPure(text)
    fast_tokens = [(t.type, t.value) for t in fast.tokenize()]
    pure_tokens = [(t.type, t.value) for t in pure.tokenize()]
    assert fast_tokens == pure_tokens
    assert fast.warnings == pure.warnings
    assert not fast.errors and not pure.errors
    assert all(t != TokenType.STRAY_CHAR for t, _ in fast_tokens)
