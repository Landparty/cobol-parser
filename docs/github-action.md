# The COBOL lint GitHub Action

This repository is a GitHub Action. Another repository adds a few lines to a
workflow and every pull request gets COBOL lint findings on its diff, a job
summary listing them, and a pass or fail gate. You choose which rules run,
and for each rule whether it judges **new code only** (the lines the pull
request adds or edits, like a Sonar new-code quality gate) or **the whole
codebase**.

It runs `cobol-parser lint` ([ci-lint.md](ci-lint.md)) with
`--new-code-since` and `--scope`, so a terminal, pre-commit and CI all lint
the same way and read the same `cobol.yml`.

## Quick start

`.github/workflows/cobol-lint.yml` in the repository holding the COBOL:

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
          fetch-depth: 0              # history back to the base branch
      - uses: landparty/cobol-parser@main
        with:
          copybook-path: copybooks
          fail-on: error
```

On a pull request this lints the programs the pull request touched (and the
programs that COPY a copybook it touched) and reports only the findings on
the lines it added or edited. A pull request that adds no new error passes,
however many old findings the programs already had. On a push to `main` it
judges what the push brought in.

`@main` follows the latest commit. For runs that only change when you
decide, pin a release tag instead (`@vX.Y.Z`): any release published after
this action was added carries `action.yml`; earlier tags, 3.5.0 included,
do not.

**This repository is private.** For a workflow in another repository to use
it, open this repository's **Settings → Actions → General → Access** and
allow access from repositories owned by the same account or organization.

## Choosing rules and scopes

```yaml
      - uses: landparty/cobol-parser@main
        with:
          rules: dead-code, truncation, call-check, unused-variables
          scope: new                         # the default for every rule
          all-code-rules: call-check         # these judge the whole codebase
          callee-path: src
          fail-on: warning
```

* **`rules`** runs only the rules named. Left empty, every rule runs,
  including rules a later cobol-parser release adds. **`disable`** leaves
  rules out. The rule ids are listed by `cobol-parser lint --help` (under
  `--rule`).
* **`scope`** is the default for every rule:
  * `new`: a finding counts only when it is on a line the change added or
    edited (in a program, or in a copybook the change edited). A finding
    with no line counts only when its whole file is new.
  * `all`: every finding in the linted programs counts.
  * `auto` (the default): `new` on `pull_request` and `merge_group` events,
    and on a push whose previous commit is known; `all` on the first push of
    a branch, `workflow_dispatch` and `schedule`.
* **`new-code-rules`** and **`all-code-rules`** override the scope for the
  rules named (`rule` or `rule/KIND`, e.g. `io-sequence/FILE_LEFT_OPEN`).
  A typical setup holds style and hygiene rules to new code and gates real
  bugs (`call-check`, `parse`) everywhere.

When any rule judges the whole codebase, every program is linted; when all
rules judge new code, only the programs the change touched are.

The scope can live in `cobol.yml` instead, so the terminal and CI agree
([project-config.md](project-config.md)):

```yaml
lint:
  rules: [dead-code, truncation, call-check, unused-variables]
  scope:
    default: new
    call-check: all
```

An input given to the action overrides the file; `cobol.yml`'s
`lint.severity`, `lint.exclude`, `lint.baseline` and inline
`*> cobol-lint: disable=RULE` comments all still apply.

## Inputs

| Input | Default | What it does |
|---|---|---|
| `paths` | every program git tracks | files or globs to lint (`**` recurses), space, comma or new-line separated |
| `rules` | every rule | run only these rules |
| `disable` | none | never run these rules |
| `scope` | `auto` | default scope of every rule: `new`, `all` or `auto` |
| `new-code-rules` | none | rules always judged on new code only |
| `all-code-rules` | none | rules always judged on the whole codebase |
| `base-ref` | the PR's base branch, or the commit before the push | where new code starts (branch, tag or commit) |
| `fail-on` | `error` | fail the step at this severity: `error`, `warning`, `info`, `never` |
| `min-severity` | `warning` (or `lint.min_severity`) | hide findings below this severity |
| `severity` | none | re-grade rules: `dead-code=error io-sequence/FILE_LEFT_OPEN=warning` |
| `copybook-path` | `cobol.yml` | copybook folders |
| `callee-path` | `cobol.yml` | folders of CALLed programs; turns on `call-check` |
| `config` | found from `working-directory` up | a `cobol.yml` path, or `none` |
| `baseline` | none | a `--write-baseline` file of known findings to leave out |
| `working-directory` | `.` | where to run |
| `summary` | `true` | add a Markdown summary of every finding to the job summary |
| `sarif-file` | none | also write a SARIF log, for code scanning |
| `args` | none | extra `cobol-parser lint` arguments, as typed |
| `python-version` | `3.12` | Python to run on (empty: the runner's `python3`) |
| `version` | this action's own copy | a cobol-parser release from PyPI instead (one that has `lint --new-code-since`) |

Outputs: `exit-code` (0 clean, 3 a finding reached `fail-on`, 1 a file could
not be linted, 2 bad input), `scope` (`new` or `all`) and `base-ref`.

## What a run shows

* **Annotations** on the pull request diff, one per finding. GitHub shows at
  most 10 errors and 10 warnings per step on the diff, which is why
  new-code scope matters on a legacy codebase.
* **A job summary** with the totals, a count per rule and every finding
  (up to 200), plus how many were left out as outside new code, suppressed
  by comments, or in the baseline.
* **The gate**: the step fails when a counted finding reaches `fail-on`, or
  when a program could not be read or parsed.

## History and the base branch

New code is measured from the merge base of the base branch and `HEAD`.
`actions/checkout` fetches a single commit by default; the action fetches
the base branch and, if it must, the full history. `fetch-depth: 0` on the
checkout makes that one fetch. A base that still cannot be found fails the
step instead of quietly linting everything.

## Code scanning (SARIF)

```yaml
    permissions:
      contents: read
      security-events: write
    steps:
      - uses: actions/checkout@v4
        with: { fetch-depth: 0 }
      - uses: landparty/cobol-parser@main
        with:
          sarif-file: cobol-lint.sarif
      - uses: github/codeql-action/upload-sarif@v3
        if: always()
        with:
          sarif_file: cobol-lint.sarif
```

Code scanning on a private repository needs GitHub Code Security.

## The same thing without the action

```bash
cobol-parser lint --new-code-since origin/main --format github --fail-on error
cobol-parser lint --new-code-since origin/main --scope call-check=all --fail-on error
cobol-parser lint --new-code-since origin/main --scope all --scope truncation=new
cobol-parser lint --new-code-since origin/main --summary-file "$GITHUB_STEP_SUMMARY"
```

`--new-code-since REF` keeps the findings on lines added or edited since the
merge base of REF and `HEAD` (committed, staged, unstaged and untracked
changes all count), `--scope [RULE=]new|all` sets the scopes, and the JSON
report's `summary.outside_new_code` counts what the scope left out.
