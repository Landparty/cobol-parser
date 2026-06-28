# AST Models

> The typed node hierarchy produced by parsing; every node extends `ASTNode` and implements `to_dict()`.

## Files

| File | Purpose |
|------|---------|
| `cobolparser/models/ast_base.py` | `ASTNode` abstract base, `SourceLocation`, `ASTValidator`, `ValidationResult` |
| `cobolparser/models/program.py` | Top-level program structure nodes |
| `cobolparser/models/data_items.py` | DATA DIVISION item nodes |
| `cobolparser/models/sql_statements.py` | EXEC SQL statement models |
| `cobolparser/models/statements/base.py` | `CobolStatement` abstract base and expression nodes |
| `cobolparser/models/statements/arithmetic.py` | Arithmetic statement nodes |
| `cobolparser/models/statements/call.py` | `CallStatement`, `EntryStatement`, `CallParameter` |
| `cobolparser/models/statements/control.py` | Control-flow statement nodes |
| `cobolparser/models/statements/data.py` | Data-manipulation statement nodes |
| `cobolparser/models/statements/io.py` | I/O statement nodes |
| `cobolparser/models/statements/misc.py` | Miscellaneous statement nodes |
| `cobolparser/_data_fast.pyx` | Cython acceleration for DATA DIVISION PICTURE/clause loops |

## Key Classes — Base

| Name | Location | Description |
|------|----------|-------------|
| `ASTNode` | `ast_base.py` | Abstract base; requires `to_dict() -> dict`; provides `to_json()`, `find_all_by_type(type_name)` |
| `SourceLocation` | `ast_base.py` | Dataclass: `line: int`, `column: int`, `length: int` |
| `ValidationResult` | `ast_base.py` | Dataclass: `is_valid: bool`, `errors: list[str]` |
| `ASTValidator` | `ast_base.py` | Validates an AST tree; `.validate(node) -> ValidationResult` |

## Key Classes — Program Structure

| Name | Location | Description |
|------|----------|-------------|
| `CobolProgram` | `program.py` | Root node: `divisions: list[CobolDivision]`, `program_id: str` |
| `CobolDivision` | `program.py` | A COBOL division: `name: str`, `sections: list[CobolSection]` |
| `CobolSection` | `program.py` | A section: `name: str`, `paragraphs: list[CobolParagraph]` |
| `CobolParagraph` | `program.py` | A paragraph: `name: str`, `statements: list[CobolStatement]` |

## Key Classes — Data Items

| Name | Location | Description |
|------|----------|-------------|
| `CobolDataItem` | `data_items.py` | A data definition: `level: int`, `name: str`, `picture: PictureClause`, `occurs: OccursClause`, `value`, `children` |
| `PictureClause` | `data_items.py` | Parsed PICTURE string: `pattern: str`, `category: DataCategory` |
| `OccursClause` | `data_items.py` | Array dimensions: `min_times`, `max_times`, `depending_on` |
| `ConditionNameItem` | `data_items.py` | Level-88 condition name: `name: str`, `values: list` |
| `RenamesItem` | `data_items.py` | Level-66 RENAMES entry |

## Key Classes — Statement Models

### base.py

| Name | Description |
|------|-------------|
| `CobolStatement` | Abstract base for all statements; has `location: SourceLocation` |
| `CobolExpression` | Abstract expression base |
| `ArithmeticExpression` | Arithmetic expression tree |
| `ConditionalExpression` | A boolean condition |
| `LogicalExpression` | AND/OR combination of conditions |
| `FunctionCall` | COBOL intrinsic function call |

### arithmetic.py

| Name | Description |
|------|-------------|
| `ArithmeticStatement` | Abstract base for arithmetic verbs |
| `AddStatement` | ADD … TO … (GIVING …) |
| `SubtractStatement` | SUBTRACT … FROM … |
| `MultiplyStatement` | MULTIPLY … BY … |
| `DivideStatement` | DIVIDE … INTO … |
| `ComputeStatement` | COMPUTE identifier = expression |

### call.py

| Name | Description |
|------|-------------|
| `CallStatement` | CALL with ON EXCEPTION/ON OVERFLOW handling |
| `EntryStatement` | ENTRY 'name' USING … |
| `CallParameter` | A single USING parameter with BY REFERENCE/CONTENT/VALUE |

### control.py

| Name | Description |
|------|-------------|
| `IfStatement` | IF condition THEN … ELSE … END-IF |
| `EvaluateStatement` | EVALUATE subject WHEN … END-EVALUATE |
| `WhenClause` | A WHEN arm in EVALUATE |
| `PerformStatement` | PERFORM paragraph / PERFORM VARYING / inline PERFORM |
| `GoStatement` | GO TO paragraph |
| `StopStatement` | STOP RUN / STOP literal |
| `SearchStatement` | SEARCH / SEARCH ALL |

### data.py

| Name | Description |
|------|-------------|
| `MoveStatement` | MOVE source TO destination(s) |
| `DisplayStatement` | DISPLAY items |
| `InitializeStatement` | INITIALIZE identifier |
| `InspectStatement` | INSPECT tallying/replacing/converting |
| `SetStatement` | SET identifier TO value |
| `StringStatement` | STRING … DELIMITED BY … INTO … |
| `UnstringStatement` | UNSTRING source INTO … |

### io.py

| Name | Description |
|------|-------------|
| `IOAcceptStatement` | ACCEPT identifier (FROM device) |
| `IOReadStatement` | READ file (INTO …) (AT END …) |
| `IOWriteStatement` | WRITE record (FROM …) |
| `IOOpenStatement` | OPEN mode file |
| `IOCloseStatement` | CLOSE file |
| `IODeleteStatement` | DELETE file RECORD |
| `IORewriteStatement` | REWRITE record |
| `IOStartStatement` | START file KEY IS … |
| `IOUnlockStatement` | UNLOCK file |

### misc.py

| Name | Description |
|------|-------------|
| `GobackStatement` | GOBACK |
| `CancelStatement` | CANCEL program |
| `AlterStatement` | ALTER paragraph TO PROCEED TO paragraph |
| `GenerateStatement` | GENERATE report |
| `ReleaseStatement` | RELEASE record |
| `ReturnStatement` | RETURN file |
| `UseStatement` | USE AFTER ERROR PROCEDURE |
| `SortStatement` | SORT file ON KEY … |
| `MergeStatement` | MERGE file ON KEY … |
| `CommitStatement` | COMMIT |
| `RollbackStatement` | ROLLBACK |
| `ContinueStatement` | CONTINUE |
| `ExitStatement` | EXIT (PROGRAM / PERFORM / SECTION) |
| `SelectStatement` | SELECT file ASSIGN TO device |
| `CopyStatement` | COPY copybook-name (structural, not the preprocessor) |

## SQL Models (`sql_statements.py`)

| Name | Description |
|------|-------------|
| `SQLStatementInfo` | Parsed SQL block: `statement_type`, `raw_sql`, `host_variables` |
| `SQLStatementType` | Enum: SELECT, INSERT, UPDATE, DELETE, DECLARE, FETCH, OPEN, CLOSE, EXECUTE, COMMIT, ROLLBACK, other |
| `ExecSQLStatement` | EXEC SQL … END-EXEC block node |
| `DeclareCursorStatement` | EXEC SQL DECLARE cursor CURSOR FOR … |
| `FetchStatement` | EXEC SQL FETCH cursor INTO … |
| `DynamicSQLStatement` | EXEC SQL EXECUTE (dynamic) |
| `TransactionControlStatement` | COMMIT / ROLLBACK inside EXEC SQL |
| `parse_exec_sql()` | Parses raw SQL text into `SQLStatementInfo` |

## `to_dict()` Contract

Every `ASTNode` subclass must implement `to_dict() -> dict`. Rules:
- Keys are snake_case strings
- `SourceLocation` serializes to `{"line": n, "column": n, "length": n}` (or `None`)
- Child nodes recursively call their own `to_dict()`
- Lists of children serialize to `list[dict]`
- `to_json()` (on `ASTNode` base) is `json.dumps(self.to_dict(), indent=2)`
- `find_all_by_type("MoveStatement")` does a depth-first search for nodes whose class name matches

## ASTNodeFactory

Use `ASTNodeFactory` (via `create_node()`) rather than instantiating nodes directly:

```python
from cobolparser.core import create_node
node = create_node("MoveStatement", source=..., destinations=[...], location=loc)
```

Raises `NodeTypeError` for unknown type names, `FieldValidationError` for invalid fields.

## Public API (exported symbols)

```python
from cobolparser import (
    CobolProgram, CobolDivision, CobolSection,
    CobolDataItem, PictureClause, OccursClause,
    MoveStatement, DisplayStatement, PerformStatement,
    CallStatement, IfStatement, EvaluateStatement,
)
from cobolparser.models.sql_statements import SQLStatementInfo, parse_exec_sql
```

## Gotchas / Invariants

- `ASTNode.to_dict()` is abstract — forgetting to implement it on a new node class causes a runtime error, not a type error.
- `find_all_by_type()` matches on class **name**, not class identity — string argument must match exactly.
- `_data_fast.pyx` accelerates DATA DIVISION parsing (picture clause and data item clause loops) but does not change the model classes — it only speeds up how `DataDivisionParser` populates them.
- Level-88 items (`ConditionNameItem`) are children of their parent `CobolDataItem`, not siblings.
- `WhenClause` contains a list of conditions; the last WHEN can be `WHEN OTHER`.

## Refresh Checklist

- [ ] Check `models/statements/` for any new statement node files or classes
- [ ] Verify `SQLStatementType` enum values against `sql_statements.py`
- [ ] Check `CobolDataItem` fields against `data_items.py`
- [ ] Check `ASTNode.to_dict()` signature — it must remain `-> dict`
- [ ] Verify `_data_fast.pyx` still exists and still accelerates the DATA DIVISION parser
