# Phase 3: Coverage Improvement Strategy

## Current Coverage Baseline
- **Overall Coverage**: 44.83% (147 failures, 2397 passes)
- **Target Coverage**: 90%+ 
- **Gap**: ~45 percentage points

## Key Failing Test Categories (Highest Priority)

### 1. PERFORM Statement Parsers (20+ failures)
- `test_perform_until_nested.py` (11 failures)
- `test_perform_statement_coverage.py` (10 failures)
- `test_perform_backward_compat.py` (8 failures)
- `test_perform_thru.py` (5 failures)

**Priority**: HIGH  
**Reason**: PERFORM is core COBOL control flow; extensively used in real programs

### 2. IF Statement Parsers (15+ failures)
- `test_if_complete.py` (12 failures)
- `test_control_flow_basic.py` (6 failures)

**Priority**: HIGH  
**Reason**: IF is fundamental conditional statement

### 3. CALL Statement Parsers (10+ failures)
- `test_call_diagnostics.py` (3 failures)
- `test_call_basic_parsing.py` (3 failures)
- `test_real_world_patterns.py` (1 CALL test failure)

**Priority**: HIGH  
**Reason**: CALL statements enable modular programming

### 4. EVALUATE Statement Diagnostics (12 failures)
- `test_evaluate_statement_diagnostics.py` (12 failures)

**Priority**: MEDIUM  
**Reason**: EVALUATE is important but we already have variants tests working

### 5. COPY Statement Handling (3 failures)
- `test_copybook_expansion_contracts.py` (2 failures)

**Priority**: CRITICAL  
**Reason**: COPY is essential for modular COBOL; affects data item parsing

### 6. Move Advanced Patterns (3 failures)
- `test_move_advanced.py` (3 failures)

**Priority**: MEDIUM  
**Reason**: MOVE with CORRESPONDING and multiple targets are specialized

### 7. Data Definition Parsing (4 failures)
- `test_parser.py` - Data definition tests (4 failures)
- `test_real_world_patterns.py` - Complex PIC clauses, REDEFINES, OCCURS

**Priority**: HIGH  
**Reason**: Data definitions are parsed for every COBOL program

## Proposed Phase 3.2 Test Suite: Statement Parsers

### Create High-Impact Comprehensive Tests

1. **PerformStatementParser Comprehensive** (20+ tests)
   - File: `tests/unit/test_perform_parser_comprehensive.py`
   - Target coverage: PERFORM UNTIL, PERFORM TIMES, PERFORM VARYING
   - Include: nested performs, inline performs, thru paragraphs

2. **IfStatementParser Comprehensive** (15+ tests)
   - File: `tests/unit/test_if_parser_comprehensive.py`
   - Target coverage: IF...END IF, nested IFs, ELSE IF chains
   - Include: conditions, evaluations, END IF requirements

3. **CallStatementParser Comprehensive** (12+ tests)
   - File: `tests/unit/test_call_parser_comprehensive.py`
   - Target coverage: Static and dynamic CALLS, USING, RETURNING
   - Include: error cases (missing program), parameter passing

4. **MoveStatementParser Comprehensive** (15+ tests)
   - File: `tests/unit/test_move_parser_comprehensive.py`
   - Target coverage: Simple MOVE, MOVE CORRESPONDING, multiple targets
   - Include: data conversions, picture clause interactions

5. **EvaluateStatementParser Comprehensive** (15+ tests)
   - File: `tests/unit/test_evaluate_parser_comprehensive.py`
   - Target coverage: Diagnostics already have some tests; add edge cases
   - Include: WHEN OTHER, ALSO chains, conditions

## Proposed Phase 3.3 Test Suite: Division Parsers

### Create Comprehensive Division Tests

1. **DataDivisionParser Comprehensive** (18+ tests)
   - File: `tests/unit/test_data_division_comprehensive.py`
   - Target coverage: Data items, OCCURS, REDEFINES, picture clauses
   - Include: PICTURE clause complexity, COMP-3 handling, USAGE clauses

2. **IdentificationDivisionParser Comprehensive** (8+ tests)
   - File: `tests/unit/test_identification_division_comprehensive.py`
   - Target coverage: PROGRAM-ID variations already tested; add OPTIONS, clauses

3. **ProcedureDivisionParser Comprehensive** (15+ tests)
   - File: `tests/unit/test_procedure_division_comprehensive.py`
   - Target coverage: Section/paragraph handling, statement sequencing
   - Include: GET ALL STATEMENTS functionality

## Proposed Phase 3.4 Test Suite: Integration & Cross-Functional

### Create Integration Tests

1. **Copy Statement Integration** (10+ tests)
   - File: `tests/integration/test_copybook_integration_comprehensive.py`
   - Target coverage: COPY in DATA/PROCEDURE div, nested copies, expansion

2. **Mixed Statement Sequences** (12+ tests)
   - File: `tests/integration/test_mixed_statement_sequences.py`
   - Target coverage: Real-world multi-statement scenarios

## Coverage Impact Analysis

### Expected Coverage Improvement

| Category | Tests Added | Est. Coverage Gain | Cumulative |
|----------|-------------|-------------------|-----------|
| PERFORM  | 20          | +8%               | 52.83%    |
| IF       | 15          | +6%               | 58.83%    |
| CALL     | 12          | +4%               | 62.83%    |
| MOVE     | 15          | +5%               | 67.83%    |
| Data Div | 18          | +8%               | 75.83%    |
| EVALUATE | 15          | +3%               | 78.83%    |
| Other    | 20          | +11%              | 89.83%    |
| **TOTAL**| **115+**   | **+45%**          | **90%+** |

## Risk Mitigation

### Potential Issues & Mitigations
1. **Breaking Changes**: Validate backward compatibility with contract tests
2. **Complex AST Interactions**: Focus on black-box testing, not implementation details
3. **Performance Impact**: Monitor test execution time; target <5 seconds per file
4. **Coverage False Positives**: Mark unreachable code with `# pragma: no cover`

## Next Actions for Phase 3

1. **3.1 - Baseline**: Generate detailed coverage report ✓ (done)
2. **3.2 - Statement Tests**: Create 60-70 statement parser comprehensive tests
3. **3.3 - Division Tests**: Create 40+ division parser comprehensive tests  
4. **3.4 - Integration**: Create 20+ cross-functional integration tests
5. **3.5 - Verification**: Run full suite and verify 90%+ coverage

## Timeline Estimation

- **3.2**: ~6 hours (60-70 tests)
- **3.3**: ~5 hours (40+ tests)
- **3.4**: ~4 hours (20+ tests)
- **3.5**: ~2 hours (verification, fixes)
- **Total Phase 3**: ~17-20 hours

---

**Current Status**: Phase 3.1 baseline complete. Ready to proceed with 3.2 test creation.
