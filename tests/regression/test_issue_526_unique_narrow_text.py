"""Issue #526: ``gen-data --unique`` wrote duplicate values for a narrow text
field whose values come from a small fixed set (a VALUE clause, level-88s):
after 32 retries the counter fallback ``STAT1`` / ``STAT2`` ... was cut to
``STA`` on a ``PIC X(3)``, so every fallback value was the same, silently. A
misspelt ``--unique`` name was accepted silently too.
"""

from __future__ import annotations

from cobolparser.cli.parse import main
from cobolparser.generators import CopybookDataGenerator, DataGeneratorOptions

COPYBOOK = """\
       01 UREC.
          05 STATUS-CD PIC X(3).
             88 ST-NEW VALUE 'NEW'.
             88 ST-OLD VALUE 'OLD'.
          05 CUST-KEY PIC 9(4).
          05 REGION PIC X(2) VALUE 'NE'.
          05 FLAG PIC 9 VALUE 1.
"""


def _generate(rows: int, *unique: str):
    options = DataGeneratorOptions(rows=rows, seed=1, unique_fields=unique)
    return CopybookDataGenerator(options).generate_from_source(COPYBOOK)


def _column(dataset, name: str) -> list[str]:
    index = dataset.header.index(name)
    return [row[index] for row in dataset.rows]


def test_narrow_text_fields_stay_distinct() -> None:
    dataset = _generate(40, "STATUS-CD", "REGION")
    for name in ("STATUS-CD", "REGION"):
        values = _column(dataset, name)
        assert len(set(values)) == len(values), (name, values)
        assert all(len(v) <= (3 if name == "STATUS-CD" else 2) for v in values)
    assert dataset.caveats == []


def test_exhausted_picture_is_reported() -> None:
    dataset = _generate(12, "FLAG")
    assert len(set(_column(dataset, "FLAG"))) == 10
    assert dataset.caveats == [
        "unique field FLAG repeats a value: its PICTURE cannot hold 12 distinct "
        "values"
    ]


def test_unknown_unique_field_is_reported() -> None:
    dataset = _generate(3, "NOPE")
    assert dataset.caveats == [
        "unique field NOPE matches no generated field of record UREC; ignored"
    ]


def test_cli_warns_on_stderr(tmp_path, capsys, monkeypatch) -> None:
    path = tmp_path / "u2.cpy"
    path.write_text(COPYBOOK)
    monkeypatch.setattr(
        "sys.argv",
        ["cobol-parser", "gen-data", str(path), "--rows", "3", "--unique", "NOPE"],
    )
    main()
    assert "warning: unique field NOPE matches no generated field" in (
        capsys.readouterr().err
    )
