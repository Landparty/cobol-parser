# Phase 6: Test Stabilization & Coverage Improvement - Proposal

## Why

Following Phase 5's successful factory optimization (2,631 tests passing), systematic test stabilization is critical for production readiness. Current state reveals:

- **4 failing tests** blocking full suite passage (test_evaluate_variants_sample, test_fixed_format_auto_detection, test_doubled_quote_across_continuation, test_error_recovery_mechanisms)
- **72.36% overall coverage** vs 90%+ target (17.64% gap)
- **Core module coverage 91.68%** but statement/division parsers critically under-covered (40-70%)
- **Critical component gaps**: Error recovery mechanisms not fully integrated post-factory refactoring, lexer continuation handling incomplete, EVALUATE statement parsing needs hardening

These gaps create technical debt, reduce reliability on real COBOL programs, and prevent production deployment. Phase 6 establishes test-driven stabilization protocols to achieve 90%+ coverage with 100% passing tests.

## What Changes

- **Root cause analysis** for all 4 failing tests with detailed diagnostics
- **Critical fixes** for error recovery modes (FAIL_FAST/COLLECT_ALL), fixed-format detection, lexer continuation handling, EVALUATE parsing
- **Comprehensive test expansion** for statement/division parsers (40+ new tests)
- **Coverage improvement** from 72% to 90%+ with focus on high-impact modules
- **Process improvements**: Definition of Done criteria, test coverage monitoring, regression prevention protocols
- **Documentation**: Testing guidelines, coverage requirements, code review protocols

## Capabilities

### New Capabilities

- `test-failure-root-cause-analysis`: Systematic root cause identification for all failing tests with diagnostic protocols
- `error-recovery-mode-validation`: FAIL_FAST and COLLECT_ALL modes fully integrated and tested across parser hierarchy
- `fixed-format-detection`: Robust fixed-format vs free-format column detection with backward compatibility
- `lexer-continuation-improvement`: Multi-line string/continuation handling with proper quote escaping preservation
- `evaluate-statement-hardening`: EVALUATE statement parsing with comprehensive WHEN/ALSO/ANY/TRUE handling
- `statement-parser-coverage`: Comprehensive test suite for all statement parsers (>90% individual coverage)
- `division-parser-coverage`: Comprehensive test suite for all division parsers (>90% individual coverage)
- `error-handling-integration-tests`: Cross-division error propagation and recovery testing
- `test-monitoring-process`: Automated coverage tracking, trend analysis, and regression prevention

### Modified Capabilities

- `factory-architecture`: Error recovery mode needs full integration throughout parser hierarchy
- `parser-orchestration`: Error aggregation and recovery mode support needs validation across divisions
- `ast-node-hierarchy`: No spec-level changes, but requires validation with expanded test coverage

## Impact

**Code Areas:**
- `cobolparser/core/`: Error recovery mode implementation
- `cobolparser/lexer.py`: Continuation handling improvements
- `cobolparser/parsers/statements/`: Statement parser test expansion
- `cobolparser/parsers/divisions/`: Division parser test expansion

**APIs:**
- `CobolParser.parse()` error recovery mode behavior
- Error aggregation in `COLLECT_ALL` mode
- Lexer continuation state machine

**Tests:**
- 40+ new unit tests for statement/division parsers
- 15+ new integration tests for cross-division validation
- Full regression test suite validation

**Deliverables:**
- Phase 6 completion: All tests passing (2,635+)
- Coverage: 90%+ overall, 95%+ core modules
- Documentation: Testing guidelines, coverage requirements, PHASE6_COMPLETE.md

---

**Timeline:** 10-13 days (Phases 1-5 delivered)

**Success Criteria:** 100% test pass rate, 90%+ coverage, production-ready stability, comprehensive testing protocols established
