---
type: Module
title: Business Rule Extraction
description: BusinessRuleExtractor (analysis/business_rules.py) -- every IF/EVALUATE/SEARCH as a decision table, promoted to validation on reject paths, paragraph-level arithmetic as calculations; technical-rule detection, guards, reached_via, inputs/outputs via xref roles, level-88 glossary and data lineage.
tags: [analysis, business-rules, decision-table, validation, calculation]
timestamp: 2026-10-15T00:00:00Z
---

# Business Rule Extraction

Answers "what are the rules in this program?" -- the question a
modernization or documentation engagement asks first -- as a catalogue of
`BusinessRule`s (decisions, validations, calculations), each with its
conditions, actions, enclosing guards and the arms elsewhere that reach it.
Entry point: `BusinessRuleExtractor(include_technical=False).analyze(ast)`;
backs `cobol-parser business-rules` ([../cli.md](../cli.md)). Feature idea #21
in `docs/feature-ideas.md`. Start with [API](#api) and [Rule
kinds](#rule-kinds).

## API

```python
from cobolparser import BusinessRuleExtractor

report = BusinessRuleExtractor().analyze(ast)      # BusinessRuleExtractor(include_technical=False)
report.rules                 # list[BusinessRule], BR-001.. in source order
report.rules[0].branches     # list[RuleBranch]: label, condition, actions
report.condition_names       # level-88 glossary: POL-AUTO -> POL-TYPE = 'A'
report.data_lineage          # {item: {"read_by": [...], "written_by": [...]}}
report.technical_rules_excluded
report.caveats               # always holds the "kinds are heuristic" caveat
report.rule("BR-003") / report.rules_of_kind("validation")
print(report.to_text())      # IF/THEN/ELSE-shaped catalogue
```

## Rule kinds

**Rule kinds.** Every IF / EVALUATE / SEARCH is a `decision`, shaped as a
decision table: one `RuleBranch` per arm (THEN, ELSE, each WHEN, WHEN OTHER,
SEARCH AT END) with the condition selecting that arm and its actions. It is
promoted to `validation` when an arm signals rejection (moves or DISPLAYs an
error-like literal, writes/SETs an item whose name has an ERR / ERROR /
INVALID / REJECT / ABEND word, PERFORMs or GOes TO such a procedure, CALLs
CEE3ABD / ILBOABN0) or the condition is a class test. COMPUTE / ADD /
SUBTRACT / MULTIPLY / DIVIDE at paragraph level (not inside an arm) is a
`calculation` with `formula` normalized to `target = expression` (`DIVIDE A
INTO B GIVING C` -> `C = B / A`; each receiver keeps its own `ROUNDED [MODE IS
m]`, `ADD A TO B ROUNDED C` -> `B ROUNDED = B + A; C = C + A`, #517; a GIVING
target that is also an operand keeps both, `MULTIPLY A BY B GIVING B` -> `B =
A * B`, read from `source_operands`, #495); inside an arm it is an action of that
decision only, never counted twice. Counters (`ADD 1 TO X`, `COMPUTE X = X +
1`) are not rules at all.

**Stacked WHENs (#314).** `WHEN 'A' WHEN 'B' stmt` is one arm whose
condition is `WS-T = 'A' OR WS-T = 'B'` (via `EvaluateStatement.when_groups()`);
the same grouping numbers program-flow `BranchArm`s (one `WHEN_n` arm, label
`WHEN A / WHEN B`) and constraint arms, where each phrase of a stack is an
OR-split disjunct of that arm (`WHEN_1#1`, `WHEN_1#2`) and later arms /
WHEN OTHER negate every phrase.

## Technical vs business

**Technical vs business.** A decision whose *own* condition reads only
technical items, or a calculation that writes only technical items, is
`technical` and excluded by default (counted in `technical_rules_excluded`;
`include_technical=True` keeps it). Technical items are found from the
program, not only from names: every SELECT `FILE STATUS` item; everything a
READ / RETURN `AT END` clause writes (the EOF flag, whatever it is called);
the level-88s of those items and the items of those 88s; the xref special
registers (SQLCODE, SQLSTATE, EIB*, RETURN-CODE, ...); plus a narrow name
pattern (`EOF`, `EOJ`, `FS`, `END-OF-FILE`, `FILE-STAT`, `EIB*`, `DFH*`). A
SEARCH is never technical (it is a table lookup). CICS `RESP` fields compared
to `DFHRESP(...)` are deliberately *not* technical: "NOTFND -> CUSTOMER NOT
FOUND" is a business rule. The same holds for the other DL/I and MQ status
fields: an IMS PCB status code (`PCB-STATUS = 'GE'`), the EXEC DLI `DIBSTAT`
(and the other `DIB*` fields), and an MQ completion / reason code compared to
`MQCC-*` / `MQRC-*`. `DIB*` are special registers to xref (never undefined),
but `_collect_technical_items` unions the special registers *minus*
`_DLI_INTERFACE_BLOCK` into the technical set (#311): EXEC DLI has no
`RESP()`, so `DIBSTAT` is the only way such a program tests a not-found, and
the same rule must not vanish just because it uses EXEC DLI rather than
`CALL 'CBLTDLI'`. `EIB*`, `SQLCODE` and the other special registers stay
technical.

## Context, inputs and outputs

**Context on every rule.** `guards` are the conditions of the arms the rule
is nested in, within its paragraph (ELSE contributes `NOT (cond)`, WHEN
OTHER the conjunction of the negated WHENs, an exception clause `AT END
(READ ...)` / `ON SIZE ERROR (COMPUTE ...)`). `reached_via` links across
paragraphs: every arm elsewhere that PERFORMs or GOes TO the rule's paragraph
or section, as `"BR-001 ELSE"` / `"BR-004 WHEN POL-TYPE = 'A'"`. A
`PERFORM A THRU C` reaches every procedure from A through C in source order
(`_thru_range`, on bare names over `ProcedureIndex`; a section header crossed
on the way to a paragraph inside it is left out), and `GO TO A B DEPENDING
ON N` reaches every target (#354). A nested
decision is its own rule; the parent arm lists it as an action whose
`rule_id` points at it (dropped to `None` if the nested rule was excluded as
technical, never left dangling). `in_dead_code` comes from
`DeadCodeAnalyzer`.

**Inputs / outputs** reuse `XrefAnalyzer`'s per-statement role mapping
(`_role_assignments` / `_names_for` / `_residual_names`), filtered to
declared names (+ INDEXED BY names, + data-bearing special registers; not
`DFHRESP` / `LENGTH` / `ADDRESS`). A decision's are its condition plus its
*direct* actions (a nested rule's reads/writes are its own). Testing or
SETting a condition name also counts its item.

## Rendering

**Rendering notes.** Conditions come from `program_flow/condition_text.py`
then `_tidy()` (`T-K ( IX )` -> `T-K(IX)`, `NOT =` reads `<>`). EVALUATE
selector literals arrive **unquoted** from the parser, so a non-identifier,
non-numeric, non-figurative selector is re-quoted -- except the space-joined
call shape `DFHRESP ( NORMAL )`, which is an expression, a typed literal
(`X'00'`, `"typed": True`), already in source spelling (#331), and a
selector marked `"expression"` (`WHEN WS-N + 1`, #333), rendered unquoted.
A signed number is numeric even with a space after its sign
(`_SPLIT_SIGN_RE`; the parser already folds it, #747), so `WHEN +100`
reads `SQLCODE = +100`, never the string `'+ 100'`.
A negated range
selector (`WHEN NOT 0 THRU 17`, a `Condition` dict with `negated` plus
`start`/`end`) reads `NOT (AGE >= 0 AND AGE <= 17)` from those bounds, not
from its raw `THRU` text; only a single negated value reads `AGE <> 6`
(#260). Level-88 values are
also stored unquoted with `THRU` as `"THROUGH:end"`; `_condition_values`
quotes them unless the item's PICTURE / USAGE is numeric. STRING sources
arrive quoted (#330), so they are rendered as is. Actions are
rendered in full here rather than via `program_flow/statement_text.py`
(flowchart summaries, truncated to 48 chars).

## Design choices and limits

**Why not `constraints.py`** (as idea #21 proposed): `ConstraintExtractor`
only models conditions on fields that trace to a mocked boundary (it takes a
`ProgramLayoutIndex` and a `BoundaryReport`), so a rule on a computed
WORKING-STORAGE field -- most rating/pricing logic -- would be missing.

**Known limits** (the always-present caveat says the kinds are heuristic;
`classification` on each rule names the signal that decided it):
single-program scope (like `xref`, contained programs are not walked --
`--program` picks one); an arithmetic statement inside an
inline PERFORM *within an arm* is neither a rule nor an action of that arm.

Tests: `tests/unit/analysis/test_business_rules.py`,
`tests/unit/cli/test_business_rules_cli.py`.

## See also

* [../analysis.md](../analysis.md) -- routing page, calling conventions, module map
* [data-use.md](data-use.md) -- `XrefAnalyzer` roles, which give each rule's
  inputs and outputs
* [flow.md](flow.md) -- `DeadCodeAnalyzer` (`in_dead_code`),
  `program_flow/condition_text.py` (condition rendering)
* [fixtures-support.md](fixtures-support.md) -- `ConstraintExtractor`, the
  boundary-scoped sibling
* [../cli.md](../cli.md) -- `business-rules` flags
* [history](../history/analysis.md) -- archived dated notes
