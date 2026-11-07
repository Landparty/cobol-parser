"""Regression tests: DATA DIVISION defects found by the 2026-09-28 bug hunt.

1. Bare ``NATIONAL`` / ``DISPLAY-1`` / ``UTF-8`` usage words (the USAGE
   keyword is optional): ``PIC N(5) NATIONAL`` glued the word onto the
   picture (``N(5)NATIONAL``, sized 3 bytes), ``DISPLAY-1`` and
   ``IS NATIONAL`` were dropped with "Unparsed token" warnings.
2. National data: a ``PIC N`` item with no USAGE clause reported
   ``usage == "DISPLAY"`` (IBM: implicitly NATIONAL); ``PIC 9(5) USAGE
   NATIONAL`` was sized 5 bytes instead of 10; national-edited ``N(2)BN``
   was sized 4 (not 8) and classified numeric-edited; ``GROUP-USAGE
   NATIONAL`` was dropped, leaving its children DISPLAY.
3. ``OCCURS ... DEPENDING ON CNT OF CTL``: the qualifier stopped the OCCURS
   walk, so every ASCENDING/DESCENDING KEY and INDEXED BY after it was
   dropped.
4. ``USAGE PROCEDURE-POINTER`` is 8 bytes on IBM Enterprise COBOL (was 4);
   ``USAGE OBJECT REFERENCE`` is a 4-byte address (was 0).
"""

from cobolparser import parse_cobol
from cobolparser._storage import storage_size
from cobolparser.generators.data import (
    CopybookDataGenerator,
    DataGeneratorOptions,
    EncodingOptions,
    RecordDecoder,
)
from cobolparser.generators.data.layout_offsets import compute_program_data_items

HEADER = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. REG0928.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
"""

FOOTER = """\
       PROCEDURE DIVISION.
       MAIN-PARA.
           STOP RUN.
"""


def _parse(ws_source: str):
    result = parse_cobol(HEADER + ws_source + FOOTER, filename="reg0928.cbl")
    assert result.success, result.errors
    return result


def _item(result, name: str):
    for item in result.ast.find_all_by_type("DataItem"):
        if item.name == name:
            return item
    raise AssertionError(f"no data item {name}")


class TestBareUsageWords:
    def test_bare_national_is_the_usage_not_part_of_the_picture(self):
        result = _parse(
            "       01  REC.\n"
            "           05  A  PIC N(5) NATIONAL.\n"
            "           05  B  PIC 9(5) NATIONAL VALUE 12.\n"
        )
        assert result.warnings == []
        a = _item(result, "A")
        assert a.picture_clause.pattern == "N(5)"
        assert a.usage == "NATIONAL"
        assert a.calculate_size() == 10
        b = _item(result, "B")
        assert b.picture_clause.pattern == "9(5)"
        assert b.usage == "NATIONAL"
        assert b.value_clause == "12"

    def test_bare_display_1_and_is_national(self):
        result = _parse(
            "       01  REC.\n"
            "           05  G1  PIC G(5) DISPLAY-1.\n"
            "           05  N1  PIC 9(4) IS NATIONAL.\n"
        )
        assert result.warnings == []
        assert _item(result, "G1").usage == "DISPLAY-1"
        assert _item(result, "N1").usage == "NATIONAL"

    def test_bare_utf8(self):
        result = _parse("       01  U1  PIC U(4) UTF-8.\n")
        assert result.warnings == []
        u1 = _item(result, "U1")
        assert u1.picture_clause.pattern == "U(4)"
        assert u1.usage == "UTF-8"


class TestNationalData:
    def test_pic_n_implies_usage_national(self):
        result = _parse(
            "       01  REC.\n"
            "           05  A  PIC N(5).\n"
            "           05  B  PIC NNN.\n"
            "           05  C  PIC X(3).\n"
            "           05  D  PIC G(2).\n"
        )
        a = _item(result, "A")
        assert a.usage == "NATIONAL"
        assert a.usage_explicit is False
        assert a.calculate_size() == 10
        assert a.to_dict()["usage"] == "NATIONAL"
        assert _item(result, "B").usage == "NATIONAL"
        assert _item(result, "C").usage == "DISPLAY"
        assert _item(result, "D").usage == "DISPLAY-1"

    def test_explicit_usage_on_pic_n_still_wins(self):
        result = _parse("       01  A  PIC N(4) USAGE DISPLAY-1.\n")
        assert _item(result, "A").usage == "DISPLAY-1"

    def test_numeric_national_is_two_bytes_per_position(self):
        result = _parse(
            "       01  REC.\n"
            "           05  A  PIC 9(5) USAGE NATIONAL.\n"
            "           05  B  PIC S9(3) NATIONAL SIGN LEADING SEPARATE.\n"
            "           05  C  PIC ZZ9.99 USAGE NATIONAL.\n"
        )
        assert _item(result, "A").calculate_size() == 10
        assert _item(result, "B").calculate_size() == 8
        assert _item(result, "C").calculate_size() == 12
        assert _item(result, "REC").calculate_size() == 30

    def test_national_edited_picture(self):
        result = _parse("       01  A  PIC N(2)BN.\n")
        pic = _item(result, "A").picture_clause
        assert pic.size == 8
        assert pic.is_national_edited
        assert not pic.is_numeric_edited
        assert _item(result, "A").usage == "NATIONAL"

    def test_group_usage_national(self):
        result = _parse(
            "       01  GRP GROUP-USAGE IS NATIONAL.\n"
            "           05  GA  PIC N(3).\n"
            "           05  GB  PIC 9(3).\n"
        )
        assert result.warnings == []
        grp = _item(result, "GRP")
        assert grp.group_usage == "NATIONAL"
        assert grp.to_dict()["group_usage"] == "NATIONAL"
        assert _item(result, "GB").usage == "NATIONAL"
        assert _item(result, "GB").calculate_size() == 6
        assert grp.calculate_size() == 12

    def test_storage_size_national(self):
        assert storage_size("NATIONAL", picture_size=5, total_digits=5) == 10
        assert (
            storage_size(
                "NATIONAL", picture_size=10, total_digits=None, national_picture=True
            )
            == 10
        )

    def test_layout_offsets_and_record_image_agree(self):
        source = (
            HEADER + "       01  REC.\n"
            "           05  A  PIC 9(5) USAGE NATIONAL.\n"
            "           05  B  PIC X(2).\n" + FOOTER
        )
        ast = parse_cobol(source).ast
        rows = {r["name"]: r for r in compute_program_data_items(ast)["items"]}
        assert rows["A"]["byte_length"] == 10
        assert rows["B"]["byte_offset"] == 10

        copybook = (
            "       01  REC.\n"
            "           05  A  PIC 9(5) USAGE NATIONAL.\n"
            "           05  B  PIC X(2).\n"
        )
        opts = DataGeneratorOptions(rows=3, seed=7).for_record_image()
        dataset = CopybookDataGenerator(opts).generate_from_source(copybook)
        assert dataset.record_length() == 12
        image = dataset.to_records(EncodingOptions())
        assert len(image) == 36
        decoded = RecordDecoder.from_copybook_source(copybook).decode_bytes(image)
        assert decoded.error_count == 0
        assert [r.values()["A"] for r in decoded.records] == [
            row[0] for row in dataset.rows
        ]


class TestOccursQualifiedDependingOn:
    SOURCE = (
        "       01  REC.\n"
        "           05  TBL OCCURS 1 TO 10 TIMES DEPENDING ON CNT OF CTL\n"
        "                   ASCENDING KEY IS K1 OF TBL K2\n"
        "                   DESCENDING K3\n"
        "                   INDEXED BY IX1 IX2.\n"
        "               10  K1   PIC X.\n"
        "               10  K2   PIC X.\n"
        "               10  K3   PIC X.\n"
        "       01  CTL.\n"
        "           05  CNT      PIC 9(2).\n"
    )

    def test_keys_and_indexes_survive_a_qualified_counter(self):
        result = _parse(self.SOURCE)
        assert result.warnings == []
        occurs = _item(result, "TBL").occurs_clause
        assert occurs.depending_on == "CNT"
        assert occurs.depending_on_qualifiers == ["CTL"]
        assert occurs.max_times == 10
        assert occurs.key_clauses == [
            {"direction": "ASCENDING", "keys": ["K1", "K2"]},
            {"direction": "DESCENDING", "keys": ["K3"]},
        ]
        assert occurs.index_names == ["IX1", "IX2"]
        assert occurs.to_dict()["depending_on_qualifiers"] == ["CTL"]

    def test_unqualified_counter_serializes_no_qualifiers(self):
        result = _parse(
            "       01  REC.\n"
            "           05  N  PIC 9.\n"
            "           05  T  PIC X OCCURS 1 TO 5 DEPENDING ON N\n"
            "                  INDEXED BY TX.\n"
        )
        occurs = _item(result, "T").occurs_clause
        assert occurs.depending_on_qualifiers == []
        assert "depending_on_qualifiers" not in occurs.to_dict()
        assert occurs.index_names == ["TX"]


class TestAddressUsageSizes:
    def test_procedure_pointer_is_a_doubleword(self):
        result = _parse(
            "       01  REC.\n"
            "           05  P1  USAGE PROCEDURE-POINTER.\n"
            "           05  P2  USAGE FUNCTION-POINTER.\n"
            "           05  P3  USAGE POINTER.\n"
            "           05  P4  USAGE OBJECT REFERENCE.\n"
        )
        assert _item(result, "P1").calculate_size() == 8
        assert _item(result, "P2").calculate_size() == 4
        assert _item(result, "P3").calculate_size() == 4
        assert _item(result, "P4").calculate_size() == 4
        assert _item(result, "REC").calculate_size() == 20
