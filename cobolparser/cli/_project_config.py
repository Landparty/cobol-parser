"""Merging ``cobol.yml`` into parsed CLI arguments.

Precedence is **explicit CLI flag > config file > built-in default**, and
this module is the single place that merge happens, so every subcommand
keeps reading ``args.copybook_path`` (and friends) unchanged.

The hard part is telling "the user passed ``--charset ascii``" apart from
"``--charset`` defaulted to ascii" -- most of this CLI's flags have a
non-``None`` default, so a plain ``is None`` test cannot distinguish them.
Rather than rewrite 65 ``add_argument`` calls to default to ``None``, this
module parses the same argv a second time against a throwaway parser whose
optional-argument defaults have been replaced with a sentinel: whatever
comes back as the sentinel is a flag the user did **not** type. That second
parse only runs when a config file was actually found, so a user without one
pays nothing for it.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from ..config import ConfigError, ProjectConfig

__all__ = [
    "CONFIG_FLAG_HELP",
    "apply_project_config",
    "extract_config_flags",
    "provided_dests",
    "unapplied_parse_settings",
]


class _Unset:
    """Sentinel for "this option did not appear in argv"."""

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return "<unset>"


_UNSET = _Unset()

CONFIG_FLAG_HELP = (
    "Read project defaults from FILE instead of searching for a "
    "cobol.yml/cobol.yaml upward from the current directory. May appear "
    "anywhere on the command line."
)

NO_CONFIG_FLAG_HELP = (
    "Ignore any cobol.yml/cobol.yaml entirely and use only flags and "
    "built-in defaults. May appear anywhere on the command line."
)


# Each entry maps an argparse ``dest`` to the config value that fills it when
# the user did not pass the corresponding flag. Returning ``None`` means the
# config says nothing about it, leaving the built-in default in place.
#
# Only genuinely project-level settings appear here. Per-invocation choices
# (--program, --output, --format, --compact, ...) stay flags: putting them in
# a shared file would make two people in the same repo get different output
# from the same command.
_BINDINGS: dict[str, Callable[[ProjectConfig], Any]] = {
    "copybook_path": lambda c: list(c.copybook_path) or None,
    "callee_path": lambda c: list(c.callee_path) or None,
    "proc_path": lambda c: list(c.proc_path) or None,
    "source_format": lambda c: c.source_format,
    "debug_lines": lambda c: c.debug_lines,
    "dialect": lambda c: c.dialect,
    "error_recovery": lambda c: c.error_recovery,
    "seed": lambda c: c.seed,
    # `--extension` and `--rule` below declare a dest that is not their flag
    # name; these keys are argparse dests, not flag spellings.
    "extensions": lambda c: list(c.extensions) or None,
    "define": lambda c: list(c.define) or None,
    "charset": lambda c: c.data.charset,
    "endian": lambda c: c.data.endian,
    "record_format": lambda c: c.data.record_format,
    "record_separator": lambda c: c.data.record_separator,
    "rows": lambda c: c.data.rows,
    "rules": lambda c: list(c.lint.rules) or None,
    "min_severity": lambda c: c.lint.min_severity,
    "fail_on": lambda c: c.lint.fail_on,
    "disable": lambda c: list(c.lint.disable) or None,
    "severity_overrides": lambda c: dict(c.lint.severity) or None,
    "exclude": lambda c: list(c.lint.exclude) or None,
    "baseline": lambda c: c.lint.baseline,
}


def extract_config_flags(argv: list[str]) -> tuple[list[str], Path | None, bool]:
    """Pull ``--config FILE`` / ``--config=FILE`` / ``--no-config`` out of argv.

    Handled before argparse rather than as ordinary arguments so they can
    appear either side of the subcommand, and -- more importantly -- so
    ``main()``'s legacy "first positional isn't a subcommand, so prepend
    parse" rewrite does not mistake a config path for a source file.

    Returns the remaining argv, the explicit config path (if any), and
    whether config loading was switched off.
    """
    remaining: list[str] = []
    path: Path | None = None
    disabled = False
    index = 0
    while index < len(argv):
        arg = argv[index]
        if arg == "--no-config":
            disabled = True
        elif arg == "--config":
            if index + 1 >= len(argv):
                raise ConfigError("--config requires a file path")
            path = Path(argv[index + 1])
            index += 1
        elif arg.startswith("--config="):
            value = arg[len("--config=") :]
            if not value:
                raise ConfigError("--config requires a file path")
            path = Path(value)
        elif _abbreviates_config_flag(arg):
            raise ConfigError(
                f"{arg.split('=', 1)[0]} could be an abbreviation of --config or "
                "--no-config, which are only recognised spelled out in full"
            )
        else:
            remaining.append(arg)
        index += 1
    if disabled and path is not None:
        raise ConfigError("--config and --no-config cannot be used together")
    return remaining, path, disabled


def _abbreviates_config_flag(arg: str) -> bool:
    """True for ``--no-conf``, ``--no``, ``--conf=FILE`` and the like.

    Only the exact spellings above are stripped, so a shortened one would
    otherwise reach argparse, whose prefix matching may take it for some
    *other* option of the subcommand (``--no`` for ``--no-debug-lines``)
    while the discovered cobol.yml quietly stays in force. Rejected here
    rather than with ``allow_abbrev=False`` on every subparser, which would
    also take away abbreviations that cannot be mistaken for these two.
    """
    if not arg.startswith("--"):
        return False
    name = arg[2:].split("=", 1)[0]
    return bool(name) and any(
        flag.startswith(name) and flag != name for flag in ("config", "no-config")
    )


def _iter_parsers(parser: argparse.ArgumentParser) -> Iterator[argparse.ArgumentParser]:
    """Every parser in the tree, subparsers included, each yielded once.

    Reaches into argparse's ``_actions`` / ``_SubParsersAction.choices``
    because there is no public way to enumerate a parser's subparsers. Both
    have been stable across every Python release this package supports, and
    the alternative -- threading a registry through 40-odd builder functions
    -- would put the same knowledge in 40 places instead of one.
    """
    seen: set[int] = set()

    def walk(current: argparse.ArgumentParser) -> Iterator[argparse.ArgumentParser]:
        if id(current) in seen:
            return
        seen.add(id(current))
        yield current
        for action in current._actions:
            if isinstance(action, argparse._SubParsersAction):
                for sub in action.choices.values():
                    yield from walk(sub)

    yield from walk(parser)


def _strip_defaults(parser: argparse.ArgumentParser) -> None:
    """Replace every optional argument's default with a sentinel.

    ``append`` actions get ``None`` instead: argparse's append
    implementation copies and appends to whatever the default is, so a
    non-list sentinel there would raise the moment the flag is used. ``None``
    serves the same purpose for them, since no command line can produce it.
    """
    for sub in _iter_parsers(parser):
        for action in sub._actions:
            if not action.option_strings:
                continue  # positional: always present, never config-filled
            if action.default is argparse.SUPPRESS:
                continue  # --help / --version
            if isinstance(action, argparse._AppendAction):
                action.default = None
            else:
                action.default = _UNSET


def provided_dests(
    build_parser: Callable[[], argparse.ArgumentParser], argv: list[str]
) -> set[str]:
    """The argparse ``dest``s the user actually typed a flag for.

    ``build_parser`` is called to get a *fresh* parser -- the defaults are
    stripped destructively, and the parser that produced the real namespace
    must be left intact.
    """
    parser = build_parser()
    _strip_defaults(parser)
    namespace = parser.parse_args(argv)
    return {
        dest
        for dest, value in vars(namespace).items()
        if value is not _UNSET and value is not None
    }


def apply_project_config(
    args: argparse.Namespace, config: ProjectConfig, provided: set[str]
) -> None:
    """Fill every config-backed argument the user did not pass explicitly.

    Mutates ``args`` in place. Arguments the running subcommand does not
    define are skipped, so this is safe to call for every subcommand.
    """
    for dest, read in _BINDINGS.items():
        if dest in provided or not hasattr(args, dest):
            continue
        if dest == "source_format" and "free_form" in provided:
            # --free-form is the legacy spelling of the same setting, and
            # _source_format_kwargs() reads --source-format first. Letting
            # the config fill source_format here would silently override a
            # layout the user stated on the command line.
            continue
        value = read(config)
        if value is not None:
            setattr(args, dest, value)


# The settings that change *which program* a COBOL-parsing subcommand sees,
# each with the argparse dest that would apply it and the value at which it
# changes nothing (so a config stating the default draws no warning).
# ``dialect`` is not here: there is one dialect, so it can change nothing.
_PARSE_SETTINGS: tuple[tuple[str, str, Callable[[ProjectConfig], bool]], ...] = (
    ("project.define", "define", lambda c: bool(c.define)),
    (
        "project.source_format",
        "source_format",
        lambda c: c.source_format not in (None, "auto"),
    ),
    ("project.debug_lines", "debug_lines", lambda c: bool(c.debug_lines)),
)

#: Dests whose presence marks a subcommand as one that parses COBOL source.
#: ``config``, ``le-info``, ``jcl`` and ``mcp`` have none of them and are
#: never warned about.
_PARSES_COBOL = frozenset({"define", "source_format", "debug_lines", "copybook_path"})

#: Subcommands that read copybooks for their data layout, or only inline
#: them, where auto-detection settles the source format and a stated
#: ``project.source_format`` almost never changes the result. Warning about
#: it on every run there only trained users to ignore stderr, so only the
#: ``define`` warning (which can change a layout) is kept for them (#324).
_SOURCE_FORMAT_NOT_WARNED = frozenset({"decode", "compare", "gen-data", "expand"})


def unapplied_parse_settings(
    args: argparse.Namespace, config: ProjectConfig
) -> list[str]:
    """The cobol.yml keys that would change the parsed program but that the
    running subcommand has no flag for -- ``apply_project_config`` skips
    those, and skipping them silently made e.g. ``batch`` parse a different
    program than ``parse`` did (#324). Empty for a subcommand that does not
    parse COBOL at all.
    """
    if not any(hasattr(args, dest) for dest in _PARSES_COBOL):
        return []
    quiet = (
        {"source_format"}
        if getattr(args, "command", None) in _SOURCE_FORMAT_NOT_WARNED
        else set()
    )
    return [
        key
        for key, dest, changes in _PARSE_SETTINGS
        if changes(config) and not hasattr(args, dest) and dest not in quiet
    ]
