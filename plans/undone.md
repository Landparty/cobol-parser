# Executive Summary

| Metric | Status |
|--------|--------|
| **Overall Progress** | Phases 0-2 complete (100%), Phase 3 at ~70%, Phase 4 not started (0%) |
| **Test Status** | 116 tests failing (4.9% of 2,349 tests) |
| **Critical Finding** | New parsers exist but dual code paths (registry + old methods) remain |

---

# Completed Work ✅

## Infrastructure (Phases 0-2)

| Component | File | Status |
|-----------|------|--------|
| TokenStream abstraction | `token_stream.py` | ✅ Complete |
| StatementRegistry | `registry.py` | ✅ Complete |
| StatementParser protocol | `interfaces.py` | ✅ Complete |
| Registration system | `parser.py:240-251` | ✅ Complete |

## Statement Parsers Created & Registered

| Parser | File | Status | Lines |
|--------|------|--------|-------|
| DISPLAY | `display_parser.py` | ✅ Complete | 44 |
| MOVE | `move_parser.py` | ✅ Complete | 103 |
| Arithmetic (5) | `arithmetic_parsers.py` | ✅ Complete | 320 |
| CALL | `call_parser.py` | ⚠️ Created but not fully migrated | 283 |
| IF | `if_parser.py` | ⚠️ Created but not fully migrated | 151 |
| PERFORM | `perform_parser.py` | ⚠️ Created but not fully migrated | 414 |
| EVALUATE | `evaluate_parser.py` | ⚠️ Created but not fully migrated | 251 |

---

# Partially Complete Work ⚠️

## Dual Code Paths Issue

The `parse_statement` method tries registry first but falls back to old methods:

### Old Methods Still Present

| Statement | Old Method Location | Lines | Status |
|-----------|---------------------|-------|--------|
| CALL | `parser.py:7258-7576` | 319 | ❌ Should be removed |
| IF | `parser.py:7113-7256` | 144 | ❌ Should be removed |
| PERFORM | `parser.py:5996-6340` | 345 | ❌ Should be removed |
| EVALUATE | `parser.py:6512-6811` | 300 | ❌ Should be removed |

**Total duplicated code:** ~1,108 lines

### Inline Parsing Methods

Legacy inline methods (`_parse_call_inline`, `_parse_if_inline`, etc.) at lines 3376-5280 are still used by sentence parsing - totaling ~2,000 lines of legacy code.

---

# Not Started ❌

## Phase 4: AST Freezing

**Impact:** ~80 AST node classes across 3 files need conversion to `frozen=True` dataclasses

### Example Required Change

```python
@dataclass(frozen=True)
class MoveStatement(Statement):
    target: DataReference
    source: Union[DataReference, Literal]
```

### Files Affected

| File | Nodes |
|------|-------|
| `statements.py` | 80+ nodes |
| `program.py` | Program/Division/Section |
| `data_items.py` | Data definitions |

**Estimated Effort:** ~2,500 lines of parser code changes

---

# Test Failures Analysis

## By Category (116 total failures)

| Category | Count | Severity | Root Cause |
|----------|-------|----------|------------|
| EVALUATE | 8+ | 🔴 HIGH | Selector/subject validation, END-EVALUATE detection |
| IF | 5+ | 🔴 HIGH | THEN/ELSE termination, nested IF handling |
| Preprocessing | 15+ | 🟡 MEDIUM | Line continuation in fixed format |
| Division Context | 5+ | 🟡 MEDIUM | Implicit section creation |
| IO Coverage | 5+ | 🟡 MEDIUM | Analysis infrastructure |
| Other (Real-world) | ~78 | 🟢 VARIES | Complex integration patterns |

---

# Prioritized Remaining Work

## PRIORITY 1: Remove Dual Code Paths (1-2 days)

**Why:** Maintenance burden, confusing architecture, may cause inconsistent behavior

### Tasks

- [ ] Verify all 11 parsers work via registry
- [ ] Run full test suite with registry-only dispatch
- [ ] Remove old methods from `parser.py`:
  - `parse_call_statement()` @ line 7258 (319 lines)
  - `parse_if_statement()` @ line 7113 (144 lines)
  - `parse_perform_statement()` @ line 5996 (345 lines)
  - `parse_evaluate_statement()` @ line 6512 (300 lines)
- [ ] Remove fallback logic in `parse_statement`

**Expected Reduction:** ~1,100 lines from `parser.py`

---

## PRIORITY 2: Fix Failing Tests (2-3 days)

**Critical for production readiness**

### High-Priority Fixes

#### EVALUATE failures (8 tests)

- [ ] Fix selector/subject count validation
- [ ] Fix END-EVALUATE terminator detection
- [ ] Add cross-validation logic

#### IF failures (5 tests)

- [ ] Fix THEN/ELSE termination logic
- [ ] Improve condition expression parsing
- [ ] Handle nested IF statements properly

#### Preprocessing (15 tests)

- [ ] Fix line continuation handling
- [ ] Address fixed-format parsing edge cases

**Approach:** Fix highest-impact categories first (EVALUATE → IF → Preprocessing)

---

## PRIORITY 3: Refactor Inline Methods (3-4 days)

**Architectural debt** - legacy inline parsing

### Methods to Refactor/Remove

| Method | Line | Est. Lines |
|--------|------|------------|
| `_parse_call_inline()` | 3441 | ~200 |
| `_parse_call_exception_handlers()` | 3655 | ~200 |
| `_parse_if_inline()` | 4700 | ~100 |
| `_parse_perform_inline()` | 4149 | ~200 |
| `_parse_evaluate_inline()` | 5010 | ~270 |

**Strategy:** Migrate to registry-based parsing or helper methods in statement parsers

**Expected Reduction:** ~970 additional lines

---

## PRIORITY 4: AST Freezing (4-5 days)

**Phase 4** - Immutable dataclasses

### Phased Approach

1. **Leaf nodes first** - MoveStatement, DisplayStatement (~40 lines changed)
2. **Arithmetic statements** - ADD, SUBTRACT, etc. (~60 lines changed)
3. **Complex statements** - CALL, IF, PERFORM, EVALUATE (~200 lines changed)
4. **Program structure** - Division, Section, Paragraph (~150 lines changed)

**Total refactoring:** ~450 lines across parser files

---

## PRIORITY 5: Missing Statement Implementations (2-3 days)

From plan review - not yet extracted:

| Statement | Complexity | Effort | Notes |
|-----------|------------|--------|-------|
| SEARCH | Medium | 3 hrs | Table search operations |
| STRING/UNSTRING | Medium | 4 hrs | String manipulation |
| GO TO | Low | 1 hr | Control transfer |
| STOP | Low | 1 hr | Program termination |
| ACCEPT | Low | 2 hrs | User input |
| File I/O (READ/WRITE/OPEN/CLOSE) | Medium | 6 hrs | Multiple statements |

These still use old `parser.py` methods at lines 7500-8700.

---

# Architectural Gaps Identified

## 1. Missing Delegation

Current `parse_statement` has 40+ statement types, but only 11 use registry. 27 statements still use old methods.

## 2. Inconsistent Error Handling

- New parsers use `context.error()`
- Old methods use `self.add_error()`
- Need unified error handling strategy

## 3. Stream Synchronization

Registry parsers manipulate `stream._pos` directly at line 6374, which couples implementation to TokenStream internals.

## 4. No Deprecation Path

Old methods should be marked `@deprecated` with removal timeline before deletion.

---

# Effort Estimates

| Task | Estimated Days | Dependencies |
|------|----------------|--------------|
| Remove dual code paths | 1-2 | None |
| Fix 116 failing tests | 2-3 | Remove dual paths |
| Refactor inline methods | 3-4 | Test fixes |
| AST freezing (Phase 4) | 4-5 | Inline refactor |
| Extract remaining statements | 2-3 | Registry stable |
| **TOTAL** | **12-17 days** | Sequential |

---

# Success Metrics

| Metric | Target | Current | Gap |
|--------|--------|---------|-----|
| `parser.py` lines | <6,200 | 8,755 | -2,555 lines |
| Test pass rate | 100% | 95.1% | -4.9% |
| Registry parsers | 27 (all) | 11 | 16 missing |
| Frozen AST nodes | 100% | 0% | 100% |
| Method complexity | <15 | Some 40+ | Needs reduction |

---

# Immediate Recommendations

1. Run test suite to get current failure count (may differ from plan's 116)
2. Remove fallback paths in `parse_statement` for CALL/IF/PERFORM/EVALUATE
3. Fix EVALUATE parser bugs causing 8 test failures
4. Create deprecation timeline for old methods before removal
5. Document registry pattern for future statement additions

> **Next Action:** Start with Priority 1 (remove dual code paths) as it unblocks everything else and reduces maintenance burden immediately.

