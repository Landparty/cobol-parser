# Spec: Error Recovery Mode Validation

## Overview

Error recovery modes (FAIL_FAST and COLLECT_ALL) are defined but incomplete integration with factory parser architecture. This spec validates both modes work correctly across entire parser hierarchy with proper error aggregation.

## Requirements

### R1: FAIL_FAST Mode Implementation
- Parser stops at first error (existing behavior)
- Error thrown immediately via exception
- No error collection or aggregation
- Performance: zero overhead vs baseline

### R2: COLLECT_ALL Mode Implementation
- Parser collects all errors encountered
- Parsing continues despite syntax errors
- Error aggregation with error deduplication
- Error list available via `parse_result.errors`

### R3: Mode Propagation
- `CobolParser` accepts `error_recovery` parameter
- Mode passed through to `DivisionParserFactory` 
- Mode respected by all division parsers
- Mode respected by statement parsers via factory

### R4: Error Aggregation
- Errors tracked with location information (file, line, column)
- Duplicate errors suppressed (same error, same location)
- Error severity levels: ERROR, warning (optional)
- Parse completes even with critical errors in COLLECT_ALL mode

### R5: Backward Compatibility
- Default mode: FAIL_FAST (existing behavior)
- No API changes to public interface
- Existing code without error_recovery parameter works unchanged

## Acceptance Criteria

- [ ] `test_error_recovery_mechanisms` passes
- [ ] FAIL_FAST mode: stops at first error
- [ ] COLLECT_ALL mode: collects all errors and continues
- [ ] Error mode propagates through all division parsers
- [ ] Error aggregation deduplicates identical errors
- [ ] Existing tests still pass (no regressions)
- [ ] Backward compatibility: default FAIL_FAST mode

## Related Components

- `cobolparser/core/exceptions.py` - ParseError class
- `cobolparser/parser.py` - CobolParser orchestrator
- `cobolparser/parsers/divisions/factory.py` - DivisionParserFactory
- `cobolparser/parsers/divisions/procedure.py` - ProcedureDivisionParser
- All statement parsers (inherit mode from factory)

## Test Coverage

- New unit tests: error mode behavior validation
- Integration tests: cross-division error aggregation
- Regression tests: ensure FAIL_FAST remains default

## Dependencies

- Phase 5: Factory architecture complete
- Phase 6.1: Root cause analysis (diagnoses error recovery issue)
