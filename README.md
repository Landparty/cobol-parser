# cobol-parser

Python library for parsing IBM Enterprise COBOL source into an AST. Supports dependency extraction, dead code detection, program flow analysis, and CRUD matrices. 99.1% parse success on the NIST COBOL-85 corpus.

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://img.shields.io/badge/tests-8000%2B%20passing-green.svg)](#commands)
[![Coverage](https://img.shields.io/badge/coverage-81%25%2B%20enforced-green.svg)](#commands)
[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](LICENSE)

## Install

```bash
pip install -e ".[dev]"
```

Requires Python 3.11, 3.12, or 3.13.

### Install the CLI globally (uv)

To get the `cobol-parser` command on your `PATH` in any directory, without
setting up a project virtualenv:

```bash
uv tool install .            # from a clone of this repo
uv tool install --editable . # dev mode: picks up code changes without reinstalling
```

The install is pure Python by default: no C compiler needed. The optional
Cython accelerators (about 3x lexer throughput) are an opt-in, chosen by one
environment variable both when building and when running:

```bash
COBOLPARSER_ACCEL=1 uv tool install . --reinstall   # compile them
export COBOLPARSER_ACCEL=1                          # and use them
```

The PyPI wheels already contain the compiled accelerators, so for a
`pip install cobol-parser` setting `COBOLPARSER_ACCEL=1` at run time is
enough. Without the variable, a compiled extension is ignored.

Verify it worked from anywhere:

```bash
cobol-parser --version
```

After pulling new commits (non-editable install only), rerun `uv tool install . --reinstall` to update.

## Quick Start

```python
from cobolparser import parse_cobol

result = parse_cobol(source, filename="prog.cbl")
if result.success:
    print(result.ast.program_name)
    print(result.ast.to_json())
```

CLI:

```bash
cobol-parser parse program.cbl
cobol-parser analyze program.cbl      # dynamic call analysis
cobol-parser dead-code program.cbl    # unreferenced paragraphs
cobol-parser lint program.cbl         # every analyzer at once, as one list
```

### Lint a program

`lint` runs several analyzers over a single parse and reports everything they
found as one severity-graded list, instead of one subcommand (and one
re-parse) per concern:

```bash
cobol-parser lint program.cbl --format text
```

```text
program.cbl:6:1: warning [unused-variables] WORKING-STORAGE item WS-NEVER-USED (level 01) is never referenced in the PROCEDURE DIVISION
program.cbl:12:5: error [move-type-check] Illegal MOVE: cannot move NUMERIC item 'WS-COUNTER' to ALPHABETIC item 'WS-ALPHA'
program.cbl:17:1: warning [dead-code] paragraph ORPHAN-PARA is never referenced
3 finding(s): 1 error, 2 warning, 0 info (7 rule(s) ran)
```

`--rule` narrows the run (rule ids are the analyzer subcommand names),
`--min-severity` narrows the output, and `--fail-on error` exits 3 when
anything at that severity was reported — a CI gate that stays distinct from
exit 1, which still means the run itself failed. `--format json` (the
default) additionally reports which rules ran, which raised, and what could
not be checked, so a quiet report is never mistaken for a clean program.

```python
from cobolparser import LintAnalyzer, parse_cobol

report = LintAnalyzer().analyze(parse_cobol(source, filename="prog.cbl").ast)
for finding in report.findings:
    print(finding.rule, finding.severity, finding.message)
```

### Generate test data from a copybook

`gen-data` turns a copybook record layout into a CSV of synthetic records —
one column per elementary field, values that always fit the field's PICTURE,
`USAGE`, and level-88 domain:

```bash
cobol-parser gen-data CUSTOMER.cpy --rows 100 --seed 7 -o customers.csv
```

```python
from cobolparser.generators import CopybookDataGenerator, DataGeneratorOptions

dataset = CopybookDataGenerator(
    DataGeneratorOptions(rows=100, seed=7)
).generate_from_file("CUSTOMER.cpy")
print(dataset.to_csv())
```

A `seed` makes output byte-identical across runs; omit it and the seed that
was drawn is reported on `dataset.seed` (and by `gen-data --describe`) so any
run can be replayed. `REDEFINES` and `FILLER` are excluded by default, and
`OCCURS` tables expand to one column per occurrence.

## Commands

```bash
# Tests
python -m pytest tests/ -v
python -m pytest --cov=cobolparser --cov-report=html

# Lint / format / type-check
ruff check .
black .
mypy cobolparser/
```

## Documentation

Full reference: [`.okf/index.md`](.okf/index.md)

## License

GNU Affero General Public License v3.0 or later — Copyright © 2026 Samuel Dion. See [LICENSE](LICENSE).
