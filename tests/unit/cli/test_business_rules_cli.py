"""Tests for the `business-rules` subcommand.

The extractor's own behaviour is covered in
tests/unit/analysis/test_business_rules.py; what is pinned here is the
subcommand surface: that it is wired, its JSON and text outputs, and the
`--include-technical` switch.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from cobolparser.cli.parse import _build_parser, _cmd_business_rules, main

PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. RULECLI.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-FILE ASSIGN TO INFILE
               FILE STATUS IS WS-FS.
       DATA DIVISION.
       FILE SECTION.
       FD  IN-FILE.
       01  IN-REC.
           05  IN-AMOUNT  PIC 9(5)V99.
           05  IN-TYPE    PIC X.
               88  IN-VIP VALUE 'V'.
       WORKING-STORAGE SECTION.
       01  WS-FS          PIC XX.
       01  WS-DISCOUNT    PIC 9(5)V99.
       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT IN-FILE
           IF WS-FS NOT = '00'
               STOP RUN
           END-IF
           IF IN-VIP
               COMPUTE WS-DISCOUNT = IN-AMOUNT * 0.10
           END-IF
           CLOSE IN-FILE
           STOP RUN.
"""


def _args(filepath: str, **kwargs: object) -> argparse.Namespace:
    defaults: dict[str, object] = {
        "file": filepath,
        "compact": True,
        "free_form": False,
        "source_format": "auto",
        "dialect": "ibm-enterprise",
        "error_recovery": "collect-all",
        "copybook_path": [],
        "program": None,
        "define": [],
        "output": None,
        "profile": False,
        "output_format": "json",
        "include_technical": False,
    }
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def _source(tmp_path: Path) -> str:
    path = tmp_path / "RULECLI.cbl"
    path.write_text(PROGRAM, encoding="utf-8")
    return str(path)


class TestSubcommand:
    def test_it_is_a_known_subcommand(self) -> None:
        parsed = _build_parser().parse_args(["business-rules", "prog.cbl"])
        assert parsed.func is _cmd_business_rules
        assert parsed.output_format == "json"
        assert parsed.include_technical is False

    def test_json_output_carries_rules_glossary_and_summary(
        self, tmp_path, capsys
    ) -> None:
        _cmd_business_rules(_args(_source(tmp_path)))
        payload = json.loads(capsys.readouterr().out)

        assert payload["program_name"] == "RULECLI"
        assert [r["condition"] for r in payload["rules"]] == ["IN-VIP"]
        assert payload["summary"]["technical_rules_excluded"] == 1
        assert payload["condition_names"] == [
            {
                "name": "IN-VIP",
                "data_item": "IN-TYPE",
                "values": ["'V'"],
                "condition": "IN-TYPE = 'V'",
            }
        ]
        assert payload["data_lineage"]["WS-DISCOUNT"]["written_by"] == ["BR-001"]

    def test_include_technical_reports_the_file_status_check(
        self, tmp_path, capsys
    ) -> None:
        _cmd_business_rules(_args(_source(tmp_path), include_technical=True))
        payload = json.loads(capsys.readouterr().out)

        assert [r["technical"] for r in payload["rules"]] == [True, False]
        assert payload["summary"]["technical_rules_excluded"] == 0

    def test_text_format(self, tmp_path, capsys) -> None:
        _cmd_business_rules(_args(_source(tmp_path), output_format="text"))
        text = capsys.readouterr().out

        assert text.startswith("Business rules for RULECLI: 1 rule(s)")
        assert "COMPUTE WS-DISCOUNT = IN-AMOUNT * 0.10" in text
        assert "IN-VIP  IN-TYPE = 'V'" in text

    def test_through_main_with_an_output_file(self, tmp_path, monkeypatch) -> None:
        out = tmp_path / "rules.txt"
        monkeypatch.setattr(
            "sys.argv",
            [
                "cobol-parser",
                "business-rules",
                _source(tmp_path),
                "--format",
                "text",
                "--include-technical",
                "-o",
                str(out),
            ],
        )
        main()
        text = out.read_text(encoding="utf-8")
        assert "2 rule(s)" in text
        assert "[technical]" in text
