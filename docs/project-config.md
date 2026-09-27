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

Two flags override the search, and may appear on either side of the
subcommand:

```bash
cobol-parser --config ./ci/cobol.yml lint PROG.cbl   # use exactly this file
cobol-parser lint PROG.cbl --no-config               # ignore any config file
```

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

Schema version; currently `1`. A file declaring a higher version is refused
rather than read under the older rules.

### `project:` — shared by every tool

| Key | Type | Fills |
|-----|------|-------|
| `copybook_path` | string or list | `--copybook-path` |
| `callee_path` | string or list | `--callee-path` (`gen-fixtures`) |
| `source_format` | `auto` \| `fixed` \| `free` | `--source-format` |
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

### `data:` — record layout and encoding

Defaults for `gen-data`, `gen-fixtures` and `decode`. An EBCDIC shop states
these once here instead of on every invocation.

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
key's own column), flow sequences, flow mappings, quoted and plain scalars,
`#` comments, one optional leading `---` — and **rejects** everything else
with a line number: anchors and aliases, tags, block scalars (`|`, `>`),
merge keys, multiple documents, tabs in indentation, duplicate keys.

Two deliberate departures from YAML 1.1, both following the YAML 1.2 core
schema, because the surprising behavior is worse than the missing feature:

- `yes` / `no` / `on` / `off` are **strings**, not booleans. Only `true` and
  `false` are booleans.
- A duplicate key is an error rather than last-one-wins.

Quote anything you want kept as literal text: `"true"`, `"42"`.
