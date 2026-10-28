"""A value overwritten before it is read again: the field-flow report's
``overwrites`` and the impact paths they mark."""

from __future__ import annotations

from typing import Any

from cobolparser import parse_cobol
from cobolparser.analysis.field_lineage import FieldFlowAnalyzer, FieldFlowReport
from cobolparser.analysis.lineage_graph import LineageGraph

PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. OWPROG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-IN        PIC 9(5).
       01  WS-OTHER     PIC 9(5).
       01  WS-FLAG      PIC X.
       01  WS-OUT       PIC 9(5).
       PROCEDURE DIVISION.
       MAIN-PARA.
{body}
           STOP RUN.
{tail}"""


def _report(body: str, tail: str = "") -> FieldFlowReport:
    source = PROGRAM.format(body=body, tail=tail)
    result = parse_cobol(source, "OWPROG.cbl")
    assert result.ast is not None
    return FieldFlowAnalyzer().analyze(result.ast)


def _overwritten(body: str, tail: str = "", start: str = "WS-IN") -> list[Any]:
    graph = LineageGraph([_report(body, tail)])
    hits = graph.impact(start, None, "forward").hits
    return [h for h in hits if h.node_kind == "port"]


class TestReport:
    def test_unconditional_move_is_an_overwrite(self) -> None:
        report = _report(
            "           MOVE WS-IN TO WS-OUT\n"
            "           MOVE WS-OTHER TO WS-OUT\n"
            "           DISPLAY WS-OUT"
        )
        (kill,) = [e for e in report.overwrites if e.source.name == "WS-OTHER"]
        assert kill.target.name == "WS-OUT"
        assert kill.paragraph == "MAIN-PARA"
        assert "overwrites" in report.to_dict()

    def test_guarded_and_accumulating_writes_are_not(self) -> None:
        report = _report(
            "           IF WS-FLAG = 'Y'\n"
            "               MOVE WS-OTHER TO WS-OUT\n"
            "           END-IF\n"
            "           ADD WS-OTHER TO WS-OUT"
        )
        assert report.overwrites == []


class TestImpactPaths:
    def test_value_replaced_before_the_display(self) -> None:
        (hit,) = _overwritten(
            "           MOVE WS-IN TO WS-OUT\n"
            "           MOVE WS-OTHER TO WS-OUT\n"
            "           DISPLAY WS-OUT"
        )
        (kill,) = hit.overwritten
        assert kill.field == "WS-OUT"
        assert kill.statement == "MOVE"
        assert hit.to_dict()["overwritten"][0]["field"] == "WS-OUT"

    def test_value_read_before_it_is_replaced(self) -> None:
        (hit,) = _overwritten(
            "           MOVE WS-IN TO WS-OUT\n"
            "           DISPLAY WS-OUT\n"
            "           MOVE WS-OTHER TO WS-OUT"
        )
        assert hit.overwritten == ()
        assert "overwritten" not in hit.to_dict()

    def test_conditional_replacement_claims_nothing(self) -> None:
        (hit,) = _overwritten(
            "           MOVE WS-IN TO WS-OUT\n"
            "           IF WS-FLAG = 'Y'\n"
            "               MOVE WS-OTHER TO WS-OUT\n"
            "           END-IF\n"
            "           DISPLAY WS-OUT"
        )
        assert hit.overwritten == ()

    def test_across_paragraphs_claims_nothing(self) -> None:
        (hit,) = _overwritten(
            "           MOVE WS-IN TO WS-OUT\n"
            "           MOVE WS-OTHER TO WS-OUT\n"
            "           PERFORM SHOW-PARA",
            "       SHOW-PARA.\n           DISPLAY WS-OUT.\n",
        )
        assert hit.overwritten == ()

    def test_backward_from_the_display(self) -> None:
        graph = LineageGraph(
            [
                _report(
                    "           MOVE WS-IN TO WS-OUT\n"
                    "           MOVE WS-OTHER TO WS-OUT\n"
                    "           DISPLAY WS-OUT"
                )
            ]
        )
        start = graph.impact("WS-OUT", None, "backward")
        # From the field itself both values are its sources: it holds each
        # in turn, so nothing is claimed.
        assert all(h.overwritten == () for h in start.hits)

    def test_sql_select_into_overwrites(self) -> None:
        (hit,) = _overwritten(
            "           MOVE WS-IN TO WS-OUT\n"
            "           EXEC SQL SELECT BAL INTO :WS-OUT FROM ACCT END-EXEC\n"
            "           DISPLAY WS-OUT"
        )
        (kill,) = hit.overwritten
        assert kill.statement == "EXEC SQL"


class TestMcpAnswer:
    def test_overwritten_hits_are_named_and_listed_last(self, tmp_path: Any) -> None:
        from cobolparser.config.project import ProjectConfig
        from cobolparser.mcp import CobolTools, Workspace

        (tmp_path / "OWPROG.cbl").write_text(
            PROGRAM.format(
                body="           MOVE WS-IN TO WS-OUT\n"
                "           MOVE WS-OTHER TO WS-OUT\n"
                "           DISPLAY WS-OUT",
                tail="",
            )
        )
        tools = CobolTools(Workspace(tmp_path, ProjectConfig()))
        answer = tools.impact_of_change("WS-IN", "OWPROG.cbl")["answer"]
        assert answer["may_be_overwritten"] == 1
        flagged = [h for h in answer["hits"] if "may_be_overwritten" in h]
        assert flagged[0]["may_be_overwritten"] == ["WS-OUT by MOVE at OWPROG.cbl:12"]
        assert answer["hits"][-1] is flagged[-1]
