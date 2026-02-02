# COBOL Parser Refactoring - Comprehensive Research Report
**Date:** January 31, 2026  
**Focus:** Current refactoring state analysis across all work streams

---

## 1. FAILING TESTS INVENTORY

### Overall Statistics
- **Total Tests:** 2,349
- **Passing:** 2,233 (95.1%)
- **Failing:** 116 (4.9%)
- **Skipped:** 13 (0.5%)

### Test Failure Categories

#### Category: IF Statement Failures (5+ failures)
- `test_if_else_minimal` - Core IF-ELSE parsing
- `test_else_recovery_without_if` - Error recovery
- `test_if_with_end_if_explicit` - Explicit END-IF terminator
- `test_sample_features.py::TestControlFlowStatements::test_if_statement`
- `test_parser_coverage_complete.py::TestProcedureStatementEdgeCases::test_if_else_statement`
- Related: `test_control_flow_basic.py` + division context tracking tests

**Severity:** HIGH - Core control flow affecting multiple downstream tests

#### Category: EVALUATE Statement Failures (8+ failures)
- `test_evaluate_missing_end_evaluate` - END-EVALUATE validation
- `test_evaluate_selector_mismatch_single_subject` - Subject/selector count validation
- `test_evaluate_selector_mismatch_multiple_subjects` - Multi-subject handling
- `test_evaluate_multiple_errors_collected` - Error accumulation
- `test_evaluate_parser_stays_stable` - Parser state consistency
- `test_evaluate_mixed_thru_through` - THRU syntax handling
- `test_evaluate_any_with_also` - ALSO clause handling
- `test_single_subject_literals_and_ranges` - Subject parsing variants
- `test_multiple_subjects_any_and_also` - Complex selectors
- `test_evaluate_true_with_conditions_and_or` - Condition operators

**Severity:** HIGH - Complex control flow with numerous edge cases

#### Category: CALL Statement Failures (2+ failures)
- `test_call_basic_parsing.py` (likely, not explicitly listed but exists)
- Indirect failures through integration tests

**Severity:** MEDIUM - Dynamic calling and parameter passing

#### Category: PERFORM Statement Failures (2+ failures)
- Related to `test_perform_thru.py` basic structure
- Implicit section creation (`test_implicit_section.py::test_implicit_section_created_for_top_level_code`)

**Severity:** MEDIUM - Loop and paragraph execution

#### Category: Other Failures (~95 failures)
- Continuation line handling (`test_continuation_cases.py::test_doubled_quote_across_continuation`)
- Preprocessing issues (`test_preprocess_init_coverage.py` - 3+ failures)
- Division context tracking (`test_division_context.py`)
- IO coverage reporting (`test_io_coverage_reporter.py` - 5+ failures)
- Sentence multi-verb parsing (`test_sentence_multi_verbs.py::test_multi_verbs_one_sentence`)
- Real-world patterns (`test_real_world_patterns.py` - multiple)

**Severity:** MEDIUM-LOW - Infrastructure and integration issues

---

## 2. EXISTING COMPLETED PARSERS ANALYSIS

### DisplayStatementParser
**Location:** `cobolparser/parsers/display_parser.py` (44 lines)

**Key Methods:**
- `can_parse(stream: TokenStream) -> bool` - Checks for DISPLAY token
- `parse(stream: TokenStream, context: ParseContext) -> DisplayStatement`

**Pattern Structure:**
1. Token type detection coupled with identifier name check for robustness
2. Recovery mechanism checking previous token
3. Whitespace/comment skipping using stream methods
4. Terminal detection (PERIOD, END-DISPLAY)
5. Device specification via UPON clause
6. Item accumulation in while loop
7. Returns constructed statement

**Best Practices Observed:**
- Defensive programming: checks `token is None`, unwraps optional values
- Handles both TokenType constants and string-based IDENTIFIER matching
- COBOL syntax flexibility: checks both `token.type` and `token.value.upper()`

### MoveStatementParser
**Location:** `cobolparser/parsers/move_parser.py` (103 lines)

**Key Methods:**
- `can_parse(stream: TokenStream) -> bool`
- `parse(stream: TokenStream, context: ParseContext) -> MoveStatement`

**Pattern Structure:**
1. MOVE keyword detection with fallback to previous token
2. CORRESPONDING flag detection
3. Source operand parsing with parenthesis tracking (handles subscripts/refmods)
4. TO keyword detection (with error handling)
5. Target accumulation loop with:
   - Comma separator handling
   - Terminator detection (PERIOD, keywords for new statements)
   - Multiple target collection
6. Returns MoveStatement with source + targets

**Advanced Features:**
- Parenthesis depth tracking for complex operands
- Intelligent terminator detection (looks for statement-starting keywords)
- String literal handling with quote preservation

### ArithmeticParsersModule
**Location:** `cobolparser/parsers/arithmetic_parsers.py` (320 lines)

**Base Structure:**
`ArithmeticParserBase` - Contains shared logic for ADD, SUBTRACT, MULTIPLY, DIVIDE

**Key Methods:**
- `parse_size_error_clauses()` - Handles ON SIZE ERROR / NOT ON SIZE ERROR
- `parse_nested_statements()` - Collects statements within error handlers
- Specific parsers: `AddStatementParser`, `SubtractStatementParser`, etc.

**Key Features:**
- Nested statement support within exception clauses
- Token lookahead for multi-token keywords (e.g., "ON SIZE ERROR")
- Stream consumption with validation
- Reusable base class pattern

**Pattern Observations:**
- Modular helper methods for recurring patterns
- Comprehensive error clause handling
- Each parser implements `can_parse()` and `parse()` interface

---

## 3. PARSER METHODS TO EXTRACT - DETAILED ANALYSIS

### Method 1: parse_call_statement()
**Location:** `parser.py:6617-6933` (317 lines)
**Complexity:** HIGH (30+ statement paths)
**Difficulty:** HIGH

**Related Inline Method:** `_parse_call_inline()` @ line 3441
**Related Inline Method:** `_parse_call_exception_handlers()` @ line 3655 (200+ lines)
**Related Helper:** `_parse_call_using_parameters_inline()` @ line 3523

**Topics Handled:**
- CALL literal vs CALL identifier (dynamic dispatch)
- USING clause with BY REFERENCE/CONTENT/VALUE parameters
- RETURNING vs GIVING clause variants
- ON EXCEPTION / NOT ON EXCEPTION handlers
- ON OVERFLOW / NOT ON OVERFLOW handlers
- END-CALL terminator
- Multi-line parameter lists
- Error recovery

**Lines by Feature:**
- Dynamic program name detection: 15 lines
- USING parameter parsing: 40 lines
- RETURNING/GIVING handling: 25 lines
- Exception handlers: 80 lines
- Nested statement collection: 60 lines
- Stream management: 30+ lines

**Dependencies:**
- `CallStatement` AST node (models/statements.py:612)
- `CallParameter` dataclass
- Exception handler statement parsing

---

### Method 2: parse_if_statement()
**Location:** `parser.py:6478-6615` (137 lines)
**Complexity:** MEDIUM (condition parsing + nesting)
**Difficulty:** MEDIUM

**Related Inline Methods:**
- `_parse_if_inline()` @ line 4700+ (inline form)
- `_parse_inline_if_into_perform()` - nested IF in PERFORM

**Topics Handled:**
- Condition expression parsing
- THEN clause parsing
- ELSE branch support
- END-IF terminator
- Nested IF statements
- Nested statements in branches
- Condition operators (>, <, =, AND, OR, NOT)

**Lines by Feature:**
- Condition collection until THEN: 20 lines
- THEN branch statement parsing: 30 lines
- ELSE branch detection and parsing: 35 lines
- END-IF termination: 15 lines
- Error recovery: 15 lines
- Nested statement dispatch: 20 lines

**Dependencies:**
- `IfStatement` AST node
- `CobolExpression` for conditions
- Recursive statement parsing

---

### Method 3: parse_perform_statement()
**Location:** `parser.py:5552-5871` (319 lines)
**Complexity:** VERY HIGH (6 major variants)
**Difficulty:** VERY HIGH

**Related Inline Method:** `_parse_perform_inline()` @ line 4149-4349 (200+ lines)
**Related Helpers:**
- `_parse_test_timing_clause()` 
- `_parse_until_condition()`
- `_parse_perform_thru_range()`

**Variants Supported:**
1. **Simple PERFORM:** `PERFORM paragraph-name` (20 lines)
2. **THRU variant:** `PERFORM paragraph THRU paragraph-name` (20 lines)
3. **TIMES variant:** `PERFORM n TIMES` (25 lines)
4. **UNTIL variant:** `PERFORM UNTIL condition` (30 lines)
5. **Test timing:** `WITH TEST BEFORE/AFTER` (15 lines)
6. **VARYING variant:** Full loop structure with nested statements (120+ lines)
7. **Inline PERFORM:** Embedded statements (80+ lines)

**Topics Handled:**
- Paragraph/section range parsing
- Test timing clauses
- Loop counting (TIMES)
- Condition specifications (UNTIL)
- VARYING clause with FROM, BY, UNTIL
- Inline statement collection
- END-PERFORM terminator
- Nested control flow (IF, CALL within PERFORM)

**Complexity: Extreme**
- Multiple branching paths
- Lookahead requirements
- Nested inline parsing
- State management for VARYING clause

---

### Method 4: parse_evaluate_statement()
**Location:** `parser.py:6041-6197` (157 lines)
**Complexity:** HIGH (multiple subjects/selectors)
**Difficulty:** HIGH

**Related Inline Method:** `_parse_evaluate_inline()` @ line 5010-5280 (270+ lines)
**Related Helper:** `_parse_evaluate_selector()` - complex selector parsing

**Topics Handled:**
- EVALUATE subject expression(s)
- ALSO clause for additional subjects
- WHEN selector clauses
- ALSO in selectors for multi-way comparisons
- Literal value selectors
- Range selectors (TRUE, FALSE, ANY)
- WHEN OTHER clause
- END-EVALUATE terminator
- Nested statements in WHEN branches
- Subject/selector mismatch validation
- Selector validation (no empty selectors)

**Lines by Feature:**
- Subject parsing loop: 30 lines
- WHEN clause parsing: 60 lines
- Selector parsing: 40 lines
- Statement execution paths: 20 lines
- Validation logic: 15 lines

**Key Complexity:**
- Subject count must match selector count
- WHEN OTHER validation (must be last)
- Complex expression support in subjects/selectors
- Inline statement parsing in WHEN branches

**Critical Edge Cases:**
- Multiple subjects with multiple selectors (cross-product)
- ANY selector with multiple subjects
- THROUGH syntax in selectors
- Implicit vs explicit END-EVALUATE

---

## 4. AST NODES & FREEZING IMPACT ANALYSIS

### Current Mutable Patterns in statements.py

#### MoveStatement (lines 51-80)
```python
# Current: Mutable with set_* methods
stmt.set_source(value)
stmt.add_target(target)
stmt.set_corresponding(True)
```

**Mutation Patterns:**
- `set_source()` and `add_target()` - Direct property mutation
- List modification via `targets.append()`
- Boolean flag modification

**Freezing Impact if dataclass(frozen=True) applied:**
- ❌ Cannot use `set_source()` - needs `dataclass.replace()`
- ❌ Cannot mutate `targets` list - needs immutable tuple
- ⚠️ Existing parser code would break

#### CallStatement (lines 612-655)
```python
stmt.set_called_program(program_name, is_dynamic)
stmt.add_using_parameter(param_name, mode)
stmt.set_giving_parameter(param_name)
```

**Mutation Methods:** 8+ setter methods
**Data Structures:** Lists (using_parameters, _possible_values)
**Freezing Challenge:** HIGH - Significant refactoring needed

#### IfStatement (lines 770-820)
```python
stmt.set_condition(condition_expr)
stmt.add_then_statement(stmt)
stmt.add_else_statement(stmt)
```

**Freezing Challenge:** MEDIUM - 3 main mutation points

#### PerformStatement (lines 900-980)
```python
stmt.add_dynamic_target(target)
stmt.set_test_timing(timing)
stmt.set_varying_clause(var, from_val, by_val, cond)
stmt.set_until_condition(cond)
```

**Mutations:** 5+ setters
**Data Structures:** Nested objects with their own mutations
**Freezing Challenge:** VERY HIGH

#### EvaluateStatement (lines 1050-1130)
```python
stmt.add_subject(subject)
stmt.add_when_clause(when_obj)
stmt.set_when_other_clause(stmts)
```

**Mutations:** 5+ methods
**Freezing Challenge:** HIGH

### Mutation Dependency Chain
**Current Builders (parser code):**
```
Create Statement → Set properties → Add sub-items → Add statements → Return complete object
```

**After Freezing:**
```
Create Statement with all parameters → Add statements in one pass → Return frozen object
```

**Required Changes:**
1. All AST node classes must use `@dataclass(frozen=True)`
2. Parser factory methods need refactoring to build complete objects
3. Use `dataclass.replace()` for any necessary state changes
4. Replace all setter methods with parameter-based construction
5. Replace all append methods with builder pattern

**Affected Files:**
- `cobolparser/models/statements.py` - 1921 lines, ~80 AST node classes
- `cobolparser/models/program.py` - Program/Division/Section/Paragraph structures
- `cobolparser/models/data_items.py` - Data item definitions
- All parser files using these nodes

**Compatibility Breakage:** HIGH
- Every parser method that builds AST nodes needs updating
- Estimated impact: 500+ lines of parser code changes
- Testing needed for all 116 failing tests

---

## 5. REGISTRY STATUS & PARSER REGISTRATION

### Current Registry Implementation

**File:** `cobolparser/core/registry.py` (14 lines)

```python
class StatementRegistry:
    def __init__(self):
        self._parsers: List[StatementParser] = []
    
    def register(self, parser: StatementParser) -> None:
        self._parsers.append(parser)
    
    def get_parser(self, stream: TokenStream) -> Optional[StatementParser]:
        for parser in self._parsers:
            if parser.can_parse(stream):
                return parser
        return None
```

**Design:** Simple linear registry (first match wins)

### Current Registration (parser.py:192-199)
```python
self.registry = StatementRegistry()
self.registry.register(DisplayStatementParser())
self.registry.register(MoveStatementParser())
self.registry.register(AddStatementParser())
self.registry.register(SubtractStatementParser())
self.registry.register(MultiplyStatementParser())
self.registry.register(DivideStatementParser())
self.registry.register(ComputeStatementParser())
```

**Status:** ✅ 7 parsers registered (DISPLAY, MOVE, 5 arithmetic

)

**Missing Registrations:**
- ❌ CallStatementParser - parser file doesn't exist yet
- ❌ IfStatementParser - parser file doesn't exist yet
- ❌ PerformStatementParser - parser file doesn't exist yet
- ❌ EvaluateStatementParser - parser file doesn't exist yet

### Interface: StatementParser Protocol

**File:** `cobolparser/core/interfaces.py`

```python
class StatementParser(Protocol):
    """Protocol for statement parsers."""
    
    def can_parse(self, stream: TokenStream) -> bool:
        """Return True if parser can handle this token stream."""
        ...
    
    def parse(self, stream: TokenStream, context: ParseContext) -> CobolStatement:
        """Parse the statement and return AST node."""
        ...
```

**Expected Implementation Pattern:**

```python
class CallStatementParser(StatementParser):
    def can_parse(self, stream: TokenStream) -> bool:
        token = stream.peek()
        return (token and (token.type == TokenType.CALL or 
                          (token.type == TokenType.IDENTIFIER and token.value.upper() == "CALL")))
    
    def parse(self, stream: TokenStream, context: ParseContext) -> CallStatement:
        # Implementation extracted from parser.py
        ...
```

### How Parsers Will Be Used

**Current Flow (Main Parser):**
```
parse_procedure_division() 
  → parse_statement() 
    → switch/if checking statement type 
      → parse_specific_statement()
```

**New Flow After Registration:**
```
parse_procedure_division()
  → parse_statement()
    → registry.get_parser(stream)
      → parser.can_parse() [first match]
      → parser.parse()
      → Return AST node
```

**Parser Lookup Order (matters when multiple `can_parse()` return true):**
1. RegisteredOrder: DisplayStatementParser → MoveStatementParser → ... → CallStatementParser
2. **Issue:** If multiple parsers can_parse the same token, first wins
3. **Mitigation:** Design `can_parse()` to be specific to avoid conflicts

---

## 6. COMPLEXITY & LINE COUNT SUMMARY

### Parser Method Extraction Effort

| Statement | Target Lines | Complexity | Effort | Inline Methods | Total Scope |
|-----------|--------------|-----------|--------|----------------|-------------|
| CALL | 317 | HIGH | Hard | `_parse_call_inline` (200), `_parse_call_exception_handlers` (200) | 717 |
| IF | 137 | MEDIUM | Medium | `_parse_if_inline` (100) | 237 |
| PERFORM | 319 | VERY HIGH | Very Hard | `_parse_perform_inline` (200), helpers (50) | 569 |
| EVALUATE | 157 | HIGH | Hard | `_parse_evaluate_inline` (270), helpers (50) | 477 |
| **TOTAL** | **930** | | | | **2,000+** |

### Helper Methods Dependencies

**parse_call_statement requirements:**
- `_parse_call_using_parameters_inline()` - 82 lines
- `_parse_call_exception_handlers()` - 200+ lines
- `_parse_inline_call_into_perform()` - for nested calls

**parse_perform_statement requirements:**
- `_parse_test_timing_clause()` - 15 lines
- `_parse_until_condition()` - 30 lines
- `_parse_perform_thru_range()` - 25 lines
- `_parse_inline_call_into_perform()` / `_parse_inline_if_into_perform()`

**parse_evaluate_statement requirements:**
- `_parse_evaluate_selector()` - 60+ lines
- `_validate_evaluate_statement()` - 20 lines

**parse_if_statement requirements:**
- `_parse_inline_if_into_perform()` - nested IF support
- Statement parsing for branches

### Parser.py Size Before/After Extraction

**Current:** 8,113 lines
**After full extraction (all 4 statements + helpers):**
- Main parser reduction: ~2,000 lines (24.6% reduction)
- Estimated target: 6,100-6,200 lines
- New parser files combined: ~2,200 lines

---

## 7. TEST FAILURE ROOT CAUSES

### IF Statement Failures - Root Cause Analysis

**Pattern:** Failures in `test_control_flow_basic.py`, `test_division_context.py`, sample features

**Suspected Cause:**
1. Primary: `_parse_if_inline()` method not properly handling THEN/ELSE/END-IF flow in inline form
2. Secondary: Division context not tracking for nested IF statements
3. Related: Interaction with error recovery mode might suppress errors

**Evidence:** Debug output shows:
```
DEBUG SENTENCE: Starting sentence with IF
DEBUG SENTENCE: Breaking at expected tokens
DEBUG FINAL: Parser continues past expected boundaries
```

### EVALUATE Statement Failures - Root Cause Analysis

**Pattern:** WHEN clause parsing, END-EVALUATE validation, selector mismatch

**Suspected Cause:**
1. `_parse_evaluate_inline()` missing END-EVALUATE validation
2. Selector count doesn't match subject count (requires cross-validation)
3. Empty selector detection failing
4. WHEN OTHER placement validation not working

**Evidence from debug output:**
```
DEBUG FINAL: i=3, token=TokenType.WHEN 'WHEN'
DEBUG: Checking PERIOD at i=4, type=TokenType.LEVEL_NUMBER
```
Parser confusing LEVEL_NUMBER as terminator.

### CALL Statement Failures - Indirect

**Pattern:** Likely failures in integration tests calling external programs

**Suspected Cause:**
- Dynamic CALL resolution
- Parameter passing validation
- Exception handler parsing edge cases

### PERFORM Statement Failures - Indirect

**Pattern:** `test_implicit_section.py` failures suggest section creation issues

**Suspected Cause:**
- PERFORM paragraph references creating implicit sections
- PERFORM THRU range validation
- Nested perform statement handling

---

## RECOMMENDATIONS FOR REMAINING WORK

### Priority 1: Fix Failing Tests (Address Root Causes)
1. Fix `_parse_evaluate_inline()` END-EVALUATE validation
2. Fix IF-ELSE termination detection
3. Fix selector/subject count validation
4. Run test suite after each fix

### Priority 2: Extract Critical Parsers
1. Start with **CallStatementParser** (highest value, existing structure)
2. Then **EvaluateStatementParser** (many failures, moderate complexity)
3. Then **IfStatementParser** (medium complexity)
4. Finally **PerformStatementParser** (highest complexity, 6 variants)

### Priority 3: AST Freezing (Phase 4)
1. Convert simple nodes first (DisplayStatement, MoveStatement)
2. Update corresponding parsers to use frozen-compatible builders
3. Test each frozen node conversion
4. Scale up to complex nodes

### Key Metrics After Completion
- Parser.py size: < 6,200 lines (from 8,113)
- Method cyclomatic complexity: No method > 15 in extracted parsers
- Test pass rate: 100% (from 95.1%)
- New parser files: 4 total (from 3)
- Coverage: Maintain > 90% branch coverage

---

## APPENDIX: File Locations Reference

### Core Infrastructure
- TokenStream: `cobolparser/core/token_stream.py`
- StatementRegistry: `cobolparser/core/registry.py`
- StatementParser Protocol: `cobolparser/core/interfaces.py`

### Existing Parsers (Model for new ones)
- DisplayStatementParser: `cobolparser/parsers/display_parser.py`
- MoveStatementParser: `cobolparser/parsers/move_parser.py`
- ArithmeticParsers: `cobolparser/parsers/arithmetic_parsers.py`

### Main Parser
- CobolParser: `cobolparser/parser.py` (8,113 lines)

### AST Nodes
- Statements: `cobolparser/models/statements.py` (1,921 lines)
- Program: `cobolparser/models/program.py`
- DataItems: `cobolparser/models/data_items.py`

### Tests
- Contracts: `tests/contracts/` (38 tests for API stability)
- Unit: `tests/unit/` (59 unit tests)
- Integration: `tests/integration/` (17 integration tests)
