# COBOL Statement Coverage - Quick Reference

**Status**: 2026-01-11  
**Coverage**: 12/41 statements (29%) | 367/1,169 tests (31.4%)

## 📊 At-a-Glance Status

| Priority | Statements | Done | In Progress | To Do | Test Coverage |
|----------|-----------|------|-------------|-------|---------------|
| 🔴 HIGH | 24 | 12 | 0 | 12 | 47.2% (367/778) |
| 🟡 MEDIUM | 12 | 0 | 0 | 12 | 0% (0/322) |
| 🟢 LOW | 5 | 0 | 0 | 5 | 0% (0/98) |
| **TOTAL** | **41** | **12** | **0** | **29** | **31.4%** (367/1,169) |

## ✅ Implemented (12 statements)

| Statement | Test Count | Usage Frequency |
|-----------|-----------|-----------------|
| MOVE | 31 tests | 95% of programs |
| DISPLAY | 22 tests | 85% of programs |
| PERFORM | 43 tests | 90% of programs |
| IF | 38 tests | 95% of programs |
| CALL | 50 tests | 70% of programs |
| COMPUTE | 28 tests | 60% of programs |
| STOP | 17 tests | 99% of programs |
| ENTRY | 20 tests | 15% of programs |
| EXEC SQL | 29 tests | 50% of programs (IBM) |
| EXEC CICS | 23 tests | 40% of programs (IBM) |
| EXEC IMS | 15 tests | 10% of programs (IBM) |
| **EVALUATE** | **51 tests** | **60% of programs** |

## 🔴 HIGH Priority Gaps (13 statements)

**Need 417 tests**

### Arithmetic (4 statements - Phase 1)
- ❌ **ADD** - 75% frequency, 35 tests needed
- ❌ **SUBTRACT** - 70% frequency, 31 tests needed
- ❌ **MULTIPLY** - 65% frequency, 31 tests needed
- ❌ **DIVIDE** - 65% frequency, 35 tests needed

**Phase 1 Target**: Weeks 1-9, **132 tests total**

### File I/O (6 statements - Phase 2)
- ❌ **OPEN** - 85% frequency, 28 tests needed
- ❌ **CLOSE** - 85% frequency, 19 tests needed
- ❌ **READ** - 85% frequency, 43 tests needed (most complex)
- ❌ **WRITE** - 80% frequency, 36 tests needed
- ❌ **REWRITE** - 60% frequency, 27 tests needed
- ❌ **DELETE** - 60% frequency, 27 tests needed

**Phase 2 Target**: Weeks 10-18, **180 tests total**

### Control Flow (2 statements - Phase 3)
- ✅ **EVALUATE** - 60% frequency, 51 tests COMPLETE (2026-01-11)
- ❌ **ACCEPT** - 70% frequency, 28 tests needed
- ❌ **INITIALIZE** - 65% frequency, 27 tests needed

**Phase 3 Target**: Weeks 19-27, **55 tests total**

## 🟡 MEDIUM Priority (12 statements - Phases 4-5)

**Need 322 tests**

- EXIT, GOBACK, CONTINUE (control flow)
- STRING, UNSTRING, INSPECT, SET (data manipulation)
- SEARCH, SORT, MERGE (table operations)
- CANCEL, RETURN (program flow)

## 📋 Implementation Roadmap

| Phase | Weeks | Statements | Tests | Status |
|-------|-------|-----------|-------|--------|
| **Phase 1** | 1-9 | Arithmetic (4) | 132 | 📝 Planning |
| **Phase 2** | 10-18 | File I/O (6) | 180 | ⏸️ Pending |
| **Phase 3** | 19-27 | Control Flow (3) | 105 | ⏸️ Pending |
| **Phase 4** | 28-35 | Data Manip (4) | 180 | ⏸️ Pending |
| **Phase 5** | 36-42 | Table Ops (3) | 150 | ⏸️ Pending |

**Total Timeline**: 42 weeks to 100% coverage

## 🎯 Next Actions

1. **This Week**: Run `/speckit.specify` for Phase 1 (Arithmetic Statements)
2. **Week 1-2**: Implement ADD statement (TDD: write 35 tests first!)
3. **Week 3-4**: Implement SUBTRACT statement (31 tests)
4. **Week 5-6**: Implement MULTIPLY statement (31 tests)
5. **Week 7-8**: Implement DIVIDE statement (35 tests)
6. **Week 9**: Integration testing + performance benchmarking

## 📚 Documentation

- **Gap Analysis**: `docs/STATEMENT_COVERAGE_GAP_ANALYSIS.md` (comprehensive details)
- **Test Matrix**: `docs/STATEMENT_TEST_COVERAGE_MATRIX.md` (test tracking)
- **Constitution**: `.specify/memory/constitution.md` (TDD principles)

## 🏛️ Constitutional Compliance

All implementations MUST follow:
- ✅ **Principle I**: Tests written FIRST, must FAIL before implementation
- ✅ **Principle II**: 90%+ test coverage, type hints, docstrings
- ✅ **Principle III**: Performance degradation <10% per phase
- ✅ **Principle IV**: Clear error messages with line/column info
- ✅ **Principle V**: IBM Enterprise COBOL features prioritized

## 📈 Success Metrics

| Metric | Current | Phase 1 Target | Final Target |
|--------|---------|---------------|--------------|
| Statement Coverage | 29% (12/41) | 37% (15/41) | 100% (41/41) |
| Test Count | 667 tests | 750 tests | 1,455 tests |
| Test Coverage % | 90%+ (current) | 90%+ (maintain) | 90%+ (maintain) |
| Parsing Speed | 10K lines/sec | 9.5K lines/sec | 9K lines/sec |

---

**Quick Start Command**:
```bash
# Create Phase 1 specification
/speckit.specify Implement COBOL arithmetic statements (ADD, SUBTRACT, MULTIPLY, DIVIDE) with full syntax support including GIVING, ROUNDED, ON SIZE ERROR clauses for IBM Enterprise COBOL fixed-format compatibility
```
