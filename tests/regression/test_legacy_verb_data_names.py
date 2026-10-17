"""Issue #525: a data item named CHAIN, NOTE, EXHIBIT, EXAMINE or TRANSFORM
became an anonymous FILLER, and every MOVE to it failed to parse.

None of these legacy verbs (Micro Focus CHAIN, COBOL-74 NOTE, OS/VS
EXHIBIT / EXAMINE / TRANSFORM) is reserved under IBM Enterprise COBOL, but
the lexer always tokenized them as verbs. Option 1 of the issue, as TITLE
and VALIDATE already behave: a word the program declares as a data name is
an identifier everywhere; undeclared, it is still the verb.
"""

from __future__ import annotations

import pytest

from cobolparser import parse_cobol
from cobolparser.generators import CopybookDataGenerator, DataGeneratorOptions
from cobolparser.generators.data.layout_offsets import compute_program_data_items

LEGACY = ("CHAIN", "NOTE", "EXHIBIT", "EXAMINE", "TRANSFORM")

PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CHAINP.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 STORE-REC.
          05 STORE-ID   PIC 9(5).
          05 CHAIN      PIC X(10).
          05 NOTE       PIC X(30).
          05 EXHIBIT    PIC X.
          05 EXAMINE    PIC X.
          05 TRANSFORM  PIC X.
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 'ACME' TO CHAIN
           MOVE CHAIN TO NOTE
           DISPLAY 'X' NOTE ' ' CHAIN
           IF EXHIBIT = 'Y' MOVE 'N' TO EXAMINE TRANSFORM
           END-IF
           STOP RUN.
"""


def _parse(source: str):
    result = parse_cobol(source, filename="chain.cbl")
    assert result.ast is not None and result.errors == [], result.errors
    assert result.warnings == [], result.warnings
    return result.ast


def test_declared_legacy_words_are_data_items() -> None:
    ast = _parse(PROGRAM)
    names = [item.name for item in ast.find_all_by_type("CobolDataItem")]
    for word in LEGACY:
        assert word in names, names
    assert not any(name.startswith("ANONYMOUS") for name in names)


def test_declared_legacy_words_are_operands() -> None:
    ast = _parse(PROGRAM)
    moves = ast.find_all_by_type("MoveStatement")
    assert [(m.source, m.targets) for m in moves] == [
        ('"ACME"', ["CHAIN"]),
        ("CHAIN", ["NOTE"]),
        ('"N"', ["EXAMINE", "TRANSFORM"]),
    ]
    (display,) = ast.find_all_by_type("DisplayStatement")
    assert display.display_items == ['"X"', "NOTE", '" "', "CHAIN"]
    for node in ("ChainStatement", "NoteStatement", "ExhibitStatement"):
        assert ast.find_all_by_type(node) == []


def test_gen_data_and_data_items_keep_the_columns(tmp_path) -> None:
    path = tmp_path / "chain.cbl"
    path.write_text(PROGRAM)
    dataset = CopybookDataGenerator(
        DataGeneratorOptions(rows=1, seed=1)
    ).generate_from_file(str(path))
    header = dataset.to_csv().splitlines()[0].split(",")
    assert header == ["STORE-ID", *LEGACY]
    items = compute_program_data_items(_parse(PROGRAM))
    names = {entry["name"] for entry in items["items"]}
    assert set(LEGACY) <= names
    assert "FILLER" not in names


def test_dclgen_copybook_with_a_note_column(tmp_path) -> None:
    path = tmp_path / "DCLSTORE.cpy"
    path.write_text(
        "       01  DCLSTORE.\n"
        "           10 STORE-ID   PIC S9(9) USAGE COMP.\n"
        "           10 NOTE       PIC X(30).\n"
    )
    dataset = CopybookDataGenerator(
        DataGeneratorOptions(rows=1, seed=1)
    ).generate_from_file(str(path))
    assert dataset.to_csv().splitlines()[0] == "STORE-ID,NOTE"


@pytest.mark.parametrize(
    ("statement", "node"),
    [
        ("EXHIBIT NAMED WS-A", "ExhibitStatement"),
        ("EXAMINE WS-A TALLYING ALL 'A'", "ExamineStatement"),
        ("TRANSFORM WS-A CHARACTERS FROM 'A' TO 'B'", "TransformStatement"),
        ("CHAIN 'NEXTPGM'", "ChainStatement"),
        ("NOTE THIS IS A COMMENT", "NoteStatement"),
    ],
)
def test_undeclared_legacy_words_stay_verbs(statement: str, node: str) -> None:
    source = (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. LEGACY.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01 WS-A PIC X(5).\n"
        "       PROCEDURE DIVISION.\n"
        "       MAIN-PARA.\n"
        "           IF WS-A = 'Y'\n"
        "              MOVE 'N' TO WS-A\n"
        f"              {statement}.\n"
        "           STOP RUN.\n"
    )
    result = parse_cobol(source, filename="legacy.cbl")
    assert result.ast is not None and result.errors == [], result.errors
    assert len(result.ast.find_all_by_type(node)) == 1
    (move,) = result.ast.find_all_by_type("MoveStatement")
    assert move.targets == ["WS-A"]


@pytest.mark.parametrize(
    ("statement", "node"),
    [
        ("EXHIBIT NAMED WS-A", "ExhibitStatement"),
        ("EXAMINE WS-A TALLYING ALL 'A'", "ExamineStatement"),
        ("TRANSFORM WS-A CHARACTERS FROM 'A' TO 'B'", "TransformStatement"),
        ("CHAIN 'NEXTPGM'", "ChainStatement"),
        ("NOTE THIS IS A COMMENT", "NoteStatement"),
    ],
)
def test_undeclared_legacy_verb_ends_a_compute_expression(
    statement: str, node: str
) -> None:
    # Out of STATEMENT_KEYWORDS, the verbs are boundaries by TokenType only:
    # COMPUTE's value-only stop check folded them into the expression.
    source = (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. LEGACY.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01 WS-A PIC X(5).\n"
        "       01 WS-N PIC 9.\n"
        "       PROCEDURE DIVISION.\n"
        "       MAIN-PARA.\n"
        "           COMPUTE WS-N = WS-N + 1\n"
        f"           {statement}.\n"
        "           STOP RUN.\n"
    )
    result = parse_cobol(source, filename="legacy.cbl")
    assert result.ast is not None and result.errors == [], result.errors
    (compute,) = result.ast.find_all_by_type("ComputeStatement")
    assert compute.to_dict()["expression"] == "WS-N + 1"
    assert len(result.ast.find_all_by_type(node)) == 1
