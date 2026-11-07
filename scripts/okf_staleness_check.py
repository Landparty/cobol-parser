#!/usr/bin/env python3
"""OKF staleness checker — keeps .okf/ in sync with source changes.

Modes
-----
  (no args)      Claude Code PostToolUse hook: read tool JSON from stdin,
                 print a one-line reminder if the OKF file wasn't touched yet.
  --mode=git     Git pre-commit hook: check staged files and exit 1 if any
                 OKF-covered source changed without a corresponding OKF update.

Touching the right file is all this can check. Whether what the file says is
still true is ``scripts/okf_check.py``'s job (run by the same hook).
"""

import json
import subprocess
import sys
from pathlib import Path

# Modules map to the topic file that documents them, not to a folder's routing
# page: a split doc (.okf/analysis/, .okf/parser/, .okf/generators/) gets one
# entry per module so a change asks for the one file a reader would load.
#
# Longest-prefix-wins is NOT how this is matched: *every* entry whose prefix
# matches contributes, so a file may map to several OKF docs. Two rules keep
# the map honest, both learned from a real drift:
#
#   1. A directory prefix ends with "/" and therefore does NOT cover a
#      same-named module beside it -- "cobolparser/parsers/" never matched
#      "cobolparser/parser.py", so the parse orchestrator changed for months
#      without ever asking for an OKF update. Every module gets its own entry.
#   2. Every non-test .py file under cobolparser/ must match at least one
#      prefix. tests/test_okf_staleness_map.py enforces that, so a new
#      package (the way cobolparser/jcl/ arrived) cannot land undocumented.
OKF_MAP = [
    ("cobolparser/lexer.py", [".okf/lexer.md"]),
    ("cobolparser/_literals.py", [".okf/lexer.md", ".okf/parser/statements.md"]),
    ("cobolparser/_lines.py", [".okf/lexer.md", ".okf/preprocessing.md"]),
    ("cobolparser/_source_directive.py", [".okf/preprocessing.md"]),
    ("cobolparser/preprocess/", [".okf/preprocessing.md"]),
    ("cobolparser/parser.py", [".okf/parser/orchestration.md"]),
    ("cobolparser/_errors.py", [".okf/parser/orchestration.md"]),
    ("cobolparser/profiling.py", [".okf/parser/orchestration.md"]),
    ("cobolparser/core/", [".okf/parser/orchestration.md"]),
    ("cobolparser/plugins/", [".okf/parser/orchestration.md"]),
    ("cobolparser/parsers/__init__.py", [".okf/parser/statements.md"]),
    ("cobolparser/parsers/divisions/", [".okf/parser/divisions.md"]),
    ("cobolparser/parsers/statements/__init__.py", [".okf/parser/statements.md"]),
    ("cobolparser/parsers/statements/_utils.py", [".okf/parser/statements.md"]),
    ("cobolparser/parsers/statements/_conditions.py", [".okf/parser/statements.md"]),
    (
        "cobolparser/parsers/statements/call_parser.py",
        [".okf/parser/statements-control.md"],
    ),
    (
        "cobolparser/parsers/statements/entry_parser.py",
        [".okf/parser/statements-control.md"],
    ),
    (
        "cobolparser/parsers/statements/evaluate_parser.py",
        [".okf/parser/statements-control.md"],
    ),
    (
        "cobolparser/parsers/statements/exception_parsers.py",
        [".okf/parser/statements-control.md"],
    ),
    (
        "cobolparser/parsers/statements/go_parser.py",
        [".okf/parser/statements-control.md"],
    ),
    (
        "cobolparser/parsers/statements/if_parser.py",
        [".okf/parser/statements-control.md"],
    ),
    (
        "cobolparser/parsers/statements/invoke_parser.py",
        [".okf/parser/statements-control.md"],
    ),
    (
        "cobolparser/parsers/statements/legacy_verb_parsers.py",
        [".okf/parser/statements-control.md"],
    ),
    (
        "cobolparser/parsers/statements/perform_parser.py",
        [".okf/parser/statements-control.md"],
    ),
    (
        "cobolparser/parsers/statements/search_parser.py",
        [".okf/parser/statements-control.md"],
    ),
    (
        "cobolparser/parsers/statements/simple_statement_parsers.py",
        [".okf/parser/statements-control.md"],
    ),
    (
        "cobolparser/parsers/statements/stop_parser.py",
        [".okf/parser/statements-control.md"],
    ),
    (
        "cobolparser/parsers/statements/accept_parser.py",
        [".okf/parser/statements-data.md"],
    ),
    (
        "cobolparser/parsers/statements/allocate_free_parsers.py",
        [".okf/parser/statements-data.md"],
    ),
    (
        "cobolparser/parsers/statements/arithmetic_parsers.py",
        [".okf/parser/statements-data.md"],
    ),
    (
        "cobolparser/parsers/statements/display_parser.py",
        [".okf/parser/statements-data.md"],
    ),
    (
        "cobolparser/parsers/statements/initialize_inspect_parsers.py",
        [".okf/parser/statements-data.md"],
    ),
    (
        "cobolparser/parsers/statements/move_parser.py",
        [".okf/parser/statements-data.md"],
    ),
    (
        "cobolparser/parsers/statements/set_parser.py",
        [".okf/parser/statements-data.md"],
    ),
    (
        "cobolparser/parsers/statements/string_unstring_parsers.py",
        [".okf/parser/statements-data.md"],
    ),
    (
        "cobolparser/parsers/statements/xml_json_parser.py",
        [".okf/parser/statements-data.md"],
    ),
    (
        "cobolparser/parsers/statements/close_parser.py",
        [".okf/parser/statements-io.md"],
    ),
    (
        "cobolparser/parsers/statements/communication_parsers.py",
        [".okf/parser/statements-io.md"],
    ),
    (
        "cobolparser/parsers/statements/delete_parser.py",
        [".okf/parser/statements-io.md"],
    ),
    (
        "cobolparser/parsers/statements/ibm_exec_statements.py",
        [".okf/parser/statements-io.md"],
    ),
    ("cobolparser/parsers/statements/open_parser.py", [".okf/parser/statements-io.md"]),
    ("cobolparser/parsers/statements/read_parser.py", [".okf/parser/statements-io.md"]),
    (
        "cobolparser/parsers/statements/report_writer_parsers.py",
        [".okf/parser/statements-io.md"],
    ),
    (
        "cobolparser/parsers/statements/rewrite_parser.py",
        [".okf/parser/statements-io.md"],
    ),
    (
        "cobolparser/parsers/statements/sort_merge_parsers.py",
        [".okf/parser/statements-io.md"],
    ),
    (
        "cobolparser/parsers/statements/start_parser.py",
        [".okf/parser/statements-io.md"],
    ),
    (
        "cobolparser/parsers/statements/unlock_parser.py",
        [".okf/parser/statements-io.md"],
    ),
    (
        "cobolparser/parsers/statements/write_parser.py",
        [".okf/parser/statements-io.md"],
    ),
    ("cobolparser/models/", [".okf/ast-models.md"]),
    (
        "cobolparser/_storage.py",
        [".okf/ast-models.md", ".okf/generators/record-data.md"],
    ),
    ("cobolparser/analysis/__init__.py", [".okf/analysis.md"]),
    ("cobolparser/analysis/program_flow/", [".okf/analysis/flow.md"]),
    ("cobolparser/analysis/dead_code.py", [".okf/analysis/flow.md"]),
    ("cobolparser/analysis/recursion_risk.py", [".okf/analysis/flow.md"]),
    ("cobolparser/analysis/complexity.py", [".okf/analysis/flow.md"]),
    ("cobolparser/analysis/redundancy.py", [".okf/analysis/flow.md"]),
    ("cobolparser/analysis/technical_debt.py", [".okf/analysis/flow.md"]),
    ("cobolparser/analysis/_procedures.py", [".okf/analysis/flow.md"]),
    ("cobolparser/analysis/_cics.py", [".okf/analysis/flow.md"]),
    ("cobolparser/analysis/_abend.py", [".okf/analysis/flow.md"]),
    ("cobolparser/analysis/_sql_whenever.py", [".okf/analysis/flow.md"]),
    ("cobolparser/analysis/unused_variables.py", [".okf/analysis/data-use.md"]),
    ("cobolparser/analysis/xref.py", [".okf/analysis/data-use.md"]),
    ("cobolparser/analysis/move_type_checker.py", [".okf/analysis/data-use.md"]),
    ("cobolparser/analysis/linkage_checker.py", [".okf/analysis/data-use.md"]),
    ("cobolparser/analysis/io_logger.py", [".okf/analysis/data-use.md"]),
    ("cobolparser/analysis/io_sequence.py", [".okf/analysis/data-use.md"]),
    ("cobolparser/analysis/io_coverage_reporter.py", [".okf/analysis/data-use.md"]),
    ("cobolparser/analysis/io_diagnostics.py", [".okf/analysis/data-use.md"]),
    ("cobolparser/analysis/crud_matrix.py", [".okf/analysis/data-use.md"]),
    ("cobolparser/analysis/value_tracker.py", [".okf/analysis/data-use.md"]),
    ("cobolparser/analysis/_names.py", [".okf/analysis/data-use.md"]),
    ("cobolparser/analysis/_files.py", [".okf/analysis/data-use.md"]),
    ("cobolparser/analysis/host_var_resolver.py", [".okf/analysis/sql-cics-ims.md"]),
    ("cobolparser/analysis/dclgen_check.py", [".okf/analysis/sql-cics-ims.md"]),
    ("cobolparser/analysis/sql_cics_lint.py", [".okf/analysis/sql-cics-ims.md"]),
    ("cobolparser/analysis/ims_segment_analyzer.py", [".okf/analysis/sql-cics-ims.md"]),
    (
        "cobolparser/analysis/language_env_analyzer.py",
        [".okf/analysis/sql-cics-ims.md"],
    ),
    ("cobolparser/analysis/lint.py", [".okf/analysis/lint.md"]),
    ("cobolparser/analysis/bug_patterns.py", [".okf/analysis/lint.md"]),
    ("cobolparser/analysis/compiler_checks.py", [".okf/analysis/lint.md"]),
    ("cobolparser/analysis/code_patterns.py", [".okf/analysis/lint.md"]),
    ("cobolparser/analysis/sarif.py", [".okf/analysis/lint.md"]),
    ("cobolparser/analysis/field_lineage.py", [".okf/analysis/lineage.md"]),
    ("cobolparser/analysis/field_widening.py", [".okf/analysis/lineage.md"]),
    ("cobolparser/analysis/lineage_graph.py", [".okf/analysis/lineage.md"]),
    ("cobolparser/analysis/lineage_jcl.py", [".okf/analysis/lineage.md"]),
    ("cobolparser/analysis/_sql_flow.py", [".okf/analysis/lineage.md"]),
    ("cobolparser/analysis/business_rules.py", [".okf/analysis/business-rules.md"]),
    ("cobolparser/analysis/codebase.py", [".okf/analysis/codebase.md"]),
    ("cobolparser/analysis/program_signature.py", [".okf/analysis/codebase.md"]),
    ("cobolparser/analysis/call_interface.py", [".okf/analysis/codebase.md"]),
    ("cobolparser/analysis/ast_diff.py", [".okf/analysis/codebase.md"]),
    (
        "cobolparser/analysis/boundary_inventory.py",
        [".okf/analysis/fixtures-support.md"],
    ),
    ("cobolparser/analysis/constraints.py", [".okf/analysis/fixtures-support.md"]),
    ("cobolparser/analysis/domains.py", [".okf/analysis/fixtures-support.md"]),
    ("cobolparser/analysis/const_fold.py", [".okf/analysis/fixtures-support.md"]),
    (
        "cobolparser/analysis/invocation_counts.py",
        [".okf/analysis/fixtures-support.md"],
    ),
    ("cobolparser/generators/__init__.py", [".okf/generators.md"]),
    ("cobolparser/generators/flowchart.py", [".okf/generators/flowchart.md"]),
    ("cobolparser/generators/copybook_data.py", [".okf/generators/record-data.md"]),
    ("cobolparser/generators/program_fixtures.py", [".okf/generators/fixtures.md"]),
    ("cobolparser/generators/scenarios.py", [".okf/generators/fixtures.md"]),
    ("cobolparser/generators/verification.py", [".okf/generators/fixtures.md"]),
    ("cobolparser/generators/data/__init__.py", [".okf/generators/record-data.md"]),
    ("cobolparser/generators/data/options.py", [".okf/generators/record-data.md"]),
    ("cobolparser/generators/data/errors.py", [".okf/generators/record-data.md"]),
    ("cobolparser/generators/data/layout.py", [".okf/generators/record-data.md"]),
    (
        "cobolparser/generators/data/layout_offsets.py",
        [".okf/generators/record-data.md"],
    ),
    ("cobolparser/generators/data/values.py", [".okf/generators/record-data.md"]),
    ("cobolparser/generators/data/storage.py", [".okf/generators/record-data.md"]),
    ("cobolparser/generators/data/editing.py", [".okf/generators/record-data.md"]),
    ("cobolparser/generators/data/encoding.py", [".okf/generators/record-data.md"]),
    ("cobolparser/generators/data/dataset.py", [".okf/generators/record-data.md"]),
    (
        "cobolparser/generators/data/copybook.py",
        [".okf/generators/record-data.md", ".okf/generators/decode-compare.md"],
    ),
    ("cobolparser/generators/data/views.py", [".okf/generators/decode-compare.md"]),
    ("cobolparser/generators/data/decoding.py", [".okf/generators/decode-compare.md"]),
    ("cobolparser/generators/data/compare.py", [".okf/generators/decode-compare.md"]),
    ("cobolparser/generators/data/program_layout.py", [".okf/generators/fixtures.md"]),
    ("cobolparser/generators/data/bundle.py", [".okf/generators/fixtures.md"]),
    ("cobolparser/batch.py", [".okf/batch.md"]),
    ("cobolparser/scan.py", [".okf/batch.md"]),
    ("cobolparser/_facts_cache.py", [".okf/batch.md"]),
    ("cobolparser/_file_limits.py", [".okf/batch.md"]),
    ("cobolparser/cli/", [".okf/cli.md"]),
    # cli/parse.py is the entry point and top-level parser; the subcommands
    # live in cli/commands/ (one module per area) on top of cli/_common.py.
    ("cobolparser/cli/_common.py", [".okf/cli.md"]),
    ("cobolparser/cli/commands/", [".okf/cli.md"]),
    (
        "cobolparser/cli/commands/analyze.py",
        [".okf/cli.md", ".okf/analysis/data-use.md"],
    ),
    (
        "cobolparser/cli/commands/data.py",
        [".okf/cli.md", ".okf/generators/fixtures.md"],
    ),
    ("cobolparser/config/", [".okf/cli.md"]),
    # The tool modules (CobolTools mixins, the JCL tools), one per area.
    ("cobolparser/mcp/tools/", [".okf/mcp.md"]),
    ("cobolparser/mcp/", [".okf/mcp.md"]),
    ("cobolparser/__main__.py", [".okf/cli.md"]),
    (
        "cobolparser/dialects/le_signatures.py",
        [".okf/dialects.md", ".okf/analysis/sql-cics-ims.md"],
    ),
    ("cobolparser/dialects/", [".okf/dialects.md"]),
    ("cobolparser/jcl/", [".okf/jcl.md"]),
    ("cobolparser/definitions/", [".okf/definitions.md"]),
    ("cobolparser/__init__.py", [".okf/index.md"]),
    ("tests/", [".okf/tests.md"]),
]


def _get_okf_files(rel_path: str) -> list:
    seen: set = set()
    result = []
    for prefix, okf_files in OKF_MAP:
        if rel_path.startswith(prefix) or rel_path == prefix.rstrip("/"):
            for f in okf_files:
                if f not in seen:
                    seen.add(f)
                    result.append(f)
    return result


def _git(args, cwd):
    r = subprocess.run(["git"] + args, cwd=cwd, capture_output=True, text=True)
    return r.stdout.strip()


def _is_okf_modified(okf_file: str, repo_root: Path) -> bool:
    return bool(_git(["status", "--porcelain", okf_file], repo_root))


def _git_mode(repo_root: Path) -> int:
    staged_raw = _git(["diff", "--cached", "--name-only"], repo_root)
    staged = {f.strip() for f in staged_raw.splitlines() if f.strip()}

    needs_update: dict = {}
    for src in staged:
        if src.startswith("docs/") or src.startswith(".okf/"):
            continue
        for okf_file in _get_okf_files(src):
            if okf_file not in staged:
                needs_update.setdefault(okf_file, set()).add(src)

    if not needs_update:
        return 0

    print("OKF staleness warning — update these docs before committing:")
    for okf_file in sorted(needs_update):
        triggers = ", ".join(sorted(needs_update[okf_file]))
        print(f"  {okf_file}  (changed by: {triggers})")
    print()
    print("To bypass: git commit --no-verify")
    return 1


def _claude_mode(repo_root: Path) -> int:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    file_path = (data.get("tool_input") or {}).get("file_path", "")
    if not file_path:
        return 0

    try:
        rel = Path(file_path).relative_to(repo_root).as_posix()
    except ValueError:
        rel = file_path.replace("\\", "/")
        for marker in ("cobolparser/", "tests/", "docs/"):
            idx = rel.find(marker)
            if idx != -1:
                rel = rel[idx:]
                break

    if rel.startswith("docs/") or rel.startswith(".okf/"):
        return 0

    okf_files = _get_okf_files(rel)
    stale = [f for f in okf_files if not _is_okf_modified(f, repo_root)]
    for f in stale:
        print(f"[OKF] {rel} — consider updating {f}")

    return 0


def main():
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return 0
    repo_root = Path(result.stdout.strip())

    if "--mode=git" in sys.argv:
        return _git_mode(repo_root)
    return _claude_mode(repo_root)


if __name__ == "__main__":
    sys.exit(main())
