ios/ or android/
# Implementation Plan: IO Variation Coverage

**Branch**: `[001-io-variation-coverage]` | **Date**: 2026-01-11 | **Spec**: [`specs/001-io-variation-coverage/spec.md`](./spec.md)
**Input**: Feature specification plus clarifications recorded in `/specs/001-io-variation-coverage/spec.md`

## Summary

We must extend the existing COBOL parser so that every IBM Enterprise COBOL fixed-format IO statement variation (OPEN, CLOSE, READ, WRITE, REWRITE, DELETE, START, ACCEPT, DISPLAY, UNLOCK) is parsed, serialized, and regression-tested. The work reuses the current lexer → parser → AST pipeline, seeds a complete IO test matrix (contract/integration/unit), emits a machine-readable coverage artifact, and keeps a human-readable summary in sync. Research (see `research.md`) confirms we will anchor the variation list on the IBM Language Reference, lean on existing statement coverage infrastructure, and baseline the full pytest + performance suites before and after delivering the feature.

## Technical Context

**Language/Version**: Python 3.13 (per `pyproject.toml`) with modern typing/dataclass features.  
**Primary Dependencies**: Internal modules `cobolparser/lexer.py`, `cobolparser/parser.py`, `cobolparser/models/{program,statements,data_items}.py`, dialect plug-ins in `cobolparser/dialects/ibm_enterprise.py`, plus dev tooling `pytest`, `pytest-cov`, `ruff`, `black`, `mypy`.  
**Storage**: N/A — parser operates entirely in memory with `MemoryConfiguration` enforcing limits; coverage artifacts persist as JSON/CSV files in repo/docs.  
**Testing**: Pytest suite organized under `tests/{contracts,integration,unit,regression,performance}` with statement coverage matrix documented in `docs/STATEMENT_TEST_COVERAGE_MATRIX.md`; CI enforces `pytest --cov=cobolparser --cov-fail-under=81` today (moving toward ≥90%).  
**Target Platform**: Cross-platform Python library (Windows 10+, macOS 10.15+, modern Linux) with baseline measurements taken on reference Windows machine plus CI Linux runners.  
**Project Type**: Single Python package distributed as a library/CLI helper, not a web/mobile app.  
**Performance Goals**: Maintain ≥10k COBOL lines/sec parsing throughput, keep IO suites under 90 seconds execution, and preserve default memory footprint under 256MB for 5MB fixed-format inputs; warn at 80% memory via `ParseStatistics`.  
**Constraints**: Must honor Constitution requirements (TDD, 90% coverage target, IBM priority), emit JSON AST via `to_dict()`, respect fixed-format column rules, and avoid adding new runtime dependencies.  
**Scale/Scope**: Coverage must span all IO verbs/qualifiers listed in IBM reference, across sequential/indexed/relative/VSAM files, ensuring sample programs up to multi-thousand lines remain parseable with streaming disabled by default.

## Constitution Check

*GATE: Passed — proceed to Phase 0 research (re-evaluate after Phase 1 deliverables).* 

1. **Test-First Development (TDD)** — ✅ We will extend the existing statement coverage matrix to enumerate IO permutations, author failing contract/unit/integration tests per variation, then implement parser/AST updates.  
2. **Code Quality Standards** — ✅ Plan includes 90%+ incremental coverage via pytest/pytest-cov, MyPy typing on new nodes, Ruff/Black formatting, and docstrings for every AST addition and coverage serializer.  
3. **Performance Requirements** — ✅ Baseline captured before coding; `tests/performance/` plus ParseStatistics instrumentation ensure IO suites stay within 10k lines/sec & 256MB, with regression budgets documented in Phase 2.  
4. **User Experience Consistency** — ✅ Public APIs remain unchanged; AST/JSON enhancements follow existing naming conventions, include line/column diagnostics, and reuse `SerializationConfig`. Documentation updates land in `docs/` and the coverage artifact schema.  
5. **IBM Enterprise COBOL Priority** — ✅ Variation catalog tied to IBM manual; dialect-specific clauses (NO REWIND, WITH LOCK, ADVANCING, KEY phrases) drive parsing/tests first.

**Quality Gates**:
- [x] TDD workflow documented (red-green-refactor cycle via coverage matrix before coding)
- [x] Test organization follows `tests/{contract,integration,unit}/` structure with IO-specific submodules
- [x] Performance benchmarks identified (10k lines/sec, <90s suite, <256MB) and tied to `tests/performance/`
- [x] Error messages include line/column information and recovery suggestions through existing `ParseError` pathways
- [x] JSON serialization includes AST `to_dict()` updates for any IO metadata and the new coverage artifact schema

**Justification for Any Failed Checks**: N/A — all checks satisfied.

## Project Structure

### Documentation (this feature)

```text
specs/001-io-variation-coverage/
├── plan.md              # Current implementation plan
├── research.md          # Phase 0 research decisions
├── data-model.md        # Phase 1 entity + relationship design
├── quickstart.md        # Phase 1 contributor ramp + workflow
├── contracts/
│   ├── io-coverage-schema.json
│   └── io-statement-ast.md
└── tasks.md             # Generated later via /speckit.tasks
```

### Source Code (repository root)

```text
cobolparser/
├── lexer.py
├── parser.py
├── models/
│   ├── ast_base.py
│   ├── program.py
│   ├── statements.py
│   └── data_items.py
├── dialects/
│   └── ibm_enterprise.py
├── plugins/
│   └── core.py          # MemoryConfiguration, ErrorRecoveryMode, SerializationConfig
├── analysis/
│   └── value_tracker.py
└── optimization/

tests/
├── contracts/
├── integration/
├── unit/
├── regression/
├── performance/
└── samples/

docs/
├── STATEMENT_TEST_COVERAGE_MATRIX.md
├── file-control.md
└── ... (IO + dialect references)
```

**Structure Decision**: This remains a single Python package; IO coverage touches `cobolparser/{lexer,parser,models}` and the `tests` tree only. Documentation additions stay inside `docs/` plus the new machine-readable artifact referenced from CI. No additional top-level services or packages are introduced.

## Complexity Tracking

N/A — no constitutional violations or extra subsystems required beyond existing architecture.

## Phase 0 – Research Highlights & Tasks

1. **IBM IO Variation Inventory** — Completed via `research.md` by mapping IBM Language Reference clauses to the spec’s `IO Statement Variation` entity. The canonical source is **IBM Enterprise COBOL for z/OS 6.4 Language Reference (SC27-8949-30, November 2023)** and its version tag must be recorded inside `io-variation-catalog.csv`. Output feeds both the data model and the coverage schema.
2. **Framework Assessment** — Confirmed reuse of `cobolparser/lexer.py`, `parser.py`, and AST definitions; no new parsing frameworks will be introduced, satisfying the user’s “use existing libraries” directive.
3. **Baseline Strategy** — Documented baseline procedure (full pytest + performance suites, reference to `docs/STATEMENT_TEST_COVERAGE_MATRIX.md`) to ensure regressions are detected at the outset and after landing IO coverage.

Deliverable: [`research.md`](./research.md) (complete) consolidates the above decisions with rationale and alternatives.

## Phase 1 – Design & Contract Outputs

1. **Data Model (`data-model.md`)**
  - Define entities: `IOStatementVariation`, `IOTestFixture`, `IOCoverageArtifact`, `IODialectProfile`, and `IOErrorDiagnostic`.
  - Capture relationships (variation ↔ fixtures ↔ AST metadata) plus validation rules (unique identifier, clause compatibility, performance tags).
2. **Contracts (`contracts/`)**
  - `io-coverage-schema.json`: JSON schema describing the machine-readable artifact (variation id, verb, qualifiers, tests, status, last_run, duration, diagnostics link).
  - `io-statement-ast.md`: Markdown contract enumerating required AST fields per IO verb, including serialization expectations and diagnostic format.
3. **Quickstart (`quickstart.md`)**
  - Developer workflow covering baseline test run, adding IO fixtures, writing TDD suites (unit/contract/integration), updating coverage artifact, and verifying performance gates.

This phase ensures the implementation team has unambiguous models, schema guarantees, and an onboarding playbook **before** code changes begin.

## Phase 2 – Implementation & Validation Roadmap

1. **Baseline & Instrumentation**
  - Run `pytest tests/ --cov=cobolparser --cov-report=html` and `pytest tests/performance/ -m io` (new marker) to capture timing/memory metrics.
  - Enforce automated guards (≤90 s runtime, ≤256 MB peak memory) so regressions are blocked at the CI level and record pass/fail status with every run.
  - Store summarized baseline metrics alongside the coverage artifact for comparison.
2. **TDD Cycle for Each IO Verb/Qualifier Set**
  - Author failing contract/unit/integration **and negative/diagnostic** tests referencing IBM clauses (e.g., READ NEXT WITH LOCK, WRITE BEFORE ADVANCING).
  - Capture evidence (logs or CI artifacts) that the new tests fail before starting parser/AST work, then update parser components incrementally while reusing error-recovery hooks and `SourceLocation` tracking.
  - Ensure new AST metadata implements `to_dict()` and is documented in `io-statement-ast.md`.
3. **Coverage Artifact Generation**
  - Build a lightweight reporter (likely under `cobolparser/analysis/`) that ingests pytest results and emits `io-coverage.json` conforming to the schema.
  - Wire artifact publication into CI and cross-link it with `docs/STATEMENT_TEST_COVERAGE_MATRIX.md`.
4. **Regression & Performance Guardrails**
  - Re-run full pytest + performance suites; compare metrics to baseline and investigate deviations >10% runtime or memory per Constitution Principle III.
  - Validate COLLECT_ALL error recovery continues to surface helpful diagnostics for malformed IO statements.
5. **Documentation & Handoff**
  - Update `docs/` (IO sections, STATEMENT_TEST_COVERAGE_MATRIX) with new coverage stats and instructions for extending the matrix.
  - Record final coverage artifact location in README/Quickstart.

6. **Supportability Metrics**
  - Track IO-related support tickets (baseline vs. post-release) using the metrics tooling introduced in tasks, so SC-004’s 40 % reduction goal is measurable and reportable alongside coverage artifacts.

Outputs from this plan feed `/speckit.tasks` for a sequenced implementation backlog aligned with TDD, quality, performance, and IBM priority mandates.

## Core Implementation Sequence & References

| Step | Task | Primary References |
|------|------|--------------------|
| 1 | **Sync IO variation catalog** – import/reconcile every verb/qualifier combo before coding. | Spec §Requirements, Clarifications (IBM reference); `research.md` Decision 1; `data-model.md` → `IOStatementVariation`. |
| 2 | **Author fixtures & failing tests** – create positive/negative COBOL snippets, wire pytest suites. | `quickstart.md` §4 “TDD Workflow”; `data-model.md` → `IOTestFixture`; `docs/STATEMENT_TEST_COVERAGE_MATRIX.md` for gap tracking. |
| 3 | **Extend lexer/parser/AST** – add tokens if needed, update `cobolparser/parser.py` and `models/statements.py`, ensure JSON serialization matches contract. | `contracts/io-statement-ast.md`; README “Architecture” section; existing AST patterns in `cobolparser/models`. |
| 4 | **Emit diagnostics** – implement `ParseError` codes and recovery hints per negative fixtures. | `contracts/io-statement-ast.md` (Diagnostics), `plugins/core.py` for error recovery hooks. |
| 5 | **Generate coverage artifact** – run reporter to build `io-coverage.json`, validate schema, attach baseline metrics. | `contracts/io-coverage-schema.json`; `quickstart.md` §5; `data-model.md` → `IOCoverageArtifact`. |
| 6 | **Update documentation & matrices** – sync Markdown summary and ensure Quickstart reflects new steps. | `docs/STATEMENT_TEST_COVERAGE_MATRIX.md`; `quickstart.md`; README “Features/Testing”. |
| 7 | **Baseline vs. post-change comparison** – capture pytest + performance metrics before and after implementation to guard regressions. | `quickstart.md` §2; `research.md` Decision 3; Constitution Principle III. |

## Refinement Loop (Per IO Verb)

1. **Plan** – Choose next variation from the catalog (spec + `data-model.md`).
2. **Test** – Add failing contract/unit/integration cases (`tests/.../io/` folders) referencing fixtures defined in Step 2 table above.
3. **Implement** – Update lexer/parser/AST per contracts, regenerate JSON snapshots.
4. **Verify** – Run targeted pytest subset, then full suite + performance comparison; update coverage artifact.
5. **Document** – Append row in `docs/STATEMENT_TEST_COVERAGE_MATRIX.md`, note artifact diff in PR, and keep Quickstart tips current if workflow changes.

Repeat until every variation moves from `missing` → `gap` → `covered` in `io-coverage.json`.
