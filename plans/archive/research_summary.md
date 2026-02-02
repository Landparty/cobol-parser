# COBOL Parser Refactoring - Research Summary
**Prepared:** January 31, 2026  
**Status:** Phase 3 (50% complete) + 116 failing tests to address

---

## 1. FAILING TESTS INVENTORY

### Overall Statistics
- **Total Tests:** 2,349
- **Passing:** 2,233 (95.1%)
- **Failing:** 116 (4.9%)

### Failure Categories Ranked by Impact

| Category | Count | Severity | Affected Areas |
|----------|-------|----------|-----------------|
| **EVALUATE** | 8+ | HIGH | Selector/subject validation, END-EVALUATE termination, WHEN clause structure |
| **IF** | 5+ | HIGH | THEN/ELSE branching, END-IF termination, condition expression parsing |
| **Preprocessing/Continuation** | 15+ | MEDIUM | Line continuation, fixed format handling |
| **Division Context** | 5+ | MEDIUM | Implicit section creation, scope tracking |
| **IO Coverage Reporting** | 5+ | MEDIUM | Analysis infrastructure |
| **CALL & PERFORM** | 3+ | MEDIUM | Parameter passing, implicit section creation |
| **Real-world Patterns** | 20+ | LOW | Complex real-world code samples |

---

## 2. COMPLETED PARSER IMPLEMENTATIONS - STRUCTURE ANALYSIS

### Pattern Summary (Common to All)

1. **Token Detection:**
   ```python
   def can_parse(self, stream: TokenStream) -> bool:
       token = stream.peek()
       return token and (token.type == TokenType.KEYWORD or 
                        (token.type == TokenType.IDENTIFIER and token.value.upper() == "KEYWORD"))
   ```

2. **Recovery Pattern:**
   - Check current token
   - Fallback to previous token if needed (for recovery scenarios)

3. **Parsing Loop:**
   - Skip whitespace and comments
   - Token-by-token processing with lookahead
   - Terminator detection (PERIOD, keywords starting new statements)
   - List accumulation for multi-valued operands

### Key Files & Line Counts

| File | Lines | Methods | Pattern Complexity |
|------|-------|---------|-------------------|
| `display_parser.py` | 44 | 2 | Simple (linear parsing) |
| `move_parser.py` | 103 | 2 | Medium (CORRESPONDING, parenthesis tracking) |
| `arithmetic_parsers.py` | 320 | 7 classes + base | Complex (error clauses, nested statements) |

### Reusable Patterns Identified

**Pattern: Keyword/Identifier Dual Detection**
```python
token.type == TokenType.KEYWORD or (token.type == TokenType.IDENTIFIER and 
                                    token.value.upper() == "KEYWORD_STRING")
```

**Pattern: Terminator Detection Loop**
```python
while not stream.is_at_end:
    token = stream.peek()
    if token.type in (TokenType.PERIOD, TokenType.END_STATEMENT, keyword_tokens):
        break
    # Process token
    stream.advance()
```

**Pattern: Error Clause Handling**
```python
if stream.is_keyword(token, "ON"):
    # Parse exception handler statements
    stmts = self.parse_nested_statements()
    stmt.set_error_clause(stmts)
```

---

## 3. PARSER METHODS TO EXTRACT - LINE COUNTS & COMPLEXITY

### Method Extraction Scope

#### 1. CALL Statement Parser
| Component | Lines | Notes |
|-----------|-------|-------|
| `parse_call_statement()` | 317 | Main method |
| `_parse_call_inline()` | ~200 | Sentence-level variant |
| `_parse_call_exception_handlers()` | 200+ | Exception/overflow clauses |
| `_parse_call_using_parameters_inline()` | 82 | Parameter parsing helper |
| **Total Extract** | **~800** | |

**Complexity Sources:**
- Multiple clause types (USING, RETURNING, GIVING, ON EXCEPTION, ON OVERFLOW)
- Parameter mode variants (BY REFERENCE/CONTENT/VALUE)
- Dynamic vs static program names
- Nested statement collection in exception handlers

**Difficulty:** HARD

---

#### 2. IF Statement Parser
| Component | Lines | Notes |
|-----------|-------|-------|
| `parse_if_statement()` | 137 | Main method |
| `_parse_if_inline()` | ~100 | Inline variant |
| `_parse_inline_if_into_perform()` | ~40 | Nested in PERFORM |
| **Total Extract** | **~280** | |

**Complexity Sources:**
- Condition expression parsing (>, <, =, AND, OR, NOT)
- THEN/ELSE/END-IF termination
- Nested IF statements
- Nested statement collection

**Difficulty:** MEDIUM

---

#### 3. PERFORM Statement Parser
| Component | Lines | Notes |
|-----------|-------|-------|
| `parse_perform_statement()` | 319 | Main method (6 variants) |
| `_parse_perform_inline()` | 200+ | Inline/VARYING variant |
| `_parse_test_timing_clause()` | ~20 | WITH TEST BEFORE/AFTER |
| `_parse_until_condition()` | ~30 | UNTIL condition parsing |
| `_parse_perform_thru_range()` | ~25 | THRU range logic |
| **Total Extract** | **~600** | |

**Complexity Sources:**
- 6 different PERFORM variants (simple, THRU, TIMES, UNTIL, VARYING, inline)
- VARYING clause with FROM/BY/UNTIL logic
- Nested statement collection
- Loop variable tracking
- Test timing specifications

**Variants:**
1. Basic: `PERFORM paragraph-name`
2. Range: `PERFORM paragraph THRU paragraph-name`
3. Counter: `PERFORM n TIMES`
4. Condition: `PERFORM UNTIL condition`
5. Loop: `PERFORM VARYING var FROM val BY val UNTIL condition`
6. Inline: `PERFORM [VARYING] ... nested-statements END-PERFORM`

**Difficulty:** VERY HARD

---

#### 4. EVALUATE Statement Parser
| Component | Lines | Notes |
|-----------|-------|-------|
| `parse_evaluate_statement()` | 157 | Main method |
| `_parse_evaluate_inline()` | 270+ | Inline variant with selector parsing |
| `_parse_evaluate_selector()` | ~60 | Selector expression parsing |
| `_validate_evaluate_statement()` | ~20 | Cross-validation logic |
| **Total Extract** | **~510** | |

**Complexity Sources:**
- Multiple subjects with ALSO clauses
- Multiple selectors per WHEN clause with ALSO
- Subject/selector count validation (must match)
- Selector types: literals, ranges, TRUE, FALSE, ANY
- WHEN OTHER validation (must be last)
- Nested statement collection

**Critical Validation Rules:**
- Number of subjects must match number of selectors in each WHEN
- WHEN OTHER must be last clause
- Cannot have empty selectors
- ALSO must connect subjects/selectors (not standalone)

**Difficulty:** HARD

---

### Extraction Priority & Effort Estimate

| Parser | Priority | Effort | Duration | Notes |
|--------|----------|--------|----------|-------|
| CALL | 2 | 4 hrs | Medium | Well-structured, clear scope |
| IF | 3 | 2 hrs | Low | Simpler variant of PERFORM |
| EVALUATE | 1 | 3 hrs | Medium-High | Many failing tests, validation complex |
| PERFORM | 4 | 6 hrs | High | 6 variants, complex state management |

**Recommended Sequence:** EVALUATE (fix tests) → CALL (proven pattern) → IF (builds on CALL) → PERFORM (most complex)

---

## 4. AST NODES & FREEZING IMPACT

### Current State: Mutable + Setters
```python
# Current pattern
stmt = MoveStatement(location)
stmt.set_source("WS-SOURCE")
stmt.add_target("WS-TARGET-1")
stmt.add_target("WS-TARGET-2")
stmt.set_corresponding(True)
```

### After Freezing: Immutable Constructors
```python
# Required pattern
stmt = MoveStatement(
    location=location,
    source="WS-SOURCE",
    targets=["WS-TARGET-1", "WS-TARGET-2"],
    is_corresponding=True
)
```

### Nodes Requiring Conversion

| Node | Current Setters | Collections | Impact Level |
|------|----------------|-------------|--------------|
| MoveStatement | 3 methods | targets (list) | LOW |
| DisplayStatement | 2 methods | display_items (list) | LOW |
| CallStatement | 8+ methods | using_parameters (list), _possible_values (list) | HIGH |
| IfStatement | 3 methods | then_stmts (list), else_stmts (list) | MEDIUM |
| PerformStatement | 5+ methods | dynamic_targets (list) | HIGH |
| EvaluateStatement | 5+ methods | subjects (list), when_clauses (list) | HIGH |
| All Statements | ~80 nodes | Varies | **VERY HIGH** |

### Required Changes by Phase

**Phase 1: Simple Nodes (Statements)**
- MoveStatement → frozen
- DisplayStatement → frozen
- Update parsers to use builders
- Estimated: 40 lines changed in parsers

**Phase 2: Arithmetic Statements**
- AddStatement, SubtractStatement, etc. → frozen
- Handle nested error clauses
- Estimated: 60 lines changed

**Phase 3: Complex Statements**
- CallStatement, IfStatement, PerformStatement, EvaluateStatement → frozen
- Estimated: 200 lines changed across parsers

**Phase 4: Program Structure**
- CobolProgram, CobolDivision, CobolSection, etc. → frozen
- Estimated: 150 lines changed

**Total Refactoring:** ~2,500 lines across parser.py + new parser files

---

## 5. REGISTRY STATUS & REGISTRATION PATTERN

### Current Registry Implementation
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

**Design:** Linear search, first match wins

### Currently Registered
```python
self.registry = StatementRegistry()
self.registry.register(DisplayStatementParser())      # ✅ Works
self.registry.register(MoveStatementParser())         # ✅ Works
self.registry.register(AddStatementParser())          # ✅ Works
self.registry.register(SubtractStatementParser())     # ✅ Works
self.registry.register(MultiplyStatementParser())     # ✅ Works
self.registry.register(DivideStatementParser())       # ✅ Works
self.registry.register(ComputeStatementParser())      # ✅ Works
# Missing:
# self.registry.register(CallStatementParser())       # ❌ Doesn't exist yet
# self.registry.register(IfStatementParser())         # ❌ Doesn't exist yet
# self.registry.register(PerformStatementParser())    # ❌ Doesn't exist yet
# self.registry.register(EvaluateStatementParser())   # ❌ Doesn't exist yet
```

### How New Parsers Will Be Integrated

1. **Create parser file**
   ```python
   # File: cobolparser/parsers/evaluate_parser.py
   class EvaluateStatementParser(StatementParser):
       def can_parse(self, stream: TokenStream) -> bool: ...
       def parse(self, stream: TokenStream, context: ParseContext) -> EvaluateStatement: ...
   ```

2. **Register in parser.py __init__**
   ```python
   self.registry.register(EvaluateStatementParser())
   ```

3. **Update parser dispatch**
   - Current: `if self._is_keyword("EVALUATE"): result = self.parse_evaluate_statement()`
   - New: Delegate to registry in main parse loop
   - Eventually: Remove old method from main parser

### Registration Order Dependency
- **Order matters:** First `can_parse()` that returns True wins
- **Risk:** If multiple parsers match same token, behavior depends on registration order
- **Mitigation:** Design `can_parse()` to be specific (check token type + value)

---

## SUMMARY TABLE

| Objective | Finding | Actionable Item |
|-----------|---------|-----------------|
| **Failing Tests** | 116 failures (4.9%), mostly EVALUATE & IF | Fix root causes in inline parsers before extraction |
| **Parser Pattern** | Token detection → condition → loop → terminator | Apply to all new parsers |
| **Extraction Scope** | ~2,000 lines across 4 methods + helpers | Phased extraction in priority order |
| **Complexity Range** | EVALUATE (HIGH) to IF (MEDIUM) to PERFORM (VERY HIGH) | Start with EVALUATE to fix tests |
| **Freezing Impact** | ~80 AST nodes need conversion, ~2,500 lines of parser changes | Phase 4, after extraction complete |
| **Registry Pattern** | Simple linear registry, works well, 7/11 parsers registered | Add 4 parsers via registration calls |

---

## IMMEDIATE NEXT STEPS

1. **Fix failing EVALUATE tests** by addressing `_parse_evaluate_inline()` bugs
2. **Extract EvaluateStatementParser** to `cobolparser/parsers/evaluate_parser.py`
3. **Fix failing IF tests** in same manner
4. **Extract CallStatementParser** using EVALUATE as model
5. **Extract IfStatementParser** and **PerformStatementParser**
6. **Begin Phase 4:** Convert AST nodes to frozen dataclasses
