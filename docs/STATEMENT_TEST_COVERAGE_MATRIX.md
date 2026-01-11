# COBOL Statement Test Coverage Matrix

**Purpose**: Track TDD progress for all COBOL statement implementations  
**Constitution Compliance**: Principle I (Test-First Development)  
**Last Updated**: 2026-01-11

## Legend

- ✅ **Complete**: All required tests written and passing
- 🟡 **Partial**: Some tests exist but gaps remain
- 🔴 **Missing**: No tests or implementation
- 📝 **Planned**: Specification created, tests pending

## Test Categories (Per Statement)

Each statement requires:
- **Contract Tests** (8-10): AST structure, serialization, backward compatibility
- **Integration Tests** (3-5): Full program parsing, multi-statement workflows
- **Unit Tests** (15+): Syntax variations, clauses, errors, edge cases

**Total Tests per HIGH Priority Statement**: ~30-35 tests  
**Total Tests per MEDIUM Priority Statement**: ~20-25 tests

---

## HIGH Priority Statements (13 statements)

### Arithmetic Operations

| Statement | Status | Contract | Integration | Unit | Total | Notes |
|-----------|--------|----------|-------------|------|-------|-------|
| **COMPUTE** | ✅ Complete | 8/8 ✅ | 5/5 ✅ | 15/15 ✅ | 28/28 | Expressions working |
| **ADD** | 🔴 Missing | 0/10 | 0/5 | 0/20 | **0/35** | **Phase 1 Target** |
| **SUBTRACT** | 🔴 Missing | 0/8 | 0/5 | 0/18 | **0/31** | **Phase 1 Target** |
| **MULTIPLY** | 🔴 Missing | 0/8 | 0/5 | 0/18 | **0/31** | **Phase 1 Target** |
| **DIVIDE** | 🔴 Missing | 0/10 | 0/5 | 0/20 | **0/35** | REMAINDER clause |

**Arithmetic Subtotal**: 28/160 tests (17.5%)

### File I/O Operations

| Statement | Status | Contract | Integration | Unit | Total | Notes |
|-----------|--------|----------|-------------|------|-------|-------|
| **OPEN** | � Planned | 0/8 | 0/5 | 0/15 | **0/28** | INPUT/OUTPUT/I-O/EXTEND (FR-001) |
| **CLOSE** | 📝 Planned | 0/6 | 0/3 | 0/10 | **0/19** | WITH LOCK clause (FR-002) |
| **READ** | 📝 Planned | 0/10 | 0/8 | 0/25 | **0/43** | Complex AT END logic (FR-002) |
| **WRITE** | 📝 Planned | 0/10 | 0/6 | 0/20 | **0/36** | BEFORE/AFTER ADVANCING (FR-002) |
| **REWRITE** | 📝 Planned | 0/8 | 0/4 | 0/15 | **0/27** | INVALID KEY clause (FR-002) |
| **DELETE** | 📝 Planned | 0/8 | 0/4 | 0/15 | **0/27** | INVALID KEY clause (FR-002) |
| **START** | 📝 Planned | 0/6 | 0/3 | 0/12 | **0/21** | Key positioning (FR-001) |
| **UNLOCK** | 📝 Planned | 0/4 | 0/2 | 0/8 | **0/14** | Record unlock (FR-001) |

**File I/O Subtotal (61 variations planned)**: 0/215 tests (0%) | Catalog: [io-variation-catalog.csv](../specs/001-io-variation-coverage/io-variation-catalog.csv)

### Control Flow

| Statement | Status | Contract | Integration | Unit | Total | Notes |
|-----------|--------|----------|-------------|------|-------|-------|
| **IF** | ✅ Complete | 10/10 ✅ | 6/6 ✅ | 22/22 ✅ | 38/38 | Nested IF working |
| **PERFORM** | ✅ Complete | 10/10 ✅ | 8/8 ✅ | 25/25 ✅ | 43/43 | UNTIL/TIMES/VARYING |
| **STOP** | ✅ Complete | 6/6 ✅ | 3/3 ✅ | 8/8 ✅ | 17/17 | STOP RUN |
| **EVALUATE** | 🔴 Missing | 0/12 | 0/8 | 0/30 | **0/50** | Complex WHEN logic |
| **ACCEPT** | � Planned | 0/8 | 0/5 | 0/15 | **0/28** | FROM DATE/TIME/ENV (FR-001) |
| **INITIALIZE** | 🔴 Missing | 0/8 | 0/4 | 0/15 | **0/27** | REPLACING clause |

**Control Flow Subtotal**: 98/203 tests (48.3%)

### Data Manipulation

| Statement | Status | Contract | Integration | Unit | Total | Notes |
|-----------|--------|----------|-------------|------|-------|-------|
| **MOVE** | ✅ Complete | 8/8 ✅ | 5/5 ✅ | 18/18 ✅ | 31/31 | CORRESPONDING working |
| **DISPLAY** | ✅ Complete | 6/6 ✅ | 4/4 ✅ | 12/12 ✅ | 22/22 | UPON clause |

**Data Manipulation Subtotal**: 53/53 tests (100%)

### IBM Dialect Extensions

| Statement | Status | Contract | Integration | Unit | Total | Notes |
|-----------|--------|----------|-------------|------|-------|-------|
| **EXEC SQL** | ✅ Complete | 8/8 ✅ | 6/6 ✅ | 15/15 ✅ | 29/29 | IBM DB2 dialect |
| **EXEC CICS** | ✅ Complete | 6/6 ✅ | 5/5 ✅ | 12/12 ✅ | 23/23 | Transaction commands |
| **EXEC IMS** | ✅ Complete | 4/4 ✅ | 3/3 ✅ | 8/8 ✅ | 15/15 | IMS commands |

**IBM Dialect Subtotal**: 67/67 tests (100%)

### Program Flow

| Statement | Status | Contract | Integration | Unit | Total | Notes |
|-----------|--------|----------|-------------|------|-------|-------|
| **CALL** | ✅ Complete | 12/12 ✅ | 8/8 ✅ | 30/30 ✅ | 50/50 | BY REF/CONTENT/VALUE |
| **ENTRY** | ✅ Complete | 6/6 ✅ | 4/4 ✅ | 10/10 ✅ | 20/20 | Multiple entry points |

**Program Flow Subtotal**: 70/70 tests (100%)

---

## HIGH Priority Summary

| Category | Implemented | Tests Written | Tests Passing | Coverage |
|----------|-------------|---------------|---------------|----------|
| Arithmetic | 1/5 (20%) | 28/160 | 28/160 | 17.5% |
| File I/O | 0/6 (0%) | 0/180 | 0/180 | 0% |
| Control Flow | 3/6 (50%) | 98/203 | 98/203 | 48.3% |
| Data Manip | 2/2 (100%) | 53/53 | 53/53 | 100% |
| IBM Dialect | 3/3 (100%) | 67/67 | 67/67 | 100% |
| Program Flow | 2/2 (100%) | 70/70 | 70/70 | 100% |
| **TOTAL** | **11/24 (46%)** | **316/733** | **316/733** | **43.1%** |

**Gap**: Need **417 additional tests** for HIGH priority statements

---

## MEDIUM Priority Statements (11 statements)

### Control Flow Extensions

| Statement | Status | Contract | Integration | Unit | Total | Notes |
|-----------|--------|----------|-------------|------|-------|-------|
| **EXIT** | 🔴 Missing | 0/6 | 0/3 | 0/12 | **0/21** | EXIT PROGRAM/PARAGRAPH |
| **GOBACK** | 🔴 Missing | 0/6 | 0/3 | 0/10 | **0/19** | Similar to STOP RUN |
| **CONTINUE** | 🔴 Missing | 0/4 | 0/2 | 0/8 | **0/14** | Null statement |

**Control Extensions Subtotal**: 0/54 tests (0%)

### Data Manipulation Extensions

| Statement | Status | Contract | Integration | Unit | Total | Notes |
|-----------|--------|----------|-------------|------|-------|-------|
| **STRING** | 🔴 Missing | 0/8 | 0/5 | 0/20 | **0/33** | DELIMITED BY |
| **UNSTRING** | 🔴 Missing | 0/8 | 0/5 | 0/20 | **0/33** | Complex parsing |
| **INSPECT** | 🔴 Missing | 0/8 | 0/5 | 0/20 | **0/33** | REPLACING/TALLYING |
| **SET** | 🔴 Missing | 0/6 | 0/4 | 0/15 | **0/25** | Index manipulation |

**Data Extensions Subtotal**: 0/124 tests (0%)

### Table & Sorting

| Statement | Status | Contract | Integration | Unit | Total | Notes |
|-----------|--------|----------|-------------|------|-------|-------|
| **SEARCH** | 🔴 Missing | 0/8 | 0/5 | 0/20 | **0/33** | SEARCH ALL binary |
| **SORT** | 🔴 Missing | 0/10 | 0/6 | 0/25 | **0/41** | INPUT/OUTPUT PROCEDURE |
| **MERGE** | 🔴 Missing | 0/8 | 0/4 | 0/18 | **0/30** | File merging |

**Table/Sort Subtotal**: 0/104 tests (0%)

### Program Flow Extensions

| Statement | Status | Contract | Integration | Unit | Total | Notes |
|-----------|--------|----------|-------------|------|-------|-------|
| **CANCEL** | 🔴 Missing | 0/6 | 0/3 | 0/10 | **0/19** | Cancel dynamic programs |
| **RETURN** | 🔴 Missing | 0/6 | 0/3 | 0/12 | **0/21** | SORT/MERGE output |

**Program Extensions Subtotal**: 0/40 tests (0%)

---

## MEDIUM Priority Summary

| Category | Implemented | Tests Written | Tests Passing | Coverage |
|----------|-------------|---------------|---------------|----------|
| Control Extensions | 0/3 (0%) | 0/54 | 0/54 | 0% |
| Data Extensions | 0/4 (0%) | 0/124 | 0/124 | 0% |
| Table/Sort | 0/3 (0%) | 0/104 | 0/104 | 0% |
| Program Extensions | 0/2 (0%) | 0/40 | 0/40 | 0% |
| **TOTAL** | **0/12 (0%)** | **0/322** | **0/322** | **0%** |

**Gap**: Need **322 additional tests** for MEDIUM priority statements

---

## LOW Priority Statements (5 statements)

| Statement | Status | Contract | Integration | Unit | Total | Notes |
|-----------|--------|----------|-------------|------|-------|-------|
| **ALTER** | 🔴 Missing | 0/4 | 0/2 | 0/8 | **0/14** | Deprecated, 2% usage |
| **GO TO** | 🔴 Missing | 0/4 | 0/2 | 0/8 | **0/14** | Discouraged, 10% usage |
| **RELEASE** | 🔴 Missing | 0/6 | 0/3 | 0/10 | **0/19** | SORT-related |
| **START** | 🔴 Missing | 0/6 | 0/3 | 0/12 | **0/21** | Keyed file positioning |
| **JSON/XML** | 🔴 Missing | 0/8 | 0/4 | 0/18 | **0/30** | COBOL 2014+ modern |

**LOW Priority Total**: 0/98 tests (0%)

---

## Overall Test Coverage Summary

| Priority | Statements | Implemented | Tests Written | Tests Needed | Coverage |
|----------|-----------|-------------|---------------|--------------|----------|
| **HIGH** | 24 | 11 (46%) | 316/733 | 417 | 43.1% |
| **MEDIUM** | 12 | 0 (0%) | 0/322 | 322 | 0% |
| **LOW** | 5 | 0 (0%) | 0/98 | 98 | 0% |
| **TOTAL** | **41** | **11 (27%)** | **316/1,153** | **837** | **27.4%** |

**Current Test Count**: 618 total tests (includes lexer, parser infrastructure, copybook, etc.)  
**Statement-Specific Tests**: 316 tests  
**Target Test Count**: 1,153 statement tests (current 618 + 837 new = **1,455 total tests**)

---

## Phase 1 Test Tracking (Arithmetic - Weeks 1-9)

### ADD Statement (Week 1-2) - Target: 35 tests

**Contract Tests (10)**:
- [ ] `test_add_statement_ast_structure` - Verify AST node attributes
- [ ] `test_add_statement_to_dict_serialization` - JSON format
- [ ] `test_add_statement_backward_compatibility` - API stability
- [ ] `test_add_statement_operands_list` - Operand tracking
- [ ] `test_add_statement_targets_list` - Target tracking
- [ ] `test_add_statement_giving_attribute` - GIVING clause
- [ ] `test_add_statement_rounded_attribute` - ROUNDED flag
- [ ] `test_add_statement_on_size_error_attribute` - Error handling
- [ ] `test_add_statement_source_location` - Line/column tracking
- [ ] `test_add_statement_metadata_preservation` - Metadata handling

**Integration Tests (5)**:
- [ ] `test_add_in_full_program` - Complete program with ADD
- [ ] `test_add_multiple_statements` - ADD + other statements
- [ ] `test_add_in_perform_loop` - ADD within PERFORM
- [ ] `test_add_with_if_condition` - ADD in conditional
- [ ] `test_add_error_recovery` - Parser recovery from ADD errors

**Unit Tests (20)**:
- [ ] `test_add_to_simple` - ADD A TO B
- [ ] `test_add_to_multiple_targets` - ADD A TO B C D
- [ ] `test_add_giving` - ADD A B GIVING C
- [ ] `test_add_corresponding` - ADD CORR WS-GROUP1 TO WS-GROUP2
- [ ] `test_add_multiple_operands_to` - ADD A B C TO D
- [ ] `test_add_multiple_operands_giving` - ADD A B C GIVING D
- [ ] `test_add_rounded` - ADD A TO B ROUNDED
- [ ] `test_add_on_size_error` - ADD A TO B ON SIZE ERROR...
- [ ] `test_add_not_on_size_error` - NOT ON SIZE ERROR clause
- [ ] `test_add_both_error_clauses` - ON SIZE ERROR + NOT ON SIZE ERROR
- [ ] `test_add_literal_values` - ADD 100 TO WS-TOTAL
- [ ] `test_add_qualified_names` - ADD WS-VAR OF GROUP1 TO...
- [ ] `test_add_missing_to_keyword` - Error: ADD A B (missing TO)
- [ ] `test_add_invalid_operand` - Error: Invalid operand type
- [ ] `test_add_incomplete_expression` - Error: ADD A TO (no target)
- [ ] `test_add_missing_period` - Error: Statement without period
- [ ] `test_add_continued_across_lines` - Fixed-format continuation
- [ ] `test_add_with_inline_comment` - Modern *> comment
- [ ] `test_add_giving_to_same_variable` - ADD A GIVING A (valid)
- [ ] `test_add_zero_operands` - Error: ADD TO B (no source)

**Total ADD Tests**: 35

### SUBTRACT Statement (Week 3-4) - Target: 31 tests

**Contract Tests (8)**:
- [ ] `test_subtract_statement_ast_structure`
- [ ] `test_subtract_statement_to_dict_serialization`
- [ ] `test_subtract_statement_backward_compatibility`
- [ ] `test_subtract_statement_operands_list`
- [ ] `test_subtract_statement_from_target_attribute`
- [ ] `test_subtract_statement_giving_attribute`
- [ ] `test_subtract_statement_rounded_attribute`
- [ ] `test_subtract_statement_on_size_error_attribute`

**Integration Tests (5)**:
- [ ] `test_subtract_in_full_program`
- [ ] `test_subtract_with_add_multiply` - Mixed arithmetic
- [ ] `test_subtract_in_perform_until`
- [ ] `test_subtract_with_if_else`
- [ ] `test_subtract_error_recovery`

**Unit Tests (18)**:
- [ ] `test_subtract_from_simple` - SUBTRACT A FROM B
- [ ] `test_subtract_from_multiple` - SUBTRACT A FROM B C
- [ ] `test_subtract_giving` - SUBTRACT A FROM B GIVING C
- [ ] `test_subtract_corresponding` - SUBTRACT CORR...
- [ ] `test_subtract_multiple_operands` - SUBTRACT A B FROM C
- [ ] `test_subtract_rounded` - SUBTRACT A FROM B ROUNDED
- [ ] `test_subtract_on_size_error`
- [ ] `test_subtract_not_on_size_error`
- [ ] `test_subtract_both_error_clauses`
- [ ] `test_subtract_literal_values`
- [ ] `test_subtract_qualified_names`
- [ ] `test_subtract_missing_from` - Error
- [ ] `test_subtract_invalid_operand` - Error
- [ ] `test_subtract_incomplete_expression` - Error
- [ ] `test_subtract_continued_across_lines`
- [ ] `test_subtract_with_inline_comment`
- [ ] `test_subtract_negative_result` - Validation
- [ ] `test_subtract_giving_from_same_variable`

**Total SUBTRACT Tests**: 31

### MULTIPLY Statement (Week 5-6) - Target: 31 tests

**Contract Tests (8)**: [Same pattern as SUBTRACT]

**Integration Tests (5)**: [Same pattern as SUBTRACT]

**Unit Tests (18)**:
- [ ] `test_multiply_by_simple` - MULTIPLY A BY B
- [ ] `test_multiply_by_multiple` - MULTIPLY A BY B C
- [ ] `test_multiply_giving` - MULTIPLY A BY B GIVING C
- [ ] `test_multiply_rounded`
- [ ] `test_multiply_on_size_error`
- [ ] `test_multiply_not_on_size_error`
- [ ] `test_multiply_both_error_clauses`
- [ ] `test_multiply_literal_values`
- [ ] `test_multiply_by_zero` - Edge case
- [ ] `test_multiply_by_one` - Edge case
- [ ] `test_multiply_overflow` - SIZE ERROR trigger
- [ ] `test_multiply_qualified_names`
- [ ] `test_multiply_missing_by` - Error
- [ ] `test_multiply_invalid_operand` - Error
- [ ] `test_multiply_incomplete` - Error
- [ ] `test_multiply_continued_across_lines`
- [ ] `test_multiply_with_inline_comment`
- [ ] `test_multiply_giving_to_same_variable`

**Total MULTIPLY Tests**: 31

### DIVIDE Statement (Week 7-8) - Target: 35 tests

**Contract Tests (10)**: [Add REMAINDER attribute]

**Integration Tests (5)**: [Same pattern]

**Unit Tests (20)**:
- [ ] `test_divide_into_simple` - DIVIDE A INTO B
- [ ] `test_divide_by_simple` - DIVIDE A BY B GIVING C
- [ ] `test_divide_by_with_remainder` - DIVIDE A BY B GIVING C REMAINDER D
- [ ] `test_divide_into_multiple` - DIVIDE A INTO B C
- [ ] `test_divide_rounded`
- [ ] `test_divide_on_size_error`
- [ ] `test_divide_not_on_size_error`
- [ ] `test_divide_both_error_clauses`
- [ ] `test_divide_literal_values`
- [ ] `test_divide_by_zero` - SIZE ERROR mandatory
- [ ] `test_divide_remainder_only` - Edge case
- [ ] `test_divide_qualified_names`
- [ ] `test_divide_missing_into_or_by` - Error
- [ ] `test_divide_invalid_operand` - Error
- [ ] `test_divide_incomplete` - Error
- [ ] `test_divide_continued_across_lines`
- [ ] `test_divide_with_inline_comment`
- [ ] `test_divide_giving_to_same_variable`
- [ ] `test_divide_remainder_without_giving` - Error
- [ ] `test_divide_negative_values` - Validation

**Total DIVIDE Tests**: 35

---

## Phase 2 Test Tracking (File I/O - Weeks 10-18)

### Template for Each File Statement

**Contract Tests**: AST structure, serialization, file mode attributes  
**Integration Tests**: Full program with file operations, multi-file scenarios  
**Unit Tests**: All clauses, error conditions, fixed-format edge cases

[Detailed breakdown deferred until Phase 1 complete]

---

## Test Execution Tracking

### Continuous Integration Gates

**Pre-Commit Hook**:
```bash
pytest tests/unit/test_add_statement_unit.py -v
pytest tests/contracts/test_add_statement_contract.py -v
```

**Pre-Push Hook**:
```bash
pytest tests/ --cov=cobolparser --cov-fail-under=90
```

**CI Pipeline (GitHub Actions)**:
```yaml
- name: Run All Tests
  run: pytest tests/ -v --cov=cobolparser --cov-report=html
  
- name: Check Coverage Threshold
  run: |
    if coverage report | grep -q "TOTAL.*9[0-9]%"; then
      echo "Coverage OK"
    else
      echo "Coverage below 90% threshold" && exit 1
    fi
```

### Weekly Test Progress Report Template

```markdown
## Week [N] Test Progress - [Statement Name]

**Target**: [X] tests  
**Completed**: [Y] tests ([Y/X]%)  
**Passing**: [Z] tests ([Z/Y]%)  

**Blockers**: [List any issues]  
**Next Week Goals**: [Tests to complete]  

**Constitutional Compliance**:
- [ ] Tests written before implementation (Principle I)
- [ ] 90%+ coverage maintained (Principle II)
- [ ] Performance benchmarks run (Principle III)
```

---

## Notes

1. **Test-First Mandate**: Per Constitution Principle I, ALL tests must be written and MUST fail before implementation begins.

2. **Coverage Threshold**: Maintain 90%+ coverage per Constitution Principle II. CI pipeline enforces this automatically.

3. **Performance Benchmarking**: After completing each Phase, run `tests/performance/benchmark_parser.py` to ensure <10% degradation (Principle III).

4. **IBM Dialect Priority**: Tests must include IBM-specific syntax (COMP-3 operands, QSAM files, etc.) per Principle V.

5. **Real-World Samples**: Integration tests should use actual enterprise COBOL code patterns, not just synthetic examples.

6. **Fixed-Format Edge Cases**: Every statement requires at least 2 unit tests for continuation characters and multi-line syntax.

---

**Last Review**: 2026-01-11  
**Next Review**: After Phase 1 Week 2 (ADD statement completion)  
**Responsibility**: Core maintainers + TDD compliance audits
