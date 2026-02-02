# Spec: Test Failure Root Cause Analysis

## Overview

Systematic root cause analysis for all 4 failing tests to identify patterns, integration issues, and failure modes that inform targeted fixes.

## Requirements

### R1: Test Isolation & Diagnostics
- Run each failing test in isolation with verbose output
- Capture full execution traces and stack dumps
- Document expected vs actual AST structure, token streams, error messages
- Create detailed diagnostic report per test

### R2: Failure Categorization
- Categorize failures by component: Lexer (1 test), Parser (2 tests), Orchestration (1 test)
- Identify if rootcause is factory integration, state management, or logic error
- Determine if issue is specific to test or affects real COBOL programs

### R3: Pattern Identification
- Cross-test analysis to identify common patterns
- Example: Does EVALUATE issue show up in similar statement parsers?
- Example: Does continuation handling issue affect other multi-line constructs?

### R4: Documentation
- Deliver `reports/phase6-failure-analysis.md` with:
  - Summary table (test, component, severity, complexity, root cause)
  - Detailed analysis per test with trace logs
  - Proposed fix approach for each test
  - Risk assessment (likelihood of side effects)

## Acceptance Criteria

- [ ] All 4 tests analyzed in isolation
- [ ] AST structure differences documented (expected vs actual)
- [ ] Root cause identified with high confidence for each test
- [ ] Proposed fix approach documented for each test
- [ ] Risk assessment completed
- [ ] Report deliverable: `reports/phase6-failure-analysis.md`

## Related Tests

- `tests/unit/test_evaluate_variants.py::test_evaluate_variants_sample`
- `tests/integration/test_fixed_format_parsing.py::test_fixed_format_auto_detection`
- `tests/unit/test_continuation_cases.py::test_doubled_quote_across_continuation`
- `tests/unit/test_parser.py::TestParserEdgeCases::test_error_recovery_mechanisms`

## Dependencies

- Phase 5 test suite (pytest infrastructure)
- Existing test infrastructure and test data files
