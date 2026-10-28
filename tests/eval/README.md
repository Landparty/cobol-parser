# MCP benchmark tasks

The questions the MCP server benchmark asked, kept next to the code so a
change that breaks an answer is caught before the next benchmark run.

| File | What it is |
|------|------------|
| `tasks.json` | 13 tasks about the benchmark shop: `id`, `kind`, `q` (the question), `facts` (the verified answer key) |
| `tasks_carddemo.json` | 10 tasks about AWS CardDemo (not checked in, see below) |
| `shop/` | The parts of the shop that exist nowhere else in the repository: the order-processing programs and copybooks, their JCL and PROCLIBs, `cobol.yml` |
| `build_shop.py` | Builds the whole shop: `shop/` plus `tests/samples/enterprise`, `tests/samples/lineage`, `tests/samples/jcl` and the NIST `IC*` programs |
| `test_answer_keys.py` | The deterministic half: for every task, the tool a model would call returns the key's facts. Runs with the suite (`integration` marker) |
| `run_eval.py` | The model half: headless Claude Code with and without the `cobol` MCP server, a blind judge, a report |

## The deterministic tests

```bash
python -m pytest tests/eval -q --no-cov
```

Every task in `tasks.json` must have a `test_<id>_...` function; a new task
without one fails `test_every_task_is_pinned`. When a tool answer changes on
purpose, update the key in `tasks.json` and the test together.

## A model run

Needs the `claude` CLI on `PATH` and `cobol-parser` installed with the
`[mcp,jcl]` extras. Runs and grades go to `.eval-runs/` (git-ignored) and an
existing run is never repeated, so an interrupted run resumes.

```bash
python tests/eval/run_eval.py run            # every task, both arms, EVAL_REPS times
python tests/eval/run_eval.py run t03-callers
python tests/eval/run_eval.py judge
python tests/eval/run_eval.py report
```

`EVAL_MODEL`, `EVAL_JUDGE`, `EVAL_REPS`, `EVAL_PAR`, `EVAL_ARMS` and
`EVAL_MCP_ARGS` are described at the top of `run_eval.py`. A full run is
13 tasks x 2 arms x 3 reps of a model session: it costs real money, so run a
task or two after a change and the whole set before a release.

## CardDemo

The CardDemo tasks need a checkout of AWS CardDemo at the commit the keys
were verified on, laid out with the NIST programs:

```bash
mkdir -p /tmp/shop2 && cd /tmp/shop2
git clone https://github.com/aws-samples/aws-mainframe-modernization-carddemo carddemo
git -C carddemo checkout 59cc6c2fd7ebd7ef7925cad552a01a4b8b6e4d5e
mkdir -p nist/copy && cp "$REPO"/examples/cobol/IC*.CBL nist/ \
  && cp "$REPO"/examples/cobol/*.CPY nist/copy/
cp "$REPO"/tests/eval/carddemo-cobol.yml cobol.yml

EVAL_TASKS=tasks_carddemo.json EVAL_SHOP=/tmp/shop2 \
  python "$REPO"/tests/eval/run_eval.py run
```
