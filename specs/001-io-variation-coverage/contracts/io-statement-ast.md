# Contract — IO Statement AST & Diagnostics

## Scope

This contract governs AST structures, serialization, and diagnostics for all IBM Enterprise COBOL fixed-format IO statements supported by the parser. It complements `io-coverage-schema.json` (coverage artifact) and binds the following layers:

- Lexer tokens for IO verbs/qualifiers
- Parser productions generating AST nodes in `cobolparser/models/statements.py`
- JSON serialization via `ASTNode.to_dict()` and `SerializationConfig`
- Diagnostic payload emitted by `ParseError`

## AST Nodes

| Verb | AST Class | Required Fields |
|------|-----------|-----------------|
| OPEN | `IOOpenStatement` | `file_name`, `mode`, `with_lock`, `reel_unit_control`, `location`, `metadata` |
| CLOSE | `IOCloseStatement` | `file_name`, `options` (e.g., `WITH NO REWIND`), `lock_release`, `location` |
| READ | `IOReadStatement` | `file_name`, `access_mode` (NEXT, PREVIOUS, RANDOM), `with_lock`, `at_end_clause`, `invalid_key_clause`, `key_name`, `location`, `metadata` |
| WRITE | `IOWriteStatement` | `file_name`, `record_name`, `advancing_clause`, `from_clause`, `with_lock`, `location` |
| REWRITE | `IORewriteStatement` | `file_name`, `record_name`, `invalid_key_clause`, `not_invalid_key_clause`, `with_lock`, `location` |
| DELETE | `IODeleteStatement` | `file_name`, `invalid_key_clause`, `not_invalid_key_clause`, `with_lock`, `location` |
| START | `IOStartStatement` | `file_name`, `key_condition`, `invalid_key_clause`, `not_invalid_key_clause`, `location` |
| ACCEPT | `IOAcceptStatement` | `target`, `from_clause` (DATE, TIME, MNEMONIC), `with_auto`, `location`, `metadata` |
| DISPLAY | `IODisplayStatement` | `operands`, `upon_device`, `with_no_advancing`, `location` |
| UNLOCK | `IOUnlockStatement` | `file_name`, `record_scope`, `location` |

### Shared Requirements

1. **SourceLocation**: Every node MUST populate `location.file`, `location.line`, and `location.column` using the fixed-format coordinates determined in `parser.py`.
2. **Metadata**: Use the `_metadata` dict to capture clause presence flags (`has_invalid_key`, `uses_advancing`, etc.) so serialization remains backward compatible.
3. **Serialization**: `to_dict()` outputs must include `node_type`, the verb-specific fields above, `location`, and `metadata`. New keys must be documented in this contract.

## Diagnostics Contract

Negative fixtures for IO statements rely on `ParseError` instances emitted through existing error recovery paths.

- **Fields**: `code`, `message`, `line`, `column`, `context`, `recovery_hint`.
- **Codes**: Introduce verb-specific codes prefixed with `IO_` (e.g., `IO_READ_INVALID_KEY_ORDER`).
- **Messages**: Provide actionable text referencing the offending clause ("`INVALID KEY` requires `KEY IS data-name` in indexed files").
- **Recovery**: When in `COLLECT_ALL` mode, parser must continue after inserting a synthetic skip token; the diagnostic must note this behavior in `recovery_hint`.

## Clause Handling Rules

- `WITH LOCK` can appear on OPEN, READ, REWRITE, DELETE; AST nodes will include `with_lock: bool` and `lock_scope: Literal["record","file"]` when applicable.
- `AT END` and `INVALID KEY` blocks serialize as nested structures with `statements` arrays referencing child nodes (mirroring existing IF/PERFORM serialization) to maintain consistency.
- `AFTER ADVANCING` and `BEFORE ADVANCING` on WRITE are modeled via an `advancing_clause` object: `{ "type": "AFTER" | "BEFORE", "value": <literal or identifier>, "unit": "LINES" | "CHANNEL" }`.
- ACCEPT/DISPLAY environment names (DATE, TIME, COMMAND-LINE, etc.) persist in `from_clause.kind` so downstream tooling can distinguish device vs. mnemonic variations.

## Backward Compatibility

- Existing nodes such as `DisplayStatement` remain aliased to the new `IODisplayStatement` to avoid breaking imports; deprecation warnings (if any) must be documented in release notes.
- JSON keys introduced here (e.g., `with_lock`, `advancing_clause`) require version bumps in the coverage artifact schema and a changelog entry.

## Acceptance Criteria

A pull request updating IO AST behavior is considered contract-compliant when:

1. All new/updated nodes conform to the field lists above and include docstrings + type hints.
2. Serialization snapshots captured in contract tests match the schema documented here.
3. Negative tests assert the expected `ParseError` structure using the standardized `IO_*` codes.
4. `io-coverage-schema.json` validates successfully against real artifacts produced by the test suite.
