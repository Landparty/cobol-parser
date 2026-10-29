---
type: Module
title: CLI
description: cobol-parser command-line interface — every subcommand with their flags and defaults, exit codes, output identification, shared flags, and the cobol.yml project config (cobolparser/cli/, cobolparser/config/, __main__.py).
tags: [cli, command-line, subcommands, output-identification, cobol-yml, project-config]
timestamp: 2026-10-15T00:00:00Z
---

# CLI

The `cobol-parser` command: <!-- okf:gen cli-subcommand-count -->41<!-- /okf:gen --> subcommands that parse, tokenize, preprocess,
expand, analyze, generate/decode/compare record data for, and graph COBOL
(plus one for JCL and one for the LE catalogue), all built with `argparse` in
`cobolparser/cli/parse.py`, and the `cobol.yml` project config every
subcommand reads. Start with the [subcommand reference](#subcommand-reference)
table (every flag and default), then [Exit codes](#exit-codes) and
[Shared flags](#shared-flags); per-subcommand behaviour follows by family.

## Contents

* [Entry points and `main()`](#entry-points-and-main) · [Subcommand reference](#subcommand-reference) · [Exit codes](#exit-codes) · [Output identification](#output-identification)
* [Project config file (`cobol.yml`)](#project-config-file-cobolyml) — discovery, precedence, the YAML subset, `config`
* [Shared flags](#shared-flags) — `--error-recovery`, `--copybook-path`/`--define`, `--source-format`/`--debug-lines`, `--program`, origin stamping, profiling
* [Parsing subcommands](#parsing-subcommands) · [Record data subcommands](#record-data-subcommands) · [gen-fixtures](#gen-fixtures)
* [Single-file analyzers](#single-file-analyzers) · [lint](#lint) · [scan](#scan) · [lineage / field-impact](#lineage--field-impact)
* [diff, codebase-graph, copybook-impact, jcl, le-info](#diff-codebase-graph-copybook-impact-jcl-le-info) · [IO coverage tools](#io-coverage-tools-cobolparserclicoveragepy) · [See also](#see-also)

## Entry points and `main()`

All entry points reach `cobolparser.cli.parse.main`: the `cobol-parser`
console script (`[project.scripts]` → `cobolparser.cli:main`, which
`cli/__init__.py` re-exports), `python -m cobolparser` (`__main__.py`), and
`python -m cobolparser.cli.parse` (a `__main__` guard). `python -m
cobolparser.cli.coverage` is a **separate** program (see
[IO coverage tools](#io-coverage-tools-cobolparserclicoveragepy)).

**Source:** `cli/parse.py` (per subcommand a `_build_<name>_parser()` and a
`_cmd_<name>()`, assembled in `_build_parser()`), `cli/_project_config.py`
(the `cobol.yml` → argv merge), `cli/coverage.py`, `cobolparser/config/`
(`project.py` schema + discovery, `_yaml.py` reader).

`cobol-parser --help` lists subcommands; `<name> --help` shows flags,
defaults and runnable examples. **Adding a single-file analyzer:** call `_build_analyzer_parser(subparsers,
name, help, func, profiling=..., examples=...)` in `_build_parser()` (the
standard flag set **A**; `examples` is required and becomes the `--help`
epilog — hand-built parsers set `epilog=` themselves) and emit through
`_emit_report(..., ast=ast)` so the output is identified and origin-stamped.

**`main()`:**

* `--version` prints `cobol-parser <version>`; `--config FILE` / `--no-config`
  are global and may sit on either side of the subcommand.
* **Legacy spelling**: if the first non-flag argument is not in
  `_SUBCOMMANDS`, `parse` is prepended (`cobol-parser prog.cbl` is `parse
  prog.cbl`). An empty argv also becomes `parse` (exit 2, "file required").
* A closed stdout (`... | head`) exits **141** quietly, no `BrokenPipeError`.
* CLI errors go through `_fail()`: one `error: ...` line on stderr, exit 1,
  never a traceback.

**Shared flag helpers** (each subcommand composes a subset):
`_add_compact_arg`, `_add_source_format_args` (`--source-format` |
`--free-form`, plus `--debug-lines`), `_add_debug_lines_arg`,
`_add_dialect_arg`, `_add_error_recovery_arg`, `_add_copybook_args`,
`_add_program_arg`, `_add_define_args`, `_add_output_arg` (`-o/--output`),
`_add_profiling_args`, `_add_record_file_args` (decode/compare),
`_add_min_clone_statements_arg` (redundancy/scan), `_add_direction_args`
(lineage/field-impact).

## Subcommand reference

Verified against `python -m cobolparser <cmd> --help` on 2026-10-15. Order is
`_build_parser()`'s. Flag-set legend for the last column:

* **A** — the standard analyzer set from `_build_analyzer_parser()`:
  `--compact`, `--source-format {auto,fixed,free}` (default `auto`) |
  `--free-form`, `--debug-lines`/`--no-debug-lines`, `--dialect {ibm-enterprise}`
  (default), `--error-recovery {fail-fast,collect-all}` (default `collect-all`),
  `--copybook-path DIR`..., `--program NAME` (default: the outermost unit),
  `--define SYMBOL[=VALUE]`..., `--encoding ENC` (default: detected, #522),
  `-o/--output FILE`.
* **+prof** — also `--profile`, `--profile-top-n N` (default 20; implies
  `--profile`), `--profile-output PATH` (implies `--profile`).
* **dl** — `--debug-lines`/`--no-debug-lines` without `--source-format`.

| Subcommand | Positionals | Own flags (default) | Shared flags | Output |
|---|---|---|---|---|
| `parse` | `file [path]` | `--errors`, `--stats`, `--find-type NODE_TYPE` | A without `--program`; +prof | AST JSON; exit 2 on a recovered-but-errored parse |
| `batch` | `[files ...]` | `--glob PATTERN`..., `--workers N` (CPU count), `--encoding` (detected), `--errors`, `--stats` | `--compact`, `--dialect`, `--error-recovery`, `-o`, dl; +prof | JSON list, one entry per file |
| `tokenize` | `file` | — | `--compact`, `--source-format`/`--free-form`, dl, `--dialect`, `--encoding`, `-o` | `{source_file, tokens}` |
| `preprocess` | `file` | `--strip-directives` | `--source-format`/`--free-form`, dl, `--define`, `--encoding` (no `--compact`, no `-o`) | free-form source text |
| `expand` | `file` | `--keep-comments`, `--source-map`, `--max-depth N` (100) | `--copybook-path`, `--compact`, `--define`, `--encoding`, `-o`, dl | expansion JSON |
| `gen-data` | `file` (copybook or program) | `--rows/-n` (10), `--seed`, `--record`, `--list-records`, `--describe`, `--header-style {short,path}`, `--include-filler`, `--include-redefines`, `--no-expand-occurs`, `--max-occurs`, `--no-semantic`, `--ignore-values`, `--unique FIELD`, `--blank-rate`, `--format {csv,json,record,hex}` (csv), `--charset` (ascii), `--endian` (auto), `--record-format` (fixed), `--record-varying MIN:MAX`, `--record-separator` (none) | `--copybook-path`, `--compact`, `--encoding`, `-o` | CSV / JSON / record bytes / hex |
| `decode` | `[file]` | `--copybook FILE` (required), `--record`, `--view`, `--list-views`, `--format {csv,json,hex}` (csv), `--charset`, `--endian`, `--record-format`, `--record-length N`, `--record-separator`, `--max-records N` (all), `--skip N` (0), `--strict` | `--copybook-path`, `--compact`, `-o` | CSV / JSON / hex |
| `compare` | `expected actual` | `--copybook FILE` (required), `--record`, `--view`, `--key FIELD`..., `--ignore FIELD`..., `--compare-bytes`, `--max-differences N`, `--format {text,json}` (text), the decode file-format flags (`--charset`, `--endian`, `--record-format`, `--record-length N`, `--record-separator`) | `--copybook-path`, `--compact`, `-o` | report; exit 0/1/2 like `cmp` |
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
| `scan` | `[files ...]` | `--glob`..., `--files-from FILE`, `--analyzer NAME`... (`health,redundancy`), `--clones`, `--min-clone-members N` (2), `--min-clone-statements N` (3), `--workers N` (CPU count), `--encoding` (detected), `--cache-dir DIR` (off), `--format {json,sarif}` (json; sarif runs `lint`) | A without `--program` | `scan_version` report, or a SARIF log of every file's lint findings |
| `lint` | `file` | `--rule RULE`... (all), `--min-severity {error,warning,info}` (info), `--fail-on {error,warning,info,never}` (never), `--format {json,text,sarif}` (json) | A (`--program` default: every unit); +prof | findings (or a SARIF 2.1.0 log); exit 3 on `--fail-on` |
| `data-items` | `file` | — | A; +prof | `compute_program_data_items()` |
| `program-signature` | `file` | — | A (`--program` default: every unit); +prof | `{"signatures": [...]}` |
| `xref` | `file` | — | A; +prof | `XrefReport` |
| `diff` | `old new` | `--format {json,text}` (json), `--rename-threshold RATIO` (0.8) | A without `--program` | `DiffReport` |
| `codebase-graph` | `PATH ...` | `--format {json,dot,mermaid}` (json), `--extension EXT`... (`.cbl .cob .cobol`), `--workers N` (by size) | `--compact`, `--copybook-path`, `-o`, dl | graph |
| `copybook-impact` | `member PATH ...` | `--extension`..., `--workers` | `--compact`, `--copybook-path`, `-o`, dl | `ImpactReport` |
| `call-check` | `PATH ...` | `--extension`..., `--workers`, `--min-severity {error,warning,info}` (info), `--fail-on {error,warning,info,never}` (never), `--format {json,text,sarif}` (json) | `--compact`, `--copybook-path`, `-o`, dl | `CallInterfaceReport` (or SARIF); exit 3 on `--fail-on` (judged on the findings `--min-severity` keeps, as `lint`), 2 when a file is missing or failed to parse |
| `sql-cics-check` | `file` | — | A; +prof | `SqlCicsReport` |
| `business-rules` | `file` | `--format {json,text}` (json), `--include-technical` | A; +prof | `BusinessRuleReport` |
| `lineage` | `file` | `--field NAME`, `--direction {forward,backward}` (forward), `--format {json,text}` (json) | A (no profiling) | `FieldFlowReport` |
| `field-impact` | `[FIELD] PATH ...` | `--program NAME` (every program with that field), `--table T.C`, `--dataset DSN`, `--direction` (forward), `--depth N` (unlimited), `--jcl PATH`..., `--proc-path DIR`... (from `project.proc_path`), `--bindings FILE.json`, `--key-relationships`, `--workers N`, `--format {json,text}` (json) | `--compact`, `--copybook-path`, `--source-format`, `--define`, `-o`, dl | `ImpactResult`; exit 1 when the start matches nothing |
| `widen-check` | `FIELD PATH ...` | `--to PIC` (required), `--usage USAGE` (kept), `--program NAME`, `--depth N`, `--jcl PATH`..., `--proc-path DIR`..., `--bindings FILE.json`, `--min-severity {error,warning,info}` (info), `--fail-on {error,warning,info,never}` (never), `--workers N`, `--format {json,text}` (json) | `--compact`, `--copybook-path`, `--source-format`, `--define`, `-o`, dl | `WideningReport`; exit 1 when nothing produced a report, the field matches nothing or nothing could be checked; exit 3 on `--fail-on` (judged on the findings `--min-severity` keeps) |
| `jcl` | `file` | `--dd-map`, `--bindings`, `--program NAME`, `--proc-path DIR`..., `--strict` | `--compact`, `-o` | job JSON; needs `[jcl]` extra; exit 3 on `--strict` |
| `le-info` | `[name ...]` | `--kind {service,function,all}` (all) | `--compact`, `-o` | LE / intrinsic signature catalogue |
| `config` | — | `--json` | `--compact`, `-o` | effective `cobol.yml` |
| `mcp` | — | `--root DIR` (`.`), `--cache-size N` (32), `--tools SPEC` (`auto`), `--max-answer-bytes N` (24000), `--workers N` (CPUs, at most 8), `--cache-dir DIR` (`default_cache_dir()`), `--no-disk-cache`, `--no-warm-up` | — | MCP server on stdio until the client disconnects; needs `[mcp]` extra; `cobol.yml` read from `--root` itself, never a parent; outside copybook dirs serve members only, dangerous ones refused (see [mcp.md](mcp.md#workspace)) |

Subcommands that take none of the COBOL parse flags (`--source-format`,
`--dialect`, `--debug-lines`, `--define`, `--error-recovery`): `gen-data`,
`decode`, `compare` (they read a record layout only), `jcl`, `le-info`, `config`,
`mcp` (it reads `cobol.yml` instead).

## Exit codes

| Code | Meaning |
|------|---------|
| `0` | Ran to completion; findings alone never change it. Analyzer subcommands exit 0 on a partial parse too, printing `warning: <file> parsed with N error(s); analysis may be incomplete` to stderr (`_parse_result_or_fail`) |
| `1` | The CLI failed (`_fail()`): unreadable file, `ast is None`, unwritable output, a `cobol.yml` error, a missing extra, an invalid option value |
| `2` | Argparse rejected the arguments; `parse` (incl. `--find-type`) got a recovered-but-errored parse — JSON still printed, summary on stderr (`_exit_if_partial_parse`; with `--errors` it says the errors are in the JSON instead of the re-run hint, #745); `batch` had a file with a `read_error` or `success=false`; `scan` had a file in `failures`, and `codebase-graph` / `copybook-impact` a file in the graph's `errors` (missing, unreadable or parsed with errors) -- output still written, a `warning:` on stderr, plus `error: no such file or directory: X` per missing path (`_exit_on_graph_errors`, #325, owner's option (a): any failed file, as `batch`); `gen-fixtures --strict` found unresolved items; `call-check` had a missing file (before any parse) or a file that failed to parse (after the report) |
| `3` | `lint --fail-on` / `call-check --fail-on` / `widen-check --fail-on` threshold hit; `jcl --strict` hit an unparseable card |
| `141` | stdout closed (128 + SIGPIPE) |

Exit 2 on a partial parse lets scripts gating on `$?` tell a partial parse
from success. Exit 3 is deliberately distinct from 1/2, so a CI gate never
confuses "this program has problems" with "the tool never ran". `compare`
follows `cmp` instead (0 equal / 1 different / 2 could not compare);
`field-impact` exits 1 when nothing produced a report or the start matches
nothing.

## Output identification

Every output identifies its source (`_identification()` in `cli/parse.py`;
pinned by `tests/unit/cli/test_output_identification.py`):

* **JSON documents** start with `"source_file"` (the path as given). Parsing
  subcommands add `"program_id"` (or `null`) as the second key and, ONLY when
  the file holds more than one unit, `"program_units"` listing every unit in
  source order, so a report can say what it did not cover. Analyzer reports
  get these via `_emit_report(..., ast=ast)`.
* **`parse`**: full-AST output gets `"source_file"` spliced in (the AST dict
  carries `program_name`); `--errors`/`--stats` wrap as `{"source_file",
  "program_id", "ast", ...}`; a dotted path emits `{..., "path", "result"}`;
  `--find-type` emits `{..., "node_type", "matches"}`.
* **`tokenize`** `{"source_file", "tokens"}`; **`expand`** prefixed with
  `"source_file"` (no `program_id`, nothing is parsed); **`batch`** a list
  whose entries carry `"path"` and, given an AST, `"program_id"`.
* **Text**: Mermaid starts with `%% Program: <name>`; DOT names the digraph
  after the program. `preprocess` output is deliberately unidentified (it is
  source meant to be fed onward).
* **`gen-fixtures`** JSON is `{"source_file", "bundle_version",
  "program_name", ...}` (`program_name` inside the bundle, no `program_id`);
  `csv-dir`'s `MANIFEST.json` carries the same. **`le-info`** has no header
  (there is no source).

## Project config file (`cobol.yml`)

The **universal** project config the tool family reads — this CLI,
`mockymock`, and the COBOL Analyzer extension — so a shop states copybook
paths, layout, dialect and record encoding once. User-facing reference:
`docs/project-config.md`. Tests: `tests/unit/test_config_yaml.py`,
`tests/unit/test_project_config.py`, `tests/unit/cli/test_project_config_cli.py`.

**Public API** (`from cobolparser.config import ...`):
`load_project_config(start_dir=None, path=None) -> ProjectConfig` (all-default
with `source=None` when nothing is found; `path` loads exactly that file, as
`--config` and the VS Code extension do), `find_config_file(start_dir)`,
`build_config(document, source)`, `resolve(cli_value, config_value,
hardcoded_default)` (the precedence helper), `parse_yaml` / `YamlError`,
`ConfigError`, `CONFIG_FILE_NAMES = ("cobol.yml", "cobol.yaml")`,
`SCHEMA_VERSION = 1`.

**Schema** (frozen dataclasses; a field not stated is `None`/empty, so "not
stated" stays distinct from "equals the default"):

| Section | Keys → `ProjectConfig` field |
|---|---|
| top level | `version`, `project`, `data`, `lint`, `mockymock`, `analyzer` (anything else is an error) |
| `project:` | `copybook_path`, `callee_path`, `proc_path` (lists, resolved against the file's directory), `source_format` (`auto\|fixed\|free`), `debug_lines` (bool), `dialect` (`ibm-enterprise`), `error_recovery` (`collect-all\|fail-fast`), `seed`, `extensions`, `define` (normalized to `SYMBOL=VALUE`) |
| `data:` → `DataDefaults` | `charset`, `endian`, `record_format`, `record_separator`, `rows` |
| `lint:` → `LintDefaults` | `rules`, `min_severity`, `fail_on` |
| `mockymock:` / `analyzer:` | validated only as mappings, carried verbatim on `ProjectConfig.tools`; `tool_section(name)` returns the mapping or `{}` |

* **Discovery** — `cobol.yml` then `cobol.yaml` in the cwd and each parent,
  first match wins, at most 32 levels. Finding nothing is normal. Paths inside
  resolve against **the file's own directory**, so a run from a subdirectory
  searches the same copybook libraries as one from the root.
* **Precedence** — explicit CLI flag > config file > built-in default, merged
  in one place (`_project_config.apply_project_config`), so every `_cmd_*`
  keeps reading `args.copybook_path` etc. unchanged.
* **`--config FILE` / `--no-config`** are stripped from argv by
  `extract_config_flags()` *before* argparse and before the legacy "prepend
  parse" rewrite — so they work on either side of the subcommand, and the
  rewrite cannot take `--config`'s argument for the source file (they are on
  the top-level parser for `--help` only). Only the exact spellings are
  stripped, and any `--X` / `--X=...` where X is a proper prefix of `config`
  or `no-config` (`--no-conf`, `--no`, `--conf=FILE`, `--co`) is rejected
  (exit 1, `ConfigError`) on either side (#323): argparse's prefix matching
  would otherwise swallow it, or a subcommand would read `--no` as one of its
  `--no-...` flags, and the discovered `cobol.yml` would silently stay in
  force. Done on raw argv rather than `allow_abbrev=False` everywhere, so
  abbreviations that cannot mean these two still work.
* **Typed vs defaulted flags** — most flags have a non-`None` default, so `is
  None` cannot tell "user passed it". `provided_dests()` re-parses argv against
  a throwaway parser whose optional defaults are a sentinel (append actions get
  `None`: argparse's append copies-and-appends to the default, and a non-list
  sentinel would raise). Runs only when a config file was found.
* **Bound dests** — `copybook_path`, `callee_path`, `proc_path`, `source_format`,
  `debug_lines`, `dialect`, `error_recovery`, `seed`, `extensions`, `define`,
  `charset`, `endian`, `record_format`, `record_separator`, `rows`, `rules`,
  `min_severity`, `fail_on`. `extensions`/`rules` are argparse *dests*, not
  the `--extension`/`--rule` spellings — getting that wrong silently binds
  nothing. A subcommand without the dest skips the key; for the keys that
  change *which program* is parsed (`project.define`, a non-`auto`
  `source_format`, a true `debug_lines`) `unapplied_parse_settings()` names
  each one it skipped and `main()` prints `warning: <file> sets
  project.define, but `batch` has no flag for it and parses without it` on
  stderr (#324). It returns nothing for a subcommand with none of `define` /
  `source_format` / `debug_lines` / `copybook_path` (`config`, `le-info`,
  `jcl`, `mcp`), and nothing for `dialect`, which has one value. For
  `gen-data` / `decode` / `compare` / `expand` (`_SOURCE_FORMAT_NOT_WARNED`)
  it leaves out `source_format`, which auto-detection settles for a
  copybook; their `define` warning stays. Every
  subcommand that parses COBOL has `--debug-lines`; `batch`, `gen-fixtures`,
  `codebase-graph`, `copybook-impact`, `call-check`, `gen-data`, `decode`, `compare`,
  `tokenize` and `expand` still lack `--define` and/or `--source-format`.
* **`--free-form`** passed by the user suppresses filling `source_format`:
  `_source_format_kwargs()` reads `--source-format` first, so a config value
  would override the layout stated on the command line.
* **Fail-closed** — a malformed file, unknown key, out-of-range enum value or
  missing `--config` target is `ConfigError` → exit 1 naming the file (and,
  for YAML syntax, the line); exit 2 under `compare` (`main()` routes it via
  `_config_fail()`). Never a silent fallback to defaults.

**The YAML subset** (`_yaml.py`, stdlib only — the package has no runtime
dependencies):

* Supported: nested mappings; block/flow sequences (incl. the indentless form,
  a block sequence at its key's own column); flow mappings; quoted/plain
  scalars (`''` in single quotes; YAML 1.2's full double-quoted escape set,
  `\xXX`/`\uXXXX`/`\UXXXXXXXX` with exactly that many hex digits, and
  `\e`/`\N`/`\_`/`\L`/`\P`); `#` comments; one optional leading `---`; an
  optional trailing `...` (anything significant after it is a second document,
  rejected); a leading UTF-8 BOM (ignored).
* **Rejected with a line number**: anchors, aliases, tags, block scalars,
  merge keys, multiple documents, tabs in indentation, duplicate keys.
  Deliberate YAML 1.2-core departures from 1.1: `yes`/`no`/`on`/`off` stay
  strings; a duplicate key is an error, not last-one-wins.
* **Comment stripping tracks quote state, and a backslash escape consumes the
  character after it** (`_strip_comment`, run before the parser):
  `msg: "a \" # b"` keeps its whole value. Skipping one character instead of
  two after `\` makes a later `#` look unquoted after an odd number of escaped
  quotes (pinned by `tests/regression/test_audit_2026_09_16.py`).
* **A quote only opens a quoted span at the start of a scalar** (line start,
  or after `:`, `- `, `[`, `{`, `,`) — `_opens_quote()`, shared by
  `_strip_comment`, `_split_key` and `_is_mapping_entry`. Mid-word it is
  plain: `owner: Sam's shop  # note` drops the comment, `don't: 1` parses.
* **Stricter where YAML is stricter**: numbers resolve only for YAML 1.2 core
  spellings (`1_000`, `٣`, `0x1F` stay strings; Python's `int()` would
  take the first two); a plain value holding `: ` (`key: a: b`) is rejected —
  quote it; `- - x` is a nested sequence; line numbers count `\n`/`\r\n`/`\r`
  records only (`split_source_lines`), never form feed / NEL / U+2028.
* **A sequence entry where a scalar belongs is rejected**
  (`_is_sequence_indicator()`): `copybook_path: - copybooks` (and `[- x]`,
  `{k: - x}`, `key: -`) is an error, as in YAML, never the string
  `"- copybooks"` (a list silently turned into one directory name). `-x` /
  `-1` are plain scalars.

### `config`

Reports which `cobol.yml` is in effect and every setting it supplies;
settings the file does not mention are **omitted**, so what is printed is
exactly what the file changes. No file anywhere: says so, suggests creating
one, exit 0. `--json` emits `{"config_file", "version", "project", "data",
"lint", "tools"}` (`config_file` `null` when none), plus
`missing_directories` only when `ProjectConfig.missing_directories()` names
a path entry that is not a directory; the text form marks those entries
`(not an existing directory)`. Honours `--config` / `--no-config`.

Path entries (`_path_list`) get `os.path.expanduser` + `expandvars` before
the join onto the file's directory: as written, `~/cpy` became
`<cfgdir>/~/cpy` and silently found nothing (#550). `main()` warns on stderr
once per missing entry for a dest the subcommand reads and the user did not
pass explicitly.

## Shared flags

### `--error-recovery`

Default `collect-all` (`ErrorRecoveryMode` via `_add_error_recovery_arg()` /
`_get_error_recovery()`; `cobol.yml` `error_recovery`). Taken by every
`_build_analyzer_parser` subcommand and by `batch`, `scan`, `lint`,
`unused-variables`, `program-flow`, `redundancy`, `business-rules`,
`lineage`, `diff`; not by `tokenize`, `preprocess`, `expand`, `gen-data`,
`decode`, `compare`, `gen-fixtures`, `codebase-graph`, `copybook-impact`,
`call-check`, `field-impact`, `jcl`, `le-info`, `config`.

### `--copybook-path` / `--define`

`parse` and every analyzer go through `_do_parse()`. With copybook paths:
`parse_cobol_with_expansion(..., process_conditionals=True,
defined_symbols=...)`, so `--define` reaches `>>IF`s inside members; a
missing or circular copybook is `error: Copybook expansion failed ...`
(exit 1). Without: `--define` runs `preprocess_conditional_compilation()` on
the raw source (keeping `>>SOURCE FORMAT` directives for the normalizer),
then `parse_cobol`. Conditional-compilation diagnostics (unknown `>>IF`
conditions, stray `>>ELSE`/`>>END-IF`, malformed `>>DEFINE`, unclosed `>>IF`)
are printed as `warning:` lines on stderr — by `preprocess`, and by `parse` /
analyzers given `--define` without `--copybook-path` — so deleted guarded
blocks are never silent. `scan` and `field-impact` take `--define` too
(`ScanOptions.defined_symbols`, same two paths inside the worker; the
directive warnings land in each unit's parse warnings) (#324). With `--copybook-path` the expander runs that pass
and `expand` reports them in `statistics.warnings`.

### Source layout (`--source-format`)

`--source-format {auto,fixed,free}` (default `auto`; exclusive with
`--free-form`; `cobol.yml` `project.source_format`) is taken by `parse`,
`tokenize`, `preprocess`, every `_build_analyzer_parser` subcommand, and the
hand-built `unused-variables`, `program-flow`, `redundancy`, `scan`, `lint`,
`business-rules`, `lineage`, `diff`, `field-impact`. `batch`, `expand`,
`gen-fixtures`, `codebase-graph` and `copybook-impact` always auto-detect
(their APIs expose no layout override; a config value is warned about, see
Bound dests).

| Value | Behaviour |
|-------|-----------|
| `auto` | Detect via `detect_fixed_format` (`preprocess/source_format.py`) (see [parser.md](parser.md)) |
| `fixed` | Always normalise — strips columns 1-6 whatever they hold |
| `free`  | Never normalise |

Reach for `fixed` when a layout defeats auto-detection, e.g. a sequence area
holding a tag with an internal space (a solid tag like `SAPR24` or `28486` is
detected). `--free-form` is the legacy, *weaker* hint: auto-detection may
still normalise source it classifies as fixed (scripts that always passed it
against fixed-format members rely on that). It is **not**
`--source-format=free`, which hard-disables normalisation.

`--debug-lines` / `--no-debug-lines` (`BooleanOptionalAction`, default off;
`cobol.yml` `project.debug_lines`, strictly a boolean, which
`--no-debug-lines` overrides) compiles fixed-format `D` lines as code instead
of dropping them (#334; see [preprocessing.md](preprocessing.md)).
`_source_format_kwargs()` adds `debug_lines=True` only when set; `scan`
forwards it as `ScanOptions.debug_lines`; `preprocess` passes it to
`normalize_fixed_format`. Subcommands without `--source-format` that parse
COBOL take it via `_add_debug_lines_arg()`; `gen-data` / `decode` /
`compare` / `jcl` / `le-info` / `config` have none (pinned by
`test_only_record_layout_subcommands_lack_debug_lines`).

### Selecting a program unit (`--program`)

A file can hold several `PROGRAM-ID`s (stacked or nested), and every analyzer
is program-scoped, so a report is about ONE unit — by default the outermost.
A contained program would otherwise come back "clean" because it was never
examined:

* `--program NAME` (every `_build_analyzer_parser` subcommand, plus
  `unused-variables`, `program-flow`, `redundancy`, `lint`, `business-rules`,
  `lineage`) selects a unit case-insensitively via
  `CobolProgram.find_program_unit`; an unknown name fails listing the units
  there, never a report about a different program.
* A multi-unit file's reports carry `"program_units"` in the header; a
  single-program file's output is unchanged, key for key.
* `lint` and `program-signature` cover every unit unless `--program` narrows
  it. `scan` reports every unit of every file; `diff` has no `--program`
  (contained programs appear as a caveat). `field-impact --program` and `jcl
  --program` mean something else (the PROGRAM-ID owning FIELD; the steps
  running a program).

### Origin stamping (with `--copybook-path`)

With expansion, analyzer locations count lines of the *expanded* text.
`_parse_result_or_fail` keeps `ParseResult.expansion_source_map` on
`args._expansion_source_map`, and `_emit_report` stamps every analyzer
report (`analysis.lint.stamp_report_origins`): each `location` gains a
sibling `"origin": {"file", "line"}` naming the program or copybook the line
came from; `location` is unchanged. Locations under other keys get a sibling
of their own name (#367; `analysis.lint._ORIGIN_KEYS`): xref's `definition` →
`definition_origin`, program-flow's `exit_statement_location` →
`exit_statement_origin`. No map, no `origin` — except `lint`, which always
stamps. An existing `origin` is never overwritten. `gen-fixtures` is not
stamped (bare `line` keys under `bundle_version`); `business-rules --format
text` prints expanded-listing line numbers.

### Profiling flags

`--profile` / `--profile-top-n` / `--profile-output PATH` wrap the parse in a
`ProfilerContext` (see [parser.md](parser.md)) and embed timing/memory
metrics, or write a binary `.prof`. `--profile-output`, or a non-default
`--profile-top-n`, implies `--profile` (#328). A single-file
`--profile-output` naming an existing directory is an `error:` (exit 1)
before the parse; in `batch` it must be a directory (one `.prof` per file)
and a `.prof` name or existing file is an `error:`. Metrics embed only in
JSON, so `program-flow --format mermaid|dot` and `business-rules --format
text` warn on stderr rather than silently drop them.

**Nested profilers** (#274): a `ProfilerContext` entered while another
profiler is active (an outer `ProfilerContext`, a bare `cProfile`, anything on
`sys.setprofile` or `sys.monitoring`'s PROFILER_ID) skips cProfile — its
result has `function_profile_available: false`, empty `top_functions`, no
`.prof`, a `caveats` entry — while wall-clock, CPU and memory are still
measured. A second cProfile would silently replace the outer one on 3.11 and
raise on 3.12+. An inner context never stops a tracemalloc session it did not
start.

## Parsing subcommands

* **`parse`** prints the AST JSON; `json-path` (dotted) extracts a subtree,
  `--errors` shows errors only, `--stats` appends `ParseStatistics`,
  `--find-type T` lists nodes of a type (`ast.find_all_by_type()`). Exit 2 on
  a recovered-but-errored parse, `--find-type` included.
* **Source encoding** (#522): every subcommand that reads one COBOL source
  through `_read_source` (`parse`, `tokenize`, `preprocess`, `expand`,
  `gen-data`, `lint`, every analyzer subcommand) takes `--encoding ENC`,
  default detected as for a copybook (`read_program_source`): a cp1252 /
  Latin-1 program is read, not refused as "not valid UTF-8". A lossy decode
  prints `warning: Lossy decode ...` on stderr; an unknown codec exits 1.
  `gen-fixtures` and `jcl` still read their own way. `cobol.yml` has no
  source-encoding key.
* **`batch`** parses in parallel (`ProcessPoolExecutor`); files positional
  and/or via repeatable `--glob 'src/**/*.cbl'`; `--workers` (CPU count),
  `--encoding` (detected); one JSON result per file, `--errors` / `--stats`
  per file. Exit 2 when any file has a `read_error` or `success=false`.
* **`tokenize`** prints `{"source_file", "tokens": [{"type", "value", "line",
  "column"}]}` (`type` is the `TokenType` name) through
  `lexer._tokenize_source`, the same normalize-then-lex path as `parse`, with
  fixed-format comments kept as `COMMENT` tokens; lexer errors are ignored.

### `preprocess`

Prints the normalised, conditionally compiled free-form text on stdout.

* `--strip-directives` runs `strip_compiler_directives()` (PROCESS/CBL cards)
  first.
* Under `auto`, normalisation runs only when `detect_fixed_format` says
  fixed — running it unconditionally slices columns off free-form input.
* `>>IF` / `>>EVALUATE` / `>>DEFINE` are evaluated **with or without
  `--define`** (#271), so an in-source `>>DEFINE` counts and only one arm of
  `>>IF ... >>ELSE` comes out.
* Records split with `_lines.split_source_lines` (`\n` / `\r\n` / `\r` only):
  `str.splitlines()` would cut a comment record at a form feed / NEL / U+2028
  and emit its tail as code.
* Normalisation uses `source_format.normalize_with_recovery()`: an
  unterminated literal at EOF prints `warning: Unterminated string literal
  ...` and the recovered text, exit 0 (#372).
* Fixed-format only: column-72 overflow diagnostics (real content past column
  72, truncated) print as `warning:` lines — see
  [preprocessing.md](preprocessing.md).

### `expand`

Prints `{"source_file", **CopybookExpansion.to_dict()}`. `--copybook-path` is
repeatable (search order); `--max-depth` (100) caps nesting (`max_nesting_depth`). A missing /
circular / traversing COPY is `error: Copybook expansion failed ...`, exit 1.
Conditional compilation always runs in the expander, `--define` or not
(`process_conditionals=True`), so a program's own `>>DEFINE` reaches its
copybooks and only one arm of each `>>IF` survives; diagnostics go to
`statistics.warnings`. Gating it on `--define` printed both arms (#583, the
`expand` twin of #271).

* `--keep-comments` puts each comment line's text back, in the program and in
  every inlined member. Expansion always blanks comments first (a `COPY`
  inside one must not expand); restoration happens after every substitution
  and moves no line. See [preprocessing.md](preprocessing.md).
* `--source-map` adds `source_location_map`: `{"<expanded line>": {"file",
  "line"}}` per expanded line — how a consumer maps a listing line back to a
  file a human edits. `lint` applies it automatically.

## Record data subcommands

Semantics (encodings, RDW, ODO trimming, FD `RECORD VARYING`, views,
compare rules) live in [generators/record-data.md](generators/record-data.md)
and [generators/decode-compare.md](generators/decode-compare.md); this
section covers what the CLI adds.

### `gen-data`

Synthetic data from a copybook (or a whole program's records). **CSV on
stdout** by default, so it pipes into a fixture file; `--output` writes
through the `csv` module so quoted cells round-trip.

* `--seed` pins the RNG (same seed and copybook, byte-identical output).
  `--list-records` (`{"source_file", "records": [{name, level, size}]}`) and
  `--describe` (layout plus rows, including the `seed` used — how to recover
  an unseeded run's seed) are the JSON modes. `--record NAME` picks a level-01
  (default the first; an unknown name lists the choices).
  `CopybookLayoutError` exits 1.
* **`--format record|hex`** emit the record image (COMP-3 packed, COMP
  big-endian, overpunched signs, ...) instead of display values. `record`
  writes raw bytes via `sys.stdout.buffer` or binary-mode `--output` (a COMP
  field routinely holds `0x0A`). The image is encoded **once** for whichever
  destination; the `--output` branch deliberately avoids
  `GeneratedDataset.write_records()`, which would encode a second time and
  hold both copies (a ceiling on a large `--rows`). `hex` annotates the same
  image field by field (offset, length, name, PICTURE, USAGE, value, bytes).
* Both force the byte-complete layout (`for_record_image()`: FILLER in,
  REDEFINES out, every OCCURS expanded) and say so on stderr, so
  `--include-filler`/`--max-occurs` never look silently ignored. Anything not
  modelled (SYNC alignment, IEEE-vs-hex float, ODO at maximum under `fixed`)
  goes to stderr for `record` and the header for `hex` — never swallowed.
* `--charset ebcdic` = cp037 DISPLAY bytes and EBCDIC sign zones (the sign
  convention follows the charset). `--endian` (`auto`: big for `ebcdic`, host
  order otherwise) applies to COMP-5 and COMP-1/2 only. `--record-separator
  newline` appends `\n` per record; `none` is a true RECFM=F image.
* **`--record-format fixed|variable|variable-bare|auto`** (record/hex only):
  `fixed` (default, so existing output never moves) writes every ODO
  occurrence; `variable` trims to each record's counter with a 4-byte RDW;
  `variable-bare` trims without RDW; `auto` is `variable` iff the record can
  vary. `--record-varying MIN:MAX` (or `MIN-MAX`) supplies an FD-style range
  for a bare copybook (a whole program's FD `RECORD VARYING` is read with no
  flag); passed alone it resolves to `auto`, while an explicit `fixed` still
  wins (argparse's default is `None` to keep the two apart). A range clamped
  to the record, or ignored because nothing is left, prints a `warning:` on
  stderr and a `* caveat:` in the hex header (#274). `hex` marks fields
  `(past record length)` / `(cut N/M bytes)`.
* The LRECL (or range) goes to stderr for `record` (raw bytes have no
  header) — the *declared* LRECL alongside the span the file happens to
  contain; `hex` puts it in its header with a `(RDW)` row per record. A
  DEPENDING ON counter outside the record is named on stderr and its table
  written at full length. A shorter 01 of a whole program is space-padded to
  the FD's LRECL so `decode` frames it the same way (#362).

### `decode`

The inverse of `gen-data --format record`: **bytes somebody else wrote plus a
copybook, back into a table**.

* Data file positional, copybook `--copybook`; the data file is optional only
  with `--list-views` (layout and every REDEFINES overlay with offsets,
  `length` / `overlay_length` — also how to learn what `--view` accepts).
  `--record` goes through the same `select_record()` as `gen-data`.
* `--view` reads the bytes through an overlay, by short name
  (`ADDR-OVERSEAS`) or path (`CUST-REC.ADDR-OVERSEAS`); output is the whole
  record with the overlay in place (every occurrence inside a table), so
  `compare --view` can still `--key` outside it (#296).
* `--format csv` is byte-identical to `gen-data`'s CSV for the same layout;
  `json` adds offset, length, raw hex, `present`/`truncated`/`error` per
  field; `hex` is a byte pane with `! field: error` under bad fields.
* File-format flags are the same `EncodingOptions` as `gen-data`.
  `--record-format auto` resolves identically on both sides: variable for a
  DEPENDING ON table **or** a whole-program `--copybook` whose FD declares
  `RECORD VARYING` (`RecordDecoder.varying`) — judging by the layout alone
  reads `gen-data --record-format auto`'s RDW file as fixed-length garbage.
* `--record-length` (decode-only) cuts fixed-length records longer than the
  layout; a whole-program source defaults it to the FD's LRECL (largest 01, or
  a larger `RECORD CONTAINS`), so `--record HDR-REC` on a shorter 01 frames
  right (#362).
* `--max-records`/`--skip` page a file (a `--max-records` stop is not
  reported as trailing bytes). Negative values, or a non-positive
  `--record-length`, are errors (exit 1; 2 on `compare`).
* stderr always reports caveats, the count of fields that did not decode, and
  trailing bytes that are not a whole record (usually a wrong record length);
  **`--strict`** makes either of the last two exit 1 — the CI form of "does
  this copybook describe this file?".
* A copybook that is not UTF-8 (a Latin-1 accent in a comment) is a one-line
  `error: Cannot read copybook FILE: ...`, exit 1, also under
  `--list-views` -- `UnicodeDecodeError` is a `ValueError`, not an `OSError`,
  and used to escape as a traceback (#496). `compare` words it the same.

### `compare`

Expected vs actual output of a batch run, field by field, one copybook.

* **Exit status follows `cmp`/`diff`**: 0 equal, 1 different (incl.
  differing trailing partial records, #250), 2 could not compare (unknown
  key/ignore name, unreadable or non-text file, layout error, unwritable `-o`,
  a `cobol.yml` error). Hence its own `_compare_fail()` (exit 2) and writer
  instead of `_fail()` / `_verbatim_out()`, whose exit 1 would mean "differ".
* LOW-VALUES vs spaces padding in a text field is a difference without
  `--compare-bytes` (#287), except in FILLER, which only `--compare-bytes`
  checks; when two values print the same, the text report adds their hex.
* `--key` (repeatable) pairs by key; `--ignore` (repeatable) drops a column,
  a field name (every occurrence) or a group; both are checked against the
  layout (a typo is exit 2 listing valid columns).
* File-format flags are shared with `decode` (`_add_record_file_args()`,
  same `cobol.yml` `data:` settings); both files use the same options.
* `--format text` (default) uses 1-based record numbers; `json` is
  `CompareResult.to_dict()` plus the three input paths, 0-based.

## gen-fixtures

Points at a whole **program** and produces mock in-data / assert-on stubs for
every boundary it touches (files, CALL/DYNCALL, SQL, CICS, DLI, console
ACCEPT); see [generators.md](generators.md) (program fixtures — phase
numbers below are that initiative's) and `docs/fixture-bundle-schema.md`.

* `--copybook-path` (repeatable) expands COPYs first; an unresolved member
  refuses (`ProgramLayoutError`, exit 1) rather than generate from a layout
  with a hole.
* `--callee-path DIR` (repeatable) finds a statically-CALLed program's source
  (`NAME`, `name` × `""`/`.cbl`/`.CBL`/`.cob`/`.COB`) to resolve its LINKAGE
  writes for the argument-direction ladder's "callee source" rung; a pair in
  one compilation unit (`contained_programs`, e.g. `subprogram_demo.cbl`)
  needs none.
* `--rows` (10) is per **READ** boundary's sequence; every other IN boundary
  (SQL SELECT/FETCH, ACCEPT, CALL argument) gets one value. A negative
  `--rows` / `data.rows`, or `--max-occurs` below 1, is an `error:`, exit 1
  (#327). `--max-occurs N` caps occurrences per OCCURS table.
* `--seed` gives byte-identical JSON; per-boundary sub-seeds mean adding one
  boundary never reshuffles another's values.
* `--scenarios happy` (default) is the single unconstrained scenario (Phase
  3); `branches` targets every reachable, satisfiable arm; `all` adds the
  empty-input / error-status / boundary-values families. Both go through
  `ScenarioPlanner` (Phase 5) via `generate_with_scenarios_from_file` (Phase
  6) and fill `scenario_coverage` (`null` under `happy`).
* `--format csv-dir` needs `--output DIR`: one CSV per file-shaped fixture at
  `DIR/<scenario-slug>/<KEY>.csv` plus `DIR/MANIFEST.json` — the bundle with
  each `sequence` emptied to `[]` (never a hint string, so it stays
  type-compatible) and a `csv_path` per fixture (or `null`, e.g. a
  STATUS_ONLY boundary).
* `--list-boundaries` runs Phases 1-2 only: `{"source_file", "boundaries":
  [{category, key, paragraph, line, direction}]}` — the cheap cross-check
  against a consumer's own walk.
* `--strict` exits **2** (1 stays "could not run") when `bundle.unresolved` is
  non-empty, including any arm whose scenario data *violates* it (#244).

## Single-file analyzers

Each takes `file` plus **A** (and **+prof** per the
[reference](#subcommand-reference)), parses once, and emits the analyzer's
`to_dict()` via `_emit_report`. Semantics: [analysis.md](analysis.md).

| Subcommand | Runs / reports |
|---|---|
| `analyze` | `DynamicCallAnalyzer`: dynamic `CALL` targets only (`called_program`, `is_dynamic`, `possible_values`, plus `"possible_values_incomplete": true` when the set is not fully resolvable, so it never reads as exhaustive). Not an all-analyzers summary |
| `dead-code` | `DeadCodeAnalyzer`: unreachable paragraphs/sections; one referenced only from dead code is dead too (#384) |
| `program-flow` | `ProgramFlowAnalyzer` CFG; `--format json` (`report.to_dict()`), `mermaid` / `dot` (`generators/flowchart.py`'s `MermaidFlowchartGenerator` / `DotFlowchartGenerator`) |
| `recursion-check` | `RecursionRiskAnalyzer`: `cycle_details` cycles (`PERFORM_RECURSION` HIGH; `GOTO_LOOP`/`MIXED` HIGH or MEDIUM by escape route) and self-recursive CALLs (HIGH) |
| `complexity` | `ComplexityAnalyzer`: per-paragraph McCabe and `extended_complexity`, nesting, fan-in/out, LOW/MODERATE/HIGH `rating`, program summary (`total_complexity`, `mean_complexity`, `goto_density`, ...) |
| `health` | `TechnicalDebtAnalyzer`: 0-100 score, A-F grade, components, `top_offenders`, `complexity_summary`/`redundancy_summary`. A file parsed with errors exits 0 with `"grade": null`, nonzero `parse_error_count` and a caveat (#397) |
| `io-sequence` / `move-type-check` / `linkage-check` / `language-env` | `IOSequenceAnalyzer` / `MoveTypeChecker` / `LinkageChecker` violations; LE function/service usage |
| `ims-dli` | `IMSSegmentAnalyzer`; `is_ims_program` = `ast.has_ims() or ast.uses_ims_interface()` (a CBLTDLI / AIBTDLI / CEETDLI caller is IMS without `ENTRY 'DLITCBL'`, #398); `primary_segment` is a call's **last** segment |
| `data-items` | `compute_program_data_items()`: `{"items", "unresolved"}` — offset, length, REDEFINES chain, OCCURS min/max, level-88 values, every DATA DIVISION section ([generators/record-data.md](generators/record-data.md)). A bare copybook is wrapped like gen-data's (`args._wrap_copybook_fragment`, read by `_do_parse`); a file with no DATA DIVISION exits 1 instead of printing `"items": []` (#536) |
| `dclgen-check` | `DclgenChecker().check(ast)`: `violation_count`, `checked_count`, `unchecked_count`, `worst_severity`, `tables`, `violations`, `checked`, `unchecked`, `ambiguous_columns`; also a lint rule |
| `redundancy` | `RedundancyAnalyzer`: `dead_code`, `unused_variables`, `clone_groups`, `paragraph_fingerprints` (only exposed here). Hand-built for `--min-clone-statements`, shared with `scan` via `_add_min_clone_statements_arg` so the two cannot disagree on what a clone is |
| `xref` | `XrefReport`: `entries` (`definition`, `references`, `reference_count`), `undefined`, `caveats` (+ the parser's unexpanded-COPY warnings, which explain fields looking undeclared), `duplicate_declarations`, `summary` |
| `program-signature` | `{"signatures": [...]}` for **every unit** by default (a caller may target a contained program); `--program` narrows |
| `sql-cics-check` | `SqlCicsReport`; lint rule id `sql-cics-check` |

**`unused-variables`**: `--exclude-copybook-variables` drops unused items that
came from an expanded COPY. It needs `--copybook-path` (else a stderr warning
notes the no-op) because provenance comes from a second parse *without*
expansion (`_parse_without_copybook_expansion`) diffed against the expanded
AST — `expand_copybooks`'s own line tracking cannot answer it.

**`business-rules`**: decision / validation / calculation rules, the level-88
glossary, a rule-to-data lineage table. `--format text` renders
`BusinessRuleReport.to_text()`; `--include-technical` keeps file-status / EOF
/ SQLCODE / EIBRESP rules flagged `technical` (otherwise only counted in
`summary.technical_rules_excluded`). Hand-built
(`_build_business_rules_parser`) only for those two flags.

## lint

`LintAnalyzer` ([analysis.md](analysis.md)): several analyzers over **one**
parse, one severity-graded finding list.

* `--rule` ids are the analyzer subcommand names (`dead-code`,
  `unused-variables`, `move-type-check`, `io-sequence`, `linkage-check`,
  `recursion-check`, `complexity`, `dclgen-check`, `sql-cics-check`).
  Argparse `choices` rejects an unknown id (exit 2) so a typo never reads as
  "found nothing" (`test_lint_subcommand.py::test_unknown_rule_is_rejected_by_argparse`).
  Selection is normalized to canonical order. `--min-severity` filters
  *after* the rules run, so summary counts match what is shown.
* `--format json`: header plus `findings` / `rules_run` / `failed_rules` /
  `caveats` / `summary`. `--format text`: `file:line:column: severity [rule]
  message` per finding (the prefix editors and build logs parse), `note:`
  lines for caveats and failed rules, a summary line; a finding with no
  location prints as `file: severity ...`.
* Exit: 0 completed (findings alone never change it), 1 unreadable / no AST /
  unwritable output, 2 argparse, 3 `--fail-on` threshold hit.
* **Parse errors are findings** (#249): a partial AST lints quietly, so
  `_cmd_lint` runs `add_parse_errors()` over `result.errors` before the
  source map and the severity filter — each a `rule: "parse"`, `severity:
  "error"` finding (`kind` = error code or class name). `--fail-on` (any
  level) then exits 3 on a non-COBOL file; without it the exit is 0 and the
  partial findings stay usable. `parse` is not in `RULES`, so `--rule` neither
  selects nor drops it.
* **Every program unit** by default (a contained program left unexamined
  would read as clean); `--program` narrows.
* **`--copybook-path`** expands COPYs so MOVE operands resolve; grades an
  unused copybook item `info` and a program-declared one `warning` (the
  `unused-variables` set difference); and gives real origins — a finding in
  an inlined member names the *copybook*; one the map cannot place has no
  `origin`. `_lint_copybook_item_names` diffs expanded vs unexpanded declared
  names over `program_units()` on both sides, narrowed the same way under
  `--program` (diffing only the outermost would grade a contained program's
  copybook fields `warning`; another unit's declaration must not subtract from
  this one's set) — `test_nested_program_units.py::TestCopybookProvenanceCoversEveryUnit`.
* **On-disk columns** (#301): analyzer columns count the *normalized* text
  (fixed-format columns 8-72, 7 short of an editor). `_lint_column_offset`
  judges the program as `CobolParser` does (`--source-format`, else
  `detect_fixed_format`), each copybook as the expander did
  (`_looks_fixed_format`), and gives a line after `>>SOURCE FORMAT FREE`
  (`free_format_flags`) no shift. `analysis.lint.fixed_format_column_offset`:
  fixed listing + fixed file 7, fixed listing + free member 0 (re-padded by
  7), free listing + fixed member 6 (only the sequence area is cut), free
  throughout 0.
* **Lint always stamps `origin`** (the file itself when nothing is expanded),
  so `origin.column` is the on-disk column and text prints it;
  `location.column` stays the analyzer's. Compare `origin.file` with
  `source_file` to know whether copybooks were involved. Text omits a column
  it cannot vouch for (`LintFinding.column_known` False, an unreadable
  copybook, a line outside the map): `file:line:`, no `origin.column`. Known
  gap: `>>SOURCE FORMAT IS FREE` *inside a copybook* leaves columns off by one.

## scan

Many files, one process: parse *and* analysis run in workers and only report
dicts come back, so a worker's peak memory is one file's AST.
`cobolparser/scan.py`, not `batch.py` (see [batch.md](batch.md)).

* `--analyzer` takes repeated or comma-separated names (`parse_analyzer_list`):
  `health`, `redundancy`, `complexity`, `dead-code`, `unused-variables`,
  `lineage` (the `FieldFlowReport` `field-impact` joins); default
  `health,redundancy`. Unknown names exit 1 from `scan_files` (argparse
  `choices` would reject the comma spelling).
* `--clones` (needs `redundancy`; otherwise no groups rather than an empty
  result) merges paragraph fingerprints into cross-file groups
  (`cross_file_clone_groups`), Type-1 over Type-2, ranked by *duplicated
  volume* (statements x members), NOT by spread: every shop's near-identical
  four-statement `0000-MAIN-PROCESS` would bury a sixteen-statement verbatim
  copy.
* With `--copybook-path`, a paragraph expanded from a PROCEDURE DIVISION
  copybook carries its `origin`; members sharing an origin are one source
  included several times, so `--min-clone-members` and the ranking count
  *distinct sources* (`source_count`) (#352). A copybook paragraph only ever
  arriving by COPY forms no group; one also pasted into another program does.
* `--files-from FILE` (`-` = stdin; `#` comments and blanks skipped; lines
  stripped so a Windows `\r` never joins a path) exists because a Windows
  command line caps at 8191 characters and the COBOL Analyzer extension spawns
  via `shell: true` there. An unreadable list exits 1 rather than scanning
  nothing.
* A directory named as a file (argument or `--files-from` line) exits 1 with
  `X is a directory; pass the files in it, e.g. --glob 'X/**/*.cbl'`, and a
  `--glob` drops the directories its `**` walks through (#737; shared with
  `batch` via `_collect_scan_files`). Before, each one was a `failures` entry
  reading "Encoding error ... Is a directory".
* `--source-format` reaches the parse as `ScanOptions.free_form` +
  `ScanOptions.preprocess_fixed`, the pair `_source_format_kwargs()` hands
  every single-file subcommand (forwarding only `free_form` would leave
  `fixed` auto-detecting).
* Output: `scan_version` (check it first), `analyzers`,
  `min_clone_statements`, `summary` (`file_count == scanned + failed` by
  construction), `files[]`, `failures[]`. An unreadable/unparseable file is a
  `failures` entry; an analyzer raising on one unit lands in that unit's
  `failed_analyzers`, other reports intact; a failed copybook expansion still
  scans unexpanded with `copybook_error`. Every unit is reported with its
  nesting `depth`.

## lineage / field-impact

`lineage` runs `FieldFlowAnalyzer` on one program (ports, edges,
port-to-port summary, key uses; edges origin-stamped). `--field` traces one
data item (a single-report `LineageGraph`). See [analysis.md](analysis.md).

`field-impact` parses every `.cbl/.cob/.cobol` under PATH through
`scan_files(..., analyzers=("lineage",))` and joins the reports in a
`LineageGraph`. Start: FIELD (narrow with `--program`), `--table
[SCHEMA.]TABLE.COLUMN` or `--dataset DSN` — exactly one. Bindings: `--jcl`
(needs jcl-parser; `--proc-path` is a flat PROC folder or a JCLLIB base,
repeatable and searched in order, the first folder doubling as the JCLLIB base)
and/or `--bindings` (`{"bindings": [...], "passthroughs": [...]}`, dict forms
of `DatasetBinding` / `Passthrough`; `jcl --bindings` output works as-is: a
row with no `program` or `dataset` is skipped, and a malformed row is a
one-line `error: --bindings: ...` naming it, exit 1, never a traceback). `--depth` caps the joins a path crosses
(dataset or table hop into another program, or a CALL). JSON:
`ImpactResult.to_dict()` + `graph` (statistics, opaque callees, unjoined DDs,
caveats, incl. JCL steps `bindings_from_jobs` could not read, passed as
`join_caveats`) + `problems` (files with no report, JCL that did not parse
or expand). Text groups hits by program with their paths -- item hits and
port hits (`port console:SYSOUT@0+4 line 23 [display]`, an unbound DD, a
CALL argument), the same hits as the JSON (#528) -- then `Unjoined:` and
`Problems:`. Exit 0 when the start was found (hits or not, including a
declared field no value flows through, #546); 1 when no source produced a
report (problems printed first), the start matches no declared item (report
still printed with `"start_found": false`), or on an argument error. Files
that failed while others parsed stay in `problems` only.

## diff, codebase-graph, copybook-impact, jcl, le-info

Their arguments do not fit `_build_analyzer_parser`'s single-`file` shape, so
each builds its own parser (`_cmd_diff`, `_cmd_codebase_graph`,
`_cmd_copybook_impact`, `_cmd_jcl`, `_cmd_le_info`).

### `diff`

`cobol-parser diff old/PROG.cbl new/PROG.cbl`. `--format text` renders
`DiffReport.to_text()` (`+`/`-`/`~`); `--rename-threshold` (0.0–1.0, default
0.8; 1.0 = identical bodies only; out of range exits 1) is the similarity
before an unmatched pair is a rename rather than remove + add. Both sides go
through the single-file parse helper by swapping `args.file`, so
`--source-format`, `--dialect`, `--copybook-path` and `--define` apply
identically — different options per side would make the diff meaningless.
JSON is `{"old_file", "new_file", **report.to_dict()}`. No `--program`.

### `codebase-graph` / `copybook-impact`

```bash
cobol-parser codebase-graph ./src --copybook-path ./copybooks --format mermaid -o graph.mmd
cobol-parser copybook-impact CUSTREC ./src --copybook-path ./copybooks
```

Both take **one directory to walk, or any number of source files**.
`--extension` (repeatable, with or without the dot; `cobol.yml`
`project.extensions`), `--workers` (by input size), `--copybook-path`.
`codebase-graph --format dot|mermaid` uses `to_dot()` / `to_mermaid()` (the
flowchart renderer's conventions). `copybook-impact` takes the member first
(bare name, file name or path) and emits `ImpactReport.to_dict()`:
`direct_programs`, `transitive_programs`, COPY `chains`, the member's
`fields`, `unresolved`, `summary`.

### `jcl`

| Flag | Meaning |
|------|---------|
| `--dd-map` | Only the `ddname -> datasets` mapping (what `SELECT ... ASSIGN TO ddname` resolves through) |
| `--bindings` | One row per DD binding (ddname, dataset, step, job, DISP, RECFM, LRECL, program) instead of the job structure; usable as `field-impact --bindings` input |
| `--program NAME` | Only the steps that run this program (`PGM=`, or `RUN PROGRAM` under IKJEFT01, the DFSRRC00 `PARM` program); filters `--dd-map` (DD names *and* datasets of those steps only) and `--bindings` to the same steps. A name no step runs prints the empty view, then exits 1 (#493) |
| `--proc-path DIR` | Cataloged procedures and INCLUDE members (one per file, named after it; repeatable, in order). Without it only in-stream procedures expand; other `EXEC proc`s go to `unresolved` |
| `--strict` | **Exit 3** when any card could not be parsed (exit 1 still means the run failed) |

Not COBOL, so no COBOL parse flags. Needs `jcl-parser` (`pip install
'cobol-parser[jcl]'`); without it, a one-line `error:` with that hint, exit 1
(#326). See [jcl.md](jcl.md).

### `le-info`

`cobol-parser le-info [CEEDAYS NUMVAL-C ...] [--kind service|function|all]`.
The only subcommand reading **no source**: it dumps
`dialects/le_signatures.py`'s catalogue for the COBOL Analyzer's LE hover, so
its shape is pinned by `catalog_version`. No name: `{catalog_version,
reference, services[], services_without_signature[], functions[]}`; names:
`{catalog_version, reference, entries[]}` in the order asked. A name the
dialect knows but the catalogue cannot describe has `"parameters": null` and
a note; an unknown name exits 1. `--kind` restricts both forms.

## IO coverage tools (`cobolparser/cli/coverage.py`)

A separate argparse program (not a subcommand, not a console script): `python
-m cobolparser.cli.coverage <cmd>`, wrapping
`analysis.io_coverage_reporter.IOCoverageReporter` ([analysis.md](analysis.md)).

| Command | Flags (default) |
|---|---|
| `status` | `--artifact` (`io-coverage.json`), `--verb`, `--qualifier`, `--format {table,json}` (table) |
| `generate` | `--pytest-results FILE` (required), `--output` (`io-coverage.json`), `--catalog CSV`, `--schema JSON` |
| `validate` | `--artifact FILE` (required) |
| `render` | `--input FILE` (required), `--output` (stdout), `--format {markdown,csv,summary}` (markdown) |

`main()` returns the command's status (no command: help, exit 1). `status`
falls back to `./io-coverage.json` only when the requested artifact is missing
*and* is not that path (printing a `Note:`), so a stale default is never
served silently. A malformed artifact or pytest-results file is a clean
error, exit 1. Tests: `tests/unit/cli/test_coverage_cli.py`,
`test_coverage_cli_extra.py`.

## See also

* [analysis.md](analysis.md) — the analyzers, incl. `BoundaryInventoryAnalyzer`
  and `ConstraintExtractor`/`domains.solve()` behind `gen-fixtures`
* [generators.md](generators.md) — program fixtures, record data, decode/compare, flowcharts
* [parser.md](parser.md) — `parse_cobol`, `ProfilerContext`
* [preprocessing.md](preprocessing.md) — expansion, source map, comment restoration, D lines
* [batch.md](batch.md) — `scan_files` behind `scan`, and why it is not `batch.py`
* [jcl.md](jcl.md) — the jcl-parser adapter behind `jcl`
* [tests.md](tests.md) — `tests/unit/cli/` covers the subcommands
* [`docs/fixture-bundle-schema.md`](../docs/fixture-bundle-schema.md) — the `FixtureBundle` JSON shape
* [history](history/cli.md) — archived dated notes (former "Recent changes", per-fix narratives)
