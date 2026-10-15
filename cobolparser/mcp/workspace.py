"""The directory an MCP server answers about, and its parsed programs.

Three jobs, each the reason a tool can stay a thin question over an analyzer:

* **The guard.** Every path a client names is resolved (symlinks included)
  and refused unless it lies under the workspace root or one of the
  ``cobol.yml`` copybook directories. A model passing ``../../etc/passwd``
  gets an error, not a file.
* **The config.** ``cobol.yml`` is found from the root the way the CLI finds
  it, so copybook paths, source format and ``>>DEFINE`` symbols are the ones
  every other tool in the family already uses. No tool takes a copybook
  path argument: one config, one answer. A found file is re-read when it
  changes (or appears, or goes away), and the cache is dropped with it.
* **The cache.** A program is parsed once and kept, keyed by its path and
  program unit, and re-parsed only when it -- or a copybook it expanded --
  changes on disk.

Parsing always recovers (``COLLECT_ALL``), as the CLI does, so a program with
one bad statement still answers; the recovery is a caveat, not a failure. A
COPY whose member cannot be found is left as written and named in a caveat,
while every other member is still expanded.
"""

from __future__ import annotations

import contextlib
import sys
import threading
from collections import OrderedDict
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..config.project import (
    ConfigError,
    ProjectConfig,
    find_config_file,
    load_project_config,
)
from ..models.program import CobolProgram
from .envelope import Caveat, Response, ToolError

#: Programs kept parsed at once. A 20,000-line program's AST is tens of MB,
#: so the bound is on entries, and small.
DEFAULT_CACHE_SIZE = 32


@contextlib.contextmanager
def stdout_to_stderr() -> Iterator[None]:
    """Route stray ``print()`` output to stderr while a tool runs.

    Over stdio, stdout *is* the protocol channel: one diagnostic line printed
    there by a library call corrupts the stream the client is reading.
    """
    with contextlib.redirect_stdout(sys.stderr):
        yield


def _stamp(path: str) -> tuple[int, int] | None:
    try:
        stat = Path(path).stat()
    except OSError:
        return None
    return (stat.st_mtime_ns, stat.st_size)


def _defined_symbols(defines: tuple[str, ...]) -> dict[str, str] | None:
    """``cobol.yml``'s ``define`` entries (``SYMBOL=VALUE``) as a dict."""
    if not defines:
        return None
    symbols: dict[str, str] = {}
    for entry in defines:
        key, _, value = entry.partition("=")
        symbols[key.strip()] = value.strip() if value else "TRUE"
    return symbols


@dataclass
class ParsedProgram:
    """One parsed source file, with what it takes to cite it on disk."""

    path: Path
    display_path: str
    result: Any  # ParseResult
    #: Expanded-text line -> (file, line on disk). None when nothing was
    #: expanded: every line is then this file's own.
    source_map: dict[int, tuple[str, int]] | None
    column_offset: Callable[[str, int], int | None]
    caveats: list[Caveat]
    #: (mtime_ns, size) of every file this parse read, and of every copybook
    #: directory, for invalidation.
    stamps: dict[str, tuple[int, int] | None]
    _display: Callable[[str], str] = field(repr=False, default=str)

    @property
    def ast(self) -> CobolProgram:
        ast = self.result.ast
        assert ast is not None  # a parse without an AST is never cached
        return ast  # type: ignore[no-any-return]

    def unit_names(self) -> list[str]:
        return [u.program_name or "<unnamed>" for u in self.ast.program_units()]

    def unit(self, program: str | None, response: Response) -> CobolProgram:
        """The program unit *program* names, or the outermost one.

        A file holding several units answers for one at a time; when the
        caller did not pick, the caveat says which one it got and what else
        is there.
        """
        names = self.unit_names()
        if program:
            selected = self.ast.find_program_unit(program)
            if selected is None:
                raise ToolError(
                    f"no program unit named {program!r} in {self.display_path} "
                    f"(found: {', '.join(names)})"
                )
            return selected
        if len(names) > 1:
            response.caveat(
                "program-unit-selected",
                f"{self.display_path} holds {len(names)} program units; this "
                f"answer covers {names[0]} only (also: {', '.join(names[1:])})",
                "pass program= to ask about another unit",
            )
        return self.ast

    def program_info(self, unit: CobolProgram | None = None) -> dict[str, Any]:
        info: dict[str, Any] = {"file": self.display_path}
        if unit is not None:
            info["program_id"] = unit.program_name
        names = self.unit_names()
        if len(names) > 1:
            info["program_units"] = names
        return info

    def locate(
        self,
        line: int | None,
        column: int | None,
        response: Response,
        *,
        column_known: bool = True,
    ) -> dict[str, Any] | None:
        """``{"file", "line", "column"}`` on disk for an analyzer location.

        ``None`` (with an ``unmapped-location`` caveat) when the source map
        has nothing for the line: an honest gap beats a line nobody vouched
        for.
        """
        if line is None or line <= 0:
            return None
        if self.source_map is None:
            origin: tuple[str, int] | None = (str(self.path), line)
        else:
            origin = self.source_map.get(line)
        if origin is None:
            response.caveat(
                "unmapped-location",
                "some locations could not be traced back to a file on disk "
                "and are reported as null",
            )
            return None
        file, file_line = origin
        located: dict[str, Any] = {"file": self._display(file), "line": file_line}
        if column_known and column is not None and column > 0:
            offset = self.column_offset(file, file_line)
            if offset is not None:
                located["column"] = column + offset
        return located


class Workspace:
    """A root directory, its ``cobol.yml``, and a cache of parsed programs.

    Not thread-safe: the cache and :func:`stdout_to_stderr` are shared
    state. A caller running tools on several threads holds :attr:`lock`
    around each call (the MCP server does).
    """

    def __init__(
        self,
        root: str | Path,
        config: ProjectConfig | None = None,
        cache_size: int = DEFAULT_CACHE_SIZE,
    ) -> None:
        self.root = Path(root).resolve()
        if not self.root.is_dir():
            raise ToolError(f"workspace root is not a directory: {root}")
        #: Serializes tool calls made from worker threads.
        self.lock = threading.Lock()
        self.cache_size = max(1, cache_size)
        self._cache: OrderedDict[str, ParsedProgram] = OrderedDict()
        # A config handed in (``--config`` / ``--no-config``) is the caller's
        # choice and stays fixed; a found one follows the file on disk.
        self._config_fixed = config is not None
        self._config_source: tuple[Path | None, tuple[int, int] | None] = (
            None,
            None,
        )
        self._config = ProjectConfig()
        self._allowed: list[Path] = [self.root]
        if config is not None:
            self._use_config(config)
        else:
            self._reload_config()

    # -- config --------------------------------------------------------------

    @property
    def config(self) -> ProjectConfig:
        """The project config, re-read first if ``cobol.yml`` changed."""
        self.refresh_config()
        return self._config

    def refresh_config(self) -> None:
        """Re-read ``cobol.yml`` if it was edited, added or removed.

        A few ``stat`` calls per tool call: cheap next to a parse, and an
        agent editing ``cobol.yml`` mid-session sees the change at once
        instead of after a restart it cannot perform.
        """
        if self._config_fixed:
            return
        found = find_config_file(self.root)
        source = (found, _stamp(str(found)) if found else None)
        if source != self._config_source:
            self._reload_config()

    def _reload_config(self) -> None:
        found = find_config_file(self.root)
        source = (found, _stamp(str(found)) if found else None)
        try:
            config = load_project_config(self.root)
        except ConfigError as exc:
            # The stamp is not recorded, so the next call tries again once
            # the file is fixed.
            raise ToolError(f"cobol.yml could not be read: {exc}") from exc
        self._config_source = source
        self._use_config(config)

    def _use_config(self, config: ProjectConfig) -> None:
        self._config = config
        self._allowed = [self.root] + [Path(p).resolve() for p in config.copybook_path]
        # Copybook paths, source format and defines all shape a parse.
        self._cache.clear()

    # -- paths ---------------------------------------------------------------

    def _within(self, path: Path) -> bool:
        return any(path == base or base in path.parents for base in self._allowed)

    def resolve(self, file: str) -> Path:
        """*file* (relative to the root, or absolute) as a guarded real path."""
        if not file or not file.strip():
            raise ToolError("no file given")
        # A changed cobol.yml can move the guard (its copybook directories).
        self.refresh_config()
        candidate = Path(file)
        if not candidate.is_absolute():
            candidate = self.root / candidate
        try:
            resolved = candidate.resolve()
        except (OSError, RuntimeError) as exc:
            raise ToolError(f"cannot resolve {file}: {exc}") from exc
        if not self._within(resolved):
            raise ToolError(
                f"{file} is outside the workspace ({self.root}) and its "
                "copybook directories"
            )
        if not resolved.is_file():
            raise ToolError(f"file not found: {file}")
        return resolved

    def display(self, path: str | Path) -> str:
        """*path* as a client should cite it: root-relative when it can be."""
        try:
            resolved = Path(path).resolve()
        except (OSError, RuntimeError):
            return str(path)
        try:
            return resolved.relative_to(self.root).as_posix()
        except ValueError:
            return resolved.as_posix()

    @staticmethod
    def read_text(path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ToolError(f"{path.name} is not valid UTF-8 text") from exc
        except OSError as exc:
            raise ToolError(f"cannot read {path.name}: {exc}") from exc

    # -- parsing -------------------------------------------------------------

    def program(self, file: str) -> ParsedProgram:
        """The parsed program in *file*, from the cache when still current."""
        path = self.resolve(file)
        key = str(path)
        cached = self._cache.get(key)
        if cached is not None and all(
            _stamp(name) == stamp for name, stamp in cached.stamps.items()
        ):
            self._cache.move_to_end(key)
            return cached
        parsed = self._parse(path)
        self._cache[key] = parsed
        self._cache.move_to_end(key)
        while len(self._cache) > self.cache_size:
            self._cache.popitem(last=False)
        return parsed

    def _copybook_directories(self) -> list[str]:
        directories: list[str] = []
        for base in self.config.copybook_path:
            directories.append(base)
            try:
                directories.extend(
                    str(entry) for entry in Path(base).iterdir() if entry.is_dir()
                )
            except OSError:
                pass
        return directories

    def _format_kwargs(self) -> dict[str, Any]:
        source_format = self.config.source_format or "auto"
        kwargs: dict[str, Any]
        if source_format == "free":
            kwargs = {"free_form": True, "preprocess_fixed": False}
        elif source_format == "fixed":
            kwargs = {"free_form": False, "preprocess_fixed": True}
        else:
            kwargs = {"free_form": False, "preprocess_fixed": None}
        if self.config.debug_lines:
            kwargs["debug_lines"] = True
        return kwargs

    def _parse(self, path: Path) -> ParsedProgram:
        from .. import parse_cobol
        from ..analysis.lint import source_column_offsets
        from ..plugins.core import DialectType, ErrorRecoveryMode
        from ..preprocess import PreprocessingError, preprocess_conditional_compilation
        from ..preprocess.copybook_expander import parse_cobol_with_expansion

        source = self.read_text(path)
        filename = str(path)
        format_kwargs = self._format_kwargs()
        parse_kwargs: dict[str, Any] = {
            "dialect": DialectType.IBM_ENTERPRISE,
            "error_recovery": ErrorRecoveryMode.COLLECT_ALL,
            **format_kwargs,
        }
        defines = _defined_symbols(self.config.define)
        copybook_paths = list(self.config.copybook_path)
        caveats: list[Caveat] = []

        def parse_plain() -> Any:
            text = source
            if defines:
                # Same order as the CLI without copybook paths: the directive
                # pass runs first so the --define symbols are seen at all.
                text = preprocess_conditional_compilation(
                    source, defines, keep_source_format_directives=True
                )
            return parse_cobol(text, filename=filename, **parse_kwargs)

        with stdout_to_stderr():
            result: Any = None
            if copybook_paths:
                try:
                    result = parse_cobol_with_expansion(
                        source,
                        filename=filename,
                        copybook_paths=copybook_paths,
                        process_conditionals=True,
                        defined_symbols=defines,
                        # A missing member is named by the parser's "not
                        # expanded" warning below; the rest still expand.
                        skip_missing_copybooks=True,
                        **parse_kwargs,
                    )
                except PreprocessingError as exc:
                    # What is left: a circular COPY, a nesting or size
                    # limit, an undecodable member.
                    caveats.append(
                        Caveat(
                            "unresolved-copybook",
                            f"copybook expansion failed ({exc}); the program "
                            "was parsed without expanding any COPY",
                            "declarations from every copybook are missing; "
                            "unused and undeclared names are unreliable",
                        )
                    )
            if result is None:
                result = parse_plain()

        if result.ast is None:
            errors = "; ".join(str(e) for e in result.errors[:3])
            raise ToolError(f"{self.display(path)} could not be parsed: {errors}")

        for warning in result.warnings or []:
            text = str(warning)
            if "COPY" in text.upper() and "not expanded" in text:
                caveats.append(
                    Caveat(
                        "unresolved-copybook",
                        text,
                        "declarations from that member are missing; unused "
                        "and undeclared names are unreliable",
                    )
                )
        if result.errors:
            first = "; ".join(str(e) for e in result.errors[:3])
            caveats.append(
                Caveat(
                    "partial-parse",
                    f"parsed with {len(result.errors)} error(s), recovered: {first}",
                    "statements around those errors were not analyzed",
                )
            )

        source_map = getattr(result, "expansion_source_map", None) or None
        files = {filename}
        if source_map:
            files.update(file for file, _ in source_map.values())
        # A member that was missing, or one that would now shadow the one
        # used, is a new directory entry: no file the parse read changes,
        # but its directory's mtime does. ``COPY X OF LIB`` searches one
        # level down, so library subdirectories are stamped too.
        files.update(self._copybook_directories())
        return ParsedProgram(
            path=path,
            display_path=self.display(path),
            result=result,
            source_map=source_map,
            column_offset=source_column_offsets(
                filename, format_kwargs["preprocess_fixed"]
            ),
            caveats=caveats,
            stamps={name: _stamp(name) for name in files},
            _display=self.display,
        )
