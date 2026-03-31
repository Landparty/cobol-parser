# Contributing

## Setup

```bash
git clone https://github.com/Landparty/cobol-parser.git
cd cobol-parser
pip install -e ".[dev]"
```

## Workflow

This project follows TDD. Write tests before implementation.

```bash
# 1. Add a test
python -m pytest tests/ -k "your_feature" -v

# 2. Implement
# ...

# 3. Verify full suite passes with coverage
python -m pytest tests/ --cov=cobolparser --cov-fail-under=81

# 4. Lint and format
python -m ruff check . --fix
python -m black .
python -m mypy cobolparser/
```

## Code Standards

- Python 3.13+ only
- Type hints on all public APIs
- Docstrings on all public functions and classes
- Black formatting, Ruff linting, mypy passes

## Adding a new statement

See [architecture.md](architecture.md#adding-a-new-statement-parser).

## Pull Request Checklist

- All tests pass
- Coverage ≥ 81%
- CHANGELOG.md updated
- IBM Enterprise COBOL compatibility verified for new language features
