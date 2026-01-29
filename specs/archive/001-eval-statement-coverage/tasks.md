# Tasks: COBOL Fixed-Format EVALUATE Coverage

**Input**: Design documents from `/specs/001-eval-statement-coverage/`
**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, data-model.md, contracts/

**Constitution Compliance**: Follows TDD—write tests first and see them fail before implementation.

**Format**: `- [ ] T### [P?] [Story] Description with file path`

---
## Phase 1: Setup (Shared Infrastructure)
**Purpose**: Baseline to guard regressions.
- [ ] T001 Run baseline tests before changes (`python -m pytest tests -v`) 
- [ ] T002 Optional baseline coverage (`python -m pytest --cov=cobolparser --cov-fail-under=90`)
**Status**: Queued after US1 completion; establishes regression baseline.

---
## Phase 2: Foundational (Blocking Prerequisites)
**Purpose**: Verify existing infrastructure for diagnostics/negative tests.
- [ ] T003 Confirm existing diagnostics plumbing and fixed-format helpers ready (review `cobolparser/parser.py`, `cobolparser/lexer.py`)
**Status**: Prerequisite for US2; needed to support negative test error messages.

---
## Phase 3: User Story 1 - Validate all fixed-format EVALUATE variants (Priority: P1) 🎯 MVP
**Goal**: Parse all fixed-format EVALUATE variants into consistent AST.
**Independent Test**: Positive EVALUATE variant suite passes standalone.
**Status**: ✅ COMPLETE — All 5 tests passing; AST subjects/selectors/defaults verified.

### Tests (write first; must fail initially)
- [X] T010 [P] [US1] Unit positive variants in `tests/unit/test_evaluate_variants.py`
- [X] T011 [P] [US1] Contract serialization cases in `tests/contract/test_evaluate_serialization.py`
- [X] T012 [P] [US1] Integration sample coverage in `tests/integration/test_evaluate_samples.py` using `tests/samples/*.cbl`

### Implementation (after tests are red)
- [X] T013 [P] [US1] Add `EvaluateStatement`, `WhenClause`, selectors to `cobolparser/models/statements.py` with `to_dict()`
- [X] T014 [US1] Implement EVALUATE parsing (subjects/ALSO, TRUE/FALSE with AND/OR, WHEN selectors, WHEN OTHER, END-EVALUATE) in `cobolparser/parser.py`
- [X] T015 [US1] Ensure figurative constants/THRU-THROUGH/ALSO ordering preserved in AST (tests from T010/T011)
- [X] T016 [US1] Update/extend samples for positive variants in `tests/samples/control_flow.cbl` (or new sample) aligned with T012
- [X] T017 [US1] GREEN check: rerun US1 test set (`pytest tests/unit/test_evaluate_variants.py tests/contract/test_evaluate_serialization.py tests/integration/test_evaluate_samples.py`)

---
## Phase 4: User Story 2 - Surface clear diagnostics for malformed EVALUATE (Priority: P2)
**Goal**: Deterministic, line/column diagnostics for malformed fixed-format EVALUATE.
**Independent Test**: Negative EVALUATE suite reports expected diagnostics, parser stays stable.
**Status**: ✅ COMPLETE — All 31 tests passing (15 unit + 16 contract); diagnostics verified.

### Tests (write first; must fail initially)
- [X] T020 [P] [US2] Negative unit cases (missing WHEN/END-EVALUATE, selector mismatch, invalid THRU/THROUGH) in `tests/unit/test_evaluate_diagnostics.py`
- [X] T021 [P] [US2] Contract diagnostics expectations in `tests/contract/test_evaluate_diagnostics.py`

### Implementation (after tests are red)
- [X] T022 [US2] Implement diagnostic paths in `cobolparser/parser.py` (deterministic messages, line/column)
- [X] T023 [US2] Confirm fixed-format column/continuation validation via normalize_fixed_format and token locations
- [X] T024 [US2] Confirm diagnostics include context/category per contract (Data Model §Diagnostic Record)
- [X] T025 [US2] GREEN check: rerun US2 test set (`pytest tests/unit/test_evaluate_diagnostics.py tests/contract/test_evaluate_diagnostics.py`)

---
## Phase 5: User Story 3 - Maintain regression guardrails for EVALUATE support (Priority: P3)
**Goal**: Variant coverage gate prevents regressions.
**Independent Test**: Coverage gate fails if any cataloged variant lacks passing positive+negative tests.
**Status**: ✅ COMPLETE — 15 coverage gate tests passing; catalog with 24 positive + 12 negative variants.

### Tests/Scaffolding
- [X] T030 [P] [US3] Add variant coverage matrix fixtures/index in `tests/contract/test_evaluate_coverage_gate.py`

### Implementation
- [X] T031 [US3] Implement coverage report/gate logic (script or test helper) in `tests/contract/test_evaluate_coverage_gate.py`
- [X] T032 [US3] Wire catalog reference from Contracts to gate (ensure missing variant detection)
- [X] T033 [US3] GREEN check: run coverage gate only (`pytest tests/contract/test_evaluate_coverage_gate.py`)

---
## Phase N: Polish & Cross-Cutting
**Status**: ✅ COMPLETE — Documentation updated, docstrings enhanced, performance verified.

- [X] T040 [P] Update docs (`docs/STATEMENT_COVERAGE_SUMMARY.md`, `docs/EVALUATE_COVERAGE.md`) with EVALUATE coverage status
- [X] T041 [P] Add `EvaluateStatement` docstring/schema notes in `cobolparser/models/statements.py`
- [X] T042 Performance sanity: full EVALUATE suite `pytest tests/.../test_evaluate*.py` runs in <1s; no regressions
- [X] T043 Final coverage: EVALUATE tests pass (51 tests across 3 user stories)

---
## Dependencies & Execution Order
- Setup → Foundational → US1 → US2 → US3 → Polish.
- Within each story: Tests (fail first) → Implementation → GREEN check.
- Tasks marked [P] can run in parallel when files/deps do not conflict.

## Parallel Examples
- US1 tests T010/T011/T012 can be authored in parallel (distinct files).
- AST node (T013) can proceed in parallel with sample prep (T016) once tests are written.
- Coverage gate tasks T030/T031 can run while docs updates (T040) proceed.

## Implementation Strategy
- MVP: Complete US1 (tests then implementation) and validate independently.
- Incremental: US2 diagnostics after US1 green; US3 gate after US2.
- Always rerun targeted tests after each story, then full suite before close.
