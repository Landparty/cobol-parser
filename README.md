# COBOL Parser for Python

[![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://img.shields.io/badge/tests-2975%20passing-green.svg)](#testing)
[![Coverage](https://img.shields.io/badge/coverage-81%25%2B%20enforced-green.svg)](#testing)
[![License: Proprietary](https://img.shields.io/badge/License-Proprietary-red.svg)](LICENSE)
[![IBM COBOL](https://img.shields.io/badge/IBM%20Enterprise%20COBOL-supported-blue.svg)](docs/ibm-enterprise.md)

A COBOL source code parser for Python 3.13+ that converts COBOL programs into structured ASTs. Supports IBM Enterprise COBOL, configurable memory management, JSON export, and robust error recovery. Built with TDD — 2,975 tests, 81%+ coverage enforced.

## Features

- **IBM Enterprise COBOL** — COMP-3, EXEC SQL, EXEC CICS, 75+ verbs
- **Error recovery** — fail-fast or collect-all modes
- **JSON export** — cross-platform AST serialization with source locations
- **Memory management** — configurable limits from 64MB to 8GB
- **Batch parsing** — parallel multi-file processing via `parse_files()`

## Installation

```bash
pip install cobolparser

# or from source
git clone https://github.com/Landparty/cobol-parser.git
cd cobol-parser
pip install -e ".[dev]"
```

Requires Python 3.13+.

## Quick Start

```python
from cobolparser import parse_cobol

result = parse_cobol(source, filename="prog.cob")

if result.success:
    print(result.ast.program_name)
    print(result.ast.to_json())
else:
    for err in result.errors:
        print(f"Line {err.line}: {err.message}")
```

See [docs/PARSER_INVOCATION_GUIDE.md](docs/PARSER_INVOCATION_GUIDE.md) for the full API including `CobolParser`, `MemoryConfiguration`, `ErrorRecoveryMode`, and `parse_files()`.

## Documentation

| Topic | Guide |
|---|---|
| Full API reference & invocation | [PARSER_INVOCATION_GUIDE.md](docs/PARSER_INVOCATION_GUIDE.md) |
| Real-world recipes | [cookbook.md](docs/cookbook.md) |
| Architecture & pipeline | [architecture.md](docs/architecture.md) |
| Configuration options | [configuration.md](docs/configuration.md) |
| Performance & optimization | [performance.md](docs/performance.md) |
| Troubleshooting | [troubleshooting.md](docs/troubleshooting.md) |
| Contributing | [contributing.md](docs/contributing.md) |
| IBM Enterprise COBOL | [ibm-enterprise.md](docs/ibm-enterprise.md) |

## Testing

```bash
python -m pytest tests/ -v                              # all tests
python -m pytest tests/unit/ -v                         # unit only
python -m pytest --cov=cobolparser --cov-report=html    # with coverage
```

81%+ line coverage is enforced. Running a subset of tests will cause the coverage check to fail — this is expected.

## License

Proprietary — Copyright © 2026 Samuel Dion. All rights reserved. See [LICENSE](LICENSE) for terms.
