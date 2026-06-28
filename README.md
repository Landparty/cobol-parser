# cobol-parser

Python library for parsing IBM Enterprise COBOL source into an AST. Supports dependency extraction, dead code detection, program flow analysis, CRUD matrices, and CobolCheck test generation. 99.1% parse success on the NIST COBOL-85 corpus.

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://img.shields.io/badge/tests-5800%2B%20passing-green.svg)](#commands)
[![Coverage](https://img.shields.io/badge/coverage-81%25%2B%20enforced-green.svg)](#commands)
[![License: Proprietary](https://img.shields.io/badge/License-Proprietary-red.svg)](LICENSE)

## Install

```bash
pip install -e ".[dev]"
```

Requires Python 3.11, 3.12, or 3.13.

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
cobol-parser generate-tests program.cbl -o program.cut
```

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
