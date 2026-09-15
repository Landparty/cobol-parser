"""Tests for the codebase-scoped CLI subcommands: xref, diff,
codebase-graph and copybook-impact.

These four are the first subcommands that answer a question about more than
one file, so what is pinned here is mostly the shapes their consumers read
and the argument handling that has no equivalent elsewhere in the CLI: two
positional source files (diff), a directory-or-file-list (the two graph
commands), and non-JSON output formats.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from cobolparser.cli.parse import (
    _build_parser,
    _cmd_codebase_graph,
    _cmd_copybook_impact,
    _cmd_diff,
    _cmd_xref,
)

MAINPGM = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. MAINPGM.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       COPY CUSTREC.
       01 WS-COUNT PIC 9(4) VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 1 TO WS-COUNT
           IF WS-COUNT > 0
              CALL "SUBPGM" USING WS-COUNT
           END-IF
           PERFORM REPORT-PARA
           GOBACK.
       REPORT-PARA.
           DISPLAY WS-COUNT.
"""

SUBPGM = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. SUBPGM.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       COPY CUSTREC.
       LINKAGE SECTION.
       01 LK-COUNT PIC 9(4).
       PROCEDURE DIVISION USING LK-COUNT.
       SUB-MAIN.
           MOVE 5 TO LK-COUNT
           GOBACK.
"""

CUSTREC = """       01 CUST-REC.
          05 CUST-ID   PIC X(6).
          05 CUST-NAME PIC X(30).
"""


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """A two-program codebase sharing one copybook."""
    copybooks = tmp_path / "copybooks"
    copybooks.mkdir()
    (copybooks / "CUSTREC.cpy").write_text(CUSTREC, encoding="utf-8")
    (tmp_path / "MAINPGM.cbl").write_text(MAINPGM, encoding="utf-8")
    (tmp_path / "SUBPGM.cbl").write_text(SUBPGM, encoding="utf-8")
    return tmp_path


def _single_file_args(filepath: str, **kwargs: object) -> argparse.Namespace:
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
    }
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def _graph_args(paths: list[str], **kwargs: object) -> argparse.Namespace:
    defaults: dict[str, object] = {
        "paths": paths,
        "compact": True,
        "copybook_path": [],
        "extensions": None,
        "workers": 1,
        "output_format": "json",
        "output": None,
    }
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


class TestXref:
    def test_it_is_a_known_subcommand(self):
        parsed = _build_parser().parse_args(["xref", "prog.cbl"])

        assert parsed.func is _cmd_xref

    def test_a_reference_carries_its_role_and_enclosing_paragraph(self, tree, capsys):
        _cmd_xref(_single_file_args(str(tree / "MAINPGM.cbl")))
        payload = json.loads(capsys.readouterr().out)

        entry = next(e for e in payload["entries"] if e["name"] == "WS-COUNT")
        roles = {r["role"] for r in entry["references"]}
        # The whole point of the listing: "unused" becomes "used HOW".
        assert {"write", "condition", "call-argument", "read"} <= roles
        assert {r["context"] for r in entry["references"]} == {
            "MAIN-PARA",
            "REPORT-PARA",
        }

    def test_paragraphs_are_cross_referenced_too(self, tree, capsys):
        _cmd_xref(_single_file_args(str(tree / "MAINPGM.cbl")))
        payload = json.loads(capsys.readouterr().out)

        report_para = next(e for e in payload["entries"] if e["name"] == "REPORT-PARA")
        assert report_para["kind"] == "paragraph"
        assert any(r["role"] == "perform" for r in report_para["references"])


class TestDiff:
    def test_it_takes_two_positional_files(self):
        parsed = _build_parser().parse_args(["diff", "old.cbl", "new.cbl"])

        assert parsed.func is _cmd_diff
        assert parsed.old == "old.cbl"
        assert parsed.new == "new.cbl"

    def _diff_args(self, old: str, new: str, **kwargs: object) -> argparse.Namespace:
        defaults: dict[str, object] = {
            "old": old,
            "new": new,
            "compact": True,
            "free_form": False,
            "source_format": "auto",
            "dialect": "ibm-enterprise",
            "error_recovery": "collect-all",
            "copybook_path": [],
            "define": [],
            "output": None,
            "output_format": "json",
            "rename_threshold": 0.8,
        }
        defaults.update(kwargs)
        return argparse.Namespace(**defaults)

    def test_a_renamed_paragraph_is_a_rename_not_an_add_and_a_remove(
        self, tree, tmp_path, capsys
    ):
        renamed = tmp_path / "MAINPGM_NEW.cbl"
        renamed.write_text(
            MAINPGM.replace("REPORT-PARA", "SUMMARY-PARA"), encoding="utf-8"
        )

        _cmd_diff(self._diff_args(str(tree / "MAINPGM.cbl"), str(renamed)))
        payload = json.loads(capsys.readouterr().out)

        kinds = {c["kind"] for c in payload["changes"]}
        assert "paragraph-renamed" in kinds
        assert "paragraph-added" not in kinds
        assert "paragraph-removed" not in kinds

    def test_a_changed_picture_is_reported_with_both_values(
        self, tree, tmp_path, capsys
    ):
        widened = tmp_path / "MAINPGM_WIDE.cbl"
        widened.write_text(
            MAINPGM.replace("PIC 9(4) VALUE 0", "PIC 9(6) VALUE 0"), encoding="utf-8"
        )

        _cmd_diff(self._diff_args(str(tree / "MAINPGM.cbl"), str(widened)))
        payload = json.loads(capsys.readouterr().out)

        change = next(c for c in payload["changes"] if c["kind"] == "picture-changed")
        assert change["symbol"] == "WS-COUNT"
        assert change["old"] == "9(4)"
        assert change["new"] == "9(6)"

    def test_identical_programs_produce_no_changes(self, tree, capsys):
        path = str(tree / "MAINPGM.cbl")

        _cmd_diff(self._diff_args(path, path))
        payload = json.loads(capsys.readouterr().out)

        assert payload["changes"] == []

    def test_text_format_renders_a_readable_summary(self, tree, tmp_path, capsys):
        renamed = tmp_path / "MAINPGM_NEW.cbl"
        renamed.write_text(
            MAINPGM.replace("REPORT-PARA", "SUMMARY-PARA"), encoding="utf-8"
        )

        _cmd_diff(
            self._diff_args(
                str(tree / "MAINPGM.cbl"), str(renamed), output_format="text"
            )
        )
        out = capsys.readouterr().out

        assert "MAINPGM" in out
        assert "paragraph-renamed" in out

    def test_output_names_both_sides(self, tree, capsys):
        path = str(tree / "MAINPGM.cbl")

        _cmd_diff(self._diff_args(path, path))
        payload = json.loads(capsys.readouterr().out)

        assert payload["old_file"] == path
        assert payload["new_file"] == path

    @pytest.mark.parametrize("threshold", [-0.1, 1.5])
    def test_an_out_of_range_rename_threshold_exits_nonzero(
        self, tree, threshold, capsys
    ):
        path = str(tree / "MAINPGM.cbl")

        with pytest.raises(SystemExit) as exc:
            _cmd_diff(self._diff_args(path, path, rename_threshold=threshold))

        assert exc.value.code == 1
        assert "rename-threshold" in capsys.readouterr().err


class TestCodebaseGraph:
    def test_it_is_a_known_subcommand_taking_many_paths(self):
        parsed = _build_parser().parse_args(["codebase-graph", "a.cbl", "b.cbl"])

        assert parsed.func is _cmd_codebase_graph
        assert parsed.paths == ["a.cbl", "b.cbl"]

    def test_a_directory_is_walked_and_call_edges_found(self, tree, capsys):
        _cmd_codebase_graph(
            _graph_args([str(tree)], copybook_path=[str(tree / "copybooks")])
        )
        payload = json.loads(capsys.readouterr().out)

        assert {p["program_id"] for p in payload["programs"]} == {
            "MAINPGM",
            "SUBPGM",
        }
        assert {"caller": "MAINPGM", "callee": "SUBPGM"}.items() <= next(
            e for e in payload["call_edges"]
        ).items()

    def test_copy_edges_name_the_shared_member(self, tree, capsys):
        _cmd_codebase_graph(
            _graph_args([str(tree)], copybook_path=[str(tree / "copybooks")])
        )
        payload = json.loads(capsys.readouterr().out)

        copiers = {e["program"] for e in payload["copy_edges"]}
        assert copiers == {"MAINPGM", "SUBPGM"}

    def test_an_explicit_file_list_works_too(self, tree, capsys):
        _cmd_codebase_graph(
            _graph_args([str(tree / "MAINPGM.cbl"), str(tree / "SUBPGM.cbl")])
        )
        payload = json.loads(capsys.readouterr().out)

        assert len(payload["programs"]) == 2

    def test_mixing_a_directory_and_files_is_rejected_rather_than_guessed(
        self, tree, capsys
    ):
        with pytest.raises(SystemExit) as exc:
            _cmd_codebase_graph(_graph_args([str(tree), str(tree / "MAINPGM.cbl")]))

        assert exc.value.code == 1
        assert "one directory" in capsys.readouterr().err

    def test_mermaid_output_quotes_hyphenated_names(self, tree, capsys):
        _cmd_codebase_graph(_graph_args([str(tree)], output_format="mermaid"))
        out = capsys.readouterr().out

        assert out.startswith("flowchart")
        assert "P_MAINPGM" in out
        # A raw hyphen in a Mermaid node id is a syntax error, so ids are
        # sanitized and the real name lives in the quoted label.
        assert '"MAINPGM"' in out

    def test_dot_output_is_a_digraph(self, tree, capsys):
        _cmd_codebase_graph(_graph_args([str(tree)], output_format="dot"))
        out = capsys.readouterr().out

        assert "digraph" in out
        assert "MAINPGM" in out

    def test_a_path_that_does_not_exist_is_reported_not_dropped(self, tmp_path, capsys):
        # A mistyped file name must not quietly shrink the graph. It is not a
        # directory, so it goes down the file-list path and the builder
        # records it rather than skipping it.
        missing = tmp_path / "also-missing.cbl"

        _cmd_codebase_graph(_graph_args([str(missing)]))
        payload = json.loads(capsys.readouterr().out)

        assert payload["errors"], "a missing file must be reported"
        assert any(str(missing) in e["path"] for e in payload["errors"])
        assert payload["programs"][0]["parse_failed"] is True


class TestCopybookImpact:
    def test_it_takes_a_member_and_paths(self):
        parsed = _build_parser().parse_args(["copybook-impact", "CUSTREC", "./src"])

        assert parsed.func is _cmd_copybook_impact
        assert parsed.member == "CUSTREC"
        assert parsed.paths == ["./src"]

    def test_it_names_every_program_that_copies_the_member(self, tree, capsys):
        _cmd_copybook_impact(
            argparse.Namespace(
                member="CUSTREC",
                **vars(
                    _graph_args([str(tree)], copybook_path=[str(tree / "copybooks")])
                ),
            )
        )
        payload = json.loads(capsys.readouterr().out)

        assert payload["direct_programs"] == ["MAINPGM", "SUBPGM"]

    def test_it_lists_the_fields_the_member_contributes(self, tree, capsys):
        _cmd_copybook_impact(
            argparse.Namespace(
                member="CUSTREC",
                **vars(
                    _graph_args([str(tree)], copybook_path=[str(tree / "copybooks")])
                ),
            )
        )
        payload = json.loads(capsys.readouterr().out)

        assert set(payload["fields"]) == {"CUST-REC", "CUST-ID", "CUST-NAME"}

    def test_a_member_nothing_copies_reports_empty_rather_than_failing(
        self, tree, capsys
    ):
        _cmd_copybook_impact(
            argparse.Namespace(
                member="NOSUCH",
                **vars(
                    _graph_args([str(tree)], copybook_path=[str(tree / "copybooks")])
                ),
            )
        )
        payload = json.loads(capsys.readouterr().out)

        assert payload["direct_programs"] == []
        assert payload["summary"]["program_count"] == 0
