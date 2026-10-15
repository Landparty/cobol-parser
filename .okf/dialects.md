---
type: Module
title: Dialects
description: IBMEnterpriseCobol dialect tables and lookups (reserved words, intrinsic functions, CICS/IMS command sets, LE callable services, COMP-3 validation), the le_signatures call-signature catalogue, and notes on the EXEC SQL statement model the parser builds.
tags: [dialects, ibm-enterprise, exec-sql, exec-cics, exec-ims, intrinsic-functions, le-services]
timestamp: 2026-10-15T00:00:00Z
---

# Dialects (`cobolparser/dialects/`)

Two modules:

* `ibm_enterprise.py` -- `IBMEnterpriseCobol`: class-level word tables
  (`IBM_RESERVED_WORDS`, `IBM_INTRINSIC_FUNCTIONS`, `CICS_COMMANDS`,
  `IMS_COMMANDS`, `IBM_LE_CALLABLE_SERVICES`, `IBM_LE_SERVICE_CATEGORIES`,
  `IBM_LE_SERVICE_INFO`) plus lookups and light validation. The analyzers read
  the tables directly (`analysis/xref.py`, `analysis/language_env_analyzer.py`).
  `cobolparser.dialects` exports only `IBMEnterpriseCobol` (also re-exported
  from `cobolparser`).
* `le_signatures.py` -- per-operand call signatures for LE callable services
  and intrinsic functions (backs `le-info`; see "LE / intrinsic signature
  catalogue" below).

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
small hand-written `_UNCATALOGUED_LE_SERVICE_INFO` (37 of the 62 services as
of 2026-10-15), so it returns `None` for a recognised service with neither.

**The `Exec*Statement` classes here are not what the parser builds.**
`ibm_enterprise.py` defines its own `ExecSQLStatement`, `ExecCICSStatement`,
`ExecIMSStatement` (node types `EXEC-SQL`/`EXEC-CICS`/`EXEC-IMS`),
`IBMDataItem` and `IBMDataType`, returned only by the dialect's own
`parse_exec_*` / `create_comp3_data_item` helpers. The parser produces
`models/sql_statements.py`'s `ExecSQLStatement` (and its subclasses) and
`parsers/statements/ibm_exec_statements.py`'s `ExecCicsStatement` /
`ExecImsStatement` (node types `EXEC_CICS` / `EXEC_IMS`). The sections from
"`ExecSQLStatement.null_indicators`" on describe the parser's SQL model.

## Command sets and COMP-3 validation (issue #341, 2026-10-15)

* `validate_data_item` accepts any plain numeric PICTURE for COMP-3 --
  optional leading `S`, then `9` / `P` / one `V` with repeat counts
  (`_is_numeric_picture`). It used to test `pattern.startswith("9")`, so
  every signed (`S9(7)V99`) or fraction-only (`V99`) item got a false
  "COMP-3 items should have numeric PICTURE".
* `CICS_COMMANDS` also holds READQ/WRITEQ/DELETEQ, SYNCPOINT, ENQ/DEQ,
  WAIT/POST/SIGNAL, ASSIGN/INQUIRE/ADDRESS/DUMP/QUERY, WEB, INVOKE,
  SPOOLOPEN; `NOHANDLE` (an option, not a command) is gone.
* `IMS_COMMANDS` is DL/I call codes only: the hold forms GHU/GHN/GHNP,
  SYNC/ROLB/ROLL/ROLS/SETS/SETU, CHNG/CMD/GCMD, INQY/LOG/STAT were added;
  ENQUEUE/DEQUEUE/XDLT/XRPL (not DL/I calls) were removed. `ROLLB` is kept
  for compatibility. The dialect's own `ExecIMSStatement.ims_call_type`
  reads this set, so those commands classify there instead of staying
  `UNKNOWN`. The parser's `ExecImsStatement` does **not**: it classifies
  against `ibm_exec_statements._IMS_CALL_TYPES` (GU/GN/GNP/ISRT/REPL/DLET/
  CHKP/ROLLB/TERM/XRST/XDLT), so e.g. `GHU` still parses as `UNKNOWN` there.

Pinned by `tests/unit/test_issue_341_dialect_crud.py`.

## `ExecSQLStatement.null_indicators` (`models/sql_statements.py`)

Both indicator forms land here: `:X:IND` and `:X INDICATOR :IND`. The EXEC
SQL parser rebuilds `sql_text` without a blank before a colon
(`INDICATOR:IND`), so `_SQL_INDICATOR_KW_RE` takes `\s*`, not `\s+` --
before 2026-09-28 the keyword form was only recognized in hand-written test
strings, never in parsed source. Indicators also appear in `host_variables`
(the plain `:name` scan). Pinned by
`test_sql_statements.py::TestHostVariables::test_null_indicator_keyword_as_parsed_from_source`.

## EXEC SQL text: literals and `--` comments (`parsers/statements/_utils.py`)

`collect_exec_sql_text(stream, sql=True)` (EXEC SQL, procedure and data
division) re-delimits every string literal the lexer handed over unquoted
(`'...'`, embedded `'` doubled; a typed literal such as `X'C1'` keeps its
`raw_value`) and drops a `--` comment -- two MINUS tokens in adjacent columns
-- up to its NEWLINE (never past END-EXEC). Before 2026-09-28 neither reached
the SQL model's scrubber, so `WHERE B = 'X:FAKE'` reported host variable
`FAKE`, `'FROM T9'` reported table `T9`, and a comment's `:WS-C` was a host
variable. EXEC CICS / DLI text is still collected unquoted (option values are
read bare by the codebase graph and signature extractor). Pinned by
`tests/unit/test_exec_sql_literals_comments.py`.

## Structure-qualified host variables (`models/sql_statements.py`)

`:DCLEMP.EMPNO` is EMPNO OF DCLEMP. `host_variables`, `null_indicators`,
`into_variables` and `using_variables` carry the **last component**
(`EMPNO`) -- what a DATA DIVISION or DCLGEN lookup needs; the qualifier is
dropped (`_SQL_HV_QUALIFIERS`). `dclgen_check._INDICATOR_RE` reads the same
form. Before 2026-09-28 the structure (`DCLEMP`) was reported instead, the
indicator of `:DCLEMP.SAL:IND` was not seen as one, and `dclgen-check` filed
both as unchecked while checking nothing. Pinned by
`test_exec_sql_host_variable_lists.py` and `test_dclgen_check.py`.

## `into_variables` / `using_variables` (`models/sql_statements.py`)

Every host variable of the `INTO` (SELECT / FETCH) or `USING` (PREPARE /
EXECUTE) list, in order, **indicators included** (they are written by the
INTO too). The list regexes (`_SQL_HV_LIST`) take `\s*` after the keyword
-- the collector writes `INTO:WS-A` -- and an item may carry an indicator
(`:A:IND`, `:A INDICATOR :IND`) or a qualifier (`:REC.FLD`). Before
2026-09-28 both lists were empty for every statement parsed from source
(`INTO\s+:` never matched) and an indicator ended the list; `io_logger` and
`sql_cics_lint` had grown text-regex fallbacks for it, still in place.
Pinned by `tests/unit/test_exec_sql_host_variable_lists.py`.

## `FetchStatement` cursor / orientation (`models/sql_statements.py`)

`_parse_fetch_clause()` reads `FETCH [SENSITIVE|INSENSITIVE] [WITH CONTINUE]
[orientation] [FROM] cursor [FOR n ROWS]` positionally: `cursor_name` is the
first word none of those may be, `fetch_direction` the orientation word
(NEXT default; PRIOR/FIRST/LAST/CURRENT/BEFORE/AFTER/ABSOLUTE/RELATIVE, the
ROWSET forms included) and `fetch_count` the `FOR n ROWS` size. Before
2026-09-28 `FETCH NEXT ROWSET FROM C1` named cursor `ROWSET` (likewise
`ABSOLUTE`, `SENSITIVE`), `FETCH PRIOR FROM C1` named none -- so the CRUD
matrix lost the cursor's read -- and the direction was a substring test
(`INTO :WS-LAST-NAME` made a FETCH LAST). Pinned by
`tests/unit/test_exec_sql_fetch_orientation.py`.

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

`TRUNCATE [TABLE] t ...` has `sql_type == "TRUNCATE"`
(`SQLStatementType.TRUNCATE`, issue #341) and `tables == [t]`; it was
`UNKNOWN` with no tables before.

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

Coverage on 2026-10-15: 33 of the dialect's 62 LE services have a
signature (the other 29 are reported by `services_without_signature()`,
never hidden); all 81 intrinsic functions do (pinned by a test). Full
API notes: [analysis.md](analysis.md) ("Call signatures").

## `get_intrinsic_function_signature`

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
