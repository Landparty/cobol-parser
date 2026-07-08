---
type: Module
title: AST Models
description: ASTNode hierarchy — CobolProgram, data items, statement nodes, to_dict()/to_json() serialisation.
tags: [ast, models, cobol-program, data-items, statements]
timestamp: 2026-07-03T00:00:00Z
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
* `GoStatement` carries `target_paragraphs` (all computed-GO-TO targets) in
  addition to `target_paragraph` (the first).
* `XmlJsonStatement` (`models/statements/misc.py`) models XML/JSON
  GENERATE/PARSE with `verb`, `action`, `primary_operand`, `from_item`, and
  raw `clause_text`.
* `IOWriteStatement.advancing_clause` is populated by the WRITE parser
  (`{"type": "AFTER", "value": 2, "unit": "LINES"}`), not just
  `advancing_mode`.
* `IORewriteStatement.from_clause` (2026-07-09) — the `REWRITE rec FROM data`
  source (previously consumed and discarded).
* `IOStartStatement.key_name` (2026-07-09) — the `START f KEY IS ... data-name`
  key (previously discarded; `key_condition` kept only the operator).
* `StopStatement.returning` (2026-07-09) — `STOP RUN RETURNING x` return code
  (previously dropped).

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

# See Also

* [parser.md](parser.md) — produces AST nodes
* [analysis.md](analysis.md) — consumes AST via analyzer interfaces
