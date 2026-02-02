# Phase 4: AST Hardening - Error Detection & Validation

## Executive Summary

Phase 4 focuses on transforming the COBOL parser from a **"best-effort" parser** (accepts invalid syntax) into a **"validating parser"** (detects errors and provides diagnostics). This phase will reduce the remaining 80 test failures through systematic error detection and validation.

**Phase 4 Scope:**
- Add validation to EVALUATE statement parser
- Add validation to IF/PERFORM/CALL statement parsers
- Implement comprehensive error messages
- Add structural validation for nested statements
- Improve error recovery strategies

---

## Problem Statement: Remaining 80 Failures

### Current Failure Categories

| Category | Count | Root Cause | Phase 4 Approach |
|----------|-------|-----------|-----------------|
| EVALUATE Diagnostics | 28 | No error detection for invalid EVALUATE | Add validation |
| Error Handling Tests | 15 | Missing error reports for syntax issues | Add validation |
| Infrastructure (IO schema, SQL) | 7 | External dependencies, not parser | Defer/Skip |
| Edge Cases | 30 | Complex scenarios, preprocessing | Investigate |

**Phase 4 Priority:** Focus on EVALUATE and Error Handling (43 tests) to demonstrate validation architecture.

---

## Architecture: Validation Strategy

### 1. Error Detection Points

Three validation levels in each parser:

**Level 1: Syntax Validation (During Parsing)**
```python
def _validate_structure(self, parsed_items: Dict) -> List[ParseError]:
    """Validate statement structure during parsing."""
    errors = []
    
    # Check for required clauses, count mismatches, etc.
    if not parsed_items.get('when_clauses'):
        errors.append(ParseError(
            "EVALUATE must contain at least one WHEN clause",
            location=parsed_items['start_location']
        ))
    
    return errors
```

**Level 2: Semantic Validation (After Parsing)**
```python
def _validate_selectors(self, evaluate_stmt: EvaluateStatement) -> List[ParseError]:
    """Validate selector/subject count match."""
    errors = []
    
    subject_count = len(evaluate_stmt.subjects)
    for clause in evaluate_stmt.when_clauses:
        selector_count = len(clause.selectors)
        if selector_count != subject_count and subject_count > 0:
            errors.append(ParseError(
                f"Selector count ({selector_count}) doesn't match "
                f"subject count ({subject_count})",
                location=clause.location
            ))
    
    return errors
```

**Level 3: Cross-Statement Validation**
```python
def _validate_nesting(self, stmt: CobolStatement, context: ParseContext) -> List[ParseError]:
    """Validate properly nested statements."""
    errors = []
    
    # Check that END-EVALUATE is present when needed, etc.
    
    return errors
```

### 2. Integration Pattern: ParseContext Carries Validator

Extend `ParseContext` to support error collection:

```python
class ParseContext:
    def __init__(self, parser, registry, validators=None):
        self.parser = parser
        self.registry = registry
        self.validators = validators or {}
    
    def collect_error(self, error: ParseError) -> None:
        """Collect validation error."""
        self.parser.add_error(error)
```

---

## EVALUATE Statement Validation (Pilot)

### EVALUATE Syntax Rules

```
EVALUATE subject [ALSO subject]...
    WHEN selector [ALSO selector]... [NEXT SENTENCE | statement...]
    [WHEN OTHER [NEXT SENTENCE | statement...]]
END-EVALUATE
```

### Validation Rules Implementation

**Rule 1: At Least One WHEN Clause**
```
EVALUATE WS-GRADE
    DISPLAY 'ERROR'
END-EVALUATE

Error: "EVALUATE must contain at least one WHEN clause"
```

**Rule 2: Must Have END-EVALUATE Terminator**
```
EVALUATE WS-GRADE
    WHEN 1 DISPLAY 'ONE'.
    WHEN OTHER DISPLAY 'OTHER'

Error: "Missing END-EVALUATE terminator in EVALUATE statement"
```

**Rule 3: Selector/Subject Count Mismatch**
```
EVALUATE WS-GRADE  -- 1 subject
    WHEN 1 ALSO 'A'  -- 2 selectors
    DISPLAY 'X'
END-EVALUATE

Error: "Selector count (2) doesn't match subject count (1)"
```

**Rule 4: WHEN OTHER Must Be Last**
```
EVALUATE WS-GRADE
    WHEN OTHER DISPLAY 'OTHER'
    WHEN 1 DISPLAY 'ONE'
END-EVALUATE

Error: "WHEN OTHER must be the last WHEN clause"
```

**Rule 5: Only One WHEN OTHER**
```
EVALUATE WS-GRADE
    WHEN OTHER DISPLAY 'OTHER1'
    WHEN OTHER DISPLAY 'OTHER2'
END-EVALUATE

Error: "Only one WHEN OTHER clause allowed per EVALUATE"
```

---

## Implementation Plan

### Phase 4 Sprint 1: EVALUATE Validation (This Sprint)

**Step 1: Create EvaluateValidator Class**
```
cobolparser/validators/evaluate_validator.py
- _validate_at_least_one_when()
- _validate_end_evaluate_present()
- _validate_selector_subject_count()
- _validate_when_other_placement()
- _validate_single_when_other()
```

**Step 2: Integrate into EvaluateStatementParser**
```
evaluate_parser.py:
- Instantiate validator in parse()
- Collect errors after parsing
- Add errors to parser via context.collect_error()
```

**Step 3: Test & Verify**
```
python -m pytest tests/contracts/test_evaluate_diagnostics.py -xvs
```

**Expected Result:** Reduction of 28 EVALUATE diagnostic failures

### Phase 4 Sprint 2: IF/PERFORM/CALL Validation

**Step 4: Create IF Validator (similar pattern)**
- Validate condition is non-empty
- Validate proper nesting of THEN/ELSE
- Validate END-IF presence

**Step 5: Create PERFORM Validator**
- Validate VARYING format (FROM...BY...UNTIL)
- Validate paragraph names exist (semantic check - defer)
- Validate THRU paragraph exists

**Step 6: Create CALL Validator**
- Validate parameter modes (IN, OUT, INOUT)
- Validate ON EXCEPTION/END-CALL handling

### Phase 4 Sprint 3: Error Recovery

**Step 7: Implement Recovery Strategies**
- When WHEN clause missing: insert synthetic WHEN clause
- When END-EVALUATE missing: auto-close at period or next keyword
- When selector mismatch: report error but continue parsing

---

## Implementation Approach: Validation-in-Place

Rather than creating separate validator classes immediately, we'll add validation **inline** in each parser:

```python
# evaluate_parser.py
def parse(self, stream: TokenStream, context: ParseContext) -> EvaluateStatement:
    start_token = stream.peek()
    stmt = EvaluateStatement(start_token.location)
    
    # ... parsing logic ...
    
    # Perform validation
    self._validate_evaluate_structure(stmt, context)
    
    return stmt

def _validate_evaluate_structure(self, stmt: EvaluateStatement, context: ParseContext) -> None:
    """Collect validation errors for this EVALUATE statement."""
    
    # Check 1: At least one WHEN clause
    if not stmt.when_clauses and not stmt.default_when:
        error = ParseError(
            "EVALUATE must contain at least one WHEN clause",
            location=stmt.location
        )
        context.parser.add_error(error)
    
    # Check 2: WHEN OTHER is last (if present)
    if stmt.default_when is not None:
        when_count = len(stmt.when_clauses)
        if when_count > 0:
            # Check that default_when is actually the last one
            # This requires tracking position - for now, just warn
            pass
    
    # Check 3: Subject/selector count matching
    subjects = len(stmt.subjects) if stmt.subjects else 1
    for when_clause in stmt.when_clauses:
        selectors = len(when_clause.selectors) if when_clause.selectors else 1
        if subjects > 0 and selectors != subjects:
            error = ParseError(
                f"Selector count ({selectors}) doesn't match subject count ({subjects})",
                location=when_clause.location
            )
            context.parser.add_error(error)
```

---

## Benefits of This Approach

1. **Incremental**: One statement at a time, without large refactors
2. **Focused**: Each parser handles its own validation rules
3. **Testable**: Validation can be tested independently
4. **Maintainable**: Validation rules co-located with parsing logic
5. **Non-Breaking**: Errors are collected, not fatal; parsing continues

---

## Metrics & Success Criteria

### Success Criteria for Phase 4

1. **EVALUATE Validation**: 28 EVALUATE diagnostic test pass
2. **Error Handling**: 15 error handling tests pass
3. **Zero Regressions**: All 2269 passing tests remain passing
4. **Improved Total**: Reduce 80 failures to ~40 by end of phase

### Stretch Goals (If Time Permits)

1. Add IF statement validation (condition non-empty, END-IF present)
2. Add PERFORM validation (UNTIL/VARYING structure)
3. Implement error recovery strategies

---

## Validation Rules Reference

### EVALUATE Statement Rules

| Rule | Validation | Error Message |
|------|-----------|----------------|
| R1 | At least one WHEN clause | "EVALUATE must contain at least one WHEN clause" |
| R2 | END-EVALUATE terminator | "Missing END-EVALUATE terminator" |
| R3 | Selector/subject count match | "Selector count ({N}) doesn't match subject count ({M})" |
| R4 | WHEN OTHER is last | "WHEN OTHER must be the last WHEN clause" |
| R5 | Single WHEN OTHER | "Only one WHEN OTHER clause allowed" |
| R6 | Valid selectors | "Empty selector in WHEN clause" |

---

## Next Steps

1. ✅ Read and understand remaining EVALUATE diagnostic tests
2. 🔳 Extend ParseContext to support error collection context
3. 🔳 Implement _validate_evaluate_structure() in EvaluateStatementParser
4. 🔳 Run EVALUATE diagnostic tests and measure improvement
5. 🔳 Repeat for IF, PERFORM, CALL statements
6. 🔳 Implement error recovery mechanisms

**Ready to proceed with implementation?**
