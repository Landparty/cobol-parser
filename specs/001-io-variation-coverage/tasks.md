# Tasks: IO Variation Coverage

**Input**: Design documents from `/specs/001-io-variation-coverage/`
**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/`

**Constitution Compliance**: This task list enforces TDD—tests MUST be authored first, reviewed, and failing before implementation work proceeds. All tasks inherit the project’s requirements for 90%+ coverage, typed code, and IBM Enterprise COBOL priority.

**Tests**: Mandatory. For every user story, contract, unit, and integration tests precede implementation tasks.

**Organization**: Tasks are grouped by phase and user story to keep increments independently deliverable.

## Phase 1: Setup (Shared Infrastructure)

Purpose: Capture baseline metrics, prepare IO-specific test scaffolding, and wire the guardrails that enforce SC-002/SC-004 before development starts.

- [x] T001 Capture pre-change metrics by running `pytest tests/ --cov=cobolparser --cov-report=term` and `pytest tests/performance/ -m io`, then write results to `specs/001-io-variation-coverage/baselines/metrics.json`.
- [x] T002 [P] Create IO-focused test package scaffolding by adding `__init__.py` (and README notes) under `tests/unit/io/`, `tests/contracts/io/`, and `tests/integration/io/` to isolate new suites.
- [x] T003 [P] Register an `io` pytest marker in `pyproject.toml` and add marker usage examples in `tests/performance/conftest.py` so performance suites can target IO scenarios.
- [x] T004 Implement an automated performance guard (`tools/perf/io_threshold_guard.py` + CI wiring) that fails the pipeline whenever IO suites exceed 90 seconds runtime or 256 MB peak memory, and document the thresholds in `quickstart.md` (SC-002).
- [x] T005 Establish IO ticket tracking by creating `docs/metrics/io_ticket_baseline.md` and a helper script (`tools/metrics/io_ticket_tracker.py`) that captures weekly IO-related support ticket counts so reductions toward SC-004 are measurable.

---

## Phase 2: Foundational (Blocking Prerequisites)

Purpose: Establish canonical IO variation data (with IBM reference metadata) and shared fixtures before story work begins.

- [x] T006 Build the authoritative variation catalog by exporting every IBM IO verb/qualifier combination into `specs/001-io-variation-coverage/io-variation-catalog.csv`, tagging each row with the source **IBM Enterprise COBOL for z/OS 6.4 Language Reference (SC27-8949-30, November 2023)** so future updates stay traceable.
- [x] T007 [P] Implement `tools/io_catalog/validate_catalog.py` to verify the catalog entries match IBM reference rules (including version checks) and wire it into pre-commit or CI.
- [x] T008 Create baseline COBOL fixtures for each variation by adding positive samples to `tests/samples/io/positive/` and negative samples to `tests/samples/io/negative/`, ensuring filenames match catalog IDs.
- [x] T009 [P] Add FD-bound fixture coverage by crafting samples that exercise `BLOCK CONTAINS`, `RECORD KEY`, and `ALTERNATE RECORD KEY` clauses, plus a helper test (`tests/unit/io/test_fd_binding_setup.py`) that confirms each IO statement binds to its FD metadata (FR-005).
- [x] T010 [P] Extend `docs/STATEMENT_TEST_COVERAGE_MATRIX.md` with new IO variation rows/columns, referencing `io-variation-catalog.csv` so gaps are visible before implementation.

**Checkpoint**: Catalog + fixtures + documentation hooks ready → User story work can begin.

---

## Phase 3: User Story 1 – Parse every IBM COBOL IO form (Priority: P1) 🎯

Goal: Parser ingests every OPEN/CLOSE/READ/WRITE/REWRITE/DELETE/START/ACCEPT/DISPLAY/UNLOCK variation and produces AST nodes with complete metadata.

Independent Test: Parsing the curated IO suite in COLLECT_ALL mode yields AST + diagnostics that match `contracts/io-statement-ast.md` without fatal errors.

### Tests (write first, ensure they fail)

- [x] T011 [P] [US1] Author contract snapshots in `tests/contracts/io_statements/test_io_statements_contract.py` covering each verb + qualifier; tie expectations to `contracts/io-statement-ast.md`.
- [x] T012 [P] [US1] Add unit tests in `tests/unit/io_statements/test_io_clause_variations.py` covering clause permutations (AT END, INVALID KEY, ADVANCING, WITH LOCK) using fixtures from `tests/samples/io/`.
- [x] T013 [P] [US1] Expand negative/diagnostic suites in `tests/unit/io_statements/test_io_errors.py`, asserting each invalid clause combination emits the `IO_*` codes defined in `contracts/io-statement-ast.md` (FR-004).
- [x] T014 [P] [US1] Add integration programs in `tests/integration/io_statements/test_io_programs.py` that mix sequential/indexed/relative files (with FD metadata) to prove complete AST coverage.

**TDD Gate**: Before T016+ begin, collect evidence (logs or CI artifacts) showing T011–T014 fail and store it in `specs/001-io-variation-coverage/evidence/US1_failing_tests.md`.

### Implementation (after tests fail)

- [ ] T016 [P] [US1] Update IO keyword/token handling in `cobolparser/lexer.py` (including continuation-line rules) so new clauses are recognized.
- [ ] T017 [P] [US1] Extend AST node classes and `to_dict()` implementations in `cobolparser/models/statements.py` per `contracts/io-statement-ast.md` (add metadata fields such as `with_lock`, `advancing_clause`, and FD bindings).
- [ ] T018 [US1] Implement parser productions and error-recovery hooks in `cobolparser/parser.py` to map tokens + clauses into the new AST nodes while preserving SourceLocation data.
- [ ] T019 [US1] Update diagnostics for malformed IO statements by adding `IO_*` error codes and recovery hints in `cobolparser/plugins/core.py` (ErrorRecoveryMode helpers).
- [ ] T020 [US1] Refresh documentation (`docs/file-control.md` and `docs/STATEMENT_TEST_COVERAGE_MATRIX.md`) with the newly supported IO forms and AST examples.
- [ ] T021 [US1] Run the full test + performance suites (guarded by T004) and write post-US1 metrics to `specs/001-io-variation-coverage/baselines/post-us1.json` for regression comparison.

---

## Phase 4: User Story 2 – Guarantee regression coverage (Priority: P2)

Goal: Every IO variation has automated regression tests plus a machine-readable artifact proving coverage status.

Independent Test: Removing support for any variation forces its tests (unit/contract/integration) to fail and the coverage artifact marks the row as `gap`.

### Tests (write first)

- [ ] T022 [P] [US2] Create unit tests for the coverage reporter in `tests/unit/analysis/test_io_coverage_reporter.py`, mocking pytest results to verify aggregation logic.
- [ ] T023 [P] [US2] Add integration tests in `tests/integration/io/test_io_coverage_reporting.py` that run a subset of IO tests and assert the generated artifact matches `contracts/io-coverage-schema.json`.

### Implementation

- [ ] T024 [P] [US2] Implement `cobolparser/analysis/io_coverage_reporter.py` to ingest pytest outputs, attach variation metadata, and emit `io-coverage.json` per the schema.
- [ ] T025 [US2] Add a CLI/utility entry point `tools/io_coverage/generate_artifact.py` plus CI wiring (e.g., `.github/workflows/tests.yml`) so the artifact is published on every run.
- [ ] T026 [US2] Add schema validation to the workflow (e.g., `scripts/validate_io_coverage.py`) ensuring `io-coverage.json` matches `contracts/io-coverage-schema.json` before CI succeeds.
- [ ] T027 [US2] Document artifact consumption in `docs/STATEMENT_TEST_COVERAGE_MATRIX.md` and create `docs/io-coverage/README.md` so QA leads know how to audit coverage results.

---

## Phase 5: User Story 3 – Surface coverage status to maintainers (Priority: P3)

Goal: Provide an at-a-glance report (CLI + docs) listing each IO variation’s support state with links to tests and diagnostics.

Independent Test: Running the summary command or viewing the docs clearly indicates support status for CLOSE WITH NO REWIND or DELETE INVALID KEY, referencing the exact regression tests.

### Tests (write first)

- [ ] T028 [P] [US3] Add unit tests for the summary renderer in `tests/unit/analysis/test_io_coverage_summary.py`, ensuring it maps artifact rows to human-readable entries.
- [ ] T029 [P] [US3] Add documentation integration tests in `tests/integration/docs/test_io_coverage_docs.py` that build the docs and assert the IO coverage table renders with latest data.

### Implementation

- [ ] T030 [P] [US3] Implement the summary renderer script `tools/io_coverage/render_markdown.py` that consumes `io-coverage.json` and outputs Markdown/CSV for docs.
- [ ] T031 [US3] Add a CLI entry point `cobolparser/cli/coverage.py` (or extend existing CLI) to print support status filtered by verb/qualifier.
- [ ] T032 [US3] Update documentation touchpoints (`docs/README.md`, `specs/001-io-variation-coverage/quickstart.md`) to explain how maintainers read the coverage summary and link to tests.
- [ ] T033 [US3] Link coverage rows to diagnostics by updating `docs/STATEMENT_TEST_COVERAGE_MATRIX.md` with anchors pointing to `tests/*` node IDs and the artifact summary.

---

## Phase 6: Polish & Cross-Cutting Concerns

Purpose: Wrap-up tasks affecting all stories.

- [ ] T034 [P] Update `CHANGELOG.md` and release notes (if applicable) summarizing IO coverage support and artifact publication.
- [ ] T035 Re-run the full baseline comparison (tests + performance) and write final metrics to `specs/001-io-variation-coverage/baselines/final.json`, highlighting deviations from T001/T021 and documenting whether SC-002 remains satisfied.
- [ ] T036 [P] Run code-quality gates (`ruff`, `black`, `mypy`) and refresh top-level `README.md` + `docs/` highlights to reflect full IO coverage and the SC-004 ticket-tracking process.

---

## Dependencies & Execution Order

1. **Setup → Foundational**: T001–T005 must finish before catalog/test authoring begins (performance/ticket gates are required guardrails).
2. **Foundational → User Stories**: T006–T010 unlock US1–US3 by supplying catalog metadata, FD-bound fixtures, and documentation hooks.
3. **User Story Sequencing**: US1 (P1) delivers the MVP parser support and MUST complete before US2 and US3 consume its AST/diagnostics. US2 (coverage enforcement) should finish before US3 (reporting) so reports have data.
4. **Polish Phase**: Runs after all desired user stories close; it depends on artifacts and docs from earlier phases.

## Parallel Opportunities

- Tasks marked **[P]** can run concurrently (e.g., T002 & T003 in Setup, T011–T014 test authoring, T016–T017 implementation). Ensure each developer focuses on different files to avoid conflicts.
- Once Foundational tasks complete, individual user stories can proceed in parallel provided shared files are coordinated (e.g., one developer on US1 parser work while another prototypes the coverage reporter scaffolding, but US1 must deliver AST fields before US2 integrates them).

## Implementation Strategy

1. **MVP (User Story 1)**: Finish Phases 1–3 (including the failing-test evidence gate) to unlock end-to-end parsing; this slice is independently testable and demoable.
2. **Incremental Delivery**: After MVP, add User Story 2 (coverage artifact) to secure regression guarantees, then User Story 3 for maintainer visibility.
3. **Quality Gates Every Phase**: At the end of each story, run full pytest + performance suites, validate schema outputs, and update documentation before moving on.

---

**Deliverable**: Completion of these tasks ensures every IO variation is parsed, covered by TDD suites, tracked via machine-readable artifacts, and clearly reported to maintainers without regressing existing functionality.
