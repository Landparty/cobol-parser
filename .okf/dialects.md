---
type: Module
title: Dialects
description: IBMEnterpriseCobol dialect support — EXEC SQL/CICS/IMS node types, IBM data-item validation, and the intrinsic-function / LE callable-service lookups.
tags: [dialects, ibm-enterprise, exec-sql, exec-cics, exec-ims, intrinsic-functions, le-services]
timestamp: 2026-09-15T00:00:00Z
---

# Dialects (`cobolparser/dialects/`)

IBM Enterprise COBOL dialect support: extra AST node types for EXEC
SQL/CICS/IMS, IBM-specific data-item validation, and the intrinsic-function/
LE-service lookups the CLI and analyzers read.

```python
from cobolparser.dialects.ibm_enterprise import IBMEnterpriseCobol

dialect = IBMEnterpriseCobol()
dialect.is_reserved_word(word)                    # bool, case-insensitive
dialect.is_intrinsic_function(name)                # bool
dialect.is_cics_command(name) / is_ims_command(name)
dialect.is_le_callable_service(name)
dialect.get_le_service_info(name) -> dict | None
dialect.get_intrinsic_function_signature(name) -> dict | None
dialect.validate_data_item(item) -> list[str]      # warnings
dialect.validate_program_structure(program) -> list[str]
dialect.get_dialect_info() -> dict[str, Any]
```

`ibm_enterprise.py` also defines the AST node types EXEC SQL/CICS/IMS
statements and IBM-specific data items build on: `ExecSQLStatement`,
`ExecCICSStatement`, `ExecIMSStatement`, `IBMDataItem`, `IBMDataType`.

## `ExecSQLStatement.null_indicators` (`models/sql_statements.py`)

Both indicator forms land here: `:X:IND` and `:X INDICATOR :IND`. The EXEC
SQL parser rebuilds `sql_text` without a blank before a colon
(`INDICATOR:IND`), so `_SQL_INDICATOR_KW_RE` takes `\s*`, not `\s+` --
before 2026-09-28 the keyword form was only recognized in hand-written test
strings, never in parsed source. Indicators also appear in `host_variables`
(the plain `:name` scan). Pinned by
`test_sql_statements.py::TestHostVariables::test_null_indicator_keyword_as_parsed_from_source`.

## `ExecSQLStatement.cursor_name` on positioned UPDATE/DELETE

`UPDATE ... WHERE CURRENT OF C1` / `DELETE FROM T WHERE CURRENT OF C1` set
`cursor_name` to the cursor (`_SQL_CURRENT_OF_RE`); a searched UPDATE/DELETE
leaves it `None`. Before 2026-09-28 it was `None` for both. `tables[0]` is
still the target table, so `io_logger`'s `target` is unchanged. Pinned by
`test_sql_statements.py::TestCursorOperations::test_positioned_update_delete_names_the_cursor`.

## `ExecSQLStatement.tables` (`models/sql_statements.py`)

Source order, with the statement's **target first** for INSERT / UPDATE /
DELETE / MERGE (`io_logger` and the CRUD matrix rely on `tables[0]`); the
rest are tables a subquery, `INSERT ... SELECT` or `MERGE ... USING` reads
(INSERT/UPDATE subquery tables were missing before 2026-09-28). A FROM that
separates function arguments -- `EXTRACT(YEAR FROM D)`, `TRIM(... FROM C)`,
`SUBSTRING(N FROM 1)` -- is blanked first (`_blank_function_argument_froms`:
a FROM directly inside a parenthesised group not opening with SELECT/WITH),
so the column after it is no longer reported as a table.

## `get_intrinsic_function_signature` (2026-09-10)

Backed by the complete catalogue in `dialects/le_signatures.py` (the one
`le-info` reads — see [analysis.md](analysis.md)'s "Call signatures"
subsection for the full `le_service_signature`/`intrinsic_signature` API),
so every function `is_intrinsic_function` accepts has a signature here. The
returned dict carries the catalogue's own keys (`returns`, `arguments`,
`call_example`, ...) plus historical `return_type`/`parameters`/
`description` keys derived from the catalogue's `returns`/`arguments`/
`summary` — **not** from a second, hand-written table. Such a table
(`_LEGACY_INTRINSIC_SIGNATURES`, five functions) used to exist and always
overrode the catalogue's answer regardless of which was more correct: it
kept reporting `LENGTH`'s argument category as `["string"]` after the
catalogue was corrected to the more precise `["any"]` (LENGTH accepts any
category, not just alphanumeric). Only `CURRENT-DATE`'s fixed return
length — a fact the catalogue has no structured field for at all — is still
added on top, via the much narrower `_INTRINSIC_EXTRA_FIELDS`.

See [ast-models.md](ast-models.md) and [analysis.md](analysis.md) for the
`PictureClause`/`MoveTypeChecker` P-scaling notes that were touched in the
same pass.
