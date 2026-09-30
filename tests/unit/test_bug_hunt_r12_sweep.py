"""Bug hunt round 12: defects found by crash/invariant sweeps and mutation
fuzzing over tests/samples and examples/cobol (NIST + shamrice).

Each test reproduces a defect through the public API; see the docstrings for
the pre-fix behaviour.
"""

import pytest

from cobolparser import parse_cobol
from cobolparser.analysis.program_flow import ProgramFlowAnalyzer
from cobolparser.generators import (
    Charset,
    CopybookDataGenerator,
    DataGeneratorOptions,
    EncodingOptions,
    RecordDecoder,
)

_HDR = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. T.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 X PIC 9.
       PROCEDURE DIVISION.
       P0.
"""


def _condition(relation: str) -> dict:
    result = parse_cobol(_HDR + f"           IF X {relation} 3 DISPLAY 'Y'.\n")
    assert result.errors == []
    return result.ast.find_all_by_type("IfStatement")[0].to_dict()["condition"]


# ---------------------------------------------------------------------------
# Relational noise words were matched case-sensitively
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("relation", "operator"),
    [
        ("equal to", "EQUAL"),
        ("greater than", "GREATER"),
        ("Less Than", "LESS"),
        ("greater than or equal to", "GREATER_OR_EQUAL"),
        ("less or equal", "LESS_OR_EQUAL"),
    ],
)
def test_lower_case_relational_operator_matches_upper_case(relation, operator):
    """Pre-fix, lower-case source kept the ``to``/``than`` connective in the
    right operand (``right_operand == "to 3"``) and -- worse -- split
    ``greater than or equal to 3`` into ``X > than OR X = to 3``. Upper-case
    source was always right; case must not change the AST."""
    lower = _condition(relation)
    upper = _condition(relation.upper())
    assert lower == upper
    assert lower["operator"] == operator
    assert lower["left_operand"] == "X"
    assert lower["right_operand"] == "3"


# ---------------------------------------------------------------------------
# GO TO. (alterable GO) took the period as its target
# ---------------------------------------------------------------------------


_ALTER = _HDR.replace("       P0.\n", "") + (
    "       P0.\n"
    "           ALTER P1 TO PROCEED TO P2.\n"
    "       P1.\n"
    "           GO TO.\n"
    "       P2.\n"
    "           STOP RUN.\n"
)


def test_alterable_go_to_has_no_target():
    """Pre-fix: ``target_paragraph == "."`` (NIST NC303M)."""
    result = parse_cobol(_ALTER)
    assert result.errors == []
    go = result.ast.find_all_by_type("GoStatement")[0]
    assert go.target_paragraph is None
    assert go.to_dict()["target_paragraphs"] == []


def test_alterable_go_to_puts_no_phantom_node_in_the_flow_graph():
    """Pre-fix the flow graph had a GOTO edge ``P1 -> "."`` to a node that
    does not exist; the ALTER edge is what carries the destination."""
    report = ProgramFlowAnalyzer().analyze(parse_cobol(_ALTER).ast)
    nodes = {n.name for n in report.nodes}
    for edge in report.edges:
        assert edge.source in nodes and edge.target in nodes, edge.to_dict()
    assert ("P1", "P2", "ALTER") in {
        (e.source, e.target, e.edge_type.value) for e in report.edges
    }


def test_go_without_to_before_period_is_alterable_too():
    result = parse_cobol(_ALTER.replace("GO TO.", "GO."))
    assert result.errors == []
    assert result.ast.find_all_by_type("GoStatement")[0].target_paragraph is None


# ---------------------------------------------------------------------------
# DATE/TIME cells carried leading zeros the decoder never renders
# ---------------------------------------------------------------------------


_DATES = """
       01  STAMP-REC.
           05  TXN-TIME        PIC 9(6).
           05  LONG-TIME       PIC 9(8).
           05  RUN-DATE        PIC 9(9).
           05  LILIAN-DATE     PIC S9(9) COMP.
           05  PACKED-TIME     PIC 9(5) COMP-3.
"""


@pytest.mark.parametrize("charset", [Charset.ASCII, Charset.EBCDIC])
def test_date_and_time_cells_round_trip_through_the_decoder(charset):
    """decode(encode(row)) == row is the documented contract. Pre-fix a
    TIME field rendered ``055132`` (and a 9(8) one ``00163040``, a 9-digit
    date ``019980928``) while the decoder -- like every other generated
    number -- renders ``55132``, so the round trip failed for any hour
    before 10."""
    options = DataGeneratorOptions(rows=40, seed=5).for_record_image()
    dataset = CopybookDataGenerator(options).generate_from_source(_DATES)
    opts = EncodingOptions(charset=charset)
    decoded = RecordDecoder.from_copybook_source(_DATES, opts=opts).decode_bytes(
        dataset.to_records(opts)
    )
    assert decoded.error_count == 0
    assert [list(r.values().values()) for r in decoded.records] == dataset.rows
    for row in dataset.rows:
        for cell in row:
            assert cell == "0" or not cell.lstrip("-").startswith("0"), row
