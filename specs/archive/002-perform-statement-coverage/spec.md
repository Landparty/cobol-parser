# Feature Specification: Comprehensive PERFORM Statement Coverage for COBOL Fixed Format

**Feature Branch**: `002-perform-statement-coverage`  
**Created**: January 11, 2026  
**Status**: Draft  
**Input**: User description: "make sure that all the different variation of perform statements are covered and tested by the parser for a cobol fix format"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Simple PERFORM Paragraph Execution (Priority: P1)

A COBOL developer writes a program that uses basic PERFORM statements to call paragraphs and sections. The parser must correctly identify and represent the target paragraph name and optional THRU clause.

**Why this priority**: This is the most fundamental PERFORM construct used in virtually every COBOL program. Without this working correctly, basic program flow cannot be analyzed.

**Independent Test**: Can be fully tested by parsing simple COBOL programs containing `PERFORM PARA-NAME` and `PERFORM PARA-START THRU PARA-END` statements and verifying the AST correctly captures both target and thru paragraph names.

**Acceptance Scenarios**:

1. **Given** a COBOL program with `PERFORM INITIALIZE-DATA`, **When** the parser processes this statement, **Then** the AST contains a PerformStatement node with `target_paragraph="INITIALIZE-DATA"`, `perform_type="SIMPLE"`, and `thru_paragraph=None`

2. **Given** a COBOL program with `PERFORM PARA-START THRU PARA-END`, **When** the parser processes this statement, **Then** the AST contains a PerformStatement node with `target_paragraph="PARA-START"`, `thru_paragraph="PARA-END"`, and `perform_type="SIMPLE"`

3. **Given** a COBOL program with `PERFORM PARA-START THROUGH PARA-END` (using THROUGH instead of THRU), **When** the parser processes this statement, **Then** the AST correctly recognizes THROUGH as equivalent to THRU and captures both paragraph names

---

### User Story 2 - PERFORM with TIMES Clause (Priority: P1)

A developer writes repetitive operations using `PERFORM ... TIMES` to execute a paragraph a specific number of times. The parser must capture both the iteration count and the optional THRU range.

**Why this priority**: TIMES clauses are extremely common for counted loops in COBOL programs, especially in batch processing and report generation.

**Independent Test**: Can be fully tested by parsing COBOL programs containing `PERFORM PARA-NAME n TIMES` and `PERFORM PARA-START THRU PARA-END n TIMES`, verifying the AST captures the times count and paragraph names correctly.

**Acceptance Scenarios**:

1. **Given** a COBOL program with `PERFORM PROCESS-RECORD 10 TIMES`, **When** the parser processes this statement, **Then** the AST contains a PerformStatement node with `perform_type="TIMES"`, `times_count=10`, and `target_paragraph="PROCESS-RECORD"`

2. **Given** a COBOL program with `PERFORM PARA-A THRU PARA-B 5 TIMES`, **When** the parser processes this statement, **Then** the AST contains a PerformStatement with `perform_type="TIMES"`, `times_count=5`, `target_paragraph="PARA-A"`, and `thru_paragraph="PARA-B"`

3. **Given** a COBOL program where the times count is a variable name (e.g., `PERFORM PARA WS-COUNT TIMES`), **When** the parser processes this statement, **Then** the AST correctly stores the variable name as the times count reference

---

### User Story 3 - PERFORM with UNTIL Clause (Priority: P2)

A developer implements conditional loops using `PERFORM ... UNTIL condition` to repeat execution until a specific condition becomes true. The parser must capture the condition expression and support both WITH TEST BEFORE (default) and WITH TEST AFTER variants.

**Why this priority**: UNTIL loops are fundamental for file processing and conditional iterations but less common than simple PERFORM and TIMES.

**Independent Test**: Can be fully tested by parsing COBOL programs with various UNTIL conditions (`PERFORM PARA UNTIL WS-EOF = 'Y'`, `PERFORM PARA WITH TEST BEFORE UNTIL condition`, `PERFORM PARA WITH TEST AFTER UNTIL condition`) and verifying condition capture.

**Acceptance Scenarios**:

1. **Given** a COBOL program with `PERFORM READ-RECORD UNTIL WS-EOF = "Y"`, **When** the parser processes this statement, **Then** the AST contains a PerformStatement with `perform_type="UNTIL"`, `until_condition` as a condition expression node, and test timing defaults to BEFORE

2. **Given** a COBOL program with `PERFORM PARA WITH TEST BEFORE UNTIL WS-COUNT > 100`, **When** the parser processes this statement, **Then** the AST captures the condition and explicitly records test timing as BEFORE

3. **Given** a COBOL program with `PERFORM PARA WITH TEST AFTER UNTIL WS-DONE = 'Y'`, **When** the parser processes this statement, **Then** the AST captures the condition and records test timing as AFTER (ensuring at least one execution before testing)

4. **Given** a COBOL program with `PERFORM PARA-START THRU PARA-END UNTIL condition`, **When** the parser processes this statement, **Then** the AST correctly combines THRU and UNTIL clauses in a single statement

---

### User Story 4 - PERFORM VARYING with Loop Control (Priority: P2)

A developer implements indexed loops using `PERFORM VARYING` to iterate with an explicit counter variable. The parser must capture the control variable, FROM value, BY increment, and UNTIL condition.

**Why this priority**: VARYING loops are essential for array/table processing and indexed operations but represent a more advanced construct than simple PERFORM statements.

**Independent Test**: Can be fully tested by parsing `PERFORM VARYING counter FROM initial BY increment UNTIL condition END-PERFORM` blocks and verifying all clause components are captured in the AST.

**Acceptance Scenarios**:

1. **Given** a COBOL program with `PERFORM VARYING WS-I FROM 1 BY 1 UNTIL WS-I > 10 ... END-PERFORM`, **When** the parser processes this statement, **Then** the AST contains a PerformStatement with `perform_type="VARYING"`, `varying_clause` containing control variable "WS-I", from_value=1, by_value=1, and the UNTIL condition

2. **Given** a COBOL program with `PERFORM VARYING counter FROM start-value BY increment-value UNTIL condition` where values are variable names, **When** parsed, **Then** the AST stores variable references (not just literals) in the varying clause

3. **Given** a COBOL program with nested VARYING (e.g., `PERFORM VARYING I FROM 1 BY 1 UNTIL I > 10 PERFORM VARYING J FROM 1 BY 1 UNTIL J > 10`), **When** parsed, **Then** the AST correctly represents the nested structure with the inner PERFORM as a child of the outer

4. **Given** a COBOL program with `PERFORM VARYING` containing inline statements (MOVE, COMPUTE, DISPLAY) before END-PERFORM, **When** parsed, **Then** all inline statements are captured in the `inline_statements` list

---

### User Story 5 - Inline PERFORM with END-PERFORM (Priority: P3)

A developer writes inline procedural code using `PERFORM ... END-PERFORM` blocks to group statements without creating separate paragraphs. The parser must capture all statements within the block.

**Why this priority**: Inline PERFORM blocks are less common in legacy COBOL but important for modern COBOL style and code clarity.

**Independent Test**: Can be fully tested by parsing `PERFORM ... END-PERFORM` blocks containing various statement types (MOVE, DISPLAY, CALL, IF) and verifying all inline statements are captured.

**Acceptance Scenarios**:

1. **Given** a COBOL program with `PERFORM MOVE "START" TO WS-STATUS ADD 1 TO WS-COUNTER DISPLAY "Processing" END-PERFORM`, **When** the parser processes this block, **Then** the AST contains a PerformStatement with `perform_type="INLINE"`, `target_paragraph=None`, and three inline statement nodes in `inline_statements`

2. **Given** an inline PERFORM block containing CALL statements, **When** parsed, **Then** the CALL statements are correctly captured as children of the PERFORM with all their parameters

3. **Given** an inline PERFORM block containing nested IF statements, **When** parsed, **Then** the IF structure (condition, then-branch, else-branch) is correctly captured within the PERFORM's inline statements

---

### Edge Cases

- What happens when a PERFORM statement references a paragraph that doesn't exist in the program? (Parser should still capture the reference; validation is separate)
- How does the parser handle PERFORM statements split across multiple lines with continuation in fixed format (columns 7-72)?
- What happens with malformed PERFORM statements (e.g., `PERFORM VARYING` without required FROM/BY/UNTIL clauses)?
- How are numeric literals vs. variable names distinguished in TIMES and VARYING clauses?
- What happens when END-PERFORM is missing from an inline PERFORM block?
- How does the parser handle PERFORM statements with both THRU and WITH TEST clauses (e.g., `PERFORM PARA-START THRU PARA-END WITH TEST AFTER UNTIL condition`)?
- What happens when THROUGH is spelled out instead of abbreviated as THRU?

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Parser MUST recognize and correctly tokenize all PERFORM statement variants: SIMPLE, TIMES, UNTIL, VARYING, and INLINE in COBOL fixed format
- **FR-002**: Parser MUST capture target paragraph name in all PERFORM statement types that reference paragraphs
- **FR-003**: Parser MUST capture optional THRU/THROUGH clause specifying a range of paragraphs to execute (PARA-START THRU PARA-END)
- **FR-004**: Parser MUST capture TIMES clause with either numeric literal or variable name reference
- **FR-005**: Parser MUST capture UNTIL clause with condition expression for conditional loop termination
- **FR-006**: Parser MUST capture WITH TEST BEFORE and WITH TEST AFTER timing qualifiers for UNTIL clauses
- **FR-007**: Parser MUST capture VARYING clause components: control variable, FROM value, BY increment, UNTIL condition
- **FR-008**: Parser MUST support nested VARYING clauses for multi-dimensional table processing
- **FR-009**: Parser MUST capture inline statements within PERFORM...END-PERFORM blocks as children in the AST
- **FR-010**: Parser MUST recognize END-PERFORM as the terminator for inline PERFORM blocks
- **FR-011**: Parser MUST support all standard COBOL statements within inline PERFORM blocks (MOVE, DISPLAY, CALL, IF, etc.)
- **FR-012**: Parser MUST handle PERFORM statements that span multiple lines in fixed format (columns 7-72, continuation in column 7)
- **FR-013**: Parser MUST distinguish between numeric literals and variable references in TIMES and VARYING clauses
- **FR-014**: Parser MUST generate PerformStatement AST nodes with correct `perform_type` attribute: "SIMPLE", "TIMES", "UNTIL", "VARYING", or "INLINE"
- **FR-015**: Parser MUST include all PERFORM statement attributes in JSON serialization via `to_dict()` method
- **FR-016**: Parser MUST support combining THRU and UNTIL clauses (e.g., `PERFORM PARA-A THRU PARA-B UNTIL condition`)
- **FR-017**: Parser MUST support combining THRU and TIMES clauses (e.g., `PERFORM PARA-A THRU PARA-B 5 TIMES`)
- **FR-018**: Parser MUST support combining THRU and WITH TEST clauses (e.g., `PERFORM PARA-A THRU PARA-B WITH TEST AFTER UNTIL condition`)

### Key Entities *(include if feature involves data)*

- **PerformStatement**: AST node representing any PERFORM statement with attributes:
  - `perform_type`: Enum value ("SIMPLE", "TIMES", "UNTIL", "VARYING", "INLINE")
  - `target_paragraph`: Name of paragraph to execute (None for inline PERFORM)
  - `thru_paragraph`: Ending paragraph for THRU clause (None if not used)
  - `times_count`: Union[int, str, None] - int for numeric literals (e.g., 10), str for variable names (e.g., "WS-COUNT") - enables semantic analysis and source regeneration
  - `until_condition`: Condition expression for UNTIL clause (None if not used)
  - `test_timing`: Enum for WITH TEST clause ("BEFORE", "AFTER", or None for default) - **will be added to model**
  - `varying_clause`: Dictionary containing control variable, FROM value, BY increment
  - `inline_statements`: List of statement nodes for PERFORM...END-PERFORM blocks

- **VaryingClause**: Structure containing loop control parameters:
  - `control_variable`: Variable name being varied (str)
  - `from_value`: Starting value as Union[int, str, None] - int for numeric literals, str for variable references
  - `by_value`: Increment value as Union[int, str, None] - int for numeric literals, str for variable references
  - Nested VARYING clauses for multi-dimensional iteration supported via parent-child AST relationships

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Parser successfully parses all PERFORM statement variations documented in IBM Enterprise COBOL Language Reference without errors
- **SC-002**: 100% of PERFORM statement test cases pass, covering all combinations of clauses (THRU, TIMES, UNTIL, VARYING, WITH TEST)
- **SC-003**: AST representation of PERFORM statements is complete enough to regenerate equivalent COBOL source code from the AST
- **SC-004**: JSON serialization of PerformStatement nodes includes all attributes necessary for cross-tool interoperability
- **SC-005**: Parser handles PERFORM statements in programs up to 50,000 lines without performance degradation (parse time under 5 seconds)
- **SC-006**: All PERFORM statement edge cases (missing END-PERFORM, malformed clauses, multi-line continuations) are handled with clear error messages or graceful recovery
- **SC-007**: Test coverage for PERFORM statement parsing code exceeds 90% line coverage and 85% branch coverage
- **SC-008**: Parser correctly distinguishes between all 5 PERFORM types with 100% accuracy in classification
## Assumptions

1. **Fixed Format Assumption**: This feature focuses on COBOL fixed format (columns 1-6 for sequence numbers, column 7 for continuation/comment, columns 8-72 for code). Free format COBOL may have different parsing requirements.

2. **IBM Enterprise COBOL Priority**: The parser prioritizes IBM Enterprise COBOL dialect features and syntax. ANSI COBOL or other dialects may have slight variations in PERFORM statement syntax.

3. **Lexer Already Handles Tokenization**: This feature assumes the lexer correctly tokenizes COBOL keywords (PERFORM, THRU, THROUGH, TIMES, UNTIL, VARYING, END-PERFORM) and can distinguish them from identifiers.

4. **Condition Expression Parsing**: Complex condition expressions in UNTIL clauses are parsed by existing expression parsing logic. This feature focuses on PERFORM-specific structure, not general condition parsing improvements.

5. **Semantic Validation is Separate**: The parser captures the structure of PERFORM statements but does not validate that referenced paragraphs exist, that loop variables are properly defined, or that conditions are semantically valid. Such validation occurs in a separate analysis phase.

6. **WITH TEST BEFORE is Default**: When WITH TEST clause is omitted in PERFORM UNTIL statements, the default behavior is TEST BEFORE (condition evaluated before first execution), per COBOL standard.

7. **Nested PERFORM Scope**: Nested PERFORM statements (PERFORM within PERFORM) are captured as separate statement nodes with proper parent-child relationships in the AST.

8. **END-PERFORM Optional for Simple PERFORM**: END-PERFORM is required only for inline PERFORM blocks (PERFORM...statements...END-PERFORM). Simple paragraph calls (PERFORM PARA-NAME) do not use END-PERFORM.

9. **Memory Efficiency**: Given the parser's memory management design (64MB-8GB configurable limits), PERFORM statement parsing must be memory-efficient to handle programs with thousands of PERFORM statements.

10. **Error Recovery Mode Awareness**: Test cases should validate PERFORM parsing behavior in both FAIL_FAST (production) and COLLECT_ALL (development) error recovery modes.

## Dependencies

- Lexer must correctly tokenize PERFORM keywords and related tokens (THRU, THROUGH, TIMES, UNTIL, VARYING, END-PERFORM, WITH, TEST, BEFORE, AFTER)
- Expression parser must handle condition expressions in UNTIL clauses
- AST base classes (ASTNode, SourceLocation) must be stable for PerformStatement inheritance
- JSON serialization framework must support PerformStatement's to_dict() method
- Test infrastructure must support parsing COBOL fixed format test programs
- Existing parser infrastructure for handling procedure division statements and paragraphs

## Out of Scope

- Free format COBOL syntax variations
- PERFORM statement semantic validation (verifying paragraph existence, variable types, condition validity)
- Optimization of PERFORM statement execution (this is a parser, not a compiler or interpreter)
- PERFORM THRU behavior when ending paragraph is before starting paragraph (runtime behavior, not parsing)
- Integration with specific IDE features or code completion for PERFORM statements
- Migration tools to convert between different PERFORM statement styles
- Performance profiling of executed PERFORM statements at runtime
- COBOL-85 vs COBOL-2002 vs COBOL-2014 dialect-specific PERFORM variations (IBM Enterprise COBOL is the priority)

## Clarifications

### Session 2026-01-11

- Q: Should we add test_timing attribute to PerformStatement model for WITH TEST BEFORE/AFTER support? → A: B (Add test_timing attribute to PerformStatement model to align code with spec requirements and ensure full IBM Enterprise COBOL compliance)
- Q: Should times_count be changed to support both numeric literals and variable name references? → A: A (Change times_count to Union[int, str, None] to store literals as int and variable names as str for semantic analysis and source regeneration)
- Q: Should WITH TEST parsing be implemented as part of this feature or deferred? → A: B (Implement WITH TEST parsing in parser to ensure full COBOL compliance with SC-001 requirement)
- Q: Should from_value and by_value in varying_clause use Union[int, str] for consistency? → A: A (Use Union[int, str] for from_value and by_value to maintain semantic type consistency across all numeric parameters)