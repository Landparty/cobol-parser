---
type: Module
title: AST Models
description: ASTNode hierarchy — CobolProgram, data items, statement nodes, to_dict()/to_json() serialisation.
tags: [ast, models, cobol-program, data-items, statements]
timestamp: 2026-06-28T00:00:00Z
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
    max_times: int | None    # None = fixed-size OCCURS
    key_fields: list[str]
    index_names: list[str]
```

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

# See Also

* [parser.md](parser.md) — produces AST nodes
* [analysis.md](analysis.md) — consumes AST via analyzer interfaces
