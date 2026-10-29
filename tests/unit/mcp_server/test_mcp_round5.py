"""What the fifth benchmark round asked of the server: a fast first call
after a restart, answers scoped to the question, every source of a program
name in any language, the code a JCL step runs through its CALLs, and the
jobs that run a program named in its brief."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from cobolparser.mcp import CobolTools, ToolError, Workspace
from cobolparser.mcp import languages as languages_module
from cobolparser.mcp.facts import HEAVY_FIELDS, FactsStore


def cobol(program: str, body: str = "", data: str = "") -> str:
    """A small fixed-format COBOL program."""
    lines = [
        "       IDENTIFICATION DIVISION.",
        f"       PROGRAM-ID. {program}.",
        "       DATA DIVISION.",
        "       WORKING-STORAGE SECTION.",
        "       01  WS-PGM               PIC X(8).",
        "       01  WS-AMT               PIC 9(5).",
        *[f"       {line}" for line in data.splitlines() if line],
        "       PROCEDURE DIVISION.",
        "       MAIN-PARA.",
        *[f"           {line}" for line in body.splitlines() if line],
        "           GOBACK.",
    ]
    return "\n".join(lines) + "\n"


def write(root: Path, name: str, text: str) -> None:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


@pytest.fixture
def shop(tmp_path: Path) -> Path:
    """Two applications side by side, as in a root holding several repos."""
    root = tmp_path / "shop"
    # bank: BATCH CALLs DATERTN statically; MENU CALLs through WS-PGM,
    # whose value is read at run time (so not traced), and names DATERTN.
    write(root, "bank/cbl/BATCH.cbl", cobol("BATCH", "CALL 'DATERTN' USING WS-AMT"))
    write(
        root,
        "bank/cbl/MENU.cbl",
        cobol(
            "MENU",
            "ACCEPT WS-PGM\nCALL WS-PGM",
            "01  WS-NOTE              PIC X(8) VALUE 'DATERTN'.",
        ),
    )
    write(root, "bank/cbl/DATERTN.cbl", cobol("DATERTN"))
    # cards: an untraced dynamic CALL that never names DATERTN.
    write(root, "cards/cbl/ROUTER.cbl", cobol("ROUTER", "ACCEPT WS-PGM\nCALL WS-PGM"))
    write(
        root,
        "bank/jcl/NIGHTLY.jcl",
        "//NIGHTLY  JOB (ACCT),'BANK',CLASS=A\n"
        "//STEP1    EXEC PGM=BATCH\n"
        "//IN       DD DSN=BANK.INPUT,DISP=SHR\n",
    )
    # A JCL file with a gap (a procedure not under the root) that never
    # names BATCH.
    write(
        root,
        "cards/jcl/CARDS.jcl",
        "//CARDS    JOB (ACCT),'CARDS',CLASS=A\n" "//STEP1    EXEC MISSPROC\n",
    )
    return root


def make_tools(root: Path, **store: Any) -> CobolTools:
    workspace = Workspace(root)
    if store:
        workspace.facts_store = FactsStore(workspace, **store)
    return CobolTools(workspace)


class TestRestartFromCache:
    def test_heavy_facts_stay_on_disk_until_needed(
        self, shop: Path, tmp_path: Path
    ) -> None:
        cache = tmp_path / "cache"
        first = make_tools(shop, workers=1, cache_dir=cache)
        before = first.where_from("WS-AMT", file="bank/cbl/BATCH.cbl")["answer"]
        first.callers_of(None, "DATERTN")
        (pickle_file,) = cache.glob("facts-*.pickle")
        assert len(list(pickle_file.with_suffix(".d").glob("*.pickle"))) == 4

        again = make_tools(shop, workers=1, cache_dir=cache)
        store = again.workspace.facts_store
        again.callers_of(None, "DATERTN")
        # The call graph came from the core facts alone: nothing parsed,
        # and no lineage read back.
        assert store.last_compute == (0.0, 0)
        assert not any(f.heavy for f in store._facts.values())
        after = again.where_from("WS-AMT", file="bank/cbl/BATCH.cbl")["answer"]
        assert store.last_compute == (0.0, 0)
        assert all(f.heavy for f in store._facts.values())
        assert after == before

    def test_a_missing_shard_is_computed_again(
        self, shop: Path, tmp_path: Path
    ) -> None:
        cache = tmp_path / "cache"
        make_tools(shop, workers=1, cache_dir=cache).find_statements(verb="CALL")
        (pickle_file,) = cache.glob("facts-*.pickle")
        victim = sorted(pickle_file.with_suffix(".d").glob("*.pickle"))[0]
        victim.unlink()
        again = make_tools(shop, workers=1, cache_dir=cache)
        found = again.find_statements(verb="CALL")["answer"]
        assert again.workspace.facts_store.last_compute[1] == 1
        assert found["match_count"] == 3

    def test_the_core_cache_holds_no_heavy_fields(
        self, shop: Path, tmp_path: Path
    ) -> None:
        import pickle

        cache = tmp_path / "cache"
        make_tools(shop, workers=1, cache_dir=cache).where_from(
            "WS-AMT", file="bank/cbl/BATCH.cbl"
        )
        (pickle_file,) = cache.glob("facts-*.pickle")
        held = pickle.loads(pickle_file.read_bytes())
        for facts in held["facts"].values():
            assert not facts.heavy
            assert all(getattr(facts, name) == [] for name in HEAVY_FIELDS)


class TestScopedAnswers:
    def test_unresolved_calls_elsewhere_are_counted(self, shop: Path) -> None:
        result = make_tools(shop).callers_of(None, "DATERTN")
        answer = result["answer"]
        assert [c["program"] for c in answer["callers"]] == ["BATCH"]
        assert [r["program"] for r in answer["unresolved_dynamic_calls"]] == ["MENU"]
        assert answer["unresolved_dynamic_calls_elsewhere"] == {
            "count": 1,
            "folders": ["cards"],
        }
        (caveat,) = [c for c in result["caveats"] if "dynamic CALL" in c["detail"]]
        assert "1 untraced dynamic CALL/LINK/XCTL site(s) in other folders" in (
            caveat["detail"]
        )

    def test_a_name_with_no_anchor_keeps_every_site(self, shop: Path) -> None:
        answer = make_tools(shop).callers_of(None, "NOWHERE")["answer"]
        # Declared nowhere and CALLed by no one: nothing to scope by.
        assert "unresolved_dynamic_calls_elsewhere" not in answer

    def test_jcl_gaps_elsewhere_are_counted(self, shop: Path) -> None:
        pytest.importorskip("jclparser")
        result = make_tools(shop).jobs_running("BATCH")
        details = [c["detail"] for c in result["caveats"]]
        assert not any("CARDS.jcl" in d for d in details)
        assert any(
            d.startswith("1 other JCL file(s) under the root have gaps")
            and d.endswith("do not name BATCH")
            for d in details
        )

    def test_jcl_gaps_naming_the_program_are_spelled_out(self, shop: Path) -> None:
        pytest.importorskip("jclparser")
        write(
            shop,
            "cards/jcl/CARDS.jcl",
            "//CARDS    JOB (ACCT),'CARDS',CLASS=A\n"
            "//* RUNS BATCH THROUGH A PROC NOT UNDER THE ROOT\n"
            "//STEP1    EXEC MISSPROC\n",
        )
        result = make_tools(shop).jobs_running("BATCH")
        assert any("cards/jcl/CARDS.jcl" in c["detail"] for c in result["caveats"])

    def test_coverage_names_what_was_read(self, shop: Path) -> None:
        write(shop, "bank/rexx/DATERTN.rexx", "/* REXX */\nsay 'hi'\n")
        answer = make_tools(shop).callers_of(None, "DATERTN")["answer"]
        assert answer["coverage"]["files_read"]["COBOL"] == 4
        assert answer["coverage"]["files_not_analyzed"] == {"REXX": 1}
        # A source of the same name in a language not read is named even
        # though a COBOL DATERTN is declared.
        assert answer["sources_not_analyzed"] == [
            {"file": "bank/rexx/DATERTN.rexx", "language": "REXX"}
        ]


class TestOtherLanguages:
    @pytest.fixture(autouse=True)
    def _needs_hlasm(self) -> None:
        pytest.importorskip("hlasmparser")

    def test_mlc_assembler_is_read_and_its_twin_named(self, shop: Path) -> None:
        write(
            shop,
            "bank/assembler/DATERTN.mlc",
            "DATERTN  CSECT\n         CALL  AUDITLOG\n         END\n",
        )
        result = make_tools(shop).callers_of(None, "DATERTN")
        declared = result["answer"]["declared_in"]
        assert {"file": "bank/assembler/DATERTN.mlc", "language": "assembler"} in (
            declared
        )
        assert {"file": "bank/cbl/DATERTN.cbl"} in declared
        assert any(c["kind"] == "duplicate-declaration" for c in result["caveats"])

    def test_jobs_running_lists_every_source_of_the_name(self, shop: Path) -> None:
        pytest.importorskip("jclparser")
        write(shop, "bank/assembler/BATCH.mlc", "BATCH    CSECT\n         END\n")
        result = make_tools(shop).jobs_running("BATCH")
        assert result["answer"]["sources"] == [
            {"file": "bank/assembler/BATCH.mlc", "language": "assembler"},
            {"file": "bank/cbl/BATCH.cbl", "language": "COBOL"},
        ]
        assert any(c["kind"] == "duplicate-declaration" for c in result["caveats"])

    def test_follow_calls_reaches_assembler(self, shop: Path) -> None:
        pytest.importorskip("jclparser")
        write(
            shop,
            "bank/assembler/DATERTN.asm",
            "DATERTN  CSECT\n         CALL  AUDITLOG\n         END\n",
        )
        (shop / "bank/cbl/DATERTN.cbl").unlink()
        answer = make_tools(shop).jobs_running("BATCH", follow_calls=True)["answer"]
        assert answer["languages_run"] == ["COBOL", "assembler"]
        calls = {c["program"]: c for c in answer["calls"]}
        assert calls["DATERTN"] == {
            "program": "DATERTN",
            "called_by": "BATCH",
            "via": "CALL",
            "depth": 1,
            "at": "bank/cbl/BATCH.cbl:9",
            "language": "assembler",
            "file": "bank/assembler/DATERTN.asm",
        }
        assert calls["AUDITLOG"]["depth"] == 2
        assert calls["AUDITLOG"]["in_workspace"] is False

    def test_overview_filters_by_language_and_path(self, shop: Path) -> None:
        write(shop, "bank/assembler/DATEASM.asm", "DATEASM  CSECT\n         END\n")
        tools = make_tools(shop)
        answer = tools.codebase_overview(language="asm")["answer"]
        assert [p["program"] for p in answer["programs"]] == ["DATEASM"]
        assert answer["programs_filter"] == {"language": "assembler"}
        assert answer["programs_matched"] == 1
        by_path = tools.codebase_overview(path="cards")["answer"]
        assert [p["program"] for p in by_path["programs"]] == ["ROUTER"]
        globbed = tools.codebase_overview(path="bank/*/BATCH.*")["answer"]
        assert [p["program"] for p in globbed["programs"]] == ["BATCH"]
        with pytest.raises(ToolError, match="unknown language"):
            tools.codebase_overview(language="FORTRAN")


class TestBriefRunBy:
    def test_cobol_brief_names_its_jobs(self, shop: Path) -> None:
        pytest.importorskip("jclparser")
        answer = make_tools(shop).program_brief("bank/cbl/BATCH.cbl")["answer"]
        assert answer["run_by"] == [
            {
                "job": "NIGHTLY",
                "step": "STEP1",
                "file": "bank/jcl/NIGHTLY.jcl",
                "location": {"file": "bank/jcl/NIGHTLY.jcl", "line": 2},
            }
        ]

    def test_a_program_no_step_runs(self, shop: Path) -> None:
        pytest.importorskip("jclparser")
        answer = make_tools(shop).program_brief("bank/cbl/MENU.cbl")["answer"]
        assert answer["run_by"] == []

    def test_no_jcl_extra_no_field(self, shop: Path) -> None:
        with patch("cobolparser.mcp.jcl_tools.jcl_available", return_value=False):
            answer = make_tools(shop).program_brief("bank/cbl/BATCH.cbl")["answer"]
        assert "run_by" not in answer


class TestLanguagesCache:
    def test_a_restart_reads_no_source_again(self, shop: Path, tmp_path: Path) -> None:
        pytest.importorskip("hlasmparser")
        write(shop, "bank/assembler/DATEASM.asm", "DATEASM  CSECT\n         END\n")
        cache = tmp_path / "cache"
        make_tools(shop, workers=1, cache_dir=cache).codebase_overview()
        with patch.object(
            languages_module, "read_facts", side_effect=AssertionError("read")
        ):
            answer = make_tools(shop, workers=1, cache_dir=cache).codebase_overview()
        assert "DATEASM" in {p["program"] for p in answer["answer"]["programs"]}


class TestWarmIndexes:
    def test_the_call_graph_and_jcl_are_built_at_start(self, shop: Path) -> None:
        pytest.importorskip("mcp")
        pytest.importorskip("jclparser")
        from cobolparser.mcp.server import warm_indexes

        workspace = Workspace(shop)
        warm_indexes(workspace).join(timeout=120)
        assert workspace.built_index("programs") is not None
        assert workspace.built_index("jcl") is not None

    def test_a_failing_index_does_not_stop_the_others(self, shop: Path) -> None:
        pytest.importorskip("mcp")
        pytest.importorskip("jclparser")
        from cobolparser.mcp.server import warm_indexes

        workspace = Workspace(shop)
        with patch(
            "cobolparser.mcp.codebase_index.programs_index",
            side_effect=RuntimeError("boom"),
        ):
            warm_indexes(workspace).join(timeout=120)
        assert workspace.built_index("programs") is None
        assert workspace.built_index("jcl") is not None
