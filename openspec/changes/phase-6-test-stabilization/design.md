# Phase 6: Test Stabilization & Coverage Improvement - Design

## Context

**Current State:**
- 2,631 tests passing (99.85% pass rate)
- 4 persistent test failures blocking full suite passage
- 72.36% overall coverage (17.64% gap to 90% target)
- Core modules 91.68% (acceptable), statement/division parsers 40-70% (critical gap)
- Post-Phase 5 factory integration revealed incomplete error recovery integration
- Test suite structure: 38 contract, 17 integration, 59 unit tests across phases

**Constraints:**
- Cannot modify public API (backward compatibility requirement)
- Must maintain Phase 5 performance benchmarks (1.4M nodes/sec factory)
- Error recovery modes must be fully integrated without breaking existing code
- All fixes must include regression tests

**Stakeholders:**
- Core parser team (maintenance of lexer/parser)
- Test framework maintainers (coverage monitoring)
- Integration customers (large COBOL programs)

## Goals / Non-Goals

**Goals:**
1. **Achieve 100% test pass rate** - Fix all 4 failing tests with documented root causes
2. **Reach 90%+ coverage** - Comprehensive test expansion for under-covered modules
3. **Stabilize error recovery** - Full FAIL_FAST/COLLECT_ALL integration validation
4. **Establish standards** - Definition of Done criteria, testing guidelines, code review protocols
5. **Production readiness** - Backward-compatible, performance-stable, fully tested

**Non-Goals:**
- Performance optimization (Phase 5 benchmarks adequate)
- API redesign (backward compatibility required)
- New statement types or dialect support (focus on stability)
- Refactoring existing working code (minimal changes only)

## Decisions

### D1: Five-Phase Implementation Approach

**Decision:** Organize Phase 6 into 5 sequential phases (Root Cause → Fixes → Coverage → Process → Validation)

**Rationale:** 
- Complex multipart work requires structured ordering
- Root causes must be understood before fixes
- Coverage gaps can be addressed in parallel after critical fixes
- Process improvements protect against future regressions

**Alternatives Considered:**
- Single monolithic task list: Would lose visibility and ordering requirements
- Concurrent phases: Would risk interdependencies (e.g., can't improve coverage without understanding failures)
- External contractor: Continuity and deep codebase knowledge argue against outsourcing

### D2: Root Cause Analysis Before Fixes

**Decision:** Conduct detailed investigation of each failing test before implementation

**Rationale:**
- Surface-level fixes often miss underlying issues
- Four distinct root causes require targeted approaches
- Documentation of root causes prevents future regressions
- Clear diagnostic output helps identify similar issues

**Alternatives Considered:**
- Direct implementation: Would miss patterns, create fragile fixes
- Senior engineer review: Adds dependency, slower timeline

### D3: Prioritize Error Recovery and Fixed-Format

**Decision:** Fix error recovery modes (test_error_recovery_mechanisms) and fixed-format detection (test_fixed_format_auto_detection) first

**Rationale:**
- Critical for core parser functionality
- Error recovery affects all downstream error handling
- Fixed-format support needed for legacy COBOL
- Both likely have quick root cause→fix cycles

**Alternative Priority:** EVALUATE first (more complex, needs last)

### D4: Coverage Expansion Through Unit Tests

**Decision:** Create focused unit tests for statement/division parsers rather than integration tests

**Rationale:**
- Statement parsers are highly testable components
- Unit tests provide faster feedback loop
- Less brittle than integration tests
- Easier to debug coverage gaps with isolated units

**Alternatives Considered:**
- Only integration tests: Slower feedback, harder to isolate issues
- Grand integration test suite: Would cover gaps but miss edge cases

### D5: Automated Coverage Monitoring

**Decision:** Implement `scripts/monitor_coverage.py` for continuous tracking

**Rationale:**
- Prevents regression into low coverage
- Identifies coverage trends
- Enables data-driven prioritization
- Supports CI/CD integration

**Alternatives Considered:**
- Manual coverage reports: Requires discipline, easily forgotten
- Third-party tools: Adds external dependency

### D6: Process Documentation Over Enforcement

**Decision:** Create guidelines and checklists (TESTING_GUIDELINES.md, code review checklist) rather than automated enforcement

**Rationale:**
- Team learning and best practices documentation
- Sustainable improvement through process understanding
- Lower friction than strict automated enforcement
- Flexibility for edge cases

**Alternatives Considered:**
- Strict linting enforcement: Would require constant tuning
- No documentation: Process knowledge lost over time

## Risks / Trade-offs

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Test fixes introduce regressions | Medium | High | Comprehensive regression testing before commit |
| Coverage improvement slower than estimated | Medium | Medium | Prioritize high-impact modules (display, move, if, perform) |
| Complex EVALUATE issue in root cause | Medium-High | High | Allocate extra time buffer for EVALUATE statement deep dive |
| Process documentation ignored post-phase | Medium | Low | Team review session on guidelines, CI integration |
| Performance degradation from new tests | Low | High | Benchmark critical parsers before/after |
| File encoding/continuation edge cases | Low | Medium | Comprehensive lexer state trace and logging |

**Trade-offs:**
- **Coverage vs Speed:** Pursuing 90%+ requires comprehensive test expansion (slower) vs 80% baseline (faster). Justified by production readiness requirement.
- **Process Overhead:** Documentation and guidelines add initial overhead but prevent future regressions (net positive).
- **Backward Compatibility:** Cannot modify APIs to simplify fixes, must work within existing constraints.

## Migration Plan

**Phase 1: Root Cause Analysis (Days 1-2)**
- Run full test suite in isolation for each failing test
- Trace execution flows and state changes
- Document diagnostics in reports/phase6-failure-analysis.md
- No code changes, diagnostic only

**Phase 2: Critical Fixes (Days 3-5)**
- Implement fixes for error recovery (1 day)
- Fix fixed-format detection (0.5 day)
- Fix lexer continuation handling (1 day)
- Fix EVALUATE parsing (1.5 days)
- Run full regression suite after each fix
- Commit with regression tests

**Phase 3: Coverage Improvement (Days 6-10)**
- Create statement parser test suite (3 days)
- Create division parser test suite (2 days)
- Integration tests for cross-division validation (1 day)
- Achieve 90%+ coverage target

**Phase 4: Process Improvement (Days 11-12)**
- Document testing guidelines
- Create code review checklist
- Implement coverage monitoring script
- Team review of protocols

**Phase 5: Validation & Sign-off (Day 13)**
- Execute full test suite: 2,635 tests passing
- Verify 90%+ coverage target
- Performance benchmark comparison
- Final review and archive

**Rollback Strategy:**
- All fixes include regression tests
- If fix causes regressions: revert commit, document issue, create separate ticket
- Each fix is independent—can rollback individually

## Open Questions

1. **Q: Should ERROR-RECOVERY changes modify existing statement parsers?**
   - A: Update only ProcedureDivisionParser and CobolParser orchestration—no statement parser changes needed

2. **Q: How to handle test files (IX103A.CBL) that may not exist?**
   - A: Create minimal test fixtures or use fallback detection for missing files

3. **Q: Will EVALUATE fix require grammar changes?**
   - A: Unlikely—likely parser state machine issue, not grammar

4. **Q: Should performance benchmarks be part of CI/CD?**
   - A: Yes—add to pre-commit checklist with tolerance thresholds

5. **Q: Coverage target for new tests?**
   - A: Minimum 80% for new code, aim for 90%+ where possible

---

**Design Status:** Ready for implementation  
**Linked Artifacts:** Phase 6 proposal, test-stabilization action plan (reference)  
**Next:** Create specs for each new capability
