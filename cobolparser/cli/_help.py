"""The top-level ``cobol-parser --help`` screen and command-name suggestions.

argparse lists subcommands as one flat block in registration order, which at
40+ commands buries the three a new user needs. The top-level parser prints
them grouped by task instead (:data:`COMMAND_GROUPS`), followed by a quick
start, the exit-code convention and where defaults come from. Each
subcommand's own ``--help`` is untouched.

``tests/unit/cli/test_cli_help_overview.py`` pins that every registered
subcommand sits in exactly one group, so a new subcommand cannot be left out
of the overview.
"""

from __future__ import annotations

import argparse
import difflib

#: ``(group title, ((command, one-line summary), ...))``, in display order.
COMMAND_GROUPS: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = (
    (
        "Parse and preprocess",
        (
            ("parse", "parse one program to AST JSON (the default command)"),
            ("batch", "parse many programs in parallel"),
            ("expand", "expand COPY statements (copybooks)"),
            ("preprocess", "fixed-format source to free-form text"),
            ("tokenize", "the lexer's token stream"),
        ),
    ),
    (
        "Lint and CI",
        (
            ("lint", "run every checker in one pass (text, json, sarif, github)"),
            ("scan", "run analyzers over a whole source tree, with a cache"),
            ("config", "show the effective cobol.yml and where it came from"),
        ),
    ),
    (
        "Analyze one program",
        (
            ("dead-code", "unreachable paragraphs and sections"),
            ("unused-variables", "data items never referenced"),
            ("program-flow", "control-flow graph (PERFORM, GO TO, CALL)"),
            ("recursion-check", "PERFORM / GO TO cycles, recursive CALLs"),
            ("complexity", "cyclomatic complexity per paragraph"),
            ("health", "composite technical-debt score"),
            ("redundancy", "dead code, unused data and duplicated paragraphs"),
            ("io-sequence", "OPEN / READ / WRITE / CLOSE ordering"),
            ("move-type-check", "MOVE category compatibility"),
            ("linkage-check", "LINKAGE items vs CALL / ENTRY USING"),
            ("sql-cics-check", "embedded SQL and CICS pitfalls"),
            ("dclgen-check", "SQL host variables vs DCLGEN columns"),
            ("analyze", "dynamic CALL targets"),
            ("language-env", "intrinsic functions and LE service calls"),
            ("ims-dli", "IMS DL/I segment references"),
            ("data-items", "byte offsets, lengths, REDEFINES, level-88s"),
            ("program-signature", "a program's calling interface"),
            ("xref", "cross-reference listing of every symbol"),
            ("business-rules", "decisions, validations and calculations"),
            ("lineage", "field-level data flow inside one program"),
            ("diff", "what changed in behavior between two versions"),
        ),
    ),
    (
        "Analyze a codebase",
        (
            ("codebase-graph", "CALL / LINK / XCTL and copybook graphs"),
            ("copybook-impact", "every program a copybook change reaches"),
            ("call-check", "CALL arguments vs the callee's interface"),
            ("field-impact", "where a field's value flows across programs"),
            ("widen-check", "what a PICTURE change breaks"),
            ("jcl", "which program each JCL step runs, DD -> dataset"),
        ),
    ),
    (
        "Test data",
        (
            ("gen-data", "synthetic CSV rows from a copybook layout"),
            ("decode", "decode a record image / EBCDIC file via a copybook"),
            ("compare", "compare two record files field by field"),
            ("gen-fixtures", "boundary mocks and asserts for a program"),
        ),
    ),
    (
        "Reference and integrations",
        (
            ("le-info", "signature of an LE service or intrinsic function"),
            ("mcp", "serve the analyzers to AI agents over MCP"),
        ),
    ),
)

QUICK_START = """\
Quick start:
  cobol-parser parse PROG.cbl --copybook-path ./copybooks -o prog.json
  cobol-parser lint src/*.cbl --format text --fail-on error
  cobol-parser dead-code PROG.cbl
  cobol-parser copybook-impact CUSTREC src/ --copybook-path ./copybooks
  cobol-parser <command> --help        every flag of one command, with examples"""

EXIT_CODES = """\
Exit codes:
  0  success (analyzer findings alone never fail a run)
  1  a file could not be read, parsed or written
  2  the command line was rejected, or the run finished but some input
     only partly parsed or failed (output is still written; see stderr)
  3  a gate tripped: --fail-on (lint, widen-check, call-check) or
     jcl --strict
  compare is the exception: 1 means "the files differ", 2 a failed run"""

DEFAULTS = """\
Defaults:
  A cobol.yml (or cobol.yaml) in the current directory or a parent supplies
  copybook paths, defines and per-command defaults; flags always win.
  See it with 'cobol-parser config'; skip it with --no-config."""


def overview_text() -> str:
    """The grouped command list shown by ``cobol-parser --help``."""
    width = max(len(name) for _, cmds in COMMAND_GROUPS for name, _ in cmds)
    lines: list[str] = ["Commands:"]
    for title, commands in COMMAND_GROUPS:
        lines.append(f"  {title}:")
        for name, summary in commands:
            lines.append(f"    {name.ljust(width)}  {summary}")
    return "\n".join(lines)


def suggest_command(word: str, known: frozenset[str] | set[str]) -> str | None:
    """The registered command *word* is most likely a typo of, if any."""
    matches = difflib.get_close_matches(word.lower(), sorted(known), n=1, cutoff=0.6)
    return matches[0] if matches else None


class TopLevelParser(argparse.ArgumentParser):
    """``cobol-parser`` itself: the subcommand list is printed grouped.

    Only the help screen changes. The subparsers action keeps every choice
    (``scripts/okf_check.py`` reads them to generate the CLI table), it is
    just not printed as argparse's flat ``{parse,batch,...}`` block.
    """

    def format_help(self) -> str:
        formatter = self._get_formatter()
        formatter.add_usage(self.usage, self._actions, self._mutually_exclusive_groups)
        formatter.add_text(self.description)
        formatter.add_text(overview_text())
        for group in self._action_groups:
            actions = [
                a
                for a in group._group_actions
                if not isinstance(a, argparse._SubParsersAction)
            ]
            if not actions:
                continue
            formatter.start_section(group.title)
            formatter.add_arguments(actions)
            formatter.end_section()
        formatter.add_text(QUICK_START)
        formatter.add_text(EXIT_CODES)
        formatter.add_text(DEFAULTS)
        return formatter.format_help()


def grouped_command_names() -> list[str]:
    """Every command named in :data:`COMMAND_GROUPS`, in display order."""
    return [name for _, commands in COMMAND_GROUPS for name, _ in commands]
