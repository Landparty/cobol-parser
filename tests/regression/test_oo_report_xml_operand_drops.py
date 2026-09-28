"""Regression tests: operands dropped from valid OO / Report Writer / XML-JSON
source (2026-09-28 bug hunt).

1. INVOKE ... USING / RETURNING stopped at a subscript, an OF/IN qualifier,
   ``LENGTH OF`` / ``ADDRESS OF`` or ``OMITTED``: the rest of the statement
   (RETURNING included) was warned about and dropped.
2. XML/JSON GENERATE/PARSE clause subjects (``COUNT IN``, JSON PARSE's
   ``INTO``, ``NAME OF`` / ``TYPE OF`` / ``SUPPRESS`` / ``CONVERTING`` items,
   ``NAMESPACE IS`` identifiers) lived only in ``clause_text``, so
   unused-variables reported each as never referenced and xref saw none.
3. A one-/two-digit integer inside a report-group clause (``SUM WS-AMT (1)``,
   ``PRESENT WHEN WS-I > 1``) lexes as a LEVEL_NUMBER and ended the clause,
   opening a phantom data item and dropping the rest of the entry.
4. ``LINE integer ON NEXT PAGE`` dropped ``ON`` with a warning and misread
   ``NEXT PAGE`` as an empty ``NEXT GROUP`` clause.
"""

from cobolparser import UnusedVariableAnalyzer, parse_cobol
from cobolparser.analysis.xref import XrefAnalyzer


def _program(data: str, procedure: str, env: str = "") -> str:
    return (
        "IDENTIFICATION DIVISION.\n"
        "PROGRAM-ID. T1.\n"
        f"{env}"
        "DATA DIVISION.\n"
        f"{data}"
        "PROCEDURE DIVISION.\n"
        "MAIN-PARA.\n"
        f"{procedure}"
    )


class TestInvokeOperandForms:
    SRC = _program(
        "WORKING-STORAGE SECTION.\n"
        "01 WS-OBJ USAGE OBJECT REFERENCE.\n"
        "01 WS-TAB.\n"
        "   05 WS-AMT PIC 9(5) OCCURS 5.\n"
        "01 WS-I PIC 9.\n"
        "01 WS-GRP.\n"
        "   05 WS-X PIC X(5).\n"
        "01 WS-RC PIC 9.\n"
        "01 WS-OUT.\n"
        "   05 WS-R PIC 9 OCCURS 3.\n",
        "    INVOKE WS-OBJ 'a' USING BY VALUE WS-AMT (WS-I)\n"
        "        RETURNING WS-RC\n"
        "    INVOKE WS-OBJ 'b' USING WS-X OF WS-GRP\n"
        "    INVOKE WS-OBJ 'c' USING BY CONTENT LENGTH OF WS-X\n"
        "    INVOKE WS-OBJ 'd' RETURNING WS-R (2)\n"
        "    INVOKE WS-OBJ 'e' USING OMITTED WS-RC\n"
        "    DISPLAY 'DONE'\n"
        "    GOBACK.\n",
    )

    def test_no_warnings_and_every_statement_kept(self):
        result = parse_cobol(self.SRC)
        assert result.errors == []
        assert result.warnings == []
        types = [type(s).__name__ for s in result.ast.get_all_statements()]
        assert types == ["InvokeStatement"] * 5 + [
            "DisplayStatement",
            "GobackStatement",
        ]

    def test_operands_are_folded(self):
        invokes = parse_cobol(self.SRC).ast.find_all_by_type("InvokeStatement")
        params = [
            [(p.name, p.passing_mode) for p in s.using_parameters] for s in invokes
        ]
        assert params == [
            [("WS-AMT ( WS-I )", "VALUE")],
            [("WS-X OF WS-GRP", "REFERENCE")],
            [("LENGTH OF WS-X", "CONTENT")],
            [],
            [("OMITTED", "REFERENCE"), ("WS-RC", "REFERENCE")],
        ]
        assert invokes[0].returning_target == "WS-RC"
        assert invokes[3].returning_target == "WS-R ( 2 )"

    def test_subscript_variable_is_referenced(self):
        report = UnusedVariableAnalyzer().analyze(parse_cobol(self.SRC).ast)
        assert "WS-I" not in {item.name for item in report.unused_items}


class TestXmlJsonClauseReferences:
    SRC = _program(
        "WORKING-STORAGE SECTION.\n"
        "01 WS-IN PIC X(100).\n"
        "01 WS-OUT PIC X(100).\n"
        "01 WS-CNT PIC 9(5).\n"
        "01 WS-NS PIC X(40).\n"
        "01 WS-REC.\n"
        "   05 A PIC X(5).\n"
        "   05 B PIC X(5).\n"
        "   05 C PIC 9(5).\n"
        "01 WS-DEST.\n"
        "   05 D PIC X(5).\n",
        "    XML GENERATE WS-OUT FROM WS-REC COUNT IN WS-CNT\n"
        "        NAMESPACE IS WS-NS\n"
        "        NAME OF A IS 'aa'\n"
        "        TYPE OF C IS ATTRIBUTE\n"
        "        SUPPRESS B WHEN SPACES\n"
        "    END-XML\n"
        "    JSON PARSE WS-IN INTO WS-DEST WITH DETAIL\n"
        "        NAME OF D IS 'dd'\n"
        "    END-JSON\n"
        "    GOBACK.\n",
    )

    def test_structured_fields(self):
        stmts = parse_cobol(self.SRC).ast.find_all_by_type("XmlJsonStatement")
        gen, parse = stmts
        assert gen.count_in == "WS-CNT"
        assert gen.clause_items == ["WS-NS", "A", "C", "B"]
        assert parse.into_item == "WS-DEST"
        assert parse.clause_items == ["D"]
        as_dict = parse.to_dict()
        assert as_dict["into_item"] == "WS-DEST"
        assert as_dict["clause_items"] == ["D"]

    def test_clause_items_are_not_unused(self):
        report = UnusedVariableAnalyzer().analyze(parse_cobol(self.SRC).ast)
        assert {item.name for item in report.unused_items} == set()

    def test_xref_roles(self):
        report = XrefAnalyzer().analyze(parse_cobol(self.SRC).ast).to_dict()
        roles = {
            e["name"]: {r["role"] for r in e["references"]} for e in report["entries"]
        }
        assert roles["WS-CNT"] == {"write"}
        assert roles["WS-DEST"] == {"write"}
        assert roles["WS-NS"] == {"read"}
        assert roles["B"] == {"read"}

    def test_validating_with_file_schema_is_not_a_data_item(self):
        src = _program(
            "WORKING-STORAGE SECTION.\n01 WS-IN PIC X(100).\n",
            "    XML PARSE WS-IN VALIDATING WITH FILE ORDERXSD\n"
            "        PROCESSING PROCEDURE H1\n"
            "    END-XML\n"
            "    GOBACK.\n"
            "H1.\n"
            "    CONTINUE.\n",
        )
        stmt = parse_cobol(src).ast.find_all_by_type("XmlJsonStatement")[0]
        assert stmt.clause_items == []
        assert stmt.processing_procedure == "H1"


_REPORT_ENV = (
    "ENVIRONMENT DIVISION.\n"
    "INPUT-OUTPUT SECTION.\n"
    "FILE-CONTROL.\n"
    "    SELECT RPT-FILE ASSIGN TO RPTOUT.\n"
)


def _report_program(groups: str) -> str:
    return _program(
        "FILE SECTION.\n"
        "FD RPT-FILE REPORT IS RPT-A.\n"
        "WORKING-STORAGE SECTION.\n"
        "01 WS-GRP.\n"
        "   05 WS-AMT PIC 9(5)V99 OCCURS 3.\n"
        "01 WS-I PIC 9.\n"
        "01 WS-FLAG PIC X.\n"
        "REPORT SECTION.\n"
        "RD RPT-A.\n"
        f"{groups}",
        "    OPEN OUTPUT RPT-FILE\n"
        "    INITIATE RPT-A\n"
        "    GENERATE DL\n"
        "    TERMINATE RPT-A\n"
        "    CLOSE RPT-FILE\n"
        "    STOP RUN.\n",
        env=_REPORT_ENV,
    )


def _report_items(result):
    items = {}
    for item in result.ast.get_data_items():
        clauses = item.get_metadata("report_clauses")
        if clauses is not None or item.name.startswith("ANONYMOUS"):
            items[item.name] = clauses
    return items


class TestReportClauseIntegers:
    SRC = _report_program(
        "01 DL TYPE DETAIL LINE PLUS 1.\n"
        "   05 COLUMN 40 PIC X(3) VALUE 'X' PRESENT WHEN WS-I > 1.\n"
        "   05 COLUMN 50 PIC X(3) VALUE 'Y' PRESENT WHEN WS-FLAG = 'Y'.\n"
        "01 CFF TYPE CONTROL FOOTING FINAL LINE PLUS 1.\n"
        "   05 T-SUM COLUMN 10 PIC Z(6)9.99 SUM WS-AMT (1) WS-AMT (2)\n"
        "      WS-AMT OF WS-GRP (3) RESET ON FINAL.\n"
    )

    def test_no_phantom_items_or_warnings(self):
        result = parse_cobol(self.SRC)
        assert result.errors == []
        assert result.warnings == []
        report_section = result.ast.get_division("DATA")._sections["REPORT"]
        assert [item.name for item in report_section.data_items] == ["DL", "CFF"]

    def test_clause_operands(self):
        items = _report_items(parse_cobol(self.SRC))
        present = [
            clauses.get("present_when")
            for clauses in items.values()
            if clauses and "present_when" in clauses
        ]
        assert present == ["WS-I > 1", "WS-FLAG = 'Y'"]
        assert items["T-SUM"]["sum"] == [
            {
                "operands": [
                    "WS-AMT ( 1 )",
                    "WS-AMT ( 2 )",
                    "WS-AMT OF WS-GRP ( 3 )",
                ],
                "reset_on": "FINAL",
            }
        ]


class TestReportLineOnNextPage:
    SRC = _report_program(
        "01 DL TYPE DETAIL.\n"
        "   05 LINE 5 ON NEXT PAGE.\n"
        "      10 COLUMN 1 PIC X(5) VALUE 'END'.\n"
        "   05 LINE NUMBER IS 7 ON NEXT PAGE COLUMN 1 PIC X(3) VALUE 'A'.\n"
    )

    def test_line_on_next_page(self):
        result = parse_cobol(self.SRC)
        assert result.errors == []
        assert result.warnings == []
        lines = [
            clauses
            for clauses in _report_items(result).values()
            if clauses and "line" in clauses
        ]
        assert lines == [
            {"line": ["5 ON NEXT PAGE"]},
            {"line": ["7 ON NEXT PAGE"], "column": ["1"]},
        ]
