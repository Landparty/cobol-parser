"""Tests for the ``cobol-parser gen-data`` CLI subcommand."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

import pytest

from cobolparser.cli.parse import _build_parser, main

SAMPLES = Path(__file__).parents[2] / "samples"
TXNDATA = str(SAMPLES / "copybooks" / "TXNDATA.cpy")
CUSTOMER = str(SAMPLES / "copybooks" / "CUSTOMER.cpy")


def _run(monkeypatch, *argv: str) -> None:
    monkeypatch.setattr("sys.argv", ["cobol-parser", "gen-data", *argv])
    main()


def _run_argv(argv: list[str]) -> None:
    """Invoke the CLI without monkeypatching, for tests that need several
    invocations in one test body."""
    import sys

    saved = sys.argv
    sys.argv = ["cobol-parser", *argv]
    try:
        main()
    finally:
        sys.argv = saved


def _csv_out(capsys) -> list[list[str]]:
    return list(csv.reader(io.StringIO(capsys.readouterr().out)))


class TestGenDataParser:
    def test_subcommand_is_registered(self):
        args = _build_parser().parse_args(["gen-data", TXNDATA])
        assert args.command == "gen-data"
        assert args.rows == 10

    def test_defaults(self):
        args = _build_parser().parse_args(["gen-data", TXNDATA])
        assert args.seed is None
        assert args.header_style == "short"
        assert not args.include_filler
        assert not args.include_redefines
        assert args.blank_rate == 0.0

    def test_short_flags(self):
        args = _build_parser().parse_args(["gen-data", TXNDATA, "-n", "5"])
        assert args.rows == 5

    def test_repeatable_unique_flag(self):
        args = _build_parser().parse_args(
            ["gen-data", TXNDATA, "--unique", "A", "--unique", "B"]
        )
        assert args.unique == ["A", "B"]


class TestGenDataOutput:
    def test_emits_csv_on_stdout(self, monkeypatch, capsys):
        _run(monkeypatch, CUSTOMER, "--rows", "3", "--seed", "1")
        rows = _csv_out(capsys)
        assert rows[0] == [
            "CUSTOMER-ID",
            "CUSTOMER-NAME",
            "STREET",
            "CITY",
            "STATE",
            "ZIP",
        ]
        assert len(rows) == 4

    def test_output_is_reproducible_for_a_seed(self, monkeypatch, capsys):
        _run(monkeypatch, TXNDATA, "--rows", "6", "--seed", "99")
        first = capsys.readouterr().out
        _run(monkeypatch, TXNDATA, "--rows", "6", "--seed", "99")
        assert capsys.readouterr().out == first

    def test_writes_to_output_file(self, monkeypatch, capsys, tmp_path):
        target = tmp_path / "data.csv"
        _run(monkeypatch, CUSTOMER, "--rows", "4", "--seed", "2", "-o", str(target))
        assert capsys.readouterr().out == ""
        rows = list(csv.reader(target.open(newline="")))
        assert len(rows) == 5

    def test_rows_flag_controls_record_count(self, monkeypatch, capsys):
        _run(monkeypatch, CUSTOMER, "--rows", "17", "--seed", "3")
        assert len(_csv_out(capsys)) == 18

    def test_header_style_path(self, monkeypatch, capsys):
        _run(
            monkeypatch,
            CUSTOMER,
            "--rows",
            "1",
            "--seed",
            "4",
            "--header-style",
            "path",
        )
        assert _csv_out(capsys)[0][0] == "CUSTOMER-RECORD.CUSTOMER-ID"

    def test_include_filler_and_redefines(self, monkeypatch, capsys):
        _run(
            monkeypatch,
            TXNDATA,
            "--rows",
            "1",
            "--seed",
            "5",
            "--include-filler",
            "--include-redefines",
        )
        header = _csv_out(capsys)[0]
        assert "FILLER" in header
        assert "PART-A" in header

    def test_no_expand_occurs(self, monkeypatch, capsys):
        _run(monkeypatch, TXNDATA, "--rows", "1", "--seed", "6", "--no-expand-occurs")
        header = _csv_out(capsys)[0]
        assert "ITEM-CODE(1)" in header
        assert "ITEM-CODE(2)" not in header

    def test_max_occurs(self, monkeypatch, capsys):
        _run(monkeypatch, TXNDATA, "--rows", "1", "--seed", "7", "--max-occurs", "2")
        header = _csv_out(capsys)[0]
        assert "ITEM-CODE(2)" in header
        assert "ITEM-CODE(3)" not in header

    def test_blank_rate_one_blanks_everything(self, monkeypatch, capsys):
        _run(monkeypatch, CUSTOMER, "--rows", "2", "--seed", "8", "--blank-rate", "1.0")
        rows = _csv_out(capsys)
        assert all(cell == "" for row in rows[1:] for cell in row)

    def test_unique_flag_yields_distinct_values(self, monkeypatch, capsys):
        _run(
            monkeypatch,
            TXNDATA,
            "--rows",
            "25",
            "--seed",
            "9",
            "--unique",
            "TXN-ID",
        )
        rows = _csv_out(capsys)
        index = rows[0].index("TXN-ID")
        values = [row[index] for row in rows[1:]]
        assert len(values) == len(set(values))

    def test_ignore_values_widens_the_domain(self, monkeypatch, capsys):
        _run(monkeypatch, TXNDATA, "--rows", "40", "--seed", "10", "--ignore-values")
        rows = _csv_out(capsys)
        index = rows[0].index("TXN-TYPE")
        assert {row[index] for row in rows[1:]} - {"D", "W", "T"}


class TestGenDataJsonModes:
    def test_list_records(self, monkeypatch, capsys):
        _run(monkeypatch, TXNDATA, "--list-records")
        payload = json.loads(capsys.readouterr().out)
        assert payload["source_file"] == TXNDATA
        assert [r["name"] for r in payload["records"]] == ["TXN-RECORD"]

    def test_describe_emits_layout_and_rows(self, monkeypatch, capsys):
        _run(monkeypatch, CUSTOMER, "--rows", "2", "--seed", "11", "--describe")
        payload = json.loads(capsys.readouterr().out)
        assert payload["record_name"] == "CUSTOMER-RECORD"
        assert payload["seed"] == 11
        assert payload["row_count"] == 2
        assert payload["fields"][0]["picture"] == "9(8)"

    def test_describe_reports_the_seed_chosen_at_random(self, monkeypatch, capsys):
        _run(monkeypatch, CUSTOMER, "--rows", "1", "--describe")
        assert isinstance(json.loads(capsys.readouterr().out)["seed"], int)

    def test_compact_json(self, monkeypatch, capsys):
        _run(monkeypatch, TXNDATA, "--list-records", "--compact")
        assert "\n" not in capsys.readouterr().out.strip()


class TestGenDataErrors:
    def test_missing_file(self, monkeypatch, capsys):
        with pytest.raises(SystemExit) as exc:
            _run(monkeypatch, "does-not-exist.cpy")
        assert exc.value.code == 1
        assert "File not found" in capsys.readouterr().err

    def test_unknown_record(self, monkeypatch, capsys):
        with pytest.raises(SystemExit) as exc:
            _run(monkeypatch, CUSTOMER, "--record", "NOPE")
        assert exc.value.code == 1
        assert "CUSTOMER-RECORD" in capsys.readouterr().err

    def test_invalid_blank_rate(self, monkeypatch, capsys):
        with pytest.raises(SystemExit) as exc:
            _run(monkeypatch, CUSTOMER, "--blank-rate", "2.5")
        assert exc.value.code == 1
        assert "blank_rate" in capsys.readouterr().err

    def test_negative_rows(self, monkeypatch, capsys):
        with pytest.raises(SystemExit) as exc:
            _run(monkeypatch, CUSTOMER, "--rows", "-3")
        assert exc.value.code == 1
        assert "rows" in capsys.readouterr().err

    def test_copybook_with_no_record(self, monkeypatch, capsys, tmp_path):
        empty = tmp_path / "EMPTY.cpy"
        empty.write_text("      * nothing but a comment\n")
        with pytest.raises(SystemExit) as exc:
            _run(monkeypatch, str(empty))
        assert exc.value.code == 1
        assert "no level-01 record" in capsys.readouterr().err


COMPBOOK = """       01  COMP-REC.
           05  CR-ID     PIC X(4).
           05  CR-QTY    PIC S9(4) COMP.
           05  CR-AMT    PIC S9(5)V99 COMP-3.
           05  CR-ADJ    PIC S9(3).
"""


@pytest.fixture
def comp_copybook(tmp_path) -> str:
    path = tmp_path / "COMPREC.cpy"
    path.write_text(COMPBOOK, encoding="utf-8")
    return str(path)


class TestRecordImageFormats:
    """``--format record`` / ``--format hex``: the bytes a program reads.

    The values asserted here are the same ones ``tests/unit/generators/data/
    test_encoding.py`` pins against a compiled GnuCOBOL probe; this layer
    only checks that the CLI reaches them and routes the output correctly.
    """

    def test_format_defaults_to_csv(self):
        args = _build_parser().parse_args(["gen-data", TXNDATA])
        assert args.output_format == "csv"
        assert args.charset == "ascii"
        assert args.endian == "auto"
        assert args.record_separator == "none"

    def test_record_output_is_written_as_binary(self, comp_copybook, tmp_path):
        out = tmp_path / "recs.bin"
        _run_argv(
            [
                "gen-data",
                comp_copybook,
                "-n",
                "2",
                "--seed",
                "5",
                "--format",
                "record",
                "-o",
                str(out),
            ]
        )
        # 4 + 2 + 4 + 3 = 13 bytes per record, two records.
        assert out.stat().st_size == 26

    def test_record_output_is_not_the_display_text(self, comp_copybook, tmp_path):
        out = tmp_path / "recs.bin"
        _run_argv(
            [
                "gen-data",
                comp_copybook,
                "-n",
                "1",
                "--seed",
                "5",
                "--format",
                "record",
                "-o",
                str(out),
            ]
        )
        raw = out.read_bytes()
        # CR-AMT is PIC S9(5)V99 COMP-3: seven digits packed into bytes 6-9,
        # with the sign in the low nibble of the last of them -- nothing a
        # CSV cell for this field could ever look like.
        assert raw[9] & 0x0F in (0x0C, 0x0D)

    def test_record_separator_newline_lengthens_each_record(
        self, comp_copybook, tmp_path
    ):
        out = tmp_path / "recs.bin"
        _run_argv(
            [
                "gen-data",
                comp_copybook,
                "-n",
                "2",
                "--seed",
                "5",
                "--format",
                "record",
                "--record-separator",
                "newline",
                "-o",
                str(out),
            ]
        )
        assert out.stat().st_size == 28

    def test_ebcdic_charset_changes_the_display_bytes(self, comp_copybook, tmp_path):
        ascii_out = tmp_path / "a.bin"
        ebcdic_out = tmp_path / "e.bin"
        for path, charset in ((ascii_out, "ascii"), (ebcdic_out, "ebcdic")):
            _run_argv(
                [
                    "gen-data",
                    comp_copybook,
                    "-n",
                    "1",
                    "--seed",
                    "5",
                    "--format",
                    "record",
                    "--charset",
                    charset,
                    "-o",
                    str(path),
                ]
            )
        assert ascii_out.read_bytes()[:4] != ebcdic_out.read_bytes()[:4]
        # 'C' is 0x43 in ASCII and 0xC3 in EBCDIC.
        assert ebcdic_out.read_bytes()[0] == 0xC3

    def test_hex_format_is_text_with_offsets_and_field_names(
        self, comp_copybook, capsys
    ):
        _run_argv(
            ["gen-data", comp_copybook, "-n", "1", "--seed", "5", "--format", "hex"]
        )
        out = capsys.readouterr().out
        assert "* record length: 13 bytes" in out
        assert "CR-AMT" in out
        assert "000000" in out

    def test_json_format_matches_describe(self, comp_copybook, capsys):
        _run_argv(
            ["gen-data", comp_copybook, "-n", "1", "--seed", "5", "--format", "json"]
        )
        payload = json.loads(capsys.readouterr().out)
        assert payload["record_name"] == "COMP-REC"
        assert payload["fields"][1]["storage_size"] == 2

    def test_record_formats_report_the_layout_override(self, comp_copybook, capsys):
        _run_argv(
            ["gen-data", comp_copybook, "-n", "1", "--seed", "5", "--format", "hex"]
        )
        assert "FILLER is included" in capsys.readouterr().err

    def test_csv_output_is_unchanged_by_the_new_flags(self, comp_copybook, capsys):
        _run_argv(["gen-data", comp_copybook, "-n", "2", "--seed", "5"])
        rows = list(csv.reader(io.StringIO(capsys.readouterr().out)))
        assert rows[0] == ["CR-ID", "CR-QTY", "CR-AMT", "CR-ADJ"]
        assert len(rows) == 3

    def test_output_file_encodes_the_dataset_exactly_once(
        self, comp_copybook, tmp_path, monkeypatch
    ):
        """Regression: the ``--output`` path used to call ``to_records()`` and
        then ``write_records()``, encoding every row twice and holding both
        copies at once -- the practical ceiling on a large ``--rows``."""
        from cobolparser.generators.data import dataset as dataset_module

        calls = []
        real = dataset_module.encode_record

        def counting(specs, row, opts, **kwargs):
            calls.append(row)
            return real(specs, row, opts, **kwargs)

        monkeypatch.setattr(dataset_module, "encode_record", counting)
        out = tmp_path / "recs.bin"
        _run_argv(
            [
                "gen-data",
                comp_copybook,
                "-n",
                "3",
                "--seed",
                "5",
                "--format",
                "record",
                "-o",
                str(out),
            ]
        )
        assert len(calls) == 3
        assert out.stat().st_size == 39


# A copybook whose record length genuinely varies: the counter, the table it
# sizes, and a field after the table that has to shift up when occurrences
# are dropped.
ODOBOOK = """       01  ORDER-REC.
           05  ORD-ID            PIC X(4).
           05  ORD-LINE-COUNT    PIC 9(2).
           05  ORD-LINES OCCURS 1 TO 4 TIMES
                         DEPENDING ON ORD-LINE-COUNT.
               10  ORD-SKU       PIC X(3).
           05  ORD-TOTAL         PIC 9(5).
"""


@pytest.fixture
def odo_copybook(tmp_path) -> str:
    path = tmp_path / "ORDER.cpy"
    path.write_text(ODOBOOK, encoding="utf-8")
    return str(path)


def _gen_records(copybook: str, out: Path, *extra: str) -> bytes:
    _run_argv(
        [
            "gen-data",
            copybook,
            "-n",
            "6",
            "--seed",
            "7",
            "--format",
            "record",
            *extra,
            "-o",
            str(out),
        ]
    )
    return out.read_bytes()


class TestRecordFormatFlag:
    """``--record-format``: RECFM=F/FB against RECFM=V/VB."""

    def test_the_default_is_fixed(self):
        # The parsed value is None rather than "fixed" so that
        # --record-varying can reach auto without overriding an explicit
        # --record-format fixed; what matters is what it resolves to.
        from cobolparser.cli.commands.data import _encoding_options
        from cobolparser.generators.data.encoding import RecordFormat

        args = _build_parser().parse_args(["gen-data", TXNDATA])
        assert args.record_format is None
        assert _encoding_options(args).record_format is RecordFormat.FIXED

    def test_a_record_varying_range_defaults_to_auto_not_fixed(self):
        from cobolparser.cli.commands.data import _encoding_options
        from cobolparser.generators.data.encoding import RecordFormat

        args = _build_parser().parse_args(
            ["gen-data", TXNDATA, "--record-varying", "20:31"]
        )
        assert _encoding_options(args).record_format is RecordFormat.AUTO

    def test_an_explicit_fixed_still_wins_over_a_varying_range(self):
        from cobolparser.cli.commands.data import _encoding_options
        from cobolparser.generators.data.encoding import RecordFormat

        args = _build_parser().parse_args(
            [
                "gen-data",
                TXNDATA,
                "--record-varying",
                "20:31",
                "--record-format",
                "fixed",
            ]
        )
        assert _encoding_options(args).record_format is RecordFormat.FIXED

    def test_every_choice_parses(self):
        for choice in ("fixed", "variable", "variable-bare", "auto"):
            args = _build_parser().parse_args(
                ["gen-data", TXNDATA, "--record-format", choice]
            )
            assert args.record_format == choice

    def test_fixed_writes_one_length_for_every_record(self, odo_copybook, tmp_path):
        # 4 + 2 + 4*3 + 5 = 23 bytes, six times.
        raw = _gen_records(odo_copybook, tmp_path / "f.bin")
        assert len(raw) == 6 * 23

    def test_variable_records_are_shorter_and_differ_in_length(
        self, odo_copybook, tmp_path
    ):
        fixed = _gen_records(odo_copybook, tmp_path / "f.bin")
        variable = _gen_records(
            odo_copybook, tmp_path / "v.bin", "--record-format", "variable"
        )
        assert len(variable) < len(fixed)
        # Walk the RDW chain: it has to land exactly on the end of the file,
        # which is the whole point of writing one.
        offset, lengths = 0, []
        while offset < len(variable):
            total = int.from_bytes(variable[offset : offset + 2], "big")
            assert variable[offset + 2 : offset + 4] == b"\x00\x00"
            lengths.append(total)
            offset += total
        assert offset == len(variable)
        assert len(lengths) == 6
        assert len(set(lengths)) > 1

    def test_variable_bare_drops_the_rdw_but_keeps_the_trimming(
        self, odo_copybook, tmp_path
    ):
        variable = _gen_records(
            odo_copybook, tmp_path / "v.bin", "--record-format", "variable"
        )
        bare = _gen_records(
            odo_copybook, tmp_path / "b.bin", "--record-format", "variable-bare"
        )
        assert len(bare) == len(variable) - 6 * 4

    def test_auto_follows_the_layout(self, odo_copybook, comp_copybook, tmp_path):
        auto = _gen_records(odo_copybook, tmp_path / "a.bin", "--record-format", "auto")
        variable = _gen_records(
            odo_copybook, tmp_path / "v.bin", "--record-format", "variable"
        )
        assert auto == variable
        # No DEPENDING ON table anywhere in COMPREC, so auto stays fixed.
        assert _gen_records(
            comp_copybook, tmp_path / "c1.bin", "--record-format", "auto"
        ) == (_gen_records(comp_copybook, tmp_path / "c2.bin"))

    def test_fixed_output_is_unchanged_by_the_flag_existing(
        self, comp_copybook, tmp_path
    ):
        """A copybook that cannot vary encodes to the same bytes it always
        did -- the compatibility guarantee the ``fixed`` default exists for."""
        plain = _gen_records(comp_copybook, tmp_path / "p.bin")
        flagged = _gen_records(
            comp_copybook, tmp_path / "q.bin", "--record-format", "fixed"
        )
        assert plain == flagged

    def test_the_record_length_range_is_reported_on_stderr(
        self, odo_copybook, tmp_path, capsys
    ):
        _gen_records(odo_copybook, tmp_path / "v.bin", "--record-format", "variable")
        err = capsys.readouterr().err
        assert "variable record length:" in err
        assert "RDW included" in err

    def test_fixed_output_still_warns_that_the_table_is_at_its_maximum(
        self, odo_copybook, tmp_path, capsys
    ):
        _gen_records(odo_copybook, tmp_path / "f.bin")
        err = capsys.readouterr().err
        assert "maximum length" in err
        assert "--record-format variable" in err

    def test_the_hex_dump_shows_the_rdw(self, odo_copybook, capsys):
        _run_argv(
            [
                "gen-data",
                odo_copybook,
                "-n",
                "2",
                "--seed",
                "7",
                "--format",
                "hex",
                "--record-format",
                "variable",
            ]
        )
        out = capsys.readouterr().out
        assert "record format: variable (RECFM=V/VB)" in out
        assert "(RDW)" in out


# The mainframestechhelp.com worked example: a flat record whose length is
# declared on the FD, with the length item in WORKING-STORAGE rather than in
# the record. No OCCURS DEPENDING ON anywhere.
EMPVL_PROGRAM = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. EMPVL.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT EMPFILE ASSIGN TO INPUT01
               ORGANIZATION IS SEQUENTIAL
               ACCESS MODE  IS SEQUENTIAL
               FILE STATUS  IS WS-FS1.
       DATA DIVISION.
       FILE SECTION.
       FD  EMPFILE
           RECORD VARYING FROM 47 TO 80 CHARACTERS
                  DEPENDING ON EMPREC-LEN
           RECORDING MODE IS V.
       01  EMP-RECORD80.
           05  EMP-ID          PIC X(6).
           05  EMP-NAME        PIC X(25).
           05  EMP-DEPT        PIC X(10).
           05  EMP-SALARY      PIC 9(6).
           05  EMP-COMMENT     PIC X(33).
       WORKING-STORAGE SECTION.
       01  WS-FS1              PIC XX.
       01  EMPREC-LEN          PIC S9(4) COMP.
       PROCEDURE DIVISION.
           CONTINUE.
"""


@pytest.fixture
def empvl_program(tmp_path) -> str:
    path = tmp_path / "EMPVL.cbl"
    path.write_text(EMPVL_PROGRAM, encoding="utf-8")
    return str(path)


def _rdw_lengths(raw: bytes) -> list[int]:
    """Walk a RECFM=V file's RDW chain, asserting it lands exactly on EOF."""
    offset, lengths = 0, []
    while offset < len(raw):
        total = int.from_bytes(raw[offset : offset + 2], "big")
        assert raw[offset + 2 : offset + 4] == b"\x00\x00"
        lengths.append(total)
        offset += total
    assert offset == len(raw)
    return lengths


class TestRecordVaryingFlag:
    """FD `RECORD VARYING` — the other way a COBOL record's length varies."""

    def test_the_fd_clause_is_picked_up_without_any_flag(self, empvl_program, tmp_path):
        out = tmp_path / "emp.vb"
        raw = _gen_records(empvl_program, out, "--record-format", "variable")
        lengths = _rdw_lengths(raw)
        # 47..80 data bytes, plus the 4-byte RDW.
        assert all(51 <= total <= 84 for total in lengths)
        assert len(set(lengths)) > 1

    def test_auto_follows_the_fd_clause_with_no_table_present(
        self, empvl_program, tmp_path
    ):
        auto = _gen_records(
            empvl_program, tmp_path / "a.bin", "--record-format", "auto"
        )
        variable = _gen_records(
            empvl_program, tmp_path / "v.bin", "--record-format", "variable"
        )
        assert auto == variable

    def test_fixed_writes_full_length_records_and_warns(
        self, empvl_program, tmp_path, capsys
    ):
        raw = _gen_records(
            empvl_program, tmp_path / "f.bin", "--record-format", "fixed"
        )
        assert len(raw) == 6 * 80
        assert "fixed-length output was asked for" in capsys.readouterr().err

    def test_the_declared_lrecl_is_reported_not_just_the_observed_span(
        self, empvl_program, tmp_path, capsys
    ):
        _gen_records(empvl_program, tmp_path / "v.bin", "--record-format", "variable")
        err = capsys.readouterr().err
        assert "declared RECORD VARYING FROM 47 TO 80" in err
        assert "LRECL is 84" in err

    def test_an_explicit_range_makes_a_bare_copybook_vary(
        self, comp_copybook, tmp_path
    ):
        raw = _gen_records(
            comp_copybook, tmp_path / "v.bin", "--record-varying", "6:12"
        )
        assert all(10 <= total <= 16 for total in _rdw_lengths(raw))

    def test_the_range_accepts_a_hyphen_as_well_as_a_colon(
        self, comp_copybook, tmp_path
    ):
        colon = _gen_records(
            comp_copybook, tmp_path / "c.bin", "--record-varying", "6:12"
        )
        hyphen = _gen_records(
            comp_copybook, tmp_path / "h.bin", "--record-varying", "6-12"
        )
        assert colon == hyphen

    def test_a_range_past_the_record_warns_instead_of_going_silent(
        self, comp_copybook, tmp_path, capsys
    ):
        # #274: COMP-REC is 13 bytes; 40:50 used to write plain RECFM=F and
        # 6:40 used to report "FROM 6 TO 13", neither with a word of warning.
        raw = _gen_records(
            comp_copybook, tmp_path / "x.bin", "--record-varying", "40:50"
        )
        assert len(raw) == 6 * 13
        err = capsys.readouterr().err
        assert "warning: requested RECORD VARYING FROM 40 TO 50" in err
        assert "ignored" in err

        _gen_records(comp_copybook, tmp_path / "y.bin", "--record-varying", "6:40")
        err = capsys.readouterr().err
        assert "clamped to FROM 6 TO 13" in err

    def test_a_clamped_range_is_a_caveat_in_the_hex_header(self, comp_copybook, capsys):
        _run_argv(
            [
                "gen-data",
                comp_copybook,
                "-n",
                "1",
                "--format",
                "hex",
                "--record-varying",
                "40:50",
            ]
        )
        out = capsys.readouterr().out
        assert "* caveat: requested RECORD VARYING FROM 40 TO 50" in out

    @pytest.mark.parametrize("bad", ["notanumber", "5", "1:2:3", "a:b"])
    def test_a_malformed_range_is_rejected(self, comp_copybook, tmp_path, bad):
        with pytest.raises(SystemExit):
            _gen_records(comp_copybook, tmp_path / "x.bin", "--record-varying", bad)

    def test_the_hex_dump_names_the_clause_and_marks_the_cut(
        self, empvl_program, capsys
    ):
        _run_argv(
            [
                "gen-data",
                empvl_program,
                "-n",
                "1",
                "--seed",
                "7",
                "--format",
                "hex",
                "--record-format",
                "variable",
            ]
        )
        out = capsys.readouterr().out
        assert "FD RECORD VARYING FROM 47 TO 80 DEPENDING ON EMPREC-LEN" in out
        assert "(RDW)" in out

    def test_a_copybook_with_no_range_is_unaffected(self, comp_copybook, tmp_path):
        plain = _gen_records(comp_copybook, tmp_path / "p.bin")
        assert len(plain) == 6 * 13
