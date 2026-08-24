"""SET operands must fold OF/IN qualifier chains, like MOVE/arithmetic do.

Before the fix, SET was the one qualifier-folding straggler of the corpus
series that routed MOVE and the arithmetic verbs through
``consume_optional_qualifiers``:

* a qualified *value* (``SET WS-IDX TO WS-VAL OF WS-CTL``) recorded the bare
  ``WS-VAL`` and stranded ``OF WS-CTL`` in the stream, dropped as
  "Unparsed tokens";
* a qualified *target* (``SET FLAG-ON OF WS-REC TO TRUE``) silently
  recorded TWO targets (``FLAG-ON`` and ``WS-REC``) with the ``OF``
  discarded -- no warning at all.
"""

from cobolparser import parse_cobol


def _parse_clean(source: str):
    result = parse_cobol(source, filename="SETQ.cbl")
    assert result.success, result.errors
    assert not result.warnings, result.warnings
    return result.ast


def _single_set(ast):
    sets = ast.find_all_by_type("SetStatement")
    assert len(sets) == 1
    return sets[0]


class TestSetQualifiedValue:
    def test_to_value_with_of_qualifier(self):
        ast = _parse_clean("""       IDENTIFICATION DIVISION.
       PROGRAM-ID. SETQV.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-CTL.
           05  WS-VAL PIC 9(4) VALUE 7.
       01  WS-IDX PIC 9(4).
       PROCEDURE DIVISION.
       MAIN-PARA.
           SET WS-IDX TO WS-VAL OF WS-CTL
           STOP RUN.
""")
        stmt = _single_set(ast)
        assert stmt.value == "WS-VAL OF WS-CTL"
        assert stmt.targets == ["WS-IDX"]

    def test_up_by_value_with_in_qualifier_chain(self):
        ast = _parse_clean("""       IDENTIFICATION DIVISION.
       PROGRAM-ID. SETQU.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  GROUP-A.
           05  GROUP-B.
               10  WS-STEP PIC 9(4) VALUE 2.
       01  WS-IDX PIC 9(4).
       PROCEDURE DIVISION.
       MAIN-PARA.
           SET WS-IDX UP BY WS-STEP IN GROUP-B IN GROUP-A
           STOP RUN.
""")
        stmt = _single_set(ast)
        assert stmt.set_type == "UP_BY"
        assert stmt.value == "WS-STEP IN GROUP-B IN GROUP-A"

    def test_qualified_value_with_subscript(self):
        ast = _parse_clean("""       IDENTIFICATION DIVISION.
       PROGRAM-ID. SETQS.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-CTL.
           05  WS-TAB OCCURS 5 TIMES PIC 9(4).
       01  WS-IDX PIC 9(4).
       PROCEDURE DIVISION.
       MAIN-PARA.
           SET WS-IDX TO WS-TAB OF WS-CTL (3)
           STOP RUN.
""")
        stmt = _single_set(ast)
        assert stmt.value == "WS-TAB OF WS-CTL ( 3 )"

    def test_signed_value_still_recomposed(self):
        ast = _parse_clean("""       IDENTIFICATION DIVISION.
       PROGRAM-ID. SETSN.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-IDX PIC S9(4).
       PROCEDURE DIVISION.
       MAIN-PARA.
           SET WS-IDX DOWN BY -1
           STOP RUN.
""")
        stmt = _single_set(ast)
        assert stmt.set_type == "DOWN_BY"
        assert stmt.value == "-1"


class TestSetQualifiedTarget:
    def test_condition_name_target_with_of_qualifier(self):
        ast = _parse_clean("""       IDENTIFICATION DIVISION.
       PROGRAM-ID. SETQT.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-REC.
           05  WS-FLAG PIC X VALUE 'N'.
               88  FLAG-ON VALUE 'Y'.
       PROCEDURE DIVISION.
       MAIN-PARA.
           SET FLAG-ON OF WS-REC TO TRUE
           STOP RUN.
""")
        stmt = _single_set(ast)
        # Previously two spurious targets: ["FLAG-ON", "WS-REC"].
        assert stmt.targets == ["FLAG-ON OF WS-REC"]
        assert stmt.set_type == "TRUE"

    def test_multiple_targets_one_qualified(self):
        ast = _parse_clean("""       IDENTIFICATION DIVISION.
       PROGRAM-ID. SETQT2.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-REC.
           05  WS-IX1 PIC 9(4).
       01  WS-IX2 PIC 9(4).
       PROCEDURE DIVISION.
       MAIN-PARA.
           SET WS-IX1 OF WS-REC WS-IX2 TO 5
           STOP RUN.
""")
        stmt = _single_set(ast)
        assert stmt.targets == ["WS-IX1 OF WS-REC", "WS-IX2"]
        assert stmt.value == "5"

    def test_address_of_form_unchanged(self):
        ast = _parse_clean("""       IDENTIFICATION DIVISION.
       PROGRAM-ID. SETADDR.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-BUF PIC X(8).
       LINKAGE SECTION.
       01  LNK-PTR USAGE POINTER.
       PROCEDURE DIVISION.
       MAIN-PARA.
           SET LNK-PTR TO ADDRESS OF WS-BUF
           STOP RUN.
""")
        stmt = _single_set(ast)
        assert stmt.value == "WS-BUF"
        assert stmt.value_is_address_of is True
