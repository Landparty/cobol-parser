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
* **`--format github`** prints one `::error` / `::warning` / `::notice` per
  finding, which GitHub shows on the pull request diff. `text` is
  `file:line:column: severity [rule] message`; `sarif` is for code scanning.

| Exit | Meaning |
|------|---------|
| 0 | every file linted; no finding reached `--fail-on` |
| 1 | a file could not be read or parsed, the output could not be written, or git could not answer `--changed-since` |
| 2 | bad arguments |
| 3 | a finding at or above `--fail-on` |

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

`call-check` compares each static CALL with the program it calls (argument
count and byte lengths). It runs only when lint can find the callees: pass
`--callee-path DIR` (repeatable) or set `project.callee_path` in `cobol.yml`.
A callee it cannot find or parse becomes a caveat, never a finding.

```bash
cobol-parser lint src/PAYMAIN.cbl --callee-path src/ --fail-on error
```

## GitHub Actions

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
