# cobol-parser

Python library for parsing IBM Enterprise COBOL source into an AST. Supports dependency extraction, dead code detection, program flow analysis, and CRUD matrices. 99.1% parse success on the NIST COBOL-85 corpus.

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://img.shields.io/badge/tests-5800%2B%20passing-green.svg)](#commands)
[![Coverage](https://img.shields.io/badge/coverage-81%25%2B%20enforced-green.svg)](#commands)
[![License: Proprietary](https://img.shields.io/badge/License-Proprietary-red.svg)](LICENSE)

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

`uv tool install` builds the Cython fast-path extensions as part of the
install, so the CLI runs at full speed. Verify it worked from anywhere:

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

Proprietary — Copyright © 2026 Samuel Dion. All rights reserved. See [LICENSE](LICENSE).
