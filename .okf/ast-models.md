---
type: Module
title: AST Models
description: ASTNode hierarchy — CobolProgram, data items, statement nodes, to_dict()/to_json() serialisation.
tags: [ast, models, cobol-program, data-items, statements]
timestamp: 2026-07-24T00:00:00Z
---

# Overview

`cobolparser/models/` — all AST node classes. Every node extends `ASTNode`
from `ast_base.py` and must implement `to_dict()`. Instantiate nodes via
`ASTNodeFactory` (`core/ast_factory.py`), not directly.

# Base Classes (`models/ast_base.py`)

```python
@dataclass
class SourceLocation:
    line: int
    column: int
    filename: str

class ASTNode:
    location: SourceLocation | None
    def to_dict(self) -> dict: ...
    def to_json(self) -> str: ...
    def find_all_by_type(self, type_name: str) -> list[ASTNode]: ...

class ASTValidator: ...
```

# Program Structure (`models/program.py`)

```python
class CobolProgram(ASTNode):
    program_id: str
    divisions: list[CobolDivision]
    # ...

class CobolDivision(ASTNode):
    name: str
    sections: list[CobolSection]

class CobolSection(ASTNode):
    name: str
    paragraphs: list[CobolParagraph]

class CobolParagraph(ASTNode):
    name: str
    statements: list[CobolStatement]
```

`CobolProgram.to_json()` exports the full tree as JSON for cross-platform
interoperability.

Serialization fidelity notes (2026-07-07):

* `CobolProgram.contained_programs` holds additional program units from the
  same compilation unit (stacked/nested programs); serialized as
  `contained_programs` and included in `get_all_statements()`.
* `CobolDataItem.to_dict()` serializes level-88 children as
  `condition_names`; `CobolSection.to_dict()` serializes level-66 children as
  `renames_items`. Both were previously captured in-memory but dropped at the
  JSON boundary.
* `CallStatement.to_dict()` serializes `not_on_exception` (previously
  omitted), and CALL handler statements are registered as AST children so
  `find_all_by_type()` agrees with `get_all_statements()`.
* `CallStatement.using_parameters`' `CallParameter.passing_mode` now
  persists correctly across a comma-separated parameter list within one
  `BY REFERENCE`/`BY CONTENT`/`BY VALUE` group (2026-07-24) — `CALL 'P'
  USING BY CONTENT a, b` previously mode-tagged `b` back to the REFERENCE
  default instead of CONTENT (both parameter names survived; only the
  mode was silently wrong). See [parser.md](parser.md) "Follow-up
  comma-list sweep" targeted round.
* `GoStatement` carries `target_paragraphs` (all computed-GO-TO targets) in
  addition to `target_paragraph` (the first).
* `XmlJsonStatement` (`models/statements/misc.py`) models XML/JSON
  GENERATE/PARSE with `verb`, `action`, `primary_operand`, `from_item`, and
  raw `clause_text`.
* `IOWriteStatement.advancing_clause` is populated by the WRITE parser
  (`{"type": "AFTER", "value": 2, "unit": "LINES"}`), not just
  `advancing_mode`. `unit` is also `"CHANNEL"` for `ADVANCING PAGE`
  (`value="PAGE"`); `"LINES"` for `ADVANCING identifier LINES` (a
  data-name holding a line count — `value` is the data-name, not an int);
  and `"MNEMONIC"` for a bare SPECIAL-NAMES mnemonic-name target with no
  `LINE`/`LINES` suffix (`value` is the mnemonic-name, e.g.
  `ADVANCING TOP-OF-PAGE` → `{"type": "AFTER", "value": "TOP-OF-PAGE",
  "unit": "MNEMONIC"}`) (2026-07-20).
* `IORewriteStatement.from_clause` (2026-07-09) — the `REWRITE rec FROM data`
  source (previously consumed and discarded). Also added to `operands` via
  `_add_unique_operand`, matching `IOWriteStatement.set_from`, so
  identifier-discovery consumers that read `operands` see it.
* `IOStartStatement.key_name` (2026-07-09) — the `START f KEY IS ... data-name`
  key (previously discarded; `key_condition` kept only the operator). Also
  tracked in `operands` for the same reason.
* `StopStatement.returning` (2026-07-09) — `STOP RUN RETURNING x` return code
  (previously dropped).
* `ArithmeticStatement.targets: list[str]` (2026-07-22) — full ordered list
  of comma/space-separated `TO`/`FROM` targets (`ADD 1 TO a, b, c`);
  `.target` keeps the first for backward compatibility. `.rounded: bool`
  (also on `ComputeStatement`) and `.is_corresponding: bool` (ADD/SUBTRACT
  `CORRESPONDING`) were previously discarded or misparsed as literal
  operands. `DivideStatement.remainder: str | None` — the `REMAINDER r`
  target (was entirely unimplemented). See [parser.md](parser.md)
  "Statement-Support Verification Sweep (2026-07-22/23)".
* `UnstringStatement.tallying_variable: str | None` (2026-07-22) —
  `TALLYING IN counter`, documented but never implemented; `.delimiters`
  now collects every `OR`-joined delimiter (`DELIMITED BY d1 OR d2`),
  previously only the first survived.
* `IOOpenStatement.file_modes: dict[str, str]` (2026-07-22) — per-file
  open mode keyed by file name, for `OPEN INPUT a OUTPUT b`-style
  statements where `.open_mode` alone (first mode group only) can't
  distinguish `b`'s real mode. `crud_matrix.py`/`io_logger.py` still read
  `.open_mode` alone — not yet updated to consult this map.
* `IOWriteStatement.not_at_eop_clause` (2026-07-22) — `NOT AT
  END-OF-PAGE`; `.at_eop_clause`/`.not_at_eop_clause` (format-1,
  sequential files) are now actually populated by the WRITE parser
  (previously `AT END-OF-PAGE` was entirely unimplemented; only format-2's
  `INVALID KEY`/`NOT INVALID KEY` worked).
* `IOAcceptStatement.environment_name` (2026-07-22) — `ACCEPT x FROM
  ENVIRONMENT "name"`'s variable name; the field existed but the parser
  never called its setter.
* `PictureClause` now sizes `PIC N(n)` (national/DBCS) correctly — one
  character position per `N`, no double-byte counting (2026-07-22;
  previously fell through to a default size of 1 regardless of `n`).
* `ArithmeticStatement.givings: list[str]` (2026-07-24) — full ordered
  list of comma/space-separated `GIVING` result targets (`ADD A TO B
  GIVING C, D`); `.giving` keeps the first for backward compatibility,
  mirroring the `target`/`targets` split above. Applies to
  `AddStatement`/`SubtractStatement`/`MultiplyStatement`/`DivideStatement`
  alike. See [parser.md](parser.md) "Follow-up comma-list sweep
  (2026-07-24)".
* `MultiplyStatement`/`DivideStatement` now populate `.target`/`.targets`
  (2026-07-24) for format 1 (no `GIVING`) — `MULTIPLY x BY id-2, id-3` /
  `DIVIDE x INTO id-2, id-3` overwrite their second operand(s) in place,
  so they're result targets like ADD/SUBTRACT's `TO`/`FROM`, not just
  `.operands` entries (previously only `.operands` was populated, and
  anything past the first comma was dropped). Format 2 (`GIVING`)
  deliberately does **not** set `.target` — the second operand there is a
  multiplicand/divisor, not a result.

# Data Items (`models/data_items.py`)

```python
class CobolDataItem(ASTNode):
    level: int               # 01, 02, …, 49, 66, 77, 88
    name: str
    picture: PictureClause | None
    occurs: OccursClause | None
    # REDEFINES, VALUE, USAGE, …

class PictureClause(ASTNode):
    picture_string: str      # e.g. "9(5)V99"
    category: DataCategory

class OccursClause(ASTNode):
    min_times: int
    max_times: int | None      # None = fixed-size OCCURS
    depending_on: str | None
    indexed_by: str | None     # first index (backward-compatible)
    index_names: list[str]     # all INDEXED BY names (2026-07-09)
    key_clauses: list[dict]    # {"direction": "ASCENDING"|"DESCENDING",
                               #  "keys": [...]} — SEARCH ALL keys (2026-07-09)
```

Two shapes here regularly surprise consumers (both confirmed against source
2026-08-02, and both compensated for in
[generators.md](generators.md)'s data generator):

* **`PictureClause.is_signed` reports only an explicit `S`.** A
  numeric-edited picture whose sign lives in an insertion symbol —
  `PIC -ZZ,ZZ9.99`, `PIC +999`, `PIC 999CR`, `PIC 999DB` — can hold a
  negative value but reports `is_signed=False`. Code deciding "may this
  field be negative?" must also test `is_numeric_edited` plus the presence
  of `-`/`+`/`CR`/`DB` in the pattern.
* **Level-88 `THRU` ranges are marked, not expanded.**
  `ConditionNameItem.values` for `88 ST-OK VALUE 2 THRU 4.` is
  `["2", "THROUGH:4"]` — the second entry is the range *end*, tagged with a
  `THROUGH:` prefix, and the intermediate values are not enumerated. A
  consumer wanting the field's full domain has to expand the range itself
  (and bound the expansion — `VALUE 1 THRU 999999` is legal COBOL).

`index_names` and `key_clauses` are serialized only when non-empty. Before
2026-07-09 `ASCENDING/DESCENDING KEY` was dropped and `INDEXED BY` kept only
its last name (and was lost entirely when a KEY clause preceded it). See
[parser.md](parser.md) Silent-Drop Audit (2026-07-09).

# SQL Statement Nodes (`models/sql_statements.py`)

AST nodes for EXEC SQL, EXEC CICS, and EXEC IMS DLI blocks captured by
`ibm_exec_statements.py`.

# Statement Models (`models/statements/`)

| File | Node Classes |
|------|-------------|
| `base.py` | `CobolStatement`, `CobolExpression`, `ArithmeticExpression`, `ConditionalExpression`, `LogicalExpression`, `FunctionCall` |
| `arithmetic.py` | `ArithmeticStatement`, `AddStatement`, `SubtractStatement`, `MultiplyStatement`, `DivideStatement`, `ComputeStatement` |
| `call.py` | `CallStatement`, `EntryStatement`, `CallParameter` |
| `control.py` | `IfStatement`, `EvaluateStatement`, `WhenClause`, `PerformStatement`, `GoStatement`, `StopStatement`, `SearchStatement` |
| `data.py` | `MoveStatement`, `DisplayStatement`, `InitializeStatement`, `InspectStatement`, `SetStatement`, `StringStatement`, `UnstringStatement` |
| `io.py` | `IOReadStatement`, `IOWriteStatement`, `IOOpenStatement`, `IOCloseStatement`, `IOAcceptStatement`, `IORewriteStatement`, `IODeleteStatement`, `IOStartStatement`, `IOUnlockStatement` |
| `misc.py` | `SelectStatement`, `CopyStatement`, `ContinueStatement`, `ExitStatement`, `GobackStatement`, `CancelStatement`, `AlterStatement`, `GenerateStatement`, `ReleaseStatement`, `ReturnStatement`, `UseStatement`, `SortStatement`, `MergeStatement`, `CommitStatement`, `RollbackStatement` |

Notes (2026-07-07 audit remediation):

* `PerformStatement.after_clauses` — list of AFTER dimensions of a
  `PERFORM VARYING ... AFTER ...` loop, each
  `{"variable", "from_value", "by_value", "until_condition":
  CobolExpression | None}`; populated via `add_after_clause()` (which also
  registers the condition as a child) and serialized as `after_clauses`
  only when non-empty (H2).
* `CobolExpression.to_dict()` includes `operands` — condition/expression
  text (e.g. PERFORM UNTIL conditions) previously vanished at the JSON
  boundary.
* `SelectStatement`'s long-standing fields (`alternate_keys`,
  `file_status_vsam`, `reserve_areas`, `padding_character`,
  `record_delimiter`, `password`, `lock_mode`/`lock_on`/
  `lock_with_rollback`, `sharing_mode`, `assign_device_type`) are now
  actually populated by the ENVIRONMENT division parser (H5).
* Arithmetic statements' `on_size_error` / `not_on_size_error` lists can
  contain any statement type (registry-dispatched), all registered as AST
  children (H1).

# ASTNodeFactory

```python
from cobolparser.core.ast_factory import get_factory, create_node

factory = get_factory()
node = create_node("MoveStatement", location=loc, sending=..., receiving=...)
```

Raises `NodeTypeError` for unknown node types, `FieldValidationError` for bad fields.

# Traversal

```python
ast: CobolProgram = result.ast
move_stmts = ast.find_all_by_type("MoveStatement")
```

`find_all_by_type()` / `find_first_by_type()` match either the node's
`node_type` attribute (`"Statement"`, `"DataItem"`, ...) or its concrete
class name (`"MoveStatement"`, `"CallStatement"`, `"ExecSQLStatement"`,
`"IOReadStatement"`, ...). All statement subclasses share the generic
`node_type` `"Statement"` (their `to_dict()` distinguishes them via
`statement_type`), so the class name is the only way to select a specific
statement kind — this is what the CLI `analyze` and `parse --find-type`
subcommands rely on.

# Additive expression-tree fields (2026-07-20, M12)

* `ComputeStatement.expression_tree: CobolExpression | None` — structural
  decomposition of the COMPUTE expression (`set_expression_tree()`); the
  raw `.expression` string is unchanged. Emitted in `to_dict()` under
  `"expression_tree"` only when populated, so pre-M12 dict output is
  byte-identical.
* `CobolExpression.condition_tree: CobolExpression | None` — structural
  decomposition of a raw condition (`set_condition_tree()`; also
  registered as a child for generic traversal). Used by PERFORM UNTIL:
  `until_condition` remains the historical `CobolExpression("CONDITION")`
  with the raw joined string in `operands`, and the tree rides alongside.
  Emitted in `to_dict()` under `"condition_tree"` only when populated.
* Consumers (`ProgramFlowAnalyzer`, `coverage_analyzer`,
  backend extractors per `interface-contract.md`) need no changes — all
  historical fields/keys are untouched.

# See Also

* [parser.md](parser.md) — produces AST nodes
* [analysis.md](analysis.md) — consumes AST via analyzer interfaces
