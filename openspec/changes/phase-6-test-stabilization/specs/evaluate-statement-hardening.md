# Spec: EVALUATE Statement Hardening

## Overview

EVALUATE statement is complex with multiple optional clauses (WHEN, ALSO, ANY, TRUE, FALSE, THRU). Factory integration needs validation that all variants parse correctly through AST node creation.

## Requirements

### R1: EVALUATE Base Structure
- EVALUATE selector (expression or literal)
- WHEN clauses with conditions
- WHEN OTHER clause (final fallback)
- END-EVALUATE terminator

### R2: WHEN Condition Variants
- Simple value: `WHEN 1`
- Range: `WHEN 1 THRU 10`
- Multiple subjects: `WHEN 1 ALSO 2 ALSO 3` (ALSO keyword)
- ANY keyword: `WHEN ANY` (matches any value)
- TRUE/FALSE keywords: `WHEN TRUE`, `WHEN FALSE`
- Nested expressions: `WHEN value = X`

### R3: Multiple Selectors
- EVALUATE can have multiple selectors with ALSO
- Each selector has parallel conditions in WHEN clauses
- Factory creates proper AST node hierarchy

### R4: Nested Statements
- WHEN clauses contain procedure division statements
- Statement registry dispatch works correctly
- Nested evaluation statements supported

### R5: AST Node Hierarchy
- EvaluateStatement node created by factory
- WhenClause nodes with proper parent-child relationships
- Selector nodes properly attached
- Condition nodes properly attached

## Acceptance Criteria

- [ ] `test_evaluate_variants_sample` passes
- [ ] Simple WHEN clauses parse correctly
- [ ] WHEN ALSO (multiple subjects) works
- [ ] WHEN ANY, TRUE, FALSE work
- [ ] WHEN THRU (ranges) work
- [ ] WHEN OTHER (fallback) works
- [ ] Nested statements in WHEN block work
- [ ] AST structure matches factory validation
- [ ] Existing EVALUATE tests still pass

## Related Components

- `cobolparser/parsers/statements/evaluate_parser.py` - EVALUATE parsing
- `cobolparser/core/ast_factory.py` - AST node creation validation
- `cobolparser/models/statements.py` - EVALUATE node definitions

## Test Coverage

- New unit tests: EVALUATE variant coverage (20+ tests)
- Integration tests: WHEN clause statement execution
- Regression tests: existing EVALUATE functionality

## Known Issues

- Current implementation may miss ALSO handling
- Range (THRU) parsing may be incomplete
- Multiple selector support may be missing

## Dependencies

- Phase 6.1: Root cause analysis (diagnoses EVALUATE issue structure)
- Phase 5: Factory validation infrastructure
