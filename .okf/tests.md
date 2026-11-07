---
type: Reference
title: Tests
description: Test suite layout (tests/ directories, corpora, conftest fixtures), pytest markers and their per-directory enforcement, the 90% coverage floor and why it is measured on pure Python, the CI jobs in .github/workflows/ci.yml (manual dispatch only), and the conventions a new test must follow.
tags: [tests, pytest, coverage, fixtures, markers]
timestamp: 2026-10-28T00:00:00Z
---

# Tests

The suite lives under `tests/` and runs with plain pytest: **~15,640 tests
collected from 636 `test_*.py` files** (`python -m pytest tests --collect-only
-q --no-cov`, 2026-10-29). Configuration is `[tool.pytest.ini_options]` in
`pyproject.toml` (`testpaths = ["tests"]`, `--strict-markers`, coverage on by
default with a **90% floor**, branch coverage enabled). Two shared fixtures
(`parser`, `samples_dir`) come from `tests/conftest.py`; four markers
(`integration`, `slow`, `contract`, `io`), three of them applied structurally
by per-directory `conftest.py` files.

Getting started: `pip install -e ".[dev]"`, then `python -m pytest
tests/unit/test_lexer.py --no-cov` for a single file (`--no-cov`, because a
subset always fails the 90% floor), or `python -m pytest tests/ -n auto` for
the whole suite with coverage (`pytest-xdist` is in `[dev]`). The library is
pure Python, so coverage sees every line.

Where to put a new test: `tests/unit/` (one component; analyzers under
`unit/analysis/`, CLI under `unit/cli/`, record encoding/decoding under
`unit/generators/data/`), `tests/regression/` (a pinned bug fix, usually
named for the issue or finding), `tests/integration/` (end-to-end over a
corpus), `tests/contracts/` (public API shapes other repos depend on). Before
writing one, read [Writing tests](#writing-tests): fixed-format fixtures have
a column-72 trap, and several registries are pinned by self-maintaining tests.

## Contents

- [Directory Layout](#directory-layout)
- [pytest Markers](#pytest-markers) (incl. per-directory enforcement)
- [Shared Fixtures](#shared-fixtures-testsconftestpy)
- [Running Tests](#running-tests)
- [Example Corpora](#example-corpora)
- [Enterprise program-type corpus](#enterprise-program-type-corpus)
- [Writing tests](#writing-tests) -- conventions and traps
- [Where behaviour is pinned](#where-behaviour-is-pinned) -- notable test files by area
- [Coverage Requirement Detail](#coverage-requirement-detail)
- [CI/CD](#cicd)
- [OKF guards](#okf-guards)
- [See also](#see-also)

## Directory Layout

File counts are `test_*.py` files, recursive, as of 2026-10-17.

```
tests/
  conftest.py                  # shared fixtures: parser(), samples_dir()
  test_all_samples.py          # smoke-tests every tests/samples/*.cbl program
  test_okf_staleness_map.py    # OKF_MAP guard (see "OKF guards")
  test_okf_claims.py           # OKF content guard: the docs' claims vs the code
  test_readme_examples.py      # every README command / Python API example, run as written (slow)
  unit/                        # 302 files: individual components (203 directly in unit/)
    test_copybook_data_generator.py  # copybook -> CSV: flattening, categories, value constraints, options, dataset surface, TestFloatValueClauses (#551)
    test_program_layout_index.py     # ProgramLayoutIndex: FD/record resolution, FD-vs-SD tagging, FileFacts, name resolution, qualified level-88 names (resolve/condition_values/gen-fixtures arms, #272), record_named(), multi-program units, from_file errors (see generators.md)
    test_program_fixtures.py         # ProgramFixtureGenerator: bundle assembly, CALL-argument fixtures (IN/OUT/BIDIRECTIONAL notes), SQL fixtures, determinism, write_csv_dir (csv-dir <-> JSON round trip, one directory per scenario, distinct CSVs on a forced name collision); TestScenarioModes (witness pinning incl. compound SEARCH WHEN #348, empty-input, boundary min-max, scenario_coverage); TestTier1CallCountExpectations / TestTier2FieldEqualsExpectations; TestTargetedArmsAreVerified (#244); TestFailurePathExpectations (#318); TestCallCountFollowsControlFlow (#363); TestMultipleRecordsUnderOneFd (#364); TestArmsOnTwoRecordsOfOneFd; TestFillerOwningConditionName; TestCallFixtureSameNamedFields (#365); TestKeyedReadReturnsTheKeyAskedFor (#322); TestFloatFieldArms (#551); TestFieldEqualsAfterARunEndingArm (#591) (see generators.md)
    test_scenario_planner.py         # ScenarioPlanner: THEN/ELSE targeting, disjoint-field merging, unsatisfiable arms, fixed families (empty-input/error-status/boundary-values), exact coverage accounting, TestScenarioNamesAreUnique (#267) (see generators.md)
    test_extended_verb_parsers.py    # 2026-09-02 statement-coverage audit: every Report Writer / Communication / legacy / COBOL 2002 verb -> node, operands, no warnings; UNSUPPORTED_VERBS == {EXECUTE, GOTO, RECOVER}; every STATEMENT_KEYWORDS verb dispatches (see parser.md)
    test_function_id.py              # FUNCTION-ID units (IBM 6.4 user-defined functions): unit_kind/external_name, END FUNCTION, REPOSITORY entries, function_references, codebase `function` edges, FUNCTION call_example
    definitions/                     # test_definitions.py (CSD, BMS, DDL, DBD, PSB parsers over tests/samples/definitions/); test_issues_800_802.py (JCL jobs and Python never detected as definitions, #800; view base_tables without CTEs / function FROMs / TABLE(), DEFAULT NULL, inline UNIQUE / ON DELETE, #801; PSB NAME= as DBD name, PROCSEQ, #802) (see definitions.md)
    analysis/                  # 50 files: every analyzer
      test_call_interface.py   # CallInterfaceChecker / call-check: count, passing mode, length (short=error, long=info), usage, RETURNING, argument shapes, dynamic/ENTRY/nested targets, CLI exit codes (--fail-on after --min-severity)
      test_boundary_inventory.py  # BoundaryInventoryAnalyzer: per-category key/layout/direction, nested-body reachability, CALL argument-direction ladder, structure-qualified SQL host variables, ACCEPT filtering, IOLogger cross-check
      test_constraints.py      # ConstraintExtractor: relational/level-88/figurative/class-sign forms, AND/OR/NOT via De Morgan, EVALUATE TRUE + 88s, WHEN OTHER, SEARCH WHEN (#348), PERFORM-UNTIL SequenceConstraint
      test_domains.py          # domains.solve(): numeric/text/enum domains, witness-satisfies-constraint property, Unsatisfiable never returns a value, level-88 pick re-checked against gt/ge/lt/le (#244), TestFloatDomain: COMP-1/COMP-2 signed fractional domain (#551), TestNumericClassOnAlphanumeric (NUMERIC over the whole width), TestOdoCounterDomain (ODO counter within its table's bounds)
      test_dclgen_check.py     # DclgenChecker: column <-> host-variable pairing, every violation kind/severity, both null-indicator syntaxes, what it declines to check, "DCLGEN's own output is always clean" table
      test_const_fold.py       # ConstantFolder: MOVE/arithmetic/COMPUTE folding, GIVING, loop/branch poisoning, DIVIDE poison, PERFORM chaining, GO TO/STOP RUN, observation points; TestStorageAliasing (#245), TestValueAtObservationPoint (#246), TestWalkBudget, TestInspectAndExecWrites (#317), TestReadKeys (#322), run enders inside an arm (#591, TestControlFlowStops)
      test_invocation_counts.py  # count_invocations (#363): status-check exemption (success-arm evaluation, #590), unknown-count bodies, EXIT PARAGRAPH, literal TIMES, fall-through + PERFORM, GO TO following
    cli/                       # 29 files: CLI subcommands
      test_decode_cli.py       # decode: CSV/JSON/hex, --view / --list-views, gen-data -> decode round trip, paging, trailing bytes, --strict, non-UTF-8 copybook one-line error (#496); dclgen-check subcommand and lint rule
      test_gen_fixtures_cli.py # gen-fixtures: flags, --list-boundaries, --format json|csv-dir, --strict exit codes
    test_flowchart_generator.py      # Mermaid/DOT flowcharts: label fidelity, quoting, escaping (see generators.md)
    generators/                # 17 files (6 here: bug-hunt r11, cross-record correlation (carrier detection incl. lossless carriers #758 and no READ or GO TO before the MOVE #762, two-row planning, verification, GnuCOBOL oracle; sample in `tests/samples/correlation/`), entry parameters, row witnesses, scenario verification (incl. early-exit guards, TestEarlyExitGuards), VSAM FILE STATUS scenarios (codes by file organization, OPEN mode and key of reference); + data/)
      data/                    # 11 files: compare, decoding, editing, encoding, layout, layout_offsets, program_layout_conditions, storage, values, variable_length, views
        test_views.py          # build_record_views(): running offsets vs real encoded bytes, REDEFINES overlays (every occurrence inside OCCURS, FILLER padding, nested overlays #296), short-name lookup, ODO ambiguity, contiguity property
        test_decoding.py       # RecordDecoder: decode(encode(row)) == row for every storage class and both charsets, ODO under every RecordFormat, RDW framing, overlay switching, sign conventions read but never written, bad bytes reported per field, paging, hex pane
    io_statements/             # 7 files: IO parser unit tests (`io` marker)
  integration/                 # 32 files: end-to-end over corpora (`integration` marker)
    test_shamrice_examples.py  # all examples/cobol/shamrice/*.cbl parse error-free
    test_nist_cobol85_support.py  # all 459 NIST *.CBL parse error-free (strict-xfail KNOWN_ISSUES ratchet, empty); copybook validation
    test_enterprise_program_types.py  # tests/samples/enterprise/ (see below)
    test_copybook_csv_generation.py   # sample + NIST *.CPY: gen-data never crashes; no-layout copybooks raise CopybookLayoutError; every cell fits its field
    test_data_item_layout_corpus.py   # compute_program_data_items() over fixtures and shamrice
    test_program_layout_corpus.py, test_boundary_inventory_corpus.py, test_gen_fixtures_corpus.py,
    test_constraint_extractor_corpus.py, test_scenario_planner_corpus.py, test_const_fold_corpus.py
                               # gen-fixtures phases 1-7 parametrised over shamrice: no raise, no unexpected unresolved, layout-valid values, exact coverage accounting
    io/                        # 1 file: IO coverage reporting integration (`io` too)
    io_statements/             # 2 files: IO statement parsing, VSAM (`io` too)
  contracts/                   # 21 files: API contract tests (`contract` marker)
    test_fixture_bundle_contract.py  # FixtureBundle: exported names, bundle_version, generator signatures, to_dict() key sets, reproducibility, scenario-mode contract (see docs/fixture-bundle-schema.md)
    io_statements/             # 1 file (`io` too)
  regression/                  # 262 files: pinned bug fixes, typically named for the issue/finding, e.g.
                               #   test_swallow_sweep.py: one period-less snippet per registered statement
                               #     parser x a DISPLAY 'MARKER'. sentinel; fails if a new parser is
                               #     registered without a fixture (see parser.md)
                               #   test_statement_coverage_audit_2026_09_02.py: EXEC CICS/DLI in
                               #     get_all_statements(), handler boundaries, NIST no-drop-warning guard
                               #   test_open_findings_high_regressions.py / ..._medium_regressions.py:
                               #     reports/open-findings.md H1-H8 / M-series
                               #   test_nist_edge_case_fixes.py: minimal repros of NIST edge cases
                               #   test_open_gaps_2026_11_06.py: PERFORM-only paragraphs do not fall
                               #     through, CALL fixture direction, IncompleteRecordImageWarning
  eval/                        # the MCP benchmark's tasks next to the code (tests/eval/README.md)
    test_answer_keys.py        # `integration` in-file: every tasks.json task's tool answer states its key's facts, over the shop build_shop.py assembles (shop/ + samples + NIST); a task without a test fails
                               # + run_eval.py (a script, not collected: headless Claude Code with/without the MCP server, a judge, a report; writes .eval-runs/)
  performance/                 # test_factory_performance.py (`slow`; absolute floors skipped under a tracer); test_large_program.py (per-analyzer time budgets on a generated program: 4,000 lines by default, 40,000 plus a x4-size scaling check under COBOLPARSER_PERF=1)
  samples/                     # shared COBOL fixtures: 48 *.cbl at top level
    copybook_programs/         # programs with COPY statements
    copybooks/                 # .CPY files
    definitions/               # ACCTSET.bms, BANKCSD.csd, BANKPCT.asm, BANKDDL.ddl, CUSTDBD.dbd, CUSTPSB.psb (cobolparser.definitions)
    enterprise/                # 22 programs, one per IBM Enterprise COBOL program type, + copybooks/
    io/positive/, io/negative/ # valid / invalid IO patterns
    jcl/                       # invupdt.jcl, payproc.jcl
    lineage/                   # WRITER/SUBPGM/READER/MISC .cbl + FEEJOB.jcl (field-lineage chain)
```

## pytest Markers

Declared in `pyproject.toml` (`--strict-markers`, so an undeclared marker is
a collection error):

| Marker | Meaning |
|--------|---------|
| `integration` | Integration tests |
| `slow` | Slow-running tests (`tests/performance/test_factory_performance.py` and `test_large_program.py`) |
| `contract` | API contract tests |
| `io` | IO statement tests (OPEN, CLOSE, READ, WRITE, REWRITE, DELETE, START, ACCEPT, DISPLAY, UNLOCK) |

```bash
python -m pytest -m "integration"    # integration tests only
python -m pytest -m "slow"           # slow tests only
python -m pytest -m "contract"       # API contract tests only
python -m pytest -m "io"             # IO statement tests only
```

### Per-directory marker enforcement

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

In-file `pytestmark = pytest.mark.<x>` lines in these directories are
harmless duplicates, not required. A file *outside* these directories can
still opt in explicitly (e.g. `tests/unit/test_ims_segment_analyzer.py`,
`tests/regression/test_nist_edge_case_fixes.py`).

## Shared Fixtures (`tests/conftest.py`)

| Fixture | Returns |
|---------|---------|
| `parser()` | Fresh `CobolParser` instance |
| `samples_dir()` | `Path` to `tests/samples/` |

## Running Tests

```bash
# All tests with coverage (90% min); -n auto (pytest-xdist) is optional
python -m pytest tests/ -v

# Single file / single test (--no-cov: a subset always misses the floor)
python -m pytest tests/unit/test_lexer.py -v --no-cov
python -m pytest tests/integration/test_call_comprehensive.py::TestCallComprehensive::test_call_with_periods -xvs --no-cov

# By directory (no dedicated marker needed)
python -m pytest tests/regression/ -v
python -m pytest tests/contracts/ -v
python -m pytest tests/performance/ -v
```

Running only a subset of tests with coverage on will trigger a coverage
failure -- that is expected.

## Example Corpora

| Path | Contents |
|------|----------|
| `tests/samples/` | 48 COBOL programs covering all statement types, smoke-tested by `test_all_samples.py` |
| `tests/samples/enterprise/` | 22 programs, one per IBM Enterprise COBOL program type (see next section) |
| `examples/cobol/` | NIST COBOL-85 test suite (459 .CBL files + 51 .CPY copybooks); **all 459** parse error-free, pinned by `test_nist_cobol85_support.py`. Its strict-xfail `KNOWN_ISSUES` ratchet is empty (a new entry must be a known, tracked failure); SM101A is parsed through copybook expansion (`REQUIRES_COPYBOOK_EXPANSION`) since its COPY members are statement fragments. Minimal repros for NIST edge cases live in `tests/regression/test_nist_edge_case_fixes.py` |
| `examples/cobol/shamrice/` | 24 IBM COBOL programs from shamrice/COBOL-Examples; all parse cleanly under FAIL_FAST; the gen-fixtures corpus tests sweep it |

## Enterprise program-type corpus

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
and every subcommand that parses COBOL) and `debug_line_numbers` (#334).
`test_all_samples.py` covers the corpus too, since it lives under
`tests/samples/`. The same 22 files are copied into
`mocky-mock/tests/fixtures/enterprise/`, where
`mocky-mock/tests/unit/test_enterprise_corpus.py` pins `mockymock generate`'s
outcome per program (that path is in the *sibling* repo, not this one).

`tests/unit/test_enterprise_syntax.py` pins each construct the corpus
surfaced in isolation: PROGRAM-ID attributes, OO units, DECLARATIVES,
`USE BEFORE REPORTING`, the 6.x data clauses, `OCCURS UNBOUNDED`, JSON
`CONVERTING`, `RETURNING`, `SET ADDRESS OF`, conditional compilation by
default, and REPLACE partial words. Tests elsewhere rely on three behaviours
the corpus required: a missing period after the `PROGRAM-ID` keyword is
tolerated (IBM), the mandatory-PROGRAM-ID message names CLASS-ID /
METHOD-ID too, and an unknown `>>` directive is blanked rather than passed
through.

## Writing tests

Conventions and traps that have each cost real debugging time:

* **Column 72 in fixed-format fixtures.** `normalize_fixed_format` drops
  columns 73+ exactly as a compiler does, silently. A test template that
  appends a clause to a deep-indented line (an FD's `RECORD` clause, an
  `OCCURS ... DEPENDING ON <var>`) loses it with no error; put the clause on
  its own line. `test_all_samples.py::TestSampleCorpus` fails any
  `tests/samples/*.cbl` with **non-whitespace** past column 72 (trailing
  spaces are allowed: dropping them changes nothing) and requires every
  sample to parse error-free except the two in `EXPECTED_PARSE_ERRORS`
  (`error_recovery_tests.cbl`, purpose-built malformed input;
  `special_names_config.cbl`, a non-ASCII `¥` currency symbol the lexer
  rejects). Sample programs feed thousands of other tests, so a truncated
  sample silently changes what they assert against.
* **Self-maintaining registries.** Registering a statement parser means
  adding a `FIXTURES` entry to `tests/regression/test_swallow_sweep.py` and
  an `EXPECTED_ORDER` position plus a `DISPATCH_CASES` case to
  `tests/unit/test_procedure_registry_dispatch_order.py`; both fail when a
  parser has no fixture. A new enterprise program type goes in both the
  directory and `PROGRAM_TYPES`. A new `cobolparser/` file needs an
  `OKF_MAP` entry ([OKF guards](#okf-guards)).
* **Contract key sets and goldens.** An additive key on a public shape is
  pinned in the matching `tests/contracts/` key set (e.g.
  `test_copybook_data_generator_contract.py`'s `_FIELD_SPEC_KEYS`), and
  `tests/regression/test_fixturedemo_golden.py`'s golden bundle is
  regenerated when its serialized shape changes (check no generated value
  moved).
* **Record-image fixtures come from the encoder.** Decode / compare tests
  build their inputs with `encode_record`, not hand-built decode results, so
  a round trip is what is tested. Encoding values were checked against
  GnuCOBOL; a new expected byte string should be too.
* **Positive controls for negative assertions.** An "X is not reported"
  test should also declare something that *is* reported (an unused
  `WS-DEAD`), so a parser regression that drops the declarations cannot make
  it pass vacuously.
* **Process pools under coverage.** `field-impact` CLI tests pass
  `--workers 1`: scan's process pool under pytest-cov fails to pickle its
  work items. `jcl-parser` is in `[dev]`, but jcl end-to-end tests still
  `importorskip("jclparser")`.
* **Patching file reads.** The expander opens files itself, so patching
  `Path.read_text` affects only helpers that use it (e.g. lint's column
  re-read) -- useful, but check which reader a test actually patches.
* **Changing a pinned behaviour.** When a fix inverts what a test pinned,
  replace the old test (and name the new behaviour in it) rather than
  deleting it; the archive in [history](history/tests.md) records which
  tests changed meaning and why.

## Where behaviour is pinned

Notable test files by area, beyond those in the layout above. Most
regression files are named for their issue (`test_issue_NNN_*.py`) or audit
(`test_audit_<date>*.py`, `test_bug_hunt_*.py`); grep
[history](history/tests.md) for a file name to find what it pins and why.

| Area | Test files |
|------|-----------|
| Preprocessing / COPY / REPLACE | `regression/test_audit_2026_09_17_preprocessing.py` (record-only line splitting, EBCDIC NL, REPLACING text words), `test_copy_member_case_folding.py`, `test_issue_580_copy_member_as_written.py` (codebase-graph / copybook-impact / MCP resolve COPY members as written; no self-suggestion), `test_copy_replacing_identifier_operand.py`, `test_copy_replacing_literal_operand.py`, `test_copy_replacing_across_lines.py` (#560, #561), `test_copy_replacing_leading_trailing_once.py` (#513; written clause order), `test_comment_entry_copy_replace_scan.py`, `test_replace_before_identification_division.py`, `test_tagged_sequence_area_detection.py`, `test_numbered_blank_copybook_lines.py` (lines holding only a sequence number count as fixed format), `test_source_format_free_first_line.py` (#502; a column 1-6 opening directive decides free, a column-8 one keeps a later `>>SOURCE FIXED` section), `test_expansion_width_and_tags.py`, `test_version_tag_line_handling.py`, `test_normalize_column_overflow_warning.py`, `test_fixed_format_word_boundary_overflow.py`, `test_conditional_compilation_literals.py`, `test_conditional_compilation_word_operators.py` (#512; incl. the undefined-symbol warning inside parentheses), `test_conditional_compilation_stacked_when.py` (#492), `test_define_as_variable.py` (#567; `AS A` and `AS (A)`), `test_expansion_source_map_and_comments.py` (incl. #581 CR-only / CRLF `--keep-comments`) (incl. #355 text after a COPY's period); `unit/test_preprocess_init_coverage.py::TestValidateCopybookContent` |
| Lexer / literals | `regression/test_inline_comment_stripping.py`, `test_literal_concatenation.py`, `test_issue_479_mixed_hex_concatenation.py` (`'AB' & X'0102'` joined, written and round-tripped in both charsets), `test_doubled_quote_literal_values.py`, `test_dead_keyword_removal.py`, `test_sql_name_chars.py` (`#` / `@` inside EXEC SQL names; a declared currency sign outside), `test_all_digit_procedure_names.py` (`1000-0` is one word outside EXEC), `test_stray_characters_never_fail_the_file.py` / `test_stray_sql_chars.py` (an unknown character outside EXEC is dropped with a warning, never a lexer error; `#` / `@` in a data name glued), `test_copybook_template_placeholders.py` (`(9999-)NAME` / `:PFX:-NAME` lex as one name, also inside a condition's parentheses; CardDemo `CSSETATY.cpy` standalone and through COPY REPLACING) |
| Parser statements | `regression/test_swallow_sweep.py`, `test_keyword_line_breaks.py` (#385), `test_condition_expression_separators.py` (#386), `test_optional_keyword_forms.py` / `_402.py`, `test_evaluate_*` (stacked / figurative / word-operator WHEN), `test_arithmetic_qualifier_chain.py`, `test_move_qualifier_chain.py`, `test_tier8_arithmetic_scope_terminator.py`, `test_special_register_paragraph_boundary.py`, `test_go_depending_without_on.py`, `test_issue_258_same_named_items.py`, `test_implicit_paragraph_trailing_period.py` (#503), `test_call_function_argument.py` (#579), `test_initialize_phrase_line_breaks.py` (#575), `test_separator_comma_operands.py` (#569), `test_inspect_tallying_multiple_phrases.py` (#332), `test_language_env_when_inspect_functions_issue_506.py` (INSPECT keeps a `FUNCTION` operand whole; language-env scans EVALUATE / SEARCH WHEN and INSPECT operands, not a literal inside a WHEN condition, #506), `test_multiply_divide_receivers.py` (#534), `test_multiply_divide_giving_operands_issue_495.py` (MULTIPLY/DIVIDE GIVING `source_operands`, business-rules formula, statement text / diff INTO vs BY, #495), `test_rounded_per_receiver.py` (#517), `test_legacy_verb_data_names.py` (#525, incl. an undeclared verb ending a COMPUTE), `test_unrecognised_input_ast_contract_issue_368.py` (#368: no division -> empty UNKNOWN program, not None), `test_deep_nesting_recursion_issue_375.py` (#375: 3,000-term chains, nesting past the recursion limit), `test_cancel_literal_vs_identifier_issue_479.py` (#479), `test_string_delimiter_groups_issue_576.py` (#576), `test_continue_after_seconds_issue_578.py` (#578); `unit/test_perform_until_newline.py`, `test_call_using_mode_without_by.py`, `test_compute_bare_size_error.py`, `test_report_section.py`, `test_xml_json_structured_clauses.py` (incl. `CONVERTING x [FROM or TO] JSON BOOLEAN` before ON EXCEPTION, #574), `test_extended_verb_parsers.py`, `test_display_parser.py` (screen phrases; a declared COLOR / POS / COL is an item, #821) |
| EXEC SQL | `unit/test_exec_sql_fetch_orientation.py`, `_host_variable_lists.py`, `_literals_comments.py`, `_merge_cte.py`, `_qualified_tables.py`; `regression/test_sql_delimited_identifiers_issue_597.py` (`"PROD"."CUST"` delimited identifiers reach `tables` and the CRUD matrix, #597), `test_dclgen_null_indicator_direction_issue_530.py` (dclgen-check null-indicator only on outputs, #530), `test_host_var_dclgen_column_names_issue_572.py` (HostVariableResolver links `:CUST-ID` to column `CUST_ID`, #572) |
| Dead code / program flow | `unit/analysis/test_dead_code.py` (`TestTransitiveDeadCode`, `TestSectionExitGoTo`, `TestFallThroughReferences`, `TestFallThroughEdges`), `test_program_flow.py`, `test_exit_section_and_alterable_goto.py`, `test_cics_terminators.py`, `test_sql_whenever_references.py`; `regression/test_issue_586_exhaustive_branch_terminator.py` (an IF/ELSE or EVALUATE ... WHEN OTHER whose every arm terminates ends the paragraph), `test_issue_373_recursion_check_restart_idiom.py` (recursion-check linear per cycle on the GO TO restart idiom), `test_thru_section_end_issue_577.py` (a SECTION THRU end includes its paragraphs in `range_members` and MCP `callers_of`, #577), `test_declaratives_no_fall_through_issue_533.py` (no FALL_THROUGH out of a DECLARATIVES section; MCP `callers_of` MAIN empty, #533), `test_recursion_check_entry_names_issue_515.py` (a CALL to the program's own or a container's ENTRY name is self-recursive, #515); `unit/analysis/test_issue_842_section_fall_through.py` (a section entered through one paragraph frees none of its later members; PERFORM THRU stops at its end, #842) |
| Other analyzers | `unit/analysis/test_unused_variables.py` (an undecomposed PERFORM UNTIL guard still references its fields: `regression/test_issue_539_user_class_and_omitted_conditions.py`; SQL host structures / VARCHAR 49-levels used whole, #531, and WORKING-STORAGE DECLARE CURSOR host variables, #378: `regression/test_sql_host_structure_unused_issue_531.py`; `PERFORM 1000-INIT` is no reference to data item `INIT`, #487: `regression/test_digit_led_paragraph_tail_issue_487.py`), `test_io_sequence*.py` (and `regression/test_issue_548_io_open_mode.py`: verbs vs OPEN mode, OPEN after CLOSE WITH LOCK, no WRITE-under-I-O judgment without a SELECT), `test_move_type_checker.py` (and `regression/test_move_special_registers_issue_520.py`: LENGTH OF / SORT-RETURN / WHEN-COMPILED / XML-CODE ... resolve, #520), `test_xref.py` (incl. level-88s under a FILLER and level-66 RENAMES, #485; RENAMES in `data-items` / MCP `record_layout` (an unplaceable one caveated), #563: `regression/test_issue_563_renames_data_items.py`; SPECIAL-NAMES declarations, #519: `regression/test_issue_519_xref_special_names.py`, also pinned in `test_field_lineage.py` and the MCP `explain_symbol` tests), `test_business_rules.py`, `test_redundancy.py` (`TestKeywordDifferencesAreNotType2`: ACCEPT FROM source, CALL passing mode and SEARCH ALL are no rename, #823; cross-file clones: `unit/test_scan.py::TestCopybookExpansion`, a copybook paragraph or paragraph body is one source, #352 / #470), `regression/test_issue_311_judgment_calls.py` (`OCCURS UNBOUNDED` unresolved note; `DIBSTAT` a special register, its tests still business rules; MQ CompCode stays business; the diff section-rename half is in `test_ast_diff.py`), `test_technical_debt.py` (and `regression/test_health_clone_shared_name_issue_555.py`: a clone offender is matched by qualified name, #555), `test_complexity.py` (and `regression/test_complexity_clause_pairs_issue_553.py`: an AT END / NOT AT END pair is one decision, SEARCH AT END none, #553), `test_complexity.py` (and `regression/test_complexity_perform_after_issue_514.py`: each PERFORM VARYING AFTER phrase is a decision and a nesting level, #514), `test_codebase.py` (also `regression/test_issue_500_oo_units_not_programs.py`: OO member units are not graph nodes; `regression/test_signature_by_value_direction_issue_490.py`: a BY VALUE parameter is `input` in program-signature, #490; `regression/test_issue_494_codebase_diagram_id_collisions.py`: DOT/Mermaid ids unique per diagram; `regression/test_issue_521_entry_names_in_call_graph.py`: CALL to an ENTRY name, graph + MCP; `regression/test_issue_325_failed_inputs_exit_code.py`: scan / codebase-graph / copybook-impact exit 2 on a failed file, no phantom program for a missing path; `regression/test_issue_522_program_source_encoding.py`: a cp1252 program is decoded by the CLI, batch, scan, codebase-graph and MCP, lossy decodes reported; `unit/test_cli.py::test_non_utf8_file` now expects exit 2, and the r11 strict-errors scan test names utf-8), `test_ast_diff.py` (and `regression/test_issue_545_diff_data_item_order.py`: `data-item-moved`; `regression/test_issue_516_diff_unnamed_paragraph.py`: the unnamed leading paragraph), (`regression/test_diff_equivalent_values_issue_543.py`: VALUE spellings), `test_sql_cics_lint.py` (and `regression/test_sqlcode_check_via_go_to_issue_557.py`: a SQLCODE check in the paragraph an unconditional GO TO reaches counts, #557), `test_ims_ssa_segment_resolution.py` (and `regression/test_dli_function_codes_issue_481_595.py`: one DL/I call-code list and one EXEC DLI command list that the parser and dialect EXEC nodes both read, function-code candidates never filtered by them, #481 / #595), `regression/test_le_callable_services_issue_529.py` (the LE callable service list and categories pinned against a checked-in SA38-0683 list, #529), `test_linkage_checker.py`, `test_lint.py`, `test_bug_patterns.py` (the seven bug-pattern lint rules, the IF END-IF attributes, `CalleeResolver` and `lint --callee-path`; the skill's rule count in `unit/test_cobol_analysis_skill.py`), `test_code_patterns.py` (the eight code-pattern lint rules: each with its look-alike, incl. CardDemo's shared `WHEN X WHEN X` group and an ELSE IF chain under `nesting-depth`; past twenty the skill writes the rule count in digits), `test_compiler_checks.py` (the ten compiler-check lint rules, `omitted_copy_lines`, level-88 `value_kinds`, GO TO after PERFORM VARYING AFTER UNTIL); CRUD matrix: `regression/test_crud_ws_cursor_issue_518.py` (a WORKING-STORAGE `DECLARE CURSOR`, #518), `test_crud_cics_file_control_issue_538.py` (EXEC CICS file control, data-item FILE caveat, #538), `test_report_writer_file_output_issue_499.py` (Report Writer INITIATE/GENERATE/TERMINATE in CRUD, IOLogger, io-sequence, boundaries, lineage, #499); `regression/test_io_logger_rewrite_from_read_record_issue_573.py` (IOLogger: REWRITE FROM logs the FROM item, READ without INTO the FD's records, #573); `regression/test_issue_570_allocate_based_linkage.py` (ALLOCATE gives a based LINKAGE item storage; xref ALLOCATE / FREE roles); `regression/test_issue_596_linkage_redefines.py` (a LINKAGE 01 REDEFINES group shares its USING reference); `regression/test_issue_588_cics_literal_options.py` (an EXEC CICS literal option references no same-named item); `regression/test_issue_549_556_select_clause_references.py` (SELECT key / padding items referenced in xref and unused-variables); `regression/test_issue_571_xref_report_section.py` (xref records REPORT SECTION SOURCE / SUM / CONTROLS operands; PAGE-COUNTER / LINE-COUNTER are special registers); `regression/test_issue_594_dfhresp_arguments.py` (a `DFHRESP` / `DFHVALUE` argument is no data name: xref, unused-variables, business-rules, move-type-check); `regression/test_issue_501_screen_section_references.py` (SCREEN SECTION USING / FROM / TO bindings, their subscripts, LINE / COLUMN / colour values, and screen names: parser metadata, unused-variables, lint, xref); `unit/test_ims_segment_analyzer.py`, `test_value_tracker.py`, `test_issue_564_dynamic_call_incomplete.py` (dynamic CALL targets: LINKAGE / READ / SQL / CICS receivers, MOVE fixpoint), `test_issue_593_set_entry_dynamic_call.py` (`SET p TO ENTRY` targets), `test_dynamic_program_tables.py` (EXEC CICS LINK / XCTL / LOAD `PROGRAM(data-name)` candidates, subscripted operands, REDEFINES-over-FILLER program tables) |
| Field lineage | `regression/test_qualified_name_lookup_issue_541.py` (#541: `IN` qualifier and partial chains in field-impact and MCP explain_symbol), `unit/analysis/test_field_lineage.py` (incl. `WRITE flat-REC FROM group` reaching the file at each field's own bytes; a RENAMES item traced through its THRU range, and the caveat when it cannot be placed, #485; SQL host variables under an OCCURS give inexact edges, #507; the MCP `explain_symbol` tests pin its byte range too; `TestSummaryLimit`: `summary_limit` cap, caveat, 0 and None), `test_lineage_graph.py` (`TestOpaqueCallHub`: an opaque callee's join through one hub node, linear in the arguments, same hits both ways, no hop or depth for the hub), `test_lineage_overwrites.py` (an unconditional MOVE / SELECT INTO between a write and a read in one paragraph marks the hit, a guarded or cross-paragraph one or an ADD does not; MCP `may_be_overwritten` sorted last), `test_lineage_jcl.py`, `test_sql_flow.py` (`TestUntracedCorrelationNames`: a sub-select / table function / FINAL TABLE correlation name is no table, #782; `TestLateralXmltableUnnest`: LATERAL / XMLTABLE / JSON_TABLE / UNNEST are no tables, #787); `unit/cli/test_lineage_cli.py` (incl. `--summary-limit`); `unit/analysis/test_field_widening.py` + `unit/cli/test_widen_check_cli.py` (`widen-check`: capacities, truncation cut once along a path, pre-existing / decimal / derived grading, narrowing feeders, layout through overlays / REDEFINES / LRECL / datasets / CALL and LINKAGE, same-layout, reports without PICTUREs; `TestRegressions`: an edited receiver with no sign symbol #757, a literal-subscript receiver #759, an inner REDEFINES only when it covers the change #760, ENTRY linkage both ways #761, sign and decimal point into an alphanumeric item #822, a CALL argument beside the widened field is no layout change; samples in `tests/samples/widening/`); `regression/test_same_record_area_issue_497.py` (SAME RECORD AREA aliasing, lineage + constant folding); `regression/test_lineage_no_flow_field_issue_546.py` (a declared field with no value flow is found, CLI exit 0, MCP `found: true`); `regression/test_lineage_ambiguous_name_issue_540.py` (a bare name matching several fields: each traced, ambiguity caveat, MCP `ambiguous-name`); `regression/test_lineage_receivers_issue_535.py` (receivers of one ADD/SUBTRACT/MULTIPLY/DIVIDE/INSPECT/STRING/UNSTRING do not feed each other); `regression/test_impact_text_ports_issue_528.py` (impact text lists the port hits the JSON does); `regression/test_lineage_variable_refmod_issue_527.py` (a non-literal reference modifier reaches every field, inexact in MOVE and non-MOVE statements alike, with a caveat); `regression/test_impact_two_way_ports_issue_510.py` (an I-O DD, a BY REFERENCE outside CALL and a LINKAGE parameter are impact hits; a join still hides the port); `regression/test_mcp_hop_file_issue_489.py` (MCP lineage steps cite the program or copybook file a line is really in); lineage + constant folding), `test_issue_585_sort_joinkeys_outfil_files.py` (DFSORT JOINKEYS / `OUTFIL FILES=` steps, the unread-sort-step caveat); lineage + constant folding), `test_issue_339_control_statements_from_a_dataset.py` (SORT / IEBGENER control statements from a dataset: reformat + caveat); lineage + constant folding), `test_issue_566_icetool_and_tso_systsin_dataset.py` (ICETOOL TOOLIN operators, dataset SYSTSIN / TOOLIN caveats); lineage + constant folding), `test_issue_565_proc_step_referbacks.py` (`*.INVOKE.PROCSTEP.DD` / in-PROC referbacks, unresolved-referback caveat); lineage + constant folding), `test_issue_584_ikjeft_several_run_programs.py` (every IKJEFT01 `RUN PROGRAM` bound); lineage + constant folding), `test_issue_338_idcams_command_word_qualifiers.py` (IDCAMS REPRO with a command-word DSN qualifier); lineage + constant folding), `test_issue_547_jcl_bindings_into_field_impact.py` (`jcl --bindings` -> `field-impact --bindings`, row validation, overrides listed once); samples in `tests/samples/lineage/` |
| Record data | `regression/test_cobol2002_usages_issue_524.py` (#524: FLOAT-/BINARY-* sizes, with or without the USAGE keyword; unknown USAGE words), `regression/test_condition_figurative_thru_issue_468.py` (#468: level-88 `THRU` with a figurative end), `unit/generators/data/test_encoding.py` (`TestHexLiteralBytes`, `TestFiller`, `TestDbcsCaveat`), `test_editing.py`, `test_variable_length.py`, `test_layout_offsets.py`, `test_compare.py`, `test_views.py`, `test_decoding.py`; `regression/test_fd_lrecl_framing_issue_362.py`, `test_issue_587_numeric_edited_strict_decode.py` (an edited field's bytes must be exactly an edited form), `test_issue_554_pic_u_character_length.py` (`PIC U(n)` is 4n bytes in data-items and record images), `test_issue_552_group_value_clause.py` (a group VALUE sliced over its fields; a numeric slice read as digits at the field scale), `test_issue_491_currency_sign_record_image.py` (a declared currency sign in a record image, a multi-character string and a letter `PICTURE SYMBOL` sized and round-tripped, caveat for two symbols in one picture), `test_issue_536_data_items_copybook.py` (`data-items` / MCP `record_layout` on a bare copybook; MCP caveats a wrapped copybook and never wraps a program file); gen-fixtures scenario planning: `regression/test_issue_505_unresolved_boundary_coverage.py` (an unresolved SQL host variable / ACCEPT target counts its boundary unresolved; OCCURS arrays named unsupported), `regression/test_issue_498_sort_files_not_boundaries.py` (SORT/MERGE USING/GIVING files named in `unresolved`), `regression/test_issue_374_const_fold_walk_cache.py` (cached/memoised folds equal fresh ones; the memo is never shared and is keyed on `success_skipped`; the bundle equals an uncached run; the cache does not keep a folded program alive), `regression/test_issue_509_unmodeled_arms.py` (an unmodeled SEARCH AT END is missed, `--strict` exits 2; a WHEN OTHER after not-boundary-fed WHENs is missed for their reason, `--strict` exits 0; a WHEN OTHER after a THRU range or arms on different fields is targeted), `regression/test_bug_hunt_2026_11_05_generation.py` (compound EVALUATE TRUE WHENs modeled and negated by later arms; WHEN OTHER after ranges; a loop-ending arm never merged; a branch below a STOP RUN arm keeps a staying arm), `regression/test_evaluate_figurative_when.py` (WHEN SPACES / 'SPACES' / OTHER all targeted) |
| CLI | `unit/test_cobol_analysis_skill.py` (every subcommand and flag the `cobol-analysis` agent skill names exists; its lint rule list is `lint.RULES`), `unit/cli/test_output_identification.py`, `test_source_format_flag.py`, `test_profile_output_flags.py`, `test_analyzer_cli_gaps.py`, `test_new_subcommands.py`, `test_lint_subcommand.py`, `test_lint_ci.py` (the `line-length` rule, multi-file lint and its exit codes, `--changed-since` against a scratch git repo incl. nested copybooks, `--format github`, the pre-commit hook file), `test_lint_new_code.py` (`--new-code-since` / `--scope` against a scratch git repo: only new lines, a rule scoped `all`, `rule/KIND`, untracked and copybook changes, `lint.scope`, `--summary-file`, the diff parser; the README's `--new-code-since` example needs git like `--changed-since`), `test_lint_policy_cli.py` (the default `--min-severity` per format, `--disable`, `--severity`, `--exclude`, `--baseline` / `--write-baseline`, inline suppression end to end, `--workers 1` and `2` giving the same report, the `DFHAID` stand-in, `--strict-copybooks`, the new `lint:` keys of `cobol.yml`; the lenient missing-copybook caveat in `regression/test_review_2026_09_09_cli.py`), `unit/analysis/test_lint_policy.py` (`parse_suppressions` / `apply_suppressions` incl. a directive in a copybook and one inside a literal, severity overrides, the baseline round trip without lines and its per-program counts, the 2026-11-06 noise cuts, FILE_LEFT_OPEN always placed, the system copybook stand-ins), `test_expand_source_map_cli.py` (a copybook the column pass cannot re-read through `read_program_source` gets no column), `test_gen_data_cli.py`, `test_compare_cli.py`, `test_record_layout_copy_expansion.py`, `test_jcl_cli.py` (+ `regression/test_issue_493_jcl_program_under_launchers.py`: `jcl --program` under IKJEFT01 / DFSRRC00; `test_issue_523_dd_map_program_plain_pgm.py`: `--dd-map --program` keeps only that program's steps' datasets for a ddname two `PGM=` steps share), `test_project_config_cli.py`; `unit/test_config_yaml.py`, `test_project_config.py` (+ #550 `~`/`$VAR` expansion, missing directories reported); `regression/test_config_define_multi_file_commands.py` (#324; no `source_format` warning for the data commands) |
| Program units / models | `regression/test_issue_508_program_metadata.py` (`procedure_count` skips DATA DIVISION sections; `parser_version` is the package version; no `created_at`), `regression/test_nested_program_units.py`, `test_issue_532_nested_program_scope.py` (nesting vs stacking, CALL scope in codebase-graph / MCP / scan depth), `regression/test_issue_504_global_items_in_contained_programs.py` (GLOBAL items in contained programs: xref, MCP explain_symbol, lineage, move-type-check), `unit/test_models.py` (`from_json` lossy warning, `TestNodeEquality`) |
| Scenario path conditions | `regression/test_issue_310_cross_paragraph_path.py` (a paragraph PERFORMed from one guarded arm takes its guard; several guarded sites make the scenario unverified; a guarded `PERFORM` of a SECTION folds its guard, a section fallen into needs none, #310) |
| OCCURS expansion caps | `regression/test_issue_376_occurs_expansion_budget.py` (nested tables bounded at 100,000 occurrences per field, every cut table named in gen-data / views / gen-fixtures -- those two tests monkeypatch both caps small to stay fast, #376) |
| gen-data `--unique` | `unit/generators/data/test_values.py` (`TestBlankRateAndUniqueFields`), `regression/test_issue_526_unique_narrow_text.py` (narrow VALUE / level-88 text stays distinct, exhausted PICTURE and unknown name become caveats, #526) |
| VALUE vs JUSTIFIED / BWZ | `regression/test_issue_558_value_ignores_justified_bwz.py` (a VALUE-clause cell is written unjustified and unblanked, level-88 / generated cells are not, decode round-trip, #558) |
| Dialect helpers | `unit/test_ibm_enterprise.py` (`IBMDataItem.calculate_storage_size()` equals `calculate_size()`: even-digit COMP-3, PICTURE-less COMP-1 / COMP-2 / POINTER, #589) |
| gen-fixtures register branches | `unit/generators/test_issue_839_840_register_branches.py` (EVALUATE on a CALL's RETURN-CODE drives the CALL mock, #839; branches on SQLCODE drive the SQL fixture's status with realistic codes and verify, #840); `unit/generators/test_scenario_verification.py::TestCallReturnCode` (#831) |
| gen-fixtures CALL arguments | `regression/test_call_function_argument.py` (#579), `regression/test_issue_582_call_constant_arguments.py` (literal / figurative / OMITTED / LENGTH OF / ADDRESS OF arguments are no resolution gap, #582; a subscripted / reference-modified one says why it gets no value) |
| gen-fixtures csv-dir | `unit/test_program_fixtures.py` (`write_csv_dir`, MANIFEST shape), `regression/test_issue_568_empty_input_csv.py` (the empty-input scenario's READ gets a header-only CSV, #568) |
| OCCURS KEY / INDEXED BY order | `regression/test_occurs_indexed_before_key_issue_542.py` (#542: OCCURS KEY/INDEXED BY in either order) |
| AWS CardDemo gaps | `unit/test_carddemo_gaps.py` (`ADD n TO ZERO GIVING x` parses and a literal without GIVING still errors; `project.proc_path` resolution and missing folders; `load_jobs` over several PROC folders, first wins; the MCP server expands a suffix-less cataloged PROC member only from `proc_path` folders inside its root, with a caveat otherwise, and a `.prc` member without any; an IDCAMS `SYSIN` dataset is named in a note) |
| SARIF | `unit/analysis/test_sarif.py` (levels, rules/`ruleIndex`, `%SRCROOT%`-relative vs absolute URIs, no line -> no location, `origin` over `location`, notifications; `lint` / `scan` (file-level lint, copybook findings in the copybook, failed file) / `call-check --format sarif` through the CLI) |
| Facts cache | `unit/test_facts_cache.py` (`FactsCache` stamps, settings/namespace separation, corrupt entries; `scan --cache-dir`: a hit, then a miss for an edited program, copybook, new member in a copybook dir, an edited wrapper copybook that only COPYs another (#763), other options) |
| MCP server | `unit/mcp_server/test_mcp_tools.py` (no SDK: guard, cache incl. a copybook added after a miss, caveats incl. one missing member among several, `cobol.yml` re-read on edit, `TestConfigCannotWidenTheGuard` (#544: `copybook_path: [/]` reads nothing outside, a parent-dir `cobol.yml` ignored, an outside copybook dir serves `FOO.cpy` / an extensionless member but not `secret.txt` or dotfiles, `..` and symlinks out refused, home / its ancestors / root ancestors / hidden / system dirs refused, `--config` under the same rules, the refused-directory caveat), each tool, copybook fields linted as info like the CLI, special registers, `TestReadSource` incl. a window larger than the cap keeping the cited line, #537), `program_brief` / `callers_of` / `record_layout` (every cited line checked against the file; PERFORM THRU, FILLER, a failing analyzer, reachability agreeing with dead-code after a PERFORMed paragraph or THRU range, #486), `test_mcp_codebase.py` (`TestOtherSources`: without the PL/I and assembler parsers, a CALL into assembler under the root is `in_workspace_not_analyzed`, not missing; lineage paths shared with `from_hit` rebuild the `full_paths` ones, exact hits first, `trail_ends`; the root-wide indexes: what counts as a program, built once and kept out of the parse cache, rebuilt on an added or edited program; symlinks out of the root skipped, progress while indexing;
program-level `callers_of` incl. dynamic CALLs, a dynamic CICS LINK and a duplicate PROGRAM-ID; copybook impact with COPY lines; field lineage across a CALL and a JCL job, with and without jcl-parser, and through an expanded copybook; `codebase_overview` incl. clones across programs, and a copybook paragraph body under each program's own header is none, #470), `test_mcp_v3_tools.py` (`business_rules` cited lines, kind / procedure filters, technical rules opt-in; `diff_programs` each side cited in its own file, category filter; `decode_record` EBCDIC round trip from `gen-data`'s encoder, `cobol.yml` charset default, paging with `skip`, a REDEFINES view, trailing bytes, the 16 MiB read cap (fixed records paged past it by seeking; a separator framing stops there with no `next`); `gen_fixtures` determinism, seed from `cobol.yml`, arm coverage, callee dirs outside the root skipped, a callee symlinked from outside the root not read; a raising analyzer as `analyzer-failed`; every prompt naming real tools), `test_mcp_jcl_tools.py` (skipped without `jclparser`: `jcl_job` cards cited in the job file or the cataloged procedure member, overrides told apart by the card text, in-stream data capped, filters, errors; `jobs_running` SELECTs bound to DDs, launcher steps, an IBM-supplied procedure (`EXEC DLIBATCH,MBR=`) not under the root expanded from jcl-parser's template under its own caveat (#744; the adapter side in `unit/test_jcl_adapter.py`), `dds_not_coded` skipping OPTIONAL / SD / ASSIGN USING files, source found by PROGRAM-ID; `dataset_users` GDG base / exact / wildcard matching, `TestAccessFromTheProgram` (DISP=SHR opened OUTPUT is a write, with `access_because` citing the OPEN; IDCAMS REPRO, SORT OUTFIL, ICETOOL FROM/TO roles; an unknown program falls back to DISP), job-level DDs, temporaries; `TestReviewFixes`: a `.cbl` never shadows a `.prc` member, concatenation members after an override cited card by card, an unparseable source keeps the steps, a utility parses no program; z/OS filter wildcards; `TestProcedureLibraries`: a `JCLLIB ORDER=` folder, an ORDER list continued over cards, a missing JCLLIB library as a caveat, a suffix-less `proc_path` member, a `.jcl` member of a `SYS1.PROCLIB` folder expanded and not read as a job; the `jcl` index rebuilt on an added file, a failing file named, every tool naming the install command without the extra; one in-memory session), `test_mcp_languages.py` (skipped without `pl1_parser` / `hlasmparser`; over `tests/samples/mixed/`, a PL/I driver, a COBOL subprogram and an assembler routine run by one JCL job: PL/I aliased calls kept as the real program, assembler ENTRY names / `EPLOC=` / EXEC CICS LINK and XCTL, the index re-reading only changed files; one call graph across languages incl. a cycle and a COBOL CALL to an assembler ENTRY name, program-level `callers_of`, `check_claims` `calls` / `copies`, `included_by_other_languages`; the PL/I and assembler `program_brief`, COBOL-only tools refusing such a file; `jobs_running` / `jcl_job` naming the source, the PL/I brief's `run_by`, an included member's `member_files`, `coverage` by language; without the parsers the install commands; a parse that raises named), `test_mcp_round5.py` (the round 5 benchmark fixes: a restart loads no heavy facts until `where_from`, a missing shard recomputed, the core pickle without heavy fields; unresolved dynamic calls and JCL gaps elsewhere counted, those naming the program spelled out; `coverage` and REXX `sources_not_analyzed`; a `.mlc` twin, `jobs_running` `sources`, `follow_calls` reaching assembler at depth 2; overview `language` / `path` filters incl. a glob and an unknown language; `run_by`; the languages index from cache; `warm_indexes`)`test_mcp_round6.py` (round 6: a `path` filter scopes every overview section, three clone members with one truncation entry, a glob keeps its members; `program_brief(follow_calls=True)` with each callee's files and tables, `at`, `also_called_by`; `jobs_running`'s `jobs` flow: reads / writes by open mode, `fed_by`, in-stream and member SYSIN cards from the nearest folder), `test_mcp_round7.py` (round 7: `unreachable_reasons` for a paragraph nothing names, one named only from dead code and one after a PERFORMed paragraph; `copied_at` on a caller in a copybook; `explain_condition()` for COND codes, EVEN, ONLY and a compound; IDCAMS DELETE / DEFINE / REPRO in SYSIN as `dataset_users` rows and job-flow writes, with `condition_means`), `test_mcp_round8.py` (round 8: `parse_sort_control()` / `map_sort()` keys, OUTREC, literals, partial fields, INCLUDE before INREC, an edit mask not mapped, `read_back()`; `jcl_job`'s `sort_layout` from a READ INTO in another job and `output_read_as` through a REPRO into a KSDS, `run_order`, a REPRO OUTFILE as a write and an IEFBR14 delete; the job flow's `sort_layout`, none for a utility query; COPY vs EXEC SQL INCLUDE and `brought_in_by`; `program_brief(follow_calls=True)` `implementations` of a callee with a VSAM and a DB2 source, the step whose DDs pick the VSAM one, an OPTIONAL DD not needed, no step coding them, one source and no comparison), `test_mcp_round9.py` (round 10: `call_type` for a CALL literal, a CALL identifier, a PL/I FETCHABLE and a plain EXTERNAL ENTRY; `runs_as` from EXEC CICS, DFHCOMMAREA, a JCL step and a subroutine's callers, absent when nothing says, on `call_tree` rows; `commented_out` for a COPY on a comment line), `test_mcp_round12.py` (round 12: `not_affected` folder neighbours, absent when every one copies the member; the job flow's `step_count` and `run_order`; `access_because` in `test_mcp_jcl_tools.py`; round 14: `programs_by_role`, `jobs_by_effect` (IDCAMS DELETE and an IEBGENER write from its SYSUT1 vs a read-only job, `copied_to`), `member_files_to_change` for a copybook and a PL/I include of one member)), `test_mcp_heldout_fixes.py` (held-out round 1: `control_flow_notes` for falling off the end, the fall-through chain, an FD never OPENed and one never CLOSEd, none for a program that PERFORMs and ends, an SD never said unopened; `also_declared_in` for a comment-only twin and `compare_sources()`; EXEC SQL tables as `find_statements` operands qualified and bare, a cursor OPEN as a read, `dataset_users`' `sql_programs`; a DSNTIAD member and an in-stream DSNTIAUL unload as `db2 sql` rows with `copied_to`, `_sql_tables()`; `parse_deck()`, `link_edited_into` on `callers_of` and `link_edit` on the brief; `other_forms` both ways between EXEC DLI and CALL 'CBLTDLI'; the search checklist in `INSTRUCTIONS`); `regression/test_sql_table_hash_issue_770.py` (#770: `#@$` in DB2 table names), `test_mcp_argument_handling.py` (`lint` rules / severity in any case; `where_from` / `impact_of_change` limited by `program` without `file`, unknown one an error; a name only another unit of the file declares named in `declared_in_program_units`; `define: [X=]` empty like the CLI; lint columns on an EBCDIC program are on-disk columns), `test_mcp_navigation.py` (`read_procedure` lines equal the file, ends before the next header, a COPY segment in the member, sections; `find_statements` by verb / prefix / operand + role / literal / paragraph, a copybook statement found and a comment not, the index rebuilt on an added program), `test_mcp_claims.py` (every kind confirmed and contradicted on the enterprise and lineage samples, a flow through a SELECT INTO overwrite not checkable, dataset access with jcl-parser, unknown kind / missing field / cap / no claims), `test_mcp_claims_storage_and_names.py` (`flows_to` by whole names, not substrings, #776; `writes_field` / `sets_only_in` through a parent group, INITIALIZE and REDEFINES, partial overlap and REPLACING not checkable, #778; `TestFileRecordWrites`: sibling FD / SD records share storage, READ / RETURN a possible write, WRITE / RELEASE FROM a write of the record, #788), `test_mcp_slice.py` (backward data + control rows of a total, cited on disk, inexact REDEFINES skipped unless `aliases`; forward decisions and the arms they control, a level-88 test; unknown field suggestions, bad direction, `limit`; the hint across the boundary; the BATCHSEQ total's loop-deciding SET / MOVE rows), `unit/test_issues_790_796.py` (#790 delimited SQL names, #793 unreadable VALUEs and REDEFINES as incomplete, #794 one link deck per NAME, #795 quoted / field-to-field INCLUDE tests and OUTFIL not mapped, #796 slice over literal / SET writes, tested fields, controlled writes and an edgeless field), `test_mcp_hints_budget.py` (`fit_budget` halving the longest list and keeping a `limit` cut's total; `next` hints per tool, only offered tools, never failing; both over a session), `test_mcp_facts.py` (one parse per file across every index; only a changed file parsed again, a removed one dropped; a restart answers from the disk cache without a parse, a config change starts afresh, a bad cache file is no cache; an edited wrapper copybook re-parsed, #763; a pool answers like one process with no parse in the server, a dead worker costs its file; warm-up in process and pooled), `test_mcp_server.py` (in-memory client session incl. the v3 and JCL tools and the prompts, `--tools` selection (`auto` adds the JCL tools only with JCL under the root) and `compact_schema`, a slow tool not blocking the loop, progress notifications, `cobol-parser mcp` incl. `--workers` / `--cache-dir` / `--no-disk-cache` / `--no-warm-up` and the refused-directory stderr warning). Also `regression/test_issue_488_record_layout_sync_caveat.py` (`record_layout` / `explain_symbol` flag SYNCHRONIZED slack like `data-items`; a partial level-88 caveat leaves offsets exact). The directory is not `unit/mcp/`: a test package named `mcp` shadows the SDK |

## Coverage Requirement Detail

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

Branch coverage is also enabled (`[tool.coverage.run] branch = true`,
`source = ["cobolparser"]`). No coverage baselines are stored in the repo
(there is no `baselines/` directory); the floor above is the only gate.

**Timing assertions and coverage.** `tests/performance/test_factory_performance.py`
guards its two absolute nodes/sec floors (100,000) with `requires_untraced`
(`skipif("sys.gettrace() is not None")`). Under coverage.py's tracer the
suite took 950 s instead of 94 s, and `test_factory_throughput` measured
64,243 nodes/sec against its 100,000 floor on a CI runner that clears it
comfortably uninstrumented -- the number describes the tracer, not the
factory. Any `--no-cov` run (e.g. CI's `build` job) enforces the floors;
only a coverage run skips them. The ratio-based overhead assertion is
unaffected.

**The large-program lane** (`tests/performance/test_large_program.py`,
skipped under a tracer the same way). `generate_program(lines)` writes a
fixed-format program of ten-line paragraphs (IF / COMPUTE / MOVE /
EVALUATE, then PERFORM or every fifth a GO TO of the next), every line
within column 72. `BUDGETS` holds seconds per analyzer at 40,000 lines
(about three times the 2026-10-28 measurement); the default lane runs
4,000 lines against the budgets scaled down (floor 1 s), about 3 s in all.
`COBOLPARSER_PERF=1` runs 40,000 lines against the full budgets, plus
`test_scales_linearly`: each analyzer at 10,000 and 40,000 lines, ratio
under `MAX_SCALING_RATIO` 8 (linear is 4, quadratic 16); about 80 s. A new
analyzer needs a budget (`test_every_analyzer_has_a_budget`). Its first run
found the dead-code worklist quadratic (see
[analysis/flow.md](analysis/flow.md)).

## CI/CD

> **Manual dispatch only.** `.github/workflows/ci.yml` has a single
> `workflow_dispatch` trigger. Its triggers were first commented out with the
> whole file (commit `315d474`), but a workflow file with no content is
> invalid and GitHub logged a failed run on every push, so on 2026-11-01 the
> jobs came back with dispatch as the only trigger. No lint, typecheck, test
> or coverage job runs on push or PR; run them locally or dispatch the
> workflow on a branch. `release-please.yml` is still active.

Triggers when event-triggered CI was on: push/PR to `main`, a nightly `schedule`
(`17 4 * * *`) and manual `workflow_dispatch`. Push and PR triggers carry
`paths-ignore` for `docs/**`, `.okf/**`, `reports/**` and `**/*.md`, so a
docs-only change runs no CI. A new push to a PR cancels the run in flight
(`concurrency`); runs on `main` are never cancelled.

1. **lint** -- `ruff check .` + `black --check .` (Python 3.13, `ruff==0.15.0`
   / `black==26.3.0`, pinned to match `.pre-commit-config.yaml`)
2. **typecheck** -- `mypy cobolparser/` (Python 3.13, `mypy==1.20.0`)
3. **test** -- `pip install -e ".[dev]"` +
   `python -m pytest tests/ -q -p no:randomly -n auto` on matrix Python 3.11,
   3.12, 3.13. Coverage is on, so the 90% floor (from `addopts`) is enforced
   on every version: the library is pure Python, so one job both runs the
   suite and measures coverage.

`-n auto` keeps each test job near two minutes; `-p no:randomly` keeps a
failure reproducible from the log (pytest-randomly is not a declared
dependency; the flag is a no-op without it). With CI disabled, nothing
enforces the floor unless it is run locally.

Release builds are a separate workflow,
`.github/workflows/release-please.yml`: release-please cuts the release from
Conventional Commits, then one `build-dist` job runs `python -m build` to make
the sdist and a single pure-Python `py3-none-any` wheel (there is no
`setup.py`; `pyproject.toml` is the whole build config), and both are
published to PyPI as `cobol-parser` via Trusted Publishing (`workflow_dispatch`
with `target: testpypi` rehearses against test.pypi.org).
There is no closed-source release mode; the package is AGPL-3.0-or-later.

## OKF guards

`tests/test_okf_staleness_map.py` pins `scripts/okf_staleness_check.py`'s
`OKF_MAP`: every tracked `.py` under `cobolparser/` must map to at
least one OKF file, every mapped OKF file must exist, and every prefix that
names a directory must end with `/`. (`tests/` itself maps to this file.)

A file missing from that map is a file whose documentation can rot
silently, because the pre-commit hook never asks for an update when it
changes. The directory-slash assertion matters both ways: a prefix such as
`cobolparser/parsers/` never matches `cobolparser/parser.py` (so that file
needs its own entry), and dropping the slash would make
`cobolparser/parsers` swallow `cobolparser/parser.py` instead.

`tests/test_okf_claims.py` runs `scripts/okf_check.py` over every OKF file
and CLAUDE.md, one test per file: imports written in the docs must run,
backticked names/paths must exist, links and anchors must resolve, the CLI
table in `cli.md` must match argparse, and every `<!-- okf:gen NAME -->`
span must equal its generator's output. A failure after a code change is
either a doc that needs a real edit or a generated span to refresh with
`python scripts/okf_check.py --write`. Its `TestCheckerCatchesDrift` class
pins that each check still flags the drift it exists for.

`tests/test_readme_examples.py` (`integration`, `slow`, ~15 s) builds the
project the README's examples assume (`src/`, `copybooks/`, `jcl/`,
`proclib/`, `old/`, `defs/`, `cobol.yml`) from `tests/eval/shop/`,
`tests/samples/enterprise/` and `tests/samples/definitions/`, then runs every
`cobol-parser ...` line of the `bash` blocks and every `python` block between
"Every command, with an example" and "Language coverage", in order. JCL
examples skip without `jclparser`, `--changed-since` without `git`. A new
README example needs no test change unless it names a sample file
`_build_project()` does not copy.

## See also

* [cli.md](cli.md) -- `tests/unit/cli/` covers CLI subcommands
* [generators.md](generators.md) -- flowchart, copybook -> CSV, record
  encoding/decoding, program layout index, and fixture bundle tests
* [analysis.md](analysis.md) -- `tests/unit/analysis/` covers analyzers
* [parser.md](parser.md) -- `tests/integration/` covers end-to-end parsing
* [lexer.md](lexer.md) -- tokenizer behaviour the lexer tests pin
* `tests/unit/cli/test_gen_data_cli.py::TestRecordImageFormats` -- the
  `gen-data --format record|hex` flags, that CSV output is unchanged by any
  of them, and (counting `encode_record` calls) that `--output` encodes the
  dataset exactly once. `::TestRecordFormatFlag` covers `--record-format`
  alongside it
* `tests/unit/cli/test_record_layout_copy_expansion.py` (#592) -- a COPY
  nested in a copybook or under an FD is expanded by `gen-data` / `decode` /
  `compare` from `--copybook-path` or `cobol.yml`, and one left unexpanded
  is a stderr warning and a caveat, never a silently short record
* `tests/unit/cli/test_cli_help_overview.py` -- every registered subcommand
  sits in exactly one `--help` group (`cli/_help.py`), the bare-invocation
  overview, command typo suggestions (while a file-like or existing word is
  still parsed as a file), and the directory / missing `--copybook-path` /
  unexpanded-COPY messages
* `tests/unit/cli/test_cli_coverage_gaps.py` -- `preprocess` (#271) and
  `expand` (#583) evaluate `>>IF` / `>>DEFINE` with or without `--define`:
  one arm survives, in the program and in an inlined copybook
* `tests/unit/generators/data/test_variable_length.py` -- fixed vs variable
  record length: ODO layout linking, per-row trimming, counter bounds, RDW
  framing, and the length reporting built on them.
  `TestFdRangeWithoutDependingOn` (#320) pins that an FD range with no
  DEPENDING ON writes every record at its own 01's full length, never cut
* [history](history/tests.md) -- the archived dated change log: per test
  file, what it pins and why
