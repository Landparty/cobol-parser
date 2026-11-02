---
type: Module
title: Definitions (CSD, BMS, DDL, DBD, PSB)
description: cobolparser.definitions -- parsers for the members that sit beside COBOL programs and give them meaning - CICS CSD (DFHCSDUP, DFHPCT/PPT/FCT), BMS maps, DB2 DDL, IMS DBDGEN and PSBGEN - with detect_definition_kind for content-based routing.
tags: [definitions, cics, csd, bms, db2, ddl, ims, dbd, psb, transactions, screens, tables, segments]
timestamp: 2026-11-01T00:00:00Z
---

# Definitions (CSD, BMS, DDL, DBD, PSB)

`cobolparser/definitions/` reads the non-COBOL members an application needs to
be understood: which **transaction** starts which program and which **dataset**
a CICS file is (CSD), what the **screens** look like (BMS), what a **table**
holds (DDL), and what an **IMS database** and a program's view of it are (DBD,
PSB). None of this is in the COBOL source. Pure Python, no dependencies, used
by the LegacyLens backend's definition adapter.

```python
from cobolparser.definitions import detect_definition_kind, parse_definitions

kind = detect_definition_kind(text)      # "BMS" | "PSB" | "DBD" | "CSD" | "DDL" | None
report = parse_definitions(text, kind)   # BmsDefinitions | PsbDefinitions | ... | None
report.to_dict()                         # every dict has "kind" and "warnings"
```

Or call one parser directly: `parse_csd`, `parse_bms`, `parse_ddl`, `parse_dbd`,
`parse_psb`.

## Contents

- [Modules](#modules)
- [Detection](#detection)
- [Assembler statements (BMS, DBD, PSB, CICS tables)](#assembler-statements-bms-dbd-psb-cics-tables)
- [CSD](#csd)
- [BMS](#bms)
- [DDL](#ddl)
- [DBD and PSB](#dbd-and-psb)
- [See also](#see-also)

## Modules

| Module | Public names |
|---|---|
| `definitions/__init__.py` | `detect_definition_kind`, `parse_definitions`, `DEFINITION_KINDS`, `DefinitionKind`, `Definitions` |
| `definitions/_asm.py` | `read_statements`, `AsmStatement`, `parse_operands`, `parse_value` (private helper module) |
| `definitions/csd.py` | `parse_csd`, `CsdDefinitions`, `CsdResource` |
| `definitions/bms.py` | `parse_bms`, `BmsDefinitions`, `BmsMapset`, `BmsMap`, `BmsField` |
| `definitions/ddl.py` | `parse_ddl`, `DdlDefinitions`, `DdlTable`, `DdlColumn`, `SYSTEM_DEFAULT` |
| `definitions/ims.py` | `parse_dbd`, `parse_psb`, `DbdDefinitions`, `PsbDefinitions`, `ImsDatabase`, `ImsSegment` |

## Detection

`detect_definition_kind(source)` looks at content only (the first 200 KB), in
the order of `DEFINITION_KINDS`: a `DFHMSD` macro is BMS; `PSBGEN` is a PSB; a
`DBD NAME=` with a `SEGM` is a DBD; an upper-case `DEFINE <type>(` whose
`<type>` is a CSD resource type (or its DFHCSDUP abbreviation), or a
`DFHPCT/DFHPPT/DFHFCT TYPE=` macro, is a CSD; a `CREATE TABLE|INDEX|VIEW|ALIAS|
SYNONYM|TABLESPACE` is DDL **unless** the source is COBOL (an `IDENTIFICATION
DIVISION` or `EXEC SQL`), so a program that embeds DDL stays a program.
A JCL job (a `//name JOB|EXEC|DD|PROC` record) is None whatever its in-stream
data holds, so an IDCAMS `DEFINE GDG(`, DFHCSDUP or DSNTEP2 `CREATE TABLE` job
stays JCL (#800); IDCAMS `DEFINE CLUSTER(` and Python `def f(` are not CSD.
Plain assembler (no such macro) is None.

## Assembler statements (BMS, DBD, PSB, CICS tables)

`_asm.read_statements` returns one `AsmStatement(line, name, operation,
operand_text, keywords, positional)` per macro call. Name field = column 1,
operands end at the first blank outside quotes (the rest is remarks), `*` /
`.*` in column 1 is a comment. Operand values: `KEY=A` -> `"A"`,
`KEY=(A,(B,C))` -> `["A", ["B", "C"]]`, quoted strings lose their quotes with
`''` -> `'` and `&&` -> `&`.

Continuation rules (each one exists because a sample broke without it):

- A non-blank column 72 continues the statement **only when the next record
  has columns 1-15 blank**; the next record's text starts at column 16. Inside
  a quoted string the record is taken up to column 71 exactly, so a long
  `INITIAL='...'` keeps its blanks.
- A record that runs past column 71 without a real continuation and without a
  numeric sequence field keeps its whole text: hand-written members do this,
  and cutting at 71 read the last character (a closing quote) as a
  continuation mark and swallowed the next statement.
- Members cut down to their text (no column-72 marks): an operand field ending
  in a comma continues on the next record when that record is only operands
  (its first word has `=`, or starts with `(` or a quote).

## CSD

`parse_csd(source) -> CsdDefinitions(resources, lists, warnings)`.

- **DFHCSDUP decks** (and EXTRACT output): free-form commands; a word with no
  value that is a DFHCSDUP verb starts a new command. `DEFINE` / `ALTER`
  (and `DEF` / `ALT`) take the first keyword with a value that is a resource
  type as the resource; `GROUP(...)` is the group; every other keyword is an
  attribute (upper-cased, blanks removed, except `DESCRIPTION`). Resource
  types and attributes accept DFHCSDUP abbreviations (`TRANS(...)`,
  `PROG(...)`). A value split over records is joined; a sequence field in
  columns 73-80 is dropped. `ALTER` updates the earlier definition of the same
  type and name (and group, when given) or warns. `ADD GROUP(g) LIST(l)` fills
  `lists`.
- **Table-based regions**: when the source holds `DFHPCT` / `DFHPPT` /
  `DFHFCT` macros, their `TYPE=ENTRY` (FCT: `TYPE=FILE|DATASET`) entries
  become `TRANSACTION`, `PROGRAM` (or `MAPSET` for `DFHPPT MAPSET=`) and `FILE`
  resources with `source` = the macro. An FCT file has no DSNAME (the region's
  JCL holds it).

`to_dict()` adds the views a consumer needs: `transactions` (transid, program,
group, description, profile, remote_system, status, and `db2_entry` /
`db2_plan` from a `DB2ENTRY TRANSID(...)` or a `DB2TRAN ENTRY(...)
TRANSID(...)`), `programs`, `mapsets`, `files` (with `dsname`) and
`resource_counts`.

## BMS

`parse_bms(source) -> BmsDefinitions(mapsets, warnings)`. `DFHMSD` opens a
mapset (its label is the name; `TYPE=FINAL` closes it), `DFHMDI` a map
(`SIZE=(rows,cols)`, else the mapset's `SIZE`, else 24 x 80), `DFHMDF` a field.
A field's `POS=(row,col)` is 1-based; `POS=n` is an offset from 0 and is turned
into row/column with the map width. `XINIT=` hex is decoded as cp037 when there
is no `INITIAL=`. `kind` is `input` (ATTRB has UNPROT), `output` (named,
protected) or `constant`. A map's `title` is its top-left non-blank constant.
Statements out of place (a DFHMDF before any DFHMDI, ...) are warnings.

## DDL

`parse_ddl(source) -> DdlDefinitions(tables, views, aliases, indexes,
other_objects, ignored_statements, warnings)`.

Statements end at `;` outside quotes (`--#SET TERMINATOR x` changes it);
`--` and `/* */` comments and a numeric sequence field are dropped. Modelled:
`CREATE [GLOBAL TEMPORARY|AUXILIARY] TABLE` (columns with type text, NOT NULL,
DEFAULT -- `WITH DEFAULT` with no value is `SYSTEM_DEFAULT`, `DEFAULT NULL` is
`NULL`, a signed constant is `-1` --, inline PRIMARY KEY / UNIQUE / REFERENCES
... ON DELETE, table constraints PRIMARY KEY / UNIQUE / FOREIGN KEY ... ON
DELETE, `IN db.ts`, `LIKE t`), `CREATE [UNIQUE] INDEX ... ON t (cols)
[CLUSTER]` (also attached to the table when it is in the member), `CREATE
VIEW` (columns and the base tables named after FROM / JOIN, subqueries
included; the view's own `WITH` common table expressions, a `FROM` inside a
function call such as `EXTRACT(YEAR FROM D)` and a `TABLE(...)` table function
are left out), `CREATE ALIAS|SYNONYM ... FOR`, `CREATE TABLESPACE|DATABASE|
STOGROUP|SEQUENCE|PROCEDURE` (name only), `ALTER TABLE t ADD [COLUMN] ... |
ADD constraint`, `COMMENT ON` / `LABEL ON` a table, a column, or `t (col IS
'...', ...)`. Anything else is counted in `ignored_statements` by its first
word(s) (`GRANT`, `DROP TABLE`, `CREATE TRIGGER`, ...). Names are upper-cased
unless double-quoted.

## DBD and PSB

`parse_dbd(source) -> DbdDefinitions(databases, warnings)`: `DBD NAME=,
ACCESS=` starts a database; `DATASET` / `AREA` DD names; `SEGM NAME=, PARENT=`
(0 -> root; `((SEG,SNGL))` -> SEG), `BYTES=` (max of `(max,min)`), `POINTER`,
`SOURCE`; `FIELD NAME=(name,SEQ,U|M)` (the `SEQ` field is the segment `key`;
`M` = non-unique); `LCHILD` and `XDFLD` on the current segment.

`parse_psb(source) -> PsbDefinitions(psbs, warnings)`: `PCB TYPE=TP|DB|GSAM`
(the DBD name from `DBDNAME=`, else `NAME=` as older PSBs write it, else
positional -- a DB/GSAM PCB with none is a warning; `PROCSEQ=` is kept as
`procseq`; name from `PCBNAME=` or the label), `SENSEG NAME=,
PARENT=, PROCOPT=` (inherits the PCB's PROCOPT), and `PSBGEN PSBNAME=, LANG=`
closes a PSB. PCBs left without a PSBGEN become an unnamed PSB with a warning.

## See also

* [dialects.md](dialects.md) -- EXEC SQL / CICS / DLI inside COBOL, which these
  definitions complete · [jcl.md](jcl.md) -- the other non-COBOL input
* [tests.md](tests.md) -- `tests/unit/definitions/`, samples in
  `tests/samples/definitions/`
