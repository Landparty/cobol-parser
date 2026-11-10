"""The directory an MCP server answers about, and its parsed programs.

Three jobs, each the reason a tool can stay a thin question over an analyzer:

* **The guard.** Every path a client names is resolved (symlinks included)
  and refused unless it lies under the workspace root or one of the
  ``cobol.yml`` copybook directories. A model passing ``../../etc/passwd``
  gets an error, not a file. Since ``cobol.yml`` may come from the analysed
  tree itself, a copybook directory outside the root opens only copybook
  members (:data:`COPYBOOK_MEMBER_SUFFIXES`, no dot-named file or
  subdirectory), and a directory that could only be a trick -- ``/``, the
  home directory, an ancestor of either or of the root, a hidden directory,
  a system directory (:data:`REFUSED_SYSTEM_DIRS`) -- is refused outright:
  neither searched nor readable, and named
  (:attr:`Workspace.refused_copybook_dirs`).
* **The config.** ``cobol.yml`` (or ``cobol.yaml``) is read from the root
  itself -- never from a directory above it, as the CLI's walk-up would --
  so copybook paths, source format and ``>>DEFINE`` symbols are the ones
  every other tool in the family already uses. No tool takes a copybook
  path argument: one config, one answer. A found file is re-read when it
  changes (or appears, or goes away), and the cache is dropped with it.
* **The cache.** A program is parsed once and kept, keyed by its path and
  program unit, and re-parsed only when it -- or a copybook it expanded --
  changes on disk. The cross-program indexes (:mod:`.codebase_index`) are
  kept the same way: built over every program under the root on first use,
  and rebuilt once any file one of them read changes, or a program file is
  added or removed.

Parsing always recovers (``COLLECT_ALL``), as the CLI does, so a program with
one bad statement still answers; the recovery is a caveat, not a failure. A
COPY whose member cannot be found is left as written and named in a caveat,
while every other member is still expanded.
"""

from __future__ import annotations

import contextlib
import os
import re
import sys
import threading
from collections import OrderedDict
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .._lines import split_source_lines
from ..config.project import (
    CONFIG_FILE_NAMES,
    ConfigError,
    ProjectConfig,
    load_project_config,
)
from ..models.program import CobolProgram
from ..preprocess.models import CopybookSearchPath
from .envelope import Caveat, Response, ToolError

if TYPE_CHECKING:
    from ..analysis.context import ProgramContext
    from ..analysis.program_flow import ProgramFlowReport
    from ..analysis.xref import XrefReport

#: Programs kept parsed at once. A 20,000-line program's AST is tens of MB,
#: so the bound is on entries, and small.
DEFAULT_CACHE_SIZE = 32

#: What counts as a COBOL program under the root when ``cobol.yml`` names no
#: ``extensions``: the ``codebase-graph`` subcommand's own default.
DEFAULT_PROGRAM_EXTENSIONS: tuple[str, ...] = (".cbl", ".cob", ".cobol")

Stamp = tuple[int, int] | None

#: Suffixes (lower-cased) a file in a copybook directory outside the root
#: must have to be readable: the ones COPY resolution itself tries
#: (``CopybookSearchPath.extensions``), so every member the parse could have
#: expanded can be cited, and nothing else. ``""`` is among them, because
#: mainframe members are often downloaded without a suffix.
COPYBOOK_MEMBER_SUFFIXES: frozenset[str] = frozenset(
    e.lower() for e in CopybookSearchPath().extensions
)

#: Directories never accepted as copybook directories (nor anything under
#: them): system configuration and process state, where extensionless files
#: such as ``/etc/shadow`` or ``/proc/self/environ`` are secrets.
REFUSED_SYSTEM_DIRS: tuple[str, ...] = (
    "/etc",
    "/proc",
    "/sys",
    "/dev",
    "/boot",
    "/run",
    "/var/run",
)


@contextlib.contextmanager
def stdout_to_stderr() -> Iterator[None]:
    """Route stray ``print()`` output to stderr while a tool runs.

    Over stdio, stdout *is* the protocol channel: one diagnostic line printed
    there by a library call corrupts the stream the client is reading.
    """
    with contextlib.redirect_stdout(sys.stderr):
        yield


def _stamp(path: str) -> Stamp:
    try:
        stat = Path(path).stat()
    except OSError:
        return None
    return (stat.st_mtime_ns, stat.st_size)


def _under(path: Path, base: Path) -> bool:
    return path == base or base in path.parents


def _home() -> Path | None:
    try:
        return Path.home().resolve()
    except (OSError, RuntimeError, KeyError):
        return None


def _hidden_part(path: Path, base: Path) -> bool:
    """Whether any component of *path* below *base* is dot-named."""
    return any(part.startswith(".") for part in path.relative_to(base).parts)


def _root_config_file(root: Path) -> Path | None:
    """``cobol.yml`` / ``cobol.yaml`` in *root* itself, or None.

    Unlike the CLI's :func:`~cobolparser.config.project.find_config_file`,
    this never looks above the root: a server pinned to a root answers
    from that root's config, not from one some parent directory holds.
    """
    for name in CONFIG_FILE_NAMES:
        candidate = root / name
        if candidate.is_file():
            return candidate
    return None


def _defined_symbols(defines: tuple[str, ...]) -> dict[str, str] | None:
    """``cobol.yml``'s ``define`` entries (``SYMBOL=VALUE``) as a dict, read
    as the CLI's ``--define`` reads them: ``SYMBOL`` alone is ``TRUE``, and
    ``SYMBOL=`` is the empty value, not ``TRUE``."""
    if not defines:
        return None
    symbols: dict[str, str] = {}
    for entry in defines:
        key, equals, value = entry.partition("=")
        symbols[key.strip()] = value.strip() if equals else "TRUE"
    return symbols


def _unwrap_source_map(
    source_map: dict[int, tuple[str, int]] | None,
    filename: str,
    head_lines: int,
    fragment_lines: int,
) -> dict[int, tuple[str, int]]:
    """A wrapped copybook's lines back to the file's own.

    The skeleton's head moves every line of *filename* down by *head_lines*;
    the head and the tail after the fragment's *fragment_lines* are not in
    the file at all, so they map to nothing.  Lines from expanded members
    keep their own origins.
    """
    if source_map is None:
        source_map = {
            line: (filename, line) for line in range(1, head_lines + fragment_lines + 1)
        }
    unwrapped: dict[int, tuple[str, int]] = {}
    for line, (file, file_line) in source_map.items():
        if file != filename:
            unwrapped[line] = (file, file_line)
        elif head_lines < file_line <= head_lines + fragment_lines:
            unwrapped[line] = (file, file_line - head_lines)
    return unwrapped


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
    stamps: dict[str, Stamp]
    _display: Callable[[str], str] = field(repr=False, default=str)
    #: Analyzer reports already computed for this parse, by (analyzer, unit).
    _reports: dict[tuple[str, int], Any] = field(repr=False, default_factory=dict)
    #: The shared analysis context of each unit, by ``id(unit)``.
    _contexts: dict[int, ProgramContext] = field(repr=False, default_factory=dict)

    def report(self, name: str, unit: CobolProgram, build: Callable[[], Any]) -> Any:
        """*build()*'s result for *unit*, computed once per parse.

        Several tools ask for the same report (the flow graph backs both
        ``program_brief`` and ``callers_of``); the parse cache already keeps
        it exactly as long as it stays true.
        """
        key = (name, id(unit))
        if key not in self._reports:
            with stdout_to_stderr():
                self._reports[key] = build()
        return self._reports[key]

    def context(self, unit: CobolProgram) -> ProgramContext:
        """The :class:`~cobolparser.analysis.context.ProgramContext` of
        *unit*, one per unit per parse, so every tool and analyzer shares its
        cross-reference, flow graph and procedure index."""
        from ..analysis.context import ProgramContext

        found = self._contexts.get(id(unit))
        if found is None or found.ast is not unit:
            found = self._contexts[id(unit)] = ProgramContext(unit)
        return found

    def xref(self, unit: CobolProgram) -> XrefReport:
        """*unit*'s cross-reference, built once per parse."""
        ctx = self.context(unit)
        with stdout_to_stderr():
            return ctx.xref

    def flow(self, unit: CobolProgram) -> ProgramFlowReport:
        """*unit*'s control flow graph, built once per parse."""
        ctx = self.context(unit)
        with stdout_to_stderr():
            return ctx.flow

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


#: Suffixes of the sources the tools do not parse, with their language.
OTHER_SOURCE_LANGUAGES: dict[str, str] = {
    ".asm": "assembler",
    ".s": "assembler",
    ".mac": "assembler",
    ".hlasm": "assembler",
    ".alc": "assembler",
    ".mlc": "assembler",
    ".assemble": "assembler",
    ".asmpgm": "assembler",
    ".pli": "PL/I",
    ".pl1": "PL/I",
    ".bms": "BMS mapset",
    ".rexx": "REXX",
    ".rex": "REXX",
    ".c": "C",
    ".ezt": "Easytrieve",
}

#: ``LABEL CSECT`` / ``LABEL START`` / `` ENTRY NAME`` in an assembler source.
_ASM_SECTION = re.compile(r"^([A-Z@#$][A-Z0-9@#$]{0,7})\s+(?:CSECT|RSECT|START)\b")
_ASM_ENTRY = re.compile(r"^\s+ENTRY\s+([A-Z@#$][A-Z0-9@#$,]*)")

#: Bytes of an assembler source read for its section names.
_ASM_SCAN_BYTES = 256 * 1024


def _assembler_names(path: Path) -> set[str]:
    """The CSECT / START labels and ENTRY names *path* declares."""
    try:
        with path.open("rb") as handle:
            text = handle.read(_ASM_SCAN_BYTES).decode("latin-1")
    except OSError:
        return set()
    names: set[str] = set()
    for line in split_source_lines(text.upper()):
        if line.startswith("*"):
            continue
        match = _ASM_SECTION.match(line)
        if match:
            names.add(match.group(1))
        entry = _ASM_ENTRY.match(line)
        if entry:
            names.update(n for n in entry.group(1).split(",") if n)
    return names


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
        #: Copybook directories the config named that were refused outright
        #: (see :meth:`_refusal`), each with why: neither searched nor
        #: readable.
        self.refused_copybook_dirs: tuple[tuple[str, str], ...] = ()
        #: Kept copybook directories outside the root: only copybook
        #: members are readable under these.
        self._outside: list[Path] = []
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
        #: Cross-program indexes by name: (value, stamps of what it read).
        self._indexes: dict[str, tuple[Any, dict[str, Stamp]]] = {}
        #: Told ``(done, total, message)`` while a root-wide index is built,
        #: so a client sees the first cross-program call is alive. Set by the
        #: server around one call; None when nobody listens.
        self.progress: Callable[[float, float | None, str], None] | None = None
        #: The per-file facts the cross-program indexes are assembled from
        #: (:class:`.facts.FactsStore`); made on first use when not set.
        self.facts_store: Any = None
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
        found = _root_config_file(self.root)
        source = (found, _stamp(str(found)) if found else None)
        if source != self._config_source:
            self._reload_config()

    def _reload_config(self) -> None:
        found = _root_config_file(self.root)
        source = (found, _stamp(str(found)) if found else None)
        try:
            config = (
                ProjectConfig() if found is None else load_project_config(path=found)
            )
        except ConfigError as exc:
            # The stamp is not recorded, so the next call tries again once
            # the file is fixed.
            raise ToolError(f"cobol.yml could not be read: {exc}") from exc
        self._config_source = source
        self._use_config(config)

    def _refusal(self, directory: Path) -> str | None:
        """Why *directory* (resolved) can never be a copybook directory, or
        None when it can. A directory under the root always can."""
        if _under(directory, self.root):
            return None
        if directory == Path(directory.anchor):
            return "the filesystem root"
        if _under(self.root, directory):
            return "it contains the workspace root"
        home = _home()
        if home is not None and _under(home, directory):
            return "it is the home directory or contains it"
        for system in REFUSED_SYSTEM_DIRS:
            if _under(directory, Path(system)):
                return f"it is a system directory ({system})"
        if any(part.startswith(".") for part in directory.parts):
            return "it is a hidden directory"
        return None

    def _use_config(self, config: ProjectConfig) -> None:
        kept: list[str] = []
        refused: list[tuple[str, str]] = []
        for entry in config.copybook_path:
            reason = self._refusal(Path(entry).resolve())
            if reason is None:
                kept.append(entry)
            else:
                refused.append((entry, reason))
        if refused:
            config = replace(config, copybook_path=tuple(kept))
        self.refused_copybook_dirs = tuple(refused)
        self._config = config
        self._allowed = [self.root] + [Path(p).resolve() for p in config.copybook_path]
        self._outside = [d for d in self._allowed if not _under(d, self.root)]
        # Copybook paths, source format and defines all shape a parse.
        self._cache.clear()
        self._indexes.clear()

    def callee_directories(self, response: Response) -> list[str]:
        """``cobol.yml``'s ``callee_path`` directories that are under the
        root. A callee is a whole program, not a copybook member, so a
        directory outside the root is skipped (with a caveat) rather than
        opened to reads the guard would refuse."""
        kept: list[str] = []
        skipped: list[str] = []
        for entry in self.config.callee_path:
            if _under(Path(entry).resolve(), self.root):
                kept.append(entry)
            else:
                skipped.append(entry)
        if skipped:
            response.caveat(
                "incomplete-analysis",
                "callee directories outside the workspace were not searched: "
                + ", ".join(skipped),
                "CALL arguments to programs found only there are classified "
                "without the callee's own PROCEDURE DIVISION USING",
            )
        return kept

    def under_root(self, path: Path) -> bool:
        """Whether *path*, with every link resolved, is under the root."""
        try:
            return _under(path.resolve(), self.root)
        except (OSError, RuntimeError):
            return False

    def proc_directories(self) -> tuple[list[Path], list[str]]:
        """``cobol.yml``'s ``proc_path`` directories: those under the root
        (resolved), and the entries skipped because they are not. JCL PROCs
        are read like any other workspace file, so a folder outside the root
        is not opened."""
        kept: list[Path] = []
        skipped: list[str] = []
        for entry in self.config.proc_path:
            resolved = Path(entry).resolve()
            if _under(resolved, self.root):
                kept.append(resolved)
            else:
                skipped.append(entry)
        return kept, skipped

    # -- paths ---------------------------------------------------------------

    def _within(self, path: Path) -> bool:
        """Whether *path* (resolved) may be read: anything under the root;
        under a copybook directory outside it, a copybook member only."""
        if _under(path, self.root):
            return True
        return any(self._member_of(path, base) for base in self._outside)

    @staticmethod
    def _member_of(path: Path, base: Path) -> bool:
        return (
            path != base
            and base in path.parents
            and path.suffix.lower() in COPYBOOK_MEMBER_SUFFIXES
            and not _hidden_part(path, base)
        )

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
            if any(_under(resolved, base) for base in self._outside):
                suffixes = ", ".join(
                    sorted(s or "none" for s in COPYBOOK_MEMBER_SUFFIXES)
                )
                raise ToolError(
                    f"{file} is not a copybook member: in a copybook directory "
                    "outside the workspace only files named like one (suffix "
                    f"{suffixes}; no dot-named file or directory) are readable"
                )
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
    def read_text(path: Path, warnings: list[str] | None = None) -> str:
        """A program's text, decoded the way the CLI and a copybook decode it
        (#522): the encoding detected, so a cp1252 / Latin-1 program is read
        rather than refused. A lossy decode is appended to *warnings*."""
        from ..preprocess import PreprocessingError
        from ..preprocess.copybook_expander import read_program_source

        if not path.is_file():
            raise ToolError(f"cannot read {path.name}: not a file")
        try:
            return read_program_source(str(path), warnings=warnings)
        except (OSError, PreprocessingError) as exc:
            raise ToolError(f"cannot read {path.name}: {exc}") from exc

    # -- parsing -------------------------------------------------------------

    def program(self, file: str) -> ParsedProgram:
        """The parsed program in *file*, from the cache when still current."""
        path = self.resolve(file)
        self._refuse_other_language(path)
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

    def _refuse_other_language(self, path: Path) -> None:
        """A PL/I or assembler source is no COBOL program: say which tools
        do read it rather than report a failed COBOL parse."""
        from .languages import language_of

        language = language_of(path)
        if language is None or path.suffix.lower() in self._program_suffixes():
            return
        raise ToolError(
            f"{self.display(path)} is {language} source, not COBOL: "
            "program_brief, callers_of (by program name), codebase_overview "
            "and read_source read it; the other tools are COBOL only"
        )

    def cached_or_parse(self, path: Path) -> ParsedProgram:
        """*path* parsed, from the cache when current, else parsed afresh
        WITHOUT entering the cache: a walk over the whole root must not evict
        the programs a client is asking about one at a time."""
        cached = self._cache.get(str(path))
        if cached is not None and all(
            _stamp(name) == stamp for name, stamp in cached.stamps.items()
        ):
            return cached
        return self._parse(path)

    # -- the whole root ------------------------------------------------------

    def _copybook_roots(self) -> list[Path]:
        return [Path(p).resolve() for p in self.config.copybook_path]

    def _walk(self) -> Iterator[tuple[str, list[str]]]:
        """``(directory, file names)`` under the root, sorted, skipping hidden
        directories (``.git``, ``.venv``) and copybook directories inside the
        root: a member there is not a program, whatever its suffix."""
        skip = {p for p in self._copybook_roots() if p != self.root}
        for directory, dirnames, filenames in os.walk(self.root):
            dirnames[:] = sorted(
                d
                for d in dirnames
                if not d.startswith(".") and Path(directory, d).resolve() not in skip
            )
            yield directory, sorted(filenames)

    def program_files(self) -> list[Path]:
        """Every COBOL program under the root, by ``cobol.yml``'s
        ``extensions`` (default ``.cbl``, ``.cob``, ``.cobol``), sorted."""
        return self._files_with_suffix(self._program_suffixes())

    def _program_suffixes(self) -> set[str]:
        """The suffixes :meth:`program_files` counts as programs, lowercase."""
        return {
            (e if e.startswith(".") else f".{e}").lower()
            for e in (self.config.extensions or DEFAULT_PROGRAM_EXTENSIONS)
        }

    def files_named(self, suffixes: tuple[str, ...]) -> list[Path]:
        """Files under the root whose suffix is one of *suffixes*, sorted."""
        return self._files_with_suffix(set(suffixes))

    def _files_with_suffix(self, suffixes: set[str]) -> list[Path]:
        # A symlink to a file outside the guard is skipped, exactly as
        # resolve() would refuse it when a client named it.
        found: list[Path] = []
        for directory, names in self._walk():
            for name in names:
                if Path(name).suffix.lower() not in suffixes:
                    continue
                try:
                    path = Path(directory, name).resolve()
                except (OSError, RuntimeError):
                    continue
                if self._within(path):
                    found.append(path)
        return found

    def other_sources(self) -> dict[str, list[tuple[Path, str]]]:
        """Source files under the root these tools do not parse (assembler,
        PL/I, BMS, REXX, ...), by the program names they define: the file
        stem (a load module is named after its member) plus, for assembler,
        each ``CSECT`` / ``START`` label and ``ENTRY`` name. Each value is a
        list of ``(path, language)``. A CALL to one of these names is a call
        into the workspace, not to a missing program.

        A PL/I or assembler source whose parser is installed is analyzed
        (:mod:`.languages`), so it is not one of these."""
        from .languages import LANGUAGE_SUFFIXES, parser_available

        found: dict[str, list[tuple[Path, str]]] = {}
        programs = self._program_suffixes()
        analyzed = {
            suffix
            for suffix, language in LANGUAGE_SUFFIXES.items()
            if parser_available(language)
        }
        suffixes = set(OTHER_SOURCE_LANGUAGES) - programs - analyzed
        for path in self._files_with_suffix(suffixes):
            language = OTHER_SOURCE_LANGUAGES[path.suffix.lower()]
            names = {path.stem.upper()}
            if language == "assembler":
                names |= _assembler_names(path)
            for name in names:
                found.setdefault(name, []).append((path, language))
        return found

    def has_jcl(self) -> bool:
        """Whether any JCL job or procedure file is under the root, which is
        what decides that the JCL tools are worth offering."""
        suffixes = {".jcl", ".job", ".prc", ".proc"}
        for _directory, names in self._walk():
            if any(Path(n).suffix.lower() in suffixes for n in names):
                return True
        return bool(self.config.proc_path)

    def tree_stamps(self) -> dict[str, Stamp]:
        """The stamp of every directory under the root: a file added to or
        removed from one changes its mtime, so an index built over the root
        notices a new program without re-reading every file."""
        stamps = {str(self.root): _stamp(str(self.root))}
        for directory, _names in self._walk():
            stamps[directory] = _stamp(directory)
        return stamps

    def index(
        self, name: str, build: Callable[[], tuple[Any, dict[str, Stamp]]]
    ) -> Any:
        """The cross-program index *name*, built by *build()* on first use
        and again once any file or directory it stamped has changed.

        *build* returns the index and the stamps of everything it read.
        """
        self.refresh_config()
        held = self._indexes.get(name)
        if held is not None and all(
            _stamp(path) == stamp for path, stamp in held[1].items()
        ):
            return held[0]
        with stdout_to_stderr():
            value, stamps = build()
        self._indexes[name] = (value, stamps)
        return value

    def report_progress(self, done: float, total: float | None, message: str) -> None:
        """Pass progress to whoever listens; a listener that fails (a client
        gone, a closed loop) never fails the work it reports on."""
        if self.progress is None:
            return
        try:
            self.progress(done, total, message)
        except Exception:  # noqa: BLE001 -- progress is best-effort
            self.progress = None

    def built_index(self, name: str) -> Any:
        """The index *name* as last built, or None when it never was; never
        builds, and may be stale (for hints, not answers)."""
        held = self._indexes.get(name)
        return None if held is None else held[0]

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
        from .._lines import split_source_lines
        from ..analysis.lint import source_column_offsets
        from ..layout.copybook import (
            WRAPPER_HEAD_LINES,
            wrap_copybook_fragment,
        )
        from ..parser import parse_cobol, parse_cobol_with_expansion
        from ..plugins.core import DialectType, ErrorRecoveryMode
        from ..preprocess import PreprocessingError, preprocess_conditional_compilation

        decode_warnings: list[str] = []
        source = self.read_text(path, decode_warnings)
        filename = str(path)
        # A bare copybook (``record_layout`` on a .cpy) is parsed inside the
        # same program skeleton gen-data uses, so it has records at all; its
        # lines are mapped back below (#536).  Not a program file, though: a
        # ``.cbl`` with no division header is a broken program, and wrapping
        # it would list a made-up ``COPYBOOK-LAYOUT`` program in the
        # codebase indexes instead of a file that failed to parse.
        wrapped = (
            None
            if path.suffix.lower() in self._program_suffixes()
            else wrap_copybook_fragment(source)
        )
        head_lines = fragment_lines = 0
        if wrapped is not None:
            fragment_lines = len(split_source_lines(source))
            source = wrapped
            head_lines = WRAPPER_HEAD_LINES
        format_kwargs = self._format_kwargs()
        parse_kwargs: dict[str, Any] = {
            "dialect": DialectType.IBM_ENTERPRISE,
            "error_recovery": ErrorRecoveryMode.COLLECT_ALL,
            **format_kwargs,
        }
        defines = _defined_symbols(self.config.define)
        copybook_paths = list(self.config.copybook_path)
        caveats: list[Caveat] = [
            Caveat(
                "incomplete-analysis",
                warning,
                "names or literals holding those bytes may be wrong",
            )
            for warning in decode_warnings
        ]
        if head_lines:
            caveats.append(
                Caveat(
                    "incomplete-analysis",
                    f"{self.display(path)} is a copybook, not a program: it was "
                    "parsed inside a program skeleton (PROGRAM-ID "
                    "COPYBOOK-LAYOUT, an empty PROCEDURE DIVISION)",
                    "its record layouts and declarations are exact; anything "
                    "about the program (its PROGRAM-ID, procedures, unused "
                    "variables, health) describes the skeleton, not code that "
                    "uses the copybook",
                )
            )

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
        if self.refused_copybook_dirs and any(
            c.kind == "unresolved-copybook" for c in caveats
        ):
            caveats.append(
                Caveat(
                    "unresolved-copybook",
                    "copybook directories refused, and not searched: "
                    + "; ".join(
                        f"{entry} ({reason})"
                        for entry, reason in self.refused_copybook_dirs
                    ),
                    "a member kept there is not expanded; name a directory "
                    "holding only copybooks instead",
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
        if head_lines:
            source_map = _unwrap_source_map(
                source_map, filename, head_lines, fragment_lines
            )
        files = {filename}
        if source_map:
            files.update(file for file, _ in source_map.values())
        # A member that only COPYs another adds no line to the map (#763).
        files.update(getattr(result, "expansion_copybooks", None) or [])
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
