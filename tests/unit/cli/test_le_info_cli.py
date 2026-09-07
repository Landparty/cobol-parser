"""Tests for the `le-info` CLI subcommand.

`le-info` is the odd one out among the subcommands: it reads no source file,
because it exists to answer "what does this CALL need?" for an editor tooltip
rather than to analyze a program. These tests pin that difference (no
`source_file` header, no file argument) alongside the usual registration and
JSON-shape checks.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from cobolparser.cli.parse import _SUBCOMMANDS, _build_parser, main


def _run(*argv: str) -> None:
    with patch("sys.argv", ["cobol-parser", "le-info", *argv]):
        main()


class TestRegistration:
    def test_subcommand_in_parser(self) -> None:
        parser = _build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["le-info", "--help"])

    def test_subcommand_in_legacy_set(self) -> None:
        # Without this, main()'s legacy shim would read "le-info" as a
        # filename and rewrite the call as `parse le-info`.
        assert "le-info" in _SUBCOMMANDS


class TestWholeCatalogue:
    def test_default_emits_both_halves(self, capsys) -> None:
        _run("--compact")
        data = json.loads(capsys.readouterr().out)
        assert data["catalog_version"] >= 1
        assert data["services"] and data["functions"]
        assert "services_without_signature" in data

    def test_no_source_file_header(self, capsys) -> None:
        _run("--compact")
        data = json.loads(capsys.readouterr().out)
        assert "source_file" not in data

    def test_kind_service_omits_functions(self, capsys) -> None:
        _run("--kind", "service", "--compact")
        data = json.loads(capsys.readouterr().out)
        assert "services" in data
        assert "functions" not in data

    def test_kind_function_omits_services(self, capsys) -> None:
        _run("--kind", "function", "--compact")
        data = json.loads(capsys.readouterr().out)
        assert "functions" in data
        assert "services" not in data

    def test_pretty_by_default(self, capsys) -> None:
        _run()
        assert "\n  " in capsys.readouterr().out

    def test_writes_to_output_file(self, tmp_path, capsys) -> None:
        target = tmp_path / "catalog.json"
        _run("--compact", "-o", str(target))
        assert capsys.readouterr().out == ""
        data = json.loads(target.read_text())
        assert data["services"]


class TestNamedLookup:
    def test_service_by_name(self, capsys) -> None:
        _run("CEEDAYS", "--compact")
        entry = json.loads(capsys.readouterr().out)["entries"][0]
        assert entry["kind"] == "service"
        assert entry["required_count"] == 3
        assert [p["name"] for p in entry["parameters"]][-1] == "fc"

    def test_name_is_case_insensitive(self, capsys) -> None:
        _run("ceegmt", "--compact")
        entry = json.loads(capsys.readouterr().out)["entries"][0]
        assert entry["name"] == "CEEGMT"

    def test_intrinsic_function_by_name(self, capsys) -> None:
        _run("NUMVAL-C", "--compact")
        entry = json.loads(capsys.readouterr().out)["entries"][0]
        assert entry["kind"] == "function"
        assert entry["returns"] == "numeric"
        assert entry["arguments"][1]["optional"] is True

    def test_several_names_at_once(self, capsys) -> None:
        _run("CEEGMT", "LENGTH", "--compact")
        entries = json.loads(capsys.readouterr().out)["entries"]
        assert [e["name"] for e in entries] == ["CEEGMT", "LENGTH"]

    def test_known_service_without_a_signature_says_so(self, capsys) -> None:
        # Not an error and not silence: "we don't have this one" has to be
        # distinguishable from "that is not an LE service".
        _run("CEETERM", "--compact")
        entry = json.loads(capsys.readouterr().out)["entries"][0]
        assert entry["kind"] == "service"
        assert entry["parameters"] is None
        assert entry["notes"]

    def test_kind_filters_the_lookup(self, capsys) -> None:
        with pytest.raises(SystemExit):
            _run("CEEGMT", "--kind", "function")

    def test_unknown_name_fails(self, capsys) -> None:
        with pytest.raises(SystemExit):
            _run("NOT-A-THING")
        assert "Unknown name" in capsys.readouterr().err
