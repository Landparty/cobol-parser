"""IMS segment names that are not a single first child's VALUE.

``IMSSegmentAnalyzer`` used to read an SSA's segment name from the first
child of the SSA group only, so a name split across several elementary
fields came back truncated (``CUST`` for ``CUSTOMER``) and one held inside a
nested sub-group came back ``None``. ``EXEC DLI ... SEGMENT((area))`` -- the
data-area form -- was reported as the literal text ``(AREA)`` rather than
resolved through the area's value.
"""

from cobolparser import parse_cobol
from cobolparser.analysis.ims_segment_analyzer import IMSSegmentAnalyzer


def _program(data: str, procedure: str) -> str:
    return (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. IMSSSA.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01  GU-FUNC          PIC X(4) VALUE 'GU  '.\n"
        "       01  PCB-AREA         PIC X(80).\n"
        "       01  IO-AREA          PIC X(200).\n"
        f"{data}"
        "       PROCEDURE DIVISION.\n"
        f"{procedure}"
        "           GOBACK.\n"
    )


_CALL = "           CALL 'CBLTDLI' USING GU-FUNC PCB-AREA IO-AREA {ssa}.\n"


def _segments(source: str) -> list[list[str | None]]:
    result = parse_cobol(source)
    assert result.ast is not None, result.errors
    return [c.segment_names for c in IMSSegmentAnalyzer().analyze(result.ast)]


class TestSplitSegmentName:
    def test_name_split_across_two_leaves(self) -> None:
        data = (
            "       01  SSA-SPLIT.\n"
            "           05  SSA-SEG-A    PIC X(4) VALUE 'CUST'.\n"
            "           05  SSA-SEG-B    PIC X(4) VALUE 'OMER'.\n"
            "           05  FILLER       PIC X    VALUE SPACE.\n"
        )
        src = _program(data, _CALL.format(ssa="SSA-SPLIT"))
        assert _segments(src) == [["CUSTOMER"]]

    def test_short_name_padded_by_filler(self) -> None:
        data = (
            "       01  SSA-PAD.\n"
            "           05  SSA-SEG      PIC X(5) VALUE 'ORDER'.\n"
            "           05  FILLER       PIC X(3) VALUE SPACES.\n"
            "           05  FILLER       PIC X    VALUE '('.\n"
        )
        src = _program(data, _CALL.format(ssa="SSA-PAD"))
        assert _segments(src) == [["ORDER"]]

    def test_moved_into_second_leaf(self) -> None:
        data = (
            "       01  SSA-SPLIT.\n"
            "           05  SSA-SEG-A    PIC X(4) VALUE 'CUST'.\n"
            "           05  SSA-SEG-B    PIC X(4) VALUE 'OMER'.\n"
        )
        proc = "           MOVE 'ADDR' TO SSA-SEG-B.\n" + _CALL.format(ssa="SSA-SPLIT")
        assert _segments(_program(data, proc)) == [["CUSTADDR/CUSTOMER"]]

    def test_unknown_second_leaf_is_unresolved_not_truncated(self) -> None:
        data = (
            "       01  SSA-SPLIT.\n"
            "           05  SSA-SEG-A    PIC X(4) VALUE 'CUST'.\n"
            "           05  SSA-SEG-B    PIC X(4).\n"
        )
        src = _program(data, _CALL.format(ssa="SSA-SPLIT"))
        assert _segments(src) == [[None]]


class TestNestedGroupSsa:
    def test_segment_inside_sub_group(self) -> None:
        data = (
            "       01  SSA-NESTED.\n"
            "           05  SSA-KEY.\n"
            "               10  SSA-SEG  PIC X(8) VALUE 'ACCOUNT '.\n"
            "               10  FILLER   PIC X    VALUE '('.\n"
            "           05  SSA-QUAL     PIC X(20) VALUE 'ACCTNO  =12345)'.\n"
        )
        src = _program(data, _CALL.format(ssa="SSA-NESTED"))
        assert _segments(src) == [["ACCOUNT"]]

    def test_qualified_move_through_sub_group(self) -> None:
        data = (
            "       01  SSA-NESTED.\n"
            "           05  SSA-KEY.\n"
            "               10  SSA-SEG  PIC X(8).\n"
            "               10  FILLER   PIC X    VALUE SPACE.\n"
        )
        proc = "           MOVE 'BRANCH' TO SSA-SEG OF SSA-KEY OF SSA-NESTED.\n" + (
            _CALL.format(ssa="SSA-NESTED")
        )
        assert _segments(_program(data, proc)) == [["BRANCH"]]


class TestExecDliSegmentArea:
    def test_area_resolved_through_value(self) -> None:
        data = "       01  WS-SEG-AREA      PIC X(8) VALUE 'ORDER   '.\n"
        proc = (
            "           EXEC DLI GU USING PCB(1) SEGMENT((WS-SEG-AREA))\n"
            "                INTO(IO-AREA)\n"
            "           END-EXEC.\n"
        )
        assert _segments(_program(data, proc)) == [["ORDER"]]

    def test_area_resolved_through_move(self) -> None:
        data = "       01  WS-SEG-AREA      PIC X(8).\n"
        proc = (
            "           MOVE 'PATIENT' TO WS-SEG-AREA.\n"
            "           EXEC DLI GU USING PCB(1) SEGMENT((WS-SEG-AREA))\n"
            "                INTO(IO-AREA)\n"
            "           END-EXEC.\n"
        )
        assert _segments(_program(data, proc)) == [["PATIENT"]]

    def test_unknown_area_is_none_not_its_name(self) -> None:
        data = "       01  WS-SEG-AREA      PIC X(8).\n"
        proc = (
            "           EXEC DLI GU USING PCB(1) SEGMENT((WS-SEG-AREA))\n"
            "                INTO(IO-AREA)\n"
            "           END-EXEC.\n"
        )
        assert _segments(_program(data, proc)) == [[None]]

    def test_literal_segment_unchanged(self) -> None:
        proc = (
            "           EXEC DLI GU USING PCB(1) SEGMENT(CUSTOMER)\n"
            "                INTO(IO-AREA)\n"
            "           END-EXEC.\n"
        )
        assert _segments(_program("", proc)) == [["CUSTOMER"]]
