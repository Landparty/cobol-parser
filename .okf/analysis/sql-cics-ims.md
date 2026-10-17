---
type: Module
title: SQL, CICS, IMS and LE Analyzers
description: Analyzers for the non-COBOL surfaces of a mainframe program -- HostVariableResolver, DclgenChecker, SqlCicsAnalyzer (sql_cics_lint.py), IMSSegmentAnalyzer, LanguageEnvironmentAnalyzer, and the LE service / intrinsic call-signature catalogue in dialects/le_signatures.py.
tags: [analysis, sql, dclgen, host-variables, cics, ims, dli, language-environment, le-signatures, intrinsic-functions]
timestamp: 2026-10-15T00:00:00Z
---

# SQL, CICS, IMS and LE Analyzers

Checks on the parts of a program the COBOL compiler does not see: embedded DB2
SQL (host-variable resolution, DCLGEN type agreement, unchecked SQLCODE,
dynamic-SQL injection), CICS commands (missing RESP handling), IMS DL/I calls
(segment names) and IBM Language Environment services and intrinsic functions
(usage plus exact call signatures). Entry points: `HostVariableResolver().resolve(ast)`,
`DclgenChecker().check(ast)`, `SqlCicsAnalyzer().analyze(ast)`,
`IMSSegmentAnalyzer().analyze(ast)`, `LanguageEnvironmentAnalyzer().analyze(ast)`,
and `le_service_signature()` / `intrinsic_signature()`. The EXEC node models
themselves are in [../dialects.md](../dialects.md).

## Contents

* [HostVariableResolver](#hostvariableresolver)
* [DclgenChecker](#dclgenchecker)
* [SqlCicsAnalyzer](#sqlcicsanalyzer)
* [IMSSegmentAnalyzer](#imssegmentanalyzer)
* [LanguageEnvironmentAnalyzer](#languageenvironmentanalyzer)
* [See also](#see-also)

## HostVariableResolver

```python
from cobolparser.analysis import HostVariableResolver
report: HostVarResolutionReport = HostVariableResolver().resolve(ast)   # .resolve(), not .analyze()
# report.resolved / .unresolved / .declare_tables / .column_name_collisions
# then .get_symbol_table() / .get_column_index() on the resolver
```

Resolves SQL host variables (`:var-name`) in EXEC SQL blocks against WORKING-STORAGE
definitions.

**Name matching is verbatim.** `_column_index` keys DCLGEN columns by their
own upper-cased name, so `CUST_ID` and the host variable `CUST-ID` DCLGEN
generates for it do *not* pair up here. `DclgenChecker` (below) does that
normalization itself rather than changing this resolver's semantics under its
other consumers.

A DCLGEN member's `DECLARE TABLE` in WORKING-STORAGE carries a qualified
`SCHEMA.TABLE` name, which `DeclareTableStatement` extracts, so both this
resolver and `DclgenChecker` see it.

## DclgenChecker

```python
from cobolparser.analysis import DclgenChecker
report: DclgenReport = DclgenChecker().check(ast)   # note: .check(), not .analyze()
# report.violations: list[DclgenViolation]  (kind/severity/host_variable/column/table/
#                                            message/expected_picture/expected_usage/
#                                            actual_picture/actual_usage/location)
# report.checked / .unchecked / .tables / .ambiguous_columns
# report.has_violations (property) / .worst_severity() / .to_dict()
```

Cross-checks every `:host-var` against the DCLGEN `DECLARE TABLE` column of
its name. Backs `cobol-parser dclgen-check` and the `dclgen-check` lint rule.

**Why it is nearly free:** both halves are already parsed.
`HostVariableResolver` pairs a host variable with its DATA DIVISION item;
`DeclareTableStatement.columns` carries the DB2 side with
`db2_type_to_cobol_pic()` / `db2_type_to_cobol_usage()` already applied. The
checker resolves nothing itself — it only says whether a pair agrees — so a
fix to the type mapping fixes the check too.

**The name normalization is load-bearing.** DB2 columns are underscored
(`CUST_ID`); the host variables DCLGEN generates are hyphenated (`CUST-ID`),
because `_` is not a COBOL data-name character. `_normalize()` (`_` -> `-`,
upper-cased) is applied to both sides via `_column_index()`. Without it the
checker reports that no column matches *any* host variable — i.e. it checks
nothing while looking like it had. That was the first bug found in
development, and `test_an_underscored_column_is_matched_to_its_hyphenated_host_variable`
pins it.

**Null indicators are not host variables here.** An indicator (`:X:IND`, `:X
INDICATOR :IND`) is picked up by the `:name` scan like any host variable but
binds to no column; names in any statement's `null_indicators` are dropped
from the checked set (unless a column of that name exists) rather than each
being reported as `unchecked`.

| kind | severity | what it costs at runtime |
|------|----------|--------------------------|
| `category` | error | CHAR column into a numeric item (or the reverse); the binding does not mean what it says |
| `scale` | error | `DECIMAL(9,2)` into `PIC S9(7)V9` — the cents are silently rounded away on every fetch, and no status code says so |
| `precision` | error | too few integer digits; SQLCODE -304, but only once a row actually exceeds it |
| `length` | error / info | `CHAR(30)` into `PIC X(20)` truncates every fetch (error); the reverse only wastes space (info) |
| `usage` | warning | DISPLAY where DCLGEN generates COMP-3; DB2 converts every row rather than moving it (IBM synonyms are folded first: `BINARY`/`COMP-4`/`COMP-5` all count as `COMP`, since on z/OS `COMP-5` is the same big-endian storage and is IBM's recommended integer host variable -- #259) |
| `sign` | warning | unsigned host variable; a negative value arrives as its absolute value |
| `null-indicator` | warning | nullable column with no indicator variable on an **output** host variable (an `INTO` list of SELECT/FETCH/VALUES/EXECUTE, the target of `SET :hv =`); SQLCODE -305 the first time the column is actually null. An input (INSERT VALUES, UPDATE SET, WHERE, OPEN USING) needs none -- it just cannot write NULL (#530). A variable of unknown direction (a stored-procedure `CALL` argument, an unmodelled statement type) gets an `unchecked` entry for this one check instead (`_host_variable_directions`); it stays in `checked` for the others |

Pinned by `tests/regression/test_dclgen_null_indicator_direction_issue_530.py`.

**A `category` finding stands alone.** Every later check would be comparing
digits against characters, so `_compare` returns immediately after one rather
than dragging four confusing restatements along with it.

**Indicator pairing is program-wide, and read off the statement text.**
`ExecSQLStatement` keeps the indicator *names* but not which variable each
belongs to, so `_INDICATOR_RE` re-scans `sql_text` for both forms
(`:VAR:IND` and `:VAR INDICATOR :IND`). The whitespace between name and
separator is matched **once, before the alternation** — putting it inside the
`INDICATOR` branch leaves that branch with no space left to match, which is
exactly the bug the first draft had. Program-wide rather than per-statement:
a variable given an indicator on its FETCH and not on its SELECT INTO is a
different (and much rarer) bug than never having one, and flagging the second
statement would bury the finding that matters.
A structure-qualified variable (`:DCLCUST.CUST-VAL:IND`) pairs by its last
component, like the SQL model's host-variable list (otherwise the structure
name would be the "host variable" and nothing would be checked).

**What it declines to check, and says so.** `report.unchecked` is
`name: reason` for every host variable that could not be compared — no
DECLARE TABLE names a column of that name, the program has no DECLARE TABLE
at all, `VARCHAR`/`CLOB` (which bind to a *group* item: a length halfword
plus the text, so one elementary PICTURE is the wrong thing to compare), or
a type with no COBOL PICTURE (`BLOB`, `XML`, ...). A clean report is never
mistaken for a checked one. `ambiguous_columns` names a column two tables
both declare; the first declaration wins the comparison, matching
`HostVariableResolver`'s own rule, and the collision is stated rather than
assumed away.

The lint rule folds `unchecked` and `ambiguous_columns` into
`LintReport.caveats` (one line with a count, not one finding per variable)
rather than emitting findings for them.

## SqlCicsAnalyzer

A COBOL program that talks to DB2 and CICS carries two failure surfaces the
COBOL compiler says nothing about, because neither `EXEC SQL` nor `EXEC CICS`
is COBOL: the precompiler rewrites the block and moves on. Whether the program
then looked at what came back is nobody's job to check. This module makes it
somebody's job.

```python
from cobolparser.analysis.sql_cics_lint import SqlCicsAnalyzer

report = SqlCicsAnalyzer().analyze(ast)      # SqlCicsReport
report.violations                 # source-ordered SqlCicsViolation list
report.worst_severity()           # "error" | "warning" | "info" | None
report.violations_of_kind(KIND_NO_SQLCODE_CHECK)   # KIND_* constants hold the kind strings below
report.has_violations
report.unchecked                  # what this run could not check, and why
report.sql_statements / report.cics_statements
```

| Kind | Why it is a defect, not a style note |
|------|--------------------------------------|
| `SQL_NO_SQLCODE_CHECK` | An executable `EXEC SQL` whose outcome is never looked at: no `SQLCODE`/`SQLSTATE`/`SQLCA` mention in the statements that follow, no `WHENEVER SQLERROR` in effect. DB2 does not raise — it sets a number and returns, and the program commits whatever it was going to commit. The most common real defect in DB2 COBOL and the cheapest to find. |
| `SQL_DYNAMIC_CONCATENATION` | A host variable handed to `PREPARE` / `EXECUTE IMMEDIATE` whose content was assembled by `STRING` or moved in from another item — SQL injection with a mainframe accent. Parameter markers (`EXECUTE ... USING :HV`) are the fix and are never flagged. Writers are counted program-wide, except that a `MOVE` written directly in the PREPARE's paragraph, before it, that overwrites the whole item (no reference modification, not `CORRESPONDING`) cuts off everything before it: then only that MOVE, the writers between it and the PREPARE (conditional ones and those in PERFORMed paragraphs included) and, inside an inline `PERFORM` loop, the loop's later writers count (#395). A `STRING` never cuts the trace — it leaves bytes past what it transfers as they were. |
| `SQL_HARDCODED_CREDENTIALS` | A literal user id or password in `EXEC SQL CONNECT`. It is in the source, the listing, the load library, and every copy anyone took of any of them. |
| `SQL_SELECT_WITHOUT_INTO` | A singleton `SELECT` with no `INTO` and no cursor. The precompiler accepts it; the row goes nowhere. (`into_variables` is populated from parsed source; the `INTO\s*:` text check stays as a backstop.) |
| `CICS_NO_RESP_HANDLING` | An `EXEC CICS` command with no `RESP`/`RESP2`, no `NOHANDLE`, no `HANDLE CONDITION` in effect. The default action for most CICS conditions is to abend the task, so the failure mode is a dropped transaction mid-update, not a wrong answer. `IGNORE CONDITION` ("take no action": nothing abends, execution continues) counts as handling, the same as a `HANDLE CONDITION` label; only `ERROR` covers every condition, a narrower set goes to `unchecked`. A bare `HANDLE CONDITION X` restores the abend (#396). |
| `CICS_ABEND_WITHOUT_HANDLER` | `EXEC CICS ABEND` with no `HANDLE ABEND`. **Info** — frequently deliberate, worth seeing rather than worth fixing. |

`SqlCicsViolation` carries `kind`, `severity` (always `SEVERITY_BY_KIND[kind]`),
`message`, `location`, `symbol` (the SQL statement type, the CICS command verb,
or for a dynamic-SQL finding the untrusted host variable) and a machine-readable
`detail` dict — the traced assignment, the option keyword, the active handler.

**It does not guess.** Three things in the parsed form of an EXEC block are
lossy, and each is answered with an entry in `unchecked` rather than a finding
-- e.g. a CONNECT operand with neither colon nor quotes that matches a
declared DATA DIVISION item. EXEC SQL text keeps a literal's quotes, so `USING
'S3CRET'` is always a literal and `USING 'WS-KEY'` is never mistaken for the
data item WS-KEY. A quiet report with a populated `unchecked` is not a clean
program, it is an unexamined one.

The search for a status check after an `EXEC SQL` stops at the next
executable `EXEC SQL` written directly in a paragraph (also inside a
PERFORMed one): it resets the SQLCA, so `DELETE` / `COMMIT` / `IF SQLCODE`
reports the DELETE (one check is never credited to both). SQL inside an
IF/EVALUATE body may not run and does not end the search; neither does a
declaration or `WHENEVER`.

`DECLARE GLOBAL TEMPORARY TABLE` is executable and is graded;
DECLARE CURSOR / TABLE / STATEMENT / VARIABLE are not
(`_NON_EXECUTABLE_SQL_TYPES`). A `DECLARE TABLE` or `INCLUDE` in the DATA
DIVISION is not counted in `sql_statements`.

The lint rule id is `sql-cics-check` — the subcommand's own name, per the lint
convention. Tests: `tests/unit/analysis/test_sql_cics_lint.py`.

**Known gaps**: a VARCHAR host structure
written through its subordinate `49` item is not traced to `PREPARE ... FROM
:hv`; SQLCODE checked in a `PERFORM UNTIL` guard, or in the calling paragraph
rather than after the statement, is not seen.

## IMSSegmentAnalyzer

```python
from cobolparser.analysis import IMSSegmentAnalyzer
calls: list[IMSDLICall] = IMSSegmentAnalyzer().analyze(ast)
# IMSDLICall: location/interface/function_code/function_code_var/pcb_name/
#             io_area_name/ssa_names/segment_names, .primary_segment (property)
# also .get_all_segment_names(calls), .get_entry_points(ast) -> list[IMSEntryPoint]
```

Analyses IMS DL/I calls -- `CALL 'CBLTDLI'/'AIBTDLI'/'CEETDLI'` and `EXEC
DLI` (GU/GN/GNP/ISRT/DLET/REPL, ...) -- resolving each call's SSAs to segment
names.

**Function code.** A function-code variable resolves to every value its VALUE
clause and MOVEs give it, joined by the "/" convention (`CHNG/GU/ROLB`); only
values that cannot be a function code -- blank, or a figurative such as
`VALUE SPACES` -- are dropped. An unquoted literal is recognised against
`IBMEnterpriseCobol.IMS_COMMANDS`, the one DL/I call-code list. Keeping only
candidates in a (then incomplete) local list reported `GU` at every call of a
variable also set to `CHNG` / `ROLB` (#595). The candidates are the union over
the whole program, not per call site.

**Optional parmcount.** `CALL 'CBLTDLI' USING parmcount, function, pcb, ...`
(also AIBTDLI; CEETDLI takes none): a first operand that is a numeric literal
or a data item with a purely numeric PICTURE (function codes are always `PIC
X(4)`) is skipped, so it is never read as the function code. Pinned by
`TestParmcountOperand` in `tests/unit/test_ims_segment_analyzer.py`.

**Segment name = first 8 *bytes* of the SSA.** `_group_segment_candidates`
walks a group SSA's leaves in storage order (`_ssa_leaves`: REDEFINES skipped,
a sub-group with its own VALUE/MOVE taken whole), each leaf contributing VALUE
∪ MOVEs padded/cut to its width (`calculate_size()`), until 8 bytes are known,
so a name split across leaves (`05 A PIC X(4) VALUE 'CUST'. 05 B PIC X(4)
VALUE 'OMER'.`) reads `CUSTOMER`. Candidates combine (capped at 16, joined by
the "/" convention), and a leaf with unknown content before byte 8 leaves the
name `None` rather than truncated. Only values from an actual MOVE are merged
in (a separate `_moved_values` dict, not `_variable_values`): VALUE clauses are
keyed by *bare* name, and two SSAs whose child fields share a name would
otherwise cross-contaminate (the shape `test_multiple_ssas_path_call` pins).
Qualified MOVEs match against the SSA *and* every intermediate group name. An
elementary SSA with a VALUE also merges MOVEs into it. Pinned by
`tests/unit/analysis/test_ims_ssa_segment_resolution.py` and
`tests/regression/test_audit_2026_08_16_analyzers.py::TestA4IMSMovedSegmentName`.

**EXEC DLI.** `_build_exec_dli_calls` produces one `IMSDLICall` per
`ExecImsStatement` (interface `"EXEC DLI"`, `function_code` = command word,
`pcb_name` `"PCB(n)"`, `io_area_name` from `INTO`/`FROM`, `segment_names` from
every `SEGMENT(...)`), merged with the `CBLTDLI` calls in source order. `EXEC
DLI ... SEGMENT((area))` (doubled parens = a data area) resolves through
`_resolve_ssa_segment(area)`; `None` when unknown.

**`primary_segment` is the target segment** (see #398). In DL/I the **last**
SSA (or `SEGMENT(...)` option of `EXEC DLI`) names the segment retrieved /
inserted / replaced; the earlier ones only qualify the path. The property
returns `segment_names[-1]`, and `None` when that last one is unresolved -- a
resolved parent is never reported in the target's place.
`TestPrimarySegmentIsTarget` in `tests/unit/test_ims_segment_analyzer.py`.

## LanguageEnvironmentAnalyzer

```python
result: LEAnalysisResult = LanguageEnvironmentAnalyzer().analyze(ast)
# result.intrinsic_usages: list[LEFunctionUsage] — every FUNCTION <name> intrinsic reference
# result.le_service_calls: list[LEServiceCall]   — CALL "CEExxxx" to IBM LE callable services
#                                                 (static, or dynamic via possible_values)
# properties: uses_intrinsic_functions / uses_language_environment /
#             unique_functions / unique_services / service_categories
```

Detects COBOL intrinsic function references (`FUNCTION LENGTH`,
`FUNCTION UPPER-CASE`, ...) and calls to IBM LE callable services
(`CEEGTST`, `CEEDAYS`, `CEEHDLR`, ...). `to_dict()` uses the same two keys.

**Intrinsic references are words in code, not text.** `_collect_text_fields`'s
`_add` skips operands that are quoted literals (`DISPLAY 'FUNCTION KEYS ARE
DISABLED'` names no function `KEYS`). `FUNCTION` must be its own word (no name
character before it, so `WS-FUNCTIONAL` / `DLI-FUNCTIONS` are data names), and
the no-blank form (`FUNCTIONLENGTH`) is accepted only for a known intrinsic.
IF / PERFORM UNTIL conditions (their operands live on the condition tree) and
STRING's split `"FUNCTION"`, `"UPPER-CASE ( X )"` operands are scanned too.
Pinned by
`tests/regression/test_audit_2026_08_16_analyzers.py::TestA3FunctionInsideLiteralIsProse`
and `TestIntrinsicReferenceBoundaries` in
`tests/unit/test_language_env_analyzer.py`.

### Call signatures (`dialects/le_signatures.py`)

The analyzer answers "is this an LE service?"; `le_signatures.py` answers the
next question — **what does the CALL need?**

```python
from cobolparser.dialects.le_signatures import (
    le_service_signature, intrinsic_signature,
    LE_SERVICE_SIGNATURES, INTRINSIC_FUNCTION_SIGNATURES,
    services_without_signature, catalog_to_dict,
)

sig = le_service_signature("CEEDAYS")     # case-insensitive; None when unknown
sig.parameters                            # tuple[LEParameter]: name, direction
                                          # ("input"/"output"/"input/output" --
                                          # constants IN/OUT/INOUT), type_id,
                                          # description, optional, repeats
sig.required_parameters                   # the ones that may not be omitted
sig.call_example()                        # 'CALL "CEEDAYS" USING ...'
p.data_type                               # LEDataType: declaration, byte_length,
                                          # snippet (VSTRING / feedback code)
intrinsic_signature("NUMVAL-C").returns   # "numeric"
catalog_to_dict()                         # the le-info JSON; CATALOG_VERSION "1"
```

Also public: `LEServiceSignature`, `IntrinsicSignature`, `IntrinsicArgument`,
and `LE_DATA_TYPES` (type id -> `LEDataType`). As of 2026-10-15 the catalogue
holds 33 service signatures (`services_without_signature()` lists 29 more
recognised services) and 81 intrinsic signatures.

**Coverage is partial and says so.** `services_without_signature()` lists the
LE services `IBM_LE_CALLABLE_SERVICES` recognises but this module cannot
describe exactly — so a consumer can say "known service, signature not
catalogued" rather than guess a parameter list or show nothing. The intrinsic
half *is* complete, pinned by
`tests/unit/test_le_signatures.py::TestIntrinsicSignatures::test_every_ibm_intrinsic_has_a_signature`.

**The intrinsic set is Enterprise COBOL 6.4's, not COBOL-85's.**
`IBM_INTRINSIC_FUNCTIONS` and the catalogue cover the 1989 amendment's 42
functions plus the 37 later ones (3.x/4.x Unicode, 6.1 date-time / TEST-* / E
/ PI / TRIM, 6.3 BIT-/HEX-, 6.4 UUID4), each with IBM's arity (optional
trailing operands marked). Pinned by
`test_le_signatures.py::TestEnterpriseSixIntrinsicSignatures` and
`test_language_env_analyzer.py::TestEnterpriseSixIntrinsics`.

**Service operand lists are checked against SA38-0683**, operand by operand;
`TestServiceOperandsMatchIbm` pins the ones that have been wrong. Points that
are easy to get wrong: `CEE3ABD`'s second operand (`clean-up`) is 0 for the
abend *without* clean-up and 1 after normal enclave termination; `CEEISEC`
has 9 operands including `input_milliseconds`; `CEEGMT` / `CEEUTC` are
`(output_GMT_Lilian, output_GMT_seconds, fc)` -- the third `output_Gregorian`
CHAR17 operand belongs to `CEELOCT` only; `CEEFMDA` / `CEEFMDT` / `CEEFMTM`
take a leading `country_code` (CHAR2, input; blanks or `OMITTED` for the
current setting -- positional, so it is *not* `optional`, which in this
catalogue means "may be dropped from the end of the USING list");
`CEE3DMP`'s `options` is a fixed `PIC X(255)` (`char255` type), not a
halfword-prefixed `vstring`. Adding a type id does not change
`CATALOG_VERSION` (same dict shape). A CALL copied from `le-info` (and the
COBOL Analyzer extension's hover, which reads it) is only as right as these
lists.

`IBMEnterpriseCobol.IBM_LE_SERVICE_INFO` is **derived** from this catalogue
(merged over `_UNCATALOGUED_LE_SERVICE_INFO`, the leftovers), so the dialect's
one-line metadata and the signatures cannot drift. Categories are cross-checked
against `IBM_LE_SERVICE_CATEGORIES` per service by the same test module.

Exposed to non-Python consumers as `cobol-parser le-info` (see `.okf/cli.md`),
which is what the VS Code extension's LE hover reads.

## See also

* [../analysis.md](../analysis.md) -- routing page, calling conventions, module map
* [../dialects.md](../dialects.md) -- `ExecSQLStatement` / `ExecCicsStatement` /
  `ExecImsStatement`, `DeclareTableStatement`, the DB2 → COBOL type mapping
* [lint.md](lint.md) -- `dclgen-check` and `sql-cics-check` as lint rules
* [flow.md](flow.md) -- CICS terminators and SQL WHENEVER handlers in the CFG
* [data-use.md](data-use.md) -- `MoveTypeChecker`'s use of intrinsic signatures
* [../cli.md](../cli.md) -- `dclgen-check`, `sql-cics-check`, `ims-dli`,
  `language-env`, `le-info`
* [history](../history/analysis.md) -- dated fix write-ups behind these rules
