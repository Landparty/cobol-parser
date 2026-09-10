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
