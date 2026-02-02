# Phase 6 Revised Action Plan: Integration Completion Before Stabilization

**Status:** Revised due to Phase 5 integration gaps  

**Original Plan:** 4 failing tests → Phase 6 stabilization

**Actual State:** 262 failing tests, mostly due to:
- Comprehensive test files using old internal APIs (test_parser_comprehensive.py - 87 failures)
- Missing ParseContext propagation (FIXED: 34 tests)
- Remaining integration gaps (262 tests)

---

## Strategic Decision

Rather than attempt to rewrite 87+ tests for old internal interfaces, implement a **Phase 5 Integration Completion** focusing on:

1. **Parse Context Propagation** (30 min work)
   - Add ParseContext creation in all division parser delegations
   - Verify all backward-compatibility methods use context

2. **Error Recovery Mode Integration** (1 hour work)
   - Add error_recovery parameter to CobolParser.parse()
   - Propagate through factory and divisions
   - Test FAIL_FAST and COLLECT_ALL modes

3. **Comprehensive Test Review** (1 hour work)
   - Analyze test_parser_comprehensive.py (87 tests)
   - Decide: update tests OR mark as deprecated
   - Focus limited resources on critical functionality

4. **Critical Path Tests** (prioritize)
   - Contract tests (verify backward compatibility)
   - Integration tests (real COBOL programs)
   - Core functionality tests
   - Defer: internal API coverage tests

---

## Work Completed (Phase 6 Session 1)

✓ Fixed ParseContext missing in statement parser dispatch
✓ Improved test pass rate: 296 → 262 failures (34 test fix)
✓ Identified systemic integration issues
✓ Created comprehensive failure analysis

---

## Recommended Next Steps

**Option A: Complete Phase 5 Integration First** (Recommended)
- 2-3 hours to fix remaining critical integration issues
- Get passing tests to 2600+
- Then proceed with Phase 6 stabilization
- Cleaner working baseline

**Option B: Continue with Adaptive Phase 6**
- Accept that test_parser_comprehensive.py needs rework
- Focus Phase 6 on real functionality
- Schedule comprehensive test update as separate task

**Option C: Partial Sync on Old Tests**
- Update test files to match new architecture
- 8-10 hours significant rewrite effort
- Lower priority, higher cost

---

## Recommended Path Forward

Execute Option A: Quick Phase 5 integration completion (2-3 hours)

### Phase 5-INT.1: Error Recovery Mode Integration (1 hour)
```python
# In CobolParser.parse():
- Add error_recovery parameter
- Create contexts with error modes
- Propagate to divisions
- Test both modes
```

### Phase 5-INT.2: Division Parser Context (30 min)
```python
# Verify all division parsers receive context
# Check factory passes context through
# Spot-check with 5-10 key tests
```

### Phase 5-INT.3: Triage Comprehensive Tests (1 hour)
```python
# Determine which tests are critical
# Update critical ones
# Mark others for future rework
```

---

**Estimated Impact:** 
- Time: +2-3 hours
- Result: Clean 2600+ passing tests baseline
- Risk: Low
- Benefit: Much cleaner Phase 6 work environment

**Recommendation:** Proceed with Phase 5-INT.1-3, then resume Phase 6 with solid foundation
