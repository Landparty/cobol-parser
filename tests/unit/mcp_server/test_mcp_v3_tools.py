"""The v3 MCP tools (business_rules, diff_programs, decode_record,
gen_fixtures) and the prompts -- none of which needs the SDK."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from cobolparser.config.project import DataDefaults, ProjectConfig
from cobolparser.generators import (
    Charset,
    CopybookDataGenerator,
    DataGeneratorOptions,
    EncodingOptions,
)
from cobolparser.mcp import CobolTools, ToolError, Workspace
from cobolparser.mcp.prompts import PROMPTS
from cobolparser.mcp.tools import DEFAULT_DECODE_RECORDS, DEFAULT_FIXTURE_ROWS

ENTERPRISE = Path(__file__).resolve().parents[2] / "samples" / "enterprise"

ACCOUNT = """\
       01  ACCT-REC.
           05  ACCT-ID              PIC X(4).
           05  ACCT-BAL             PIC S9(5)V99 COMP-3.
           05  ACCT-KIND            PIC X.
           05  ACCT-CODE REDEFINES ACCT-KIND PIC 9.
"""


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """A private copy of the enterprise samples, safe to edit."""
    target = tmp_path / "src"
    shutil.copytree(ENTERPRISE, target)
    return target


def tools_for(root: Path, **config: object) -> CobolTools:
    return CobolTools(Workspace(root, ProjectConfig(**config)))  # type: ignore[arg-type]


def with_copybooks(root: Path, **config: object) -> CobolTools:
    return tools_for(root, copybook_path=(str(root / "copybooks"),), **config)


def kinds(result: dict) -> list[str]:
    return [c["kind"] for c in result["caveats"]]


def source_line(root: Path, location: dict) -> str:
    lines = (root / location["file"]).read_text().splitlines()
    return lines[location["line"] - 1]


def write_accounts(root: Path, rows: int, charset: Charset) -> list[list[str]]:
    """ACCT.cpy and ACCT.DAT under *root*; the rows the file holds."""
    (root / "ACCT.cpy").write_text(ACCOUNT)
    options = DataGeneratorOptions(rows=rows, seed=7).for_record_image()
    dataset = CopybookDataGenerator(options).generate_from_file(str(root / "ACCT.cpy"))
    dataset.write_records(str(root / "ACCT.DAT"), EncodingOptions(charset=charset))
    return dataset.rows


# -- business_rules ----------------------------------------------------------


class TestBusinessRules:
    def test_rules_are_cited_on_disk(self, root: Path) -> None:
        result = with_copybooks(root).business_rules("DB2BATCH.cbl")
        answer = result["answer"]
        assert answer["rule_count"] == answer["summary"]["rules"] > 0
        assert result["program"]["program_id"] == "DB2BATCH"
        for rule in answer["rules"]:
            line = source_line(root, rule["location"])
            assert rule["statement"] in line.upper()
            for branch in rule.get("branches", []):
                for action in branch["actions"]:
                    assert action["location"]["file"] == "DB2BATCH.cbl"

    def test_a_calculation_keeps_its_formula_not_a_copy_of_it(self, root: Path) -> None:
        answer = with_copybooks(root).business_rules(
            "DB2BATCH.cbl", kind="calculation"
        )["answer"]
        assert answer["rules"]
        for rule in answer["rules"]:
            assert rule["kind"] == "calculation"
            assert "formula" in rule
            assert "condition" not in rule

    def test_unknown_kind_is_an_error(self, root: Path) -> None:
        with pytest.raises(ToolError, match="unknown rule kind"):
            tools_for(root).business_rules("DB2BATCH.cbl", kind="policy")

    def test_procedure_filter_and_suggestions(self, root: Path) -> None:
        tools = with_copybooks(root)
        every = tools.business_rules("DB2BATCH.cbl")["answer"]["rules"]
        procedure = every[0]["procedure"]
        only = tools.business_rules("DB2BATCH.cbl", procedure=procedure.lower())
        assert only["answer"]["rules"]
        assert {r["procedure"] for r in only["answer"]["rules"]} == {procedure}
        miss = tools.business_rules("DB2BATCH.cbl", procedure=procedure + "X")
        assert miss["answer"]["rules"] == []
        assert procedure in miss["answer"]["suggestions"]

    def test_technical_rules_are_opt_in(self, root: Path) -> None:
        tools = with_copybooks(root)
        plain = tools.business_rules("DB2BATCH.cbl")["answer"]
        excluded = plain["summary"]["technical_rules_excluded"]
        assert excluded > 0
        assert "include_technical" in plain["note"]
        every = tools.business_rules("DB2BATCH.cbl", include_technical=True)
        assert every["answer"]["rule_count"] == plain["rule_count"] + excluded
        assert "note" not in every["answer"]

    def test_limit_truncates_with_the_true_total(self, root: Path) -> None:
        result = with_copybooks(root).business_rules("DB2BATCH.cbl", limit=1)
        assert len(result["answer"]["rules"]) == 1
        assert {"field": "rules", "shown": 1, "total": 3} in result["truncated"]


# -- diff_programs -----------------------------------------------------------


class TestDiffPrograms:
    def test_a_program_against_itself_has_no_change(self, root: Path) -> None:
        answer = tools_for(root).diff_programs("BATCHSEQ.cbl", "BATCHSEQ.cbl")["answer"]
        assert answer["summary"]["total_changes"] == 0
        assert answer["changes"] == []
        assert "no structural change" in answer["note"]

    def test_each_side_is_cited_in_its_own_file(self, root: Path) -> None:
        old = (root / "BATCHSEQ.cbl").read_text()
        new = old.replace(
            "05  TRAN-TYPE           PIC X.", "05  TRAN-TYPE           PIC XX."
        )
        assert new != old
        (root / "v2").mkdir()
        (root / "v2" / "BATCHSEQ.cbl").write_text(new)
        result = tools_for(root).diff_programs("BATCHSEQ.cbl", "v2/BATCHSEQ.cbl")
        answer = result["answer"]
        assert answer["old"]["file"] == "BATCHSEQ.cbl"
        assert answer["new"]["file"] == "v2/BATCHSEQ.cbl"
        changed = [c for c in answer["changes"] if "TRAN-TYPE" in c["symbol"]]
        assert changed
        change = changed[0]
        assert change["category"] == "data"
        assert "TRAN-TYPE" in source_line(root, change["old_location"])
        assert change["new_location"]["file"] == "v2/BATCHSEQ.cbl"

    def test_category_filter_keeps_the_whole_summary(self, root: Path) -> None:
        result = tools_for(root).diff_programs(
            "BATCHSEQ.cbl", "VSAMKSDS.cbl", category="procedure", limit=500
        )
        answer = result["answer"]
        assert answer["changes"]
        assert {c["category"] for c in answer["changes"]} == {"procedure"}
        assert answer["summary"]["by_category"]["procedure"] == len(answer["changes"])
        assert answer["summary"]["total_changes"] > len(answer["changes"])

    @pytest.mark.parametrize(
        ("kwargs", "message"),
        [
            ({"category": "copybook"}, "unknown category"),
            ({"rename_threshold": 1.5}, "rename_threshold"),
        ],
    )
    def test_bad_arguments(self, root: Path, kwargs: dict, message: str) -> None:
        with pytest.raises(ToolError, match=message):
            tools_for(root).diff_programs("BATCHSEQ.cbl", "BATCHSEQ.cbl", **kwargs)


# -- decode_record -----------------------------------------------------------


class TestDecodeRecord:
    def test_layout_only_lists_fields_and_views(self, root: Path) -> None:
        (root / "ACCT.cpy").write_text(ACCOUNT)
        answer = tools_for(root).decode_record("ACCT.cpy")["answer"]
        assert answer["record_name"] == "ACCT-REC"
        assert answer["record_length"] == 9
        assert [f["name"] for f in answer["fields"]] == [
            "ACCT-ID",
            "ACCT-BAL",
            "ACCT-KIND",
        ]
        assert [f["offset"] for f in answer["fields"]] == [0, 4, 8]
        assert len(answer["views"]) == 2
        assert "records" not in answer

    def test_round_trip_through_ebcdic(self, root: Path) -> None:
        rows = write_accounts(root, 3, Charset.EBCDIC)
        result = tools_for(root).decode_record("ACCT.cpy", "ACCT.DAT", charset="ebcdic")
        answer = result["answer"]
        assert answer["record_count"] == 3
        assert answer["more_records"] is False
        assert answer["error_count"] == 0
        assert [list(r["values"].values()) for r in answer["records"]] == rows
        assert "next" not in answer

    def test_charset_defaults_to_cobol_yml(self, root: Path) -> None:
        rows = write_accounts(root, 2, Charset.EBCDIC)
        tools = tools_for(root, data=DataDefaults(charset="ebcdic"))
        answer = tools.decode_record("ACCT.cpy", "ACCT.DAT")["answer"]
        assert [list(r["values"].values()) for r in answer["records"]] == rows

    def test_paging_with_skip(self, root: Path) -> None:
        rows = write_accounts(root, DEFAULT_DECODE_RECORDS + 2, Charset.ASCII)
        tools = tools_for(root)
        first = tools.decode_record("ACCT.cpy", "ACCT.DAT")["answer"]
        assert first["record_count"] == DEFAULT_DECODE_RECORDS
        assert first["more_records"] is True
        assert f"skip={DEFAULT_DECODE_RECORDS}" in first["next"]
        rest = tools.decode_record("ACCT.cpy", "ACCT.DAT", skip=DEFAULT_DECODE_RECORDS)[
            "answer"
        ]
        assert [r["index"] for r in rest["records"]] == [
            DEFAULT_DECODE_RECORDS,
            DEFAULT_DECODE_RECORDS + 1,
        ]
        assert list(rest["records"][-1]["values"].values()) == rows[-1]
        assert rest["more_records"] is False

    def test_fields_filter_and_an_unknown_field(self, root: Path) -> None:
        write_accounts(root, 1, Charset.ASCII)
        result = tools_for(root).decode_record(
            "ACCT.cpy", "ACCT.DAT", fields=["acct-bal", "NO-SUCH"]
        )
        assert list(result["answer"]["records"][0]["values"]) == ["ACCT-BAL"]
        assert any("NO-SUCH" in c["detail"] for c in result["caveats"])

    def test_a_redefines_view(self, root: Path) -> None:
        write_accounts(root, 1, Charset.ASCII)
        tools = tools_for(root)
        views = tools.decode_record("ACCT.cpy")["answer"]["views"]
        overlay = next(v["name"] for v in views if v["redefines"])
        answer = tools.decode_record("ACCT.cpy", "ACCT.DAT", view=overlay)["answer"]
        assert answer["view"] == overlay
        assert "ACCT-CODE" in answer["records"][0]["values"]
        with pytest.raises(ToolError, match="no view named"):
            tools.decode_record("ACCT.cpy", "ACCT.DAT", view="NOPE")

    def test_trailing_bytes_are_a_caveat(self, root: Path) -> None:
        write_accounts(root, 2, Charset.ASCII)
        with (root / "ACCT.DAT").open("ab") as handle:
            handle.write(b"XYZ")
        result = tools_for(root).decode_record("ACCT.cpy", "ACCT.DAT")
        assert result["answer"]["record_count"] == 2
        assert any("trailing" in c["detail"] for c in result["caveats"])

    def test_record_in_a_whole_program(self, root: Path) -> None:
        answer = tools_for(root).decode_record(
            "VSAMKSDS.cbl", record="CUST-MASTER-REC"
        )["answer"]
        assert answer["record_name"] == "CUST-MASTER-REC"
        assert answer["record_length"] == 68

    @pytest.mark.parametrize(
        ("kwargs", "message"),
        [
            ({"charset": "klingon"}, "bad encoding option"),
            ({"record_separator": "crlf"}, "record_separator"),
            ({"skip": -1}, "skip"),
            ({"record_length": 0}, "record_length"),
            ({"data_file": "../outside.dat"}, "outside the workspace"),
            ({"record": "NO-SUCH-REC"}, "NO-SUCH-REC"),
        ],
    )
    def test_bad_arguments(self, root: Path, kwargs: dict, message: str) -> None:
        (root / "ACCT.cpy").write_text(ACCOUNT)
        (root.parent / "outside.dat").write_bytes(b"x" * 9)
        with pytest.raises(ToolError, match=message):
            tools_for(root).decode_record("ACCT.cpy", **kwargs)


# -- gen_fixtures ------------------------------------------------------------


class TestGenFixtures:
    def test_happy_path_is_deterministic(self, root: Path) -> None:
        tools = with_copybooks(root)
        first = tools.gen_fixtures("BATCHSEQ.cbl")
        assert first == tools.gen_fixtures("BATCHSEQ.cbl")
        answer = first["answer"]
        assert answer["seed"] == 0
        assert answer["mode"] == "happy"
        assert answer["scenario_count"] == 1
        assert "arm_coverage" not in answer
        fixtures = answer["scenarios"][0]["fixtures"]
        with_rows = [f for f in fixtures if "rows" in f]
        assert with_rows
        for fixture in with_rows:
            assert len(fixture["rows"]) <= DEFAULT_FIXTURE_ROWS
            for row in fixture["rows"]:
                assert len(row) == len(fixture["columns"])
        for fixture in fixtures:
            assert fixture["location"]["file"] == "BATCHSEQ.cbl"

    def test_seed_from_the_argument_or_cobol_yml(self, root: Path) -> None:
        assert (
            tools_for(root).gen_fixtures("BATCHSEQ.cbl", seed=11)["answer"]["seed"]
            == 11
        )
        configured = tools_for(root, seed=42).gen_fixtures("BATCHSEQ.cbl")
        assert configured["answer"]["seed"] == 42

    def test_branches_report_arm_coverage(self, root: Path) -> None:
        answer = with_copybooks(root).gen_fixtures(
            "BATCHSEQ.cbl", mode="branches", limit=500
        )["answer"]
        coverage = answer["arm_coverage"]
        assert coverage["total_arms"] == (
            coverage["targeted"] + coverage["merged"] + coverage["missed"]
        )
        assert len(coverage["missed_arms"]) == coverage["missed"]
        assert answer["scenario_count"] > 1
        assert any("verification" in s for s in answer["scenarios"])

    def test_scenario_filter(self, root: Path) -> None:
        tools = with_copybooks(root)
        answer = tools.gen_fixtures("BATCHSEQ.cbl", mode="all", scenario="happy")[
            "answer"
        ]
        assert [s["name"] for s in answer["scenarios"]] == ["happy path"]
        none = tools.gen_fixtures("BATCHSEQ.cbl", scenario="happy pth")["answer"]
        assert none["scenarios"] == []
        assert none["suggestions"] == ["happy path"]

    def test_callee_directories_outside_the_root_are_skipped(
        self, root: Path, tmp_path: Path
    ) -> None:
        outside = tmp_path / "callees"
        outside.mkdir()
        tools = tools_for(root, callee_path=(str(outside), str(root)))
        result = tools.gen_fixtures("NESTED.cbl")
        assert any(
            "callee directories outside the workspace" in c["detail"]
            and str(outside) in c["detail"]
            for c in result["caveats"]
        )

    @pytest.mark.parametrize(
        ("kwargs", "message"),
        [
            ({"mode": "every"}, "unknown mode"),
            ({"rows": -1}, "rows must be"),
            ({"rows": 1000}, "rows must be"),
        ],
    )
    def test_bad_arguments(self, root: Path, kwargs: dict, message: str) -> None:
        with pytest.raises(ToolError, match=message):
            tools_for(root).gen_fixtures("BATCHSEQ.cbl", **kwargs)

    def test_answer_is_json(self, root: Path) -> None:
        json.dumps(with_copybooks(root).gen_fixtures("DB2BATCH.cbl", mode="all"))


# -- prompts -----------------------------------------------------------------


class TestPrompts:
    def test_every_prompt_names_only_real_tools(self) -> None:
        import re

        tool_names = {
            name
            for name in dir(CobolTools)
            if not name.startswith("_") and callable(getattr(CobolTools, name))
        }
        for spec in PROMPTS:
            assert spec.description
            arguments = {"file": "X.cbl", "name": "X"}
            parameters = spec.function.__code__.co_varnames[
                : spec.function.__code__.co_argcount
            ]
            text = spec.function(
                **{k: v for k, v in arguments.items() if k in parameters}
            )
            assert "file:line" in text
            called = set(re.findall(r"\b([a-z]+(?:_[a-z]+)+)\b", text))
            mentioned = {name for name in called if name in tool_names}
            assert mentioned, spec.name
            for name in called:
                if name.endswith(("_of", "_from", "_brief", "_symbol", "_layout")):
                    assert name in tool_names, (spec.name, name)

    def test_arguments_reach_the_text(self) -> None:
        by_name = {spec.name: spec.function for spec in PROMPTS}
        assert "PAYROLL.cbl (program unit SUB)" in by_name["explain_program"](
            "PAYROLL.cbl", "SUB"
        )
        text = by_name["plan_change"]("CUST-BAL", "CUST.cbl")
        assert 'name="CUST-BAL", file="CUST.cbl"' in text


# -- failure paths -----------------------------------------------------------


class TestFailures:
    @pytest.mark.parametrize(
        ("target", "call"),
        [
            (
                "cobolparser.analysis.business_rules.BusinessRuleExtractor.analyze",
                lambda tools: tools.business_rules("BATCHSEQ.cbl"),
            ),
            (
                "cobolparser.analysis.ast_diff.ProgramDiffer.diff",
                lambda tools: tools.diff_programs("BATCHSEQ.cbl", "BATCHSEQ.cbl"),
            ),
            (
                "cobolparser.generators.program_fixtures."
                "ProgramFixtureGenerator.generate_with_scenarios",
                lambda tools: tools.gen_fixtures("BATCHSEQ.cbl"),
            ),
        ],
    )
    def test_an_analyzer_that_raises_is_a_caveat(
        self, root: Path, monkeypatch: pytest.MonkeyPatch, target: str, call: object
    ) -> None:
        def boom(*args: object, **kwargs: object) -> None:
            raise RuntimeError("boom")

        monkeypatch.setattr(target, boom)
        result = call(tools_for(root))  # type: ignore[operator]
        assert "analyzer-failed" in kinds(result)
        assert any("boom" in c["detail"] for c in result["caveats"])

    def test_decode_names_an_unexpanded_copy(self, root: Path) -> None:
        (root / "HALF.cpy").write_text(ACCOUNT + "           COPY MISSING.\n")
        result = with_copybooks(root).decode_record("HALF.cpy")
        assert "unresolved-copybook" in kinds(result)
        assert any("MISSING" in c["detail"] for c in result["caveats"])

    def test_decode_reads_a_prefix_of_a_huge_file(
        self, root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        write_accounts(root, 5, Charset.ASCII)
        monkeypatch.setattr("cobolparser.mcp.tools.MAX_DECODE_BYTES", 20)
        tools = tools_for(root)
        answer = tools.decode_record("ACCT.cpy", "ACCT.DAT")["answer"]
        # 20 bytes hold two 9-byte records; the cut tail is no "trailing" bytes.
        assert answer["record_count"] == 2
        assert answer["more_records"] is True
        far = tools.decode_record("ACCT.cpy", "ACCT.DAT", skip=4)
        assert far["answer"]["records"] == []
        assert any("only the first 20 bytes" in c["detail"] for c in far["caveats"])
