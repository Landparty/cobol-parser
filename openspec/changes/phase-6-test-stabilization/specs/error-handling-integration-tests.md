# Spec: Error Handling Integration Tests

## Overview

Cross-division error propagation and recovery testing to ensure errors in one division don't corrupt parsing of subsequent divisions, and error recovery modes function correctly end-to-end.

## Requirements

### R1: Error Propagation
- Data division errors don't prevent procedure division parsing
- Procedure division errors don't break program-level output
- Error list aggregated correctly in COLLECT_ALL mode
- Errors have proper location tracking (line, column, division)

### R2: Cross-Division Scenarios
- Missing required divisions (handled gracefully)
- Divisions out of sequence (error or warning)
- Malformed division headers
- Empty divisions
- Incomplete statements

### R3: Error Recovery Modes
- FAIL_FAST: Parse stops, exception thrown, single error
- COLLECT_ALL: Parse continues, all errors collected, parse completes
- Both modes return parse result with errors list

### R4: Large Program Testing
- 100+ KB COBOL programs parse without crashing
- Performance remains acceptable (>100K lines/sec)
- Memory usage stays within limits (256MB default)

### R5: Realistic Error Scenarios
- Real IBM COBOL programs with minor syntax errors
- Mixed syntax versions (IBM + ANSI compatibility)
- Character encoding edge cases

## Acceptance Criteria

- [ ] 15+ integration tests created
- [ ] All integration tests pass
- [ ] Error propagation validated
- [ ] FAIL_FAST mode tested
- [ ] COLLECT_ALL mode tested
- [ ] Large program parsing tested
- [ ] Performance benchmarks passed
- [ ] No regressions in existing tests

## Deliverables

- `tests/integration/test_error_handling_comprehensive.py` (15+ tests)
- `tests/integration/test_cross_division_parsing.py` (error scenarios)
- Performance benchmark results
- Error aggregation samples

## Test Scenarios

1. Data division type error → procedure division continues
2. Syntax error in procedure → file control still valid
3. Missing file definition → referenced in procedure (error flagged)
4. Multiple syntax errors → all collected in COLLECT_ALL
5. Program with 100+ KB size → parses successfully
6. Mixed dialect syntax → appropriate errors

## Dependencies

- Phase 6.2: Critical fixes (error recovery, fixed-format, lexer, EVALUATE)
- Phase 6.3: Coverage improvement tests complete
