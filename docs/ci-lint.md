# Linting COBOL in CI

`cobol-parser lint` is built to gate a pull request: it lints many programs in
one run, can pick only the programs a change touched, prints GitHub
annotations, and exits 3 when a finding reaches the severity you choose.

## Settings in `cobol.yml`

Put the copybook libraries and the gate in `cobol.yml` at the repository root
([project-config.md](project-config.md)). CI, pre-commit and a terminal then
lint the same way:

```yaml
version: 1
project:
  copybook_path: [copybooks]
lint:
  min_severity: warning     # hide info findings
  fail_on: error            # exit 3 on any error, parse errors included
```

Lint **programs**, not copybooks: a copybook is checked through the programs
that COPY it, and a finding inside one names the copybook's own file and line.

## Commands

```bash
cobol-parser lint src/*.cbl --format text                  # many files, one exit code
cobol-parser lint --glob 'src/**/*.cbl' --format sarif -o lint.sarif
cobol-parser lint --changed-since origin/main --format github
```

* **Several files** (more than one FILE, or `--glob`, `--files-from`,
  `--changed-since`) are linted in one run. A file that cannot be read or
  parsed is reported and the others still run.
* **`--changed-since REF`** lints the programs changed since REF (from its
  merge base with `HEAD`; working-tree edits and untracked files count),
  **plus every program that COPYs a changed copybook**, directly or through
  another copybook. Without FILE or `--glob` it picks from every program git
  knows (`.cbl`, `.cob`, `.cobol`, or `--extension`), leaving out the
  copybook directories. Nothing changed is a clean run.
* **`--new-code-since REF`** goes one step further, to lines: it keeps only
  the findings on lines added or edited since REF (like a Sonar new-code
  quality gate), so a pull request is judged on what it wrote, not on what
  the program already had. `--scope RULE=all` judges one rule on the whole
  codebase instead (`lint.scope` in `cobol.yml`). `--summary-file
  "$GITHUB_STEP_SUMMARY"` adds a Markdown list of every finding to the run.
* **`--format github`** prints one `::error` / `::warning` / `::notice` per
  finding, which GitHub shows on the pull request diff. `text` is
  `file:line:column: severity [rule] message`; `sarif` is for code scanning.

| Exit | Meaning |
|------|---------|
| 0 | every file linted; no finding reached `--fail-on` |
| 1 | a file could not be read or parsed, the output could not be written, or git could not answer `--changed-since` |
| 2 | bad arguments |
| 3 | a finding at or above `--fail-on` |

## Adopting the gate on an existing codebase

A legacy codebase starts with thousands of findings, so a gate that fails on
any of them never goes green. Three tools get it there:

* **A baseline.** Record today's findings once and commit the file; a run
  with `--baseline` (or `lint.baseline` in `cobol.yml`) reports only findings
  that are not in it. Findings are matched on rule, kind, file and the name
  they are about, never the line, so editing a program does not turn its
  known findings into new ones.

  ```bash
  cobol-parser lint --glob 'src/**/*.cbl' --write-baseline lint-baseline.json
  cobol-parser lint --glob 'src/**/*.cbl' --baseline lint-baseline.json --fail-on warning
  ```

* **Inline suppression**, for a finding you have looked at and accept:

  ```cobol
        * cobol-lint: disable-next-line=dead-code
         9000-OLD-RECALC.
             MOVE A TO B    *> cobol-lint: disable=move-type-check
        * cobol-lint: disable=unused-variables/WORKING-STORAGE
         ...
        * cobol-lint: enable=unused-variables
        * cobol-lint: disable-file=complexity
  ```

  A rule id, `rule/KIND`, a comma-separated list, or nothing (every rule).
  A directive inside a copybook silences that copybook's findings in every
  program that COPYs it. The summary counts what was suppressed.

* **Per-rule settings** in `cobol.yml`: `disable: [...]`, `severity:
  {rule: level}` (or `rule/KIND`), and `exclude: [globs]` for folders lint
  should never read.

By default `--format text` and `github` show warnings and errors only;
`json` and `sarif` carry every finding, info included. Several files are
linted in parallel (`--workers`, default the CPU count).

## Missing copybooks

IBM's CICS copybooks `DFHAID` and `DFHBMSCA` are built in (searched after
your `copybook_path`, so a real copy wins). Any other COPY lint cannot find
is left out, the file is still linted, and the report's caveats name the
member, since rules that needed its fields could not check them. Pass
`--strict-copybooks` to fail such a file instead (exit 1).

## The `line-length` rule

Fixed-format source is 80 columns, and the compiler reads only columns 8-72.
`line-length` reports what silently goes wrong at both edges, in programs and
in every copybook they read:

* **past column 80**: error (warning when it is only comment text). The
  columns are lost when the member goes to an 80-column library.
* **a word cut at column 72**: warning. The rest of the word is in the
  identification area, which the compiler ignores. Sequence numbers and the
  file's own identification stamps in columns 73-80 are not flagged.

Free-format source has no column limit and is skipped. Select only this rule
with `--rule line-length`.

## Bug-pattern rules and CALL interfaces

Seven rules look for common coding bugs: `truncation`, `subscript-range`,
`next-sentence`, `perform-range`, `file-status`, `uninitialized` and
`obsolete-verb`. They run by default; select one with `--rule truncation`.

Ten more report what IBM's compiler would reject (`error`) or warn about
(`warning`), so a CI gate catches it before the mainframe compile:
`undefined-name`, `value-clause`, `data-layout`, `comparison`, `search-table`,
`divide-by-zero`, `subscript-usage`, `procedure-structure`, `corresponding`
and `arithmetic-operand`. `undefined-name` stays quiet, with a caveat, for a
program whose COPY members were not all found.

Eight more come from what other COBOL linters check: `constant-condition`
(`IF A = A`, `A = 'X' AND A = 'Y'`), `duplicate-branch` (a WHEN or ELSE IF
that repeats an earlier test), `self-assignment` (`MOVE X TO X`),
`stop-run-in-subprogram`, `string-pointer` (a pointer set to 0, or too small
for its field), `loop-variable` (a PERFORM VARYING body that changes its
control variable), and two info rules, `evaluate-other` (no WHEN OTHER) and
`nesting-depth` (more than 5 levels). Turn off one you do not want with
`--disable RULE` or `lint.disable` in `cobol.yml`.

`call-check` compares each static CALL with the program it calls (argument
count and byte lengths). It runs only when lint can find the callees: pass
`--callee-path DIR` (repeatable) or set `project.callee_path` in `cobol.yml`.
A callee it cannot find or parse becomes a caveat, never a finding.

```bash
cobol-parser lint src/PAYMAIN.cbl --callee-path src/ --fail-on error
```

## GitHub Actions

This repository is itself a GitHub Action that does all of this in a few
lines, and lets each rule judge either new code only (the lines a pull
request adds or edits) or the whole codebase:

```yaml
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: landparty/cobol-parser@main
        with:
          fail-on: error
          all-code-rules: call-check
```

Every input, scopes and the job summary: [github-action.md](github-action.md).
The same gate by hand:

```yaml
name: COBOL lint
on:
  pull_request:
  push:
    branches: [main]

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0          # --changed-since needs the base branch history
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install "cobol-parser==3.4.0"
      - name: Lint changed programs
        if: github.event_name == 'pull_request'
        run: cobol-parser lint --changed-since "origin/${{ github.base_ref }}" --format github
      - name: Lint every program
        if: github.event_name != 'pull_request'
        run: cobol-parser lint --glob 'src/**/*.cbl' --format github
```

The gate comes from `cobol.yml` (`fail_on: error`); add `--fail-on` to the
command to override it. For GitHub code scanning instead of annotations, write
`--format sarif -o cobol.sarif` and upload it with
`github/codeql-action/upload-sarif` (code scanning on a private repository
needs GitHub Code Security).

## pre-commit

```yaml
repos:
  - repo: https://github.com/landparty/cobol-parser
    rev: v3.4.0
    hooks:
      - id: cobol-lint-changed   # changed programs + programs using a changed copybook
```

`cobol-lint` lints only the staged program files themselves (add `exclude:`
for a copybook folder whose members end in `.cbl`). Both hooks default to
`--fail-on error`; set `args:` to change it.
