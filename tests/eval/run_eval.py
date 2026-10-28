"""The MCP benchmark as a repeatable eval: each task answered by headless
Claude Code with and without the ``cobol`` MCP server, graded against its
answer key by a blind judge, and summarised per task and arm.

    python tests/eval/run_eval.py run    [TASK_ID...]   # needs the claude CLI
    python tests/eval/run_eval.py judge
    python tests/eval/run_eval.py report

Environment (all optional):

* ``EVAL_OUT`` -- where runs and grades go (default ``.eval-runs`` in the
  repository root; git-ignored).
* ``EVAL_TASKS`` -- ``tasks.json`` (the shop, default) or
  ``tasks_carddemo.json`` (needs ``EVAL_SHOP``: see ``README.md``).
* ``EVAL_SHOP`` -- the root the tasks are asked about; built from
  ``build_shop.py`` when unset.
* ``EVAL_MODEL`` (default ``claude-sonnet-5-5``), ``EVAL_JUDGE``
  (``claude-opus-5-5``), ``EVAL_REPS`` (3), ``EVAL_PAR`` (6),
  ``EVAL_ARMS`` (``mcp,raw``), ``EVAL_MCP_ARGS`` (extra ``cobol-parser mcp``
  flags, e.g. ``--tools all``).

The deterministic half of the same answer keys -- what the tools
themselves return, no model involved -- runs with the test suite
(``test_answer_keys.py``).
"""

from __future__ import annotations

import json
import os
import re
import statistics
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
OUT = Path(os.environ.get("EVAL_OUT") or HERE.parents[1] / ".eval-runs")
TASKS = HERE / os.environ.get("EVAL_TASKS", "tasks.json")
MODEL = os.environ.get("EVAL_MODEL", "claude-sonnet-5-5")
JUDGE = os.environ.get("EVAL_JUDGE", "claude-opus-5-5")
REPS = int(os.environ.get("EVAL_REPS", "3"))
PAR = int(os.environ.get("EVAL_PAR", "6"))
ARMS = os.environ.get("EVAL_ARMS", "mcp,raw").split(",")

PREAMBLE = (
    "You are helping a developer understand the COBOL and JCL codebase in the "
    "current directory (a mainframe shop checkout). Answer the question below "
    "accurately and completely. Cite file:line where you can. Finish with a "
    "section headed 'FINAL ANSWER'.\n\nQuestion: "
)
#: A nested Claude Code session must not inherit this one's.
_STRIP = (
    "CLAUDE_CODE_SESSION_ID",
    "CLAUDE_CODE_TEE_SDK_STDOUT",
    "CLAUDE_CODE_MESSAGING_SOCKET",
    "CLAUDE_CODE_REMOTE_SESSION_ID",
    "CLAUDECODE",
)
ENV = {k: v for k, v in os.environ.items() if k not in _STRIP}


def _tasks() -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = json.loads(TASKS.read_text())
    return tasks


def _shop() -> Path:
    if os.environ.get("EVAL_SHOP"):
        return Path(os.environ["EVAL_SHOP"]).resolve()
    if TASKS.name != "tasks.json":
        sys.exit(f"{TASKS.name} needs EVAL_SHOP (see tests/eval/README.md)")
    target = OUT / "shop"
    if not target.exists():
        # The script's own directory is on sys.path when it runs.
        from build_shop import build_shop  # type: ignore[import-not-found]

        OUT.mkdir(parents=True, exist_ok=True)
        build_shop(target)
    return target


def _runs_dir() -> Path:
    return OUT / f"runs-{TASKS.stem}-{MODEL}"


def _run_one(task: dict[str, Any], arm: str, rep: int, shop: Path) -> None:
    path = _runs_dir() / f"{task['id']}__{arm}__{rep}.json"
    if path.exists():
        return
    command = [
        "claude",
        "-p",
        PREAMBLE + task["q"],
        "--setting-sources",
        "",
        "--model",
        MODEL,
        "--output-format",
        "json",
        "--tools",
        "Read,Grep,Glob",
        "--strict-mcp-config",
        "--no-session-persistence",
        "--max-turns",
        "60",
        "--allowedTools",
        "Read",
        "Grep",
        "Glob",
    ]
    if arm == "mcp":
        args = [
            "mcp",
            "--root",
            str(shop),
            *os.environ.get("EVAL_MCP_ARGS", "").split(),
        ]
        config = {"mcpServers": {"cobol": {"command": "cobol-parser", "args": args}}}
        handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, dir=OUT)
        with handle:
            json.dump(config, handle)
        command += ["mcp__cobol", "--mcp-config", handle.name]
    started = time.time()
    done = subprocess.run(
        command, cwd=shop, env=ENV, capture_output=True, text=True, timeout=1800
    )
    wall = time.time() - started
    try:
        data = json.loads(done.stdout)
    except ValueError:
        data = {
            "is_error": True,
            "result": done.stdout[-2000:],
            "stderr": done.stderr[-2000:],
        }
    data.update(_wall_s=wall, _task=task["id"], _arm=arm, _rep=rep, _model=MODEL)
    path.write_text(json.dumps(data, indent=1))
    print(task["id"], arm, rep, round(wall), data.get("num_turns"), flush=True)


def run(only: list[str]) -> None:
    shop = _shop()
    _runs_dir().mkdir(parents=True, exist_ok=True)
    jobs = [
        (task, arm, rep)
        for rep in range(REPS)
        for task in _tasks()
        for arm in ARMS
        if not only or task["id"] in only
    ]
    with ThreadPoolExecutor(PAR) as pool:
        list(pool.map(lambda job: _run_one(job[0], job[1], job[2], shop), jobs))


_JUDGE_PROMPT = """You are grading an answer about a COBOL/JCL codebase against a verified answer key.

QUESTION:
{question}

ANSWER KEY (verified facts):
{facts}

CANDIDATE ANSWER:
<<<
{answer}
>>>

For each key fact, score 1 if the candidate states it correctly, 0.5 if partially or vaguely, 0 if missing or wrong.
Also list any factually WRONG claims the candidate makes that contradict the key or that are clearly false about the code
(do not count harmless extra detail). Reply with JSON only:
{{"scores": [..one number per fact..], "wrong_claims": ["..."], "note": "one sentence"}}"""


def _grade_one(path: Path, tasks: dict[str, dict[str, Any]]) -> None:
    out = path.with_suffix(".grade.json")
    if out.exists():
        return
    data = json.loads(path.read_text())
    task = tasks[data["_task"]]
    prompt = _JUDGE_PROMPT.format(
        question=task["q"],
        facts="\n".join(f"{i + 1}. {f}" for i, f in enumerate(task["facts"])),
        answer=data.get("result") or "",
    )
    done = subprocess.run(
        [
            "claude",
            "-p",
            prompt,
            "--setting-sources",
            "",
            "--model",
            JUDGE,
            "--output-format",
            "json",
            "--tools",
            "",
            "--strict-mcp-config",
            "--no-session-persistence",
        ],
        cwd=tempfile.gettempdir(),
        env=ENV,
        capture_output=True,
        text=True,
        timeout=600,
    )
    reply = json.loads(done.stdout)["result"]
    found = re.search(r"\{.*\}", reply, re.S)
    if found is None:
        raise ValueError(f"{path.name}: the judge gave no JSON")
    grade = json.loads(found.group(0))
    if len(grade["scores"]) != len(task["facts"]):
        raise ValueError(f"{path.name}: {len(grade['scores'])} scores")
    out.write_text(json.dumps(grade, indent=1))
    print(path.name, grade["scores"], len(grade["wrong_claims"]), flush=True)


def judge() -> None:
    tasks = {t["id"]: t for t in _tasks()}
    runs = sorted(p for p in _runs_dir().glob("*.json") if ".grade" not in p.name)
    with ThreadPoolExecutor(PAR) as pool:
        list(pool.map(lambda p: _grade_one(p, tasks), runs))


def report() -> None:
    rows: list[dict[str, Any]] = []
    for path in sorted(_runs_dir().glob("*__*.json")):
        if ".grade" in path.name:
            continue
        grade_path = path.with_suffix(".grade.json")
        if not grade_path.exists():
            continue
        data = json.loads(path.read_text())
        grade = json.loads(grade_path.read_text())
        usage = data.get("usage", {})
        rows.append(
            {
                "task": data["_task"],
                "arm": data["_arm"],
                "acc": sum(grade["scores"]) / len(grade["scores"]),
                "perfect": sum(grade["scores"]) == len(grade["scores"]),
                "wrong": len(grade["wrong_claims"]),
                "tin": usage.get("input_tokens", 0)
                + usage.get("cache_read_input_tokens", 0)
                + usage.get("cache_creation_input_tokens", 0),
                "cost": data.get("total_cost_usd", 0) or 0,
                "wall": data["_wall_s"],
                "turns": data.get("num_turns", 0) or 0,
            }
        )
    print(
        f"{'task':20}{'arm':5}{'n':>3}{'acc':>6}{'perf':>5}{'wrong':>6}"
        f"{'in_tok':>9}{'cost$':>7}{'wall_s':>7}{'turns':>6}"
    )
    for task_id in [t["id"] for t in _tasks()] + ["ALL"]:
        for arm in ARMS:
            chosen = [
                r for r in rows if r["arm"] == arm and task_id in ("ALL", r["task"])
            ]
            if not chosen:
                continue
            print(
                f"{task_id:20}{arm:5}{len(chosen):>3}"
                f"{statistics.mean(r['acc'] for r in chosen):>6.2f}"
                f"{sum(r['perfect'] for r in chosen):>5}"
                f"{sum(r['wrong'] for r in chosen):>6}"
                f"{statistics.median(r['tin'] for r in chosen):>9.0f}"
                f"{statistics.mean(r['cost'] for r in chosen):>7.3f}"
                f"{statistics.median(r['wall'] for r in chosen):>7.0f}"
                f"{statistics.median(r['turns'] for r in chosen):>6.0f}"
            )


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else ""
    if action == "run":
        run(sys.argv[2:])
    elif action == "judge":
        judge()
    elif action == "report":
        report()
    else:
        sys.exit("usage: run_eval.py run [TASK_ID...] | judge | report")
