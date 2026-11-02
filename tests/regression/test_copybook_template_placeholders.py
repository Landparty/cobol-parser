"""Names holding a COPY REPLACING placeholder lex as one IDENTIFIER.

Template copybooks spell each name with a placeholder the including program
swaps out (``COPY DTFTX06S REPLACING ==(9999-)== BY ==WS-==``):
``01 (9999-)MOD-DTTX0F.``, ``05 :PFX:-CODE PIC X.``. Parsed on its own, such
a copybook lexed ``(`` ``9999`` ``-`` ``)`` ``MOD-DTTX0F``, and every item
came out ANONYMOUS with "Unparsed token" warnings.
``CobolLexer._merge_template_placeholders`` glues the run of abutting tokens
back into the name as written. Expansion with REPLACING already resolved
these names; that is pinned here too.
"""

import pytest

from cobolparser import ErrorRecoveryMode, parse_cobol, parse_cobol_with_expansion
from cobolparser.lexer import CobolLexer, _CobolLexerPure

TEMPLATE = (
    "       01  (9999-)MOD-DTTX0F.\n"
    "           05  (9999-)LONGUEUR-MOD     PIC S9(004) COMP.\n"
    "           05  (9999-)TAB-MOD OCCURS 3.\n"
    "               10  (9999-)ITEM-MOD     PIC X(02).\n"
    "       01  :PFX:-REC.\n"
    "           05  :PFX:-CODE  PIC X(08).\n"
    "           05  :PFX:       PIC X.\n"
    "           05  WS-(SFX)    PIC X.\n"
)


def _wrap(body: str, procedure: str = "") -> str:
    return (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. TPL.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        + body
        + "       PROCEDURE DIVISION.\n"
        + procedure
        + "           GOBACK.\n"
    )


def _names(result) -> list[str]:
    return [d.to_dict().get("name") for d in result.ast.find_all_by_type("DataItem")]


def test_standalone_template_keeps_its_names():
    result = parse_cobol(
        _wrap(
            TEMPLATE,
            "           MOVE SPACES TO :PFX:-CODE (9999-)ITEM-MOD (1).\n",
        ),
        error_recovery=ErrorRecoveryMode.COLLECT_ALL,
    )
    assert result.success, result.errors
    assert not result.warnings, result.warnings
    assert _names(result) == [
        "(9999-)MOD-DTTX0F",
        "(9999-)LONGUEUR-MOD",
        "(9999-)TAB-MOD",
        "(9999-)ITEM-MOD",
        ":PFX:-REC",
        ":PFX:-CODE",
        ":PFX:",
        "WS-(SFX)",
    ]
    move = result.ast.find_all_by_type("MoveStatement")[0].to_dict()
    assert ":PFX:-CODE" in move["targets"]


@pytest.mark.parametrize(
    "line, expected",
    [
        ("       05 A PIC -(5)9.99.\n", ["-", "(", "5", ")"]),
        ("       05 A PIC X(08).\n", ["X", "(", "08", ")"]),
        ("           MOVE TAB(I) TO B(1:2).\n", ["TAB", "(", "I", ")"]),
        ("           MOVE T(I)(1:2) TO X.\n", ["T", "(", "I", ")", "("]),
        ("           COMPUTE X = A-(4).\n", ["(", "4", ")"]),
    ],
)
def test_pictures_subscripts_and_reference_modification_are_untouched(line, expected):
    values = [t.value for t in CobolLexer(line).tokenize()]
    joined = " ".join(values)
    assert " ".join(expected) in joined


def test_both_lexers_agree():
    text = _wrap(TEMPLATE)
    fast = [(t.type, t.value) for t in CobolLexer(text).tokenize()]
    pure = [(t.type, t.value) for t in _CobolLexerPure(text).tokenize()]
    assert fast == pure


def test_copy_replacing_resolves_the_placeholders(tmp_path):
    (tmp_path / "DTFTX06S.cpy").write_text(TEMPLATE)
    source = _wrap(
        "       COPY DTFTX06S REPLACING ==(9999-)== BY ==WS-==\n"
        "                               ==:PFX:== BY ==ZZ==\n"
        "                               ==(SFX)== BY ==END==.\n",
        "           MOVE 'A' TO WS-ITEM-MOD (1) ZZ-CODE.\n",
    )
    result = parse_cobol_with_expansion(
        source, "prog.cbl", copybook_paths=[str(tmp_path)]
    )
    assert result.success, result.errors
    assert _names(result) == [
        "WS-MOD-DTTX0F",
        "WS-LONGUEUR-MOD",
        "WS-TAB-MOD",
        "WS-ITEM-MOD",
        "ZZ-REC",
        "ZZ-CODE",
        "ZZ",
        "WS-END",
    ]


def test_copybook_impact_notes_paren_placeholders(tmp_path):
    from cobolparser.analysis.codebase import _member_fields

    member = tmp_path / "DTFTX06S.cpy"
    member.write_text(TEMPLATE)
    fields, problem = _member_fields(str(member))
    assert fields == []
    assert problem is not None
    assert "(9999-)MOD-DTTX0F" in problem and ":PFX:-CODE" in problem
