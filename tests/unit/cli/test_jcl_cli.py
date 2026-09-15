"""Tests for the `jcl` CLI subcommand.

The JCL parser itself is covered in tests/unit/test_jcl.py. What is pinned
here is the subcommand: its four views, the flag that turns unparseable
cards into a CI failure, and the rule that the gap lists travel with every
view rather than only the default one.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from cobolparser.cli.parse import _build_parser, _cmd_jcl

SAMPLES = Path(__file__).parents[2] / "samples" / "jcl"

TWO_STEP = """//PAYJOB   JOB (ACCT),'PAYROLL',CLASS=A,MSGCLASS=X
//STEP010  EXEC PGM=PAYCALC
//STEPLIB  DD DSN=PROD.LOADLIB,DISP=SHR
//PAYIN    DD DSN=PROD.PAY.INPUT,DISP=SHR
//PAYOUT   DD DSN=PROD.PAY.OUTPUT,DISP=(NEW,CATLG,DELETE),
//            DCB=(RECFM=FB,LRECL=200,BLKSIZE=27800)
//SYSOUT   DD SYSOUT=*
//STEP020  EXEC PGM=PAYRPT
//RPTIN    DD DSN=PROD.PAY.OUTPUT,DISP=SHR
//SYSOUT   DD SYSOUT=*
"""

# A card that does not begin with // or /* at all -- the parser cannot read
# it, which is what `--strict` exists to turn into a CI failure. (`PGM=` with
# an empty value would NOT do: that card parses fine, it is merely
# semantically empty, and the parser reports only what it could not read.)
BAD_CARD = """//BADJOB   JOB (ACCT),'BROKEN'
this line is not a JCL card at all
//STEP010  EXEC PGM=PAYCALC
//SYSOUT   DD SYSOUT=*
"""


def _args(filepath: str, **kwargs: object) -> argparse.Namespace:
    defaults: dict[str, object] = {
        "file": filepath,
        "compact": True,
        "dd_map": False,
        "bindings": False,
        "program": None,
        "strict": False,
        "output": None,
    }
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def _run(tmp_path: Path, source: str, capsys, **kwargs: object) -> dict:
    path = tmp_path / "JOB.jcl"
    path.write_text(source, encoding="utf-8")
    _cmd_jcl(_args(str(path), **kwargs))
    return json.loads(capsys.readouterr().out)


class TestRegistration:
    def test_jcl_is_a_known_subcommand(self):
        parsed = _build_parser().parse_args(["jcl", "JOB.jcl"])

        assert parsed.func is _cmd_jcl
        assert parsed.file == "JOB.jcl"

    def test_it_does_not_take_the_cobol_parse_flags(self):
        # JCL is a different language: there is no dialect, no source format
        # and no copybook path to honour, so those flags must not exist here.
        parsed = _build_parser().parse_args(["jcl", "JOB.jcl"])

        assert not hasattr(parsed, "dialect")
        assert not hasattr(parsed, "copybook_path")


class TestDefaultView:
    def test_it_reports_each_step_and_the_program_it_runs(self, tmp_path, capsys):
        payload = _run(tmp_path, TWO_STEP, capsys)

        steps = payload["jobs"][0]["steps"]
        assert [(s["name"], s["program"]) for s in steps] == [
            ("STEP010", "PAYCALC"),
            ("STEP020", "PAYRPT"),
        ]

    def test_a_continued_dcb_is_read_across_cards(self, tmp_path, capsys):
        payload = _run(tmp_path, TWO_STEP, capsys)

        step = payload["jobs"][0]["steps"][0]
        payout = next(d for d in step["dd_statements"] if d["name"] == "PAYOUT")
        assert payout["dataset"] == "PROD.PAY.OUTPUT"
        assert payout["record_format"] == "FB"
        assert payout["record_length"] == 200


class TestDdMap:
    def test_it_maps_each_dd_name_to_its_datasets(self, tmp_path, capsys):
        payload = _run(tmp_path, TWO_STEP, capsys, dd_map=True)

        # This is the join a COBOL SELECT ... ASSIGN TO PAYIN resolves through.
        assert payload["dd_map"]["PAYIN"] == ["PROD.PAY.INPUT"]
        assert payload["dd_map"]["PAYOUT"] == ["PROD.PAY.OUTPUT"]

    def test_a_dd_backed_by_no_dataset_maps_to_an_empty_list(self, tmp_path, capsys):
        payload = _run(tmp_path, TWO_STEP, capsys, dd_map=True)

        # Seen but backed by nothing (SYSOUT), which is different from absent.
        assert payload["dd_map"]["SYSOUT"] == []
        assert "NOSUCHDD" not in payload["dd_map"]


class TestBindings:
    def test_each_binding_names_its_step_and_job(self, tmp_path, capsys):
        payload = _run(tmp_path, TWO_STEP, capsys, bindings=True)

        payin = next(b for b in payload["bindings"] if b["ddname"] == "PAYIN")
        assert payin["dataset"] == "PROD.PAY.INPUT"
        assert payin["step"] == "STEP010"
        assert payin["job"] == "PAYJOB"
        assert payin["disposition"] == "SHR"

    def test_bindings_carry_the_dcb_facts_a_record_layout_needs(self, tmp_path, capsys):
        payload = _run(tmp_path, TWO_STEP, capsys, bindings=True)

        payout = next(b for b in payload["bindings"] if b["ddname"] == "PAYOUT")
        assert payout["record_format"] == "FB"
        assert payout["record_length"] == 200

    def test_program_narrows_the_bindings_to_that_programs_steps(
        self, tmp_path, capsys
    ):
        payload = _run(tmp_path, TWO_STEP, capsys, bindings=True, program="PAYRPT")

        assert {b["step"] for b in payload["bindings"]} == {"STEP020"}


class TestProgramView:
    def test_it_reports_only_the_steps_running_that_program(self, tmp_path, capsys):
        payload = _run(tmp_path, TWO_STEP, capsys, program="PAYCALC")

        assert payload["program"] == "PAYCALC"
        assert [s["name"] for s in payload["steps"]] == ["STEP010"]

    def test_a_program_no_step_runs_reports_empty_rather_than_failing(
        self, tmp_path, capsys
    ):
        payload = _run(tmp_path, TWO_STEP, capsys, program="NOSUCH")

        assert payload["steps"] == []


class TestGapReporting:
    @pytest.mark.parametrize(
        "view", [{}, {"dd_map": True}, {"bindings": True}, {"program": "PAYCALC"}]
    )
    def test_every_view_carries_the_gap_lists(self, tmp_path, capsys, view):
        # A --dd-map that silently omitted the cards it could not read would
        # be exactly the failure mode these reports exist to avoid.
        payload = _run(tmp_path, TWO_STEP, capsys, **view)

        assert "errors" in payload
        assert "unresolved" in payload

    def test_strict_exits_three_when_a_card_could_not_be_parsed(self, tmp_path, capsys):
        path = tmp_path / "BAD.jcl"
        path.write_text(BAD_CARD, encoding="utf-8")

        with pytest.raises(SystemExit) as exc:
            _cmd_jcl(_args(str(path), strict=True))

        # Exit 3 is the CI gate, kept distinct from exit 1 which means the
        # run itself failed -- the same split `lint --fail-on` uses.
        assert exc.value.code == 3
        assert json.loads(capsys.readouterr().out)["errors"]

    def test_without_strict_a_bad_card_is_reported_but_exits_zero(
        self, tmp_path, capsys
    ):
        payload = _run(tmp_path, BAD_CARD, capsys)

        assert payload["errors"]


class TestSampleJcl:
    def test_the_bundled_sample_resolves_its_dd_names(self, capsys):
        _cmd_jcl(_args(str(SAMPLES / "invupdt.jcl"), dd_map=True))
        payload = json.loads(capsys.readouterr().out)

        assert payload["dd_map"]["INVFILE"] == ["PROD.INV.MASTER"]
        # A concatenated DD contributes every dataset in the concatenation.
        assert len(payload["dd_map"]["JOBLIB"]) == 2
