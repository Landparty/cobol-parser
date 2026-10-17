"""``DFHRESP(cond)`` / ``DFHVALUE(cvda)`` arguments are no data names (#594).

The argument of ``DFHRESP`` / ``DFHVALUE`` is a CICS condition or CVDA name the
translator replaces with a constant. It went through the subscript splitter as
a data-item reference: xref listed ``NORMAL`` / ``LENGERR`` / ``ACQUIRED`` as
undefined, a WORKING-STORAGE item named ``NOTFND`` was credited by
``DFHRESP(NOTFND)`` (unused-variables, business-rules), and
``MOVE DFHVALUE(ACQUIRED) TO WS-ST`` was an unresolved move-type operand.
``JNIENVPTR`` was missing from xref's special registers.
"""

from __future__ import annotations

from cobolparser import (
    BusinessRuleExtractor,
    LintAnalyzer,
    MoveTypeChecker,
    UnusedVariableAnalyzer,
    parse_cobol,
)
from cobolparser.analysis.xref import XrefAnalyzer, is_special_register

SOURCE = "".join(
    f"       {line}\n"
    for line in (
        "IDENTIFICATION DIVISION.",
        "PROGRAM-ID. DFH.",
        "DATA DIVISION.",
        "WORKING-STORAGE SECTION.",
        "01 WS-REC PIC X(80).",
        "01 WS-KEY PIC X(8).",
        "01 WS-RESP PIC S9(8) COMP.",
        "01 WS-ST PIC S9(8) COMP.",
        "01 NOTFND PIC X.",
        "PROCEDURE DIVISION.",
        "    EXEC CICS READ FILE('CUSTF') INTO(WS-REC) RIDFLD(WS-KEY)",
        "         RESP(WS-RESP)",
        "    END-EXEC",
        "    EVALUATE WS-RESP",
        "      WHEN DFHRESP(NORMAL)",
        "        CONTINUE",
        "      WHEN DFHRESP(NOTFND)",
        "        DISPLAY 'NF'",
        "    END-EVALUATE",
        "    MOVE DFHVALUE(ACQUIRED) TO WS-ST",
        "    IF WS-RESP = DFHRESP(LENGERR) DISPLAY 'L' END-IF",
        "    EXEC CICS RETURN END-EXEC.",
    )
)


def _ast():
    result = parse_cobol(SOURCE)
    assert result.success, result.errors
    return result.ast


def test_xref_lists_no_condition_name_as_undefined():
    report = XrefAnalyzer().analyze(_ast())
    assert report.undefined == []
    assert report.entry_for("NOTFND").references == []
    assert report.entry_for("WS-ST").references != []


def test_unused_variables_reports_the_same_named_item():
    report = UnusedVariableAnalyzer().analyze(_ast())
    assert "NOTFND" in {item.name for item in report.unused_items}


def test_business_rules_do_not_read_the_same_named_item():
    rules = BusinessRuleExtractor(include_technical=True).analyze(_ast())
    inputs = {name for rule in rules.rules for name in rule.inputs}
    assert "NOTFND" not in inputs
    assert "WS-RESP" in inputs


def test_move_type_check_resolves_dfhvalue_as_numeric():
    report = MoveTypeChecker().check(_ast())
    assert report.unresolved_count == 0
    lint = LintAnalyzer(["move-type-check"]).analyze(_ast())
    assert lint.caveats == []


def test_jnienvptr_is_a_special_register():
    assert is_special_register("JNIENVPTR")
