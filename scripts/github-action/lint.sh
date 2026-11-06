#!/usr/bin/env bash
# The "Lint COBOL" step of action.yml: turns the action's inputs (IN_*) and
# the triggering event into one `cobol-parser lint` command, makes sure git
# history reaches the new-code base, runs it, and reports its exit code.
#
# Inputs arrive as environment variables, never spliced into the script, so
# a branch name or input value cannot inject shell code.
set -uo pipefail

note() { echo "::notice title=cobol-lint::$*"; }
warn() { echo "::warning title=cobol-lint::$*"; }

# "a, b\nc" -> one word per entry.
split() { tr ',\n' '  ' <<<"${1:-}"; }

lint=(python3 -m cobolparser lint --format github)

# -- what to lint -------------------------------------------------------------
for item in $(split "${IN_PATHS:-}"); do
  case "$item" in
    *'*'* | *'?'* | *'['*) lint+=(--glob "$item") ;;
    *) lint+=("$item") ;;
  esac
done
for rule in $(split "${IN_RULES:-}"); do lint+=(--rule "$rule"); done
for rule in $(split "${IN_DISABLE:-}"); do lint+=(--disable "$rule"); done
for entry in $(split "${IN_SEVERITY:-}"); do lint+=(--severity "$entry"); done
for dir in $(split "${IN_COPYBOOK_PATH:-}"); do lint+=(--copybook-path "$dir"); done
for dir in $(split "${IN_CALLEE_PATH:-}"); do lint+=(--callee-path "$dir"); done
[ -n "${IN_FAIL_ON:-}" ] && lint+=(--fail-on "$IN_FAIL_ON")
[ -n "${IN_MIN_SEVERITY:-}" ] && lint+=(--min-severity "$IN_MIN_SEVERITY")
[ -n "${IN_BASELINE:-}" ] && lint+=(--baseline "$IN_BASELINE")
case "${IN_CONFIG:-}" in
  "") ;;
  none) lint+=(--no-config) ;;
  *) lint+=(--config "$IN_CONFIG") ;;
esac

# -- where new code starts ----------------------------------------------------
base="${IN_BASE_REF:-}"
if [ -z "$base" ]; then
  case "${EVENT_NAME:-}" in
    pull_request | pull_request_target)
      [ -n "${PR_BASE:-}" ] && base="origin/$PR_BASE" ;;
    merge_group)
      base="${MERGE_GROUP_BASE:-}" ;;
    push)
      # A new branch or a first push has no previous commit (all zeros).
      if [ -n "${PUSH_BEFORE:-}" ] && [ -n "${PUSH_BEFORE//0/}" ]; then
        base="$PUSH_BEFORE"
      fi ;;
  esac
fi

scope="${IN_SCOPE:-auto}"
no_base=false
case "$scope" in
  auto)
    if [ -n "$base" ]; then
      scope=new
    else
      scope=all
      no_base=true
      note "no base commit on a ${EVENT_NAME:-} event: every rule is judged on the whole codebase"
    fi ;;
  new | all) ;;
  *) echo "::error title=cobol-lint::scope must be auto, new or all, not '$scope'"; exit 2 ;;
esac

new_rules=$(split "${IN_NEW_RULES:-}")
all_rules=$(split "${IN_ALL_RULES:-}")
$no_base && new_rules=""
needs_base=false
if [ "$scope" = new ] || [ -n "${new_rules// /}" ]; then needs_base=true; fi

# Make the base and its merge base with HEAD reachable: actions/checkout
# fetches one commit by default.
reach_base() {
  local ref="$1"
  if ! git rev-parse --verify --quiet "$ref^{commit}" >/dev/null; then
    case "$ref" in
      origin/*)
        git fetch --no-tags --quiet origin \
          "+refs/heads/${ref#origin/}:refs/remotes/origin/${ref#origin/}" 2>/dev/null || true ;;
      *) git fetch --no-tags --quiet origin "$ref" 2>/dev/null || true ;;
    esac
  fi
  if ! git merge-base "$ref" HEAD >/dev/null 2>&1 \
    && [ "$(git rev-parse --is-shallow-repository 2>/dev/null)" = true ]; then
    note "fetching full history to find where HEAD left $ref (set fetch-depth: 0 on actions/checkout to skip this)"
    git fetch --no-tags --quiet --unshallow origin 2>/dev/null || true
    case "$ref" in
      origin/*)
        git fetch --no-tags --quiet origin \
          "+refs/heads/${ref#origin/}:refs/remotes/origin/${ref#origin/}" 2>/dev/null || true ;;
    esac
  fi
  git merge-base "$ref" HEAD >/dev/null 2>&1
}

if $needs_base; then
  if [ -z "$base" ]; then
    echo "::error title=cobol-lint::new code needs a base to compare with, and a ${EVENT_NAME:-} event has none: set base-ref, or scope: all"
    exit 2
  elif ! reach_base "$base"; then
    echo "::error title=cobol-lint::cannot find where HEAD left $base: check base-ref, or check out with fetch-depth: 0"
    exit 1
  fi
fi

if [ "$scope" = new ] || [ -n "${new_rules// /}" ]; then
  lint+=(--new-code-since "$base" --scope "$scope")
  for rule in $new_rules; do lint+=(--scope "$rule=new"); done
  for rule in $all_rules; do lint+=(--scope "$rule=all"); done
else
  base=""
  # Nothing to compare with: every rule is judged on everything linted. With
  # no paths, "since HEAD, every rule on all code" lints every program git
  # tracks (copybook folders left out), as a pull request run picks from.
  if [ -z "$(split "${IN_PATHS:-}" | tr -d ' ')" ]; then
    lint+=(--new-code-since HEAD --scope all)
  fi
fi

if [ "${IN_SUMMARY:-true}" = true ] && [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
  lint+=(--summary-file "$GITHUB_STEP_SUMMARY")
fi

extra=()
if [ -n "${IN_ARGS:-}" ]; then
  # Word-split on purpose: extra arguments as a user would type them.
  read -r -a extra <<<"$IN_ARGS"
fi

echo "cobol-lint: scope=$scope${base:+ base=$base}"
echo "+ ${lint[*]} ${extra[*]:-}"
"${lint[@]}" "${extra[@]}"
code=$?

if [ -n "${IN_SARIF:-}" ]; then
  # Same selection and scope, as a SARIF log; never the gate itself.
  python3 - "$IN_SARIF" "${lint[@]}" "${extra[@]}" <<'PY' || warn "could not write the SARIF log"
import subprocess, sys
out, argv = sys.argv[1], sys.argv[2:]
cleaned, drop_next = [], False
for index, arg in enumerate(argv):
    if drop_next:
        drop_next = False
        continue
    if arg in ("--summary-file", "--fail-on"):
        drop_next = True
        continue
    if index and argv[index - 1] == "--format":
        arg = "sarif"
    cleaned.append(arg)
sys.exit(subprocess.run(cleaned + ["--fail-on", "never", "-o", out]).returncode)
PY
fi

{
  echo "exit-code=$code"
  echo "scope=$scope"
  echo "base-ref=$base"
} >>"${GITHUB_OUTPUT:-/dev/null}"

case "$code" in
  0) ;;
  3) echo "::error title=cobol-lint::a finding reached fail-on=${IN_FAIL_ON:-}" ;;
  1) echo "::error title=cobol-lint::a file could not be linted (see the log above)" ;;
esac
exit "$code"
