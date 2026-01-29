# Contracts — Fixed-Format EVALUATE

## AST Contract
- **Node**: `EvaluateStatement`
- **Serialized Shape (to_dict)**:
  ```json
  {
    "node_type": "Statement",
    "statement_type": "EVALUATE",
    "subjects": [ {"expression": "WS-GRADE", "type": "Identifier", "location": {...}} ],
    "when_clauses": [
      {
        "selectors": [ {"type": "Literal", "value": "1"} ],
        "statements": [ {"statement_type": "DISPLAY", ...} ],
        "location": {...}
      }
    ],
    "default_when": { ... WHEN OTHER branch ... },
    "location": {...},
    "metadata": {"dialect": "IBM"}
  }
  ```
- **Selectors**: support `Literal`, `Identifier`, `Any`, `Range {start, end, inclusive=true}`, `Condition {op: AND|OR, operands:[...]}`.
- **Ordering**: Preserve subject order and ALSO grouping; WHEN selectors align positionally to subjects.

## Diagnostic Contract
- **Shape**:
  ```json
  {
    "category": "ParseError|FormatError|Unsupported",
    "message": "Missing WHEN clause in EVALUATE",
    "line": 42,
    "column": 12,
    "context": "EVALUATE WS-CHOICE"
  }
  ```
- **Determinism**: One primary diagnostic per malformed statement; stable wording.
- **Locations**: Line/column must point at offending keyword or selector; continuation errors point at continuation line.

## Positive Coverage Matrix (catalog excerpts)
- Single subject, literals: `EVALUATE WS-GRADE` with multiple WHEN literals + WHEN OTHER.
- Single subject, ranges: `WHEN 1 THRU 5`, `WHEN 6 THRU 8`.
- Multiple subjects with ALSO: `EVALUATE WS-GRADE ALSO WS-STATUS` with aligned selectors.
- ANY mixing: `WHEN 1 ALSO ANY`, `WHEN ANY ALSO "X"`.
- Figurative constants: `WHEN ZERO`, `WHEN SPACE`, `WHEN HIGH-VALUES`.
- EVALUATE TRUE with conditions: `EVALUATE TRUE` + WHEN expressions using AND/OR.
- Nested EVALUATE inside WHEN body.
- Continuation line handling and indicator columns present.

## Negative Coverage Matrix
- Missing WHEN before END-EVALUATE.
- Missing END-EVALUATE terminator.
- Selector count mismatch vs subjects (excluding ANY allowance).
- Invalid THRU/THROUGH (reversed bounds, non-comparable types).
- Misaligned fixed-format columns/continuations.
- Mixed selector types that violate IBM rules (e.g., range plus ANY in same position if disallowed by grammar).

## Regression Gate
- Compute variant coverage report: each cataloged variant must have a passing positive fixture and at least one negative fixture.
- Gate fails CI if any catalog entry is untested or failing; surfaces list of missing variants.
