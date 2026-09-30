"""Bug hunt round 11: lexer / parser / statement parser regressions.

Each test reproduces a defect through the public API first; see the
docstrings for the pre-fix behaviour.
"""

from cobolparser import UnusedVariableAnalyzer, parse_cobol
from cobolparser.analysis.program_flow import ProgramFlowAnalyzer
from cobolparser.parser import _detect_fixed_format

_FILE_HDR = """IDENTIFICATION DIVISION.
PROGRAM-ID. T.
ENVIRONMENT DIVISION.
INPUT-OUTPUT SECTION.
FILE-CONTROL.
    SELECT F ASSIGN TO "F" ORGANIZATION INDEXED RECORD KEY FK
        ACCESS DYNAMIC.
DATA DIVISION.
FILE SECTION.
FD F.
01 FR.
   05 FK PIC X(5).
WORKING-STORAGE SECTION.
01 G.
   05 A PIC X(5).
   05 B PIC X(5).
   05 N PIC 99.
PROCEDURE DIVISION.
P1.
"""


def _free(body: str):
    return parse_cobol(_FILE_HDR + body, free_form=True)


def _paragraph(result, name):
    for para in result.ast.find_all_by_type("CobolParagraph"):
        if para.to_dict().get("paragraph_name") == name:
            return para
    raise AssertionError(f"no paragraph {name}")


def _paragraph_names(result):
    return [
        p.to_dict().get("paragraph_name")
        for p in result.ast.find_all_by_type("CobolParagraph")
    ]


# -- 1. CURRENCY SIGN IS "<": an operator-shaped currency symbol -------------


def test_operator_currency_symbol_lexes_as_picture_symbol():
    """``PIC <(3),<<<.99`` under ``CURRENCY SIGN IS "<"`` lexed as LESS
    operators: the picture was lost and bogus ANONYMOUS items appeared."""
    src = (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. T.\n"
        "       ENVIRONMENT DIVISION.\n"
        "       CONFIGURATION SECTION.\n"
        "       SPECIAL-NAMES.\n"
        '           CURRENCY SIGN IS "<".\n'
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01 G.\n"
        '          03 FL-LESS PICTURE <(3),<<<.99 VALUE " <1,111.11".\n'
        "          03 NXT PIC X.\n"
        "       PROCEDURE DIVISION.\n"
        '           IF NXT < "A" DISPLAY "Y".\n'
        "           STOP RUN.\n"
    )
    result = parse_cobol(src)
    assert result.errors == [] and result.warnings == []
    items = {i.name: i.to_dict() for i in result.ast.find_all_by_type("CobolDataItem")}
    assert set(items) == {"G", "FL-LESS", "NXT"}
    picture = items["FL-LESS"]["picture_clause"]
    assert picture["pattern"] == "<(3),<<<.99"
    assert picture["metadata"]["currency_symbols"] == ["<"]
    (stmt,) = result.ast.find_all_by_type("IfStatement")
    assert stmt.to_dict()["condition"]["operator"] == "LESS"


# -- 2. fixed-format detection after >>SOURCE FORMAT IS FREE -----------------


def test_detect_fixed_format_samples_only_fixed_region():
    """A sequence-numbered file that switches to free format early was
    classified free-form (the free lines filled the 10-line sample)."""
    src = (
        "000100 IDENTIFICATION DIVISION.\n"
        "000200 PROGRAM-ID. T.\n"
        "000300 >>SOURCE FORMAT IS FREE\n"
        "DATA DIVISION.\n"
        "WORKING-STORAGE SECTION.\n"
        "01 A PIC X(3).\n"
        "PROCEDURE DIVISION.\n"
        "MAIN.\n"
        '    MOVE "ABC" TO A\n'
        "    DISPLAY A\n"
        "    STOP RUN.\n"
    )
    assert _detect_fixed_format(src) is True
    result = parse_cobol(src)
    assert result.errors == [] and result.warnings == []
    assert result.ast.program_name == "T"


def test_detect_fixed_format_free_file_opening_with_directive():
    src = (
        "       >>SOURCE FORMAT IS FREE\n"
        "IDENTIFICATION DIVISION.\n"
        "PROGRAM-ID. T.\n"
        "PROCEDURE DIVISION.\n"
        "  STOP RUN.\n"
    )
    assert _detect_fixed_format(src) is False


# -- 3. EVALUATE WHEN condition text keeps literal quotes --------------------


def test_evaluate_condition_selector_keeps_string_quotes():
    """``WHEN A = "B"`` was stored as ``A = B``, so analyzers read the
    literal as the data item B."""
    src = (
        "IDENTIFICATION DIVISION.\n"
        "PROGRAM-ID. T.\n"
        "DATA DIVISION.\n"
        "WORKING-STORAGE SECTION.\n"
        "01 A PIC X.\n"
        "01 B PIC X.\n"
        "PROCEDURE DIVISION.\n"
        "    EVALUATE TRUE\n"
        '      WHEN A = "B" DISPLAY 1\n'
        "      WHEN OTHER DISPLAY 2\n"
        "    END-EVALUATE\n"
        "    STOP RUN.\n"
    )
    result = parse_cobol(src, free_form=True)
    (stmt,) = result.ast.find_all_by_type("EvaluateStatement")
    assert stmt.when_clauses[0].selectors == [{"type": "Condition", "text": "A = 'B'"}]
    unused = [u.name for u in UnusedVariableAnalyzer().analyze(result.ast).unused_items]
    assert unused == ["B"]


# -- 4. qualifiers on SORT/MERGE keys and CANCEL -----------------------------


def test_sort_key_qualifier_kept_and_later_keys_not_lost():
    """``KEY K OF SR`` dropped ``OF SR`` and ended the key list, losing the
    DESCENDING key after it."""
    src = (
        "IDENTIFICATION DIVISION.\n"
        "PROGRAM-ID. T.\n"
        "ENVIRONMENT DIVISION.\n"
        "INPUT-OUTPUT SECTION.\n"
        "FILE-CONTROL.\n"
        '    SELECT SF ASSIGN TO "S".\n'
        '    SELECT IF1 ASSIGN TO "I".\n'
        "DATA DIVISION.\n"
        "FILE SECTION.\n"
        "SD SF.\n"
        "01 SR.\n"
        "   05 K PIC X(3).\n"
        "FD IF1.\n"
        "01 IR PIC X(3).\n"
        "WORKING-STORAGE SECTION.\n"
        "01 G.\n"
        "   05 X PIC X(8).\n"
        "PROCEDURE DIVISION.\n"
        "    SORT SF ON ASCENDING KEY K OF SR DESCENDING K IN SR\n"
        "        USING IF1 GIVING IF1\n"
        "    MERGE SF ON ASCENDING KEY K OF SR USING IF1 IF1 GIVING IF1\n"
        "    CANCEL X OF G\n"
        "    STOP RUN.\n"
    )
    result = parse_cobol(src, free_form=True)
    assert result.errors == [] and result.warnings == []
    (sort,) = result.ast.find_all_by_type("SortStatement")
    assert sort.keys == [
        {"field": "K OF SR", "order": "ASCENDING"},
        {"field": "K IN SR", "order": "DESCENDING"},
    ]
    assert sort.using_files == ["IF1"]
    (merge,) = result.ast.find_all_by_type("MergeStatement")
    assert merge.keys == [{"field": "K OF SR", "order": "ASCENDING"}]
    (cancel,) = result.ast.find_all_by_type("CancelStatement")
    assert cancel.program_names == ["X OF G"]


# -- 5. CALL with a repeated ON EXCEPTION phrase -----------------------------


def test_call_repeated_exception_phrase_keeps_first_handler_and_warns():
    result = _free(
        '    CALL "SUB" ON EXCEPTION DISPLAY "ONE"\n'
        '         ON EXCEPTION DISPLAY "TWO"\n'
        '         NOT ON EXCEPTION DISPLAY "OK"\n'
        "    END-CALL\n"
        "    STOP RUN.\n"
    )
    (call,) = result.ast.find_all_by_type("CallStatement")
    assert [s.display_items for s in call.on_exception] == [['"ONE"'], ['"TWO"']]
    assert len(call.not_on_exception) == 1
    assert any("Duplicate ON EXCEPTION" in w for w in result.warnings)


# -- 6. SELECT clause gaps ---------------------------------------------------


def _select(select_text: str):
    src = (
        "IDENTIFICATION DIVISION.\n"
        "PROGRAM-ID. T.\n"
        "ENVIRONMENT DIVISION.\n"
        "INPUT-OUTPUT SECTION.\n"
        "FILE-CONTROL.\n" + select_text + "DATA DIVISION.\n"
        "FILE SECTION.\n"
        "FD F.\n"
        "01 R PIC X(5).\n"
        "WORKING-STORAGE SECTION.\n"
        "01 STATUS-GROUP.\n"
        "   05 F-STATUS PIC XX.\n"
        "01 F-KEY PIC 9(4).\n"
        "PROCEDURE DIVISION.\n"
        "    STOP RUN.\n"
    )
    result = parse_cobol(src, free_form=True)
    (select,) = result.ast.find_all_by_type("SelectStatement")
    return result, select


def test_select_file_status_qualifier_is_not_a_vsam_status():
    """``FILE STATUS F-STATUS IN STATUS-GROUP`` recorded ``IN`` as the VSAM
    second status variable and dropped STATUS-GROUP (NIST SQ124A)."""
    result, select = _select(
        '    SELECT F ASSIGN TO "F"\n'
        "        FILE STATUS F-STATUS\n"
        "                    IN STATUS-GROUP.\n"
    )
    assert result.warnings == []
    assert select.file_status == "F-STATUS"
    assert select.file_status_vsam is None
    assert select.to_dict()["file_status_qualifiers"] == ["STATUS-GROUP"]


def test_select_relative_key_without_key_word_and_semicolons():
    """``RELATIVE F-KEY`` (KEY omitted, NIST RL112A) and ``;`` clause
    separators (NIST IX202A) were dropped with warnings."""
    result, select = _select(
        '    SELECT F ASSIGN TO "F"\n'
        "        ; ORGANIZATION RELATIVE\n"
        "        ; ACCESS RANDOM\n"
        "        RELATIVE F-KEY.\n"
    )
    assert result.warnings == []
    assert select.organization == "RELATIVE"
    assert select.access_mode == "RANDOM"
    assert select.relative_key == "F-KEY"


# -- 7. STRING/UNSTRING handler ending the sentence --------------------------


def test_string_handler_period_ends_statement_without_warning():
    """A handler statement consuming the period (``ON OVERFLOW GO TO P3.``)
    left STRING/UNSTRING scanning into the next paragraph header, reported
    as a missing-period statement (NIST NC217A)."""
    for stmt in (
        "STRING A DELIMITED SIZE INTO B\n        ON OVERFLOW GO TO P3.",
        "UNSTRING A INTO B\n        ON OVERFLOW GO TO P3\n"
        "        NOT ON OVERFLOW GO TO P3.",
    ):
        result = _free(f"    {stmt}\nP2.\n    DISPLAY 'P2'.\nP3.\n    STOP RUN.\n")
        assert result.errors == [] and result.warnings == [], stmt
        assert _paragraph_names(result)[-3:] == ["P1", "P2", "P3"]


# -- 8. level-88 entries -----------------------------------------------------


def _level88(entry: str):
    src = (
        "IDENTIFICATION DIVISION.\n"
        "PROGRAM-ID. T.\n"
        "DATA DIVISION.\n"
        "WORKING-STORAGE SECTION.\n"
        "01 A PIC X.\n" + entry + "01 B PIC X.\n"
        "PROCEDURE DIVISION.\n"
        "    STOP RUN.\n"
    )
    result = parse_cobol(src, free_form=True)
    item = result.ast.find_all_by_type("CobolDataItem")[0]
    return result, item.to_dict()["condition_names"][0]


def test_level88_false_phrase_without_when_set_to():
    """``88 V VALUE 'A' FALSE 'Z'`` (WHEN SET TO omitted) lost the false
    value silently."""
    result, cond = _level88('   88 V VALUES ARE "A" "B" THRU "D" FALSE "Z".\n')
    assert result.warnings == []
    assert cond["values"] == ["A", "B", "THROUGH:D"]
    assert cond["false_value"] == "Z"


def test_level88_unparsed_tail_is_reported():
    result, cond = _level88('   88 V VALUE "A" FOO BAR.\n')
    assert cond["values"] == ["A"]
    assert any("'FOO'" in w and "condition-name 'V'" in w for w in result.warnings)


# -- 9. computed GO TO keeps repeated targets --------------------------------


def test_goto_depending_on_keeps_positional_duplicates():
    """``GO TO P1 P2 P1 DEPENDING ON N`` deduplicated to [P1, P2]: value 3
    of N then mapped to no target."""
    result = _free("    GO TO P1 P2 P1 DEPENDING ON N OF G.\nP2.\n    STOP RUN.\n")
    (goto,) = result.ast.find_all_by_type("GoStatement")
    assert goto.target_paragraphs == ["P1", "P2", "P1"]
    report = ProgramFlowAnalyzer().analyze(result.ast)
    targets = [
        e.target
        for e in report.edges
        if e.source == "P1" and e.edge_type.name == "GOTO_DEPENDING"
    ]
    assert targets == ["P1", "P2"]


# -- 10. COMPUTE expression tree with qualified operands ---------------------


def test_compute_expression_tree_with_qualified_operands():
    result = _free("    COMPUTE N OF G = N OF G * 2 + LENGTH OF A.\n")
    (stmt,) = result.ast.find_all_by_type("ComputeStatement")
    tree = stmt.to_dict()["expression_tree"]
    assert tree["operator"] == "+"
    assert tree["left_operand"]["left_operand"] == "N OF G"
    assert tree["right_operand"] == "LENGTH OF A"


# -- 11. SECTION segment-number ----------------------------------------------


def test_section_segment_number_is_not_a_paragraph():
    """``S1 SECTION 50.`` created a paragraph named ``50`` (NIST SG101A)."""
    result = parse_cobol(
        "IDENTIFICATION DIVISION.\n"
        "PROGRAM-ID. T.\n"
        "PROCEDURE DIVISION.\n"
        "S1 SECTION 50.\n"
        "P1.\n"
        "    STOP RUN.\n",
        free_form=True,
    )
    assert result.warnings == []
    assert _paragraph_names(result) == ["P1"]


# -- 12. SPECIAL-NAMES SYMBOLIC CHARACTERS followed by CLASS -----------------


def test_symbolic_characters_do_not_swallow_class_clause():
    """``... TAB IS 10 CLASS HEX IS "0" THRU "F"`` recorded CLASS as a
    symbolic character with ordinal 0 and lost the class definition."""
    result = parse_cobol(
        "IDENTIFICATION DIVISION.\n"
        "PROGRAM-ID. T.\n"
        "ENVIRONMENT DIVISION.\n"
        "CONFIGURATION SECTION.\n"
        "SPECIAL-NAMES.\n"
        "    SYMBOLIC CHARACTERS BELL IS 8 TAB IS 10\n"
        '    CLASS HEXCHARS IS "0" THRU "9" "A" THRU "F".\n'
        "PROCEDURE DIVISION.\n"
        "    STOP RUN.\n",
        free_form=True,
    )
    env = result.ast.to_dict()["divisions"]["ENVIRONMENT"]
    names = env["sections"]["CONFIGURATION"]["metadata"]["special_names"]
    assert [s["name"] for s in names["symbolic_characters"]] == ["BELL", "TAB"]
    assert names["class_definitions"] == [
        {"name": "HEXCHARS", "ranges": ["0", "THRU", "9", "A", "THRU", "F"]}
    ]


# -- 13. WRITE ... ADVANCING qualified identifier ----------------------------


def test_write_advancing_qualified_line_count():
    result = _free("    WRITE FR AFTER ADVANCING N OF G LINES\n    STOP RUN.\n")
    assert result.warnings == []
    (write,) = result.ast.find_all_by_type("IOWriteStatement")
    assert write.to_dict()["advancing_clause"] == {
        "type": "AFTER",
        "value": "N OF G",
        "unit": "LINES",
    }
