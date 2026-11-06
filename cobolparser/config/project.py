"""The universal project config file: ``cobol.yml``.

One file at the root of a COBOL project, read by every tool in the family --
the ``cobol-parser`` CLI (here), the ``mockymock`` CLI (via
`load_project_config`), and the COBOL Analyzer VS Code extension (which
re-reads the same file in TypeScript). A shop states its copybook
directories, source format, dialect and record encoding **once** instead of
repeating them on every invocation and in every editor's settings.

Discovery walks up from ``start_dir`` looking for ``cobol.yml`` then
``cobol.yaml`` in each directory, the way ``git`` walks up looking for
``.git``. First match wins; finding nothing is the ordinary case and is not
an error.

Precedence at every call site is **explicit CLI flag > config file >
built-in default**. This module never overrides a flag the user actually
passed; see `cobolparser.cli._project_config.apply_project_config` for the one place
that merge happens.

Shape (every key optional)::

    version: 1

    project:                        # shared by every tool
      copybook_path: [copybooks]    # string or list, relative to this file
      callee_path: [src/subprograms]
      proc_path: [proclib]          # cataloged JCL PROCs (NAME.prc, ...)
      source_format: fixed          # auto | fixed | free
      debug_lines: false            # compile D-in-column-7 lines as code
      dialect: ibm-enterprise
      error_recovery: collect-all   # collect-all | fail-fast
      seed: 42
      extensions: [.cbl, .cob]
      define:                       # conditional-compilation symbols
        DEBUG: "TRUE"

    data:                           # record layout / encoding defaults
      charset: ebcdic               # ascii | ebcdic
      endian: big                   # auto | big | little | native
      record_format: fixed          # fixed | variable | variable-bare | auto
      record_separator: none        # none | newline
      rows: 100

    lint:
      rules: [dead-code, unused-variables]
      min_severity: warning
      fail_on: error

    mockymock: {...}                # read by the mockymock CLI
    analyzer:  {...}                # read by the VS Code extension

Unknown keys are **rejected**, not ignored: a typo'd ``copybook-paths``
that quietly did nothing would be a config the user believes is in effect
and isn't. The two tool sections (``mockymock``, ``analyzer``) are the
exception -- their contents are validated by the tool that owns them and
are carried here verbatim, so this package never has to know their schema.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ._yaml import YamlError, parse_yaml

__all__ = [
    "CONFIG_FILE_NAMES",
    "ConfigError",
    "DataDefaults",
    "LintDefaults",
    "ProjectConfig",
    "SCHEMA_VERSION",
    "find_config_file",
    "load_project_config",
    "resolve",
]

CONFIG_FILE_NAMES: tuple[str, ...] = ("cobol.yml", "cobol.yaml")

# Bumped only for a change that would make an older reader misinterpret a
# newer file. Adding an optional key is not such a change.
SCHEMA_VERSION = 1

# A config file could sit at the root of a deeply nested monorepo checkout;
# this bounds the walk so a detached or networked filesystem cannot turn "no
# config file" into an unbounded stat loop.
_MAX_WALK_LEVELS = 32

# Sections owned by another tool: parsed as mappings so a malformed one is
# still caught here, but their keys are carried through unvalidated.
_TOOL_SECTIONS: tuple[str, ...] = ("mockymock", "analyzer")

_SOURCE_FORMATS: tuple[str, ...] = ("auto", "fixed", "free")
_DIALECTS: tuple[str, ...] = ("ibm-enterprise",)
_ERROR_RECOVERY: tuple[str, ...] = ("collect-all", "fail-fast")
_CHARSETS: tuple[str, ...] = ("ascii", "ebcdic")
_ENDIANS: tuple[str, ...] = ("auto", "big", "little", "native")
_RECORD_FORMATS: tuple[str, ...] = ("fixed", "variable", "variable-bare", "auto")
_RECORD_SEPARATORS: tuple[str, ...] = ("none", "newline")


class ConfigError(Exception):
    """A config file exists but could not be read, or has a bad shape.

    Deliberately not silently ignored or defaulted away -- a malformed
    config is a fail-closed error naming the file, the same posture as the
    rest of this CLI's input validation.
    """


@dataclass(frozen=True)
class DataDefaults:
    """Record layout / encoding defaults (the ``data:`` section).

    These are the settings an EBCDIC shop would otherwise repeat on every
    ``gen-data`` and ``decode`` invocation. ``None`` throughout means "not
    stated", which stays distinct from a value that happens to equal the
    built-in default.
    """

    charset: str | None = None
    endian: str | None = None
    record_format: str | None = None
    record_separator: str | None = None
    rows: int | None = None


@dataclass(frozen=True)
class LintDefaults:
    """The ``lint:`` section: which rules run and what fails a build."""

    rules: tuple[str, ...] = ()
    min_severity: str | None = None
    fail_on: str | None = None
    #: Rules never to run (``lint.disable``), applied after ``rules``.
    disable: tuple[str, ...] = ()
    #: ``rule`` or ``rule/KIND`` -> severity (``lint.severity``).
    severity: tuple[tuple[str, str], ...] = ()
    #: Glob patterns of files never to lint, resolved against the config
    #: file's directory (``lint.exclude``).
    exclude: tuple[str, ...] = ()
    #: The baseline file (``lint.baseline``), resolved likewise.
    baseline: str | None = None
    #: ``lint.scope``: which rules ``lint --new-code-since`` judges on new
    #: code only (``new``) and which on the whole codebase (``all``), as
    #: ``--scope`` values: a bare ``new``/``all`` default, then
    #: ``RULE=new|all`` entries.
    scope: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProjectConfig:
    """A loaded ``cobol.yml``, or an all-default instance when none was found.

    ``source is None`` is the "no config file anywhere" case -- distinct
    from a file that exists and sets nothing, which matters to
    ``cobol-parser config``'s provenance reporting.
    """

    source: Path | None = None
    version: int = SCHEMA_VERSION
    # Directories, already resolved against the config file's own directory
    # (not the cwd) -- a `cobol-parser lint` run from a subdirectory must
    # search the same copybook libraries as one run from the project root.
    copybook_path: tuple[str, ...] = ()
    callee_path: tuple[str, ...] = ()
    # Folders of cataloged JCL PROCs, for expanding a job's EXEC PROC= steps.
    proc_path: tuple[str, ...] = ()
    source_format: str | None = None
    # Compile fixed-format debugging lines (D in column 7) as code; None
    # when the file does not say, so the built-in default (off) applies.
    debug_lines: bool | None = None
    dialect: str | None = None
    error_recovery: str | None = None
    seed: int | None = None
    extensions: tuple[str, ...] = ()
    # Normalized to the "SYMBOL=VALUE" spelling `--define` takes, so the CLI
    # merge does not need to know which of the two source shapes was used.
    define: tuple[str, ...] = ()
    data: DataDefaults = field(default_factory=DataDefaults)
    lint: LintDefaults = field(default_factory=LintDefaults)
    # Raw `mockymock:` / `analyzer:` sections, for the tools that own them.
    tools: dict[str, Any] = field(default_factory=dict)

    def missing_directories(self) -> list[tuple[str, str]]:
        """``(key, path)`` for each ``copybook_path`` / ``callee_path`` /
        ``proc_path`` entry
        that is not an existing directory, checked now (not at load time, so
        a long-lived reader sees a directory created since). A typo there
        otherwise only surfaced as "Copybook 'X' not found" on some later
        program (#550)."""
        return [
            (key, entry)
            for key, entries in (
                ("project.copybook_path", self.copybook_path),
                ("project.callee_path", self.callee_path),
                ("project.proc_path", self.proc_path),
            )
            for entry in entries
            if not Path(entry).is_dir()
        ]

    def tool_section(self, name: str) -> dict[str, Any]:
        """The raw mapping for another tool's section, ``{}`` if absent."""
        section = self.tools.get(name)
        return section if isinstance(section, dict) else {}


# -- validation helpers -------------------------------------------------------


def _require_mapping(value: Any, where: str, source: Path) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigError(f"{source}: '{where}' must be a mapping of key: value")
    return value


def _reject_unknown(
    data: dict[str, Any], known: tuple[str, ...], where: str, source: Path
) -> None:
    unknown = sorted(set(data) - set(known))
    if unknown:
        raise ConfigError(
            f"{source}: unknown key(s) in '{where}': {', '.join(unknown)} "
            f"(recognized: {', '.join(sorted(known))})"
        )


def _string_list(value: Any, where: str, source: Path) -> tuple[str, ...]:
    """A key that accepts either one string or a list of them."""
    if value is None:
        return ()
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ConfigError(f"{source}: '{where}' must be a string or a list of strings")
    return tuple(value)


def _path_list(value: Any, where: str, source: Path) -> tuple[str, ...]:
    """A `_string_list` whose entries are directories, resolved against the
    config file's directory so they mean the same thing from any cwd.

    ``~`` and ``$VAR`` / ``${VAR}`` are expanded first, as the shell does for
    the matching ``--copybook-path ~/cpy`` flag: joined on as written,
    ``~/cpy`` became ``<cfgdir>/~/cpy`` and silently found nothing (#550).
    """
    base = source.parent
    resolved = []
    for entry in _string_list(value, where, source):
        entry_path = Path(os.path.expandvars(os.path.expanduser(entry)))
        resolved.append(
            str(entry_path if entry_path.is_absolute() else base / entry_path)
        )
    return tuple(resolved)


def _enum(value: Any, allowed: tuple[str, ...], where: str, source: Path) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or value not in allowed:
        raise ConfigError(
            f"{source}: '{where}' must be one of {', '.join(allowed)} (got {value!r})"
        )
    return value


def _int(value: Any, where: str, source: Path) -> int | None:
    if value is None:
        return None
    # bool is an int subclass; `seed: true` is a mistake, not seed 1.
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"{source}: '{where}' must be an integer")
    # int() rather than a bare `return value`: the parameter is Any (the YAML
    # reader returns whatever the document held), and mypy will not narrow it
    # to int through the negated isinstance above.
    return int(value)


def _bool(value: Any, where: str, source: Path) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise ConfigError(f"{source}: '{where}' must be true or false")
    return value


def _defines(value: Any, source: Path) -> tuple[str, ...]:
    """`define:` accepts the natural YAML mapping shape as well as the
    ``SYMBOL=VALUE`` list `--define` itself takes. Both normalize to the
    latter, which is what the CLI merge hands to argparse."""
    if value is None:
        return ()
    if isinstance(value, dict):
        out = []
        for key, raw in value.items():
            if isinstance(raw, (dict, list)):
                # A symbol's value is one literal. Stringified, a collection
                # became Python's repr -- `--define "DEBUG=['a', 'b']"` --
                # which no >>DEFINE ever meant.
                raise ConfigError(
                    f"{source}: 'project.define.{key}' must be a single value "
                    f"(a string, number or true/false) or empty, not a "
                    f"{'mapping' if isinstance(raw, dict) else 'list'}"
                )
            if isinstance(raw, bool):
                raw = "TRUE" if raw else "FALSE"
            if raw is None:
                out.append(str(key))
            else:
                out.append(f"{key}={raw}")
        return tuple(out)
    return _string_list(value, "project.define", source)


def _lint_rules(value: Any, source: Path, where: str = "lint.rules") -> tuple[str, ...]:
    rules = _string_list(value, where, source)
    if not rules:
        return ()
    # Imported here rather than at module scope: `cobolparser.config` is
    # imported by other tools purely to read a file, and should not drag the
    # whole analysis package in with it.
    from ..analysis.lint import ALL_RULES

    unknown = sorted(set(rules) - set(ALL_RULES))
    if unknown:
        raise ConfigError(
            f"{source}: unknown lint rule(s): {', '.join(unknown)} "
            f"(recognized: {', '.join(ALL_RULES)})"
        )
    return rules


def _lint_severity_overrides(value: Any, source: Path) -> tuple[tuple[str, str], ...]:
    """``lint.severity``: a mapping of ``rule`` or ``rule/KIND`` to a
    severity, e.g. ``{recursion-check: info, io-sequence/FILE_LEFT_OPEN:
    error}``. Validated here so a typo fails loudly instead of matching
    nothing."""
    if value is None:
        return ()
    mapping = _require_mapping(value, "lint.severity", source)
    from ..analysis.lint import ALL_RULES, PARSE_RULE

    out = []
    for key, level in mapping.items():
        rule = str(key).split("/", 1)[0]
        if rule not in (*ALL_RULES, PARSE_RULE):
            raise ConfigError(
                f"{source}: lint.severity: unknown rule {rule!r} "
                f"(recognized: {', '.join(ALL_RULES)})"
            )
        severity = _severity(level, f"lint.severity.{key}", source)
        assert severity is not None
        out.append((str(key), severity))
    return tuple(out)


def _lint_scope(value: Any, source: Path) -> tuple[str, ...]:
    """``lint.scope``: ``new`` / ``all``, or a mapping of ``default`` and
    rule (or ``rule/KIND``) to one of them, e.g. ``{default: new,
    call-check: all}``. Validated here so a typo fails loudly."""
    if value is None:
        return ()
    from ..cli._new_code import parse_scopes

    if isinstance(value, dict):
        items: list[str] = []
        for key, scope in value.items():
            items.append(str(scope) if str(key) == "default" else f"{key}={scope}")
    elif isinstance(value, str):
        items = [value]
    else:
        raise ConfigError(
            f"{source}: lint.scope: expected new, all, or a mapping of rule "
            "to new/all"
        )
    try:
        parse_scopes(items)
    except ValueError as exc:
        raise ConfigError(f"{source}: lint.scope: {exc}") from exc
    return tuple(items)


def _severity(
    value: Any, where: str, source: Path, extra: tuple[str, ...] = ()
) -> str | None:
    if value is None:
        return None
    from ..analysis.lint import SEVERITIES

    return _enum(value, (*SEVERITIES, *extra), where, source)


# -- section builders ---------------------------------------------------------

_PROJECT_KEYS = (
    "copybook_path",
    "callee_path",
    "proc_path",
    "source_format",
    "debug_lines",
    "dialect",
    "error_recovery",
    "seed",
    "extensions",
    "define",
)
_DATA_KEYS = ("charset", "endian", "record_format", "record_separator", "rows")
_LINT_KEYS = (
    "rules",
    "min_severity",
    "fail_on",
    "disable",
    "severity",
    "exclude",
    "baseline",
    "scope",
)
_TOP_LEVEL_KEYS = ("version", "project", "data", "lint", *_TOOL_SECTIONS)


def _build_data(raw: Any, source: Path) -> DataDefaults:
    data = _require_mapping(raw, "data", source) if raw is not None else {}
    _reject_unknown(data, _DATA_KEYS, "data", source)
    return DataDefaults(
        charset=_enum(data.get("charset"), _CHARSETS, "data.charset", source),
        endian=_enum(data.get("endian"), _ENDIANS, "data.endian", source),
        record_format=_enum(
            data.get("record_format"), _RECORD_FORMATS, "data.record_format", source
        ),
        record_separator=_enum(
            data.get("record_separator"),
            _RECORD_SEPARATORS,
            "data.record_separator",
            source,
        ),
        rows=_int(data.get("rows"), "data.rows", source),
    )


def _build_lint(raw: Any, source: Path) -> LintDefaults:
    lint = _require_mapping(raw, "lint", source) if raw is not None else {}
    _reject_unknown(lint, _LINT_KEYS, "lint", source)
    return LintDefaults(
        rules=_lint_rules(lint.get("rules"), source),
        min_severity=_severity(lint.get("min_severity"), "lint.min_severity", source),
        # `never` is --fail-on's own "findings never fail the build" value.
        fail_on=_severity(lint.get("fail_on"), "lint.fail_on", source, ("never",)),
        disable=_lint_rules(lint.get("disable"), source, "lint.disable"),
        severity=_lint_severity_overrides(lint.get("severity"), source),
        exclude=_path_list(lint.get("exclude"), "lint.exclude", source),
        baseline=(
            _path_list([lint["baseline"]], "lint.baseline", source)[0]
            if lint.get("baseline") is not None
            else None
        ),
        scope=_lint_scope(lint.get("scope"), source),
    )


def build_config(document: Any, source: Path) -> ProjectConfig:
    """Validate a parsed YAML document into a `ProjectConfig`.

    Split out from `load_project_config` so a caller holding the document
    already (a test, or a tool that read the file itself) validates it
    through exactly the same path.
    """
    if document is None:
        # An empty or comment-only file is a legitimate placeholder.
        return ProjectConfig(source=source)
    top = _require_mapping(document, "<document>", source)
    _reject_unknown(top, _TOP_LEVEL_KEYS, "<document>", source)

    version = _int(top.get("version"), "version", source)
    if version is not None and version != SCHEMA_VERSION:
        raise ConfigError(
            f"{source}: unsupported config version {version} "
            f"(this build understands version {SCHEMA_VERSION}); "
            f"upgrade cobol-parser, or remove the 'version' key"
        )

    project = (
        _require_mapping(top.get("project"), "project", source)
        if top.get("project") is not None
        else {}
    )
    _reject_unknown(project, _PROJECT_KEYS, "project", source)

    return ProjectConfig(
        source=source,
        version=version if version is not None else SCHEMA_VERSION,
        copybook_path=_path_list(
            project.get("copybook_path"), "project.copybook_path", source
        ),
        callee_path=_path_list(
            project.get("callee_path"), "project.callee_path", source
        ),
        proc_path=_path_list(project.get("proc_path"), "project.proc_path", source),
        source_format=_enum(
            project.get("source_format"),
            _SOURCE_FORMATS,
            "project.source_format",
            source,
        ),
        debug_lines=_bool(project.get("debug_lines"), "project.debug_lines", source),
        dialect=_enum(project.get("dialect"), _DIALECTS, "project.dialect", source),
        error_recovery=_enum(
            project.get("error_recovery"),
            _ERROR_RECOVERY,
            "project.error_recovery",
            source,
        ),
        seed=_int(project.get("seed"), "project.seed", source),
        extensions=_string_list(
            project.get("extensions"), "project.extensions", source
        ),
        define=_defines(project.get("define"), source),
        data=_build_data(top.get("data"), source),
        lint=_build_lint(top.get("lint"), source),
        tools={
            name: _require_mapping(top[name], name, source)
            for name in _TOOL_SECTIONS
            if top.get(name) is not None
        },
    )


# -- discovery ----------------------------------------------------------------


def find_config_file(start_dir: Path | None = None) -> Path | None:
    """The nearest ``cobol.yml``/``cobol.yaml`` at or above ``start_dir``.

    ``cobol.yml`` beats ``cobol.yaml`` in the same directory (both are tried
    per directory before moving up). Returns ``None`` when the walk finds
    nothing, which is the common case and not an error.
    """
    directory = (start_dir or Path.cwd()).resolve()
    for _ in range(_MAX_WALK_LEVELS):
        for name in CONFIG_FILE_NAMES:
            candidate = directory / name
            if candidate.is_file():
                return candidate
        parent = directory.parent
        if parent == directory:
            break
        directory = parent
    return None


def load_project_config(
    start_dir: Path | None = None, path: Path | str | None = None
) -> ProjectConfig:
    """Load the project config, searching upward from ``start_dir``.

    ``path`` loads exactly that file instead of searching -- what
    ``cobol-parser --config FILE`` passes, and what the VS Code extension
    uses, since it spawns the CLI with no cwd of its own and an upward walk
    from the extension host's cwd would find the wrong file or none at all.
    A ``path`` that does not exist is an error; a *search* that finds
    nothing is not.
    """
    if path is not None:
        source = Path(path)
        if not source.is_file():
            raise ConfigError(f"config file not found: {source}")
        return _load_file(source)

    found = find_config_file(start_dir)
    if found is None:
        return ProjectConfig()
    return _load_file(found)


def _load_file(source: Path) -> ProjectConfig:
    try:
        text = source.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"could not read {source}: {exc}") from exc
    except UnicodeDecodeError as exc:
        raise ConfigError(f"{source}: not valid UTF-8: {exc}") from exc
    try:
        document = parse_yaml(text, str(source))
    except YamlError as exc:
        raise ConfigError(str(exc)) from exc
    return build_config(document, source)


def resolve(cli_value: Any, config_value: Any, hardcoded_default: Any = None) -> Any:
    """Precedence helper: explicit CLI value, else config file, else default.

    ``None`` is the "not given" signal at both levels, which is why every
    config field above defaults to ``None`` rather than to the built-in it
    would otherwise duplicate.
    """
    if cli_value is not None:
        return cli_value
    if config_value is not None:
        return config_value
    return hardcoded_default
