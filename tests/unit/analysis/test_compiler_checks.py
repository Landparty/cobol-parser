"""Tests for the compiler-check lint rules (cobolparser/analysis/compiler_checks.py)."""

from __future__ import annotations

import pytest

from cobolparser import parse_cobol
from cobolparser.analysis.compiler_checks import (
    COMPILER_RULE_DESCRIPTIONS,
    COMPILER_RULES,
    CompilerCheckAnalyzer,
)
from cobolparser.analysis.lint import RULES, LintAnalyzer
from cobolparser.analysis.sarif import RULE_DESCRIPTIONS
from cobolparser.models.data_items import ConditionNameItem


def program(working: str = "", procedure: str = "GOBACK.", extra: str = "") -> str:
    """A free-format program with the given WORKING-STORAGE and procedure."""
    return (
        ">>SOURCE FORMAT FREE\n"
        "IDENTIFICATION DIVISION.\n"
        "PROGRAM-ID. T.\n"
        f"{extra}"
        "DATA DIVISION.\n"
        "WORKING-STORAGE SECTION.\n"
        f"{working}\n"
        "PROCEDURE DIVISION.\n"
        "MAIN-PARA.\n"
        f"{procedure}\n"
    )


def run(source: str, rule: str | None = None):
    result = parse_cobol(source, filename="T.cbl")
    assert result.ast is not None, result.errors
    rules = [rule] if rule else None
    return CompilerCheckAnalyzer(rules).analyze(result.ast)


def kinds(source: str, rule: str | None = None) -> list[str]:
    return [f.kind for f in run(source, rule).findings]


# -- registration -------------------------------------------------------------


def test_rules_are_lint_rules_with_descriptions():
    for rule in COMPILER_RULES:
        assert rule in RULES
        assert rule in COMPILER_RULE_DESCRIPTIONS
        assert rule in RULE_DESCRIPTIONS


def test_unknown_rule_rejected():
    with pytest.raises(ValueError):
        CompilerCheckAnalyzer(["nope"])


def test_report_to_dict():
    report = run(program("01 A PIC 9 VALUE 12."), "value-clause")
    data = report.to_dict()
    assert data["findings"][0]["kind"] == "VALUE_TOO_MANY_DIGITS"
    assert data["caveats"] == []


# -- undefined-name ------------------------------------------------------------


def test_undefined_data_and_procedure_names():
    source = program(
        "01 A PIC X.",
        "MOVE A TO NOPE-ITEM\n    PERFORM NOPE-PARA\n    GOBACK.",
    )
    found = run(source, "undefined-name").findings
    assert {f.kind for f in found} == {
        "DATA_NAME_UNDEFINED",
        "PROCEDURE_NAME_UNDEFINED",
    }
    assert all(f.severity == "error" for f in found)
    assert {f.symbol for f in found} == {"NOPE-ITEM", "NOPE-PARA"}


def test_declared_names_are_not_reported():
    source = program(
        "01 A PIC X.\n01 B PIC X.",
        "MOVE A TO B\n    PERFORM OTHER-PARA\n    GOBACK.\nOTHER-PARA.\n    "
        "DISPLAY RETURN-CODE.",
    )
    assert kinds(source, "undefined-name") == []


def test_unexpanded_copy_skips_with_caveat():
    source = program("COPY MISSINGMEM.\n01 A PIC X.", "MOVE A TO B\n    GOBACK.")
    report = run(source, "undefined-name")
    assert report.findings == []
    assert any("COPY member was not expanded" in c for c in report.caveats)


def test_unexpanded_sql_include_skips_with_caveat():
    source = program(
        "EXEC SQL INCLUDE MYDCL END-EXEC.\n01 A PIC X.",
        "MOVE A TO B\n    GOBACK.",
    )
    report = run(source, "undefined-name")
    assert report.findings == []
    assert any("EXEC SQL INCLUDE MYDCL" in c for c in report.caveats)


def test_sqlca_include_does_not_skip():
    source = program(
        "EXEC SQL INCLUDE SQLCA END-EXEC.\n01 A PIC X.",
        "MOVE A TO NOPE-ITEM\n    GOBACK.",
    )
    assert kinds(source, "undefined-name") == ["DATA_NAME_UNDEFINED"]


def test_file_name_qualifier_is_not_a_data_name():
    source = (
        ">>SOURCE FORMAT FREE\n"
        "IDENTIFICATION DIVISION.\nPROGRAM-ID. T.\n"
        "ENVIRONMENT DIVISION.\nINPUT-OUTPUT SECTION.\nFILE-CONTROL.\n"
        "    SELECT PRINT-FILE ASSIGN TO PRT.\n"
        "DATA DIVISION.\nFILE SECTION.\nFD PRINT-FILE.\n01 PRINT-REC PIC X(80).\n"
        "PROCEDURE DIVISION.\n"
        "    OPEN OUTPUT PRINT-FILE\n"
        "    WRITE PRINT-REC IN PRINT-FILE\n"
        "    CLOSE PRINT-FILE\n"
        "    GOBACK.\n"
    )
    assert kinds(source, "undefined-name") == []


def test_contained_program_sees_enclosing_declarations():
    source = (
        ">>SOURCE FORMAT FREE\n"
        "IDENTIFICATION DIVISION.\nPROGRAM-ID. OUTER.\n"
        "DATA DIVISION.\nWORKING-STORAGE SECTION.\n01 SHARED-ITEM PIC X GLOBAL.\n"
        "PROCEDURE DIVISION.\n    CALL 'INNER'\n    GOBACK.\n"
        "IDENTIFICATION DIVISION.\nPROGRAM-ID. INNER.\n"
        "PROCEDURE DIVISION.\n    MOVE 'A' TO SHARED-ITEM\n    GOBACK.\n"
        "END PROGRAM INNER.\nEND PROGRAM OUTER.\n"
    )
    result = parse_cobol(source, filename="T.cbl")
    report = LintAnalyzer(["undefined-name"]).analyze(result.ast)
    assert report.findings == []


def test_screen_section_skips():
    source = program(
        "01 A PIC X.",
        "MOVE A TO B\n    GOBACK.",
    ).replace(
        "PROCEDURE DIVISION.",
        "SCREEN SECTION.\n01 MAIN-SCREEN.\n   05 LINE 1 COLUMN 1 VALUE 'X'.\n"
        "PROCEDURE DIVISION.",
    )
    report = run(source, "undefined-name")
    assert report.findings == []
    assert any("SCREEN SECTION" in c for c in report.caveats)


def test_debug_item_names_and_perform_forever_are_not_reported():
    source = program(
        "01 A PIC X.",
        "DISPLAY DEBUG-LINE\n    PERFORM FOREVER\n      EXIT PERFORM\n"
        "    END-PERFORM\n    GOBACK.",
    )
    assert kinds(source, "undefined-name") == []


# -- value-clause --------------------------------------------------------------


@pytest.mark.parametrize(
    ("entry", "kind", "severity"),
    [
        ("01 A PIC X(3) VALUE 'ABCDE'.", "VALUE_TOO_LONG", "warning"),
        ("01 A PIC X(2) VALUE X'C1C2C3'.", "VALUE_TOO_LONG", "warning"),
        ("01 A PIC 9(3) VALUE 12345.", "VALUE_TOO_MANY_DIGITS", "warning"),
        ("01 A PIC 9(3) VALUE -5.", "VALUE_SIGN_LOST", "warning"),
        ("01 A PIC 9(3)V9 VALUE 1.25.", "VALUE_DECIMALS_LOST", "warning"),
        ("01 A PIC X(4) VALUE 12.", "VALUE_NUMERIC_FOR_ALPHANUMERIC", "warning"),
        ("01 A PIC 9(3) VALUE 'AB'.", "VALUE_WRONG_CATEGORY", "error"),
        ("01 A PIC 9(3) VALUE SPACES.", "VALUE_WRONG_CATEGORY", "error"),
        ("01 A PIC 9(3) VALUE '000'.", "VALUE_QUOTED_NUMBER", "warning"),
    ],
)
def test_value_does_not_fit(entry, kind, severity):
    found = run(program(entry), "value-clause").findings
    assert [(f.kind, f.severity) for f in found] == [(kind, severity)]


@pytest.mark.parametrize(
    "entry",
    [
        "01 A PIC X(3) VALUE 'ABC'.",
        "01 A PIC X(3) VALUE SPACES.",
        "01 A PIC X(3) VALUE ALL '*'.",
        "01 A PIC 9(3) VALUE ZERO.",
        "01 A PIC S9(3) VALUE -5.",
        "01 A PIC 9(3)V99 VALUE 1.50.",
        "01 A PIC 9(3) VALUE 00012.",
        "01 A PIC 9(4) COMP-5 VALUE 65535.",
        "01 A PIC ZZ9 VALUE 'ABC'.",
        "01 A PIC 9(3) VALUE 1.000.",
    ],
)
def test_value_that_fits_is_quiet(entry):
    assert kinds(program(entry), "value-clause") == []


def test_value_in_linkage_is_ignored():
    source = program("01 A PIC X.").replace(
        "PROCEDURE DIVISION.",
        "LINKAGE SECTION.\n01 LK-A PIC X(4) VALUE 'ABCD'.\nPROCEDURE DIVISION.",
    )
    assert kinds(source, "value-clause") == ["VALUE_IGNORED"]


@pytest.mark.parametrize(
    ("entry", "kind"),
    [
        ("01 F PIC X.\n   88 F-ON VALUE 'YES'.", "CONDITION_NEVER_TRUE"),
        ("01 F PIC 9.\n   88 F-BIG VALUE 10.", "CONDITION_NEVER_TRUE"),
        ("01 F PIC 9.\n   88 F-NEG VALUE -1.", "CONDITION_NEVER_TRUE"),
        ("01 F PIC 9.\n   88 F-RANGE VALUE 1 THRU 12.", "CONDITION_NEVER_TRUE"),
        ("01 F PIC 9.\n   88 F-X VALUE 'X'.", "CONDITION_VALUE_WRONG_CATEGORY"),
    ],
)
def test_condition_values(entry, kind):
    assert kinds(program(entry), "value-clause") == [kind]


@pytest.mark.parametrize(
    "entry",
    [
        "01 F PIC X.\n   88 F-ON VALUE 'Y'.",
        "01 F PIC X.\n   88 F-ON VALUE SPACES.",
        "01 F PIC 9.\n   88 F-ON VALUE 1 THRU 9.",
        "01 F PIC XX.\n   88 F-ON VALUE X'C1C2'.",
        "01 F PIC 99.\n   88 F-ON VALUE '1'.",
    ],
)
def test_condition_values_that_fit(entry):
    found = kinds(program(entry), "value-clause")
    assert "CONDITION_NEVER_TRUE" not in found
    if "'1'" not in entry:
        assert found == []


def test_condition_value_kinds_recorded():
    result = parse_cobol(
        program("01 F PIC X(3).\n   88 F1 VALUE 'A' 7 SPACE ALL 'Z' 1 THRU 'B'.")
    )
    condition = next(
        n for n in result.ast.traverse_depth_first() if isinstance(n, ConditionNameItem)
    )
    assert condition.value_kinds == [
        "string",
        "numeric",
        "figurative",
        "all",
        "numeric",
        "string",
    ]


# -- data-layout ---------------------------------------------------------------


def test_redefines_larger_below_01():
    source = program("01 G.\n   05 G1 PIC X(2).\n   05 G2 REDEFINES G1 PIC X(5).")
    found = run(source, "data-layout").findings
    assert [f.kind for f in found] == ["REDEFINES_LARGER"]
    assert "3 byte(s)" in found[0].message


def test_redefines_at_01_or_smaller_is_quiet():
    source = program(
        "01 A PIC X(2).\n01 B REDEFINES A PIC X(5).\n"
        "01 G.\n   05 G1 PIC X(5).\n   05 G2 REDEFINES G1 PIC X(2)."
    )
    assert kinds(source, "data-layout") == []


def _fd_program(record_contains: str, record: str) -> str:
    return (
        ">>SOURCE FORMAT FREE\n"
        "IDENTIFICATION DIVISION.\nPROGRAM-ID. T.\n"
        "ENVIRONMENT DIVISION.\nINPUT-OUTPUT SECTION.\nFILE-CONTROL.\n"
        "    SELECT IN-FILE ASSIGN TO INFILE.\n"
        "DATA DIVISION.\nFILE SECTION.\n"
        f"FD IN-FILE {record_contains}.\n{record}\n"
        "PROCEDURE DIVISION.\n    GOBACK.\n"
    )


def test_record_contains_mismatch():
    source = _fd_program("RECORD CONTAINS 80 CHARACTERS", "01 IN-REC PIC X(90).")
    assert kinds(source, "data-layout") == ["RECORD_CONTAINS_MISMATCH"]


@pytest.mark.parametrize(
    ("clause", "record"),
    [
        ("RECORD CONTAINS 80 CHARACTERS", "01 IN-REC PIC X(80)."),
        ("RECORD CONTAINS 20 TO 80 CHARACTERS", "01 IN-REC PIC X(90)."),
        ("RECORD VARYING FROM 1 TO 80", "01 IN-REC PIC X(90)."),
        (
            "RECORD CONTAINS 80 CHARACTERS",
            "01 IN-REC PIC X(40).\n01 IN-REC2 PIC X(80).",
        ),
    ],
)
def test_record_contains_agreeing_or_variable(clause, record):
    assert kinds(_fd_program(clause, record), "data-layout") == []


# -- comparison ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("condition", "kind"),
    [
        ("N > 5000", "COMPARISON_ALWAYS_FALSE"),
        ("N = 5000", "COMPARISON_ALWAYS_FALSE"),
        ("N NOT = 5000", "COMPARISON_ALWAYS_TRUE"),
        ("N < 5000", "COMPARISON_ALWAYS_TRUE"),
        ("5000 < N", "COMPARISON_ALWAYS_FALSE"),
        ("N < 0", "COMPARISON_ALWAYS_FALSE"),
        ("N >= 0", None),
        ("N > -1", "COMPARISON_ALWAYS_TRUE"),
        ("N = -3", "COMPARISON_ALWAYS_FALSE"),
        ("S < 0", None),
        ("N = 999", None),
        ("C = 'ABCDE'", "COMPARISON_ALWAYS_FALSE"),
        ("C NOT = 'ABCDE'", "COMPARISON_ALWAYS_TRUE"),
        ("C = 'ABC  '", None),
        ("C > 'ABCDE'", None),
        ("N = 'ABC'", "COMPARISON_NONNUMERIC_LITERAL"),
        ("N = '123'", None),
        ("N > 'ABC'", None),
        ("B > 5000", None),
    ],
)
def test_comparisons(condition, kind):
    source = program(
        "01 N PIC 9(3).\n01 S PIC S9(3).\n01 C PIC X(3).\n01 B PIC 9(3) COMP.",
        f"IF {condition}\n      DISPLAY 'Y'\n    END-IF\n    GOBACK.",
    )
    assert kinds(source, "comparison") == ([kind] if kind else [])


def test_comparison_in_perform_until():
    source = program(
        "01 N PIC 9(3).",
        "PERFORM UNTIL N > 1000\n      ADD 1 TO N\n    END-PERFORM\n    GOBACK.",
    )
    assert kinds(source, "comparison") == ["COMPARISON_ALWAYS_FALSE"]


# -- search-table --------------------------------------------------------------


def test_search_problems():
    source = program(
        "01 T1.\n   05 E1 OCCURS 5 PIC X.\n"
        "01 T2.\n   05 E2 OCCURS 5 INDEXED BY X2 PIC X.\n"
        "01 NOT-TABLE PIC X.",
        "SEARCH E1 WHEN E1(1) = 'A' CONTINUE END-SEARCH\n"
        "    SEARCH ALL E2 WHEN E2(X2) = 'A' CONTINUE END-SEARCH\n"
        "    SEARCH NOT-TABLE WHEN NOT-TABLE = 'A' CONTINUE END-SEARCH\n"
        "    GOBACK.",
    )
    assert kinds(source, "search-table") == [
        "SEARCH_NO_INDEX",
        "SEARCH_ALL_NO_KEY",
        "SEARCH_NOT_A_TABLE",
    ]


def test_well_formed_search_is_quiet():
    source = program(
        "01 T.\n   05 E OCCURS 5 ASCENDING KEY E INDEXED BY X PIC X.",
        "SEARCH ALL E WHEN E(X) = 'A' CONTINUE END-SEARCH\n"
        "    SEARCH E WHEN E(X) = 'A' CONTINUE END-SEARCH\n    GOBACK.",
    )
    assert kinds(source, "search-table") == []


# -- divide-by-zero ------------------------------------------------------------


@pytest.mark.parametrize(
    ("statement", "expected"),
    [
        ("DIVIDE A BY 0 GIVING B", 1),
        ("DIVIDE ZERO INTO A", 1),
        ("COMPUTE A = B / 0", 1),
        ("COMPUTE A = B / 0.0 + 1", 1),
        ("DIVIDE A BY 2 GIVING B", 0),
        ("DIVIDE 0 BY A GIVING B", 0),
        ("COMPUTE A = B / 10", 0),
        ("COMPUTE A = 0 / B", 0),
    ],
)
def test_divide_by_zero(statement, expected):
    source = program("01 A PIC 9(3).\n01 B PIC 9(3).", f"{statement}\n    GOBACK.")
    assert len(kinds(source, "divide-by-zero")) == expected


# -- subscript-usage -----------------------------------------------------------


@pytest.mark.parametrize(
    ("statement", "kind"),
    [
        ("MOVE E TO F", "SUBSCRIPT_MISSING"),
        ("MOVE F(1) TO E(1)", "SUBSCRIPT_NOT_A_TABLE"),
        ("MOVE C2(1) TO F", "SUBSCRIPT_COUNT"),
        ("MOVE C2(1 2 3) TO F", "SUBSCRIPT_COUNT"),
        ("MOVE F(2:1) TO E(1)", "REFMOD_OUT_OF_RANGE"),
        ("MOVE F(1:2) TO E(1)", "REFMOD_OUT_OF_RANGE"),
        ("MOVE E(1) TO F", None),
        ("MOVE C2(1, 2) TO F", None),
        ("MOVE C2(1; 2) TO F", None),
        ("MOVE C2(I +1) TO F", None),
        ("MOVE E(I + 1) TO F", None),
        ("MOVE F(1:1) TO E(1)", None),
        ("MOVE LENGTH OF E TO I", None),
        ("MOVE C2(1 2)(1:1) TO F", None),
        ("MOVE E2 OF T2(1) TO F", None),
    ],
)
def test_subscript_usage(statement, kind):
    source = program(
        "01 T.\n   05 E OCCURS 5 PIC X.\n"
        "01 T2.\n   05 R OCCURS 3.\n      10 C2 OCCURS 4 PIC X.\n"
        "   05 E2 OCCURS 2 PIC X.\n"
        "01 F PIC X.\n01 I PIC 99.",
        f"{statement}\n    GOBACK.",
    )
    assert kinds(source, "subscript-usage") == ([kind] if kind else [])


def test_sql_host_variable_array_needs_no_subscript():
    source = program(
        "01 T.\n   05 HA-ID OCCURS 50 PIC X(10).",
        "EXEC SQL FETCH NEXT ROWSET FROM C1 FOR 50 ROWS INTO :HA-ID END-EXEC\n"
        "    GOBACK.",
    )
    assert kinds(source, "subscript-usage") == []


def test_search_table_name_needs_no_subscript():
    source = program(
        "01 T.\n   05 E OCCURS 5 INDEXED BY X PIC X.",
        "SET X TO 1\n    SEARCH E WHEN E(X) = 'A' CONTINUE END-SEARCH\n    GOBACK.",
    )
    assert kinds(source, "subscript-usage") == []


# -- procedure-structure -------------------------------------------------------


def test_empty_paragraph_is_info():
    source = program(
        "01 A PIC X.",
        "PERFORM WORK-PARA\n    GOBACK.\nEMPTY-PARA.\nWORK-PARA.\n    DISPLAY A.",
    )
    found = run(source, "procedure-structure").findings
    assert [(f.kind, f.severity, f.symbol) for f in found] == [
        ("EMPTY_PARAGRAPH", "info", "EMPTY-PARA")
    ]


def test_last_empty_paragraph_is_quiet():
    source = program("01 A PIC X.", "GOBACK.\nEND-OF-PROGRAM.")
    assert kinds(source, "procedure-structure") == []


def test_duplicate_paragraph_severity():
    unreferenced = program(
        "01 A PIC X.", "GOBACK.\nDUP-PARA.\n    DISPLAY 1.\nDUP-PARA.\n    DISPLAY 2."
    )
    found = run(unreferenced, "procedure-structure").findings
    assert [(f.kind, f.severity) for f in found] == [("DUPLICATE_PARAGRAPH", "warning")]
    referenced = unreferenced.replace("GOBACK.", "PERFORM DUP-PARA\n    GOBACK.", 1)
    found = run(referenced, "procedure-structure").findings
    assert [(f.kind, f.severity) for f in found] == [("DUPLICATE_PARAGRAPH", "error")]


def test_same_paragraph_name_in_two_sections_is_quiet():
    source = program(
        "01 A PIC X.",
        "PERFORM S1\n    GOBACK.\nS1 SECTION.\nP-EXIT.\n    EXIT.\n"
        "S2 SECTION.\nP-EXIT.\n    EXIT.",
    )
    assert kinds(source, "procedure-structure") == []


# -- corresponding -------------------------------------------------------------


def test_corresponding_without_common_names():
    source = program(
        "01 G1.\n   05 F1 PIC X.\n01 G2.\n   05 F2 PIC X.\n" "01 G3.\n   05 F1 PIC X.",
        "MOVE CORRESPONDING G1 TO G2\n    MOVE CORR G1 TO G3\n    GOBACK.",
    )
    found = run(source, "corresponding").findings
    assert [(f.kind, f.symbol) for f in found] == [("NO_CORRESPONDING_ITEMS", "G2")]


def test_corresponding_ignores_filler_redefines_and_tables():
    source = program(
        "01 G1.\n   05 FILLER PIC X.\n   05 T1 OCCURS 2 PIC X.\n"
        "01 G2.\n   05 FILLER PIC X.\n   05 T1 OCCURS 2 PIC X.",
        "MOVE CORR G1 TO G2\n    GOBACK.",
    )
    assert kinds(source, "corresponding") == ["NO_CORRESPONDING_ITEMS"]


# -- arithmetic-operand --------------------------------------------------------


@pytest.mark.parametrize(
    ("statement", "expected"),
    [
        ("ADD C TO A", ["NONNUMERIC_ARITHMETIC_OPERAND"]),
        ("ADD A TO C", ["NONNUMERIC_ARITHMETIC_RECEIVER"]),
        ("ADD A B GIVING C", ["NONNUMERIC_ARITHMETIC_RECEIVER"]),
        ("COMPUTE A = G + 1", ["NONNUMERIC_ARITHMETIC_OPERAND"]),
        ("MULTIPLY A BY E", ["NONNUMERIC_ARITHMETIC_RECEIVER"]),
        ("ADD A B GIVING E", []),
        ("COMPUTE E = A * 2", []),
        ("COMPUTE A = F1 OF G + 1", []),
        ("ADD A TO B", []),
        ("SUBTRACT A FROM B GIVING E", []),
        ("COMPUTE A = FUNCTION LENGTH(FUNCTION TRIM(C)) + 1", []),
        ("COMPUTE A = LENGTH OF C", []),
    ],
)
def test_arithmetic_operands(statement, expected):
    source = program(
        "01 A PIC 9(3).\n01 B PIC 9(3).\n01 C PIC X(3).\n01 E PIC ZZ9.\n"
        "01 G.\n   05 F1 PIC 9.",
        f"{statement}\n    GOBACK.",
    )
    assert kinds(source, "arithmetic-operand") == expected


# -- parser fixes these rules rely on -----------------------------------------


def test_omitted_copy_lines_recorded():
    result = parse_cobol(program("COPY MISSINGMEM.\n01 A PIC X."))
    assert result.ast.omitted_copy_lines
    clean = parse_cobol(program("01 A PIC X."))
    assert clean.ast.omitted_copy_lines == ()


def test_go_to_after_perform_varying_after_until_is_kept():
    source = program(
        "01 S1 PIC 99.\n01 S2 PIC 99.",
        "PERFORM WORK-PARA VARYING S1 FROM 1 BY 1 UNTIL S1 > 2\n"
        "        AFTER S2 FROM 1 BY 1 UNTIL S2 > 2\n"
        "    GO TO END-PARA.\nWORK-PARA.\n    CONTINUE.\nEND-PARA.\n    GOBACK.",
    )
    result = parse_cobol(source)
    gos = result.ast.find_all_by_type("GoStatement")
    assert len(gos) == 1
    perform = result.ast.find_all_by_type("PerformStatement")[0]
    assert "GO" not in str(perform.after_clauses[0]["until_condition"].operands)


# -- lint integration ----------------------------------------------------------


def test_lint_runs_the_rules_and_passes_caveats():
    source = program(
        "COPY MISSINGMEM.\n01 A PIC 9 VALUE 12.", "MOVE A TO B\n    GOBACK."
    )
    result = parse_cobol(source)
    report = LintAnalyzer().analyze(result.ast)
    rules = {f.rule for f in report.findings}
    assert "value-clause" in rules
    assert "undefined-name" in report.rules_run
    assert any("undefined-name skipped" in c for c in report.caveats)


def test_data_rules_run_without_procedure_division():
    source = (
        ">>SOURCE FORMAT FREE\nIDENTIFICATION DIVISION.\nPROGRAM-ID. T.\n"
        "DATA DIVISION.\nWORKING-STORAGE SECTION.\n01 A PIC 9 VALUE 12.\n"
    )
    assert kinds(source) == ["VALUE_TOO_MANY_DIGITS"]
