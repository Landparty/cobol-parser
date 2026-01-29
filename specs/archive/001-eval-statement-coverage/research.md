# Research Notes — COBOL Fixed-Format EVALUATE Coverage (Phase 0)

## Decision 1: AST shape for EVALUATE
- **Decision**: Introduce `EvaluateStatement` (subclass of `CobolStatement`) with fields: `subjects: List[CobolExpression]`, `when_clauses: List[WhenBranch]` where each branch captures selectors (values, ranges ANY/THRU/THROUGH, AND/OR conditions for EVALUATE TRUE), `statements: List[CobolStatement]`, and `default_when` (WHEN OTHER). Include `to_dict()` mirroring existing AST serialization patterns (location, metadata, children) so JSON export stays stable.
- **Rationale**: Existing statements (`IfStatement`, `PerformStatement`) follow the `CobolStatement` pattern with explicit fields plus children; aligning keeps serialization consistent and keeps diagnostics/hooks compatible.
- **Alternatives considered**: (a) Reuse `IfStatement`/generic expression tree to represent EVALUATE branches—rejected because it obscures WHEN semantics and complicates coverage mapping. (b) Represent EVALUATE as generic block node—rejected; loses selector structure required for diagnostics and variant coverage reporting.

## Decision 2: Parser integration & fixed-format handling
- **Decision**: Implement an explicit EVALUATE parser routine that: consumes `EVALUATE` token(s), parses 1..N subjects separated by `ALSO`, supports `EVALUATE TRUE/FALSE` with subsequent conditional expressions (AND/OR), parses WHEN clauses with selectors (literal/identifier, ANY, ranges via THRU/THROUGH, figurative constants), tracks nesting, and requires `END-EVALUATE`. Reuse existing helpers for whitespace/comment skipping, expression parsing, and statement accumulation. Add fixed-format column validation via existing column/area checks before parsing tokens, emitting deterministic diagnostics with line/column.
- **Rationale**: Dedicated routine keeps control-flow semantics explicit and enables targeted diagnostics (missing WHEN, misaligned continuation, missing END-EVALUATE). Leveraging existing helpers avoids duplicated lexing/spacing logic and respects current memory/error recovery configurations.
- **Alternatives considered**: (a) Preprocess EVALUATE to IF chains—rejected; obscures AST semantics and complicates coverage. (b) Treat as generic statement with minimal validation—rejected; would not meet coverage/diagnostic requirements.

## Decision 3: Test strategy & regression guardrail
- **Decision**: Add exhaustive positive fixtures for each cataloged variant (single/multi subject, ANY, THRU/THROUGH, figurative constants, EVALUATE TRUE with AND/OR, WHEN OTHER, nesting) and negative fixtures for malformed cases (missing WHEN, misaligned continuation, invalid ranges, missing END-EVALUATE). Place unit/contract tests to assert AST/diagnostic shape and an integration regression gate that fails when any catalog entry lacks passing positive+negative coverage. Baseline by running `python -m pytest tests -v` before changes and after; ensure coverage ≥90%.
- **Rationale**: Aligns with constitution (TDD, coverage) and existing repository practice (`tests/{unit,contract,integration}/`). Regression gate ensures future grammar changes cannot silently drop EVALUATE support.
- **Alternatives considered**: (a) Rely solely on existing sample programs—rejected; insufficient variant coverage. (b) Add only positive cases—rejected; diagnostics and stability require negative coverage.

## Decision 4: Reuse of existing framework components
- **Decision**: Reuse current token types (`TokenType.EVALUATE`, `TokenType.END_EVALUATE`), AST base classes, serialization pipeline, and error recovery modes (`FAIL_FAST`, `COLLECT_ALL`). Use `MemoryConfiguration` defaults and existing fixed-format column handling utilities rather than introducing new dependencies.
- **Rationale**: Minimizes new surface area and risk; leverages already proven components and adheres to “use existing libraries that have proven themselves.”
- **Alternatives considered**: (a) Introduce external parsing combinator library—rejected to avoid dependency and performance risk. (b) Build standalone EVALUATE parser bypassing existing helpers—rejected to keep consistency and maintainability.

## Decision 5: Performance & diagnostics baseline
- **Decision**: Maintain target ≥10k lines/sec and <10% slowdown; monitor lexer share (<30%) and memory (<256MB for 50k lines). Ensure diagnostics include line/column and statement context for all EVALUATE errors; integrate with existing diagnostic structures.
- **Rationale**: Constitution performance and UX principles; EVALUATE is common (~60% programs), so regressions are costly.
- **Alternatives considered**: (a) Defer performance checks to later milestone—rejected per constitution. (b) Minimal diagnostics—rejected; UX consistency requires detailed messages.
