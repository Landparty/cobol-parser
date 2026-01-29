# Quickstart — IO Variation Coverage Contribution

This guide helps contributors extend IO coverage using the existing parser framework while guarding against regressions and performance regressions.

## 1. Environment Setup

1. Install Python 3.13+ and create/activate a virtual environment.
2. Install dev dependencies:
   ```bash
   pip install -e .[dev]
   ```
3. Run sanity checks:
   ```bash
   ruff check .
   black --check .
   mypy cobolparser/
   ```

## 2. Capture Baseline Metrics (Mandatory)

```bash
pytest tests/ --cov=cobolparser --cov-report=term --maxfail=1
pytest tests/performance/ -m io
```

- Record total duration, max memory (reported via `ParseStatistics`), and coverage % inside the new `io-coverage.json` artifact.
- The baseline lives alongside the artifact so we can diff before/after every change.

## 3. Extend the IO Variation Catalog

1. Locate the IBM Enterprise COBOL Language Reference clause you are implementing.
2. Add/verify the corresponding entry in the `IOStatementVariation` table defined in `data-model.md`.
3. Update `contracts/io-statement-ast.md` if the clause introduces new AST fields.

## 4. Test-Driven Development Workflow

1. **Create fixtures** in `tests/samples/io/` (positive) and `tests/samples/io/negative/` (failure cases).
2. **Write failing tests**:
   - Contract tests under `tests/contracts/io/` to snapshot AST/JSON.
   - Unit tests under `tests/unit/io/` for clause permutations and diagnostics.
   - Integration tests under `tests/integration/io/` to assert multi-file behavior.
3. **Run targeted suites** until failures reproduce:
   ```bash
   pytest tests/unit/io/test_read.py -k "with_lock" -vv
   pytest tests/contracts/io/test_write_contract.py -vv
   ```
4. **Implement parser updates** in `cobolparser/parser.py` and AST node definitions in `cobolparser/models/statements.py`. Ensure type hints, docstrings, and `to_dict()` updates are included.
5. **Refactor** once tests pass; keep lexer/token helpers (`cobolparser/token_cache.py`) in sync if new keywords are introduced.

## 5. Coverage Artifact Generation

1. After all tests pass, run the reporter to gather pytest results and emit `io-coverage.json`:
   ```bash
   # Generate coverage artifact
   python -m cobolparser.cli.coverage generate --pytest-results results.json --output io-coverage.json
   
   # Or use standalone tool
   python tools/io_coverage/generate_artifact.py --pytest-results results.json --output io-coverage.json
   ```

2. Validate artifact against schema:
   ```bash
   python -m cobolparser.cli.coverage validate --artifact io-coverage.json
   python scripts/validate_io_coverage.py --artifact io-coverage.json
   ```

3. View coverage status:
   ```bash
   # Show all coverage
   python -m cobolparser.cli.coverage status
   
   # Filter by verb
   python -m cobolparser.cli.coverage status --verb READ
   
   # Filter by qualifier
   python -m cobolparser.cli.coverage status --qualifier "INVALID KEY"
   ```

4. Commit the artifact plus any updates to `docs/STATEMENT_TEST_COVERAGE_MATRIX.md` (human-readable summary).

## 6. Regression & Performance Check

- Re-run the **full** pytest suite and performance harness.
- Compare results to the baseline recorded in step 2; if runtime or memory increased by >10%, investigate before opening a PR.
- Ensure COLLECT_ALL mode still emits helpful diagnostics by running targeted negative tests:
  ```bash
  pytest tests/unit/io/test_read_errors.py -m "not slow"
  ```

## 7. Documentation & Review

- Update relevant docs (`docs/file-control.md`, `docs/STATEMENT_TEST_COVERAGE_MATRIX.md`, new coverage report README section).
- Summarize changes (new variations covered, tests added, artifact diff) in your pull request description.
- Link to the coverage artifact and baseline comparison to help reviewers evaluate regression risk.

Following this workflow keeps the project aligned with the Constitution (TDD, quality, performance, IBM priority) while satisfying the user request for comprehensive IO variation coverage without destabilizing existing functionality.
