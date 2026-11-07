"""The `cobol-parser` entry point: builds the top-level parser and dispatches
to the subcommands in `cli/commands/`."""

from __future__ import annotations

import argparse
import os
import sys
from typing import NoReturn

from ..config import ConfigError, ProjectConfig, load_project_config
from . import _help, _project_config
from ._common import _fail
from .commands.analyze import (
    _add_analyzer,
    _build_business_rules_parser,
    _build_le_info_parser,
    _build_program_flow_parser,
    _build_redundancy_parser,
    _build_unused_variables_parser,
)
from .commands.codebase import (
    _build_call_check_parser,
    _build_codebase_graph_parser,
    _build_copybook_impact_parser,
    _build_diff_parser,
    _build_scan_parser,
)
from .commands.data import (
    _build_compare_parser,
    _build_decode_parser,
    _build_gen_data_parser,
    _build_gen_fixtures_parser,
    _compare_fail,
)
from .commands.jcl import _build_jcl_parser
from .commands.lineage import (
    _build_field_impact_parser,
    _build_lineage_parser,
    _build_widen_check_parser,
)
from .commands.lint import _build_lint_parser
from .commands.project import _build_config_parser, _build_mcp_parser
from .commands.source import (
    _build_batch_parser,
    _build_expand_parser,
    _build_parse_parser,
    _build_preprocess_parser,
    _build_tokenize_parser,
)

_SUBCOMMANDS = frozenset(
    {
        "parse",
        "batch",
        "tokenize",
        "preprocess",
        "expand",
        "gen-data",
        "gen-fixtures",
        "decode",
        "compare",
        "dclgen-check",
        "analyze",
        "lint",
        "dead-code",
        "unused-variables",
        "program-flow",
        "recursion-check",
        "complexity",
        "health",
        "redundancy",
        "scan",
        "io-sequence",
        "move-type-check",
        "linkage-check",
        "language-env",
        "ims-dli",
        "data-items",
        "le-info",
        "program-signature",
        "xref",
        "diff",
        "codebase-graph",
        "copybook-impact",
        "call-check",
        "sql-cics-check",
        "business-rules",
        "lineage",
        "field-impact",
        "widen-check",
        "jcl",
        "config",
        "mcp",
    }
)


# -- Top-level parser with subcommands ----------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    from .. import __version__

    parser = _help.TopLevelParser(
        prog="cobol-parser",
        usage="cobol-parser <command> [options] FILE ...",
        description="Parse, tokenize, preprocess, and analyze COBOL source files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    # Declared for --help only. main() strips both out of argv before
    # argparse runs (see _project_config.extract_config_flags), so they work
    # on either side of the subcommand and cannot be mistaken for a source
    # file by the legacy "prepend parse" rewrite below.
    parser.add_argument(
        "--config", metavar="FILE", default=None, help=_project_config.CONFIG_FLAG_HELP
    )
    parser.add_argument(
        "--no-config",
        action="store_true",
        help=_project_config.NO_CONFIG_FLAG_HELP,
    )
    subparsers = parser.add_subparsers(
        dest="command", metavar="<command>", prog="cobol-parser"
    )

    _build_parse_parser(subparsers)
    _build_batch_parser(subparsers)
    _build_tokenize_parser(subparsers)
    _build_preprocess_parser(subparsers)
    _build_expand_parser(subparsers)
    _build_gen_data_parser(subparsers)
    _build_decode_parser(subparsers)
    _build_compare_parser(subparsers)
    _build_gen_fixtures_parser(subparsers)
    _add_analyzer(subparsers, "analyze")
    _add_analyzer(subparsers, "dead-code")
    _build_unused_variables_parser(subparsers)
    _build_program_flow_parser(subparsers)
    _add_analyzer(subparsers, "recursion-check")
    _add_analyzer(subparsers, "complexity")
    _add_analyzer(subparsers, "health")
    _add_analyzer(subparsers, "io-sequence")
    _add_analyzer(subparsers, "move-type-check")
    _add_analyzer(subparsers, "linkage-check")
    _add_analyzer(subparsers, "language-env")
    _add_analyzer(subparsers, "ims-dli")
    _add_analyzer(subparsers, "dclgen-check")
    _build_redundancy_parser(subparsers)
    _build_scan_parser(subparsers)
    _build_lint_parser(subparsers)
    _add_analyzer(subparsers, "data-items")
    _add_analyzer(subparsers, "program-signature")
    _add_analyzer(subparsers, "xref")
    _build_diff_parser(subparsers)
    _build_codebase_graph_parser(subparsers)
    _build_copybook_impact_parser(subparsers)
    _build_call_check_parser(subparsers)
    _add_analyzer(subparsers, "sql-cics-check")
    _build_business_rules_parser(subparsers)
    _build_lineage_parser(subparsers)
    _build_field_impact_parser(subparsers)
    _build_widen_check_parser(subparsers)
    _build_jcl_parser(subparsers)
    _build_le_info_parser(subparsers)
    _build_config_parser(subparsers)
    _build_mcp_parser(subparsers)

    return parser


def _config_fail(message: str, argv: list[str]) -> NoReturn:
    """A config error before the subcommand ran.

    Exit 1 like every other failure -- except for ``compare``, whose exit 1
    means "the files differ": a CI gate reading that status would report a
    missing or malformed ``cobol.yml`` as a data regression.
    """
    subcommand = next((arg for arg in argv if not arg.startswith("-")), None)
    if subcommand == "compare":
        _compare_fail(message)
    _fail(message)


def _warn_missing_search_dirs(args: argparse.Namespace, config: ProjectConfig) -> None:
    """Warn once per ``--copybook-path`` / ``--callee-path`` / ``--proc-path``
    entry typed on the command line that is not a directory.

    A typo there was silently accepted and only showed up later as COPY
    statements that were "not found". Entries that came from cobol.yml are
    already reported by name (with the file) in :func:`main`.
    """
    from_config = {
        entry
        for entries in (config.copybook_path, config.callee_path, config.proc_path)
        for entry in entries
    }
    for dest, flag in (
        ("copybook_path", "--copybook-path"),
        ("callee_path", "--callee-path"),
        ("proc_path", "--proc-path"),
    ):
        value = getattr(args, dest, None)
        entries = [value] if isinstance(value, str) else list(value or [])
        for entry in entries:
            if entry in from_config or os.path.isdir(entry):
                continue
            print(
                f"warning: {flag} {entry} is not an existing directory", file=sys.stderr
            )


def _reject_mistyped_command(word: str) -> None:
    """Exit 2 when *word* reads as a typo of a command, not a file name.

    The legacy ``cobol-parser FILE`` form means any unknown first word is
    taken as a source file, so ``cobol-parser dead-cod x.cbl`` used to say
    "File not found: dead-cod". A word that exists on disk, or has a path
    separator or an extension, is still a file.
    """
    if os.path.exists(word) or os.sep in word or "/" in word or "." in word:
        return
    suggestion = _help.suggest_command(word, _SUBCOMMANDS)
    if suggestion is None:
        return
    print(
        f"error: unknown command '{word}' (did you mean '{suggestion}'?)\n"
        "Run 'cobol-parser --help' to list every command.",
        file=sys.stderr,
    )
    sys.exit(2)


def main() -> None:
    argv = sys.argv[1:]

    # --config/--no-config are pulled out first so they may appear on either
    # side of the subcommand, and so the legacy rewrite below cannot mistake
    # a config path for a source file.
    try:
        argv, config_path, config_disabled = _project_config.extract_config_flags(argv)
    except ConfigError as exc:
        _config_fail(str(exc), argv)

    if not argv:
        # A bare `cobol-parser` used to fall through to `parse` and print
        # only "the following arguments are required: file". Show the grouped
        # command overview instead; still a usage error (exit 2).
        _build_parser().print_help()
        sys.exit(2)

    # Backward compatibility: if the first non-flag argument is not a known
    # subcommand, assume the user is using the legacy syntax and prepend "parse".
    first_positional = next((arg for arg in argv if not arg.startswith("-")), None)
    if first_positional is not None and first_positional not in _SUBCOMMANDS:
        _reject_mistyped_command(first_positional)
        argv = ["parse", *argv]
    elif first_positional is None and not {"-h", "--help", "--version"} & set(argv):
        argv = ["parse", *argv]

    parser = _build_parser()
    args = parser.parse_args(argv)

    # Loaded even when nothing is found (an all-default ProjectConfig), so
    # `cobol-parser config` can report the "no file anywhere" case, and so a
    # malformed file is an error naming it rather than a silent fallback.
    if config_disabled:
        config = ProjectConfig()
    else:
        try:
            config = load_project_config(path=config_path)
        except ConfigError as exc:
            _config_fail(str(exc), argv)
    args._project_config = config
    # `mcp` searches for cobol.yml from its --root, not the cwd, unless the
    # user named a file or turned config off.
    args._config_explicit = config_path is not None or config_disabled

    if config.source is not None:
        # The second parse (see cli/_project_config) is what separates a flag
        # the user typed from one that merely defaulted; it only runs when
        # there is a config file with something to say.
        args_provided = _project_config.provided_dests(_build_parser, argv)
        _project_config.apply_project_config(args, config, args_provided)
        for key in _project_config.unapplied_parse_settings(args, config):
            # Silently dropped before: the subcommand then analysed a
            # different program than the single-file ones do (#324).
            print(
                f"warning: {config.source} sets {key}, but "
                f"`{getattr(args, 'command', None) or 'parse'}` has no flag "
                "for it and parses without it",
                file=sys.stderr,
            )
        for key, missing in config.missing_directories():
            # Only for a path this run actually takes from the file: one the
            # subcommand reads and the user did not override (#550).
            dest = key.split(".", 1)[1]
            if hasattr(args, dest) and dest not in args_provided:
                print(
                    f"warning: {config.source} {key} entry {missing} is not "
                    "an existing directory",
                    file=sys.stderr,
                )

    _warn_missing_search_dirs(args, config)

    if not hasattr(args, "func"):
        parser.print_help()
        sys.exit(1)

    try:
        args.func(args)
    except BrokenPipeError:
        # The reader went away (`cobol-parser parse x.cbl | head`): stop
        # quietly, the way a shell tool killed by SIGPIPE does, instead of a
        # traceback -- and point stdout at devnull so the interpreter's own
        # final flush cannot raise the same error again at exit.
        try:
            devnull = os.open(os.devnull, os.O_WRONLY)
            os.dup2(devnull, sys.stdout.fileno())
        except (OSError, ValueError):
            pass
        sys.exit(141)  # 128 + SIGPIPE, what the shell reports for `yes | head`


if __name__ == "__main__":
    main()
