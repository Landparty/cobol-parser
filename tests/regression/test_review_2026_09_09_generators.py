"""Regression tests for the 2026-09-09 generators / gen-fixtures review.

One test class per finding, in the review's own numbering:

 1. signed numeric literals in conditions were dropped by the solver
 2. ConstantFolder kept stale child values across group-level writes
 3. ConstantFolder kept values through READ/ACCEPT/SQL/STRING/UNSTRING/refmod
 4. wrong storage size for PIC N(n) / G(n) / P-scaled pictures
 5. floating-insertion pictures counted one digit too many
 6. level-88 ``VALUE -9 THRU -1`` lost its range
 7. ConstantFolder ignored REDEFINES aliasing and JUSTIFIED RIGHT
 8. ``VALUE ALL 'x'`` rendered as the text ``ALL``
 9. ``COMPUTE 2 ** 3 ** 2`` folded right-associatively
10. ``domains.solve()`` returned a truncated text witness as satisfying
11. a CALL argument read only inside a condition looked unread
"""

from __future__ import annotations

from cobolparser import parse_cobol
from cobolparser.analysis.boundary_inventory import BoundaryInventoryAnalyzer
from cobolparser.analysis.const_fold import ConstantFolder
from cobolparser.analysis.constraints import ConstraintExtractor, FieldConstraint
from cobolparser.analysis.domains import Unsatisfiable, Witness, solve
from cobolparser.generators import (
    Charset,
    CopybookDataGenerator,
    DataGeneratorOptions,
    EncodingOptions,
    ProgramLayoutIndex,
    RecordDecoder,
)
from cobolparser.generators.data.copybook import parse_copybook_records
from cobolparser.generators.data.layout import expand_condition_values, flatten_record
from cobolparser.models.ast_base import SourceLocation
from cobolparser.models.data_items import ConditionNameItem, PictureClause

_PROGRAM_HEAD = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. REVIEW.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-FILE ASSIGN TO 'IN' FILE STATUS IS WS-FS.
       DATA DIVISION.
       FILE SECTION.
       FD  IN-FILE.
       01  IN-REC.
           05 IN-CODE     PIC X(3).
           05 IN-NUM      PIC S9(3).
           05 IN-SN       PIC S9(2).
              88 CV-NEG   VALUE -9 THRU -1.
           05 IN-X1       PIC X.
       WORKING-STORAGE SECTION.
       01  WS-FS          PIC XX.
       01  WS-GRP.
           05 WS-A        PIC 9(3).
           05 WS-B        PIC X(3).
       01  WS-GRP2.
           05 WS-C        PIC 9(3).
           05 WS-D        PIC X(3).
       01  WS-J           PIC X(3) JUSTIFIED RIGHT.
       01  WS-R           PIC X(3).
       01  WS-RR REDEFINES WS-R PIC 9(3).
       01  WS-G           PIC X(3).
       01  WS-EOF         PIC X VALUE 'N'.
       PROCEDURE DIVISION.
       MAIN.
"""


def _parse(procedure: str):
    result = parse_cobol(_PROGRAM_HEAD + procedure, filename="review.cbl")
    assert result.ast is not None, result.errors
    return result.ast


def _fold(procedure: str, seeds: dict[str, str] | None = None) -> dict[str, str]:
    ast = _parse(procedure)
    index = ProgramLayoutIndex.build(ast)
    return ConstantFolder().fold(ast, index, seed_values=seeds or {}).known


def _constraints(procedure: str):
    ast = _parse(procedure)
    index = ProgramLayoutIndex.build(ast)
    boundaries = BoundaryInventoryAnalyzer().analyze(ast, index)
    return ConstraintExtractor().extract(ast, index, boundaries)


def _arm_values(report, arm_prefix: str):
    return [
        (c.op, c.values)
        for branch in report.branches
        for arm, constraints in branch.arms.items()
        if arm.startswith(arm_prefix)
        for c in constraints
    ]


class TestFinding1SignedLiterals:
    def test_if_against_negative_literal_stores_and_solves_the_sign(self):
        report = _constraints(
            "           READ IN-FILE\n"
            "           IF IN-NUM = -5\n"
            "               DISPLAY 'T'\n"
            "           END-IF\n"
            "           STOP RUN.\n"
        )
        assert _arm_values(report, "THEN") == [("eq", ("-5",))]
        (branch,) = report.branches
        witness = solve(branch.arms["THEN"][0].field.spec, branch.arms["THEN"])
        assert isinstance(witness, Witness) and witness.value == "-5"

    def test_evaluate_when_negative_literal_and_range(self):
        report = _constraints(
            "           READ IN-FILE\n"
            "           EVALUATE IN-SN\n"
            "              WHEN -5 DISPLAY 'A'\n"
            "              WHEN -9 THRU -6 DISPLAY 'B'\n"
            "           END-EVALUATE\n"
            "           EVALUATE TRUE\n"
            "              WHEN IN-SN < -3 DISPLAY 'D'\n"
            "           END-EVALUATE\n"
            "           STOP RUN.\n"
        )
        assert _arm_values(report, "WHEN_1") == [("eq", ("-5",)), ("lt", ("-3",))]
        assert _arm_values(report, "WHEN_2") == [("ge", ("-9",)), ("le", ("-6",))]
        for branch in report.branches:
            for constraints in branch.arms.values():
                witness = solve(constraints[0].field.spec, constraints)
                assert isinstance(witness, Witness), witness
                assert int(witness.value) < 0

    def test_a_literal_the_numeric_field_cannot_hold_is_unsatisfiable(self):
        report = _constraints(
            "           READ IN-FILE\n"
            "           IF IN-NUM = 'X'\n"
            "               DISPLAY 'T'\n"
            "           END-IF\n"
            "           STOP RUN.\n"
        )
        (branch,) = report.branches
        result = solve(branch.arms["THEN"][0].field.spec, branch.arms["THEN"])
        assert isinstance(result, Unsatisfiable)
        assert "'X'" in result.reason


class TestFinding2GroupLevelWrites:
    def test_move_to_group_forgets_child(self):
        assert (
            _fold(
                "           MOVE 5 TO WS-A\n"
                "           MOVE SPACES TO WS-GRP\n"
                "           DISPLAY WS-A\n"
                "           STOP RUN.\n"
            )
            == {}
        )

    def test_group_to_group_move_initialize_and_corr_forget_children(self):
        for stmt in (
            "MOVE WS-GRP TO WS-GRP2",
            "INITIALIZE WS-GRP2",
            "MOVE CORRESPONDING WS-GRP TO WS-GRP2",
            "CALL 'SUB' USING WS-GRP2",
        ):
            known = _fold(
                f"           MOVE 5 TO WS-C\n           {stmt}\n"
                "           DISPLAY WS-C\n           STOP RUN.\n"
            )
            assert known == {}, stmt

    def test_sibling_group_is_untouched(self):
        assert _fold(
            "           MOVE 5 TO WS-C\n"
            "           MOVE SPACES TO WS-GRP\n"
            "           DISPLAY WS-C\n"
            "           STOP RUN.\n"
        ) == {"WS-GRP2.WS-C": "5"}


class TestFinding3OverwritingStatements:
    def test_read_overwrites_record_fields_and_into_target(self):
        assert (
            _fold(
                "           MOVE 'ABC' TO IN-CODE\n"
                "           MOVE 5 TO WS-A\n"
                "           READ IN-FILE INTO WS-GRP\n"
                "           DISPLAY IN-CODE WS-A\n"
                "           STOP RUN.\n"
            )
            == {}
        )

    def test_first_read_reseeds_the_record_from_the_scenario_inputs(self):
        known = _fold(
            "           MOVE 'ABC' TO IN-CODE\n"
            "           READ IN-FILE\n"
            "           DISPLAY IN-CODE\n"
            "           STOP RUN.\n",
            seeds={"IN-CODE": "XYZ"},
        )
        assert known == {"IN-REC.IN-CODE": "XYZ"}

    def test_second_read_of_the_same_file_poisons_the_seed(self):
        known = _fold(
            "           READ IN-FILE\n"
            "           READ IN-FILE\n"
            "           DISPLAY IN-CODE\n"
            "           STOP RUN.\n",
            seeds={"IN-CODE": "XYZ"},
        )
        assert known == {}

    def test_accept_sql_string_unstring_and_refmod_overwrite(self):
        cases = {
            "ACCEPT WS-A": "WS-A",
            "ACCEPT WS-GRP": "WS-A",
            "EXEC SQL SELECT C INTO :WS-A FROM T END-EXEC": "WS-A",
            "STRING 'X' DELIMITED SIZE INTO WS-B": "WS-B",
            "UNSTRING WS-D DELIMITED BY ' ' INTO WS-B": "WS-B",
            "MOVE 'Z' TO WS-B(1:1)": "WS-B",
        }
        for stmt, shown in cases.items():
            known = _fold(
                "           MOVE 5 TO WS-A\n"
                "           MOVE 'ABC' TO WS-B\n"
                f"           {stmt}\n"
                f"           DISPLAY {shown}\n"
                "           STOP RUN.\n"
            )
            assert known == {}, (stmt, known)

    def test_seeded_accept_still_survives_its_own_statement(self):
        known = _fold(
            "           ACCEPT WS-A\n"
            "           ADD 1 TO WS-A\n"
            "           DISPLAY WS-A\n"
            "           STOP RUN.\n",
            seeds={"WS-A": "10"},
        )
        assert known == {"WS-GRP.WS-A": "11"}


_SIZES_CPY = """\
       01  REC.
           05 A-N        PIC N(5).
           05 A-G        PIC G(5) USAGE DISPLAY-1.
           05 A-PPP      PIC 9(3)PPP.
           05 A-VPP      PIC SVPP9(3).
           05 A-PP3      PIC S9(3)PPP COMP-3.
           05 A-X        PIC X.
"""


class TestFinding4StorageSizes:
    def test_picture_clause_sizes(self):
        loc = SourceLocation(1, 1)
        assert PictureClause("N(5)", loc).size == 10
        assert PictureClause("G(5)", loc).size == 10
        ppp = PictureClause("9(3)PPP", loc)
        assert (ppp.size, ppp.integer_digits, ppp.decimal_digits) == (3, 6, 0)
        assert ppp.scaling_factor == 3
        vpp = PictureClause("SVPP9(3)", loc)
        assert (vpp.size, vpp.integer_digits, vpp.decimal_digits) == (3, 0, 5)
        assert vpp.is_signed

    def test_layout_and_storage_follow(self):
        (record,) = parse_copybook_records(_SIZES_CPY)
        opts = DataGeneratorOptions(rows=5, seed=3).for_record_image()
        by_name = {spec.name: spec for spec in flatten_record(record, opts)}
        assert by_name["A-N"].storage_size == 10
        assert by_name["A-G"].storage_size == 10
        assert by_name["A-PPP"].storage_size == 3
        assert by_name["A-VPP"].storage_size == 3
        assert by_name["A-PP3"].storage_size == 2  # three digits packed
        assert record.calculate_size() == 10 + 10 + 3 + 3 + 2 + 1

    def test_generated_values_are_representable_and_round_trip(self):
        (record,) = parse_copybook_records(_SIZES_CPY)
        opts = DataGeneratorOptions(rows=8, seed=3).for_record_image()
        dataset = CopybookDataGenerator(opts).generate_from_record(record)
        header = dataset.header
        for row in dataset.rows:
            assert int(row[header.index("A-PPP")]) % 1000 == 0
            assert abs(float(row[header.index("A-VPP")])) < 0.01
        for charset in (Charset.ASCII, Charset.EBCDIC):
            enc = EncodingOptions(charset=charset)
            decoded = RecordDecoder.from_record(record, opts=enc, options=opts)
            result = decoded.decode_bytes(dataset.to_records(enc))
            assert len(result.records) == len(dataset.rows)
            assert result.error_count == 0
            for rec, row in zip(result.records, dataset.rows, strict=True):
                assert list(rec.values().values()) == row


class TestFinding5FloatingInsertion:
    def test_floating_string_leftmost_symbol_is_not_a_digit(self):
        loc = SourceLocation(1, 1)
        assert PictureClause("$$$,$$9", loc).integer_digits == 5
        assert PictureClause("$Z,ZZ9", loc).integer_digits == 4
        assert PictureClause("++++9", loc).integer_digits == 4
        assert PictureClause("--,--9.99", loc).decimal_digits == 2
        assert PictureClause("-9(5)", loc).integer_digits == 5

    def test_generated_values_fit_the_edited_picture(self):
        (record,) = parse_copybook_records(
            "       01  REC.\n"
            "           05 IN-ED       PIC $$$,$$9.\n"
            "           05 IN-ED4      PIC $Z,ZZ9.\n"
        )
        dataset = CopybookDataGenerator(
            DataGeneratorOptions(rows=30, seed=5)
        ).generate_from_record(record)
        for row in dataset.rows:
            assert abs(float(row[0])) <= 99999
            assert abs(float(row[1])) <= 9999


class TestFinding6SignedThruRange:
    def test_value_minus_9_thru_minus_1_expands_the_whole_range(self):
        ast = _parse("           STOP RUN.\n")
        conditions = [
            child
            for item in ast.find_all_by_type("DataItem")
            for child in item.children
            if isinstance(child, ConditionNameItem) and child.name == "CV-NEG"
        ]
        (cv_neg,) = conditions
        assert cv_neg.values == ["-9", "THROUGH:-1"]
        assert expand_condition_values(cv_neg.values) == [str(n) for n in range(-9, 0)]


class TestFinding7RedefinesAndJustified:
    def test_write_through_redefines_alias_forgets_the_redefined_item(self):
        assert (
            _fold(
                "           MOVE 'ABC' TO WS-R\n"
                "           MOVE 123 TO WS-RR\n"
                "           DISPLAY WS-R\n"
                "           STOP RUN.\n"
            )
            == {}
        )
        assert (
            _fold(
                "           MOVE 123 TO WS-RR\n"
                "           MOVE 'ABC' TO WS-R\n"
                "           DISPLAY WS-RR\n"
                "           STOP RUN.\n"
            )
            == {}
        )

    def test_justified_right_keeps_the_rightmost_characters(self):
        assert _fold(
            "           MOVE 'ABCDE' TO WS-J\n           DISPLAY WS-J\n           STOP RUN.\n"
        ) == {"WS-J": "CDE"}
        # A short value is left-padded by the compiler, which the folder
        # does not model: absent, never wrong.
        assert (
            _fold(
                "           MOVE 'AB' TO WS-J\n           DISPLAY WS-J\n           STOP RUN.\n"
            )
            == {}
        )


class TestFinding8ValueAll:
    def test_value_all_literal_fills_the_field(self):
        (record,) = parse_copybook_records(
            "       01  REC.\n"
            "           05 AV        PIC X(4) VALUE ALL '-'.\n"
            "           05 BV        PIC X(5) VALUE ALL 'AB'.\n"
            "           05 SV        PIC X(2) VALUE ALL SPACES.\n"
        )
        dataset = CopybookDataGenerator(
            DataGeneratorOptions(rows=2, seed=1)
        ).generate_from_record(record)
        assert [row[:2] for row in dataset.rows] == [["----", "ABABA"]] * 2
        assert all(row[2] != "ALL" for row in dataset.rows)


class TestFinding9PowerAssociativity:
    def test_exponentiation_chains_fold_left_to_right(self):
        assert _fold(
            "           COMPUTE WS-A = 2 ** 3 ** 2\n"
            "           DISPLAY WS-A\n"
            "           STOP RUN.\n"
        ) == {"WS-GRP.WS-A": "64"}
        assert _fold(
            "           COMPUTE WS-A = 2 ** (3 ** 2)\n"
            "           DISPLAY WS-A\n"
            "           STOP RUN.\n"
        ) == {"WS-GRP.WS-A": "512"}
        assert _fold(
            "           COMPUTE WS-A = 100 * 2 ** -1\n"
            "           DISPLAY WS-A\n"
            "           STOP RUN.\n"
        ) == {"WS-GRP.WS-A": "50"}

    def test_unary_minus_applies_before_exponentiation(self):
        # IBM hierarchy: unary sign first, then **: (-2) ** 2 + 10 == 14.
        # Read as -(2 ** 2) this folded to 6.
        assert _fold(
            "           COMPUTE WS-A = - 2 ** 2 + 10\n"
            "           DISPLAY WS-A\n"
            "           STOP RUN.\n"
        ) == {"WS-GRP.WS-A": "14"}


class TestFinding10TruncatedTextWitness:
    def test_literal_wider_than_the_field_is_unsatisfiable(self):
        report = _constraints(
            "           READ IN-FILE\n"
            "           IF IN-X1 = 'AB'\n"
            "               DISPLAY 'T'\n"
            "           END-IF\n"
            "           STOP RUN.\n"
        )
        (branch,) = report.branches
        spec = branch.arms["THEN"][0].field.spec
        result = solve(spec, branch.arms["THEN"])
        assert isinstance(result, Unsatisfiable)
        assert "does not fit" in result.reason
        # The negated arm is still satisfiable, and a fitting literal still solves.
        assert isinstance(solve(spec, branch.arms["ELSE"]), Witness)
        fits = FieldConstraint(branch.arms["THEN"][0].field, "eq", ("A",), "t")
        assert solve(spec, [fits]) == Witness("A")


class TestFinding11ConditionReadsCallArgument:
    def test_argument_read_only_in_a_condition_is_in(self):
        ast = _parse(
            "           CALL 'SUB5' USING WS-G\n"
            "           IF WS-G = 'Y'\n"
            "              DISPLAY 'Y'\n"
            "           END-IF\n"
            "           CALL 'SUB6' USING WS-D\n"
            "           PERFORM UNTIL WS-D = 'Q'\n"
            "              MOVE 'Q' TO WS-D\n"
            "           END-PERFORM\n"
            "           CALL 'SUB7' USING WS-C\n"
            "           EVALUATE WS-C\n"
            "              WHEN 1 DISPLAY 'ONE'\n"
            "           END-EVALUATE\n"
            "           STOP RUN.\n"
        )
        index = ProgramLayoutIndex.build(ast)
        report = BoundaryInventoryAnalyzer().analyze(ast, index)
        by_key = {b.ref.key: b for b in report.boundaries if b.ref.category == "CALL"}
        for key in ("SUB5", "SUB6", "SUB7"):
            (arg,) = by_key[key].call_args
            assert (arg.direction, arg.provenance) == ("IN", "caller-dataflow"), key
