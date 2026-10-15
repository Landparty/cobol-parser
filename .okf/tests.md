---
type: Reference
title: Tests
description: Test layout, pytest markers, coverage floor (90%), and shared fixtures for the cobolparser test suite.
tags: [tests, pytest, coverage, fixtures, markers]
timestamp: 2026-10-15T00:00:00Z
---

# Overview

2026-10-15: `tests/unit/analysis/test_codebase.py::TestHelpers` (+3, #356)
pins a `:TAG:`-placeholder copybook member reporting its placeholder data
names in `copybook-impact`'s `unresolved` rather than a silently empty
`fields`. See `analysis.md`.

2026-10-15: `tests/unit/analysis/test_redundancy.py::TestClonePriority::
test_repeated_paragraph_name_does_not_drop_type2_group` (#353) pins a
Type-2 clone group surviving when one of its members shares its name with a
Type-1 member in another section. See `analysis.md`.

2026-10-14: `tests/unit/analysis/test_exit_section_and_alterable_goto.py`
(11 tests, #382) pins the alterable `GO TO.` and `EXIT SECTION` as
terminators in dead-code and program-flow: a PERFORMed section returns at
EXIT SECTION, one fallen into, gone to from another section or entered by a
CICS HANDLE branch runs on to the next section, a conditional EXIT SECTION still falls through, and
`EXIT SECTION.` right after a section header is no longer a section named
EXIT.
2026-10-14: `tests/regression/test_special_register_paragraph_boundary.py`
(13 tests, #390) pins `MOVE 0` / `TO` / `RETURN-CODE.` (and TALLY,
SORT-RETURN, the XML-/JSON- registers, `SET ... TO TRUE`) with each word on
its own line: one MOVE with the register as target, no phantom paragraph.
Also pins the fixed-format Area B rule (an undeclared Area B name stays an
operand) and two controls: an Area A header after a missing period, and an
indented free-format name, are still boundaries.
2026-10-14: `tests/regression/test_fd_lrecl_framing_issue_362.py` (18
tests, #362) pins RECFM=F framing at the FD's LRECL for a whole-program
source: `fd_record_length` (largest sibling 01, `RECORD CONTAINS`, `None`
for the longest 01 / WORKING-STORAGE / a bare copybook), `decode`/`compare`
framing a shorter 01's file, `--record-length` still overriding, and
`gen-data` space-padding (ASCII and EBCDIC) so the two round-trip, and
one LRECL per FD when `RECORD CONTAINS` is below the largest 01. Its
program template puts the RECORD clause on its own line: appended to the
FD line it ran past column 72, where fixed format drops it.

2026-10-14: `tests/regression/test_evaluate_word_operator_when.py` (38
tests, #387) pins EVALUATE WHEN phrases with relational words
(`GREATER THAN`, `EQUAL TO`, `OR EQUAL`), class tests and sign tests as
single `Condition` selectors (a lone `WHEN ZERO` stays figurative), the
logical-only `operator: "OR"`, and what business-rules / xref /
ConstraintExtractor / complexity read from them.

2026-10-14: +6 in `tests/unit/analysis/test_unused_variables.py`'s new
`TestObjectOrientedUnitData` (issue #379): FACTORY / OBJECT data used only
by that paragraph's METHODs is not reported unused, data no method touches
still is, an OBJECT method's reference does not reach FACTORY data, and a
method's CALL USING / MOVE CORRESPONDING marks the OBJECT group's fields. One
test runs `tests/samples/enterprise/OOCOBOL.cbl`. See `analysis.md`.

2026-10-14: `tests/regression/test_go_depending_without_on.py` (6 tests,
#377) pins `GO TO P-B P-C DEPENDING WS-D` with ON omitted: the variable is
read, no phantom paragraph appears, and dead-code / program-flow /
unused-variables / complexity all see the jump table.
`test_go_parser_edge_cases.py`'s `test_depending_without_on_reads_variable`
replaces the test that pinned the old behavior.

2026-10-15 (#391): `tests/unit/analysis/test_redundancy.py` gains
`TestLayoutAndCaseDoNotAffectClones` (line breaks, lowercase and spacing
still give TYPE_1; literal case still breaks it; `scan` digests agree) and
`TestUnquotedLiteralCaseStillBreaksType1` (EVALUATE WHEN / THRU, static
CALL, INVOKE and STOP literals differing only in case are never TYPE_1);
`test_evaluate_variants.py::TestRangeQuotedMarkers` pins the Range
`start_quoted` / `end_quoted` markers (and
`test_evaluate_keyword_literal_when.py` now expects them on `'A' THRU 'C'`); `test_compute_expression_parsing.py::
TestComputeExpressionLayout` pins a multi-line COMPUTE's expression text.

2026-10-14: `tests/regression/test_evaluate_figurative_when.py` (6 tests,
#313) pins EVALUATE `WHEN SPACES` / `ZERO` / `LOW-VALUES` as figurative
selectors and constraints, distinct from a quoted `WHEN 'SPACES'`, through
gen-fixtures (blank data for the figurative arm) and business-rules (quotes
kept). Four selector-shape tests now expect the additive `"quoted": True`.
`tests/unit/analysis/test_ast_diff.py` adds a parametrized test that
`WHEN SPACES` -> `WHEN 'SPACES'` and `WHEN WS-B` -> `WHEN 'WS-B'` each diff
as one `condition-changed`.

2026-10-14 (issue #392): new `tests/unit/analysis/test_cics_terminators.py`
(36 tests): `EXEC CICS RETURN` / `XCTL` / `ABEND` end a paragraph for
dead-code (later paragraphs dead), program-flow (no `FALL_THROUGH`,
`has_cics_exit`, exit point) and recursion-check (a RETURN TRANSID retry
loop is MEDIUM with an escape, not a HIGH lint error); a RETURN / XCTL with
`RESP` / `RESP2` / `NOHANDLE` still falls through but stays an exit point
and a loop escape (the RESP retry loop is MEDIUM too), ABEND never does.

2026-10-14: +9 in `tests/unit/analysis/test_dead_code.py`'s new
`TestTransitiveDeadCode` (issue #384): paragraphs PERFORMed / GONE TO only
from dead code are dead (chains, cycles, sections, an ALTER in dead code),
while declaratives, ENTRY paragraphs and live multi-hop chains keep their
targets alive; NIST IC222A / IC227A pin that every paragraph program-flow
finds unreachable is reported dead.

2026-10-14: +10 in `tests/unit/analysis/test_dead_code.py`'s new
`TestSectionExitGoTo` (issue #312): `GO TO nnnn-EXIT` inside a PERFORMed /
SORT-procedure SECTION no longer keeps later sections alive; three guards
pin that a section also fallen into or gone to still runs past its exit,
four more that a jump into it from another section (or an ENTRY) does too.

2026-10-14: `tests/regression/test_evaluate_stacked_when.py`
(11 tests, #314) pins stacked WHEN phrases (`WHEN 'A' WHEN 'B' stmt`) as one
arm while the AST keeps one `WhenClause` per phrase: `when_groups()`,
business rules (`WS-T = 'A' OR WS-T = 'B'`, `reached_via`), one program-flow
`BranchArm` owning the PERFORM, constraint disjuncts `WHEN_1#1`/`WHEN_1#2`
negated by later arms and WHEN OTHER, and scenario names; an empty WHEN
whose body was an unexpanded COPY, or one before WHEN OTHER, is not stacked.

2026-10-13: `tests/regression/test_copy_member_case_folding.py`
(17 tests, #289) pins COPY member and library names folding to uppercase on
a case-sensitive filesystem: `copy errorcd.` finds `ERRORCD.cpy`, the uppercase
member beats `errorcd.cpy`, a lowercase-only member still resolves, extension
order decides before case (in the configured order), `OF mylib` finds
`MYLIB/` without an unrelated `MYLIB/` hiding `mylib/`, path literals are not
folded, and directory order outranks case, in both `PathResolver` and `find_copybook_file`.

2026-10-04: `tests/regression/test_copy_diagnostic_line_numbers.py`
(3 tests, #256) pins COPY diagnostics after continuation records naming the
original file line, from the expander and from `parse_cobol_with_expansion`
(one diagnostic, not two in different coordinates).

2026-10-04: `tests/regression/test_replace_before_identification_division.py`
(9 tests, #254) pins a REPLACE ahead of the IDENTIFICATION DIVISION header
being applied (free and fixed layout; `parse_cobol`, `CobolParser.parse`,
`parse_cobol_with_expansion`), pre-header junk still dropped, line count kept.

2026-10-04: `tests/regression/test_copy_replacing_identifier_operand.py`
(13 tests, #253) pins qualified (`OF`/`IN`) and subscripted (`WS-TBL (2)`,
reference modification) COPY REPLACING operands, end to end against a
directly written MOVE, plus NIST SM202A / SM206A expanding every COPY.

2026-10-04: `tests/regression/test_comment_entry_copy_replace_scan.py`
(12 tests, #251) pins comment-entry text as opaque to the COPY / REPLACE
scanners (an apostrophe in AUTHOR no longer hides a later COPY or REPLACE or
flips quote parity onto a VALUE literal; a COPY inside REMARKS is prose; NIST
SG104A has no phantom `COPY NOT` warning).
`tests/regression/test_sequence_area_tag_header.py` (10 tests, #252) pins a
change tag (`CHG001`) in columns 1-6 of the IDENTIFICATION DIVISION record
through `CobolParser.parse`, `parse_cobol` and `parse_files(workers=1|2)`.
`tests/regression/test_tagged_copybook_comment_hash.py` (14 tests) pins a
`#` in comment lines of a change-tagged copybook (nested COPY, short members,
direct source, free-form `*>`) and the `DIVIDE 10 INTO X` non-anchor.

2026-10-09: `tests/unit/analysis/test_ims_ssa_segment_resolution.py` (10
tests) pins `IMSSegmentAnalyzer` segment names read from an SSA's first 8
bytes across split leaves and nested sub-groups (VALUE, MOVE, qualified
MOVE through a sub-group, unknown leaf -> `None`), and `EXEC DLI
SEGMENT((area))` resolved through the area's VALUE / MOVE.

2026-09-30: `tests/unit/analysis/test_business_rules.py` (73 tests) pins
`BusinessRuleExtractor` against real parses: IF / EVALUATE (subject, TRUE,
FALSE, ALSO, THRU, OTHER) / SEARCH decision tables with unquoted selector
literals re-quoted; nested-rule guards and `rule_id` links; `reached_via`;
`in_dead_code`; validation signals; technical exclusion (FILE STATUS, READ
AT END flag, SQLCODE) and dropped links to excluded rules; arithmetic
formulas incl. GIVING / REMAINDER / INTO; counters skipped; level-88
glossary quoting by PICTURE; report shape; and a smoke run over every
`tests/samples/enterprise/` program. `tests/unit/cli/test_business_rules_cli.py`
(5 tests) pins the `business-rules` subcommand's JSON, text and
`--include-technical` output. `TestNestingAndReachability` also pins
(#354) that `reached_via` covers every paragraph of a `PERFORM ... THRU`
range (stopping at the end paragraph even across a section header) and
every `GO TO ... DEPENDING ON` target.

2026-09-28: `tests/unit/test_exec_sql_fetch_orientation.py` (10 tests) pins
FETCH cursor name / orientation / rowset size for scroll, sensitive and
rowset forms, and a rowset FETCH's cursor in the CRUD matrix.

2026-09-28: `tests/unit/test_exec_sql_host_variable_lists.py` (6 tests)
pins `into_variables` / `using_variables` read from parsed source (no blank
after INTO/USING), indicators kept in the list rather than ending it; a
later commit adds structure-qualified host variables (`:REC.FLD` -> `FLD`),
with a matching `test_dclgen_check.py` case.

2026-09-28: `tests/unit/test_exec_sql_literals_comments.py` (6 tests) pins
EXEC SQL string literals keeping their quotes (no host variable or table read
out of a literal; `''` doubling; `X'..'` prefix) and `--` comments being
dropped (but not `A - -1`); `test_sql_cics_lint.py` gains a quoted CONNECT
credential that spells a declared name.

2026-09-27: `tests/unit/test_exec_sql_merge_cte.py` (6 tests) pins EXEC SQL
`MERGE` (type `MERGE`, target first, then the `USING` table or the tables a
`USING (SELECT ...)` subquery reads, none for `USING (VALUES ...)`) and `WITH`
statements (main verb's type, main SELECT's columns, base tables but never
the CTE names), plus a plain-SELECT guard.

2026-09-23: `tests/unit/test_exec_sql_qualified_tables.py` (8 tests) pins
schema-qualified DB2 names in EXEC SQL: one table per qualified name (no bare
schema), JOINs, three-part names, and the rebuilt `sql_text` keeping
`SCHEMA.TABLE` intact while preserving a space the source really has.

2026-10-04: `tests/regression/test_issue_258_same_named_items.py` (17
tests) pins issue #258: same-named fields in two records and same-named
paragraphs in two sections are kept apart by unused-variables, xref,
dead-code, program-flow, complexity and the flowchart, with
`qualified_name` set only where a name is shared. Tests that had pinned the
old name-merged behaviour (`TestA8SameNamedParagraphs`, the dead-code /
program-flow "duplicate name across top level and section" tests,
program-signature's declared-twice test, xref's duplicate-declarations
test) were updated to the qualified behaviour.

2026-10-14: `tests/regression/test_issue_403_abbreviated_leading_is.py` (13
tests) pins issue #403: an abbreviated leg opening with `IS` (`A > 1 AND IS
< 5`, `IS GREATER THAN`, `IS EQUAL TO`, `IS NOT >`) expands exactly as the
same leg without `IS`, in IF and PERFORM UNTIL.

2026-09-17: `tests/regression/test_audit_2026_09_17_preprocessing.py` (42
tests) pins the nine preprocessing defects of that date's audit: record-only
line splitting (`cobolparser/_lines.py`), EBCDIC NL (0x15) copybook
records, the continued-literal quote discount on stripped copybook content,
text-word / single-pass `COPY ... REPLACING`, parentheses as text words in
`REPLACE`, `>>IF name DEFINED` without `IS`, a non-literal continuation
across a comment line, and the column-72 quotation-mark rule. The last two
are mirrored in `_preprocess_fast.pyx`, so run this file once with the
extensions built and enabled too (`COBOLPARSER_ACCEL=1 python setup.py
build_ext --inplace`, then the file under `COBOLPARSER_ACCEL=1`). See `preprocessing.md`.

2026-09-16: `tests/regression/test_audit_2026_09_16.py` (12 tests) pins the
findings of that date's repo audit. Nine cover `ConstantFolder`'s exactness
machinery, which decided exactness *using inexact decimal arithmetic* in two
places and so could record a value that is wrong: `_exact_divide` proved a
quotient exact by multiplying it back at the same precision the division
used (where the rounding error cannot be represented, so the check always
passed), and `_fits_exactly` scaled with `Decimal` operators running in the
ambient 28-digit context (so an over-precise value was rounded by the very
arithmetic testing it). Both now decide over `Fraction`. Three cover
`config/_yaml.py`'s comment stripper, which advanced one character past a
backslash escape instead of two. See `analysis.md` and `cli.md`.

2026-09-28: `tests/unit/analysis/test_xref.py` (+2: RELEASE FROM / RETURN
INTO roles, reference-modifier offsets on a receiving operand read),
`test_unused_variables.py::TestSortProcedureOperands` (+1) and
`test_crud_matrix.py::TestSortMergeFileAccess` (+1: SORT/MERGE USING/GIVING,
RELEASE/RETURN). See `analysis.md`.

2026-09-27: `tests/unit/analysis/test_xref.py` (+3 tests, one updated:
`ADD 1 TO WS-COUNT` is now read *and* write) and
`test_program_signature.py` (+1) pin arithmetic read/write roles and the
LINKAGE directions derived from them. See `analysis.md`.

2026-10-14: `tests/unit/analysis/test_io_sequence.py::TestSectionLocalParagraphNames`
(4 tests) pins a `SEC-EXIT` in every section: an unqualified GO TO (direct or
conditional) lands on its own section's exit, and `PERFORM SEC-EXIT OF B-SEC`
on the named one (issue #335). See `analysis.md`.

2026-10-14: `tests/unit/analysis/test_io_sequence_perform_summaries.py` (7
tests, #371) pins io-sequence surviving a 1,500-deep PERFORM chain, walking a
2x fan-out 40 levels deep once per level, re-walking a shared range only from
a new file state or recursion-guard context, and reporting a violation once
per location. See `analysis.md`.

2026-10-14: `tests/unit/analysis/test_io_sequence_branches.py` (19 tests)
pins IF/EVALUATE arms being forked and merged in `IOSequenceAnalyzer`
(issue #380): mutually exclusive OPENs, the `CLOSE ... STOP RUN` error exit,
GOBACK/PERFORMed-abend arms left out of the merge, GO TO arms kept (THRU
...-EXIT, queued targets), while violations
that hold on every path are still reported. See `analysis.md`.

2026-09-27: `tests/unit/analysis/test_io_sequence.py::TestGoToReadLoop` (3
tests) pins the READ ... AT END GO TO loop not reporting its file left open,
while a missing/duplicate CLOSE in its exit paragraph still is. See
`analysis.md`.

2026-09-27: `tests/regression/test_doubled_quote_literal_values.py` (3
tests) pins `unquote_literal` inverting `quote_literal`, and generated VALUE
data / folded MOVEs collapsing doubled quotes. See `lexer.md`.

2026-09-27: `tests/unit/analysis/test_move_type_checker.py::TestGroupReceiverAndZeroToAlphabetic`
(4 tests) pins group receivers being exempt from elementary MOVE rules and
`ZERO` → `PIC A` being illegal. See `analysis.md`.

2026-09-27: `tests/regression/test_audit_2026_09_27.py` (22 tests) pins the
audit patch batch: typed VALUE literals keeping their prefix and decoding in
gen-data (`lexer.md`, `parser.md`), the COPY scanner staying linear on long
whitespace runs, and REPLACING growth counting toward `max_total_size`
(`preprocessing.md`).

2026-09-27: `tests/regression/test_copy_replacing_literal_operand.py` (5
tests) pins COPY REPLACING literal operands matching literals (not
identifiers). See `preprocessing.md`.

2026-09-27: `tests/unit/analysis/test_const_fold.py::TestSelfReference` (5
tests, replacing `TestAmbiguousSelfReference`'s two poison assertions) and
`::TestFigurativeZeroAndNational` (2) pin exact folds for operands that are
also targets/GIVINGs, `MOVE ZERO`, and `PIC N` truncation -- every value
checked against GnuCOBOL. See `analysis.md`.

2026-09-27: `tests/unit/generators/data/test_compare.py` (29 tests) and
`tests/unit/cli/test_compare_cli.py` (10 tests) pin the record compare: key vs
positional pairing, ignore by column / field name / group, value vs byte
compare (C vs F sign nibble, slack past the layout), VB records with absent
`OCCURS DEPENDING ON` occurrences, and the CLI's 0/1/2 exit statuses. Every
fixture is a record image from `encode_record`, not a hand-built decode
result. See `generators.md`'s "Record compare".

2026-10-15: `TestHexLiteralBytes` (+12 cases) pins hex-literal bytes keyed by
the literal, not its text (`LiteralCell`): `VALUE SPACE` text next to
`88 VALUE X'20'`, `'AB'` next to `X'4142'` and random text next to `X'41'`
stay charset-encoded, and `decode(encode(row)) == row` for hex-literal fields
in ASCII and EBCDIC across FIXED/VARIABLE/VARIABLE_BARE (#460 review).

2026-10-14: `tests/unit/generators/data/test_encoding.py::TestHexLiteralBytes`
(+10 cases) pins `VALUE X'..'` and level-88 hex witnesses written as their
own bytes in ASCII and EBCDIC, padded/justified/truncated like any text
(issue #319). See `generators.md`.

2026-10-12: `tests/unit/generators/data/test_encoding.py::TestFiller`
(+10 cases) pins a FILLER `VALUE SPACES` / `LOW-VALUES` / `HIGH-VALUES` /
`NULLS` / `ALL SPACES` filling every byte in ASCII and EBCDIC, also through
a generated dataset. See `generators.md`.

2026-09-27: `tests/unit/generators/data/test_layout_offsets.py::TestSynchronizedSlack`
(4 tests) pins `data-items` flagging offsets that unmodelled SYNC slack
could shift. See `generators.md`.

2026-09-27: `tests/unit/generators/data/test_editing.py` (87 tests) pins
numeric-edited record bytes (36 cases checked against GnuCOBOL 3), the
de-edit inverse, and encode/decode round trips in ASCII and EBCDIC.
`test_encoding.py::test_numeric_edited_keeps_its_edit_mask` now asserts the
exact bytes (`- 12.34`) instead of the unedited `-12.34`. See `generators.md`.

2026-09-27: `tests/unit/test_data_items.py::test_edited_picture_sizes` (9
cases) pins edited-picture byte sizes with `B`/`0` insertions and with a `V`
(`Z(3)V99` = 5). See `ast-models.md`.

2026-09-27: `tests/unit/test_jcl.py::TestDummyAndBackwardReferences` (5
tests) pins DUMMY/NULLFILE reading no dataset, DSN/DUMMY/SYSOUT overrides
replacing each other, and `DSN=*.` backward references landing in
`unresolved`. See `jcl.md`.

2026-09-27: `tests/unit/test_config_yaml.py` +3 tests pin the indentless
block sequence (`key:` then `- item` at the key's own column) as a mapping
value, ending at the parent's next key; it used to be rejected. See `cli.md`.

2026-09-15: `tests/regression/test_copybook_suggestion_pool.py` (4 tests)
pins `suggest_similar_copybooks`'s narrowed did-you-mean candidate pool
(`.cpy`/`.CPY` only by default, via a new `suggestion_extensions`
parameter) -- a missing copybook must never suggest the referencing
program's own `.cbl` file back. See `preprocessing.md`'s "Copybook Path
Resolution" section.

2026-09-05 (part 3): `TestBothMechanismsAtOnce` in the same file, after a
Copilot review on PR #204 found the "table decides" rule documented but not
implemented -- a record declaring *both* an ODO table and an FD
`RECORD VARYING` range had the FD-drawn length cut on top of the ODO
trimming. The class pins every surface agreeing: no length drawn for such a
record, `minimum_record_length()` taking the layout's floor rather than the
FD's, `record_lengths()` still summing to the bytes `to_records()` writes,
the hex dump reporting the layout's span while still printing the FD clause
as metadata, and a `data_length` passed *directly* to `encode_record` /
`row_record_length` being ignored for an ODO layout but still honoured
without one. `TestOdoLayout` also grew two bounds tests: disjoint ranges for
one counter collapse to the tightest maximum (over-counting names bytes the
record does not have), overlapping ones still intersect.

2026-09-05 (part 2): the same file grew `TestFdRecordVarying` and
`TestExplicitVaryingRange` for the FD `RECORD VARYING` mechanism, which no
`OCCURS DEPENDING ON` walk can see — the record is flat and the length lives
in the RDW. The former works mainframestechhelp.com's `EMPVL` example end to
end (the FD clause picked up with no flag at all, every drawn length inside
47..80, the cut falling mid-`EMP-COMMENT`, the RDW carrying it, and a seed
reproducing the lengths); the latter covers
`DataGeneratorOptions.record_varying` for a copybook that has no FD, its
clamping to the record's real length, and the degenerate equal-bounds case
-- each now also pinning the caveat it reports (#274), plus an FD range past
the record and the hex VALUE column's `(cut N/M bytes)`.
`tests/unit/cli/test_gen_data_cli.py::TestRecordVaryingFlag` covers the
`--record-varying` flag, `MIN-MAX` as well as `MIN:MAX`, malformed ranges,
an out-of-range one warning on stderr and in the hex header (#274),
and that passing it alone resolves to `auto` while an explicit
`--record-format fixed` still wins. That last point is why
`TestRecordFormatFlag::test_the_default_is_fixed` now asserts the *resolved*
format rather than the parsed one: argparse's default had to become `None` to
stay distinguishable from an explicit `fixed`.

2026-09-05: `tests/unit/generators/data/test_variable_length.py` (56 tests)
covering fixed- vs variable-length record generation end to end --
`OdoControl`/`odo_counter_bounds` linking (including a `max_occurs` cap
narrowing the bounds and a declared `OCCURS 0 TO n` keeping its zero),
`present_indexes` trimming (the field declared *after* the table has to
shift up; IBM complex ODO trims each outer occurrence by its own counter),
generated counters staying inside the table's bounds even under
`unique_fields`, RDW framing and its 0xFFFF ceiling, the length trio, and
format-dependent caveats. Its load-bearing invariant is the one tying both
readings together: a full-count `variable-bare` record is byte-for-byte the
`fixed` record. `tests/unit/cli/test_gen_data_cli.py::TestRecordFormatFlag`
(11 tests) covers the `--record-format` flag, walking the written file's RDW
chain and asserting it lands exactly on EOF. The two additive `FieldSpec`
keys are pinned in
`tests/contracts/test_copybook_data_generator_contract.py`'s
`_FIELD_SPEC_KEYS`; `tests/regression/test_fixturedemo_golden.py`'s golden
bundle was regenerated for them (no generated value changed).
2026-09-05 (repo audit): `tests/test_all_samples.py` collected **zero
tests**. It held only `run_sample_tests`-style helper functions -- none
named `test_*` -- even though the project documents it as the file that
"smoke-tests all sample COBOL programs". Nothing checked `tests/samples/`
as a corpus at all, and that gap had let real fixture rot through: **32
lines across 13 sample programs ran past column 72**, the end of Area B in
fixed-format COBOL -- 30 of them carrying real code or comment text, the
other two only trailing spaces. `normalize_fixed_format` discards columns 73+ exactly
as a compiler does, so the truncation was silent -- the parser saw
`WS-EXCEPTION-MSG` as `WS-EXCEPTION-M`, data items lost their terminating
period, and `complex_data_structures.cbl` had an unterminated literal that
failed to parse outright. Those samples feed the wider suite, so thousands
of tests were asserting against programs that were not the programs on
disk. All 32 lines are fixed (dedented, wrapped, or -- for comment banners
-- shortened; no token changed), and `TestSampleCorpus` now pins both the
cause and the effect: `test_sample_respects_fixed_format_columns` and
`test_sample_parses_without_errors`, each parametrized over every `*.cbl`
under `tests/samples/` (48 programs, 96 tests). The column test fails only
on **non-whitespace** past column 72 and reports the discarded text rather
than a line length (Copilot review, PR #205): trailing spaces there are
discarded too, but discarding them changes nothing, and failing on them
would make the test hostage to whichever editor last touched the file. `EXPECTED_PARSE_ERRORS`
documents the two samples that are meant to fail --
`error_recovery_tests.cbl` (purpose-built malformed input) and
`special_names_config.cbl` (a non-ASCII `¥` currency symbol the lexer
rejects) -- so anything else reporting an error is a regression, in the
parser or in the fixture. The runner helpers are kept.

2026-09-05: `tests/regression/test_data_fast_signature_drift.py` (8 tests)
pinning the `_data_fast` signature-drift guard. A compiled extension older
than its caller (18 parameters vs the 19 `data_clauses.parse_data_item`
passes -- seen on Python 3.14) used to raise `TypeError` inside every
data-description entry, which the division loop recovered from by abandoning
the division: every program with a DATA DIVISION degraded to a near-empty AST.
The tests cover the import-time probe accepting the real extension, rejecting
a stale 18-parameter stand-in (message must name `build_ext`), a full parse
still yielding all three divisions and both PICTURE clauses on the fallback,
byte-identical ASTs with and without the fast path, `_DATA_FAST_ARG_COUNT`
matching the compiled extension's real arity, and a *missing* extension
staying silent (a normal pure-Python install, not a misconfiguration).
Two more came out of self-review: `test_import_survives_warnings_as_errors`
runs a subprocess under `-W error` (the report must go through `logger`, not
`warnings.warn`, or a stale build breaks `import cobolparser` outright), and
`test_arg_count_constant_matches_the_real_call_site` parses `data_clauses.py`
with `ast` to count the literal call's arguments — the constant is a third
copy of the arity and nothing else pins it to the call it guards.
The extension-dependent tests `importorskip` `cobolparser._data_fast`.

2026-08-26: `tests/regression/test_tagged_sequence_area_detection.py`
grew five review-hardening pins for the change-tag detection fix: a
120-line banner must not exhaust the Area A anchor scan, an identifier
merely prefixed by a header string (`PROGRAM-ID-VAL`) must not anchor
rule 2, `preprocess_fixed=False` alone skips the normalization
preprocessor (comment-line marker text reaches the token stream),
`_tokenize_source(free_form=True, preprocess_fixed=True)` normalizes
like `parse_cobol`, and a forced-fixed layout survives the
unterminated-literal recovery deferral with the diagnostic recorded.
`tests/unit/cli/test_source_format_flag.py` re-pins `--free-form` as the
legacy *advisory* flag (auto-detection may still normalize -- numbered
and tagged members parse cleanly under it; only `--source-format=free`
hard-disables) and adds `preprocess` auto-detection pins (free-form
input passes through untouched by default; `--source-format=fixed`
still forces).

2026-10-14: New `tests/unit/test_perform_until_newline.py` (19 tests,
issue #347) -- a PERFORM UNTIL condition ending at a line break, in the
out-of-line, inline and VARYING forms: bare condition-name, `( A > 5 )`,
a parenthesised OR, `NOT cond` and a class test each get a real condition
tree; the line-break form matches the period form; and the READ/AT END/EOF
flag idiom yields a `SequenceConstraint`. See [parser.md](parser.md).

2026-08-24 (second entry this date): New
`tests/regression/test_corpus_residual_findings.py` (10 tests) pinning a
follow-up 105-program corpus sweep's four residual findings -- see
[parser.md](parser.md)'s "Residual corpus findings" section:
`TestNextSentenceStatement` (NEXT SENTENCE in an IF THEN-branch and an
EVALUATE WHEN, confirming the condition text isn't corrupted and a real
`NextSentenceStatement` node is produced), `TestPerformWithTestNewlineTolerance`
(WITH TEST BEFORE/AFTER split across continuation lines in all three
PERFORM forms -- inline UNTIL, out-of-line, and VARYING), `TestDisplaySubscriptOnContinuationLine`
(a DISPLAY item's subscript wrapped onto its own line, plus a guard that
an unrelated next item on its own line isn't mistaken for one), and
`TestQualifierFoldingOnWriteReadStart` (WRITE's FROM source, READ's INTO
target, and START's KEY name all folding an OF-qualified operand). Also +2
in `tests/regression/test_normalize_column_overflow_warning.py`'s new
`TestBareTerminalPeriodDoesNotWarn` class (see
[preprocessing.md](preprocessing.md)), plus the new
`NextSentenceStatementParser` registration threaded through the existing
self-maintaining registry fixtures/parametrizations in
`tests/regression/test_swallow_sweep.py` and
`tests/unit/test_procedure_registry_dispatch_order.py` (new `FIXTURES`
entry, `EXPECTED_ORDER` position, and `DISPATCH_CASES` case).

2026-08-23 (second entry this date): the three corpus-retry regression
files grew review-pass hardening classes -- see [parser.md](parser.md)
and [preprocessing.md](preprocessing.md):
`test_occurs_clause_line_splits.py` is now 11 tests
(+`TestOccursMissingCountRecovery` -- a malformed OCCURS with no count
must not swallow the next item's level number; `TestDependingOnLineSplit`;
`TestSignClauseLineSplit`); `test_perform_varying_signed_values.py` is now
9 tests (+`TestSignSplitAcrossLines` -- sign and digits straddling a
72-column break; `TestSubscriptedFromByValues`; `TestSetSignedValues` --
`SET ... DOWN BY -1`/`UP BY +2`/`TO -1` through the shared
`consume_signed_numeric`); `test_expansion_width_and_tags.py` is now 13
tests (+`TestReviewPassRefinements` -- wrap break allowed at exactly
column 72, `total_lines` recounted after a wrap, short flush-left code
lines like `01 A.`/`EXIT.`/`EJECT` surviving `strip_sequence_area`'s
narrowed tag heuristic).


2026-08-23: Three new regression files pinning the second mainframe-corpus
retry's remaining warning buckets — see [parser.md](parser.md) and
[preprocessing.md](preprocessing.md) for the fixes:
`tests/regression/test_occurs_clause_line_splits.py` (8 tests: OCCURS
count/TO/BY line splits, comma-separated INDEXED BY and KEY name lists,
bare `INDEX` usage — all realistic 80-column deck lines with sequence
numbers and identification stamps);
`tests/regression/test_perform_varying_signed_values.py` (4 tests: signed
FROM/BY values — `BY -1` countdown loops, negative FROM, a signed AFTER
dimension, `+`-prefixed BY); and
`tests/regression/test_expansion_width_and_tags.py` (10 tests: REPLACING
column overflow squeezed/wrapped back within column 72 by
`_fit_fixed_format_width` including quote-safety, the unbreakable-line
escape hatch, and a termination pin for the short-head/unbreakable-tail
shape whose first fix looped forever, plus columns-1-6 change-tag lines
blanked by `strip_sequence_area` with line numbering preserved).

2026-08-22 (third entry this date, updated across four `/code-review`
passes): `tests/regression/test_arithmetic_qualifier_chain.py` (11 tests)
pinning the fix for ADD/SUBTRACT/MULTIPLY/DIVIDE dropping a qualified
target/operand's `OF`/`IN` chain -- see [parser.md](parser.md). Covers: a
single `OF` qualifier on an ADD target, a multi-hop chain split across a
continuation line (the corpus repro shape), SUBTRACT's `FROM` target,
MULTIPLY's operand, DIVIDE's operand with a subscript *before* the
qualifier (`QUAL-TBL (IDX) OF GROUP-A` -- corrected by the second review
pass from a backwards `QUAL-TBL OF GROUP-A (IDX)` that "passed" only
because the parser's lenient concatenation doesn't enforce COBOL's
subscript-binds-to-its-immediate-identifier grammar), the `GIVING` clause
(shared by all four verbs) and DIVIDE's `REMAINDER` clause
(`TestGivingAndRemainderQualifierChain`, added once the first review pass
caught these two call sites still dropping the chain after the initial
fix), ADD's/SUBTRACT's leading addend list before `TO`/`FROM`
(`TestAddendListQualifierChain`, added once the first review pass caught
it splitting a qualified addend into two spurious separate addends instead
of just dropping the qualifier), and malformed-input handling
(`TestMalformedQualifierChainInput`, added once a fourth review pass
caught a dangling `OF`/`IN` with no identifier following it being consumed
and discarded rather than left untouched, and an unbalanced `(` in a
subscript running past the malformed statement's own period and devouring
every statement after it). The same fourth pass also added a sibling file,
`tests/regression/test_move_qualifier_chain.py` (4 tests), pinning the
identical qualifier-chain bug found live in MOVE's target-collection loop
-- a distinct call site the arithmetic-verb fix never touched, since MOVE
is a different statement parser (`move_parser.py`) with its own bespoke
target loop.

2026-08-22 (second entry this date): New
`tests/regression/test_tier8_arithmetic_scope_terminator.py` (9 tests)
pinning the fix for ADD/SUBTRACT/MULTIPLY/DIVIDE/COMPUTE never consuming
their own explicit scope terminator (`END-ADD`, `END-SUBTRACT`,
`END-MULTIPLY`, `END-DIVIDE`, `END-COMPUTE`) — see [parser.md](parser.md).
Left unconsumed in the stream, the terminator (a plain `IDENTIFIER`, no
dedicated `TokenType`) was misread by the procedure division's
paragraph-boundary lookahead as a new paragraph header, silently reparenting
every following statement under it. One test per verb, plus: no-trailing-
period termination (`END-ADD` alone is a valid terminator), an ON SIZE ERROR
/ NOT ON SIZE ERROR clause followed by the terminator, and a period-only
control to confirm the pre-existing path is unaffected.

2026-08-22: New `tests/regression/test_version_tag_line_handling.py` (7
tests) for `normalize_fixed_format`'s new `version_tag_lines_as_comments`
handling (see [preprocessing.md](preprocessing.md)) -- 'V'/'v' in the
fixed-format indicator column (column 7) is now treated as a comment,
matching a real shop's change-control version-tag convention (e.g. `V97`,
`TFEC` stamped into Area A) that previously reached the lexer as live
source and surfaced as "Unparsed tokens" errors. Covers: dropped by
default (upper- and lowercase), kept as code with
`version_tag_lines_as_comments=False`, line-number preservation across
dropped V-lines, `copy_statement_parser.is_comment_line()` parity, fast/pure
(`_preprocess_fast`) parity, an end-to-end `parse_cobol()` repro of the
original interleaved-V-lines shape parsing error-free, and (caught in PR
review) `lexer.py`'s `_fixed_format_comment_tokens` -- the
`tokenize_cobol(..., keep_comments=True)` helper that reconstructs COMMENT
tokens for lines `normalize_fixed_format` blanks out -- which only
recognized `*`/`D`/`d` (plus `/` for page breaks) in its own re-scan of the
physical lines; a V-line's blank placeholder in the normalized text had no
matching re-scan entry, desynchronizing every later comment/blank pairing
by one and misattributing the next real comment to the V-line's line
number. Fixed alongside (same file, `lexer.py`) and pinned by
`TestVersionTagCommentTokenPreservation`.

2026-08-21 (second entry this date): +11 in
`tests/regression/test_real_corpus_parse_failures.py` (23 total in the
file), pinning a second
controlled re-probe's four fixes (see [parser.md](parser.md) and
[lexer.md](lexer.md)): `TestSecondOperandOnContinuationLine` (MOVE/OPEN's
second-or-later operand on its own continuation line, plus a guard that a
genuinely dedented next paragraph is still caught as a boundary),
`TestDigitLedHyphenatedProcedureNames` (`43E00-PROD`-shaped and
`22310-01-TRAITE`-shaped paragraph names, plus a guard that plain
scientific-notation literals like `5E10`/`5E+5`/`5E-3`/`1.5E10` are
unaffected), `TestSetSubscriptedValue` (all four of SET's value-reading
branches — plain `TO`, `TO ADDRESS OF`, `UP BY`, `DOWN BY` — with a
subscripted value), and `TestEmbeddedSqlNotSignOperator` (`¬=` inside
`EXEC SQL` no longer crashes the parse).

2026-08-21: New `tests/regression/test_skip_statement.py` (7 tests) for
`SKIP1`/`SKIP2`/`SKIP3` compiler-directing listing no-ops — mirrors
`test_eject_statement.py`'s scenarios for the same class of statement:
trailing-period paragraph-split guard (`SKIP1.` between two paragraphs must
not create a bogus paragraph), a real user-named paragraph immediately
followed by a bare `SKIP2.` statement, no-period marker survival
(`SKIP3` with no trailing period must not swallow the following
statement), back-to-back directives across all three variants, AST node
`to_dict()` shape plus each variant's own `lines` count via
`find_all_by_type("SkipStatement")`, and COPY-expansion parity. Written
after confirming via direct repro that `SKIP1`/`SKIP2`/`SKIP3` already
parsed correctly in every one of these scenarios (they already had their
own `TokenType`s and a registered `SkipStatementParser`) — the accompanying
production change in [parser.md](parser.md) closes a related
defense-in-depth gap (`STATEMENT_TOKEN_TYPES`/`STATEMENT_KEYWORDS` parity
with `EJECT`) rather than fixing an observed misparse.

2026-08-17 (review follow-up on the entry below): +3 in
`tests/unit/analysis/test_unused_variables.py`'s `TestEvaluateSubjects` —
`test_subjects_reach_operands_and_public_lookup` (evaluate_parser now
routes subjects through `add_subject()`, so they land in `.operands` and
`find_statements_using_variable` sees them),
`test_when_selector_only_variable_not_reported` (a data-name referenced
only as a WHEN selector arrives as a `Literal`-typed selector dict —
`_selector_identifiers` now scans those; previously falsely reported
unused), and `test_expression_subject_walked_structurally` (programmatic
`CobolExpression` subject via `add_subject()` — the analyzer's explicit
subjects walk is its only coverage, and the opaque-expression fallback
must scan every operand, not just `operands[0]`). Both parsed-source
tests from the 2026-08-16 entry also gained a deliberately-unused
`WS-DEAD` positive-control item asserted to BE reported, so their
negative assertions can no longer pass vacuously if a parser regression
drops the declarations. Note: the entry below describes `add_subject()`
as "the setter that would otherwise reach `.operands`" — accurate only
for string subjects; a `CobolExpression` subject goes to `add_child()`,
never `add_operand()`. Brings the file to 35 tests.

2026-08-16 (unused-variable-function review): +2 in
`tests/unit/analysis/test_unused_variables.py`'s new `TestEvaluateSubjects`
class — `test_single_subject_marks_variable_used` and
`test_also_joined_subjects_all_marked_used` pin the fix for a false
positive found while reviewing `UnusedVariableAnalyzer`: a field
referenced only as an `EVALUATE` subject (`EVALUATE WS-CODE` /
`EVALUATE WS-A ALSO WS-B`) was reported unused because
`evaluate_parser.py` appends subjects straight to
`EvaluateStatement.subjects`, bypassing `add_subject()` (the setter that
would otherwise reach `.operands`), and the analyzer's `EvaluateStatement`
branch only special-cased `WHEN` selectors, not the subject itself. See
[analysis.md](analysis.md)'s `UnusedVariableAnalyzer` entry. Brings the
file to 32 tests (was 30 after the 2026-08-13 Copilot-review fix below).

2026-08-15 (lint fix, PR #153): `black==26.3.0` reformatted
`cobolparser/preprocess/__init__.py`,
`tests/regression/test_fixed_format_word_boundary_overflow.py`, and
`tests/regression/test_normalize_column_overflow_warning.py`
(whitespace-only, CI's `lint` job caught it — no behavior change).

2026-08-15 (Copilot review fix, PR #153): +1 in
`tests/regression/test_fixed_format_word_boundary_overflow.py`'s new
`TestInitialWarningsConsumedOnce` class —
`test_initial_warnings_apply_only_to_the_first_parse_call` pins that
`CobolParser(initial_warnings=...)` (see the entry directly below) is
consumed after the first `parse()` call rather than re-applied on every
call; reusing one `CobolParser` instance for a second, unrelated source no
longer repeats the first source's pre-construction normalization
warnings. See [parser.md](parser.md).

2026-08-14 (fixed-format column-72 overflow wiring): +2 new tests in
`tests/regression/test_normalize_column_overflow_warning.py`'s
`TestWordBoundaryOverflowWarns` class (word-boundary overflow past column
80, e.g. the `OCCURS ... DEPENDING ON` case) plus 2 more pinning the
sequence-number gate (`test_numeric_sequence_area_does_not_warn_even_when_mid_token`
/ `test_blank_sequence_area_with_same_shape_still_warns`, isolating a real
numeric sequence number in columns 1-6 as the deciding factor against a
false-positive class found in the vendored NIST corpus). New file
`tests/regression/test_fixed_format_word_boundary_overflow.py` pins the
diagnostic end-to-end through both `parse_cobol()` and
`CobolParser.parse()` — `ParseResult.warnings` now actually surfaces it,
and it stays a warning (not a hard error) under `FAIL_FAST`. See
[preprocessing.md](preprocessing.md)'s "Column 73+ overflow warning"
section for the full three-rule writeup and the corpus measurements this
change is based on. One dormant real hit surfaced by wiring the
(pre-existing) mid-token rule into the live pipeline for the first time:
`tests/unit/test_unstring_gaps.py::TestUnstringCombined::
test_full_combined_statement` had a 73-column fixture line silently
dropping a trailing comma with zero effect on the test's own assertions —
fixed by trimming one space of indentation, not by loosening the check.

2026-08-14 (follow-up fix, misnested level-77 as only child): +1 in
`tests/unit/generators/data/test_layout_offsets.py`'s
`TestComputeProgramDataItems` class —
`test_a_77_level_item_that_is_a_records_only_child_is_recovered_as_its_own_record`
reproduces `01 WS-REC. 77 WS-CTR PIC 9(4) COMP.` (no intervening `05`,
so the misnested 77 is `WS-REC`'s *only* AST child) via
`compute_program_data_items()`. Pins the narrower gap the final-review
fix wave below left unhandled: pins `WS-REC`'s own childless-root
reporting (`is_group=False`, `byte_length=0`) as the accepted baseline
for this degenerate shape, and asserts `WS-CTR` is recovered as its own
top-level record (`byte_length=2`, COMP `<=4` digits) instead of being
silently dropped. See [generators.md](generators.md)'s `layout_offsets.py`
entry for the `_find_misnested_level_77_items()` fix.

2026-08-14 (final-review fix wave, root-level 88s): +2 in
`tests/unit/generators/data/test_layout_offsets.py`'s `TestLevel88`
class — `test_root_level_condition_names_are_not_dropped` (01-level
record root with two directly-attached 88s, the `WS-EOF-FLAG`/`WS-EOF`/
`WS-NOT-EOF` flag idiom) and
`test_root_level_condition_names_under_a_77_level_record_are_not_dropped`
(same shape under a 77-level root, since 77-level records go through the
same root-construction path in `compute_record_layout()`). Both pin the
final-review fix for a whole-branch review finding that the record root
silently dropped its own direct level-88 condition names — see
[generators.md](generators.md)'s `layout_offsets.py` entry.

2026-08-14 (final-review fix wave, misnested level-77): +1 in
`tests/unit/generators/data/test_layout_offsets.py`'s
`TestComputeProgramDataItems` class —
`test_a_77_level_item_after_a_record_does_not_corrupt_the_preceding_records_length`
reproduces `01 WS-REC. 05 WS-A PIC X(3). 77 WS-CTR PIC 9(4) COMP.` via
`compute_program_data_items()` (not `compute_record_layout()` directly —
the bug is in how the section walk classifies items, confirmed by first
printing the actual AST: the parser nests `WS-CTR` as a child of `WS-A`,
not as a section-level sibling of `WS-REC`) and asserts `WS-A`'s
`byte_length` stays `3` (its own `PIC X(3)`, not swallowed into a
misclassified GROUP) and `WS-REC.byte_length` likewise stays `3`. See
[generators.md](generators.md)'s `layout_offsets.py` entry for the fix.

2026-08-14 (Task 9): +6 in `tests/unit/cli/test_new_subcommands.py`'s new
`TestCmdDataItems` class (following `TestCmdIoSequence`'s shape:
report-dict shape, compact output, `--output` file redirection, a
parse-failure exit, plus a dedicated `test_outputs_items_and_unresolved_keys`
pinning `_emit_report`'s `source_file`/`program_id` splice against a
two-item WORKING-STORAGE fixture), wiring the new `data-items` CLI
subcommand (`_cmd_data_items`, added to `_SUBCOMMANDS`) that exposes
Task 8's `compute_program_data_items()` (see [generators.md](generators.md)
and [cli.md](cli.md)'s "Data-Items" entry). Also added `"data-items"` to
the existing `TestNewSubcommandsRegistered` and
`TestNewSubcommandsOutputSilent` parametrized subcommand lists for the
same registration/`-o`-silences-stdout coverage the other five analyzer
subcommands already get.

2026-10-15 (issue #328): +7 in new `tests/unit/cli/test_profile_output_flags.py` (`--profile-output` alone writes the `.prof` and embeds `profiling` for `parse`, `dead-code` and `batch`; a non-default `--profile-top-n` alone turns profiling on; no flag still means no `profiling` key; a single-file `--profile-output` naming a directory, and a batch one naming a regular file, are one-line `error:`s with exit 1). Failed before the fix (flags ignored; `IsADirectoryError` / `FileExistsError` tracebacks).

2026-10-15 (issue #327): +4 in new `tests/unit/cli/test_gen_fixtures_cli.py::TestGenFixturesInvalidOptions` (`gen-fixtures --rows -1`, `--max-occurs 0`, `--max-occurs -1`, and `data: {rows: -5}` in a discovered `cobol.yml` each exit 1 with exactly one `error:` line). Failed before the fix (the `ValueError` from `DataGeneratorOptions` escaped).

2026-10-15 (issue #326): +1 in new `tests/unit/cli/test_jcl_cli.py::TestMissingJclParser` (with `jclparser` blocked in `sys.modules`, `jcl` exits 1 with a one-line `error:` carrying the `pip install 'cobol-parser[jcl]'` hint and no traceback). Failed before the fix (the `ImportError` escaped).

2026-10-14 (issue #397): +4 in new `tests/unit/analysis/test_technical_debt.py::TestParseErrorsWithholdTheGrade` (no parse errors keeps the grade and an empty `caveats`; `parse_error_count=4` sets `grade` to `None` with one caveat naming the count; the score is unchanged; `to_dict()` serializes all three) and +3 in new `tests/unit/cli/test_complexity_health_subcommands.py::TestHealthWithParseErrors` (`health` on a non-COBOL file emits `"grade": null`, a nonzero `parse_error_count` and a caveat, still reports a float score and exits 0; a clean sample keeps a letter grade). The CLI tests failed before the fix.

2026-10-13 (issue #291): +4 in new `tests/unit/analysis/test_move_type_checker.py::TestIntrinsicFunctionsWithArguments` (every `MOVE FUNCTION x(...)` form in a parsed program is checked -- spaced args with an `OF` qualifier and TRIM's `LEADING`, subscripted args, quoted literal args, `CURRENT-DATE(1:8)` and a reference-modified result; NUMVAL into `PIC A` and a non-integer MAX into `PIC X` are errors; an unresolved TRIM argument is an ordinary unresolved operand; NATIONAL-OF and an uncatalogued name count in `unresolved_function_count`), and +2 in `tests/unit/analysis/test_lint.py::TestCaveats` (no caveat for a checked function source; an uncheckable one gets its own caveat without the `--copybook-path` hint). All failed before the fix. Review follow-up: +2 in `TestNumericFunctionIntegerness` (SUM / REM / RANGE of integers into `PIC X` are clean; NUMVAL, SUM with a `V99` argument and MAX over a nested NUMVAL into `PIC X` are function caveats, not ERRORs; NUMVAL into `PIC A` stays an ERROR; UPPER-CASE of a `PIC N` item is unresolved) and +1 in `TestCaveats` (an unresolved COPY operand and a function caveat together give two separately worded caveats). Round 2: `TestNumericFunctionIntegerness` also pins one argument rule for SUM / MAX (a `V99` or COMP-2 argument into `PIC X` is an ERROR for both) and counts UPPER-CASE / TRIM of a `PIC N` item as function caveats, not missing COPYs.

2026-10-05 (issue #273): `tests/unit/test_models.py` -- `test_ast_from_json_roundtrip` now compares `to_dict()` and asserts no warning for a statement-free program; +1 `test_from_json_restores_structure_and_warns_about_statements` (parsed program: dict equal with paragraph statements emptied, `LossyDeserializationWarning` with the dropped count); +3 in new `TestNodeEquality` (unrelated programs not equal, reparse equal, source position ignored). The existing `from_json` tests in `test_program_model_branches.py` / `test_bug_hunt_r12_misc.py` now expect the warning.

2026-10-14 (issue #359): +5 in `test_decoding.py` (`test_fixed_newline_*`: a short line under RECFM=F + newline is a record error for the missing separator and the separator inside DISPLAY text, well-formed lines with or without a final newline stay clean, a 0x0A inside COMP data is not flagged, and the check frames on the base view whatever view is read). The first two failed before the fix.
2026-10-13 (issue #296): +3 in `test_views.py` (overlay inside OCCURS placed at every occurrence, a shorter overlay padded with FILLER, a nested overlay read through its enclosing one), +1 in `test_decoding.py` (`decode --view` on an overlay inside OCCURS reads both occurrences), +1 in `test_compare.py` (a compare through an overlay view keyed on a field outside it). Existing overlay assertions updated for the whole-record view shape.
Review follow-up on #306: +3 in `test_views.py` (an overlay before a DEPENDING ON table is not flagged ambiguous, base columns keep their names in an overlay view, overlay views are built only when read), +2 in `test_decoding.py` (an overlay of an ODO counter still sizes the table under RECFM=V, a wider overlay reads the field after it); `test_audit_2026_09_07.py`'s wider-REDEFINES framing length is now 10, matching `data-items`.
Round-2 review on #306: `test_views.py` +1 (`dataclasses.replace()` on a lazy overlay view), `test_decoding.py`'s ODO-counter overlay test also asserts no false "not part of the record" caveat, and `test_decode_cli.py`'s `--list-views` test checks `length` / `overlay_length`.

2026-10-04 (issues #247, #248): +3 in `tests/unit/generators/data/test_layout_offsets.py`'s `TestOccursDependingOn` (`test_group_holding_an_odo_table_reports_its_maximum_length`, `test_direct_odo_child_counts_its_maximum_in_the_record_length`, `test_odo_record_length_agrees_with_the_encoder` -- an ODO table's footprint is its maximum, so group/record `byte_length` equals `GeneratedDataset.record_length()`), and +5 at the end of `tests/unit/generators/data/test_decoding.py` (an ODO counter below/above its range is a field error, leftover RDW body bytes are a record-level error, a well-formed VB record stays clean, a `B`/`D` sign nibble on unsigned COMP-3 is an error and does not negate, a COMP value wider than its PICTURE is a TRUNC caveat). All failed before the fixes.

2026-08-14 (Task 8): +1 in `tests/unit/generators/data/test_layout_offsets.py` (new `TestComputeProgramDataItems` class) and +2 new test classes in new `tests/integration/test_data_item_layout_corpus.py`, for the new `compute_program_data_items()` program-wide entry point (see [generators.md](generators.md)'s `layout_offsets.py` entry). The unit test walks a two-record WORKING-STORAGE section and confirms both records' items land in `output["items"]` with independently 0-based offsets, plus the always-present `unresolved` key. The integration test's `TestRedefinesFixture` corrects a wrong assumption in this task's own brief: the brief guessed `tests/samples/redefines_test.cbl` contained a 3-way REDEFINES chain (`WS-REDEF-2 REDEFINES WS-REDEF-1 REDEFINES WS-BASE-AREA`); the real fixture (lines 16-21) is a fan-out — `WS-REDEF-1` and `WS-REDEF-2` both redefine `WS-BASE-AREA` directly — so the test asserts `redefines_chain == ["WS-BASE-AREA"]` for both, all three at `byte_offset == 0`. This also exercises the Task 8 top-level-REDEFINES fix: without it, `WS-REDEF-1`/`WS-REDEF-2` would report an empty `redefines_chain` despite genuinely redefining a section sibling (`compute_record_layout()`'s record-root `LayoutItem` hardcodes `redefines_chain=[]` since it has no visibility into section-level siblings). `TestShamriceCorpusDoesNotRaise` sweeps `examples/cobol/shamrice/*.cbl` for crash-free coverage only. The brief's Step 5 code sample also had a bare `ErrorRecoveryMode.RECOVER`, which does not exist on the enum (`FAIL_FAST`/`COLLECT_ALL` are the only members) — corrected to `COLLECT_ALL` to match every other corpus-sweep test in this suite.

2026-08-14 (Task 7): +2 in `tests/unit/generators/data/test_layout_offsets.py` — new `TestLevel88` class pinning per-condition-name level-88 value expansion: `test_each_condition_name_gets_its_own_entry_with_its_own_values` verifies that each level-88 condition name gets its own `LayoutItem` entry with its own `condition_values` list (no merging/leaking across conditions), and `test_thru_range_expands_on_a_level_88_entry` verifies THRU ranges expand (VALUE 2 THRU 4 → ["2", "3", "4"]) on level-88 entries. Both tests pass against existing behavior: Task 2's `_layout_item()` already emits a `LayoutItem` per `ConditionNameItem` child using `expand_condition_values(cond.values)`, so no production changes needed. Confirms the per-condition-name value semantics are distinct from `layout.py`'s merged `_condition_values` approach.

2026-08-14 (Task 6): +4 in `tests/unit/generators/data/test_layout_offsets.py` — new `TestOccursDependingOn` class: the brief's `test_odo_table_itself_has_a_known_offset` and `test_everything_after_an_odo_table_is_flagged_ambiguous` pin single-level OCCURS DEPENDING ON behavior (the ODO table itself keeps a concrete offset; a direct sibling after it is `offset_ambiguous=True`/`byte_offset=None`; the record root stays `offset_ambiguous=False`). Two new tests cover the cross-level propagation gap Task 5's reviewer found: `test_odo_nested_inside_a_group_makes_the_groups_own_siblings_ambiguous` (ODO nested one level inside a group — the group's own *sibling*, not just the ODO's own siblings, must go ambiguous) and `test_odo_two_levels_deep_propagates_through_both_nesting_hops` (ODO nested two levels deep — both the one-hop and two-hop siblings must go ambiguous, proving propagation isn't limited to a single level). Verified via a stash-based revert of the `layout_offsets.py` fix that the nested-group test genuinely fails without it (`AFTER-GROUP` wrongly reported a concrete offset). Pins Task 6's `(footprint, trailing_ambiguous)` tuple threading through `_layout_siblings()`/`_layout_item()` — see [generators.md](generators.md)'s `layout_offsets.py` entry. Note: fixed-format COBOL's column-72 code-area limit means `OCCURS ... DEPENDING ON <var>` fixtures at deep indentation must wrap the `DEPENDING ON` clause onto a continuation line, or the lexer silently drops it past column 72 with no error.

2026-08-14 (Task 5): +2 in `tests/unit/generators/data/test_layout_offsets.py` — new `TestOccurs` class: `test_elementary_occurs_reports_one_occurrence_length_but_advances_past_all` verifies an elementary OCCURS item's `byte_length` stays one occurrence's size while a later sibling's offset advances past all occurrences, and `occurs` reports `{"min": N, "max": N}`; `test_group_occurs_multiplies_the_whole_group_footprint` verifies the same for a *group* item's own OCCURS (its `byte_length` is one occurrence's footprint, but a later sibling's offset advances past every occurrence of the whole group). Pins Task 5's OCCURS-aware `slot_footprint` computation in `_layout_siblings()` and the `occurs` field wiring in `_layout_item()`.

2026-08-14 (Task 4): +2 in `tests/unit/generators/data/test_layout_offsets.py` — new `TestRedefines` class: `test_redefines_shares_offset_and_advances_past_the_larger_alternative` verifies a REDEFINES slot shares its base offset and the running offset advances past the *larger* alternative, not the base item; `test_three_way_redefines_chain_is_reported_in_order` verifies a multi-hop REDEFINES chain (A redefines B redefines C) is reported oldest-target-last (`["WS-REDEF-1", "WS-BASE"]`) and every chain member shares offset 0. Pins Task 4's slot-based `_layout_siblings()` rewrite in `layout_offsets.py`.

2026-08-14 (Task 3): +1 in `tests/unit/generators/data/test_layout_offsets.py` — new `TestNestedGroups` class with `test_group_length_is_sum_of_children_and_children_offsets_are_correct` verifying that group items recurse properly: group's byte_length becomes sum of children's footprints, and children's offsets are relative to group's start. Pins Task 3 implementation of nested group recursion in `_layout_item()`.

2026-08-14 (Task 2): +3 in new `tests/unit/generators/data/test_layout_offsets.py` for the new `compute_record_layout()` function and `LayoutItem` dataclass (see [generators.md](generators.md)'s `layout_offsets.py` entry) — flat records with sequential elementary items, COMP-3 packed-decimal byte-length calculation, and 77-level elementary-item handling. Pins the Task 2 deliverable: byte-offset and byte-length computation for elementary items and record roots.

2026-08-13: +5 in `tests/unit/analysis/test_unused_variables.py`'s new
`TestQualifiedAndFunctionOperands` — Copilot PR review on the
`UnusedVariableAnalyzer` PR caught that a qualified name (`WS-A OF
WS-GRP`), an intrinsic function call (`FUNCTION UPPER-CASE(WS-X)`), a
special register (`LENGTH OF WS-X`), and a subscripted reference
(`WS-ENTRY(WS-IDX)`) were each added to the referenced-names set as one
opaque joined string instead of split into their underlying data-names,
so none of the real names ever matched and were falsely reported unused.
See [analysis.md](analysis.md)'s `_extract_identifiers` note.

2026-08-13: New `tests/unit/analysis/test_unused_variables.py` (25 tests) for
the new `UnusedVariableAnalyzer` (see [analysis.md](analysis.md)) — basic
used/unused detection, FILLER/`ANONYMOUS-*` exclusion, group-item
used-if-any-descendant-used, level-88 usage marking its parent used,
IF/PERFORM UNTIL condition operands (exercising the expression-tree walk,
not `.operands`), REDEFINES propagation, OCCURS DEPENDING ON, LINKAGE/FILE
SECTION coverage, `copybook_item_names`/`include_copybook_variables`
filtering, `TestExtrasLookupIsMroAware` (pins that the
`_STR_ATTR_EXTRAS`/`_DICT_LIST_EXTRAS` lookup walks `type(stmt).__mro__`,
not exact type), `to_dict()` serialization, top-level package export, and a
`collect_declared_items()` unit test.

2026-09-02: +11 in new `tests/unit/test_report_section.py` (REPORT SECTION:
RD clauses, anonymous/named report groups, TYPE/LINE/NEXT GROUP/COLUMN/
SOURCE/SUM/GROUP INDICATE/JUSTIFIED, to_dict, missing-RD-period guard,
FD `REPORT IS` non-header) and +5 in new
`tests/unit/test_xml_json_structured_clauses.py` (XML PARSE PROCESSING
PROCEDURE fields, XML/JSON ON EXCEPTION bodies as statements, END-JSON
inside IF); issue #394 added 4 more there (IS / THRU / THROUGH on their
own lines, bare PROCEDURE with IS on the next line, and the THRU range
staying live for dead-code). The 2026-08-13 file's REPORT tests were re-pointed at the parsed
shape (no warning) and `report_writer.cbl` rejoined `test_sample_programs.py`.

2026-08-13: +23 in new `tests/regression/test_screen_report_communication_sections.py`
— pins the DATA DIVISION parser's new SCREEN/REPORT/COMMUNICATION SECTION
header recognition (previously unrecognized headers let their content
corrupt WORKING-STORAGE), including end-to-end assertions against
`tests/samples/screen_section_io.cbl`, `report_writer.cbl`, and
`communication_module.cbl`, plus a dedicated collision check against
`examples/cobol/shamrice/report_test.cbl`'s `REPORT IS report-name.` FD
clause (`REPORT` as an ordinary clause word, not a section header). See
[parser.md](parser.md).

2026-08-13: `test_statement_text.py` reformatted to match the CI-pinned
`black==26.3.0` (whitespace-only, no test logic change) — pre-existing
drift from a newer local black, discovered while unblocking this PR's CI.

2026-08-13: +13 in `tests/unit/analysis/test_dead_code.py` — 3 in new
`TestSectionPropagationDoesNotResurrectSiblings` pinning the
`_propagate_section_references` sibling-resurrection fix, plus 10 in new
`TestDefensiveEdgeCases` closing every remaining coverage gap in
`dead_code.py` (95.77% → 100% line + 100% branch): inline PERFORM with no
target, MERGE without an output procedure / without THRU, a THRU range
with a falsy start, a blank SECTION name, invalid `"."` paragraph names
inside a section, a duplicate top-level paragraph name, an orphan ENTRY
statement, and a malformed ALTER target. See [analysis.md](analysis.md).

2026-08-12: Test-infrastructure audit — `contract`/`integration`/`io`
markers are now applied structurally by per-directory `conftest.py`
collection hooks (see "Per-directory marker enforcement" below); the 12
"Implementation pending - Phase 6/7" placeholder skips in the copybook
expansion unit/integration/contract files were replaced with real tests
(the phases shipped long ago); and the assert-free/tautological tests in
`test_comprehensive_real_world.py`, `test_parser_capabilities.py`, and
`test_basic_real_world_parsing.py` now assert `result.success` and AST
content. See [log.md](log.md).

2026-08-11: +1 in `test_dead_code.py`
(`test_terminator_earlier_in_paragraph_still_cuts_off_fall_through`) and +2
in `test_program_flow.py`
(`test_terminator_earlier_in_paragraph_still_suppresses_fall_through`,
`test_conditional_stop_run_inside_if_does_not_suppress_fall_through`) --
Copilot review on PR #135 caught that the just-added fall-through
termination checks were last-statement-only (missing an earlier top-level
terminator) and that `has_stop_run`/`has_goback`/`has_exit_program` were
nesting-blind (set for a conditional terminator too). See
[analysis.md](analysis.md).

2026-08-11: +11 in `tests/unit/analysis/test_dead_code.py`'s new
`TestFallThroughReferences` class (the fall-through concept added to
`DeadCodeAnalyzer`, audit finding #1) and +3 in
`tests/unit/analysis/test_program_flow.py`'s `TestProgramFlowFallThrough`
(the conditional-GO TO fall-through-suppression fix, audit finding #5,
including a rewrite of `test_fall_through_when_goto_and_perform_both_present`
to assert the corrected behavior). 21 pre-existing tests in
`test_dead_code.py` also needed their fixtures updated: they used
`CONTINUE`/bare `DISPLAY` as filler paragraph bodies with no terminator,
which the new fall-through pass now (correctly) credits as reaching the
next paragraph — added `STOP RUN` where a fixture's paragraph needed to
stay an isolated dead-code island. See [analysis.md](analysis.md).

2026-08-11: +6 across `test_dead_code.py` and `test_program_flow.py` —
three regression tests each pinning the `dead-code-section-550f0e`
paragraphs-before-first-SECTION fix: the mixed-order reordering itself, a
name reused top-level and inside a section (dedup guard on the paragraph
branch), and a name reused as a top-level paragraph then later as a SECTION
header (dedup guard on the SECTION-registration branch, added in a Copilot
review follow-up on the same PR). See [analysis.md](analysis.md).

2026-08-11: +3 in `tests/unit/analysis/test_dead_code.py`'s
`TestEntryReferences` (whitespace-only, empty-after-quote-stripping, and
`None` ENTRY literals) plus 2 more in `tests/unit/analysis/test_program_flow.py`.
A Copilot review on the ENTRY-reachability fix (see [analysis.md](analysis.md)'s
`DeadCodeAnalyzer`/`ProgramFlowAnalyzer` sections) caught that
`dead_code.py`'s new `_collect_entry_refs` didn't apply the same
blank/whitespace-literal filter `program_flow/scanner.py`'s
`collect_entry_points` already did — fixed to match.

2026-08-11: +4 in `tests/unit/analysis/test_program_flow.py` — new
`TestScannerDeepNestingRegression` class, pinning the explicit-work-stack
rewrite of `ProcedureScanner._scan_paragraph_statements`
(`cobolparser/analysis/program_flow/scanner.py`): three tests drive
`ProcedureScanner` directly (bypassing `ProgramFlowAnalyzer.analyze()`,
which hits a separate, unrelated `RecursionError` in `CobolProgram.
get_all_statements()` at these depths) at 2,000-5,000 levels of nested
IF/PERFORM to confirm no `RecursionError`, plus one pinning the EVALUATE
`WHEN`-clause thunk-deferral ordering invariant the rewrite depends on; see
[analysis.md](analysis.md).

2026-08-07: +7 — `tests/regression/test_inline_comment_stripping.py`, pinning
the lexer's new `*>` free-form inline-comment stripping, including a
pure/Cython parity check; see [lexer.md](lexer.md). Also removed the now-stale
`unstring.cbl` entry from `_EXPECTED_UNRESOLVED` in
`test_boundary_inventory_corpus.py` — the phantom `IOStartStatement` that
entry documented no longer occurs. Also 2026-08-07: +5 in
`tests/regression/test_parser_completeness.py` —
`TestExternalGlobalClauses.test_leading_is_does_not_warn` plus the new
`TestSynchronizedJustifiedIsClause` class, covering a data-item clause
dispatch fix: the leading `IS` of `[IS] EXTERNAL`/`[IS] GLOBAL`, and the
missing `IS` before `SYNCHRONIZED`/`JUSTIFIED`'s `LEFT`/`RIGHT` direction,
were dropped as spurious "Unparsed token" warnings even on fully standard
syntax — see [parser.md](parser.md). 2026-08-05: +44 net across two fixes
— `test_dead_keyword_removal.py` (+16: seven dead `lexer.KEYWORDS` entries
that never matched real syntax, see [lexer.md](lexer.md)) and
`test_invoke_allocate_free_statements.py` (+15, plus new
`TestInvokeAllocateFreeNoLongerSwallowed` classes in
`test_tier5_silent_drip_audit.py` and `test_tier7_unsupported_verb_boundary.py`,
and a swapped-in `TRANSFORM` case replacing the now-supported `INVOKE` in
`test_tier3_silent_drop_fixes.py`/`test_tier5_silent_drip_audit.py`: `INVOKE`/
`ALLOCATE`/`FREE` now have registered statement parsers, see
[parser.md](parser.md)). A Copilot review on the same PR (#113) added
required-operand validation to all three parsers (missing object
identifier/method name for INVOKE, missing size-expr/data-item for ALLOCATE,
zero pointer names for FREE all now report a parse error instead of
silently succeeding) plus an operand-recording fix for INVOKE's literal
method names — 5 of the 15 tests above cover these. 2026-08-04: +454 tests across Phases
1-7 of the `gen-fixtures` program-scoped test-data initiative —
`ProgramLayoutIndex` (Phase 1), `BoundaryInventoryAnalyzer` (Phase 2),
`ProgramFixtureGenerator` + the `gen-fixtures` CLI subcommand (Phase 3),
`ConstraintExtractor` + the `domains.py` solver (Phase 4), `ScenarioPlanner`
(Phase 5), wiring `--scenarios branches|all` into a populated
`FixtureBundle` plus a hand-written schema doc (Phase 6, +15 tests: see
`docs/fixture-bundle-schema.md`), and per-scenario tier 1/2 `Expectation`s —
`call_count` (exact counts only since issue #363: see generators.md),
`field_equals` from the new `analysis.const_fold.ConstantFolder` single-pass
walk seeded with that scenario's own mocked inputs (Phase 7, +104 tests:
`test_const_fold.py` (44 unit tests over MOVE/arithmetic/COMPUTE folding,
loop/branch poisoning, PERFORM chaining, control-flow stops, and the
ACCEPT/READ/DISPLAY/WRITE observation boundary), `test_const_fold_corpus.py`
(50 tests parametrised over `examples/cobol/shamrice/*.cbl`, plus an ad hoc
sweep of the full 459-file NIST corpus given the higher correctness stakes
of arithmetic folding — that sweep surfaced and fixed a latent `IndexError`
in Phase 1's `ProgramLayoutIndex.resolve()` on an all-punctuation name), and
+10 in `test_program_fixtures.py` for `TestTier1CallCountExpectations` and
`TestTier2FieldEqualsExpectations`); see [generators.md](generators.md) and
[analysis.md](analysis.md). Phase 4 also fixed a pre-existing, unrelated
parser bug it uncovered: `>=`/`<=`/`<>` were silently mis-parsed as
`>`/`<`/`<` with a garbled operand in every IF/PERFORM UNTIL condition (see
[parser.md](parser.md)) — zero regressions across the 783 IF/PERFORM/
shamrice/NIST tests re-run after that fix. Earlier,
2026-07-09: CobolCheck test generation — `CoverageAnalyzer`,
`TestPlanGenerator`, `CobolCheckGenerator`, the `generate-tests` CLI
subcommand, and their ~180 dedicated tests — was removed, superseded by
the mockymock framework. Earlier the same day: +30 in
`tests/regression/test_open_findings_medium_regressions.py`, one test
class per MEDIUM finding M1, M2, M3, M4, M5, M7, M8, M9, M14, M16 fixed
that day, plus a Cython/pure-Python parity check — see
[parser.md](parser.md)'s "open-findings.md MEDIUM-severity fixes"
section and [preprocessing.md](preprocessing.md)/[lexer.md](lexer.md)
for the M4/M5/M7/M8/M14 write-ups; also includes the earlier same-day +21
in `tests/regression/test_open_findings_high_regressions.py` for HIGH
findings H1-H8). Coverage floor: **90% line coverage** enforced by
`--cov-fail-under=90` in `pyproject.toml`; full-suite run measured
92.22% (see log.md's 2026-08-19 entry). Branch coverage is enabled.

2026-08-12: +17 in `tests/unit/analysis/test_statement_text.py` (new —
`summarize_statement`/`summarize_arm`, real-parse fixtures per statement
type, truncation, never-raises guard) and +20 in
`test_flowchart_generator.py` (`TestMermaidLabelFidelity`/
`TestDotLabelFidelity`/`TestLabelFidelityEndToEnd`: ASCII-only output,
`#lt;`/`#gt;` label escaping, `"`→`'` substitution — `#quot;` renders as
literal `&quot;` on the SVG-text path — arm statement summaries with
`+N more` markers, empty-IF-arm dropping), plus `test_program_flow.py`'s
`test_branch_arm_to_dict_fields` extended for the optional
`BranchArm.summary` key. See [generators.md](generators.md)'s "Label
fidelity" section.

2026-08-11: +2 in `test_flowchart_generator.py`
(`test_loop_label_with_parens_is_quoted`, `test_call_dynamic_edge_label_with_parens_is_quoted`)
plus 6 existing `-->|label|` assertions updated to the now-quoted form —
`MermaidFlowchartGenerator` started wrapping edge labels in quotes so an
unquoted `(`/`[` inside one (a loop annotation, `CALL (dynamic)`, a
`[THRU n]` badge) can't be misread by Mermaid's flowchart lexer as a node
shape token. See [generators.md](generators.md)'s "Flowcharts" section.

Running only a subset of tests will trigger a coverage failure — that is expected.

# Directory Layout

```
tests/
  conftest.py                  # shared fixtures: parser(), samples_dir()
  test_all_samples.py          # smoke-tests all sample COBOL programs
  unit/                        # individual components
    analysis/                  # IO coverage reporter, diagnostics, all analyzers
    cli/                       # CLI command tests
    generators/                # Flowchart generator tests
    test_copybook_data_generator.py  # copybook -> CSV: flattening, categories, value constraints, options, dataset surface
    generators/data/
      test_views.py  # build_record_views(): running-offset placement checked against real encoded bytes, REDEFINES overlays as the whole record with the overlay swapped in (every occurrence inside OCCURS, FILLER padding for a shorter overlay, a nested overlay read through its enclosing one -- #296), an overlay not moving the fields after it, two redefinitions of one item, short-name lookup, ODO ambiguity flagging, and a parametrised contiguity property over every view (see generators.md)
      test_decoding.py  # RecordDecoder: decode(encode(row)) == row for every storage class and both charsets, ODO under every RecordFormat, RDW framing, overlay switching reading identical bytes (and every occurrence of an overlay inside OCCURS, #296), the sign conventions the decoder reads but never writes, bad bytes reported per field (ODO counters out of range, leftover RDW body bytes, negative sign on unsigned COMP-3 included), short/truncated records, paging, and the hex pane (see generators.md)
    test_program_layout_index.py  # ProgramLayoutIndex: FD/record resolution, FD-vs-SD tagging, FileFacts, name resolution, qualified level-88 names (resolve/condition_values/gen-fixtures arms, #272), record_named(), multi-program units, from_file errors (see generators.md)
    test_program_fixtures.py  # ProgramFixtureGenerator: bundle assembly, CALL-argument fixtures (IN/OUT/BIDIRECTIONAL notes), SQL fixtures, determinism, write_csv_dir (csv-dir <-> JSON byte-for-cell round trip, one directory per scenario; a forced name collision still writes distinct CSVs), TestScenarioModes: witness pinning (incl. a compound SEARCH WHEN pinning each conjunct, #348) / empty-input / boundary min-max / scenario_coverage presence, TestTier1CallCountExpectations, TestTier2FieldEqualsExpectations: call_count/field_equals wiring end-to-end, TestTargetedArmsAreVerified: a violated scenario's arms are counted missed and land in unresolved (#244), TestCallFixtureSameNamedFields: same-named fields in two USING records get their own column and value, index specs not renamed in place (#365) (see generators.md)

    test_program_fixtures.py  # ProgramFixtureGenerator: bundle assembly, CALL-argument fixtures (IN/OUT/BIDIRECTIONAL notes), SQL fixtures, determinism, write_csv_dir (csv-dir <-> JSON byte-for-cell round trip, one directory per scenario; a forced name collision still writes distinct CSVs), TestScenarioModes: witness pinning / empty-input / boundary min-max / scenario_coverage presence, TestTier1CallCountExpectations, TestTier2FieldEqualsExpectations: call_count/field_equals wiring end-to-end, TestTargetedArmsAreVerified: a violated scenario's arms are counted missed and land in unresolved (#244), TestFailurePathExpectations: error-status / empty-input scenarios assert no normal-path call_count and no field_equals (#318) (see generators.md)

    test_program_fixtures.py  # ProgramFixtureGenerator: bundle assembly, CALL-argument fixtures (IN/OUT/BIDIRECTIONAL notes), SQL fixtures, determinism, write_csv_dir (csv-dir <-> JSON byte-for-cell round trip, one directory per scenario; a forced name collision still writes distinct CSVs), TestScenarioModes: witness pinning / empty-input / boundary min-max / scenario_coverage presence, TestTier1CallCountExpectations, TestTier2FieldEqualsExpectations: call_count/field_equals wiring end-to-end, TestTargetedArmsAreVerified: a violated scenario's arms are counted missed and land in unresolved (#244) (see generators.md); TestCallCountFollowsControlFlow: call_count only where exact -- branches, literal TIMES, UNTIL bodies, the read-to-EOF rule and its early exits, GO TO loops, EOF status checks (#363); TestMultipleRecordsUnderOneFd: an FD's several 01 records give one record's columns per row, never all joined, picked by the scenario's pins (#364); TestArmsOnTwoRecordsOfOneFd: arms on two 01 records of one FD are never merged, an arm pinning both is missed, dropped pins demote the scenario's arms, the alternate-view note names only unused records; TestFillerOwningConditionName: a FILLER (omitted or explicit) owning a level-88 keeps its FILLER#<n> column and witness
    test_scenario_planner.py  # ScenarioPlanner: THEN/ELSE targeting, disjoint-field merging, unsatisfiable-arm handling, fixed families (empty-input/error-status/boundary-values), exact coverage accounting, TestScenarioNamesAreUnique: verb@line + disjunct naming, merged names, uniqueness over tests/samples and enterprise (#267) (see generators.md)
    io_statements/             # IO parser unit tests
    test_extended_verb_parsers.py  # 2026-09-02 statement-coverage audit: INITIATE/TERMINATE/SUPPRESS, SEND/RECEIVE/ENABLE/DISABLE/PURGE, EXHIBIT/EXAMINE/TRANSFORM/ENTER/NOTE/CHAIN, READY/RESET TRACE, SERVICE, TITLE, RAISE/RESUME/VALIDATE -- node, operands, no warnings; UNSUPPORTED_VERBS == {EXECUTE, GOTO, RECOVER}; every STATEMENT_KEYWORDS verb dispatches (see parser.md)
    cli/
      test_decode_cli.py  # decode: CSV/JSON/hex output, --view / --list-views, gen-data -> decode CSV round trip through the CLI, --skip/--max-records paging, trailing-byte warning, --strict exit code; plus dclgen-check as a subcommand and as a lint rule (see cli.md)
      test_gen_fixtures_cli.py  # gen-fixtures: flags, --list-boundaries, --format json|csv-dir, --strict exit codes (see cli.md)
    analysis/
      test_boundary_inventory.py  # BoundaryInventoryAnalyzer: per-category key/layout/direction, nested-body reachability (IF/EVALUATE/SEARCH), CALL argument-direction ladder, ACCEPT filtering (incl. `FROM DATE YYYYMMDD` qualifiers), IOLogger cross-check (see analysis.md)
      test_constraints.py  # ConstraintExtractor: relational/level-88/figurative/class-sign forms, AND/OR/NOT via De Morgan, EVALUATE TRUE + 88s, WHEN OTHER, SEARCH WHEN (incl. AND/OR from its condition tree, #348), PERFORM-UNTIL SequenceConstraint (see analysis.md)
      test_domains.py  # domains.solve(): numeric/text/enum domains, witness-satisfies-constraint property, Unsatisfiable never returns a value, TestEnumDomainHonoursRelationalConjuncts: a level-88 pick re-checked against gt/ge/lt/le (#244) (see analysis.md)
      test_dclgen_check.py  # DclgenChecker: DCLGEN column <-> host-variable pairing (the CUST_ID/CUST-VAL underscore-hyphen normalization), every violation kind and its severity, both null-indicator syntaxes, what it declines to check (VARCHAR group binding, BLOB), source ordering, ambiguous columns, and a parametrised "what DCLGEN itself would generate is always clean" table (see analysis.md)
      test_const_fold.py  # ConstantFolder: MOVE/ADD/SUBTRACT/MULTIPLY/COMPUTE folding, GIVING forms, loop/branch write-poisoning, DIVIDE's unconditional poison, the ADD-X-TO-X self-reference gap, PERFORM (inline/paragraph/THRU) chaining, GO TO/STOP RUN stopping the walk, ACCEPT/READ preserving a seeded value, DISPLAY/WRITE as the only observation points, TestStorageAliasing: sibling FD records / WRITE FROM / JUSTIFIED RIGHT padding (#245), TestValueAtObservationPoint: value at each DISPLAY/WRITE site + paragraph fall-through (#246), TestWalkBudget: the step budget on a quadratic fall-through chain (see analysis.md), TestInspectAndExecWrites: INSPECT TALLYING counters and EXEC CICS options / EXEC DLI arguments are writes (#317)

      test_const_fold.py  # ConstantFolder: MOVE/ADD/SUBTRACT/MULTIPLY/COMPUTE folding, GIVING forms, loop/branch write-poisoning, DIVIDE's unconditional poison, the ADD-X-TO-X self-reference gap, PERFORM (inline/paragraph/THRU) chaining, GO TO/STOP RUN stopping the walk, ACCEPT/READ preserving a seeded value, DISPLAY/WRITE as the only observation points, TestStorageAliasing: sibling FD records / WRITE FROM / JUSTIFIED RIGHT padding (#245), TestValueAtObservationPoint: value at each DISPLAY/WRITE site + paragraph fall-through (#246), TestWalkBudget: the step budget on a quadratic fall-through chain (see analysis.md)
      test_invocation_counts.py  # count_invocations (issue #363): status-check exemption (level-88, mixed conditions, INVALID KEY), EVALUATE / UNTIL / VARYING / variable TIMES bodies unknown, EXIT PARAGRAPH, literal TIMES with a transfer, fall-through + PERFORM counted twice, GO TO followed forward / into a SECTION, GO TO out of a PERFORM / DEPENDING ON / with ALTER / to an unknown target reporting nothing
  integration/                 # end-to-end parsing
    test_shamrice_examples.py  # parametrised: all *.cbl in examples/cobol/shamrice/ must parse error-free
    test_nist_cobol85_support.py  # parametrised: all 459 NIST *.CBL must parse error-free (strict-xfail KNOWN_ISSUES ratchet); copybook validation
    test_copybook_csv_generation.py  # parametrised over the sample + NIST *.CPY corpora: no copybook may crash gen-data; a copybook with no record layout must raise CopybookLayoutError, and every generated cell must be assignable to its field (see generators.md)
    test_program_layout_corpus.py  # parametrised over examples/cobol/shamrice/: ProgramLayoutIndex must build without raising and report zero unexpected unresolved/ambiguities entries
    test_boundary_inventory_corpus.py  # parametrised over examples/cobol/shamrice/: BoundaryInventoryAnalyzer must build without raising and report zero unexpected unresolved entries
    test_gen_fixtures_corpus.py  # parametrised over examples/cobol/shamrice/: ProgramFixtureGenerator must build a bundle without raising, every generated cell fits its field's category, and determinism holds across the corpus
    test_constraint_extractor_corpus.py  # parametrised over examples/cobol/shamrice/: every branch/loop either produces constraints or a reason in unsupported (no silent drop); every solved witness is layout-valid (see analysis.md)
    test_scenario_planner_corpus.py  # parametrised over examples/cobol/shamrice/ x {branches,all}: coverage accounting sums to the arm count for every program; every miss/merge carries a reason/target (see generators.md)
    test_const_fold_corpus.py  # parametrised over examples/cobol/shamrice/: ConstantFolder must fold without raising, and every known value is layout-valid (also smoke-tested ad hoc against the full 459-file NIST corpus -- see analysis.md)
    io/                        # IO coverage reporting integration
    io_statements/             # IO statement parsing, VSAM
  contracts/                   # API contract tests — stability guarantees
    test_fixture_bundle_contract.py  # FixtureBundle: exported names, bundle_version, generator signatures, to_dict() key sets, reproducibility; TestScenarioModeContract: generate_with_scenarios(_from_file) signatures, happy-mode byte-identity with generate, scenario_coverage population/absence, seed reproducibility, unknown-mode ValueError (see generators.md, docs/fixture-bundle-schema.md)
    io_statements/
  regression/                  # backward compatibility
                               #   test_statement_coverage_audit_2026_09_02.py: EXEC CICS/DLI in get_all_statements(); GO TO target across newline; optional ON/AT handler words; literal spelled like a verb; CALL handler boundaries; ,/; separators; XML GENERATE SUPPRESS; NIST clause forms; 20-program NIST no-drop-warning guard (see parser.md)
                               #   test_swallow_sweep.py: generic cross-product
                               #   sweep -- one period-less snippet per
                               #   registered statement parser x a DISPLAY
                               #   'MARKER'. sentinel, asserting the marker
                               #   survives as CobolParagraph's next top-level
                               #   statement. Fails automatically if a new
                               #   parser is registered without a fixture
                               #   (2026-07-21) -- see parser.md's "Generic
                               #   swallow-sweep regression" section
                               #   test_evaluate_traversal_regression.py:
                               #   EVALUATE WHEN branches must be AST children
                               #   (find_all_by_type reaches nested statements;
                               #   duplicate WHEN OTHER reuses one default clause)
                               #   test_screen_report_communication_sections.py:
                               #   SCREEN/REPORT/COMMUNICATION SECTION header
                               #   recognition (2026-08-13) -- see parser.md
                               #   test_tier5_silent_drip_audit.py: SORT/MERGE/
                               #   ENTRY/CALL-handler silent-drop fixes (2026-07-08)
                               #   test_normalize_line_number_preservation.py:
                               #   normalize_fixed_format / preprocess_conditional_
                               #   compilation line-number preservation + Cython
                               #   parity (2026-07-08)
                               #   test_open_findings_high_regressions.py:
                               #   H1-H8 from reports/open-findings.md (SET
                               #   ADDRESS OF, COMPUTE unbalanced parens, PERFORM
                               #   trailing-identifier + bare excepts, MoveType-
                               #   Checker unresolved_count, PathResolver Tier-2
                               #   containment, lexer unterminated-string warning,
                               #   CLOSE combined per-file options) (2026-07-09)
  performance/                 # benchmarks (factory, parser)
  samples/                     # shared COBOL fixtures
    copybook_programs/         # programs with COPY statements
    copybooks/                 # .CPY files
    io/
      positive/                # valid IO operations
      negative/                # invalid IO patterns
```

# pytest Markers

| Marker | Meaning |
|--------|---------|
| `integration` | Integration tests |
| `slow` | Slow-running tests |
| `contract` | API contract tests |
| `io` | IO statement tests (OPEN, CLOSE, READ, WRITE, REWRITE, DELETE, START, ACCEPT, DISPLAY, UNLOCK) |

```bash
python -m pytest -m "integration"    # integration tests only
python -m pytest -m "slow"           # slow tests only
python -m pytest -m "contract"       # API contract tests only
python -m pytest -m "io"             # IO statement tests only
```

## Per-directory marker enforcement (2026-08-12)

The `contract`, `integration`, and `io` markers are applied **structurally**
by per-directory `conftest.py` files (a `pytest_collection_modifyitems` hook
that adds the marker to every item collected under that directory), so new
test files can never drift out of `-m` selection:

| conftest.py location | Marker applied |
|----------------------|----------------|
| `tests/contracts/` | `contract` |
| `tests/integration/` | `integration` |
| `tests/unit/io_statements/` | `io` |
| `tests/integration/io_statements/` | `io` (plus `integration` from parent) |
| `tests/integration/io/` | `io` (plus `integration` from parent) |
| `tests/contracts/io_statements/` | `io` (plus `contract` from parent) |

In-file `pytestmark = pytest.mark.<x>` lines still exist in many files;
they are harmless duplicates and are no longer required. A file *outside*
these directories can still opt in with an explicit `pytestmark` (e.g. the
`integration` marker is carried by a few files elsewhere).

# Shared Fixtures (`tests/conftest.py`)

| Fixture | Returns |
|---------|---------|
| `parser()` | Fresh `CobolParser` instance |
| `samples_dir()` | `Path` to `tests/samples/` |

# Running Tests

```bash
# All tests with coverage (90% min)
python -m pytest tests/ -v

# Single file
python -m pytest tests/unit/test_lexer.py -v

# Single test
python -m pytest tests/integration/test_call_comprehensive.py::TestCallComprehensive::test_call_with_periods -xvs

# By directory (no dedicated marker needed)
python -m pytest tests/regression/ -v
python -m pytest tests/contracts/ -v
python -m pytest tests/performance/ -v
```

# Example Corpora

| Path | Contents |
|------|----------|
| `tests/samples/` | ~48 COBOL programs covering all statement types |
| `examples/cobol/` | NIST COBOL-85 test suite (459 .CBL files + 51 .CPY copybooks); 457/459 parse error-free — pinned by `test_nist_cobol85_support.py` (2 strict-xfail `KNOWN_ISSUES`: OBNC1M needs Area A/B awareness, SM101A needs copybook expansion by design; both SM101A and SM207A parse clean with expansion). Minimal repros for the fixed edge cases live in `tests/regression/test_nist_edge_case_fixes.py` |
| `examples/cobol/shamrice/` | 24 IBM COBOL programs from shamrice/COBOL-Examples; all parse cleanly under FAIL_FAST |

# Coverage Requirement Detail

From `pyproject.toml`:

```toml
addopts = [
    "--strict-markers",
    "--cov=cobolparser",
    "--cov-report=term-missing",
    "--cov-report=html:htmlcov",
    "--cov-fail-under=90",
]
```

Branch coverage is also enabled (`[tool.coverage.run] branch = true`).
No coverage baselines are stored in the repo (there is no `baselines/`
directory); the floor above is the only gate.

# CI/CD

GitHub Actions (`.github/workflows/ci.yml`) on push/PR to `main`, a nightly
`schedule` (`17 4 * * *`) and manual `workflow_dispatch`. Push and PR
triggers carry `paths-ignore` for `docs/**`, `.okf/**`, `reports/**` and
`**/*.md`, so a docs-only change runs no CI at all. A new push to a PR
cancels the run in flight (`concurrency`); runs on `main` are never
cancelled. (Reshaped 2026-10-03, commit `5fd5b8e` "ci: cut PR build cost".)

1. **lint** — `ruff check .` + `black --check .` (Python 3.13, `ruff==0.15.0`
   / `black==26.3.0`, pinned to match `.pre-commit-config.yaml`)
2. **typecheck** — `mypy cobolparser/` (Python 3.13, `mypy==1.20.0`)
3. **build** — `pip install -e ".[dev,fast]"` + `python setup.py build_ext --inplace`
   + `python -m pytest <targets> -q -p no:randomly -n auto --no-cov` on matrix
   Python 3.11, 3.12, 3.13, on **every** trigger. The full `tests/` suite
   runs on all three for a push to `main`, the nightly run and a dispatch; on
   a **PR** only 3.13 runs the full suite, and 3.11/3.12 run a smoke subset
   (`tests/unit/test_lexer.py tests/test_all_samples.py
   tests/unit/test_program_fixtures.py`). The nightly full matrix is what
   catches a 3.11/3.12-only break that slipped through a PR.
4. **coverage** — `COBOLPARSER_SKIP_EXT=1 pip install -e ".[dev]"` +
   `python -m pytest tests/ -q -p no:randomly -n auto` on Python 3.13
   (`if: github.event_name != 'push'`: PRs, nightly and dispatch). Where
   the 90% floor is actually enforced, and why it is a job of its own:
   coverage.py cannot see into a compiled Cython extension, so once
   `build_ext` has run the pure-Python bodies it shadows read as unexecuted.
   Same suite, same commit, measured 2026-09-07: **54.32%** with the
   extensions built, **91.76%** without. Gating inside `build` would fail on
   the build step rather than on the code.

Release builds are a separate workflow,
`.github/workflows/release-please.yml`: release-please cuts the release from
Conventional Commits, then `cibuildwheel` builds wheels (manylinux x86_64,
macOS arm64, Windows AMD64 × CPython 3.11–3.13; only the three Cython
accelerators are compiled, every other module ships as `.py`) and a
`build-sdist` job builds the sdist; both are attached to the GitHub Release
and published to PyPI as `cobol-parser` via Trusted Publishing.
`[tool.cibuildwheel]`'s `test-command` runs a fast pytest subset against the
installed wheel (`--no-cov`). The former closed-source release mode
(`COBOLPARSER_CLOSED_SOURCE=1`) was removed 2026-10-03 (`1d6078e`); the
package is AGPL-3.0-or-later (`fdd1199`).

**Timing assertions and coverage.** `tests/performance/test_factory_performance.py`
guards its two absolute nodes/sec floors with `requires_untraced`
(`sys.gettrace() is not None`). Under coverage.py's tracer the suite takes
950 s instead of 94 s, and `test_factory_throughput` measured 64,243
nodes/sec against its 100,000 floor on a CI runner that clears it
comfortably uninstrumented — the number describes the tracer, not the
factory. The `build` matrix runs the file uninstrumented on all three
Pythons, so the guard is not in force there; only the `coverage` job skips
them. The ratio-based overhead assertion is unaffected. Surfaced the moment
the suite was first wired into CI.

The full suite (~13,000 tests across 464 `test_*.py` files as of
2026-10-14; ~9,400 at the time) **does** run on every PR, as of the
2026-09-07 audit (on 3.13 only since 2026-10-03 -- see `build` above). It previously ran nowhere: this file used to describe a
`test` job gated on `if: github.event_name == 'workflow_dispatch'`, and no
such job was ever in `ci.yml` — the suite and the `--cov-fail-under=90`
floor went unenforced on every push and PR alike.

**Pure Python default (2026-10-15).** The Cython accelerators are now used
only under `COBOLPARSER_ACCEL=1` (build and import time; `.okf/lexer.md`), so
a default run takes the pure-Python paths even with `*.so` files present and
coverage measures correctly. `ci.yml` (currently commented out) sets the
variable on `build`'s `build_ext` and pytest steps so that job still exercises
the extensions. Locally: the default run is the pure suite; run it again with
`COBOLPARSER_ACCEL=1 ... --no-cov` after building to cover the fast paths.

It now runs twice, for two different reasons. In `build`, after `build_ext`,
so CI exercises the Cython extensions rather than the pure-Python fallback
(which it built and never ran a line through) — `--no-cov` there, per the
coverage note above. In `coverage`, on a pure-Python install, where the 90%
floor is enforced. `-n auto` keeps each near two minutes; `-p no:randomly`
keeps a failure reproducible from the log. Run it locally during development
too (see commands above).


# Source map, comments and program units (2026-09-07)

* `tests/regression/test_expansion_source_map_and_comments.py` — the
  expander's per-line source map (identity without a COPY, across a splice,
  through a continuation merge, into a nested member, on a cache hit, and out
  through `parse_cobol_with_expansion`), `lint.apply_source_map`, and
  `preserve_comments` (restored in program and copybook, no line moved, a
  `COPY` inside a comment still not expanded), plus the serialization rule
  that a half-known origin is emitted as no origin at all.
* `tests/regression/test_nested_program_units.py` — `program_units()` /
  `find_program_unit()`, `LintAnalyzer` covering every unit, and the CLI's
  `--program` selection including its "unknown name lists what is there"
  failure. `TestCopybookProvenanceCoversEveryUnit` pins the consequence that
  came with per-unit linting: a copybook field unused in a *contained*
  program grades `info`, not `warning` (see [cli.md](cli.md)).
* `tests/unit/cli/test_expand_source_map_cli.py` — the same surface at the
  command line: `expand --source-map` / `--keep-comments`, and lint findings
  carrying the copybook they are really in (this is what the VS Code
  extension consumes).
* #301 (2026-10-13): `test_lint_subcommand.py::TestTextOutput` pins the
  on-disk column for fixed-format and free-form programs (the old `:6:1:`
  expectation encoded the bug); `test_expand_source_map_cli.py` pins
  `origin.column` and the free-member-in-fixed-parent / fixed-member-in-free-
  parent offsets; `test_expansion_source_map_and_comments.py` pins
  `apply_source_map(..., column_offset)` and `fixed_format_column_offset`.
  Review follow-up: `test_source_format_free_directive_stops_the_shift`,
  `test_json_origin_carries_the_on_disk_column`,
  `test_without_expansion_origin_is_the_file_itself` (replaced the old
  "no origin without expansion" test), and the no-column parse error case.
  Round 2: `test_switching_back_to_fixed_shifts_again`,
  `test_source_format_fixed_flag_shifts` / `..._free_flag_does_not_shift`,
  `test_a_copybook_that_cannot_be_reread_prints_no_column` (patches
  `Path.read_text`, which only the column helper uses; the expander opens
  files itself).

# Cross-repo review follow-up fixes (2026-09-10)

* `tests/unit/analysis/test_const_fold.py::TestObservationPoints` — two new
  regression cases (`test_accept_into_reference_modified_target_...`,
  `test_read_into_reference_modified_target_...`) pin that a subscripted/
  reference-modified READ INTO/ACCEPT target is poisoned, not restored to
  the whole base item's seed value.
* `tests/unit/analysis/test_boundary_inventory.py::TestConditionFieldNamesExpressionTrees`
  — hand-built `EvaluateStatement`/`ArithmeticExpression`/`FunctionCall`
  nodes exercise `_condition_read_names`/`_condition_field_names` shapes the
  real parser does not currently produce (an `EVALUATE` subject that is a
  `CobolExpression`, a nested arithmetic operand inside a comparison) —
  regression coverage for the documented type contract, not a reachable-bug
  repro.
* `tests/unit/generators/data/test_layout.py::TestFieldSpecScalingPositions`
  and `tests/unit/analysis/test_move_type_checker.py::TestIsNonIntegerPicture`
  — `FieldSpec.scaling_positions`/`.stored_digits` and
  `_is_non_integer_picture` now reading `PictureClause`'s own
  `total_digits`/`scaling_leading`/`decimal_digits` fields instead of each
  re-deriving them from the raw picture string.
* `tests/unit/analysis/test_lint.py::TestFlowReportReuse::test_linkage_check_collects_entry_interfaces_once_per_file`
  — a 3-program-unit fixture confirms `LinkageChecker._collect_interfaces`
  is called exactly 3 times for a whole-file `linkage-check` lint pass, not
  9 (the O(units²) it used to be).
* `tests/unit/analysis/test_linkage_checker.py::TestPassingModeMismatch` —
  the new `PASSING_MODE_MISMATCH` violation: a CALL's BY VALUE/BY REFERENCE
  (explicit or defaulted) checked against the callee's own declared
  `PROCEDURE DIVISION USING` mode per position, never against an `ENTRY`
  statement's USING (which carries no BY clause in COBOL) or a `BY CONTENT`
  argument (no USING counterpart to compare against).
* `tests/regression/test_review_2026_09_09_parser.py::TestFinding12CheapExtras`
  — two new cases pin `SET`'s per-group `value_is_entry` flag: a later
  group must not inherit an earlier group's `ENTRY` value, and must record
  its own.
* `tests/unit/test_ibm_enterprise.py::test_get_intrinsic_function_signature_existing`
  — updated for `LENGTH`'s corrected `return_type`/`parameters` (`integer`/
  `["any"]`, not the stale hand-written `numeric`/`["string"]`) now that the
  override table only supplies `CURRENT-DATE`'s byte length, a fact the
  `le_signatures` catalogue has no structured field for at all.
* `tests/regression/test_conditional_compilation_literals.py` (2026-09-28)
  — `>>DEFINE`/`>>IF`/`>>WHEN` literal contents compare case-sensitively;
  `-1` and doubled-delimiter literals (`'O''BRIEN'`) are operands.
* `tests/regression/test_literal_concatenation.py` (2026-09-28) — `lit & lit`
  merged into one STRING_LITERAL by both lexers (VALUE clause, MOVE source,
  across lines, fixed-format columns); unlike kinds / `Z` literals kept apart.
* `tests/regression/test_level88_false_and_initialize_phrases.py`
  (2026-09-28) — `ConditionNameItem.false_value`; INITIALIZE
  `to_value_category` / `to_default`.

# Copybook missing-period check, per entry (2026-09-12)

* `tests/unit/test_preprocess_init_coverage.py::TestValidateCopybookContent`
  — four new cases around `validate_copybook_content`'s "may be missing
  terminating period" warning now that it judges a whole data-description
  entry instead of one physical line (see [preprocessing.md](preprocessing.md)):
  `test_no_false_positive_when_entry_continues_onto_next_line` (a `PIC` line
  terminated by a `VALUE` line below it is correct source),
  `test_missing_period_detected_on_multi_line_entry` (the multi-line case is
  still *checked*, not exempted),
  `test_multi_line_entry_does_not_swallow_the_entry_below_it` (an
  unterminated entry ends where the next one starts — including behind a
  single-digit level number),
  `test_single_digit_level_entry_is_checked_like_any_other` (such an entry is
  judged on its own missing period too, not merely used to close the one
  above it — the two patterns share one `_ENTRY_HEAD` fragment so they cannot
  disagree about that), and
  `test_blanked_comment_inside_an_entry_does_not_split_it` (the blank left by
  `remove_comment_lines` inside an entry is not a terminator). They sit
  alongside the decimal-point-PIC pair from the 2026-07-27 fix to the same
  check, which pins the opposite direction.

# Enterprise program-type corpus (2026-09-15)

`tests/samples/enterprise/` holds one program per IBM Enterprise COBOL
program type (22 programs + `copybooks/`; the matrix with every
distinguishing construct is `docs/enterprise-program-types.md`).
`tests/integration/test_enterprise_program_types.py` (`integration`
marker) asserts, per program: a FAIL_FAST parse with no errors and no
warnings other than the informational "Compilation unit contains N
program units"; a JSON round trip; every analyzer over every unit without
raising and `LintReport.failed_rules == []`; `gen-fixtures --scenarios
all` and `scan` accepting it; and per-type traits (the CICS commands,
DL/I function codes, MQ calls, OO unit tree, declarative sections, flow
edges, 6.x data attributes ... that make the program its kind).
`TestCorpusShape` fails when the directory and `PROGRAM_TYPES` disagree, so
a new type has to be added to both. The corpus is parsed with
`debug_lines=True` (COMPDIR declares `WITH DEBUGGING MODE`; it is the only
program with D lines), so COMPDIR's D-line DISPLAYs are in its AST and it
stays warning-free; `tests/unit/test_debugging_mode_lines.py` pins the
default (dropped + warning), the option on every surface (API, CLI,
cobol.yml, scan, tokenize, batch, the copybook expansion -- with a real
COPY, since a program without one passes through the expander untouched --
and every subcommand that parses COBOL) and `debug_line_numbers` (#334). `tests/samples/*.cbl` smoke checks
(`test_all_samples.py`) cover the corpus too, since it lives under
`tests/samples/`. The same 22 files are copied into
`mocky-mock/tests/fixtures/enterprise/`, where
`mocky-mock/tests/unit/test_enterprise_corpus.py` pins `mockymock generate`'s
outcome per program (that path is in the *sibling* repo, not this one).

`tests/unit/test_enterprise_syntax.py` pins each construct the corpus
surfaced in isolation: PROGRAM-ID attributes, OO units, DECLARATIVES,
`USE BEFORE REPORTING`, the 6.x data clauses, `OCCURS UNBOUNDED`, JSON
`CONVERTING`, `RETURNING`, `SET ADDRESS OF`, conditional compilation by
default, and REPLACE partial words.

Three older tests changed on purpose: the missing period after the
`PROGRAM-ID` keyword is tolerated (IBM), the mandatory-PROGRAM-ID message
names CLASS-ID / METHOD-ID too, and an unknown `>>` directive is blanked
rather than passed through.


# OKF staleness map guard (2026-09-15)

`tests/test_okf_staleness_map.py` pins `scripts/okf_staleness_check.py`'s
`OKF_MAP`: every tracked `.py`/`.pyx` under `cobolparser/` must map to at
least one OKF file, every mapped OKF file must exist, and every prefix that
names a directory must end with `/`.

A file missing from that map is not a lint nit -- it is a file whose
documentation can rot silently, because the pre-commit hook will never ask
for an update when it changes. That is exactly how `cobolparser/jcl/` (a
1,900-line JCL front end) and `cobolparser/parser.py` (the parse
orchestrator, missed because the `cobolparser/parsers/` prefix ends in a
slash and so never matched it) both went unmapped; 15 files were uncovered
when the guard was written. The directory-slash assertion exists because
dropping the slash would make `cobolparser/parsers` swallow
`cobolparser/parser.py` -- the inverse mistake.


# See Also

* `tests/unit/cli/test_gen_data_cli.py::TestRecordImageFormats` — the
  `gen-data --format record|hex` flags, that CSV output is unchanged by any
  of them, and (counting `encode_record` calls) that `--output` encodes the
  dataset exactly once. `::TestRecordFormatFlag` covers `--record-format`
  alongside it
* `tests/unit/generators/data/test_variable_length.py` — fixed vs variable
  record length: ODO layout linking, per-row trimming, counter bounds, RDW
  framing, and the length reporting built on them.
  `TestFdRangeWithoutDependingOn` (#320) pins that an FD range with no
  DEPENDING ON writes every record at its own 01's full length, never cut
* [cli.md](cli.md) — `tests/unit/cli/` covers CLI subcommands
* [generators.md](generators.md) — flowchart, copybook → CSV, program layout
  index, and program fixture bundle generator tests
* [analysis.md](analysis.md) — `tests/unit/analysis/` covers analyzers
* [parser.md](parser.md) — `tests/integration/` covers end-to-end parsing

## 2026-10-08

`tests/regression/test_bug_hunt_2026_10_08.py` pins the 2026-10-08 bug hunt:
picture scan stopping at a same-line gap (`PIC X(3) VALUES ...`, `BASED`),
recursion-risk escapes ignoring IF/EVALUATE branch edges, the
unused-variable references (PERFORM TIMES, WRITE ADVANCING, INITIALIZE BY,
CORRESPONDING, XML/JSON groups, digit-led names) and the matching xref
reads, bare-CR copybook expansion, `>>IF` in a copybook, signed NATIONAL
width, and `jcl --dd-map --program`. The abbreviated-condition fix is pinned
in `test_review_2026_09_09_parser.py` (`TestFinding08ConditionTrees`); the
JCL omitted-sub-parameter slot in `tests/unit/test_jcl.py`.

`tests/regression/test_keyword_line_breaks.py` (issue #385) parses each
keyword pair (STOP RUN, WHEN OTHER, 88/66 names, FD/SD, CALL ON EXCEPTION,
ENTRY, EXEC SQL/CICS/DLI, END DECLARATIVES, SPECIAL-NAMES, OBJECT
REFERENCE, ...) once on one line and once broken across two, and requires
identical ASTs apart from locations; it also pins the dispatch cache
telling EXEC<newline>SQL from EXEC<newline>CICS within one parse.

`tests/regression/test_condition_expression_separators.py` (issue #386)
pins a separator `,` / `;` after an IF condition, a PERFORM UNTIL condition
(inline, out-of-line, VARYING), an EVALUATE subject or WHEN selector, a SEARCH
WHEN condition and a COMPUTE expression
being dropped, and a comma inside `FUNCTION MAX(X, Y)` being kept.

`tests/regression/test_fd_record_after_label_data.py` (issue #401) pins
RECORD CONTAINS / RECORD VARYING written after LABEL RECORDS or DATA RECORD:
the `fd_clauses["record"]` length and `ProgramLayoutIndex.file_facts()`
record length survive every clause order, and `data_records` holds only the
record names.

### Field lineage (2026-10-08)

`tests/samples/lineage/` holds a three-program chain plus its JCL: WRITER
(READ INTO, COMPUTE, WRITE, CALL SUBPGM, UPDATE ACCOUNT), SUBPGM (LINKAGE),
READER (reads the SORT-SUMmed output, keyed READ on a VSAM master, SELECT
from ACCOUNT), MISC (CORRESPONDING, group overlay, refmod, STRING, ACCEPT,
SORT USING/GIVING, dynamic CALL) and FEEJOB.jcl. They feed
`tests/unit/analysis/test_field_lineage.py`, `test_lineage_graph.py`,
`test_lineage_jcl.py` (duck-typed jobs; the jcl-parser end-to-end tests
`importorskip("jclparser")`, which CI does not install), `test_sql_flow.py`
and `tests/unit/cli/test_lineage_cli.py`. The `field-impact` CLI tests pass
`--workers 1`: scan's process pool under pytest-cov fails to pickle its
work items. `tests/unit/test_scan.py`'s failing-analyzer stub takes the new
`source_map` argument of `_run_analyzer`.
`TestStoredJoinEdges` (test_lineage_graph.py) pins that a graph rebuilt
from `join_edges()` answers every query identically; `test_lineage_jcl.py`
covers `jobs_from_sources` (in-memory JCL + PROCs).
`TestTableFunctionDetection` (test_sql_flow.py, #340) pins that only
`TABLE(...)` is a table function: `TABLE_CUST` / `TABLES_CFG` / `TABLEX`
are traced as ordinary tables.
Review regressions (2026-10-08) use small inline programs (`_program` in
test_field_lineage.py, `_source` in test_lineage_graph.py):
`TestOccursDependingOn` / `TestOccursTables` (None offsets, every
occurrence inexact, `AMT(3)` exact, >1024 occurrences), `TestDuplicateNames`,
`TestOperands` (CALL subscript/refmod/qualifier, subscripts not values,
CORRESPONDING group vs elementary), `TestArithmeticCorresponding`
(ADD / SUBTRACT CORRESPONDING pair numeric items by name path only, no
cross product: issue #337), `TestAccept` (ACCEPT FROM DATE /
DAY / DAY-OF-WEEK / TIME make no console port), `TestReturning`; `TestStoredJoinState`
and `TestReviewFixes` (RETURNING join, schema candidates, occurrence join
at the right reader field, duplicate PROGRAM-ID, NULLFILE, MQI names,
`start_found`); `TestConcatenationAndOperands` (lineage_jcl); and the
`field-impact` exit-code / text tests in test_lineage_cli.py.

## 2026-10-10

`tests/unit/analysis/test_lineage_jcl.py`: `TestOrdinarySteps::test_ims_batch_binds_the_parm_program`
(PARM as string, list, parenthesised, quoted lower-case),
`test_ims_controller_without_program_parm_is_unchanged`, and
`test_ims_batch_proc_binds_the_application_program` (jcl-parser end to end:
an IMSBTCH-shaped PROC and a direct `PGM=DFSRRC00,PARM=(DLI,...)`).

`tests/unit/cli/test_analyzer_cli_gaps.py::TestPartialParseWarning` pins that
`parse --find-type` exits 2 on a recovered-but-errored parse, like plain
`parse`.

## 2026-10-11

`tests/unit/analysis/test_field_lineage.py::TestDynamicCallFigurativeCandidates`
pins that a dynamic CALL's SPACES / LOW-VALUES / HIGH-VALUES candidates
make no `call:` port (no blank `#1`, no `\x00#1` / `Ÿ#1`), and that a CALL
whose only candidates are figurative falls back to `?IDENT#n` plus the
caveat.
ZERO is pinned there too, along with `callee_names` itself.
`test_codebase.py::TestDynamicCalls::test_figurative_candidates_make_no_call_edge`
/ `test_only_figurative_candidates_are_reported_unresolved` pin the same for
codebase-graph, and
`test_boundary_inventory.py::TestDynamicCallSentinelCandidates` pins the
"no possible target values resolved" note when only sentinels remain.

## 2026-10-14 (issue #342)

`test_environment_division_parser.py::TestInputOutputSection::test_separator_comma_and_semicolon_not_kept_in_names`
pins that a comma/semicolon after `ASSIGN TO ddname` or between the two
FILE STATUS variables is not kept in the name, and
`test_field_lineage.py::test_separator_after_assign_names_the_dd_port`
that the lineage file port is `INDD`, not `,`.

## 2026-10-14

`tests/unit/test_compute_bare_size_error.py` pins that COMPUTE ends its
expression at a bare `SIZE ERROR` (no `ON`), with the handler body landing
in `on_size_error` rather than the paragraph; covers the `IF ... END-COMPUTE`
nesting and a bare `NOT SIZE ERROR` (#399).

`tests/unit/analysis/test_ast_diff.py::test_equivalent_picture_spellings_are_not_a_change`
/ `test_usage_synonyms_are_not_a_change` pin that `diff` compares a PICTURE
by its character positions (`X(2)` = `XX`) and a USAGE by its storage format
(`COMP-3` = `PACKED-DECIMAL`, `COMP` = `BINARY` = `COMP-4`), while `COMP` ->
`COMP-5` is still a change.

`tests/unit/cli/test_analyzer_cli_gaps.py::TestDefinitionsAndExitsStampOrigins`
pins that with `--copybook-path` xref's `definition` gains
`definition_origin` (a WORKING-STORAGE item and a paragraph after a COPY,
and an item inside the copybook) and program-flow's
`exit_statement_location` gains `exit_statement_origin`; none without
expansion (#367).

`tests/regression/test_optional_keyword_forms.py` (#405) pins the
optional-keyword forms that used to lose data: `XML PARSE x PROCEDURE IS p`
without PROCESSING (and dead-code not reporting `p`), SORT bare
`DUPLICATES`, SORT/MERGE bare `SEQUENCE name` and `KEY IS k`, the
no-keys warning on a file SORT/MERGE (not on a table SORT), and
SPECIAL-NAMES mnemonic entries and `SYMBOLIC CHARACTERS` without IS.
`test_initialize_sort_arithmetic_comma_gaps.py`'s two USING/GIVING comma-list
SORTs gained a key, since a keyless file SORT now warns.

## 2026-10-14 (issue #396)

`tests/unit/analysis/test_sql_cics_lint.py` replaces the test that pinned
`IGNORE CONDITION` as cancelling a handler with five that pin it as handling:
`IGNORE CONDITION ERROR` (alone or replacing a label handler) clears
`CICS_NO_RESP_HANDLING`, a narrower `IGNORE CONDITION NOTFND` goes to
`unchecked`, a bare `HANDLE CONDITION ERROR` afterwards restores the finding,
and `PUSH HANDLE` suspends an ignore like any other handler.
## 2026-10-14 (issue #402)

`tests/regression/test_optional_keyword_forms_402.py` pins the four optional-
keyword forms: `OCCURS n TO UNBOUNDED`, FD `RECORD VARYING n TO m` without
FROM, `ENTRY ... USING [BY] REFERENCE/VALUE` (operands and
`parameter_modes`, plus the signature's `by_clause`), and `INITIALIZE ...
FILLER` without WITH. `test_program_signature.py::test_by_clause_is_set_and_rendered_where_the_mode_changes`
now expects an ENTRY operand's `by_clause` to be `"REFERENCE"`, not None.
## 2026-10-14 (issue #388)

`tests/unit/test_call_using_mode_without_by.py` pins that a bare
`REFERENCE` / `CONTENT` / `VALUE` in `CALL ... USING` (BY omitted) switches
the passing mode instead of being recorded as an argument, alone and mixed
with `BY` phrases, literals and figurative constants.

## 2026-10-14 (issue #349)

`tests/unit/analysis/test_sql_whenever_references.py` (28 tests) pins that
`EXEC SQL WHENEVER SQLERROR|SQLWARNING|NOT FOUND GO TO p` (also `GOTO`,
`:p`, lowercase) keeps `p` out of dead-code and lint, that `CONTINUE` and an
unknown target reference nothing, and that program flow carries one
`SQL_WHENEVER` edge per procedure holding covered SQL. `TestCoverageIsSourceOrder`
pins the source-order model: a directive in a never-performed setup
paragraph still covers SQL that runs, SQL before the directive or only in a
dead paragraph is not a branch, CONTINUE is per condition, declarations are
not covered, and dead-code and program flow agree on every case.
## 2026-10-14 (issue #351)

`tests/unit/analysis/test_codebase.py::TestLibraryQualifiedCopy` pins that
`COPY REC OF LIBA` / `COPY REC IN LIBB` resolve to each library's own file in
codebase-graph, that a nested COPY inside `LIBB/REC` reaches only the programs
copying `LIBB/REC` (chains `[PB, REC, INNER]`), that `copybook-impact` on a
member name resolving to several files unions their fields and says so, and
that a hand-built nested `CopyEdge` without `parent_path` still matches by name.
`TestLibraryQualifiedCopyReview` (#445 review) pins that a COPY whose library
did not resolve is never the parent of a nested edge read from a resolved
file, and that DOT/Mermaid draw `REC -> INNER` once when two libraries' REC
both copy INNER.
