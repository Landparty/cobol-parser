# Data Model — COBOL Fixed-Format EVALUATE

## Entities

### EvaluateStatement (AST node)
- **Inherits**: `CobolStatement`
- **Fields**:
  - `subjects: List[CobolExpression]` — one or more selectors; supports `EVALUATE TRUE/FALSE` by storing boolean literal plus subsequent condition expressions.
  - `when_clauses: List[WhenClause]` — ordered WHEN branches.
  - `default_when: Optional[WhenClause]` — WHEN OTHER branch.
  - `nested_statements: List[CobolStatement]` — statements inside each WHEN (children relationships also held by WhenClause).
  - `metadata/location` — from base class; required for JSON export.
- **Behaviors**: `to_dict()` includes statement_type="EVALUATE", subjects (serialized), when_clauses (serialized), default_when, children for statements to maintain traversal.

### WhenClause
- **Fields**:
  - `selectors: List[Selector]` — each selector may be literal, identifier, ANY, range (start/end), or composite for EVALUATE TRUE/condition with AND/OR.
  - `statements: List[CobolStatement]` — statements executed when selectors match.
  - `location`/`metadata` — for diagnostics/JSON.
- **Notes**: Maintains original order of selectors and preserves ALSO grouping for multi-subject matches.

### Selector
- **Variants**:
  - `LiteralSelector` (string/numeric/figurative constant)
  - `IdentifierSelector`
  - `AnySelector`
  - `RangeSelector` (start, end, inclusive, supports THRU/THROUGH)
  - `ConditionSelector` (for EVALUATE TRUE/FALSE with AND/OR expressions)
- **Purpose**: Encodes matching semantics for a WHEN branch; feeds diagnostics and coverage reporting.

### Diagnostic Record
- **Fields**: `message`, `category` (formatting/syntax/unsupported), `location` (line/column), `context` (statement snippet), `severity`.
- **Usage**: Emitted for malformed EVALUATE (missing WHEN, missing END-EVALUATE, misaligned columns, invalid ranges, selector count mismatch).

### Coverage Entry
- **Fields**: `variant_id`, `description`, `sample_path`, `expected_ast_or_diag`, `status` (pass/fail/missing).
- **Usage**: Drives the EVALUATE variant coverage report/gate.

## Relationships
- `EvaluateStatement` → `WhenClause` (1..N), plus optional `default_when`.
- `WhenClause` → `Selector` (1..N) capturing ALSO ordering and subject alignment.
- `WhenClause` → `CobolStatement` children (statements inside WHEN).
- Diagnostics reference `EvaluateStatement` and `WhenClause` locations.
- Coverage entries map to fixtures and expected AST/diagnostics for CI gate.

## Validation Rules
- At least one WHEN or WHEN OTHER must exist; missing WHEN yields deterministic diagnostic.
- Number of selectors per WHEN must match subject count unless ANY is present; mismatches produce diagnostics.
- THRU/THROUGH ranges must have ordered bounds; reversed or overlapping ranges flagged.
- Fixed-format column rules must be enforced (sequence/indicator areas, continuation handling); violations produce formatting diagnostics.
- `END-EVALUATE` required; missing terminator triggers diagnostic.

## State/Transitions
- Parsing state moves: read EVALUATE → collect subjects (or TRUE/FALSE + condition) → read WHEN clauses → optional WHEN OTHER → END-EVALUATE. Nested EVALUATE allowed within WHEN statements without altering outer selectors.
