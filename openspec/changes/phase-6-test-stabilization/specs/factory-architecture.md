# Spec (Delta): Factory Architecture

## Overview

Phase 5 factory validation completed, but Phase 6 testing reveals incomplete error recovery mode integration. This delta spec ensures error recovery modes are fully propagated through factory hierarchy with proper aggregation.

## Changes Required

### R1: Error Recovery Mode Propagation
- `ASTNodeFactory` constructor accepts `error_recovery_mode` parameter
- Mode passed through to all child factories
- Mode respected during node validation
- No change to node validation logic, only mode awareness

### R2: Error Aggregation in Factory
- Factory tracks errors during node creation
- Invalid nodes log errors in COLLECT_ALL mode
- FAIL_FAST mode stops immediately on validation error
- Error list accessible via factory's `get_errors()` method

### R3: Factory Integration Tests
- Test error recovery mode passes through factory hierarchy
- Test error aggregation with multiple invalid nodes
- Test FAIL_FAST stops processing
- Backward compatibility with phase 5 factory behavior

## Acceptance Criteria

- [ ] Factory accepts error_recovery_mode parameter
- [ ] Mode propagates to all child factories
- [ ] Error aggregation works in both modes
- [ ] Phase 5 factory tests still pass
- [ ] test_error_recovery_mechanisms passes

## Files Modified

- `cobolparser/core/ast_factory.py` - Add error_recovery_mode support
- `cobolparser/core/factories.py` - DivisionParserFactory passes mode to ASTNodeFactory
- Test files: `tests/unit/test_ast_factory.py` - Add error recovery tests

## Related Specs

- `error-recovery-mode-validation` (main capability)
- `test-failure-root-cause-analysis` (root cause diagnosis)

## Backward Compatibility

- Default mode: FAIL_FAST (current behavior)
- Existing code without mode parameter works unchanged
- No changes to factory public API structure
