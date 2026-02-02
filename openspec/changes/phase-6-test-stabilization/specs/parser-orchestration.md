# Spec (Delta): Parser Orchestration

## Overview

Phase 5 parser orchestration completed division parsing delegation. Phase 6 testing reveals error recovery mode not fully integrated. This delta spec ensures CobolParser properly propagates error recovery modes to all divisions with error aggregation.

## Changes Required

### R1: Error Recovery Mode in CobolParser
- `CobolParser.parse()` accepts `error_recovery` parameter
- Parameter is `ErrorRecoveryMode` enum (FAIL_FAST or COLLECT_ALL) 
- Stored in parser state for access by division parsers
- Default: FAIL_FAST (current behavior)

### R2: Mode Propagation to Divisions
- `CobolParser` passes `error_recovery_mode` to `DivisionParserFactory`
- Each division parser receives and respects the mode
- Statement parsers inherit mode from parent division
- Cross-division error aggregation in COLLECT_ALL mode

### R3: Error Aggregation in CobolParser
- `CobolParser` collects errors from all divisions
- ParseResult includes error list with location info
- Errors deduplicated (same error, same location)
- COLLECT_ALL mode returns partial tree with error list
- FAIL_FAST mode stops at first division error

### R4: Backward Compatibility
- Default behavior unchanged (FAIL_FAST, stop on first error)
- Existing `CobolParser.parse(code)` calls work unchanged
- No changes to ParseResult structure (backward compatible)
- Error list always available (empty in FAIL_FAST mode)

## Acceptance Criteria

- [ ] `CobolParser.parse()` accepts error_recovery parameter
- [ ] Mode propagates through all division parsers
- [ ] Error aggregation works end-to-end
- [ ] test_error_recovery_mechanisms passes
- [ ] All existing parser tests still pass
- [ ] Default behavior unchanged (FAIL_FAST)

## Files Modified

- `cobolparser/parser.py` - Add error_recovery parameter to CobolParser.parse()
- `cobolparser/core/exceptions.py` - ErrorRecoveryMode enum
- Integration tests: Validate cross-division error flow

## Related Specs

- `error-recovery-mode-validation` (main capability)
- `factory-architecture` (factory integration)

## Performance Considerations

- Error aggregation minimal overhead (<1% performance)
- FAIL_FAST mode: no performance change
- COLLECT_ALL mode: minimal string allocation for error list
