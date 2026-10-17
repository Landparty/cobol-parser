---
type: Module
title: Fixture-Generation Analyses
description: The analyses behind gen-fixtures -- BoundaryInventoryAnalyzer (boundary_inventory.py, every mockable touchpoint and its CALL argument directions), ConstraintExtractor + domains.solve (constraints.py / domains.py, branch conditions on boundary data and witness values), ConstantFolder (const_fold.py, field_equals expectations) and count_invocations (invocation_counts.py, call_count expectations).
tags: [analysis, fixtures, gen-fixtures, boundary-inventory, constraints, domains, const-fold, invocation-counts]
timestamp: 2026-10-15T00:00:00Z
---

# Fixture-Generation Analyses

The program analyses that `ProgramFixtureGenerator` (see
[../generators.md](../generators.md)) combines into a `gen-fixtures` bundle:
Phase 2 inventories every mockable boundary
(`BoundaryInventoryAnalyzer().analyze(ast, index)`), Phase 4 turns branch
conditions on boundary-fed fields into solvable constraints
(`ConstraintExtractor().extract(ast, index, report)` + `domains.solve()`), and
Phase 7 derives exact expectations (`ConstantFolder().fold(...)` for
`field_equals`, `count_invocations(...)` for `call_count`). All of them take a
Phase 1 `ProgramLayoutIndex`. Design:
`docs/plans/2026-08-02-program-data-generation-design.md`; output shape:
`docs/fixture-bundle-schema.md`. The rule throughout is "exact by
construction, or absent": an analysis that cannot be sure reports nothing (or
an `unsupported` / `unresolved` note), never a guess.

## Contents

* [BoundaryInventoryAnalyzer](#boundaryinventoryanalyzer)
* [ConstraintExtractor and domains.solve](#constraintextractor-and-domainssolve)
* [ConstantFolder](#constantfolder)
* [Invocation counts](#invocation-counts)
* [Literal values](#literal-values)
* [See also](#see-also)

## BoundaryInventoryAnalyzer

Phase 2 of program-scoped test-data generation (the `gen-fixtures` initiative
-- see `docs/plans/2026-08-02-program-data-generation-design.md` and
`.okf/generators.md`'s `ProgramLayoutIndex` section, Phase 1). Walks the
PROCEDURE DIVISION and emits one `Boundary` per mockable statement, using the
same `(category, key)` convention mockymock's own `mock_surface` module uses
-- two independent walks over the same AST that must agree on keys (the
dependency direction is mockymock -> cobol-parser, never the reverse; the
unique-prefix key algorithm and the non-interactive-ACCEPT-sources list are
re-derived independently against that module's source, not imported).

```python
from cobolparser.analysis.boundary_inventory import BoundaryInventoryAnalyzer
from cobolparser.generators import ProgramLayoutIndex

index = ProgramLayoutIndex.build(ast)
report = BoundaryInventoryAnalyzer().analyze(
    ast, index,
    callee_indexes={"CALCULATOR": callee_index},   # optional, Phase 2b rung 2
    callee_asts={"CALCULATOR": callee_ast},
)
report.boundaries          # list[Boundary]: ref (category/key/paragraph/line),
                           # direction, record_names, status_field, handlers,
                           # call_args, unresolved
report.unresolved          # program-level gaps (never silently dropped)
```

**Categories**: `CALL`/`DYNCALL` (per-argument direction, see below),
`OPEN`/`CLOSE`/`READ`/`WRITE`/`REWRITE`/`DELETE`/`START`/`UNLOCK` (the eight
file-op verbs), `SQL`, `CICS`, `DLI`, `ACCEPT` (console only --
non-interactive sources filtered, matched on the source's first word so
`FROM DATE YYYYMMDD` / `FROM DAY YYYYDDD` count as `DATE` / `DAY`).
`DISPLAY` is never a boundary (assert-only, out of scope for this phase,
matching mockymock's own `mock_surface`).

**File ops.** WRITE/REWRITE key on the *record* name (COBOL syntax names the
record, not the FD) and READ's `INTO` target also names a whole record --
both resolved via `ProgramLayoutIndex.record_named()`, not `.resolve()`
(`.resolve()` only ever finds elementary fields; a WRITE/REWRITE/READ-INTO
target is a group item, which `flatten_record` never emits a `FieldSpec`
for -- this gap is exactly why `record_named()` exists; found via direct
reproduction against `tests/samples/file_operations.cbl`, not theorized).
OPEN/CLOSE emit one `Boundary` per file named (COBOL allows `OPEN INPUT A
OUTPUT B` in one statement) and carry `status_field` resolved via
`index.file_facts(...)` the same way READ/DELETE/START/UNLOCK do (without it,
`ScenarioPlanner`'s "OPEN -> FILE STATUS 35" error family can never fire).
DELETE/START/UNLOCK are
`STATUS_ONLY` (no data payload); READ is `IN`; WRITE/REWRITE are `OUT`.

**CALL/DYNCALL argument-direction ladder (Phase 2b)**, first rung wins,
`CallArg.provenance` records which:

1. `passing_mode` in `CONTENT`/`VALUE` -> **OUT**, always (language rule --
   the callee cannot write back through either mode).
2. Callee source available (`callee_indexes`/`callee_asts`, keyed by
   uppercased called-program name): does the callee write to its Nth
   LINKAGE 01 *at all* -> **IN**; read-only -> **OUT**. "Writes" is checked
   generically via `.targets` (shared verbatim by `MoveStatement`,
   `ArithmeticStatement` -- ADD/SUBTRACT/MULTIPLY/DIVIDE --, `ComputeStatement`,
   `InitializeStatement`, `SetStatement`) plus `.givings` (arithmetic GIVING)
   and `.into_target`/`.into_targets` (READ INTO, STRING/UNSTRING) -- **not**
   just `MoveStatement`, which would miss a `COMPUTE LK-RESULT = ...`
   subprogram entirely (found via `tests/samples/subprogram_demo.cbl`'s
   CALCULATOR, which computes its result exactly that way; a MOVE-only
   check silently mis-classified it as OUT).
   "Nth" is the Nth name of the callee's `PROCEDURE DIVISION USING`
   (RETURNING excluded), not the Nth LINKAGE 01 in declaration order --
   those differ whenever LINKAGE is declared in another order or holds
   those differ whenever LINKAGE is declared in another order or holds
   `SET ADDRESS OF` items. Declaration order is only the fallback for a
   callee with
   no USING.
3. Caller-side dataflow in the enclosing paragraph's own statement list
   (source order): last write before the CALL with no read after -> **OUT**;
   first read after with no write before -> **IN**; both -> **BIDIRECTIONAL**.
   A write to a *parent group* counts as touching a child field (and vice
   versa), checked via `FieldSpec.path` prefix comparison through the index,
   not bare string equality. "Read" for a write-shaped statement (rung 2's
   list above) comes from a per-type read list (`_write_shaped_read_names`,
   issue #268) and is checked *before* that statement's writes: MOVE's
   `.source`; ADD/SUBTRACT/MULTIPLY/DIVIDE's operands minus the GIVING and
   REMAINDER receivers (without GIVING the TO/FROM/BY/INTO target is read
   *and* written; with GIVING it is read only and is not a
   write target either); every name in a COMPUTE expression; STRING's
   sending operands, delimiters and POINTER; UNSTRING's source, delimiters,
   POINTER and TALLYING; SET's value (plus the target for UP/DOWN BY);
   INITIALIZE's REPLACING BY values. POINTER/TALLYING/COUNT IN/DELIMITER IN
   are write targets too. A write-shaped type with no read list whose
   `.operands` names the arg outside its write targets degrades the arg to
   **BIDIRECTIONAL** `assumed-bidirectional`, never OUT. The generic
   `.operands` fallback is reserved for statement types with no write-shape
   at all (DISPLAY, IF conditions, ...) since a write-shaped statement's own
   `.operands` also contains its target, which would otherwise misread a
   write as a read of the same name.
4. Otherwise **BIDIRECTIONAL**, `provenance="assumed-bidirectional"`.

**Rung 3's "read" also covers a branching statement's own condition**
(`_condition_read_names`): an `IfStatement`'s condition tree, a
`PerformStatement UNTIL`'s guard, and an `EvaluateStatement`'s subjects and
WHEN selectors don't reach the statement's generic `.operands` bag (an
`IfStatement`'s is empty), so without it a CALL argument whose only later use
is `IF WS-RC = 'Y'` would look unread and misclassify as OUT.
`_condition_field_names` recurses into a
`ConditionalExpression`/`ArithmeticExpression` operand that is itself an
expression (`A + B = C`) and into a `FunctionCall`'s arguments
(`FUNCTION UPPER-CASE(WS-X)`), and walks an `EVALUATE` subject that arrives as
a `CobolExpression` rather than a plain string -- the parser only produces
string subjects today, so that guards the documented type contract
(`EvaluateStatement.subjects: list[str | CobolExpression]`) against a future
parser change.

`RETURNING`/`GIVING` parameters are always `IN` (`provenance=
"giving-parameter"`) -- the callee produces them by definition.

**SQL.** `into_variables` is unreliable in practice: an inline `SELECT ...
INTO :a FROM t WHERE x = :b` places *both* `:a` and `:b` in `host_variables`,
never populating `into_variables` at all (verified empirically against
`tests/samples/ibm_extensions.cbl` and `database_interface.cbl` -- the parent
plan's Phase 2 table assumed `into_variables` cleanly separated IN from OUT
variables; it does not). `host_variables` is therefore the only layout
source used, for every SQL shape; direction comes from `sql_type`
(`SELECT`/`FETCH` -> IN, `INSERT`/`UPDATE`/`DELETE` -> OUT, else
`STATUS_ONLY`), independent of which variables are attached.
`status_field="SQLCODE"` always. The parser strips a structure qualifier
off `host_variables` (`:REC-A.AMT` arrives as `AMT`), so `_classify_sql`
re-reads the qualifiers from the scrubbed `sql_text` with
`host_var_resolver._QUALIFIED_HOST_VAR_RE` (the same way
`HostVariableResolver` does) and resolves the dotted `REC-A.AMT` form; an
`AMT` declared under two structures would otherwise land in `unresolved`
(issue #366).

**CICS/DLI** have no fixed INTO/FROM-shaped attributes to key layout
resolution off -- `ExecCicsStatement.options` is a generic option-keyword ->
argument-text dict, and `ExecImsStatement.arguments` is a positional list
with no fixed role per position. Best-effort in v1: every option
value/argument is tried against the layout index (via the same
`resolve()`-then-`record_named()` fallback used elsewhere), direction
defaults to `BIDIRECTIONAL`, and an unresolved entry on the `Boundary` itself
(not the report-level list) notes the limitation rather than claiming
precision this phase does not have.

**ACCEPT.** Non-interactive sources (`DATE`, `DAY`, `DAY-OF-WEEK`, `TIME`,
`COMMAND-LINE`, `ENVIRONMENT`, `ENVIRONMENT-VALUE`, `ARGUMENT-NUMBER`,
`ARGUMENT-VALUE`) are not boundaries at all -- resolved without touching
stdin, mirroring mockymock's own `_NON_INTERACTIVE_ACCEPT_SOURCES`.
`ACCEPT OMITTED` (waits for console input but stores nothing -- a real COBOL
idiom, not a gap) is still recorded as a boundary but with no fields to
resolve and no unresolved note.

**Key convention.** Static CALL keys keep the literal's original case (a
COBOL program name is written case-sensitively); dynamic CALL/SQL/CICS/DLI
keys are uppercased/normalized. SQL/CICS/DLI keys are the shortest
word-prefix of the normalized command text no other same-category site in
the program shares (`_unique_prefix`, re-derived from mockymock's
`generator._unique_prefix`), falling back to the full text on a genuine tie.
The other texts are whitespace-collapsed before the comparison: the prefix is
joined from split words, while the raw `sql_text`/`cics_text`/`ims_text` keep
their line breaks, so two multi-line sites agreeing up to a line break
(CICSONLN's two `SEND MAP`s, differing only in `ERASE`/`DATAONLY`) would
otherwise get the same truncated key. **Keys are assigned in two passes:**
`analyze()` first collects every SQL/CICS/DLI site's FULL normalized text per
category (`_collect_exec_texts`), and each site's prefix is checked against
all OTHER same-category sites' full texts (`_other_texts`). Comparing against
previously *assigned* (already-shortened) keys makes keys walk-order-dependent
and lets the first site keep a key that is a prefix of a later sibling's text;
`SELECT A FROM T` / `SELECT B FROM T` get `SELECT A` / `SELECT B` in either
source order. Pinned by
`tests/regression/test_audit_2026_08_12_analysis.py::TestB2ExecKeysAreOrderIndependentPrefixes`.

**Nested-body walk**: the same discipline `IOLogger` and mockymock's
`mock_surface` both converged on independently -- a fixed set of
`getattr()`-checked attributes (`then_statements`, `else_statements`,
`inline_statements`, the IO/CALL clause bodies, including `on_size_error`,
`not_on_size_error`, `not_on_overflow` and `not_at_eop_clause`) plus two
special cases: `EvaluateStatement.when_clauses`/`.default_when` are
`WhenClause` *nodes* with a `.statements` attribute, while
`SearchStatement.when_clauses` is a **list of dicts** with a `"statements"`
key -- a different shape, and a documented trap (mixing the two loop
variables up trips mypy immediately). This module's and `constraints.py`'s
`_NESTED_STATEMENT_ATTRS` must list every clause-body attribute
`program_flow/scanner.py` and `const_fold.py` walk; a missing one (a `CALL
'ERRLOG'` nested in an arithmetic `ON SIZE ERROR`) produces no boundary at
all. Pinned by
`tests/regression/test_audit_2026_08_12_analysis.py::TestA5SizeErrorBodiesAreWalked`.

## ConstraintExtractor and domains.solve

Phase 4 of program-scoped test-data generation (the `gen-fixtures` initiative
-- see `docs/plans/2026-08-02-program-data-generation-design.md`). Walks
IF/EVALUATE/SEARCH conditions and PERFORM UNTIL loop guards and, for every
operand that resolves (via Phase 1's `ProgramLayoutIndex`) to a field a
boundary actually feeds (per Phase 2's `BoundaryReport`), emits a
`FieldConstraint`; the domain-propagation solver in `domains.py` (same PR)
turns a field's constraints into a concrete witness value.

```python
from cobolparser.analysis.constraints import ConstraintExtractor
from cobolparser.analysis.domains import solve

report = ConstraintExtractor().extract(ast, index, boundary_report)
report.branches              # list[BranchConstraints]: one per IF/EVALUATE/
                              # SEARCH decision point
report.sequence_constraints  # list[SequenceConstraint]: the READ/AT-END/
                              # PERFORM-UNTIL EOF-loop idiom
report.unsupported           # program-level gaps (never silently dropped)

branch = report.branches[0]
branch.arms                  # dict[str, list[FieldConstraint]]: arm_id ->
                              # conjuncts, e.g. {"THEN": [...], "ELSE": [...]}
branch.enclosing             # tuple[(branch_id, arm_id), ...]: the arms that
                              # must ALL be taken for this branch to be
                              # reached at all -- outermost first

witness = solve(field_spec, branch.arms["THEN"])   # Witness | Unsatisfiable
```

**`enclosing`: the path condition.** Every `BranchConstraints`
records the `(branch_id, arm_id)` chain enclosing it. `_walk_list` threads it
down through `_nested_statement_lists`, which pairs each nested statement
list with the arm id it sits under (`THEN`/`ELSE` for an IF, `WHEN_n`/
`WHEN_OTHER` for an EVALUATE or SEARCH) -- ids that match the keys registered
in `arms`, by construction, so `ScenarioPlanner` can join on them. A
non-branch nesting (`ON EXCEPTION`, an inline `PERFORM` body) contributes no
entry: it is a path condition in the general sense but is not modeled as a
branch arm here, and inventing an id for one would produce a path entry
nothing could ever join to. **SEARCH's `AT END` is the exception**
(`_ARM_BEARING_ATTRS`): `_extract_search` really does register an
`arms["AT_END"]` entry, so a statement nested under it has an enclosing arm
to join to -- even though the clause reaches `_walk_list` through
`_NESTED_STATEMENT_ATTRS` rather than a `when_clauses` list. Leaving it
untagged made such a statement look top-level, so a scenario for a branch
inside it could be reported verified without its data establishing that the
table search found nothing.

This exists because the planner's v1 simplification -- take only the targeted
arm's own conjuncts -- was the biggest single source of scenarios whose data
never reached their own arm. On `IF INV-QTY > 500 / IF INV-TYPE = "AB"`, the
inner arm's scenario pinned `INV-TYPE` and let `INV-QTY` fall wherever the
value factory put it, so it usually never entered the outer arm at all, and
the scenario's name was a claim its data did not support. See
[generators](../generators.md)'s "Path conditions" section for the planner side.

**Extraction sources and op vocabulary** (`FieldConstraint.op`): `eq ne lt le
gt ge in_set not_in_set class_numeric class_alphabetic figurative`.
Relational comparisons (`=`, `>`, `<`, `>=`, `<=`, `NOT =`/`<>`) map directly;
a level-88 bare condition-name (`IF ORDER-VALID`) resolves through
`ProgramLayoutIndex.resolve()` to its *parent* field and becomes `in_set`
over **that one condition name's own** VALUEs (THRU ranges included), read
via `ProgramLayoutIndex.condition_values()` — deliberately NOT
`FieldSpec.condition_values`, which is the *union* of every 88 declared
under the parent field. The union is correct for the value factory ("any
value that could apply to this field") and wrong here: reading it made every
arm of an `EVALUATE TRUE / WHEN <88>` chain produce a byte-identical
constraint, so the solver picked the first 88's value for all of them and the
scenario named for the second arm was seeded with the first arm's value and
never reached the branch it was named for. Both lookups stay available
because they answer different questions. **A negated 88 needs the whole
set**: `condition_values()` is only a *sample* when a `THRU`
range could not be enumerated (a non-integer range lists its endpoints, an
integer one is capped at 65 values, and any range over a field with
decimals admits values in between). `NOT <88>` over such a name, and the
`WHEN OTHER` after `WHEN <88>`, are reported in `unsupported` rather than
modelled as a `not_in_set` whose witness can sit inside the range
(`layout.condition_values_exhaustive()` over
`ProgramLayoutIndex.condition_raw_values()` decides; a non-exhaustive
positive `in_set` carries `FieldConstraint.exhaustive=False`, not part of
`to_dict()`). An 88 `VALUE ALL 'X'` is the `in_set` of the one
value filling the field (`XXX` on `PIC X(3)`, from
`ProgramLayoutIndex.condition_values`); `VALUE ALL SPACES` counts as the
figurative `SPACES`; only a bare `ALL` is still reported unsupported. An 88
whose one VALUE is a figurative constant (`VALUE
SPACES`) becomes the `figurative` constraint `IF X = SPACES` would, instead
of an `in_set` over the word itself (which rendered `"SPA"`);
figurative constants (`SPACES`/`ZEROS`/`LOW-VALUES`/...) become `figurative`
with the symbolic name preserved in `values`, not its literal expansion (the
solver fills an alphanumeric field's whole width with it: `ZEROS` on `PIC
X(3)` is `"000"`, since `"0"` pads to `"0  "`); `LOW-VALUES` / `HIGH-VALUES` / `NULL`
(binary X'00' / X'FF', which generated character data never holds -- both
tables map them to `""`, which rendered as *blanks*) make the positive test
`Unsatisfiable` instead of witnessing spaces, and a numeric field compared
equal to any non-zero figurative (`SPACES`, `QUOTES`, ...) likewise, rather
than no-op'ing to an arbitrary number
(`tests/regression/test_domains_unrepresentable_figuratives.py`); the negated
forms narrow nothing;
class tests (`IS NUMERIC`/`IS ALPHABETIC`) become `class_numeric`/
`class_alphabetic`; sign/zero tests (`IS POSITIVE`/`NEGATIVE`/`ZERO`) fold
directly into the relational vocabulary (`gt 0`/`lt 0`/`eq 0`) rather than
getting their own domain-handling branch. An EVALUATE selector marked
`"expression"` (or any unquoted one with internal whitespace / parentheses),
and a range bound of that shape, is reported unsupported ("computed operand
rather than a literal") instead of being solved as literal text (#333), so
WHEN OTHER is not counted as targeted against made-up text either. `negated` only carries meaning for
`class_numeric`/`class_alphabetic`/`figurative`, which have no separate "not"
op name (unlike `eq`/`ne` or `in_set`/`not_in_set`, which absorb negation
directly into the op choice).

**`class_numeric`/`class_alphabetic` extract cleanly but do not narrow a
witness in v1.** `domains.py`'s `solve()` treats both ops as a no-op on
whichever domain (`NumericDomain`/`TextDomain`) the field's category picked —
the arm containing an `IS NUMERIC`/`IS ALPHABETIC` test is still correctly
`"targeted"` (or `"merged"`) in `ScenarioPlanner`'s coverage accounting, and
every *other* constraint on the same field still narrows normally, but the
generated value for a field constrained *only* by a class test is not
guaranteed to actually satisfy that test — found producing
`docs/fixture-bundle-schema.md`'s worked example (Phase 6): an `IS NUMERIC`
arm's witness rendered as an arbitrary alphanumeric value, not a digit
string. Every other op in the vocabulary above is fully solved.

**`WHEN OTHER` is the negation of every prior arm, not "unconstrained".**
`_negate_prior_arms` models the shape that dominates real COBOL — an
`EVALUATE` whose every arm is a single `eq`/`in_set` test on the *same*
field — as exactly one `not_in_set` over the union of those arms' values.
Anything else (arms over different fields, conjunctions, relational or class
tests) needs a disjunction the `FieldConstraint` vocabulary cannot express,
so the arm's conjunct list is `[]` *and records why*: in the branch's
`unsupported` list and, keyed by arm id, in `BranchConstraints.
unmodeled_arms` (`_negate_prior_arms` returns `None` for "not modeled",
distinct from `[]` for "no earlier arm"). Every SEARCH `AT_END` is listed
there too. The `[]` is kept in `arms` only so a nested branch has an
enclosing arm to join to; `ScenarioPlanner` counts an `unmodeled_arms` arm
`missed` and never solves its `[]` -- solving it as "anything goes" targeted
the arm with rows that ran an earlier WHEN, and verification then called
zero conjuncts `verified` (#509). Only a `WHEN OTHER` whose earlier WHENs
were all modeled is listed: after a WHEN that was itself unsupported (e.g.
`EVALUATE WS-MODE`, "field not boundary-fed"), `WHEN_OTHER` is left out of
`arms` like that sibling, so the planner misses it for the sibling's reason
and -- like the sibling -- it does not fail `--strict`. Leaving it unconstrained unconditionally (v1) was not the
neutral choice it looks like: an unconstrained level-88 field is generated by
drawing from its own `condition_values` (`generators/data/values.py`), so
every row of the scenario named for the OTHER arm carried one of the very
values that arm excludes — the scenario could not reach its own branch,
deterministically rather than just often.

**Every later `WHEN` arm also negates the earlier ones.** `EVALUATE` is
first-match, so `WHEN_n` runs only when `WHEN_1..n-1` all failed.
`_negate_earlier_whens` conjoins onto each later arm the negation of every
earlier arm that is a single constraint (`gt`<->`le`, `eq`<->`ne`,
exhaustive `in_set`<->`not_in_set`, class/figurative flip). Without it
`WHEN A > 50 / WHEN A > 10` witnessed 51 for the second arm — a value that
takes the first — and a duplicate `WHEN 1 / WHEN 1` reported the unreachable
second arm as satisfiable (it is `Unsatisfiable`). An earlier arm that cannot
be negated into one constraint (a `THRU` range, a conjunction, an
unsupported selector) is left out and noted in `unsupported`. `WHEN OTHER`
still negates only each arm's *own* selector constraints.

**A figurative `WHEN` selector is a `figurative` constraint** (see #313).
`_build_selector` marks a single-token selector `"figurative": True` (`WHEN
SPACES` / `ZERO` / `LOW-VALUES`) or `"quoted": True` (`WHEN 'SPACES'`), and
`_extract_evaluate_selector` maps a figurative selector the way the IF path
does (`_figurative_name`); a quoted selector is never looked up as a data
name. Without the distinction, gen-fixtures writes the six characters
`SPACES` for the figurative arm and calls it verified. `business_rules._literal`
renders a quoted selector with its quotes, so `WHEN 'SPACES'` reads as
`= 'SPACES'`.

**The level-88 enum domain is a preference, not the field's domain.**
`solve()` tries `EnumDomain(spec.condition_values)` first whenever a set op is
in play, so `IF NOT TYPE-M` against 88s `"05"`/`"09"` still yields the other
*declared* value `"09"` rather than an arbitrary PICTURE-admissible string.
But a `not_in_set` covering every declared value — exactly what a `WHEN
OTHER` arm negates to — empties that enum, and the answer there is a value
*outside* it, which the PICTURE does admit. An emptied enum therefore falls
back to `_picture_domain()` and re-applies the same constraints, instead of
reporting `Unsatisfiable` for a perfectly reachable branch. `_apply_numeric`
handles `in_set`/`not_in_set` explicitly for that fallback path (excluding
every listed value, or narrowing to the first admissible member) rather than
no-op'ing them, so a witness can never silently violate a set op it was
solved against. A genuine contradiction (`in_set ("A")` AND
`not_in_set ("A")`) is still `Unsatisfiable`.

**An enum pick is re-checked against every conjunct** (see #244).
`EnumDomain` narrows only by set ops; a relational or class conjunct beside
one is a no-op there, so `IF NOT HIGH-V AND WS-C > 5` (88s `1`/`9`) must not
return `1` (it survives `not_in_set ("9")` and fails `> 5`). Each surviving
declared value is pinned (`eq`) into a fresh `_picture_domain()` and every
conjunct is applied (`_pinned_picture_domain`); the first value that holds is
the witness, rendered through the same post-checks as any other. None holding
falls back to the picture domain, which solves the relational part itself
(`52` for the example) or reports the contradiction (`HIGH-V AND WS-C < 5` is
`Unsatisfiable`).

**AND/OR/NOT via De Morgan.** `IfStatement.condition` is walked once for the
THEN arm (`negate=False`) and once more for the ELSE arm (`negate=True`).
Most negation is baked into concrete operator strings (`NOT_EQUAL`/`IS NOT
NUMERIC`), but `_conditions.py` wraps a negation it cannot fold -- `NOT
FLAG-ON`, `NOT (A = 1 AND B = 2)` -- in a unary `LogicalExpression("NOT")`
whose operand is `left_condition`; `_extract_expr` walks that operand with
`negate` flipped (rejecting the wrapper would leave both arms of `IF NOT
<88>` unmodeled). An AND stays a single conjunct list; a negated AND becomes a
disjunction (`NOT(A AND B) = NOT A OR NOT B`) and vice versa for OR --
implemented as one `(operator == "AND") != negate` boolean flip, not two
separate code paths. A conjunction drops the *whole* variant if either side
fails to extract (keeping only one conjunct would silently widen the modeled
domain past what the source requires); a disjunction safely keeps whichever
side(s) did extract (narrowing to fewer alternatives is still sound for
witness generation, just incomplete). More than one variant means an OR was
present; each becomes its own arm via a `#1`/`#2` suffix (`arms["THEN"]` vs.
`arms["THEN#1"]`/`arms["THEN#2"]`) -- the parent plan's dataclass models one
flat conjunct list per arm *id*, not a list of variants per arm, so OR
alternatives are represented as separate arms rather than nested lists.

**`branch_id` is not `ProgramFlowAnalyzer`'s `BranchNode.node_id`.**
Replicating `program_flow/scanner.py`'s exact sequential counter would
couple this module to that scanner's specific traversal order; instead
`branch_id` self-encodes `f"{parent_proc}@{line}:{column}"`, the same join
key `BranchNode` really is keyed by in substance. The actual join a later
phase should perform is `(line, column)` alone, via the dedicated `line`/
`column` fields (`column` added when Phase 5's `ScenarioPlanner` needed it --
see [generators.md](../generators.md)) -- **not** by comparing `parent_proc`
strings: `program_flow/scanner.py` uppercases its own `parent_proc`
(`pname.upper()`) while this module preserves the source's original casing,
so the two are not directly comparable even when they name the same
paragraph (found writing Phase 5's own tests).

**PERFORM UNTIL's `until_condition` is never itself a `ConditionalExpression`
/`LogicalExpression`.** It is always the historical
`CobolExpression("CONDITION")` wrapper holding the raw joined string in
`.operands`; the real structural tree (when `_conditions.py`'s shared
machinery could build one) lives on its `.condition_tree` attribute (M12 --
see `perform_parser.py`'s `_make_until_condition_expression`). Walking
`until_condition` directly instead of `until_condition.condition_tree` was
the first bug found writing this module's own tests -- every PERFORM UNTIL
condition came back `"unsupported expression node: CobolExpression"`.

**The EOF/loop-flag idiom -> `SequenceConstraint`.** `_collect_eof_flags`
walks `ast.get_all_statements()` for every `IOReadStatement` whose
`at_end_clause` contains a `MoveStatement`, mapping the MOVE's target field
name to that READ's file name. When a `PERFORM UNTIL`'s condition mentions
that same field (by name only -- exact value match is not required, matching
on field identity is simpler and more robust to minor variations), the
`SequenceConstraint.boundary` is looked up from the *existing* `Boundary` in
`boundary_report.boundaries` (never freshly synthesized) so it is always a
real, already-resolved `BoundaryRef`. `length` is `None` in v1 -- "the flag
pattern exists" -- picking a concrete record count is Phase 5's job. A
condition that touches a boundary-fed field but matches no such pattern gets
one `unsupported` note rather than silence; a pure internal counter loop
(`PERFORM UNTIL I > 10`, `I` not boundary-fed) is correctly silent -- out of
scope, not a gap.

**SEARCH WHEN is extracted from a condition tree** (see #348).
`search_parser.py` builds each WHEN condition with the shared
`build_condition_expression` (the IF / PERFORM UNTIL machinery) and stores
it as `when_clauses[i]["condition_tree"]` next to the unchanged raw
`"condition"` string; `SearchStatement.to_dict()` serializes it too.
`_extract_search` walks that tree with `_extract_expr`, so `WHEN A = 'K1' AND
B = 'Z'` is two conjuncts and an OR becomes `WHEN_n#1` / `WHEN_n#2` arms,
exactly like IF. Splitting the raw text on its first operator would turn the
whole tail (`K1' AND B = 'Z`) into one made-up literal. A SEARCH node built
without a tree still falls back to the text parser below.

**`EVALUATE TRUE`'s non-compound selectors use a minimal text parser.**
`EVALUATE TRUE WHEN <selector>` lacks structure for a simple relational
selector: `evaluate_parser.py`'s `_build_selector` never emits an
`"Identifier"` selector type at all -- a bare condition-name like `WHEN
F1-VALID` and a simple comparison like `WHEN F1-QTY = 5` both arrive as
`{"type": "Literal", ...}` / `{"type": "Condition", "text": ...}` with no
`"operator"` key. Those route through `_parse_relational_text`; a compound
`AND`/`OR` selector (`sel["operator"]` present) stays unsupported in v1.
`_parse_relational_text` itself reports any text holding an `AND`/`OR`
outside a quoted literal as unsupported rather than splitting it on its first
operator.
Before matching, `_symbolize_relational_words` spells the word operators
as symbols (`[IS] [NOT] GREATER|LESS [THAN] [OR EQUAL [TO]]`, `EQUAL[S]
[TO]`; quoted literals untouched), so `WHEN X GREATER THAN OR EQUAL TO 1`
yields the same `ge` constraint as `WHEN X >= 1` and its `OR` is not taken
for a connective (#387). `complexity.py`'s `_BOOL_WORD_RE` likewise skips
the OR of `OR EQUAL`.

**Two-field comparisons are unsupported in v1** (`IF F1-QTY > F1-STATUS`) --
stated as a parent-plan limitation, not attempted.

**Numeric witnesses are picked on the field's decimal grid.**
`domains.NumericDomain.pick()` enumerates candidates in integer units of
`10**-decimals` (starting from the grid midpoint, scanning up, wrapping to the
low bound), quantizes exclusions to the same grid before comparison, and
`solve()` re-verifies the RENDERED witness against the numeric domain
(`_rendered_numeric_ok`). A raw float midpoint is wrong: `PIC 9` with `ne "4"`
would pick 4.5, which `ValueFactory.render()` rounds back to the excluded "4".
Fully deterministic. Pinned by
`tests/regression/test_audit_2026_08_12_analysis.py::TestA6WitnessOnTheDecimalGrid`.

**A COMP-1/COMP-2 field is solved over a float domain, not its PICTURE.**
It has none; `_picture_domain` gives `FieldCategory.FLOAT` a signed
`[-FLOAT_LIMIT, FLOAT_LIMIT]` (1E15) on a `FLOAT_DECIMALS` (4) grid, and
`scenarios._picture_ceiling` / the boundary-values family use the same bound.
The layout's placeholder `PIC 9(9)` shape made `IF F < -100` and
`IF F > 0.25 AND F < 0.75` unsatisfiable (#551). A float equality literal with
more than 4 decimals is off the grid and so still unsatisfiable. Pinned by
`tests/unit/analysis/test_domains.py::TestFloatDomain` and
`tests/unit/test_program_fixtures.py::TestFloatFieldArms`.

**The whole numeric pipeline is Decimal, never float.** `NumericDomain`'s
bounds/exclusions, `_apply_numeric`'s literal parsing, `_rendered_numeric_ok`,
`scenarios._picture_ceiling`, and `ValueFactory._format_number` /
`_fit_domain_value`'s exact-value path all use `Decimal`, with
`localcontext(prec=80)` around the few multiplications/epsilon-nudges that
could outgrow the default 28-digit context on the widest PICTUREs. float64
rounds any literal past ~16 significant digits (a `PIC 9(17)`/`9(18)` account
key: `eq 123456789012345678` would witness `123456789012345680`), the fixture
row would never take the branch, and `ScenarioCoverage` would still count the
arm targeted. Pinned by `tests/regression/test_bug_review_2026_08_12.py`.

**Compound relational operators.** The lexer emits `>=`, `<=` and `<>` as two
single-character tokens; `_conditions.py` recombines them
(`_COMPOUND_SYMBOL_OPS`, see [../parser.md](../parser.md)) in the same
cleaning pass that recombines `NOT`-prefixed operators. Without that, `IF WS-X
>= 5` parses as `GREATER` with right operand `= 5` for every consumer of
`build_condition_expression`.

## ConstantFolder

Phase 7 tier 2 of the `gen-fixtures` initiative (see
`docs/plans/2026-08-02-program-data-generation-design.md`): a single forward
walk of a program's entry paragraph chain, seeded by one scenario's own
mock-supplied inputs, that tracks which data items hold a knowable literal
value after a MOVE or a simple arithmetic/COMPUTE statement. Wired into
`ProgramFixtureGenerator` (`generators/program_fixtures.py`'s
`_tier2_expectations`), which builds the seed dict from every
`BoundaryFixture` with *exactly one* generated row and turns every field
still knowable at a `DISPLAY`/`WRITE` into a `kind="field_equals"`
`Expectation` -- see `docs/fixture-bundle-schema.md`'s Expectation section
for the full worked example.

```python
from cobolparser.analysis.const_fold import ConstantFolder

folder = ConstantFolder()
result = folder.fold(ast, index, seed_values={"WS-QTY": "622"})
result.known   # dict[qualified_name, str]: the value each field held at
               # the DISPLAY/WRITE sites that observed it
```

**`known` is the value at the observation point** (see #246).
`_WalkState.observed` records the env value at every `DISPLAY`/`WRITE` site; a
field is reported only when every site saw the same known value (not the env
at the end of the walk: `MOVE 1 TO N3. DISPLAY N3. MOVE 2 TO N3.` is `1`). The
walk **falls through**: after the entry paragraph it continues into every
following paragraph in source order (`_fall_through_chain`) until the walk
stops (`STOP RUN`/`GOBACK`/`EXIT PROGRAM`/`GO TO`), so a program displaying
`1` in `MAIN-PARA` and `2` in the next paragraph gets no `N3` expectation.
Following real control flow re-walks a PERFORMed paragraph each time control
reaches it -- quadratic for a chain of paragraphs that each PERFORM the next
with no STOP RUN -- so the main walk has a `_MAX_WALK_STEPS` (50,000 statement
visits) budget; past it the fold reports nothing (`_WalkState.exhausted`),
never a partial answer. `test_const_fold_corpus.py`'s non-triviality check
folds `tests/samples/file_operations.cbl` and `enterprise/COMPDIR.cbl`.

**Every site, and only control flow the walk really follows** (each case
checked against GnuCOBOL 3.2 output):

* **Every DISPLAY/WRITE is a site, walked or not.** A site inside an
  IF/EVALUATE arm, a loop body or a handler is recorded as unknown
  (`_poison_written_names`), and at the end `fold()` vetoes every field
  shown at a site the walk never reached (`_observation_sites` against
  `_WalkState.visited_sites`): code past a `GO TO`, code only a `GO TO`
  reaches, DECLARATIVES, dead paragraphs. (`MOVE 1 TO A. DISPLAY A. IF ...
  MOVE 2 TO A DISPLAY A END-IF.` gives no `A`.)
* **`PERFORM` of a SECTION** (and `THRU` a section) walks the section's
  paragraphs, unnamed ones included: `_ordered_paragraphs` keeps a
  `_SECTION_KEY` marker per section and an `_UNNAMED_KEY` key per unnamed
  paragraph, `_procedure_span` resolves both ends. A target that resolves to
  nothing at all clears the env.
* **SEARCH WHEN bodies and SORT/MERGE INPUT/OUTPUT PROCEDUREs** are
  poisoned like a loop body (`_nested_statement_lists`, `_procedure_ranges`).
* **Conditional transfers.** A `GO TO`, `EXIT PARAGRAPH/SECTION/PERFORM` or
  `NEXT SENTENCE` inside an arm / loop / handler (or a main-line `EXIT
  PARAGRAPH`...) sets `_WalkState.uncertain`: from then on every
  MOVE/arithmetic/READ/ACCEPT poisons instead of folding, because the walk
  can no longer tell whether it ran. A `GO TO` also clears the env (it runs
  code the walk never sees), so the `IF ... GO TO P1-EXIT` idiom never folds
  the MOVE the GO TO skips. Conservative: uncertainty lasts to the end of
  the walk. Pinned by
  `tests/unit/analysis/test_const_fold.py::TestControlFlowTheWalkDoesNotFollow`.
* **A CALL / INVOKE forgets every GLOBAL and EXTERNAL leaf**: a contained
  program writes a GLOBAL item by name and every program declaring the same
  EXTERNAL item shares its bytes, USING list or not. `_LayoutFacts.shared`
  (inherited from a GLOBAL/EXTERNAL group) is dropped in
  `_poison_statement_writes`. Pinned by
  `tests/unit/analysis/test_const_fold.py::TestCallMayWriteSharedStorage`.

**"Exact by construction, or absent" -- never a guess.** Every ambiguity
below resolves by leaving a field unknown (poisoned: removed from the
internal env) rather than approximating:

* A `PERFORM ... UNTIL`/`VARYING`/`TIMES` loop may run zero or many times,
  so nothing inside it is knowable at fold time -- every field its body
  (including through a nested `PERFORM` to another paragraph) could write is
  poisoned, and the walk continues *after* the loop, since it still runs;
  the walk just cannot see inside it. A non-looping `PERFORM` (a plain
  paragraph call, optionally `THRU` a range) is walked inline exactly once,
  including into paragraphs it in turn `PERFORM`s, guarded against a
  non-looping `PERFORM` cycle by tracking which paragraphs are already on
  the current call stack. The loop's own `VARYING` / every `AFTER` variable
  is poisoned too (it ends one step past the UNTIL, never at its pre-loop
  value) -- inline, out-of-line, and nested inside an IF arm / loop body
  alike, via `_write_targets(PerformStatement)`. `SEARCH ... VARYING x`
  poisons `x` the same way (`varying_variable`).
* A write through a level-66 `RENAMES a [THRU b]` alias poisons the leaves
  it covers (`_LayoutFacts.renames`, the declaration-order run from `a`'s
  first leaf to `b`'s last; the whole record when that run is ambiguous).
  The alias is written, never seed-restored, by READ INTO / ACCEPT.
* An `IF`/`EVALUATE` branches on data this walk does not evaluate (Phase 5's
  `ScenarioPlanner` already owns targeting one specific arm elsewhere), so
  every field either arm could write is poisoned the same way as a loop
  body -- this is a conjunctive walk, not per-scenario branch evaluation.
* A conditional handler body (`AT END`/`NOT AT END`/`INVALID KEY`/`ON SIZE
  ERROR`/`ON OVERFLOW`/`ON EXCEPTION`/`AT EOP` and their `NOT` variants,
  the `_HANDLER_BODY_ATTRS` tuple) may or may not fire, so every field it
  could write is poisoned exactly like an `IF` arm -- and the poison runs
  AFTER the statement's own fold, so a handler writing the statement's own
  target (`ADD 1 TO X ON SIZE ERROR MOVE 0 TO X`) still leaves X unknown
  (`MOVE 'N' TO WS-EOF. READ F AT END MOVE 'Y' TO WS-EOF. DISPLAY WS-EOF.`
  gives no `WS-EOF`). Pinned by
  `tests/regression/test_audit_2026_08_12_analysis.py::TestA1HandlerBodiesPoisonTheFold`.
* `DIVIDE` folds the unambiguous forms: `DivideStatement.division_mode`
  records `BY` vs `INTO` (the two invert dividend/divisor order), so
  `_fold_divide` computes `DIVIDE a BY b GIVING c` (c = a/b), `DIVIDE a INTO b
  GIVING c` (c = b/a), and the in-place `DIVIDE a INTO b [c ...]` (each target
  /= a). A mode-less node, `ROUNDED`, the nonstandard `DIVIDE a BY b` without
  GIVING, divide-by-zero, and any non-exact quotient all poison. A
  `REMAINDER` target is always poisoned (it is defined via the quotient as
  truncated to the GIVING target's PICTURE, which this module does not model)
  and is part of `_write_targets`' IF-arm/handler-body write scan. The GIVING
  value stays safe to fold alongside a poisoned REMAINDER: it is only
  recorded when the true quotient fits exactly, i.e. truncation was a no-op.
  A `/` inside a `COMPUTE` expression tree goes through the same
  `_exact_divide` gate, so both spellings of a division hold the same
  contract. Pinned by
  `tests/regression/test_bug_review_2026_08_12.py::TestDivideMode`.
* **Exactness is decided over `Fraction`, never over `Decimal`.**
  `_exact_divide` multiplies the quotient back over `Fraction`, and
  `_fits_exactly` (the last gate before a value is stored) scales over
  `Fraction` too. Decimal arithmetic rounds in its own context: a multiply-back
  inside the `prec=80` block of the division rounds straight back to the
  dividend, and `abs()` / `*` in the ambient 28-digit context round a value
  carrying more precision before it is tested (`COMPUTE WS-T = 3 /
  0.3333333333333333333333333333334` into `PIC S9(9)V9(9)` must not fold to
  `9.000000000`; COBOL stores `8.999999999`). Reachable with a 29-31 digit
  literal (IBM `ARITH(EXTEND)`). Pinned by
  `tests/regression/test_audit_2026_09_16.py`.
* **Writes that live outside `.operands`** (see #317). `_write_targets` also
  collects `InspectStatement.tallying_clauses[*]["counter"]` (INSPECT ...
  TALLYING increments it in place), every string value of
  `ExecCicsStatement.options` (INTO/SET/LENGTH/RESP/RESP2/ITEM/...: the
  command decides which are written, so all are taken as written), and the
  argument of each `KEYWORD(arg)` in `ExecImsStatement.arguments` (EXEC DLI
  INTO/KEYFEEDBACK/...). Both EXEC nodes have an empty `.operands`. Pinned by
  `tests/unit/analysis/test_const_fold.py::TestInspectAndExecWrites`.
* **A COMPUTE division is truncated mid-expression the way IBM truncates
  it.** IBM carries a fixed-point quotient to only
  `max(d1 - d2, dmax)` decimal places ("Intermediate results and arithmetic
  precision"; `dmax` = the most decimal places of any result field or any
  operand other than a divisor or exponent), so `COMPUTE N = 7 / 2 * 2`
  into `PIC 99` stores 6 and `COMPUTE PCT = A / B * 100` stores 0 when
  A < B. `_dmax_floor`
  computes a lower bound on `dmax` (every leaf under a `/` or `**`
  right-hand side left out -- a smaller bound only poisons more), and
  `_truncation_free_divide` poisons any quotient needing more places.
  Exponentiation follows IBM's three cases (`_fold_power`): an integer
  literal exponent is exact (`d1 * n` places); a negative one is
  `1 / x ** n` under the division rule (`100 * 2 ** -1` into `PIC 9(4)`
  is 0, not 50); an integral data-name/expression exponent carries only
  `dmax` places; an exponent with decimal places means floating point,
  poisoned. Pinned by
  `tests/regression/test_const_fold_intermediate_precision.py`.
* `ROUNDED`, `CORRESPONDING`, and any target that does not resolve to an
  elementary field are poisoned rather than approximated. A numeric
  MOVE/arithmetic result is only ever recorded when it fits its target
  field's PICTURE *exactly* (`_fits_exactly`: no truncated decimal digits,
  no truncated integer digits, no sign coercion into an unsigned field) --
  real COBOL's MOVE truncation rules are well-defined, but replicating them
  exactly is out of scope for v1; an overflowing result is poisoned instead.
  `MOVE ZERO`/`ZEROS`/`ZEROES` folds (0 into a numeric field, `"0"` in every
  position of an alphanumeric one) and `ZERO` is a known arithmetic operand.
  A text MOVE into `PIC N(n)` truncates to n characters (`spec.size` is
  bytes, two per national character).
* **ADD/SUBTRACT addends come from `ArithmeticStatement.source_operands`**,
  the operands written before TO/FROM/GIVING with duplicates
  kept, set by the ADD/SUBTRACT parsers and not serialized.
  `ArithmeticStatement.operands` cannot answer "which names are addends":
  `set_target`/`set_giving` append a name only when it is absent, so
  `ADD A B GIVING B` and `ADD A GIVING B` both leave `[A, B]`, so filtering
  target/GIVING names out of `.operands` would poison `ADD X TO X` and
  silently drop a real addend in `ADD -6.05 N8 GIVING N8` or `ADD X, Y TO X`.
  Checked by fuzzing random straight-line programs against GnuCOBOL (~12,000
  folded values compared). A node without `source_operands` is poisoned.
  `MULTIPLY`'s
  format-1 (`MULTIPLY A BY B`, no GIVING) has no analogous issue:
  reusing the target's own name as the second operand is directly what the
  statement means (multiplication has no target-is-also-an-addend hidden
  term the way ADD/SUBTRACT's TO/FROM accumulation does), so only GIVING
  names are filtered from its operand list, never targets.
* **ACCEPT/READ are a deliberate no-op, not an omission.** They are exactly
  the boundary categories `_tier2_expectations` seeds `env` from before the
  walk starts; falling through to the generic "unmodeled write" fallback
  below would poison that seed the instant the walk reached the very
  statement it represents. `CALL`/`EXEC SQL`/`CICS`/`DLI` are *not* given
  the same treatment -- their operand lists mix genuinely-unknowable
  OUT-direction values with seedable IN ones, and the raw AST does not carry
  resolved direction to tell them apart (only `BoundaryInventoryAnalyzer`'s
  own richer analysis does) -- deferred to a future version rather than risk
  treating an OUT value as still-known.
* **Keyed READ sites (`ConstantFoldResult.read_keys`, issue #322).** At
  every keyed READ of an INDEXED file (`keyed_read_key()`: RANDOM, or
  DYNAMIC without NEXT/PREVIOUS/FIRST/LAST; the `KEY IS` name, else the
  RECORD KEY) the walk records each elementary leaf of the key from `env`,
  before the READ resets the record area. `read_keys[(FILE, line)]` is that
  rendered dict when every pass over the READ saw the same fully-known key,
  else `None` -- a READ only poisoned (branch/loop body, uncertain mode) or
  never reached is `None`. Not in `to_dict()`; `ProgramFixtureGenerator`
  pins it into the READ's mocked rows (see generators.md).
* **A subscripted/reference-modified READ INTO or ACCEPT target is poisoned,
  never restored.** `_target_paths()` returns `(qpath, exact)` pairs; a
  suffixed target's `_reset_under` call always passes `restore=False`, since
  only part of the base item was written (resolving to the base item's whole
  qualified name would restore all of it to its seed value). Same `has_suffix`
  rule `_apply_move_target`/`_write_numeric` apply.
* **Storage shared without a REDEFINES clause** (see #245).
  Every 01 under one FD/SD implicitly redefines the same record area, so
  `_link_file_records` unions the leaves of every
  `index.records_for_file(f)` (`ProgramLayoutIndex.file_names()`) into one
  alias class: `MOVE 1234 TO B. MOVE 'ABCD' TO A. DISPLAY B.` (B in R2, A in
  R1, both under `FD F`) leaves B unknown. `I-O-CONTROL. SAME RECORD AREA
  FOR f1 f2` (#497) widens the class across FDs to every record of every
  file in the group (`_files.same_record_area_groups()`); plain `SAME AREA`
  shares no records and widens nothing.
  `WRITE rec FROM id` is folded as `MOVE id TO rec` before the WRITE is
  observed (a group record is poisoned whole); `REWRITE ... FROM` takes the
  generic poison path, which already covers the record. A field source
  MOVEd into a `JUSTIFIED RIGHT` receiver is space-padded to its own width
  first (`_text_width`), because `env` stores text unpadded and COBOL sends
  the whole field: `X5 = 'ABCD'` into `PIC X(3) JUST RIGHT` is `'CD '`,
  not `'BCD'`.
* Any other statement type this module has no specific rule for
  (`INITIALIZE`, `SET`, `STRING`/`UNSTRING`, `INSPECT`, and the CALL/SQL/
  CICS/DLI cases above) conservatively poisons every name in its `.operands`
  -- a fail-safe default, not a silent skip.
* Only a `DISPLAY`/`WRITE` operand that resolves *directly* to an elementary
  field is an observation point -- a whole-record `WRITE`'s individual
  member fields are not (yet) walked, so some real `field_equals`
  opportunities are silently not offered. Never wrong, sometimes just
  quieter than it could be. `GO TO`, `STOP RUN`, `GOBACK`, and `EXIT
  PROGRAM` all stop the walk outright (unreachable code after them is never
  folded or observed). A paragraph's end is not a stop: control falls
  through into the next paragraph (#246).

**Robustness invariants.**

* `_safe_resolve` rejects empty/punctuation-only tokens before calling
  `ProgramLayoutIndex.resolve()`: the generic "poison via `.operands`"
  fallback sees non-name garbage (a stray `"."` operand from some real
  programs), and `resolve()` itself returns `None` for an all-punctuation
  name. Verified against the full 459-file NIST COBOL-85 corpus.
* Paragraph chains are followed on an explicit frame stack, never by Python
  recursion: `_walk_perform` and `_poison_written_names` both keep one entry
  per open paragraph (`visiting` add/discard bracketing the frame's lifetime),
  the same explicit-stack DFS `program_flow/cycles.py`'s `detect_cycles` uses.
  A straight chain of a few hundred `PERFORM`s is an ordinary large program,
  not an adversarial one. Recursion is kept only for genuinely *nested*
  statement lists (an `IF`/`EVALUATE` arm or loop body inside a block being
  poisoned, an inline `PERFORM` inside an inline `PERFORM`), bounded by source
  nesting. Pinned by `tests/unit/analysis/test_const_fold.py::TestPerformChaining`
  (2000-paragraph chains, both directions).
* `_ordered_paragraphs` interleaves sections and top-level paragraphs by
  `location.line`, like `program_flow/scanner.py` and `dead_code.py`;
  otherwise a `PERFORM ... THRU ...` spanning a top-level and a section-owned
  paragraph resolves to `end_idx < start_idx` and an empty body. Pinned by
  `tests/regression/test_audit_2026_08_12_analysis.py::TestA4OrderedParagraphsInterleaveSections`.

## Invocation counts

Backs `gen-fixtures`' tier 1 `call_count` (issue #363; see
`.okf/generators.md`). `count_invocations(ast, report, index)` walks the
entry chain with `const_fold.py`'s own paragraph helpers
(`_entry_paragraph`, `_fall_through_chain`, `_ordered_paragraphs`,
`_perform_body_statements`, `_transfer_kind`) on an explicit frame stack,
and gives each statement it reaches an exact execution count or "unknown":

* main line and SIMPLE PERFORMs (inline, out of line, THRU, SECTION) add
  their multiplier each time reached -- a paragraph PERFORMed and also
  fallen into counts 2; `PERFORM <literal> TIMES` multiplies;
* IF / EVALUATE / SEARCH arms, handler bodies, `PERFORM UNTIL` / `VARYING` /
  variable-`TIMES` bodies and SORT / MERGE procedures are unknown;
* a transfer (GO TO, EXIT PARAGRAPH / SECTION / PERFORM, NEXT SENTENCE,
  STOP RUN, GOBACK, EXIT PROGRAM) inside such a region makes everything
  after it unknown; on the main line, GO TO / STOP ends the walk and a skip
  makes the rest unknown; inside a literal `TIMES` body any transfer
  discards every count (they would be overstated);
* a main-line GO TO is followed forward (`push_chain` at the target) only
  when no statement of the target paragraph was walked yet; a backward jump
  (a GO TO read loop), a GO TO out of a PERFORMed paragraph, GO TO
  DEPENDING ON, an unknown target, or any ALTER in the program discards
  every count;
* **status exemption**: an IF reading only boundary status fields (FILE
  STATUS fields and their level-88s, `SQLCODE`/`SQLSTATE`/`EIBRESP`), an
  INVALID KEY handler, and a CALL's ON EXCEPTION / ON OVERFLOW are decided
  by the scenario's status fixture, so a STOP RUN inside them does not
  blank later counts. Without it, the universal `OPEN` + status-check idiom
  would leave no count after the first OPEN. A FILE STATUS field qualifies
  only while the last boundary that set it (`status_sites`) ran on the
  certain path and is not a READ that can reach end of file: after one, the
  field is '10' in every read-to-EOF scenario and at once for empty input.
  For the IF only the arm success provably does *not* take is exempt
  (#590): `push_if` evaluates the condition (`success_selects`, three-valued
  over AND / OR / NOT) with each status field at its success value -- '00'
  (0 for a numeric FILE STATUS), SQLCODE / EIBRESP 0, SQLSTATE '00000', a
  level-88 by its own VALUEs incl. THRU ranges. The arm success takes is an
  ordinary conditional region, so `IF WS-FS = '00' ... GOBACK` blanks what
  follows; an unevaluable condition (class test, a literal of the wrong
  kind, an ordering over non-digit characters, whose collating order differs
  ASCII vs EBCDIC) exempts neither arm. An exempt region's transfer never
  propagates (`end_region` restores the saved flag), so it cannot leak into
  the sibling arm or handler pushed below it.

`is_plain_eof_loop(ast, perform, index)` backs `_CallCounter`'s EOF rule:
the UNTIL tests exactly one field, and the body (followed through PERFORMs
and SORT procedures) has no transfer -- `UNTIL WS-EOF = 'Y' OR WS-CNT >= 3`
or an EXIT PERFORM can stop before end of file.

`InvocationCounts.for_boundary(ref)` matches a `BoundaryRef` by
(paragraph, line) against statements of a boundary type only, so a MOVE in
an AT END handler on the READ's own line cannot blur the READ's count.
`count_at(line, type)` answers for any statement (used for the EOF loop's
`PERFORM UNTIL`). Unreached statements (GO TO-only targets, DECLARATIVES)
have no count. Tests: `tests/unit/analysis/test_invocation_counts.py`,
`tests/unit/test_program_fixtures.py::TestCallCountFollowsControlFlow`.

## Literal values

`_literals.py`'s `quote_literal()` re-emits a decoded literal doubling each
embedded `"`; its inverse `unquote_literal()` strips the delimiters *and*
collapses the doubled delimiter. Any consumer reading a re-emitted literal back
must use it -- `analysis/constraints.py` (`_strip_quotes`, branch witnesses),
`analysis/const_fold.py` (MOVE sources) and `generators/data/layout.py`
(`_strip_literal_quotes`, VALUE clauses) do; stripping only the delimiters
turns `VALUE "A""B"` into `A""B`. Pinned by
`tests/regression/test_doubled_quote_literal_values.py`.

## See also

* [../analysis.md](../analysis.md) -- routing page, calling conventions, module map
* [../generators.md](../generators.md) -- `ProgramLayoutIndex` (Phase 1),
  `ScenarioPlanner` (Phase 5, path conditions), `ProgramFixtureGenerator`,
  which wires these analyses into a `FixtureBundle`
* `docs/fixture-bundle-schema.md` -- the `Expectation` shapes `call_count` /
  `field_equals` / `stub` produce
* `docs/plans/2026-08-02-program-data-generation-design.md` and its
  implementation plan -- the 9-phase `gen-fixtures` plan (this file covers
  Phases 2, 4 and 7)
* [flow.md](flow.md) -- `ProgramFlowAnalyzer`, whose branch nodes the
  constraints join on `(line, column)`
* [../parser.md](../parser.md) -- `_conditions.py`, EVALUATE selectors, SEARCH
  WHEN condition trees
* [history](../history/analysis.md) -- dated fix write-ups behind these rules
