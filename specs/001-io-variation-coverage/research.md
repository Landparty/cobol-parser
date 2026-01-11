# Research Notes — IO Variation Coverage

## Decision 1: Canonical IO Variation Catalog
- **Decision**: Enumerate every IO statement variation directly from the IBM Enterprise COBOL Language Reference and map each clause/qualifier combination into the `IO Statement Variation` entity defined in the spec.
- **Rationale**: The spec and clarifications require complete IBM fixed-format coverage, and the reference manual already lists the authoritative permutations (e.g., READ NEXT WITH LOCK AT END). Aligning with it guarantees parity with mainframe expectations and prevents divergent tribal knowledge.
- **Alternatives considered**:
  - Use only in-repo samples (e.g., `docs/file-control.md`) → rejected because current docs cover FD/SELECT clauses but not every PROCEDURE DIVISION IO verb.
  - Derive variations from real customer code → useful for prioritization but not exhaustive for compliance.

## Decision 2: Leverage Existing Parser Pipeline
- **Decision**: Extend the current lexer (`cobolparser/lexer.py`), parser (`cobolparser/parser.py`), and AST node modules (`cobolparser/models/statements.py`) instead of introducing a parallel parsing subsystem.
- **Rationale**: The README already documents the lexer → parser → AST pipeline, and the AST base classes enforce `to_dict()` serialization that downstream tools rely on. Reusing this framework keeps memory-management hooks (`MemoryConfiguration`, `ParseStatistics`) and error-recovery modes intact, minimizing regression risk.
- **Alternatives considered**:
  - Introduce a separate mini-parser for IO statements → would duplicate tokenization, bypass error recovery, and complicate JSON export.
  - Depend on third-party parsing libraries → no external dependency currently handles IBM COBOL syntax as deeply, and adding one would violate the "existing framework" directive.

## Decision 3: Baseline & Regression Safety Net
- **Decision**: Capture a baseline by running the full pytest suite (`pytest tests/ --cov=cobolparser --cov-report=html`) plus the statement coverage reports documented in `docs/STATEMENT_TEST_COVERAGE_MATRIX.md` before coding, then re-run after changes. Performance baselines leverage the existing `tests/performance/` harness targeting the 10k lines/sec and <256MB limits.
- **Rationale**: Ensures we detect regressions in already-implemented statements (MOVE, DISPLAY, PERFORM, etc.) while quantifying how new IO suites affect coverage and runtime. Aligns with the user's "baseline" requirement and Constitution Principle I & III.
- **Alternatives considered**:
  - Run only targeted IO tests → faster, but would miss cross-statement regressions.
  - Defer performance checks until after implementation → risks late surprises if IO suites exceed timing/memory budgets.

## Decision 4: Machine-Readable Coverage Artifact
- **Decision**: Generate a JSON (optionally CSV) artifact that lists every IO variation, linked tests, last execution status, and diagnostics, then publish it from CI. The artifact schema will live in `/specs/001-io-variation-coverage/contracts/io-coverage-schema.json` and reuse the parser's `SerializationConfig` conventions for timestamps/metadata.
- **Rationale**: Satisfies the clarified requirement for a machine-readable coverage summary, enables dashboards to diff coverage between commits, and lets documentation auto-sync with the human-readable matrix in `docs/STATEMENT_TEST_COVERAGE_MATRIX.md`.
- **Alternatives considered**:
  - Markdown-only table updates → manual, error-prone, and not ingestible by tooling.
  - Storing coverage state inside pytest markers → convenient but too coupled to runtime and hard to expose via CI artifacts.
