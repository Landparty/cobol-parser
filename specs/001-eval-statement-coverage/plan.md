# Implementation Plan: COBOL Fixed-Format EVALUATE Coverage

**Branch**: `001-eval-statement-coverage` | **Date**: 2026-01-11 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/001-eval-statement-coverage/spec.md`

**Note**: Generated via `/speckit.plan`; aligns with constitution v1.0.0.

## Summary

Expand COBOL fixed-format EVALUATE support to cover the full IBM catalog (single/multi subjects, ALSO, ANY, THRU/THROUGH, figurative constants, EVALUATE TRUE with AND/OR conditions, WHEN OTHER, nesting) using existing parser/AST patterns. Deliver positive/negative fixtures, deterministic diagnostics, and a variant coverage gate to prevent regressions while maintaining baseline test/coverage targets.

## Technical Context

**Language/Version**: Python 3.13+  
**Primary Dependencies**: Standard library, `pytest`, `pytest-cov`, `ruff`, `black`, `mypy`; internal AST/lexer/parser framework in `cobolparser/`  
**Storage**: N/A (in-memory parsing; optional JSON export)
**Testing**: `python -m pytest tests -v`; contract/integration/unit suites; coverage via `--cov=cobolparser --cov-fail-under=90`  
**Target Platform**: Cross-platform (Windows dev; CI Linux/Windows)  
**Project Type**: CLI/library parser package  
**Performance Goals**: Maintain ≥10k lines/sec parse throughput; lexer ≤30% total parse time; memory <256MB for 50k-line programs; no >10% slowdown vs baseline  
**Constraints**: TDD required; 90%+ coverage; adhere to fixed-format column rules; preserve AST/JSON schema stability  
**Scale/Scope**: Target COBOL programs up to 100k lines; EVALUATE appears in ~60% of programs per coverage docs

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

**Five Core Principles (all MUST pass)**:

1. **Test-First Development (TDD)**: Are test cases written and approved BEFORE implementation begins?
2. **Code Quality Standards**: Does design meet 90%+ test coverage target, include type hints, and have documentation plan?
3. **Performance Requirements**: Have memory limits, parsing speed targets, and benchmarking plans been specified?
4. **User Experience Consistency**: Does API design follow Python conventions with sensible defaults and clear error handling?
5. **IBM Enterprise COBOL Priority**: Are IBM-specific features (COMP-3, EXEC SQL/CICS) considered if relevant?

**Quality Gates**:
- [x] TDD workflow documented (red-green-refactor cycle)
- [x] Test organization follows `tests/{contract,integration,unit}/` structure
- [x] Performance benchmarks identified for this feature (maintain ≥10k lines/sec; no >10% slowdown)
- [x] Error messages include line/column information and recovery suggestions
- [x] JSON serialization includes AST `to_dict()` implementation (Evaluate node will follow existing AST conventions)

**Justification for Any Failed Checks**: N/A (all checks passing)

## Project Structure

### Documentation (this feature)

```text
specs/[###-feature]/
├── plan.md              # This file (/speckit.plan command output)
├── research.md          # Phase 0 output (/speckit.plan command)
├── data-model.md        # Phase 1 output (/speckit.plan command)
├── quickstart.md        # Phase 1 output (/speckit.plan command)
├── contracts/           # Phase 1 output (/speckit.plan command)
└── tasks.md             # Phase 2 output (/speckit.tasks command - NOT created by /speckit.plan)
```

### Source Code (repository root)

```text
cobolparser/
├── lexer.py
├── parser.py
├── models/
│   ├── ast_base.py
│   ├── statements.py
│   └── data_items.py
├── dialects/
│   └── ibm_enterprise.py
├── plugins/
└── preprocess/

tests/
├── unit/
├── integration/
├── contract/
└── samples/

docs/
└── STATEMENT_COVERAGE_*.md (coverage roadmap)
```

**Structure Decision**: Single library package with parser/lexer/models plus tests split into unit/integration/contract; feature artifacts live in `specs/001-eval-statement-coverage/`.

## Implementation Tasks (ordered) with References

1. **Baseline & guardrails** — Run `python -m pytest tests -v`; optional coverage baseline `python -m pytest --cov=cobolparser --cov-fail-under=90`. (Quickstart §1)
2. **AST support** — Add `EvaluateStatement`, `WhenClause`, selectors (Any/Literal/Identifier/Range/Condition) with `to_dict()` per Contracts §AST Contract and Data Model §Entities. (files: `cobolparser/models/statements.py`)
3. **Parser integration** — Implement EVALUATE parsing routine handling subjects/ALSO, TRUE/FALSE with AND/OR, WHEN selectors (ANY, THRU/THROUGH, figurative constants), WHEN OTHER, END-EVALUATE; enforce fixed-format columns using existing helpers. (Research §Decision 2; Data Model §Validation Rules; file: `cobolparser/parser.py`)
4. **Diagnostics** — Emit deterministic diagnostics (missing WHEN/END-EVALUATE, selector mismatch, invalid THRU/THROUGH, fixed-format misalignment) with line/column per Contracts §Diagnostic Contract and Data Model §Diagnostic Record. (parser + diagnostics plumbing)
5. **Positive tests** — Add unit/contract cases for each cataloged variant (single/multi subject, ANY, ranges, figurative constants, TRUE with AND/OR, WHEN OTHER, nesting, continuation handling). (Contracts §Positive Coverage Matrix; Spec FR-004/FR-006)
6. **Negative tests** — Add malformed cases (missing WHEN, missing END-EVALUATE, selector count mismatch, invalid THRU/THROUGH, misaligned columns, disallowed selector mixes). (Contracts §Negative Coverage Matrix; Spec FR-005)
7. **Coverage gate** — Implement/extend variant coverage report and CI gate that fails when any catalog entry lacks passing positive+negative coverage. (Contracts §Regression Gate; Spec FR-006)
8. **Performance sanity** — Re-run full tests; ensure no >10% slowdown, lexer share ≤30%, memory <256MB for 50k lines. (Research §Decision 5; Plan Technical Context)
9. **Documentation** — Add `EvaluateStatement` docstring/schema; update statement coverage docs if needed (`docs/STATEMENT_COVERAGE_*`). (Quickstart §6)
10. **Final regression** — `python -m pytest tests -v` and coverage gate; ensure variant gate passes. (Quickstart §4)

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| [e.g., 4th project] | [current need] | [why 3 projects insufficient] |
| [e.g., Repository pattern] | [specific problem] | [why direct DB access insufficient] |
