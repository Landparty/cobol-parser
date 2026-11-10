"""Regression tests for open finding M10: conditional compilation was
functionally incomplete.

Before the fix, ``preprocess_conditional_compilation`` only evaluated
``symbol IS [NOT] DEFINED`` in ``>>IF`` conditions — any other condition
(e.g. ``>>IF DEBUGLEVEL > 3``) unconditionally blanked the guarded block
with a generic warning, and ``>>EVALUATE`` fell through to the unknown-
directive passthrough path.

After the fix the preprocessor supports:
- comparisons (=, <>, >, <, >=, <=) between symbol values and literals
- AND / OR / NOT with parentheses, DEFINED(sym), boolean literals
- >>EVALUATE TRUE with condition >>WHEN branches
- >>EVALUATE symbol with literal >>WHEN branches, and >>WHEN OTHER
- documented degradation: an undefined symbol referenced in a comparison
  warns and makes the condition FALSE
"""

from cobolparser.parser import parse_cobol_with_expansion
from cobolparser.preprocess import preprocess_conditional_compilation


def _run(source, defines=None):
    warnings = []
    out = preprocess_conditional_compilation(source, defines, warnings)
    return out, warnings


class TestM10ConditionalCompilation:
    """M10: real >>IF condition evaluation and >>EVALUATE support."""

    # -- numeric comparisons ------------------------------------------------

    def test_numeric_comparison_true_keeps_block(self):
        out, warnings = _run(
            ">>IF DEBUGLEVEL > 3\nDISPLAY 'DEBUG'.\n>>END-IF\n",
            {"DEBUGLEVEL": "5"},
        )
        assert "DISPLAY 'DEBUG'." in out
        assert warnings == []

    def test_numeric_comparison_false_blanks_block(self):
        out, warnings = _run(
            ">>IF DEBUGLEVEL > 3\nDISPLAY 'DEBUG'.\n>>END-IF\nDISPLAY 'AFTER'.\n",
            {"DEBUGLEVEL": "2"},
        )
        assert "DEBUG" not in out
        assert "DISPLAY 'AFTER'." in out
        assert warnings == []

    def test_blanked_lines_preserve_line_numbers(self):
        source = ">>IF LVL > 3\nDISPLAY 'A'.\nDISPLAY 'B'.\n>>END-IF\nDISPLAY 'C'.\n"
        out, _ = _run(source, {"LVL": "1"})
        out_lines = out.split("\n")
        assert len(out_lines) == len(source.splitlines())
        # Line 5 (1-based) must still be the DISPLAY 'C'. line.
        assert out_lines[4] == "DISPLAY 'C'."
        assert out_lines[0] == "" and out_lines[1] == "" and out_lines[2] == ""

    def test_all_comparison_operators(self):
        cases = [
            ("V = 5", True),
            ("V <> 5", False),
            ("V >= 5", True),
            ("V <= 4", False),
            ("V < 10", True),
            ("V > 10", False),
        ]
        for cond, expected in cases:
            out, warnings = _run(f">>IF {cond}\nDISPLAY 'YES'.\n>>END-IF\n", {"V": "5"})
            assert ("YES" in out) is expected, cond
            assert warnings == [], cond

    def test_numeric_values_via_int_symbol_values(self):
        out, warnings = _run(
            ">>IF DEBUGLEVEL >= 3\nDISPLAY 'ON'.\n>>END-IF\n", {"DEBUGLEVEL": 3}
        )
        assert "ON" in out
        assert warnings == []

    def test_string_comparison_case_insensitive(self):
        out, warnings = _run(
            ">>IF ENV = 'PROD'\nDISPLAY 'P'.\n>>ELSE\nDISPLAY 'NP'.\n>>END-IF\n",
            {"ENV": "prod"},
        )
        assert "DISPLAY 'P'." in out
        assert "NP" not in out
        assert warnings == []

    # -- boolean operators --------------------------------------------------

    def test_and_or_not_with_parentheses(self):
        defines = {"A": "1", "B": "2"}
        out, warnings = _run(
            ">>IF A = 1 AND B = 2\nDISPLAY 'AND'.\n>>END-IF\n", defines
        )
        assert "AND" in out and warnings == []

        out, warnings = _run(">>IF A = 9 OR B = 2\nDISPLAY 'OR'.\n>>END-IF\n", defines)
        assert "OR" in out and warnings == []

        out, warnings = _run(">>IF NOT (A = 9)\nDISPLAY 'NOTP'.\n>>END-IF\n", defines)
        assert "NOTP" in out and warnings == []

        out, warnings = _run(
            ">>IF (A = 1 OR B = 9) AND NOT B = 9\nDISPLAY 'MIX'.\n>>END-IF\n",
            defines,
        )
        assert "MIX" in out and warnings == []

        out, warnings = _run(">>IF A = 1 AND B = 9\nDISPLAY 'NO'.\n>>END-IF\n", defines)
        assert "NO" not in out and warnings == []

    def test_defined_function_and_is_defined_forms(self):
        out, warnings = _run(
            ">>IF DEFINED(FLAG) AND FLAG = 1\nDISPLAY 'F'.\n>>END-IF\n",
            {"FLAG": "1"},
        )
        assert "DISPLAY 'F'." in out
        assert warnings == []

        out, warnings = _run(">>IF FLAG IS NOT DEFINED\nDISPLAY 'ND'.\n>>END-IF\n")
        assert "ND" in out
        assert warnings == []

    def test_boolean_literals(self):
        out, warnings = _run(">>IF B'1'\nDISPLAY 'B1'.\n>>END-IF\n")
        assert "B1" in out and warnings == []

        out, warnings = _run(">>IF TRUE AND NOT FALSE\nDISPLAY 'T'.\n>>END-IF\n")
        assert "DISPLAY 'T'." in out and warnings == []

        out, warnings = _run(">>IF B'0'\nDISPLAY 'B0'.\n>>END-IF\n")
        assert "B0" not in out and warnings == []

    # -- undefined symbol degradation ----------------------------------------

    def test_undefined_symbol_comparison_warns_and_is_false(self):
        out, warnings = _run(
            ">>IF DEBUGLEVEL > 3\nDISPLAY 'HIDDEN'.\n>>ELSE\nDISPLAY 'ELSE'.\n>>END-IF\n"
        )
        assert "HIDDEN" not in out
        assert "ELSE" in out  # condition is FALSE, so >>ELSE branch is taken
        assert any("undefined symbol 'DEBUGLEVEL'" in w for w in warnings)

    # -- >>EVALUATE symbol with literal WHENs ---------------------------------

    def test_evaluate_symbol_literal_whens(self):
        source = (
            ">>EVALUATE PLATFORM\n"
            ">>WHEN 'ZOS'\n"
            "DISPLAY 'MAINFRAME'.\n"
            ">>WHEN 'AIX'\n"
            "DISPLAY 'UNIX'.\n"
            ">>END-EVALUATE\n"
        )
        out, warnings = _run(source, {"PLATFORM": "AIX"})
        assert "UNIX" in out
        assert "MAINFRAME" not in out
        assert warnings == []

    def test_evaluate_symbol_numeric_when(self):
        source = (
            ">>EVALUATE LEVEL\n"
            ">>WHEN 1\n"
            "DISPLAY 'ONE'.\n"
            ">>WHEN 2\n"
            "DISPLAY 'TWO'.\n"
            ">>WHEN OTHER\n"
            "DISPLAY 'MANY'.\n"
            ">>END-EVALUATE\n"
        )
        out, warnings = _run(source, {"LEVEL": "2"})
        assert "TWO" in out
        assert "ONE" not in out and "MANY" not in out
        assert warnings == []

    def test_evaluate_when_other_selected_when_nothing_matches(self):
        source = (
            ">>EVALUATE LEVEL\n"
            ">>WHEN 1\n"
            "DISPLAY 'ONE'.\n"
            ">>WHEN OTHER\n"
            "DISPLAY 'OTHER'.\n"
            ">>END-EVALUATE\n"
        )
        out, warnings = _run(source, {"LEVEL": "9"})
        assert "OTHER" in out
        assert "ONE" not in out
        assert warnings == []

    def test_evaluate_no_match_and_no_other_blanks_everything(self):
        source = (
            ">>EVALUATE LEVEL\n"
            ">>WHEN 1\n"
            "DISPLAY 'ONE'.\n"
            ">>END-EVALUATE\n"
            "DISPLAY 'AFTER'.\n"
        )
        out, warnings = _run(source, {"LEVEL": "9"})
        assert "ONE" not in out
        assert "AFTER" in out
        assert warnings == []

    def test_evaluate_undefined_subject_only_other_matches(self):
        source = (
            ">>EVALUATE MISSING\n"
            ">>WHEN 1\n"
            "DISPLAY 'ONE'.\n"
            ">>WHEN OTHER\n"
            "DISPLAY 'FALLBACK'.\n"
            ">>END-EVALUATE\n"
        )
        out, warnings = _run(source)
        assert "ONE" not in out
        assert "FALLBACK" in out
        assert any("undefined symbol 'MISSING'" in w for w in warnings)

    # -- >>EVALUATE TRUE with condition WHENs ---------------------------------

    def test_evaluate_true_condition_whens(self):
        source = (
            ">>EVALUATE TRUE\n"
            ">>WHEN DEBUGLEVEL > 7\n"
            "DISPLAY 'VERBOSE'.\n"
            ">>WHEN DEBUGLEVEL > 3\n"
            "DISPLAY 'NORMAL'.\n"
            ">>WHEN OTHER\n"
            "DISPLAY 'QUIET'.\n"
            ">>END-EVALUATE\n"
        )
        out, warnings = _run(source, {"DEBUGLEVEL": "5"})
        assert "NORMAL" in out
        assert "VERBOSE" not in out and "QUIET" not in out
        assert warnings == []

        out, warnings = _run(source, {"DEBUGLEVEL": "1"})
        assert "QUIET" in out
        assert "NORMAL" not in out and "VERBOSE" not in out
        assert warnings == []

    def test_evaluate_first_matching_when_wins(self):
        source = (
            ">>EVALUATE TRUE\n"
            ">>WHEN V >= 1\n"
            "DISPLAY 'FIRST'.\n"
            ">>WHEN V >= 1\n"
            "DISPLAY 'SECOND'.\n"
            ">>END-EVALUATE\n"
        )
        out, warnings = _run(source, {"V": "1"})
        assert "FIRST" in out
        assert "SECOND" not in out
        assert warnings == []

    def test_nested_if_inside_evaluate(self):
        source = (
            ">>EVALUATE TRUE\n"
            ">>WHEN MODE = 'FULL'\n"
            ">>IF TRACE IS DEFINED\n"
            "DISPLAY 'TRACED'.\n"
            ">>END-IF\n"
            "DISPLAY 'FULL'.\n"
            ">>WHEN OTHER\n"
            "DISPLAY 'LITE'.\n"
            ">>END-EVALUATE\n"
        )
        out, warnings = _run(source, {"MODE": "FULL", "TRACE": "TRUE"})
        assert "TRACED" in out and "FULL" in out and "LITE" not in out
        assert warnings == []

        out, warnings = _run(source, {"MODE": "FULL"})
        assert "TRACED" not in out and "FULL" in out
        assert warnings == []

    def test_unclosed_evaluate_warns(self):
        _, warnings = _run(">>EVALUATE TRUE\n>>WHEN 1 = 1\nDISPLAY 'X'.\n")
        assert any("unclosed >>EVALUATE" in w for w in warnings)

    # -- backward-compatible API forms ----------------------------------------

    def test_iterable_of_names_still_defines_symbols(self):
        out, warnings = _run(
            ">>IF DEBUG IS DEFINED\nDISPLAY 'D'.\n>>END-IF\n", ["DEBUG"]
        )
        assert "DISPLAY 'D'." in out
        assert warnings == []

    def test_bool_symbol_values(self):
        out, warnings = _run(
            ">>IF FLAG = TRUE\nDISPLAY 'ON'.\n>>END-IF\n", {"FLAG": True}
        )
        assert "ON" in out
        assert warnings == []

    def test_define_as_value_used_in_comparison(self):
        source = (
            ">>DEFINE DEBUGLEVEL AS 5\n"
            ">>IF DEBUGLEVEL > 3\n"
            "DISPLAY 'HIGH'.\n"
            ">>END-IF\n"
        )
        out, warnings = _run(source)
        assert "HIGH" in out
        assert warnings == []

    # -- end-to-end through parse_cobol_with_expansion -------------------------

    def test_end_to_end_parse_cobol_with_expansion(self):
        source = (
            "IDENTIFICATION DIVISION.\n"
            "PROGRAM-ID. M10TEST.\n"
            "PROCEDURE DIVISION.\n"
            "MAIN-PARA.\n"
            ">>IF DEBUGLEVEL > 3\n"
            "    DISPLAY 'DEBUG BUILD'.\n"
            ">>ELSE\n"
            "    DISPLAY 'RELEASE BUILD'.\n"
            ">>END-IF\n"
            "    STOP RUN.\n"
        )
        result = parse_cobol_with_expansion(
            source,
            filename="m10test.cbl",
            copybook_paths=[],
            process_conditionals=True,
            defined_symbols={"DEBUGLEVEL": "5"},
            free_form=True,
        )
        assert result.ast is not None
        displays = result.ast.find_all_by_type("DisplayStatement")
        texts = str([d.to_dict() for d in displays])
        assert "DEBUG BUILD" in texts
        assert "RELEASE BUILD" not in texts
