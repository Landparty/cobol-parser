---
type: Module
title: CLI
description: cobol-parser command-line interface — all 38 subcommands with their flags and defaults, output identification, exit codes, and the cobol.yml project config (cobolparser/cli/, cobolparser/config/, __main__.py).
tags: [cli, command-line, subcommands, output-identification, cobol-yml, project-config]
timestamp: 2026-10-15T00:00:00Z
---

# Overview

The `cobol-parser` command: 38 subcommands that parse, tokenize, preprocess,
expand, analyze, generate/decode/compare record data for, and graph COBOL
(plus one for JCL and one for the LE catalogue), all built with `argparse` in
one module, and the `cobol.yml` project config every subcommand reads.

**Entry points** (all reach `cobolparser.cli.parse.main`):

* `cobol-parser ...` — console script, `[project.scripts]` in `pyproject.toml`
  → `cobolparser.cli:main` (`cli/__init__.py` re-exports `parse.main`).
* `python -m cobolparser ...` — `cobolparser/__main__.py` calls the same `main()`.
* `python -m cobolparser.cli.parse ...` — `parse.py` has a `__main__` guard.
* `python -m cobolparser.cli.coverage ...` — a **separate** argparse program for
  IO coverage artifacts, not a `cobol-parser` subcommand (see
  [IO coverage tools](#io-coverage-tools-cobolparserclicoveragepy)).

**Source:** `cobolparser/cli/parse.py` (every subcommand: a `_build_<name>_parser()`
plus a `_cmd_<name>()` per subcommand, assembled in `_build_parser()`),
`cobolparser/cli/_project_config.py` (the `cobol.yml` → argv merge),
`cobolparser/cli/coverage.py`, `cobolparser/config/` (`project.py` schema +
discovery, `_yaml.py` reader).

**Getting started:** `cobol-parser --help` lists the subcommands,
`cobol-parser <name> --help` shows each one's flags, defaults and a runnable
example epilog. The [subcommand reference](#subcommand-reference) table below
is the one-screen version. To add a single-file analyzer, call
`_build_analyzer_parser(subparsers, name, help, func, profiling=..., examples=...)`
in `_build_parser()` — it gives the standard shared flag set — and emit through
`_emit_report(..., ast=ast)` so the output is identified and origin-stamped.

**Top-level behaviour of `main()`:**

* `--version` prints `cobol-parser <version>`; `--config FILE` / `--no-config`
  are global and may sit on either side of the subcommand (see
  [Project config file](#project-config-file-cobolyml)).
* **Legacy spelling**: if the first non-flag argument is not a subcommand name
  (`_SUBCOMMANDS`), `parse` is prepended — `cobol-parser prog.cbl` is
  `cobol-parser parse prog.cbl`. An empty argv also becomes `parse` (and so
  fails argparse's "file required", exit 2).
* A closed stdout (`cobol-parser parse x.cbl | head`) exits **141**
  (128 + SIGPIPE) quietly instead of a `BrokenPipeError` traceback.
* Errors raised by the CLI itself go through `_fail()`: one `error: ...` line
  on stderr, exit 1. Argparse usage errors exit 2.

**Shared flag helpers** in `parse.py` (each subcommand composes a subset):
`_add_compact_arg` (`--compact`), `_add_source_format_args`
(`--source-format` | `--free-form`, plus `--debug-lines`),
`_add_debug_lines_arg` (`--debug-lines` alone), `_add_dialect_arg`,
`_add_error_recovery_arg`, `_add_copybook_args` (`--copybook-path`,
repeatable), `_add_program_arg`, `_add_define_args` (`--define SYMBOL[=VALUE]`,
repeatable), `_add_output_arg` (`--output`/`-o FILE`), `_add_profiling_args`
(`--profile`, `--profile-top-n N` default 20, `--profile-output PATH`),
`_add_record_file_args` (decode/compare file-format flags),
`_add_min_clone_statements_arg` (redundancy/scan), `_add_direction_args`
(lineage/field-impact).

Every subcommand's `--help` has a `RawDescriptionHelpFormatter` epilog with
runnable `cobol-parser <name> ...` examples: `_build_analyzer_parser()` takes a
required `examples` kwarg (15 callers), the hand-built parsers set `epilog=`
themselves.

# Contents

* [Subcommand reference](#subcommand-reference) — every subcommand, its positionals and flags, in one table
* [Output Identification](#output-identification) — `source_file` / `program_id` / `program_units` headers
* [Project config file (`cobol.yml`)](#project-config-file-cobolyml) — discovery, precedence, bound dests, the YAML subset; [`config`](#config) subcommand
* [Subcommand details](#subcommand-details) — one section per subcommand (or family), in roughly the order of the table
* Shared flags: [`--error-recovery`, `--copybook-path`/`--define`, exit codes](#parse) · [`--source-format` / `--free-form` / `--debug-lines`](#source-layout---source-format) · [`--program`](#selecting-a-program-unit---program) · [origin stamping with `--copybook-path`](#unused-variables)
* [IO coverage tools](#io-coverage-tools-cobolparserclicoveragepy)
* [See Also](#see-also), [Recent changes](#recent-changes)

# Subcommand reference

Verified against `python -m cobolparser <cmd> --help` on 2026-10-15. Order is
`_build_parser()`'s. Flag-set legend for the last column:

* **A** — the standard analyzer set from `_build_analyzer_parser()`:
  `--compact`, `--source-format {auto,fixed,free}` (default `auto`) |
  `--free-form`, `--debug-lines`/`--no-debug-lines`, `--dialect {ibm-enterprise}`
  (default), `--error-recovery {fail-fast,collect-all}` (default `collect-all`),
  `--copybook-path DIR`..., `--program NAME` (default: the outermost unit),
  `--define SYMBOL[=VALUE]`..., `-o/--output FILE`.
* **+prof** — also `--profile`, `--profile-top-n N` (default 20; implies
  `--profile`), `--profile-output PATH` (implies `--profile`).
* **dl** — `--debug-lines`/`--no-debug-lines` without `--source-format`.

| Subcommand | Positionals | Own flags (default) | Shared flags | Output |
|---|---|---|---|---|
| `parse` | `file [path]` | `--errors`, `--stats`, `--find-type NODE_TYPE` | A without `--program`; +prof | AST JSON; exit 2 on a recovered-but-errored parse |
| `batch` | `[files ...]` | `--glob PATTERN`..., `--workers N` (CPU count), `--encoding` (`utf-8`), `--errors`, `--stats` | `--compact`, `--dialect`, `--error-recovery`, `-o`, dl; +prof | JSON list, one entry per file |
| `tokenize` | `file` | — | `--compact`, `--source-format`/`--free-form`, dl, `--dialect`, `-o` | `{source_file, tokens}` |
| `preprocess` | `file` | `--strip-directives` | `--source-format`/`--free-form`, dl, `--define` (no `--compact`, no `-o`) | free-form source text |
| `expand` | `file` | `--keep-comments`, `--source-map`, `--max-depth N` (100) | `--copybook-path`, `--compact`, `--define`, `-o`, dl | expansion JSON |
| `gen-data` | `file` (copybook or program) | `--rows/-n` (10), `--seed`, `--record`, `--list-records`, `--describe`, `--header-style {short,path}`, `--include-filler`, `--include-redefines`, `--no-expand-occurs`, `--max-occurs`, `--no-semantic`, `--ignore-values`, `--unique FIELD`, `--blank-rate`, `--format {csv,json,record,hex}` (csv), `--charset` (ascii), `--endian` (auto), `--record-format` (fixed), `--record-varying MIN:MAX`, `--record-separator` (none) | `--compact`, `-o` | CSV / JSON / record bytes / hex |
| `decode` | `[file]` | `--copybook FILE` (required), `--record`, `--view`, `--list-views`, `--format {csv,json,hex}` (csv), `--charset`, `--endian`, `--record-format`, `--record-length N`, `--record-separator`, `--max-records N` (all), `--skip N` (0), `--strict` | `--compact`, `-o` | CSV / JSON / hex |
| `compare` | `expected actual` | `--copybook FILE` (required), `--record`, `--view`, `--key FIELD`..., `--ignore FIELD`..., `--compare-bytes`, `--max-differences N`, `--format {text,json}` (text), the decode file-format flags | `--compact`, `-o` | report; exit 0/1/2 like `cmp` |
| `gen-fixtures` | `file` | `--callee-path DIR`..., `--rows/-n` (10), `--seed`, `--max-occurs N`, `--scenarios {happy,branches,all}` (happy), `--format {json,csv-dir}` (json), `--list-boundaries`, `--strict` | `--copybook-path`, `--compact`, `-o`, dl | `FixtureBundle` JSON or CSV dir |
| `analyze` | `file` | — | A; +prof | dynamic CALL targets |
| `dead-code` | `file` | — | A; +prof | `DeadCodeAnalyzer` |
| `unused-variables` | `file` | `--exclude-copybook-variables` | A; +prof | `UnusedVariableAnalyzer` |
| `program-flow` | `file` | `--format {json,mermaid,dot}` (json) | A; +prof | CFG JSON / Mermaid / DOT |
| `recursion-check` | `file` | — | A; +prof | `RecursionRiskAnalyzer` |
| `complexity` | `file` | — | A; +prof | `ComplexityAnalyzer` |
| `health` | `file` | — | A; +prof | `TechnicalDebtAnalyzer` |
| `io-sequence` | `file` | — | A (no profiling) | `IOSequenceAnalyzer` |
| `move-type-check` | `file` | — | A (no profiling) | `MoveTypeChecker` |
| `linkage-check` | `file` | — | A (no profiling) | `LinkageChecker` |
| `language-env` | `file` | — | A (no profiling) | `LanguageEnvironmentAnalyzer` |
| `ims-dli` | `file` | — | A (no profiling) | `IMSSegmentAnalyzer` |
| `dclgen-check` | `file` | — | A; +prof | `DclgenChecker` |
| `redundancy` | `file` | `--min-clone-statements N` (3) | A; +prof | `RedundancyAnalyzer` |
| `scan` | `[files ...]` | `--glob`..., `--files-from FILE`, `--analyzer NAME`... (`health,redundancy`), `--clones`, `--min-clone-members N` (2), `--min-clone-statements N` (3), `--workers N` (CPU count), `--encoding` (`utf-8`) | A without `--program`/`--define` | `scan_version` report |
| `lint` | `file` | `--rule RULE`... (all), `--min-severity {error,warning,info}` (info), `--fail-on {error,warning,info,never}` (never), `--format {json,text}` (json) | A (`--program` default: every unit); +prof | findings; exit 3 on `--fail-on` |
| `data-items` | `file` | — | A; +prof | `compute_program_data_items()` |
| `program-signature` | `file` | — | A (`--program` default: every unit); +prof | `{"signatures": [...]}` |
| `xref` | `file` | — | A; +prof | `XrefReport` |
| `diff` | `old new` | `--format {json,text}` (json), `--rename-threshold RATIO` (0.8) | A without `--program` | `DiffReport` |
| `codebase-graph` | `PATH ...` | `--format {json,dot,mermaid}` (json), `--extension EXT`... (`.cbl .cob .cobol`), `--workers N` (by size) | `--compact`, `--copybook-path`, `-o`, dl | graph |
| `copybook-impact` | `member PATH ...` | `--extension`..., `--workers` | `--compact`, `--copybook-path`, `-o`, dl | `ImpactReport` |
| `sql-cics-check` | `file` | — | A; +prof | `SqlCicsReport` |
| `business-rules` | `file` | `--format {json,text}` (json), `--include-technical` | A; +prof | `BusinessRuleReport` |
| `lineage` | `file` | `--field NAME`, `--direction {forward,backward}` (forward), `--format {json,text}` (json) | A (no profiling) | `FieldFlowReport` |
| `field-impact` | `[FIELD] PATH ...` | `--program NAME` (every program with that field), `--table T.C`, `--dataset DSN`, `--direction` (forward), `--depth N` (unlimited), `--jcl PATH`..., `--proc-path DIR`, `--bindings FILE.json`, `--key-relationships`, `--workers N`, `--format {json,text}` (json) | `--compact`, `--copybook-path`, `-o`, dl | `ImpactResult`; exit 1 when the start matches nothing |
| `jcl` | `file` | `--dd-map`, `--bindings`, `--program NAME`, `--proc-path DIR`..., `--strict` | `--compact`, `-o` | job JSON; needs `[jcl]` extra; exit 3 on `--strict` |
| `le-info` | `[name ...]` | `--kind {service,function,all}` (all) | `--compact`, `-o` | LE / intrinsic signature catalogue |
| `config` | — | `--json` | `--compact`, `-o` | effective `cobol.yml` |

Subcommands that take none of the COBOL parse flags (`--source-format`,
`--dialect`, `--debug-lines`, `--define`, `--error-recovery`): `gen-data`,
`decode`, `compare` (they read a record layout only), `jcl`, `le-info`, `config`.

# Output Identification

Every output the CLI emits is self-describing — it identifies the source it
was produced from (helper: `_identification()` in `cobolparser/cli/parse.py`;
pinned by `tests/unit/cli/test_output_identification.py`):

* **JSON documents** start with `"source_file"` (the input path as given on
  the command line). Subcommands that parse the source also emit
  `"program_id"` (the PROGRAM-ID, or `null` if the program has none) as the
  second key — and, ONLY when the file holds more than one program unit,
  `"program_units"` listing every unit in source order, so a report can say
  which programs it did not cover (see *Selecting a program unit*). Analyzer
  reports get these via `_emit_report(..., ast=ast)`.
* **`parse`** — full-AST output gets `"source_file"` spliced in (the AST dict
  already carries `program_name`). With `--errors`/`--stats` the wrapper is
  `{"source_file", "program_id", "ast", ...}`. Dotted-path extraction emits
  `{"source_file", "program_id", "path", "result"}`; `--find-type` emits
  `{"source_file", "program_id", "node_type", "matches"}`.
* **`tokenize`** — `{"source_file": ..., "tokens": [...]}` (previously a bare
  token list).
* **`expand`** — expansion dict prefixed with `"source_file"` (no
  `program_id`: the source is not parsed).
* **`batch`** — a JSON list; each entry carries `"path"` and, when the parse
  produced an AST, `"program_id"`.
* **Text outputs** — Mermaid flowcharts start with a `%% Program: <name>`
  comment; DOT names the digraph after the program. `preprocess`
  output is deliberately unidentified (it is transformed source meant to be
  fed onward).
* **`gen-fixtures`** — `--format json` (default) follows the standard
  convention (`{"source_file", "bundle_version", "program_name", ...}`,
  `program_name` already inside the bundle rather than a separate
  `program_id` key). `--format csv-dir` writes a directory instead of
  stdout; its `MANIFEST.json` carries the same identification.

# Project config file (`cobol.yml`)

The **universal** project config the whole tool family reads — this CLI,
`mockymock`, and the COBOL Analyzer extension. One file per project instead
of the same flags on every invocation and in every editor's settings.
User-facing reference: `docs/project-config.md`.

Source: `cobolparser/config/` (`_yaml.py` reader, `project.py` schema +
discovery) and `cobolparser/cli/_project_config.py` (the argv merge).

**Public API** (`from cobolparser.config import ...`): `load_project_config(start_dir=None,
path=None) -> ProjectConfig` (an all-default `ProjectConfig()` with
`source=None` when nothing is found; `path` loads exactly that file, which is
what `--config` and the VS Code extension use), `find_config_file(start_dir)`,
`build_config(document, source)`, `resolve(cli_value, config_value,
hardcoded_default)` (the precedence helper), `parse_yaml` / `YamlError`,
`ConfigError`, `CONFIG_FILE_NAMES = ("cobol.yml", "cobol.yaml")`,
`SCHEMA_VERSION = 1`.

**Schema** (frozen dataclasses; every field `None`/empty when not stated, so
"not stated" stays distinct from "equals the default"):

| Section | Keys → `ProjectConfig` field |
|---|---|
| top level | `version`, `project`, `data`, `lint`, `mockymock`, `analyzer` (anything else is an error) |
| `project:` | `copybook_path`, `callee_path` (lists, resolved against the file's directory), `source_format` (`auto\|fixed\|free`), `debug_lines` (bool), `dialect` (`ibm-enterprise`), `error_recovery` (`collect-all\|fail-fast`), `seed`, `extensions`, `define` (normalized to `SYMBOL=VALUE`) |
| `data:` → `DataDefaults` | `charset`, `endian`, `record_format`, `record_separator`, `rows` |
| `lint:` → `LintDefaults` | `rules`, `min_severity`, `fail_on` |
| `mockymock:` / `analyzer:` | carried verbatim on `ProjectConfig.tools`; `tool_section(name)` returns the mapping or `{}` |

* **Discovery** — `cobol.yml` then `cobol.yaml` in the cwd and each parent,
  first match wins, walk bounded at 32 levels. Finding nothing is the common
  case and not an error. Paths inside the file resolve against **the file's
  own directory**, so a run from a subdirectory searches the same copybook
  libraries as one from the project root.
* **Precedence** — explicit CLI flag > config file > built-in default, merged
  in exactly one place (`_project_config.apply_project_config`), so every
  `_cmd_*` keeps reading `args.copybook_path` etc. unchanged.
* **`--config FILE` / `--no-config`** — stripped from argv by
  `extract_config_flags()` *before* argparse and before `main()`'s legacy
  "first positional isn't a subcommand, so prepend parse" rewrite. Two
  reasons: they work on either side of the subcommand, and the rewrite would
  otherwise take `--config`'s argument for the source file. They are declared
  on the top-level parser for `--help` only; argparse never sees them.
  Only the exact spellings are stripped, so `extract_config_flags()` also
  rejects (exit 1, a `ConfigError`) any `--X` / `--X=...` where X is a proper
  prefix of `config` or `no-config` -- `--no-conf`, `--no`, `--conf=FILE`,
  `--co` -- on either side of the subcommand (issue #323, 2026-10-14).
  Otherwise argparse's prefix matching swallowed them at the top level, or
  after the subcommand read them as one of its own options (`--no` for a
  `--no-...` flag), and the discovered `cobol.yml` silently stayed in force.
  Done on the raw argv rather than with `allow_abbrev=False` on every
  subparser, so abbreviations that cannot mean these two still work.
* **Telling a typed flag from a defaulted one** — most flags here have a
  non-`None` default (`--charset ascii`, `--dialect ibm-enterprise`,
  `--source-format auto`), so `is None` cannot answer "did the user pass
  this?". `provided_dests()` re-parses the same argv against a throwaway
  parser whose optional defaults are replaced with a sentinel (append actions
  get `None`, since argparse's append copies-and-appends to the default and a
  non-list sentinel would raise). Only runs when a config file was found.
* **Bound dests** — `copybook_path`, `callee_path`, `source_format`,
  `debug_lines`, `dialect`, `error_recovery`, `seed`, `extensions`, `define`, `charset`,
  `endian`, `record_format`, `record_separator`, `rows`, `rules`,
  `min_severity`, `fail_on`. Note `extensions`/`rules` are argparse *dests*,
  not the `--extension`/`--rule` flag spellings — getting that wrong is how
  the binding silently does nothing.
* **`--free-form`** is skipped when the user passed it: it is the legacy
  spelling of `--source-format`, which `_source_format_kwargs()` reads first,
  so filling `source_format` from the config would override a layout stated
  on the command line.
* **Fail-closed** — a malformed file, an unknown key, an out-of-range enum
  value or a missing `--config` target is `ConfigError` → `_fail()` → exit 1
  naming the file (and, for YAML syntax, the line). Never a silent fallback
  to defaults.
* **The YAML subset** — stdlib only (this package has no runtime
  dependencies). Nested mappings, block/flow sequences (a block sequence
  may sit at its key's own column -- the indentless form), flow mappings,
  quoted/plain scalars (`''` in single quotes; YAML 1.2's full double-quoted
  escape set, `\xXX`/`\uXXXX`/`\UXXXXXXXX` with exactly that many hex digits,
  `\e`/`\N`/`\_`/`\L`/`\P` included since 2026-09-28), `#` comments, one optional
  leading `---`, an optional trailing `...` (anything significant after it is
  a second document and rejected), a leading UTF-8 BOM (ignored). Anchors,
  aliases, tags, block scalars, merge keys, multiple documents, tabs in
  indentation and duplicate keys are **rejected with a line number**. Two
  deliberate YAML 1.2-core departures from 1.1: `yes`/`no`/`on`/`off` stay
  strings, and a duplicate key is an error rather than last-one-wins.
* **Comment stripping tracks quote state, and a backslash escape consumes
  the character after it.** `_strip_comment` runs before the parser, so it
  has to know which `#` is inside a string: `msg: "a \" # b"` keeps its
  whole value. (Until 2026-09-16 it advanced one character past a `\`
  instead of two, so an odd number of escaped quotes left a later `#` looking
  unquoted; pinned by `tests/regression/test_audit_2026_09_16.py`.)
* **A quote only opens a quoted span at the start of a scalar** (line start,
  or after `:`, `- `, `[`, `{`, `,`) -- `_opens_quote()`, shared by
  `_strip_comment`, `_split_key` and `_is_mapping_entry`. Mid-word it is a
  plain character: `owner: Sam's shop  # note` had kept `# note` in the value
  and `don't: 1` failed to parse. Fixed 2026-09-27.
* **Stricter where YAML is stricter** (2026-09-27, round 2): numbers resolve
  only for the YAML 1.2 core spellings (`1_000`, `\u0663`, `0x1F` stay strings;
  Python's `int()` had taken the first two); a plain value holding `: `
  (`key: a: b`) is rejected -- quote it; `- - x` is a nested sequence, not the
  string `"- x"`; and line numbers count `\n`/`\r\n`/`\r` records only
  (`split_source_lines`), not the form feeds / NEL / U+2028 `splitlines()`
  also broke on.
* **A sequence entry where a scalar belongs is rejected** (2026-09-28):
  `copybook_path: - copybooks` (and `[- x]`, `{k: - x}`, `key: -`) had come
  back as the *string* `"- copybooks"` -- a list the user wrote, silently
  turned into one directory name. YAML rejects it ("sequence entries are not
  allowed here"); so does `_is_sequence_indicator()` now. `-x` / `-1` are
  still plain scalars.
* **Tool sections** — `mockymock:` and `analyzer:` are validated only as
  mappings and carried verbatim on `ProjectConfig.tools`; this package never
  needs to know their schemas.

Tests: `tests/unit/test_config_yaml.py`, `tests/unit/test_project_config.py`,
`tests/unit/cli/test_project_config_cli.py`.

## Config

```bash
cobol-parser config [--json] [--compact] [-o FILE]
```

Reports which `cobol.yml` is in effect and every setting it supplies.
Settings the file does not mention are **omitted** rather than shown at their
built-in default, so what is printed is exactly what the file changes. With
no file found anywhere, says so and suggests creating one (exit 0). `--json`
emits `{"config_file", "version", "project", "data", "lint", "tools"}`
(`config_file` is `null` when none was found). Honours the global
`--config FILE` / `--no-config`.

# Subcommand details

Synopses below emphasise each subcommand's own flags; the shared flag sets
(**A**, **+prof**, **dl**) are listed per subcommand in the
[reference table](#subcommand-reference).

## Parse

```bash
cobol-parser parse <file.cbl> [json-path] [--compact] \
    [--source-format auto|fixed|free | --free-form] [--debug-lines] \
    [--dialect ibm-enterprise] [--error-recovery fail-fast|collect-all] \
    [--copybook-path DIR]... [--define SYMBOL[=VALUE]]... [-o FILE] \
    [--errors] [--stats] [--find-type NODE_TYPE] \
    [--profile] [--profile-top-n N] [--profile-output PATH]
```

**`--error-recovery`** (default `collect-all`) maps to `ErrorRecoveryMode`
(`_add_error_recovery_arg()` / `_get_error_recovery()`). It is not
`parse`-only: every subcommand built by `_build_analyzer_parser` takes it, as
do `batch`, `scan`, `lint`, `unused-variables`, `program-flow`, `redundancy`,
`business-rules`, `lineage` and `diff`. `tokenize`, `preprocess`, `expand`,
`gen-data`, `decode`, `compare`, `gen-fixtures`, `codebase-graph`,
`copybook-impact`, `field-impact`, `jcl`, `le-info` and `config` do not.
`cobol.yml` can bind it (`error_recovery`).

**`--copybook-path` / `--define`** on `parse` and every analyzer go through
the shared `_do_parse()`: with copybook paths the parse is
`parse_cobol_with_expansion(..., process_conditionals=True,
defined_symbols=...)` (so `--define` symbols reach `>>IF`s inside members); a
missing or circular copybook is a one-line `error: Copybook expansion failed
...` (exit 1). Without copybook paths, `--define` runs
`preprocess_conditional_compilation()` on the raw source first (keeping
`>>SOURCE FORMAT` directives for the normalizer), then `parse_cobol`.

Parses a COBOL file and prints the AST as JSON. `json-path` (dotted) extracts
a specific subtree. `--errors` shows parse errors only. `--stats` appends
`ParseStatistics`. `--find-type` finds all AST nodes of the given type (e.g.
`MoveStatement`), equivalent to `ast.find_all_by_type()`. `--profile` /
`--profile-top-n` / `--profile-output` wrap the parse in a `ProfilerContext`
(see [parser.md](parser.md)) and embed timing/memory metrics in the output, or
write a binary `.prof` to `PATH`. `--profile-output` (or a `--profile-top-n`
other than the default 20) implies `--profile` -- on its own it used to be
silently ignored (#328) -- and a `--profile-output` that is an existing
directory is a one-line `error:` (exit 1) before the parse, not an
`IsADirectoryError` traceback after it.

**Nested profilers (issue #274, 2026-10-05).** A `ProfilerContext` entered
while another profiler is active (an outer `ProfilerContext`, a bare
`cProfile`, anything on `sys.setprofile` or `sys.monitoring`'s PROFILER_ID)
skips cProfile: its result has `function_profile_available: false`, empty
`top_functions`, no `.prof` file, and a `caveats` entry, while wall-clock,
CPU and memory are still measured. Before, on 3.11 the inner cProfile
silently replaced the outer one (whose `top_functions` then held only
`__enter__`/`enable`), and on 3.12+ `enable()` raised after tracemalloc had
started, leaking the session. An inner context never stops a tracemalloc
session it did not start.

**Exit codes** (`_exit_if_partial_parse`): `0` clean parse; `1` hard
failure (`ast is None`, unreadable file); `2` recovered-but-errored parse —
the JSON is still printed, a summary goes to stderr (also argparse's own exit
code for bad arguments). `--find-type` follows the same rule (it exited `0` on
a partial parse until 2026-10-10). `batch` likewise exits `2` when any file
has a `read_error` or `success=false`. Analyzer subcommands exit `0` on a
partial parse (`_parse_result_or_fail`) but print `warning: <file> parsed with
N error(s); analysis may be incomplete` to stderr; `ast is None` is exit 1
there too. Rationale: before 2026-07-07 the CLI exited `0` whenever an AST
existed, so scripts gating on `$?` saw every partial parse as success.

## Tokenize

```bash
cobol-parser tokenize <file.cbl> [--compact] [--source-format auto|fixed|free | --free-form] \
    [--debug-lines] [--dialect ibm-enterprise] [-o FILE]
```

Prints the token stream as JSON:
`{"source_file": "...", "tokens": [{"type": "...", "value": "...", "line": N, "column": N}]}`
(`type` is the `TokenType` name). Goes through `lexer._tokenize_source`, the
same normalize-then-lex pipeline `parse` uses, with fixed-format comment lines
kept as `COMMENT` tokens; lexer errors are ignored (best-effort dump).

## Preprocess

```bash
cobol-parser preprocess <file.cbl> [--source-format auto|fixed|free | --free-form] \
    [--debug-lines] [--define SYMBOL[=VALUE]]... [--strip-directives]
```

No `--compact` / `-o`: the output is source text on stdout.

Runs fixed-format normalisation and conditional compilation; prints the resulting
free-form text. `--define` sets compiler flags for conditional blocks.
`--strip-directives` runs `strip_compiler_directives()` (PROCESS/CBL cards)
before anything else.
Under `auto` (the default) normalisation runs only when `detect_fixed_format` (`preprocess/source_format.py`)
classifies the source as fixed (it used to run unconditionally, silently
slicing columns off genuine free-form input); `--source-format=fixed` forces
it; `--source-format=free` skips it entirely.
Records are split with `_lines.split_source_lines` (\n / \r\n / \r only),
the same splitter the parser uses. Before 2026-09-28 `preprocess` used
`str.splitlines()`, so a form feed / NEL / U+2028 inside a comment record
split it in two and the comment's tail came out as code.
Normalisation goes through `source_format.normalize_with_recovery()`, like
`parse` and `tokenize`: an unterminated literal at end of file (a truncated
upload) prints `warning: Unterminated string literal ...` on stderr and the
recovered text on stdout, exit 0. Before #372 it escaped as a `ValueError`
traceback.

## Source layout (`--source-format`)

`--source-format {auto,fixed,free}` (default `auto`; mutually exclusive with
`--free-form`) is taken by `parse`, `tokenize`, `preprocess`, every subcommand
built via `_build_analyzer_parser` (`analyze`, `dead-code`, `complexity`,
`health`, `xref`, ...), and the hand-built `unused-variables`,
`program-flow`, `redundancy`, `scan`, `lint`, `business-rules`, `lineage` and
`diff`. `batch`, `expand`, `gen-fixtures`, `codebase-graph`,
`copybook-impact` and `field-impact` do **not** take it (their underlying APIs
— `parse_files`, the expander, `ProgramLayoutIndex`, the graph builders —
expose no layout override); they always auto-detect. `gen-data`, `decode`,
`compare` read only a record layout. `cobol.yml`'s `project.source_format`
fills it.

| Value | Behaviour |
|-------|-----------|
| `auto` | Detect via `detect_fixed_format` (`preprocess/source_format.py`) (see [parser.md](parser.md)) |
| `fixed` | Always normalise — strips columns 1-6 whatever they hold |
| `free`  | Never normalise |

`--free-form` is retained with its historical, *weaker* semantics — a
lexer-mode hint that auto-detection may still override by normalising
source it classifies as fixed-format (scripts that always passed it
against conventional fixed-format members relied on that lenience). It is
**not** an alias for `--source-format=free`, which hard-disables
normalisation. Passing both flags is rejected by argparse.

`--debug-lines` / `--no-debug-lines` (`BooleanOptionalAction`, default off)
ride along in `_add_source_format_args`: compile fixed-format `D` lines as
code instead of dropping them (see [preprocessing.md](preprocessing.md);
issue 334). `_source_format_kwargs()` adds `debug_lines=True` to its dict only
when set; `scan` forwards it as `ScanOptions.debug_lines`; `preprocess`
passes it to `normalize_fixed_format` directly. cobol.yml
`project.debug_lines: true|false` (strictly a boolean) fills it, and
`--no-debug-lines` is the way to override a `true` there. The subcommands
without `--source-format` that still parse COBOL (`batch`, `expand`,
`gen-fixtures`, `codebase-graph`, `copybook-impact`, `field-impact`) take it
through `_add_debug_lines_arg()` (2026-10-15): without the dest, the config
key was silently ignored by them. `gen-data` / `decode` / `compare` / `jcl` /
`le-info` / `config` have none (pinned by
`test_only_record_layout_subcommands_lack_debug_lines`).

Reach for `fixed` when a shop's layout defeats auto-detection — e.g. a
sequence area holding a tag with an internal space. Auto-detection already
handles the common case of a solid change-tracking tag (`SAPR24`, `28486`)
in columns 1-6; before that fix such files were silently treated as
free-form and their tag text lexed as code.

`preprocess`, and `parse` / every analyzer given `--define` without
`--copybook-path` (the CLI-side `preprocess_conditional_compilation` pass in
`_do_parse`), print conditional-compilation diagnostics
(unknown `>>IF` conditions, stray `>>ELSE`/`>>END-IF`, malformed
`>>DEFINE`, unclosed `>>IF` — audit 2026-07-07 H7) to **stderr** as
`warning: ...` lines, so deleted guarded blocks are not silent. With
`--copybook-path` the expander runs that pass instead, and `expand` reports
them in its JSON's `statistics.warnings`.
`preprocess` evaluates `>>IF` / `>>EVALUATE` / `>>DEFINE` **whether or
not `--define` is given** (issue #271, 2026-10-05): it used to run the
conditional pass only under `--define`, so without it every `>>IF ... >>ELSE`
came out with both arms and an in-source `>>DEFINE` was ignored.
`preprocess` (fixed-format branch only) additionally prints
`normalize_fixed_format`'s column-72 overflow diagnostics the same way
(2026-08-14 — see [preprocessing.md](preprocessing.md)'s "Column 73+
overflow warning" section): a non-comment line whose real content ran past
column 72 and was silently truncated.

## Expand

```bash
cobol-parser expand <file.cbl> [--copybook-path DIR]... [--keep-comments] [--source-map] \
    [--max-depth N] [--define SYMBOL[=VALUE]]... [--debug-lines] [--compact] [-o out]
```

Runs `expand_copybooks()` and prints its result as JSON:
`{"source_file", **CopybookExpansion.to_dict()}` (the expanded text plus
statistics). `--copybook-path` is repeatable (search order). `--max-depth`
(default 100) caps COPY nesting (`max_nesting_depth`). A missing / circular /
traversing COPY is a one-line `error: Copybook expansion failed ...`, exit 1
(same as `parse --copybook-path`). Conditional compilation runs inside the
expander, and only when `--define` is given (`process_conditionals=bool(defines)`),
so a program's own `>>DEFINE` reaches the copybooks beneath it; its
diagnostics land in the JSON's `statistics.warnings`, not on stderr.

`--keep-comments` (2026-09-07) puts every comment line's original text back
into the listing, in the program and in each inlined member. Expansion always
blanks comments first — a `COPY` written inside one must not be expanded — so
without this the output keeps their line numbers and loses their text, which
for a listing meant to be *read* is most of what was wanted. Restoration
happens after every substitution and changes no line of code and no line
number. See [preprocessing.md](preprocessing.md).

`--source-map` (2026-09-07) adds `source_location_map` to the JSON: one entry
per expanded line, `{"<expanded line>": {"file": ..., "line": ...}}`, naming
the file and line that line came from — the program itself, or the copybook it
was inlined from. This is what lets a consumer move a line number reported
against the expansion back onto a file a human edits; the `lint` subcommand
applies it for its own findings automatically (see below).

## Gen-Data

```bash
cobol-parser gen-data <file.cpy> [--rows N] [--seed N] [--record NAME] \
    [--list-records] [--describe] [--header-style short|path] \
    [--include-filler] [--include-redefines] [--no-expand-occurs] \
    [--max-occurs N] [--no-semantic] [--ignore-values] [--unique FIELD] \
    [--blank-rate RATE] [--format csv|json|record|hex] \
    [--charset ascii|ebcdic] [--endian auto|big|little|native] \
    [--record-format fixed|variable|variable-bare|auto] \
    [--record-varying MIN:MAX] \
    [--record-separator none|newline] [--compact] [--output FILE]
```

Generates synthetic CSV test data from a copybook record layout — see
[generators.md](generators.md) for the generation rules. Emits **CSV on
stdout** (not JSON), so it pipes directly into a fixture file; `--output`
writes through the `csv` module so quoted cells round-trip.

* `--rows`/`-n` — record count (default 10). `--seed` pins the RNG; the same
  seed and copybook always produce byte-identical CSV.
* `--list-records` and `--describe` are the two JSON modes.
  `--list-records` emits `{"source_file", "records": [{name, level, size}]}`;
  `--describe` emits the resolved layout plus rows, including the `seed`
  actually used — the way to recover the seed of an unseeded run.
* `--record NAME` picks among multiple level-01 records (default: the first).
  An unknown name errors and lists what is available.
* Layout errors (`CopybookLayoutError`) exit 1 with the message on stderr.

### `--format record` / `--format hex`: real record bytes

`csv` (default) and `json` emit **display** values — `72436.21` regardless of
whether the field is `PIC 9(7)V99` or `PIC S9(7)V99 COMP-3`. The other two
emit the **record image**: the bytes a COBOL program would actually read,
with `COMP-3` packed into nibbles, `COMP`/`COMP-4` as big-endian binary,
`COMP-5` and the floats in host order, and signed DISPLAY overpunched. See
[generators.md](generators.md)'s "Record images" section for the full
encoding table and its verified-against-GnuCOBOL provenance.

* `record` writes raw bytes — through `sys.stdout.buffer` on stdout and in
  binary mode to `--output`, since a `COMP` field routinely contains `0x0A`
  and a text-mode write would corrupt it. The image is encoded **once** and
  the same bytes go to whichever destination applies; the `--output` branch
  deliberately does *not* call `GeneratedDataset.write_records()`, which
  would encode the whole dataset a second time and hold both copies at once
  (a real ceiling on a large `--rows`, and a review finding on PR #200).
  `write_records()` itself is unchanged and still right for a caller that
  has not already encoded. `hex` is the same image annotated
  field by field (offset, length, name, PICTURE, USAGE, value, bytes), which
  is the form that survives being opened in an editor.
* `--charset ebcdic` encodes every DISPLAY byte as cp037 and switches the
  zoned-sign convention to EBCDIC zones; the sign convention is **not** a
  separate flag, it follows the charset.
* `--endian` (default `auto`) applies to `COMP-5` and `COMP-1`/`COMP-2` only
  — `COMP`/`COMP-4` are always big-endian. `auto` reads the charset as
  intent: big-endian for `ebcdic` (z/OS-bound), host order otherwise.
* `--record-format` picks fixed- or variable-length records — see the next
  section.
* `--record-separator newline` appends `\n` per record for readability;
  the default `none` is a true fixed-length RECFM=F image.
* Both formats force the byte-complete layout (`DataGeneratorOptions
  .for_record_image()`: FILLER in, REDEFINES out, every OCCURS occurrence
  expanded) and print a note to stderr saying so, since otherwise
  `--include-filler`/`--max-occurs` would look silently ignored.
* Anything not modelled (`SYNCHRONIZED` alignment, IEEE-vs-hex float,
  `OCCURS DEPENDING ON` written at maximum under `--record-format fixed`) is
  printed to stderr for `--format record` and inlined in the header for
  `--format hex` — never swallowed.

### `--record-format`: fixed- vs variable-length files

A copybook says how long a record *can* be, not whether the file holding it
is RECFM=F/FB or RECFM=V/VB. This flag says which one to write; it applies
to `--format record|hex` only (CSV and JSON have no notion of record length).

| Value | Records | Framing |
|-------|---------|---------|
| `fixed` (default) | every `OCCURS ... DEPENDING ON` occurrence written, one length for the whole file | none |
| `variable` | only the occurrences each record's own counter names | 4-byte RDW per record |
| `variable-bare` | the same trimmed records | none |
| `auto` | `variable` if the record varies at all, else `fixed` | follows the resolved value |

* **`fixed` is the default so existing output does not move.** A record that
  cannot vary writes identical bytes under every value bar the RDW, so the
  choice only matters where records genuinely can vary. `--record-varying` is
  the exception: it *says* records vary, so passing it alone reaches `auto`
  rather than writing a fixed file; an explicit `--record-format fixed` still
  wins.

**Two ways a record varies**, and `gen-data` handles both:

1. `OCCURS ... DEPENDING ON` in the record — the count of occurrences decides
   the length, and the counter is generated inside the table's bounds.
2. `FD ... RECORD VARYING FROM min TO max DEPENDING ON item` on the file —
   the record layout is flat and the length is simply how many of its bytes
   each record carries. Given a **whole COBOL program**, the FD clause is read
   off the record with no flag at all. Given a bare **copybook**, which has no
   FD, `--record-varying MIN:MAX` supplies the range (`MIN-MAX` is accepted
   too, since that is how it reads in the FD). The cut can fall mid-field —
   which is exactly what a program reading `REC(1:LEN)` sees — and
   `--format hex` marks the fields past it as `(past record length)` and the
   field it falls inside as `(cut N/M bytes)`. A range reaching past the
   record's own bytes is clamped to them, and one with nothing left
   (`40:50` on a 28-byte record, or equal bounds) is ignored -- both with a
   `warning:` on stderr (every format) and a `* caveat:` in the hex header
   (#274); previously both happened silently.
* **The RDW** is `LL LL 00 00` — a big-endian 16-bit length *including the
  four RDW bytes*, then two reserved zero bytes — regardless of `--charset`
  and `--endian`. A record whose total would exceed 65 535 bytes errors out
  rather than writing a wrapped length; that needs RECFM=VS (spanned), which
  is not generated.
* **The counter is generated inside the table's own bounds**, so `OCCURS 1 TO
  50 DEPENDING ON WS-N` never emits a `WS-N` of 8 731 — under `fixed` too.
* **The resulting LRECL (or LRECL range) is printed to stderr** for
  `--format record`, because raw bytes carry no header to state it in. When a
  range is declared, the *declared* LRECL is printed alongside the span the
  generated file happens to contain — a short `--rows` may never hit the
  maximum, but the dataset still has to be allocated for it.
  `--format hex` puts it in its own header, along with a `(RDW)` row per
  record so field offsets stay true.
* A DEPENDING ON counter that is **not part of the record** (declared in
  WORKING-STORAGE, say) is named on stderr and its table written at full
  length — nothing generated can set it.

## Gen-Fixtures

```bash
cobol-parser gen-fixtures <file.cbl> [--copybook-path DIR]... [--callee-path DIR]... \
    [--rows N] [--seed N] [--max-occurs N] [--scenarios happy|branches|all] \
    [--format json|csv-dir] [--list-boundaries] [--strict] [--debug-lines] \
    [--compact] [--output PATH]
```

Phase 3 of the `gen-fixtures` program-scoped test-data initiative (see
[generators.md](generators.md)'s "Program fixtures" section): points at a
whole **program** rather than a copybook, and produces mock in-data /
assert-on stubs for every boundary it touches (files, CALL/DYNCALL, SQL,
CICS, DLI, console ACCEPT) — not just one record's CSV rows.

* `--copybook-path DIR` (repeatable) expands COPY statements before
  analysis; an unresolved COPY member refuses (`ProgramLayoutError`, exit 1)
  rather than generate a bundle from a layout with a hole in it.
* `--callee-path DIR` (repeatable) searches for a statically-CALLed
  program's own source (tries `NAME`, `name` × `""`/`.cbl`/`.CBL`/`.cob`/
  `.COB` in each directory) to resolve its LINKAGE writes for the CALL
  argument-direction ladder's "callee source" rung. A caller/callee pair
  already bundled in one compilation unit (`CobolProgram.contained_programs`,
  e.g. `subprogram_demo.cbl`) needs no `--callee-path` at all.
* `--rows`/`-n` — rows generated per **READ** boundary's sequence (default
  10); every other IN boundary (SQL SELECT/FETCH, ACCEPT, a CALL argument)
  generates exactly one value, matching one invocation in the "happy path"
  scenario. A negative `--rows` (or `data.rows` in `cobol.yml`) or a
  `--max-occurs` below 1 is a one-line `error:` with exit 1, as in
  `gen-data` (#327).
* `--max-occurs N` caps the occurrences expanded per OCCURS table.
* `--seed` pins the RNG; the same seed and program always produce
  byte-identical JSON (`ProgramFixtureGenerator.generate`'s own per-boundary
  sub-seed scheme -- see generators.md -- means adding one boundary never
  reshuffles another's already-generated values).
* `--scenarios happy` (default) emits the single unconstrained "happy path"
  scenario (Phase 3). `branches` targets every reachable, satisfiable branch
  arm with its own (or a merged) scenario; `all` additionally adds the fixed
  empty-input / error-status / boundary-values scenario families -- both
  route through `cobolparser.generators.scenarios.ScenarioPlanner` (Phase 5)
  via `ProgramFixtureGenerator.generate_with_scenarios_from_file` (Phase 6)
  and populate the bundle's `scenario_coverage` key (`null` under `happy`).
  See generators.md's "Scenario Planning" and "Scenario-mode generation"
  sections, and `docs/fixture-bundle-schema.md` for the full JSON shape.
* `--format json` (default) emits the full bundle; `--format csv-dir`
  requires `--output DIR` and emits one CSV per file-shaped boundary fixture
  under `DIR/<scenario-slug>/<KEY>.csv` plus a `DIR/MANIFEST.json` (the
  bundle with every fixture's `sequence` emptied to `[]` -- never replaced
  with a hint string, so the manifest stays type-compatible with a normal
  bundle -- and a new `csv_path` key per fixture: the relative CSV path, or
  `null` for a fixture with no CSV written, e.g. a STATUS_ONLY boundary).
* `--list-boundaries` runs Phases 1-2 only (no value generation) and emits
  `{"source_file", "boundaries": [{category, key, paragraph, line,
  direction}, ...]}` — the cheap debugging view, and the natural cross-check
  against a downstream consumer's own boundary walk.
* `--strict` exits **2** (not 1 -- that stays "could not run at all") when
  `bundle.unresolved` is non-empty: anything Phase 1's index, Phase 2's
  inventory, or Phase 3's own field resolution could not pin down -- and
  (since #244) any branch arm whose scenario's own data *violates* it. The
  CI-friendly "no silent gaps" switch.

## Selecting a program unit (`--program`)

```bash
cobol-parser dead-code NESTED.cbl --program INNERP
```

A source file can hold several `PROGRAM-ID`s — stacked, or nested inside the
enclosing program's PROCEDURE DIVISION — and every analyzer here is
program-scoped: it grades a paragraph against the references it can see, so a
report is about ONE unit. It has always been the outermost, silently; a
contained program came back "clean" because it was never examined.

`--program NAME` (2026-09-07; on every subcommand built by
`_build_analyzer_parser`, plus `unused-variables`, `program-flow`,
`redundancy`, `lint`, `business-rules` and `lineage`) selects the unit to report on,
case-insensitively, via `CobolProgram.find_program_unit`. An unknown name
fails with the list of units that are there rather than falling back to a
report about a different program.

Whenever a file holds more than one unit, every such report also carries
`"program_units": [...]` in its identification header, listing them all in
source order — so a report can say what it did *not* cover. A single-program
file's output is unchanged, key for key.

`lint` and `program-signature` are the deliberate exceptions to the default:
they cover every unit unless `--program` narrows it. `scan` takes no
`--program` (it reports every unit of every file), and `diff` has none yet.
`field-impact --program` and `jcl --program` mean something else (the
PROGRAM-ID owning FIELD; the steps that run a program).

## Analyze

```bash
cobol-parser analyze <file.cbl>
```

Runs `DynamicCallAnalyzer` and prints a JSON summary of dynamic `CALL`
targets only (`called_program`, `is_dynamic`, and `possible_values` when
dynamic; a dynamic entry also carries `"possible_values_incomplete": true`
when the analyzer flagged the value set as not fully resolvable — see
`.okf/analysis.md`'s DynamicCallAnalyzer section — so the list is never
silently presented as exhaustive; added in the 2026-08-16 audit). Despite
the generic name, this is *not* an all-analyzers summary —
dead code, IO, MOVE-type, linkage, and LE checks each have their own
dedicated subcommand below.

## Dead-Code

```bash
cobol-parser dead-code <file.cbl>
```

Runs `DeadCodeAnalyzer` and lists unreachable paragraphs/sections. A
paragraph referenced only from dead code is dead too (issue #384).

## Unused-Variables

```bash
cobol-parser unused-variables <file.cbl> [--copybook-path DIR ...] \
    [--exclude-copybook-variables] [--profile ...]
```

Runs `UnusedVariableAnalyzer` (see `.okf/analysis.md`) and lists DATA
DIVISION items never referenced in the PROCEDURE DIVISION.
`--exclude-copybook-variables` filters out unused items that came from an
expanded COPY; it only has an effect together with `--copybook-path`
(otherwise a stderr warning notes the no-op) since copybook provenance is
determined by parsing the source a second time *without* expansion
(`_parse_without_copybook_expansion`) and diffing declared item names
against the expanded AST — `expand_copybooks`'s own line-tracking
(`preserve_source_locations`) doesn't work (see `.okf/analysis.md`).
With `--copybook-path`, each unused item also carries
`"origin": {"file", "line"}` from `ParseResult.expansion_source_map`
(`analysis.lint.stamp_report_origins`, 2026-09-27): `location.line` counts
lines of the expanded text, so past the first `COPY` it was not the line on
disk. `location` is left as it was.
**Origin stamping applies to every analyzer, not just this one:** since
2026-09-28 it is done once, in `_emit_report`, for every
analyzer subcommand that takes `--copybook-path` (dead-code, complexity,
health, move-type-check, xref, ...): `_parse_result_or_fail` remembers the
map on `args._expansion_source_map`. Previously only lint and
unused-variables said where an expanded-listing line really is. Additive:
no map (no `--copybook-path`), no `origin`. Locations not under a
`location` key get a sibling of their own name (2026-10-14, #367): xref's
`definition` gains `definition_origin`, program-flow's
`exit_statement_location` gains `exit_statement_origin`
(`analysis.lint._ORIGIN_KEYS`). `gen-fixtures` is *not* stamped
(its bundle uses bare `line` keys under `bundle_version`).

## Program-Flow

```bash
cobol-parser program-flow <file.cbl> [--format json|mermaid|dot] [--profile ...]
```

Runs `ProgramFlowAnalyzer` and emits the control-flow graph. `--format`
selects the output: `json` (default, raw `report.to_dict()` edges), `mermaid`
(via `generators/flowchart.py`'s `MermaidFlowchartGenerator`), or `dot`
(Graphviz DOT via `DotFlowchartGenerator`). Also accepts the shared
profiling flags (`--profile`, `--profile-top-n`, `--profile-output`);
`--profile` metrics can only be embedded in `json` output, so combining it
with `mermaid`/`dot` prints a stderr warning instead of silently
discarding the profiler result (2026-08-16 audit).

## Recursion-Check

```bash
cobol-parser recursion-check <file.cbl> [--profile ...]
```

Runs `RecursionRiskAnalyzer` (see `.okf/analysis.md`) and reports recursion-
driven infinite-loop risks: PERFORM/GO TO cycles reused from
`ProgramFlowAnalyzer`'s `cycle_details` (`PERFORM_RECURSION` always `HIGH`;
`GOTO_LOOP`/`MIXED` graded `HIGH`/`MEDIUM` by whether the cycle has an
escape route) and self-recursive CALL statements (static or dynamic,
targeting the program's own `PROGRAM-ID`, always `HIGH`). Registered the
same way as `dead-code`/`data-items` (via `_build_analyzer_parser(...,
profiling=True)`), so it also accepts the shared profiling flags.

## Complexity

```bash
cobol-parser complexity <file.cbl> [--profile ...]
```

Runs `ComplexityAnalyzer` (see `.okf/analysis.md`) and reports per-paragraph
McCabe cyclomatic complexity, an AND/OR-aware `extended_complexity`, max
nesting depth, fan-in/fan-out (from `ProgramFlowAnalyzer`'s PERFORM/GO TO
edges), and a LOW/MODERATE/HIGH `rating` per procedure, plus a program-level
summary (`total_complexity`, `mean_complexity`, `goto_density`, ...).
Registered the same way as `recursion-check` (`_build_analyzer_parser(...,
profiling=True)`).

## Health

```bash
cobol-parser health <file.cbl> [--profile ...]
```

Runs `TechnicalDebtAnalyzer` (see `.okf/analysis.md`) and reports a
composite 0-100 technical-debt score with an A-F letter grade, a per-
component breakdown (`complexity`/`redundancy`/`control_flow`/`size`, each
with its own findings), and a `top_offenders` list of the worst procedures
with the specific reasons (dead code, clone membership, GO TO count, no-
escape recursion cycle, ...) that put them there. Embeds the underlying
`ComplexityReport`/`RedundancyReport` summaries (`complexity_summary`/
`redundancy_summary`) rather than the full per-procedure detail -- run
`complexity` directly for that. Registered the same way as
`recursion-check`.

A file that parsed with errors still exits 0, but its JSON has `"grade":
null`, a nonzero `parse_error_count` and a `caveats` entry (#397): the score
then covers only what the parser recovered.

## Lint

```bash
cobol-parser lint <file.cbl> [--rule RULE]... [--min-severity error|warning|info] \
    [--fail-on error|warning|info|never] [--format json|text] [--copybook-path DIR]... \
    [--program NAME] [standard analyzer flags (A) + profiling]
```

Runs `LintAnalyzer` (see `.okf/analysis.md`) — several analyzers over **one**
parse — and reports every finding as a single severity-graded list, instead of
one subcommand (and one re-parse) per concern.

`--rule` (repeatable) selects rules; the ids are deliberately the analyzer
subcommand names themselves: `dead-code`, `unused-variables`,
`move-type-check`, `io-sequence`, `linkage-check`, `recursion-check`,
`complexity`, `dclgen-check`, `sql-cics-check`. Argparse `choices` rejects an
unknown id, so a typo can never
read as "that rule found nothing". Ordering and duplicates in the flags do not
affect the report — the selection is normalized to the canonical rule order.

`--min-severity` (default `info`, i.e. everything) drops lower-severity
findings *after* the rules run, so the summary counts always describe what was
actually shown.

`--format json` (default) emits the standard identification header plus
`findings` / `rules_run` / `failed_rules` / `caveats` / `summary`. `--format
text` emits one `file:line:column: severity [rule] message` line per finding —
the prefix an editor's or build log's error parser already understands —
followed by `note:` lines for caveats and failed rules, then a summary line.
A finding with no location (a recursion cycle spans procedures) prints as
`file: severity ...`; the column is omitted rather than faked as 0.

**Columns are on-disk columns (#301, 2026-10-13).** Analyzer locations count
columns in the *normalized* text, which for a fixed-format line is columns
8-72 -- so they are 7 short of what an editor shows. `_lint_column_offset`
returns a `(file, line) -> offset` function: the program itself is judged
the way `CobolParser` decides (`--source-format`, else `detect_fixed_format`),
each copybook the way the expander judged it (`_looks_fixed_format`), and
within a fixed-format file a line after `>>SOURCE FORMAT FREE`
(`preprocess.source_format.free_format_flags`) gets no shift. The per-file table lives in
`analysis.lint.fixed_format_column_offset`: fixed listing + fixed file 7,
fixed listing + free member 0 (the expander re-pads it by exactly 7), free
listing + fixed member 6 (the expander cuts only the sequence area), free
throughout 0. Lint now **always** stamps `origin` -- without
`--copybook-path` it is the file itself, same line -- so JSON carries the
on-disk column as `origin.column` in both cases and text prints it;
`location.column` stays the analyzer's own count. Text prints only a
column it can vouch for: a parse error that reported no column
(`LintFinding.column_known` False), a copybook that cannot be re-read, or a
line the source map does not cover prints `file:line:` and has no
`origin.column`, rather than the analyzer column (7 short on a fixed line).
Known gap (predates #301): a `>>SOURCE FORMAT IS FREE` *inside a copybook*
leaves the expanded listing a column off, so those columns are off by one.
`stamp_report_origins` no longer overwrites an `origin` already present, or
`_emit_report` would drop that column again.

**Exit codes.** `0` ran to completion (findings alone never change it); `1`
the file could not be read, produced no AST at all, or its output could not
be written (`_fail`); `2` argparse rejected the arguments — an unknown `--rule` or flag,
which argparse exits on itself before `_cmd_lint` ever runs (pinned by
`test_lint_subcommand.py::test_unknown_rule_is_rejected_by_argparse`); `3`
`--fail-on` was given and a finding at or above that severity was reported.
`3` rather than the conventional `1` on purpose: a CI gate must be able to
tell "this program has problems" from "lint never ran", and `1`/`2` already
mean something else across this CLI (see *Exit codes* above).

**Parse errors are findings** (2026-10-04, #249). A file that parses *with
errors* still yields a partial AST, and a partial AST lints quietly: a file
that was not COBOL at all used to print `0 finding(s)` and exit `0` even
under `--fail-on info`. `_cmd_lint` now runs `add_parse_errors()` (in
`analysis/lint.py`) over `result.errors` before the source map and the
severity filter: each becomes a `rule: "parse"`, `severity: "error"` finding
at the error's line/column (`kind` = the error's code or class name). So
`--fail-on` (any level) exits `3` on such a file, and the JSON and text
report say why; without `--fail-on` the run still exits `0` and the partial
findings stay usable -- option (b) of the issue, rather than a hard exit
`1`. `parse` is not in `RULES`, so `--rule` neither selects nor drops it.

`--copybook-path` does triple duty here: it expands COPY members so MOVE
operands resolve, it lets lint tell a copybook-sourced unused item (info)
from one the program declares itself (warning) via the same unexpanded-parse
set difference `unused-variables` uses, *and* (2026-09-07) it turns on
finding origins. With expansion, every analyzer location counts lines in the
expanded text; the expander's own source map turns each one back into a real
file and line, emitted per finding as `"origin": {"file", "line"}` and used
by `--format text` for its `file:line:column:` prefix. A finding inside an
inlined member therefore names the *copybook*, not the program. Findings the
map cannot place carry no `origin` key rather than a guess. Since #301
(2026-10-13) a run with no expansion **does** carry `origin` on every located
finding -- the file itself, the same line, plus the on-disk `column` -- so
"`origin` present" no longer means "copybooks were expanded"; compare
`origin.file` with `source_file` for that.

**Copybook provenance covers every unit too.** `_lint_copybook_item_names`
diffs declared DATA DIVISION names between an expanded and an unexpanded
parse, and `collect_declared_items` is program-scoped -- so once lint covered
every unit, diffing the outermost alone left a contained program's copybook
fields out of the set and graded them `warning` instead of `info`. Both sides
now walk `program_units()`, and both are narrowed the same way when
`--program` selects one (otherwise another unit's own declaration of the same
name subtracts from this one's copybook set). Pinned by
`tests/regression/test_nested_program_units.py::TestCopybookProvenanceCoversEveryUnit`.

**Program units.** Unlike every other analyzer subcommand, `lint` covers
*every* program unit in the file by default — a contained program left
unexamined would read as a clean one. `--program NAME` narrows it to one (see
*Selecting a program unit* above).

## Batch

```bash
cobol-parser batch [prog1.cbl prog2.cbl ...] [--glob PATTERN]... [--workers N] \
    [--encoding utf-8] [--stats] [--errors] [--dialect ibm-enterprise] \
    [--error-recovery fail-fast|collect-all] [--debug-lines] [--compact] [-o FILE] \
    [--profile ...]
```

Parallel multi-file parsing via `ProcessPoolExecutor`. Files may be given
positionally and/or collected via repeatable `--glob` patterns (e.g.
`--glob 'src/**/*.cbl'`). `--workers` sets the process-pool size (default: CPU
count). `--encoding` sets file read encoding (default `utf-8`). Prints one
JSON result per file. `--errors` includes parse errors/warnings per file;
`--stats` appends per-file `ParseStatistics`. `--profile-output` in batch mode
must be a directory (one `.prof` per file), not a single file path: a `.prof`
name or an existing regular file is a one-line `error:` (exit 1). As for
`parse`, `--profile-output` / a non-default `--profile-top-n` imply `--profile`.

## IO-Sequence

```bash
cobol-parser io-sequence <file.cbl>
```

Runs `IOSequenceAnalyzer` and reports sequencing violations.

## Move-Type-Check

```bash
cobol-parser move-type-check <file.cbl>
```

Runs `MoveTypeChecker` and reports type-incompatible MOVE statements.

## Linkage-Check

```bash
cobol-parser linkage-check <file.cbl>
```

Runs `LinkageChecker` and reports LINKAGE SECTION violations.

## Language-Env

```bash
cobol-parser language-env <file.cbl>
```

Runs `LanguageEnvironmentAnalyzer` and reports IBM LE function/service usage.

## LE-Info

```bash
cobol-parser le-info                    # the whole catalogue
cobol-parser le-info CEEDAYS            # one LE callable service
cobol-parser le-info NUMVAL-C           # one intrinsic function
cobol-parser le-info --kind service     # every catalogued service
cobol-parser le-info CEEGMT --compact -o le.json
```

The only subcommand that reads **no source file**: it dumps
`cobolparser/dialects/le_signatures.py`'s call-signature catalogue, which is
static dialect knowledge rather than analysis. Backs the COBOL Analyzer VS
Code extension's LE hover ("what does this CALL need?"), so its JSON shape is
pinned by `catalog_version`.

Output has no `source_file` / `program_id` identification header (there is no
source). With no name: `{catalog_version, reference, services[],
services_without_signature[], functions[]}`. With one or more names:
`{catalog_version, reference, entries[]}`, in the order asked.

A name the dialect recognises but the catalogue cannot describe comes back
with `"parameters": null` and a note saying so — distinguishable from an
unknown name, which exits 1. `--kind service|function|all` restricts both
forms.

## IMS-DLI

```bash
cobol-parser ims-dli <file.cbl>
```

Runs `IMSSegmentAnalyzer` and reports IMS DLI segment calls.

`is_ims_program` is `ast.has_ims() or ast.uses_ims_interface()`: a program
that calls CBLTDLI / AIBTDLI / CEETDLI is an IMS program whether or not it
declares `ENTRY 'DLITCBL'` (issue #398). Each call's `primary_segment` is its
**last** segment -- see `IMSSegmentAnalyzer` in `analysis.md`.

## Data-Items

```bash
cobol-parser data-items <file.cbl> [--profile ...]
```

Runs `compute_program_data_items()` (see [generators.md](generators.md)'s
`layout_offsets.py` entry) and reports `{"items": [...], "unresolved":
[...]}` — byte offset, byte length, REDEFINES chain, OCCURS min/max, and
level-88 condition values for every data item across every DATA DIVISION
section (FILE/WORKING-STORAGE/LOCAL-STORAGE/LINKAGE) of the program.
Registered via `_build_analyzer_parser(..., profiling=True)`, so it takes
the standard analyzer flags plus the profiling flags (added 2026-08-14 as the
final wiring step of the data-item-layout plan).

## Decode

```bash
cobol-parser decode [data-file] --copybook <FILE.cpy> \
    [--record NAME] [--view NAME] [--list-views] \
    [--format csv|json|hex] [--charset ascii|ebcdic] \
    [--endian auto|big|little|native] \
    [--record-format fixed|variable|variable-bare|auto] \
    [--record-length N] [--record-separator none|newline] \
    [--max-records N] [--skip N] [--strict] [--compact] [-o OUT]
```

The inverse of `gen-data --format record`: **bytes somebody else wrote, plus
a copybook, back into a table.** A VSAM extract, an EBCDIC flat file, a tape
image — none of them self-describing, all of them keyed only by the copybook
compiled against them. Implementation:
`generators/data/decoding.py` + `generators/data/views.py`, documented in
[generators.md](generators.md)'s "Record views and decoding".

* Two inputs, in the order they read: the **data file** is positional, the
  **copybook** is `--copybook`. The data file is optional only with
  `--list-views`, which reads nothing but the copybook; without it, omitting
  the data file is an error rather than an empty decode. `--record` picks the 01 when
  the copybook holds several, through the same `select_record()` `gen-data`
  uses, so both halves land on the same layout.
* **`--view`** reads the same bytes through a `REDEFINES` overlay, by the
  redefining item's own short name (`ADDR-OVERSEAS`) or its qualified path
  (`CUST-REC.ADDR-OVERSEAS`). The output is the whole record with the
  overlay's fields in place of the redefined item's (every occurrence, inside
  a table), so `compare --view` can still `--key` on fields outside it (#296). **`--list-views`** prints the layout and every
  overlay with byte offsets and exits *without needing a data file at all* —
  which is also how you find out what `--view` will accept.
* **`--format`**: `csv` (default) is one row per record, byte-identical to
  what `gen-data` would have written for the same layout; `json` adds every
  field's offset, length, raw hex, `present`/`truncated`/`error`; `hex` is a
  byte pane whose lines are the field boundaries, with `! field: error` under
  the bad ones.
* **`--charset`/`--endian`/`--record-format`/`--record-separator`** mean
  exactly what they mean on `gen-data`, and are the same `EncodingOptions`.
  `--record-format auto` resolves the same way on both sides for the same
  source: variable when the layout has a DEPENDING ON table **or** the
  `--copybook` is a whole program whose FD declares `RECORD VARYING`
  (`RecordDecoder.varying`, read off `fd_clauses` in `from_record()`).
  Before 2026-09-28 decode's auto only looked at the layout, so the
  RDW-framed file `gen-data v.cbl --record-format auto` wrote was read back
  fixed-length and garbled, exit 0.
  `--record-length` is decode-only: an LRECL to cut fixed-length records at
  when the file's records are longer than the copybook describes (trailing
  slack, or a copybook covering only a prefix). With no `--record-length`
  and a whole-program source, it defaults to the FD's LRECL (the largest 01
  under the FD, or a larger `RECORD CONTAINS n`), so `--record HDR-REC` on a
  shorter 01 still frames the file right (#362); `gen-data --format
  record|hex` pads that 01 out to the same LRECL with spaces.
* **`--max-records`/`--skip`** page a large file. A run stopped by
  `--max-records` does *not* report the rest of the file as trailing bytes.
  A negative `--max-records`/`--skip`, or a `--record-length` that is not
  positive, is an error (exit 1; exit 2 on `compare`) -- 2026-09-27: a
  negative length had claimed the layout was zero bytes long, `0` was
  silently replaced by the layout length, and `--max-records -1` printed
  only a header.
* **stderr is never silent about a mismatch**: every caveat, a count of
  fields that did not decode cleanly, and any trailing bytes that are not a
  whole record (which nearly always means the record length is wrong).
  **`--strict`** turns either of the last two into exit 1 — the CI form of
  "does this copybook actually describe this file?".

## Compare

```bash
cobol-parser compare <expected> <actual> --copybook <FILE.cpy> \
    [--record NAME] [--view NAME] [--key FIELD]... [--ignore FIELD]... \
    [--compare-bytes] [--max-differences N] [--format text|json] \
    [--charset ascii|ebcdic] [--endian auto|big|little|native] \
    [--record-format fixed|variable|variable-bare|auto] \
    [--record-length N] [--record-separator none|newline] [--compact] [-o OUT]
```

Two record files, one copybook, field-level differences: the expected output
of a batch run against the actual one. Implementation:
`generators/data/compare.py`, documented in [generators.md](generators.md)'s
"Record compare".

* **Exit status follows `cmp`/`diff`**: 0 equal, 1 different (including
  differing trailing partial records -- `CompareResult.trailing_differs`,
  see generators.md, #250), 2 the
  comparison could not be made (unknown key/ignore name, unreadable file,
  layout error, unwritable `-o`). `_cmd_compare` therefore uses its own
  `_compare_fail()` (exit 2) and its own output writer rather than `_fail()` /
  `_verbatim_out()`, both of which exit 1 -- which here would read as "the
  files differ". Two failures happen before `_cmd_compare` runs or outside
  its expected exceptions and used to exit 1 (2026-09-28): a `--config` /
  `cobol.yml` error (`main()` now routes it through `_config_fail()`, which
  exits 2 when the subcommand is `compare`), and a copybook that is not text
  (a `UnicodeDecodeError` traceback; now caught).
* A text field padded with LOW-VALUES on one side and spaces on the other
  is a difference without `--compare-bytes` (#287), except in FILLER,
  which only `--compare-bytes` checks; when the two values
  print the same, the text report adds both fields' hex.
* **`--key`** (repeatable) pairs records by key; **`--ignore`** (repeatable)
  drops a column, a field name (every occurrence) or a group. Both are checked
  against the layout; a typo is exit 2 with the valid column names.
* The file-format flags (`--charset` through `--record-separator`) are shared
  with `decode` through `_add_record_file_args()`, so they mean exactly the
  same thing and pick up the same `cobol.yml` `data:` settings. Both files are
  read with the same options.
* `--format text` (default) is a report with 1-based record numbers; `json` is
  `CompareResult.to_dict()` plus the three input paths, with 0-based indexes.

## Dclgen-Check

```bash
cobol-parser dclgen-check <file.cbl> [--profile ...]
```

Runs `DclgenChecker().check(ast)` (see [analysis.md](analysis.md)) and
reports `{"violation_count", "checked_count", "unchecked_count",
"worst_severity", "tables", "violations", "checked", "unchecked",
"ambiguous_columns"}` — every `:host-var` graded against the DCLGEN
`DECLARE TABLE` column of its name, for scale, precision, length, category,
usage, sign, and missing null indicators. Registered via
`_build_analyzer_parser(..., profiling=True)` like the other analyzer
subcommands, and also available as the `dclgen-check` rule of `lint`.

## Redundancy

```bash
cobol-parser redundancy <file.cbl> [--min-clone-statements N] [--program NAME]
                                   [--copybook-path DIR] [--compact] [-o out.json]
                                   [standard analyzer flags (A) + profiling]
```

`RedundancyAnalyzer`'s whole report: `dead_code`, `unused_variables`,
`clone_groups`, and `paragraph_fingerprints` -- the last of which no other
subcommand exposes (`health` folds redundancy into a score and a summary and
drops the digests). Built with its own parser rather than
`_build_analyzer_parser` only because of `--min-clone-statements`, which it
shares with `scan` through `_add_min_clone_statements_arg` so the two cannot
default differently: a scan and a single-file run that disagreed about what
counts as a clone would report different groups for the same program.

## Scan

```bash
cobol-parser scan FILE... [--glob PATTERN]... [--files-from LIST] [--analyzer NAME]... [--clones]
                          [--min-clone-members N] [--min-clone-statements N]
                          [--workers N] [--copybook-path DIR] [--encoding ENC]
                          [--source-format auto|fixed|free | --free-form] [--debug-lines]
                          [--dialect ibm-enterprise] [--error-recovery MODE]
                          [--compact] [-o out.json]
```

Many files, one process. Unlike running an analyzer once per file, the parse
*and* the analysis happen inside a worker and only the report dicts come
back, so a whole checkout fits in one invocation and a worker's peak memory
is one file's AST. Implemented in `cobolparser/scan.py` (not `batch.py` --
see batch.md for why the two are separate).

`--analyzer` takes both the repeated and the comma-separated spelling
(`parse_analyzer_list`); one of `health`, `redundancy`, `complexity`,
`dead-code`, `unused-variables`, `lineage` (2026-10-08; the
`FieldFlowReport` `field-impact` joins), defaulting to `health,redundancy`. An
unknown name exits 1 naming the known set -- argparse `choices` would reject
the comma spelling, so the check lives in `scan_files` instead.

`--clones` additionally groups every scanned paragraph into cross-file clone
groups by fingerprint (`cross_file_clone_groups`), Type-1 taking precedence
over Type-2 exactly as the within-program pass does. Groups are ranked by
*duplicated volume* (statements x members), NOT by how many files they span:
every shop's programs open with a near-identical four-statement
`0000-MAIN-PROCESS`, and ranking on spread buries a sixteen-statement
verbatim copy under that boilerplate. Requires the `redundancy` analyzer;
without it no groups are reported rather than an empty result.

Members, sources and copies (#352): with `--copybook-path`, a paragraph
expanded from a PROCEDURE DIVISION copybook carries its `origin` (copybook
file and line). Members sharing an origin are one source included several
times, not copy-paste, so `--min-clone-members` and the volume ranking count
*distinct sources* (`source_count` on each group; `statements x
source_count`), not members. A copybook paragraph that only ever arrives by
COPY forms no group; one also pasted verbatim into another program does,
with every inclusion still listed as a member.

`--files-from FILE` reads the list from a file, one path per line (`-` for
stdin, `#` comments and blank lines skipped, each line stripped so a
Windows `\r` never becomes part of a path). Not a convenience: a Windows
command line caps at 8191 characters, which a few dozen absolute paths
already exceed, and the COBOL Analyzer extension spawns through
`shell: true` there -- so this is what makes a workspace scan possible at
all on that platform. An unreadable list file exits 1 rather than scanning
nothing, since "no input files" would read as an empty workspace.

Output carries `scan_version` (read it before trusting any other key), an
`analyzers` echo, the `min_clone_statements` in force, a `summary` whose `file_count == scanned + failed` by
construction, `files[]` and `failures[]`. A file that cannot be read or
parsed is a `failures` entry and costs the scan nothing else; an analyzer
that raises on one unit is named in that unit's `failed_analyzers` with its
other reports intact. A file whose copybook expansion failed is still
scanned (unexpanded) and carries `copybook_error` naming why. Every program
unit of a multi-`PROGRAM-ID` file is
reported, each with its nesting `depth` -- the same argument `lint` makes
for linting every unit.

`--source-format auto|fixed|free` (and `--free-form`, and cobol.yml's
`project.source_format`) reach the parse through `ScanOptions.free_form` +
`ScanOptions.preprocess_fixed`, the same pair `_source_format_kwargs()`
hands every single-file subcommand. Before 2026-09-28 only `free_form` was
forwarded, so `--source-format fixed` still auto-detected and a member with
a spaced tag in columns 1-6 scanned as an `UNKNOWN` program with no
paragraphs.

## Business-Rules

```bash
cobol-parser business-rules <file.cbl> [--format json|text] [--include-technical]
    [--program NAME] [--copybook-path DIR] [--profile ...] [-o out]
```

Runs `BusinessRuleExtractor` (see `.okf/analysis.md`) and reports the
program's decision / validation / calculation rules, the level-88 glossary
the rules use, and a rule-to-data lineage table.

| Flag | Meaning |
|------|---------|
| `--format json\|text` | `text` renders `BusinessRuleReport.to_text()` (one IF/THEN/ELSE-shaped block per rule, then the condition-name glossary and caveats); default `json` (`BusinessRuleReport.to_dict()` behind the usual identification header) |
| `--include-technical` | Keep file-status / EOF / SQLCODE / EIBRESP rules, flagged `technical`; by default they are left out and only counted in `summary.technical_rules_excluded` |

Builds its own parser (`_build_business_rules_parser`) only because of those
two flags; otherwise it takes exactly the standard analyzer set (A) plus the
profiling flags. `--profile` only reaches `--format json`
output (a warning says so under `text`), as with `program-flow`. With
`--copybook-path`, JSON locations are origin-stamped by `_emit_report` like
every other analyzer; the text format prints expanded-listing line numbers.

## Lineage / Field-Impact

```bash
cobol-parser lineage <file.cbl> [--field NAME] [--direction forward|backward]
    [--format json|text] [--program NAME] [--copybook-path DIR] [-o out]
cobol-parser field-impact [FIELD] PATH... [--program NAME]
    [--table [SCHEMA.]TABLE.COLUMN | --dataset DSN]
    [--direction forward|backward] [--depth N]
    [--jcl PATH]... [--proc-path DIR] [--bindings FILE.json]
    [--key-relationships] [--format json|text] [--workers N]
    [--copybook-path DIR] [-o out]
```

`lineage` runs `FieldFlowAnalyzer` over one program (see `.okf/analysis.md`,
"Field lineage"): ports, edges, port-to-port summary, key uses. Edges are
origin-stamped from the expansion source map. `--field` instead traces one
data item inside the program (a single-report `LineageGraph`).

`field-impact` parses every COBOL file under PATH (`.cbl/.cob/.cobol`)
through `scan_files(..., analyzers=("lineage",))` -- the parse and analysis
happen in the workers -- and joins the reports in a `LineageGraph`. The
start is FIELD (optionally narrowed with `--program`), `--table` or
`--dataset` (exactly one). Bindings come from `--jcl` (needs jcl-parser
installed; `--proc-path` is a flat PROC folder or a JCLLIB base) and/or
`--bindings` (`{"bindings": [...], "passthroughs": [...]}`, the dict form
of `DatasetBinding` / `Passthrough`). `--depth` caps the joins a path may
cross (a dataset or table hop into another program, or a CALL). JSON output
is `ImpactResult.to_dict()` plus `graph` (statistics, opaque callees,
unjoined DDs, caveats) and `problems` (files that produced no report, JCL
that did not parse or expand). `--format text` groups hits by program with
the path that reached each, then lists `Unjoined:` DDs and `Problems:`.

Exit codes (2026-10-08): `0` when the start was found, hits or not; `1`
when no source produced a lineage report (each problem is printed to stderr
first), when the start (FIELD / `--table` / `--dataset`) matches nothing --
the report is still printed, with `"start_found": false`, and the error
goes to stderr -- or on an argument error. Files that failed while others
parsed stay in `problems` and do not change the exit code.

## Cross-reference, signatures, codebase graph, SQL/CICS lint, diff, JCL

Seven subcommands landed together in PR #212 (`_cmd_xref`,
`_cmd_program_signature`, `_cmd_codebase_graph`, `_cmd_copybook_impact`,
`_cmd_sql_cics_check`, `_cmd_diff`, `_cmd_jcl` in `cli/parse.py`). Three
(`xref`, `program-signature`, `sql-cics-check`) are ordinary single-file
analyzers built through `_build_analyzer_parser(..., profiling=True)` and so
take the standard set (A) plus profiling; four (`diff`, `codebase-graph`,
`copybook-impact`, `jcl`) build their own parser because their arguments do
not fit that shape.

### Ordinary analyzer subcommands

```bash
cobol-parser xref program.cbl
cobol-parser program-signature SUBPGM.cbl [--copybook-path ./copybooks]
cobol-parser sql-cics-check program.cbl
```

* **`xref`** emits `XrefReport.to_dict()` — `entries` (each with `definition`,
  `references`, `reference_count`), `undefined`, `caveats`,
  `duplicate_declarations` and a `summary`. It additionally appends the
  parser's unexpanded-COPY warnings to `caveats`: a member the parser could not
  expand leaves every field it declares looking undeclared, so the warning
  belongs next to the `undefined` list it explains.
* **`program-signature`** reports **every program unit** in the file by default,
  not the outermost — a caller may target a contained program as readily as the
  outer one, and reporting only the outermost would hide the other entry points
  from exactly the consumer that needs them. `--program` still narrows. Output
  is `{"signatures": [...]}`.
* **`sql-cics-check`** emits `SqlCicsReport.to_dict()`. Its lint rule id inside
  `cobol-parser lint` is `sql-cics-check` — the subcommand's own name, per the
  lint rule-id convention.

### `diff` — two positionals

```bash
cobol-parser diff old/PROG.cbl new/PROG.cbl
cobol-parser diff old/PROG.cbl new/PROG.cbl --format text
cobol-parser diff old/PROG.cbl new/PROG.cbl --rename-threshold 1.0
```

| Flag | Meaning |
|------|---------|
| `--format json\|text` | `text` renders `DiffReport.to_text()` (the `+`/`-`/`~` summary); default `json` |
| `--rename-threshold RATIO` | 0.0–1.0 similarity before an unmatched pair is called a rename instead of remove + add (default 0.8; 1.0 accepts only identical bodies). Out-of-range exits 1 |

Takes two positionals rather than the usual single `file`, so it cannot share
`_build_analyzer_parser`. Each side is parsed through the *same* helper the
single-file subcommands use, by swapping `args.file` — so both sides honour
`--source-format`, `--dialect`, `--copybook-path` and `--define` identically.
Parsing the two sides under different options would make the diff meaningless.
JSON output is `{"old_file", "new_file", **report.to_dict()}`.

**No `--program` yet**: contained programs are not compared (they appear as a
caveat instead).

### `codebase-graph` / `copybook-impact` — a tree, not a file

```bash
cobol-parser codebase-graph ./src
cobol-parser codebase-graph ./src --copybook-path ./copybooks
cobol-parser codebase-graph ./src --format mermaid -o graph.mmd
cobol-parser codebase-graph a.cbl b.cbl --format dot
cobol-parser copybook-impact CUSTREC ./src --copybook-path ./copybooks
```

Both take **one directory to walk, or any number of COBOL source files**, plus:

| Flag | Meaning |
|------|---------|
| `--extension EXT` | Source extension to walk for, repeatable (default `.cbl`, `.cob`, `.cobol`); accepted **with or without** the leading dot (`--extension cbl` and `--extension .cbl` both work); `cobol.yml` `project.extensions` fills it |
| `--workers N` | Worker processes for the batch parse (default: chosen by input size) |
| `--copybook-path DIR` | Where COPY members are resolved from, as elsewhere |
| `--format json\|dot\|mermaid` | `codebase-graph` only — `to_dot()` / `to_mermaid()` reuse the flowchart renderer's conventions |

`copybook-impact` takes the member name first (bare name, file name or path),
then the paths, and emits `ImpactReport.to_dict()`: `direct_programs`,
`transitive_programs`, the COPY `chains` that reach each one, the `fields` the
member contributes, `unresolved`, and a `summary`.

### `jcl` — the one non-COBOL subcommand

```bash
cobol-parser jcl JOB.jcl
cobol-parser jcl JOB.jcl --dd-map
cobol-parser jcl JOB.jcl --bindings
cobol-parser jcl JOB.jcl --program INVUPDT
cobol-parser jcl JOB.jcl --proc-path proclib/ --bindings
cobol-parser jcl JOB.jcl --strict
```

| Flag | Meaning |
|------|---------|
| `--dd-map` | Only the `ddname -> datasets` mapping, which is what a COBOL `SELECT ... ASSIGN TO ddname` resolves through |
| `--bindings` | One row per DD binding (ddname, dataset, step, job, DISP, RECFM, LRECL) instead of the job structure |
| `--program NAME` | Only the steps that run this program (also filters `--bindings` to those steps) |
| `--proc-path DIR` | Directory of cataloged procedures and INCLUDE members (one member per file, named after it; repeatable, searched in order). Without it only in-stream procedures expand, and every other `EXEC proc` is reported in `unresolved` |
| `--strict` | **Exit 3** when any card could not be parsed — a CI gate, kept deliberately distinct from exit 1, which still means the run itself failed |

It reads a language other than COBOL, so it shares none of the COBOL parse
flags: no `--dialect`, no `--source-format`, no `--copybook-path`. `--compact`
and `-o` work as everywhere else. It needs the `jcl-parser` package
(`pip install 'cobol-parser[jcl]'`), which does the reading; without it,
`jcl` exits 1 with that install hint as a one-line `error:` (no traceback).
See [jcl.md](jcl.md).

# IO coverage tools (`cobolparser/cli/coverage.py`)

A separate argparse program — **not** a `cobol-parser` subcommand and not a
console script; run it as `python -m cobolparser.cli.coverage <cmd>`. It
wraps `analysis.io_coverage_reporter.IOCoverageReporter` (see
[analysis.md](analysis.md)) for the IO statement coverage artifact.

| Command | Flags (default) |
|---|---|
| `status` | `--artifact` (`io-coverage.json`), `--verb`, `--qualifier`, `--format {table,json}` (table) |
| `generate` | `--pytest-results FILE` (required), `--output` (`io-coverage.json`), `--catalog CSV`, `--schema JSON` |
| `validate` | `--artifact FILE` (required) |
| `render` | `--input FILE` (required), `--output` (stdout), `--format {markdown,csv,summary}` (markdown) |

`main()` returns the command's int status (no command: help, exit 1).
`status` falls back to `./io-coverage.json` only when the requested artifact
is missing *and* is not already that path (printing a `Note:`), so a stale
default artifact is never served silently. A malformed or non-object
artifact (`status`) or pytest-results file (`generate`) is a clean error with
exit 1, not a traceback (audits M10, 2026-07-08). Tests:
`tests/unit/cli/test_coverage_cli.py`, `test_coverage_cli_extra.py`.

# See Also

* [analysis.md](analysis.md) — the underlying analyzers, including
  `BoundaryInventoryAnalyzer` (`gen-fixtures`, Phase 2) and
  `ConstraintExtractor`/`domains.solve()` (Phase 4, feeds `--scenarios`)
* [parser.md](parser.md) — `parse_cobol` used by most subcommands
* [batch.md](batch.md) — `scan_files` behind `scan`, and why it is not `batch.py`
* [generators.md](generators.md) — `ProgramLayoutIndex` / `ProgramFixtureGenerator`
  / `FixtureBundle` / `ScenarioPlanner` (`gen-fixtures`, Phases 1, 3, 5-6)
* [jcl.md](jcl.md) — the jcl-parser adapter behind `jcl`: procedure
  libraries, several jobs per deck, and the `ddname -> dataset` binding
* [`docs/fixture-bundle-schema.md`](../docs/fixture-bundle-schema.md) — the
  full `FixtureBundle` JSON shape `gen-fixtures --format json` produces

# Recent changes

## 2026-10-08

* `jcl --dd-map --program NAME` now honours `--program` (it listed every
  step's DDs); the filter is the same step set `--bindings --program` uses.
* `cobolparser/cli/parse.py` has a `__main__` guard, so `python -m
  cobolparser.cli.parse ...` runs the CLI (it was a silent no-op; only the
  `cobol-parser` console script worked).

## 2026-10-15

* `jcl` without the `[jcl]` extra prints the install hint as a one-line
  `error:` and exits 1, instead of an `ImportError` traceback (#326).
* `gen-fixtures --rows -1` / `--max-occurs 0` / `data.rows: -5` in
  `cobol.yml` print a one-line `error:` and exit 1 instead of a
  `ValueError` traceback (#327).
* `--profile-output` (and a non-default `--profile-top-n`) now imply
  `--profile` on every subcommand that takes them (they were silently
  ignored without it), and a single-file `--profile-output` naming a
  directory -- or a batch one naming a regular file -- is a one-line
  `error:` instead of a traceback (#328).
