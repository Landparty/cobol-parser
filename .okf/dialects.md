---
type: Module
title: Dialects
description: IBMEnterpriseCobol dialect tables and lookups (reserved words, intrinsic functions, CICS/IMS command sets, LE callable services, COMP-3 validation), the le_signatures call-signature catalogue, and notes on the EXEC SQL statement model the parser builds.
tags: [dialects, ibm-enterprise, exec-sql, exec-cics, exec-ims, intrinsic-functions, le-services]
timestamp: 2026-10-15T00:00:00Z
---

# Dialects

`cobolparser/dialects/` holds the IBM Enterprise COBOL word tables and lookups
(`ibm_enterprise.py`) and the LE / intrinsic call-signature catalogue
(`le_signatures.py`). This file also documents the EXEC SQL statement model
the parser builds (`models/sql_statements.py`), since that is where most
dialect-specific behaviour lives. Start with
[IBMEnterpriseCobol](#ibmenterprisecobol) for lookups, or
[EXEC SQL model](#exec-sql-model-modelssql_statementspy) for host variables
and tables.

## IBMEnterpriseCobol

Two modules:

* `ibm_enterprise.py` -- `IBMEnterpriseCobol`: class-level word tables
  (`IBM_RESERVED_WORDS`, `IBM_INTRINSIC_FUNCTIONS`, `CICS_COMMANDS`,
  `IMS_COMMANDS`, `IBM_LE_CALLABLE_SERVICES`, `IBM_LE_SERVICE_CATEGORIES`,
  `IBM_LE_SERVICE_INFO`) plus lookups and light validation.
  `IBM_LE_CALLABLE_SERVICES` is the key set of `IBM_LE_SERVICE_CATEGORIES`,
  rebuilt from the LE Programming Reference in #529 (see
  [analysis/sql-cics-ims.md](analysis/sql-cics-ims.md)). The analyzers read
  the tables directly (`analysis/xref.py`, `analysis/language_env_analyzer.py`).
  `cobolparser.dialects` exports only `IBMEnterpriseCobol` (also re-exported
  from `cobolparser`).
* `le_signatures.py` -- per-operand call signatures for LE callable services
  and intrinsic functions (backs `le-info`; see
  [LE / intrinsic signature catalogue](#le--intrinsic-signature-catalogue-dialectsle_signaturespy)).

```python
from cobolparser.dialects.ibm_enterprise import IBMEnterpriseCobol

dialect = IBMEnterpriseCobol()
dialect.is_reserved_word(word)                    # bool, case-insensitive
dialect.is_intrinsic_function(name)                # bool
dialect.is_cics_command(name) / is_ims_command(name)
dialect.is_le_callable_service(name)
dialect.get_le_service_info(name) -> dict | None
dialect.get_intrinsic_function_signature(name) -> dict[str, Any] | None
dialect.validate_data_item(item) -> list[str]      # warnings
dialect.validate_program_structure(program) -> list[str]
dialect.create_comp3_data_item(name, picture, location) -> IBMDataItem
dialect.parse_exec_sql / parse_exec_cics / parse_exec_ims(text, location)
dialect.get_dialect_info() -> dict[str, Any]       # name/version/features + table sizes
```

`get_le_service_info` covers fewer names than `is_le_callable_service`
accepts: `IBM_LE_SERVICE_INFO` is the signature catalogue's services plus a
small hand-written `_UNCATALOGUED_LE_SERVICE_INFO` (37 of the 62 services),
so it returns `None` for a recognised service with neither.

**The `Exec*Statement` classes here are not what the parser builds.**
`ibm_enterprise.py` defines its own `ExecSQLStatement`, `ExecCICSStatement`,
`ExecIMSStatement` (node types `EXEC-SQL`/`EXEC-CICS`/`EXEC-IMS`),
`IBMDataItem` and `IBMDataType`, returned only by the dialect's own
`parse_exec_*` / `create_comp3_data_item` helpers. The parser produces
`models/sql_statements.py`'s `ExecSQLStatement` (and its subclasses) and
`parsers/statements/ibm_exec_statements.py`'s `ExecCicsStatement` /
`ExecImsStatement` (node types `EXEC_CICS` / `EXEC_IMS`). The
[EXEC SQL model](#exec-sql-model-modelssql_statementspy) section describes
the parser's SQL model.

## Command sets and COMP-3 validation

* `validate_data_item` accepts any plain numeric PICTURE for COMP-3 --
  optional leading `S`, then `9` / `P` / one `V` with repeat counts
  (`_is_numeric_picture`). A `pattern.startswith("9")` test is wrong: it
  rejects every signed (`S9(7)V99`) or fraction-only (`V99`) item.
* `CICS_COMMANDS` also holds READQ/WRITEQ/DELETEQ, SYNCPOINT, ENQ/DEQ,
  WAIT/POST/SIGNAL, ASSIGN/INQUIRE/ADDRESS/DUMP/QUERY, WEB, INVOKE,
  SPOOLOPEN; `NOHANDLE` is an option, not a command, and is not in it.
* `IMS_COMMANDS` is DL/I call codes only, including the hold forms
  GHU/GHN/GHNP, SYNC/ROLB/ROLL/ROLS/SETS/SETU, CHNG/CMD/GCMD, INQY/LOG/STAT;
  ENQUEUE/DEQUEUE/XDLT/XRPL (not DL/I calls) are not in it. `ROLLB` is kept
  for compatibility. The dialect's own `ExecIMSStatement.ims_call_type`
  reads this set. The parser's `ExecImsStatement` does **not**: it classifies
  against `ibm_exec_statements._IMS_CALL_TYPES` (GU/GN/GNP/ISRT/REPL/DLET/
  CHKP/ROLLB/TERM/XRST/XDLT), so e.g. `GHU` parses as `UNKNOWN` there.

Pinned by `tests/unit/test_issue_341_dialect_crud.py` (see #341).

## EXEC SQL text: literals and `--` comments (`parsers/statements/_utils.py`)

`collect_exec_sql_text(stream, sql=True)` (EXEC SQL, procedure and data
division) re-delimits every string literal the lexer handed over unquoted
(`'...'`, embedded `'` doubled; a typed literal such as `X'C1'` keeps its
`raw_value`; one the source wrote with `"` -- `Token.quote` -- is
re-delimited with `"`, since under APOSTSQL that is a DB2 *delimited
identifier*, a table/schema/column name, #597) and drops a `--` comment -- two MINUS tokens in adjacent columns
-- up to its NEWLINE (never past END-EXEC). Both must reach the SQL model's
scrubber, or `WHERE B = 'X:FAKE'` reports host variable `FAKE`, `'FROM T9'`
reports table `T9`, and a comment's `:WS-C` is a host variable. EXEC CICS /
DLI text is collected unquoted (option values are read bare by the codebase
graph and signature extractor). Pinned by
`tests/unit/test_exec_sql_literals_comments.py`.

## EXEC SQL model (`models/sql_statements.py`)

### Delimited identifiers

`_strip_sql_literals_and_comments` blanks `'...'` strings but keeps a
`"..."` delimited identifier, unquoted and verbatim (doubled `""`
unescaped), when its text is identifier-shaped
(`_SQL_DELIMITED_IDENT_RE`), so `FROM "PROD"."CUST"` reads as
`FROM PROD.CUST` in both table passes and `tables == ["PROD.CUST"]`. One
that is not (`"MY TABLE"`) is still blanked: no scan downstream can carry it
as one name. QUOTESQL (where `"` delimits strings) is not modelled. Pinned by
`regression/test_sql_delimited_identifiers_issue_597.py`.

### Null indicators

`ExecSQLStatement.null_indicators` gets both indicator forms: `:X:IND` and
`:X INDICATOR :IND`. The EXEC SQL parser rebuilds `sql_text` without a blank
before a colon (`INDICATOR:IND`), so `_SQL_INDICATOR_KW_RE` takes `\s*`, not
`\s+` -- with `\s+` the keyword form is recognised only in hand-written test
strings, never in parsed source. Indicators also appear in `host_variables`
(the plain `:name` scan). Pinned by
`test_sql_statements.py::TestHostVariables::test_null_indicator_keyword_as_parsed_from_source`.

### Structure-qualified host variables

`:DCLEMP.EMPNO` is EMPNO OF DCLEMP. `host_variables`, `null_indicators`,
`into_variables` and `using_variables` carry the **last component**
(`EMPNO`) -- what a DATA DIVISION or DCLGEN lookup needs; the qualifier is
dropped (`_SQL_HV_QUALIFIERS`). The indicator of `:DCLEMP.SAL:IND` is seen as
one. `dclgen_check._INDICATOR_RE` reads the same form. Pinned by
`test_exec_sql_host_variable_lists.py` and `test_dclgen_check.py`.

### `into_variables` / `using_variables`

Every host variable of the `INTO` (SELECT / FETCH) or `USING` (PREPARE /
EXECUTE) list, in order, **indicators included** (they are written by the
INTO too). The list regexes (`_SQL_HV_LIST`) take `\s*` after the keyword
-- the collector writes `INTO:WS-A`, so `INTO\s+:` never matches parsed
source -- and an item may carry an indicator (`:A:IND`, `:A INDICATOR :IND`)
or a qualifier (`:REC.FLD`); an indicator does not end the list. `io_logger`
and `sql_cics_lint` still carry text-regex fallbacks for these lists.
Pinned by `tests/unit/test_exec_sql_host_variable_lists.py`.

### `FetchStatement` cursor / orientation

`_parse_fetch_clause()` reads `FETCH [SENSITIVE|INSENSITIVE] [WITH CONTINUE]
[orientation] [FROM] cursor [FOR n ROWS]` positionally: `cursor_name` is the
first word none of those may be, `fetch_direction` the orientation word
(NEXT default; PRIOR/FIRST/LAST/CURRENT/BEFORE/AFTER/ABSOLUTE/RELATIVE, the
ROWSET forms included) and `fetch_count` the `FOR n ROWS` size. Reading it
any other way breaks real shapes: `FETCH NEXT ROWSET FROM C1` must not name
cursor `ROWSET`, `FETCH PRIOR FROM C1` must name `C1` (or the CRUD matrix
loses the cursor's read), and a substring test for the direction makes
`INTO :WS-LAST-NAME` a FETCH LAST. Pinned by
`tests/unit/test_exec_sql_fetch_orientation.py`.

### `cursor_name` on positioned UPDATE/DELETE

`UPDATE ... WHERE CURRENT OF C1` / `DELETE FROM T WHERE CURRENT OF C1` set
`cursor_name` to the cursor (`_SQL_CURRENT_OF_RE`); a searched UPDATE/DELETE
leaves it `None`. `tables[0]` is the target table, so `io_logger`'s `target`
is the table. Pinned by
`test_sql_statements.py::TestCursorOperations::test_positioned_update_delete_names_the_cursor`.

### `tables`

Source order, with the statement's **target first** for INSERT / UPDATE /
DELETE / MERGE (`io_logger` and the CRUD matrix rely on `tables[0]`); the
rest are tables a subquery, `INSERT ... SELECT` or `MERGE ... USING` reads
(INSERT/UPDATE subquery tables included). A FROM that
separates function arguments -- `EXTRACT(YEAR FROM D)`, `TRIM(... FROM C)`,
`SUBSTRING(N FROM 1)` -- is blanked first (`_blank_function_argument_froms`:
a FROM directly inside a parenthesised group not opening with SELECT/WITH),
so the column after it is not reported as a table.

`TRUNCATE [TABLE] t ...` has `sql_type == "TRUNCATE"`
(`SQLStatementType.TRUNCATE`, see #341) and `tables == [t]`.

## LE / intrinsic signature catalogue (`dialects/le_signatures.py`)

```python
from cobolparser.dialects.le_signatures import (
    le_service_signature, intrinsic_signature, services_without_signature,
    catalog_to_dict, LE_SERVICE_SIGNATURES, INTRINSIC_FUNCTION_SIGNATURES,
)
sig = le_service_signature("CEEDAYS")   # LEServiceSignature | None
sig.parameters                          # tuple[LEParameter, ...]: direction, data_type (LEDataType), optional, repeats
sig.required_parameters; sig.call_example()
intrinsic_signature("NUMVAL-C")         # IntrinsicSignature | None (.returns, .arguments, .required_arguments)
services_without_signature()            # [{"name", "category"}] -- known LE services not catalogued
catalog_to_dict()                       # whole catalogue, CATALOG_VERSION = 1
```

Coverage: 33 of the dialect's 62 LE services have a
signature (the other 29 are reported by `services_without_signature()`,
never hidden); all 81 intrinsic functions do (pinned by a test). Full
API notes: [analysis.md](analysis.md) ("Call signatures").

### `get_intrinsic_function_signature`

Backed by the complete catalogue in `dialects/le_signatures.py` (the one
`le-info` reads — see [analysis.md](analysis.md)'s "Call signatures"
subsection for the full `le_service_signature`/`intrinsic_signature` API),
so every function `is_intrinsic_function` accepts has a signature here. The
returned dict carries the catalogue's own keys (`returns`, `arguments`,
`call_example`, ...) plus historical `return_type`/`parameters`/
`description` keys derived from the catalogue's `returns`/`arguments`/
`summary` — **not** from a second, hand-written table: a second table drifts
and overrides the catalogue whether or not it is more correct (e.g.
`LENGTH`'s argument category is `["any"]`, not `["string"]`). Only
`CURRENT-DATE`'s fixed return length — a fact the catalogue has no structured
field for at all — is added on top, via the much narrower
`_INTRINSIC_EXTRA_FIELDS`.

## See also

* [ast-models.md](ast-models.md) — `models/sql_statements.py` node fields, `PictureClause` P-scaling
* [analysis.md](analysis.md) — "Call signatures", `MoveTypeChecker` P-scaling, CRUD matrix, `dclgen-check`
* [parser.md](parser.md) — EXEC SQL / CICS / IMS statement parsers
* [history](history/dialects.md) — archived dated notes (pre-fix behaviour of the SQL model and tables)
