# Tasks: Phase 6-FIX-1 Critical Path

## Fix 1: CALL.is_dynamic Attribute (Hour 1 - Low Risk)

### 1.1 Add is_dynamic Attribute
- [ ] Open cobolparser/models/statements.py
- [ ] Find CallStatement class
- [ ] Add `is_dynamic: bool = False` to __init__()
- [ ] Add `set_is_dynamic(value: bool)` method
- [ ] Update to_dict() to include is_dynamic

### 1.2 Update CallStatementParser
- [ ] Open cobolparser/parsers/statements/call_parser.py
- [ ] Find parse() method
- [ ] Add logic: if target is identifier (not quoted literal), set is_dynamic = True
- [ ] Test static call: CALL "PROG" -> is_dynamic = False
- [ ] Test dynamic call: CALL WS-PROG-NAME -> is_dynamic = True

### 1.3 Validation
- [ ] Run: `pytest tests/contracts/test_dynamic_call_contract.py -v`
- [ ] Verify: all 12 tests pass
- [ ] Check: is_dynamic populated in AST output

---

## Fix 2: Fixed-Format Auto-Detection (Hour 1.5 - Low Risk)

### 2.1 Review Lexer Detection
- [ ] Open cobolparser/lexer.py
- [ ] Find auto_detect_format logic
- [ ] Verify numeric columns 1-6 detection exists
- [ ] Check preprocess_fixed parameter handling

### 2.2 Fix Detection Logic
- [ ] Ensure first line sequence number detection works
- [ ] Strip columns 1-6 when fixed-format detected
- [ ] Respect continuation indicator in column 7

### 2.3 Validation
- [ ] Run: `pytest tests/integration/test_fixed_format_parsing.py -v`
- [ ] Verify: test_fixed_format_auto_detection passes
- [ ] Check: 12 fixed-format tests passing

---

## Fix 3: EVALUATE Parser Population (Hour 2-3 - Medium Risk)

### 3.1 Verify Registration
- [ ] Open cobolparser/core/registry.py
- [ ] Check if EVALUATE parser registered
- [ ] If missing, add EvaluateStatementParser to registry
- [ ] Add debug logging to dispatcher

### 3.2 Investigate parse() Execution
- [ ] Add print statements to EvaluateStatementParser.parse()
- [ ] Verify parse() method called for EVALUATE tokens
- [ ] Check ParseContext parameter passed

### 3.3 Fix Subject Population
- [ ] Find subject parsing loop in parse() method
- [ ] Verify stmt.add_subject() called for each subject
- [ ] Handle ALSO keyword for multiple subjects
- [ ] Test with simple EVALUATE WS-GRADE

### 3.4 Fix WHEN Clause Population
- [ ] Find WHEN clause parsing loop
- [ ] Verify stmt.add_when_clause() called
- [ ] Populate selectors correctly
- [ ] Handle WHEN OTHER as default_when

### 3.5 Validation
- [ ] Run: `pytest tests/unit/test_evaluate_variants.py -v`
- [ ] Verify: test_single_subject_literals_and_ranges passes
- [ ] Verify: test_multiple_subjects_any_and_also passes
- [ ] Verify: test_evaluate_true_with_conditions_and_or passes

---

## Fix 4: Error Diagnostics (Hour 4-5 - Medium Risk)

### 4.1 Verify ParseContext Error Methods
- [ ] Open cobolparser/core/interfaces.py
- [ ] Find ParseContext class
- [ ] Verify error() method exists
- [ ] Check error() adds to host errors

### 4.2 Add Diagnostic Calls
- [ ] Open cobolparser/parsers/statements/evaluate_parser.py
- [ ] Add context.error() for missing END-EVALUATE
- [ ] Add context.error() for missing WHEN clauses
- [ ] Ensure errors not fatal (COLLECT_ALL mode)

### 4.3 Expand to Other Parsers
- [ ] Add error() calls to CallStatementParser
- [ ] Add error() calls to MoveStatementParser
- [ ] Add error() calls to other statement parsers as needed

### 4.4 Validation
- [ ] Run: `pytest tests/contracts/test_evaluate_diagnostics.py -v`
- [ ] Verify: test_diagnostic_has_message passes
- [ ] Run: `pytest tests/contracts/test_call_diagnostics.py -v`
- [ ] Verify: test_missing_program_reports_error passes

---

## Fix 5: Copybook MOVE Expansion (Hour 5-6 - Medium Risk)

### 5.1 Trace Expansion Pipeline
- [ ] Open cobolparser/preprocess/copybook_expander.py
- [ ] Add debug logging to expand() method
- [ ] Trace token flow through reconstruction
- [ ] Identify where MOVE tokens lost

### 5.2 Investigate MOVE Token Handling
- [ ] Check token_types for MOVE keyword
- [ ] Verify MOVE in stringified output
- [ ] Test reconstruction of MOVE statement

### 5.3 Debug Single MOVE
- [ ] Create minimal copybook: just one MOVE statement
- [ ] Test expansion with debug logging
- [ ] Verify MOVE in expanded source
- [ ] Verify MOVE in parsed AST

### 5.4 Fix Root Cause
- [ ] If token lost: recover in reconstruction
- [ ] If parsing broken: fix MOVE parsing
- [ ] If integration broken: trace connections

### 5.5 Validation
- [ ] Run: `pytest tests/contracts/test_copybook_expansion_contracts.py -v`
- [ ] Verify: test_procedure_copybook_statements_in_ast passes
- [ ] Verify: test_procedure_copybook_preserves_order passes

---

## Regression Verification

### 6.1 Run Full Test Suite
- [ ] Run: `pytest -q --tb=short 2>&1 | tee reports/fix-1-results.txt`
- [ ] Record: total failures
- [ ] Verify: 195 → ~100 failures (approximately)

### 6.2 Check Coverage
- [ ] Run: `pytest --cov=cobolparser --cov-report=term-missing -q`
- [ ] Record: coverage percentage
- [ ] Verify: 43.86% → 70%+ (approximately)

### 6.3 Validate Contracts
- [ ] Run: `pytest tests/contracts/ -v`
- [ ] Verify: All contract tests still passing
- [ ] Ensure: Backward compatibility maintained

### 6.4 Document Results
- [ ] Create: reports/phase-6-fix-1-results.md
- [ ] Include: tests fixed count, coverage improvements, any issues encountered

---

## Success Criteria

- [x] All 5 fixes implemented and tested
- [ ] 55+ tests fixed (195 → ~100 failures)
- [ ] Coverage 70%+ (43.86% → 70%+)
- [ ] All contract tests passing
- [ ] No regressions in existing passing tests
- [ ] Implementation complete in ~6 hours focused work

---

## Rollback Plan

If any fix causes widespread regressions:
1. Identify the problematic fix
2. Comment out the changes
3. Verify tests return to baseline
4. Investigate further before re-applying

Version control at each checkpoint:
- git status before each hour
- git stash if major issue found
- Easy to rollback individual fixes
