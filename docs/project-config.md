# `cobol.yml` — the universal project config

Set your project up **once**, in one file at its root, instead of repeating
the same flags on every command and re-entering them in every editor.

Three tools read the same file:

| Tool | Reads |
|------|-------|
| `cobol-parser` CLI | `version`, `project:`, `data:`, `lint:` |
| `mockymock` CLI | `project.copybook_path`, `project.seed`, `mockymock:` |
| COBOL Analyzer (VS Code) | `project.copybook_path`, and passes the file to the CLI it spawns |

```yaml
# cobol.yml
version: 1

project:
  copybook_path:
    - copybooks
    - shared/copybooks
  source_format: fixed
  dialect: ibm-enterprise
  seed: 42

data:
  charset: ebcdic
  endian: big

lint:
  min_severity: warning
  fail_on: error

mockymock:
  test_root: tests
```

With that in place:

```bash
cobol-parser lint PROG.cbl        # copybooks found, warnings filtered, CI gate on errors
cobol-parser gen-data CUST.cpy    # EBCDIC, big-endian, seed 42
mockymock run PROG.cbl            # same copybooks, same seed, suites under tests/
```

## Where the file is looked for

`cobol.yml`, then `cobol.yaml`, in the current directory and then each parent
— the way `git` walks up looking for `.git`. **First match wins**; the walk
stops at the filesystem root (or after 32 levels). Having no config file
anywhere is the ordinary case and is not an error.

Paths inside the file are resolved **against the file's own directory**, not
against your current directory, so `cobol-parser lint` run from `src/batch/`
searches the same copybook libraries as one run from the project root.
A leading `~` and `$VAR` / `${VAR}` are expanded first, the way your shell
expands them in `--copybook-path ~/cpy`, so `~/copybooks` and
`$SHOP_ROOT/copybooks` mean what they say (an unset variable is left as
written). A `copybook_path` or `callee_path` entry that is not an existing
directory is never dropped silently: `cobol-parser config` marks it
`(not an existing directory)` (and `--json` lists it under
`missing_directories`), and every command that uses that setting prints a
one-line `warning:` naming it on stderr.

Two flags override the search, and may appear on either side of the
subcommand:

```bash
cobol-parser --config ./ci/cobol.yml lint PROG.cbl   # use exactly this file
cobol-parser lint PROG.cbl --no-config               # ignore any config file
```

Both are recognised only spelled out in full: an abbreviation such as
`--no-conf` or `--conf=FILE` is an error rather than being passed on to the
subcommand.

To see what is actually in effect:

```bash
cobol-parser config          # the file, and only the settings it changes
cobol-parser config --json
```

## Precedence

**explicit CLI flag > config file > built-in default.**

A flag you type always wins, including when the value you typed happens to
equal the built-in default. `--copybook-path` is *replaced*, not merged: if
you pass it, you get exactly the directories you named.

## Every key

All keys are optional. An unrecognized key is an **error** naming the file —
a typo'd `copybook-path` that quietly did nothing would leave you running
with a config you believe is in effect and isn't.

### `version`

Schema version; currently `1`. A file declaring any other version is refused
rather than read under the wrong rules.

### `project:` — shared by every tool

| Key | Type | Fills |
|-----|------|-------|
| `copybook_path` | string or list | `--copybook-path` |
| `callee_path` | string or list | `--callee-path` (`gen-fixtures`) |
| `source_format` | `auto` \| `fixed` \| `free` | `--source-format` |
| `debug_lines` | `true` \| `false` | `--debug-lines` / `--no-debug-lines` (compile fixed-format `D`-in-column-7 lines as code) |
| `dialect` | `ibm-enterprise` | `--dialect` |
| `error_recovery` | `collect-all` \| `fail-fast` | `--error-recovery` |
| `seed` | integer | `--seed` |
| `extensions` | list | `--extension` (`codebase-graph`, `copybook-impact`) |
| `define` | mapping or list | `--define` |

`define` takes either shape:

```yaml
define:
  DEBUG: "TRUE"
  TRACE:                 # no value -- the bare `--define TRACE` spelling
# or
define: ["DEBUG=TRUE", "TRACE"]
```

In the mapping shape each value is a single string, number or `true`/`false`
(or empty); a list or mapping as a symbol's value is an error.

A key fills a command's flag only when the command has that flag. A few
commands still have no `--define` or `--source-format` (`batch`,
`gen-fixtures`, `codebase-graph`, `copybook-impact`, `gen-data`, `decode`,
`compare`; `tokenize` has no `--define`, `expand` no `--source-format`).
When the config sets `define`, a non-`auto` `source_format` or `debug_lines:
true` and the command cannot apply it, the command prints a `warning:` on
stderr naming the key rather than quietly parsing a different program.
`gen-data`, `decode`, `compare` and `expand` do not warn about
`source_format`: they read copybooks, where auto-detection settles the
format, so the warning would fire on every run for nothing. They still warn
about `define`, which can change a record layout.

### `data:` — record layout and encoding

Defaults for the record-data subcommands. An EBCDIC shop states these once
here instead of on every invocation. The four encoding keys fill the flags of
the same name on `gen-data`, `decode` and `compare`; `rows` fills `--rows` on
`gen-data` and `gen-fixtures`.

| Key | Type |
|-----|------|
| `charset` | `ascii` \| `ebcdic` |
| `endian` | `auto` \| `big` \| `little` \| `native` |
| `record_format` | `fixed` \| `variable` \| `variable-bare` \| `auto` |
| `record_separator` | `none` \| `newline` |
| `rows` | integer |

### `lint:`

| Key | Type |
|-----|------|
| `rules` | list of rule ids (`dead-code`, `unused-variables`, `move-type-check`, `io-sequence`, `linkage-check`, `recursion-check`, `complexity`, `dclgen-check`, `sql-cics-check`) |
| `min_severity` | `error` \| `warning` \| `info` |
| `fail_on` | `error` \| `warning` \| `info` \| `never` |

### `mockymock:` and `analyzer:`

Sections owned by the other two tools. `cobol-parser` validates that each is
a mapping and otherwise carries it through untouched — it never needs to
know their schemas. See mockymock's own docs for `mockymock:` keys
(`test_root`, `ai_mode`).

## What is deliberately *not* configurable

Per-invocation choices stay flags: `--program`, `--output`, `--format`,
`--compact`, `--strict`, `--profile`. Putting them in a shared file would
mean two people in the same repository getting different output from the
same command.

## The YAML subset

This package has no runtime dependencies, so it ships a small reader rather
than taking on PyYAML. It supports what a config file needs — nested
mappings, block sequences (indented under their key or written at the
key's own column), flow sequences, flow mappings (either may span lines),
quoted and plain scalars,
`#` comments, one optional leading `---` — and **rejects** everything else
with a line number: anchors and aliases, tags, block scalars (`|`, `>`),
merge keys, multiple documents, tabs in indentation, duplicate keys.

Two deliberate departures from YAML 1.1, both following the YAML 1.2 core
schema, because the surprising behavior is worse than the missing feature:

- `yes` / `no` / `on` / `off` are **strings**, not booleans. Only `true` and
  `false` are booleans.
- A duplicate key is an error rather than last-one-wins.

Quote anything you want kept as literal text: `"true"`, `"42"`.
