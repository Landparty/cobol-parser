# Conventions

> Code style, error hierarchy, Cython fast-path pattern, import rules, and vendoring.

## Code Style

| Tool | Config | Rules |
|------|--------|-------|
| **Black** | `pyproject.toml` | Line length 88, target `py311` |
| **Ruff** | `pyproject.toml` | pycodestyle (E/W), pyflakes (F), isort (I), bugbear (B), comprehensions (C4), pyupgrade (UP); **E501 ignored** |
| **mypy** | `pyproject.toml` | Strict: `disallow_untyped_defs`, `disallow_incomplete_defs`, `strict_equality`, `warn_return_any`; tests are **exempted** from typed def requirements |

Run locally:

```bash
python -m ruff check . --fix
python -m black .
python -m mypy cobolparser/
```

## Python Version

- Minimum: Python 3.11
- Tested: 3.11, 3.12, 3.13 (CI matrix)
- Modern syntax throughout: `list[T]` (not `List[T]`), `dict[K, V]`, `X | None` (not `Optional[X]`)

## Zero Runtime Dependencies

The core library (`cobolparser/`) has **no external dependencies**. This is a hard invariant.

- `[dev]` extra: pytest, pytest-cov, ruff, black, mypy, cython
- `[fast]` extra: Cython, setuptools (for building `.pyx` extensions)
- `[profiling]` extra: `psutil` (imported lazily; library works without it)
- `[docs]` extra: sphinx, sphinx-rtd-theme

Never add an `install_requires` entry to the package.

## Import Conventions

- `__init__.py` files may have unused imports (F401 ignored in ruff per-file config) — they re-export the public API
- Circular import guard: `ParseError` is defined in `cobolparser/_errors.py` (zero imports) rather than `core/exceptions.py` to break the cycle between `plugins/core.py` and `core/exceptions.py`
- Never import `ParseError` from `core/exceptions.py` inside `plugins/core.py` — always use `_errors.py`

## Error Hierarchy

```
ParseError  (cobolparser/_errors.py — zero internal imports)
  │
  ├── [core/exceptions.py]
  │     ├── TokenMismatch
  │     ├── UnexpectedEndOfInput
  │     ├── DivisionNotFoundError
  │     ├── UnknownStatementError
  │     └── ValidationError
  │           ├── [core/ast_factory.py]
  │           │     ├── NodeTypeError
  │           │     └── FieldValidationError
  │
  ├── [plugins/core.py]
  │     ├── LexerError
  │     │     └── UnterminatedStringError
  │     │
  │     └── MemoryLimitExceededError
  │
  └── [NOT in hierarchy - separate tree]
        PreprocessingError  (cobolparser/preprocess/__init__.py)
              ├── CircularReferenceError
              ├── CopybookNotFoundError
              ├── PathTraversalError
              ├── EncodingError
              ├── NestingDepthError
              ├── CopybookSizeExceededError
              ├── CopybookSyntaxError
              └── TotalExpansionSizeExceededError
```

## Cython Fast-Path Pattern

Three optional Cython modules accelerate hot paths:

| Module | File | Accelerates |
|--------|------|-------------|
| `cobolparser._lexer_fast` | `cobolparser/_lexer_fast.pyx` | `CobolLexer` inner loops |
| `cobolparser._preprocess_fast` | `cobolparser/_preprocess_fast.pyx` | `normalize_fixed_format()` |
| `cobolparser._data_fast` | `cobolparser/_data_fast.pyx` | DATA DIVISION PICTURE/clause loops |

**Rules:**

- `.pyx` source AND pre-generated `.c` files are **both checked into the repo** — builds do not require Cython to be installed
- Build in-place: `python setup.py build_ext --inplace`
- Skip entirely: `COBOLPARSER_SKIP_EXT=1 pip install -e ".[dev]"`
- Each Cython module subclasses or overrides the pure-Python counterpart — the pure-Python path is always the fallback
- Never import `_lexer_fast`, `_preprocess_fast`, or `_data_fast` directly; they are loaded transparently

## Vendoring

`cobolparser` is vendored into `backend/_vendor/cobol-parser/` — it is **never installed from PyPI** by the backend:

```bash
# After making changes to cobolparser/, sync to the backend vendor dir:
cp -r cobolparser/ ../backend/_vendor/cobol-parser/cobolparser/
```

This is a **manual step** — there is no auto-sync. Never edit the vendor copy directly.

## Pre-Commit Hooks (`.pre-commit-config.yaml`)

| Hook | Action |
|------|--------|
| `ruff` | `ruff check . --fix` |
| `ruff-format` | Ruff's built-in formatter |
| `black` | `black .` |
| `mypy` | `mypy cobolparser/ --ignore-missing-imports` |

Run all hooks: `pre-commit run --all-files`

## Adding a New Statement Parser

1. Create `cobolparser/parsers/statements/foo_parser.py` implementing `IStatementParser` (`parse()` + `matches()`)
2. Register it in `ProcedureDivisionParser` via `StatementParserRegistry`
3. Add `TokenType` entry in `lexer.py` if the verb is not already a keyword
4. Add AST node(s) in `cobolparser/models/statements/<category>.py` with `to_dict()`; use `create_node()` from `core/ast_factory.py`
5. Export the parser from `cobolparser/parsers/statements/__init__.py`
6. Export the AST node from `cobolparser/models/statements/__init__.py` and `cobolparser/models/__init__.py`

## Gotchas and Invariants

- **PreprocessingError is NOT a ParseError**: It is a separate exception hierarchy rooted in `PreprocessingError` (defined in `cobolparser/preprocess/__init__.py`), not in `ParseError`. Catch both separately.
- **NodeTypeError and FieldValidationError extend ValidationError**, which extends ParseError. They are not separate hierarchies.
- **The pure-Python lexer/preprocessor are always fallbacks**: Even when Cython modules are available, the pure-Python paths remain the canonical implementation. Fast paths override inner loop methods only.
- **Circular imports are prevented by zero-import _errors.py**: Never add imports to `cobolparser/_errors.py`; this module is a circular-import firewall.
- **F401 is silently ignored in __init__.py files**: Unused imports there are intentional re-exports of the public API.
- **Vendoring is manual**: Changes to `cobolparser/` do not auto-propagate to `backend/_vendor/cobol-parser/`. You must run the `cp` command.

## Refresh Checklist

- [ ] Verify Black line length and target Python version in `pyproject.toml`
- [ ] Check ruff rule set for additions/removals (select: E, W, F, I, B, C4, UP; ignore: E501, B008, C901)
- [ ] Verify the error hierarchy — check `_errors.py`, `core/exceptions.py`, `plugins/core.py`, `preprocess/__init__.py`, `core/ast_factory.py` for new exception classes
- [ ] Confirm zero entries in `install_requires` in `pyproject.toml`
- [ ] Verify Cython module names are unchanged (`_lexer_fast`, `_preprocess_fast`, `_data_fast`)
- [ ] Check `.pre-commit-config.yaml` for hook changes
- [ ] Confirm PreprocessingError is NOT a ParseError subclass (separate tree)
- [ ] Verify F401 ignore pattern for `__init__.py` files in ruff config
