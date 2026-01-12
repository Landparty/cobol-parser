# cobol-parser Development Guidelines

Auto-generated from all feature plans. Last updated: 2026-01-11

**Constitution**: All development must follow principles in `.specify/memory/constitution.md` (TDD, Code Quality, Performance, UX Consistency, IBM COBOL Priority)

## Active Technologies

- Python 3.13 (per `pyproject.toml`) with modern typing/dataclass features. + Internal modules `cobolparser/lexer.py`, `cobolparser/parser.py`, `cobolparser/models/{program,statements,data_items}.py`, dialect plug-ins in `cobolparser/dialects/ibm_enterprise.py`, plus dev tooling `pytest`, `pytest-cov`, `ruff`, `black`, `mypy`. (001-io-variation-coverage)

## Project Structure

```text
backend/
frontend/
tests/
```

## Commands

cd src; pytest; ruff check .

## Code Style

Python 3.13 (per `pyproject.toml`) with modern typing/dataclass features.: Follow standard conventions

## Recent Changes

- 001-io-variation-coverage: Added Python 3.13 (per `pyproject.toml`) with modern typing/dataclass features. + Internal modules `cobolparser/lexer.py`, `cobolparser/parser.py`, `cobolparser/models/{program,statements,data_items}.py`, dialect plug-ins in `cobolparser/dialects/ibm_enterprise.py`, plus dev tooling `pytest`, `pytest-cov`, `ruff`, `black`, `mypy`.

<!-- MANUAL ADDITIONS START -->
<!-- MANUAL ADDITIONS END -->
