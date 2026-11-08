"""Per-file facts behind the root-wide indexes: one parse feeds them all,
in parallel, kept on disk between server starts.

Each cross-program index (``programs``, ``lineage``, ``health``,
``statements``) used to walk the root and parse every program itself, so
the first overview, the first ``where_from`` and the first statement search
each paid a full parse of the root, and a restarted server paid it all
again: on a 500-program checkout, about 70 seconds before the first
whole-codebase answer.

Now a program file is parsed once and everything any index needs from it is
taken from that one parse (:class:`FileFacts`): its units and CALLs, its
part of the CALL / COPY graph, its field-flow reports, its health and clone
fingerprints, its statements. Facts are kept per file, with the stamps of
everything the parse read, so after an edit only the changed files are
parsed again; the indexes are then assembled from facts, which takes a
fraction of a second.

* **Parallel.** Facts of many files are computed in worker processes
  (:func:`_worker_facts`; ``--workers``), each with its own
  :class:`~.workspace.Workspace` over the same root and config, whose stdout
  is sent to stderr (over stdio, stdout is the protocol).
* **On disk.** With a cache directory (``--cache-dir``; the CLI's default is
  under the user cache directory, never under the root), facts are pickled
  to one file per root and config and read back at the next start, so a
  restarted server answers its first whole-codebase question without a
  parse. A file that changed meanwhile is parsed again; a version or config
  change starts afresh. The cache is only ever read from a directory the
  user chose: a repository can never plant one.
* **Warm-up.** :meth:`FactsStore.warm` computes every file's facts in the
  background right after the server starts, so most of the work is done by
  the time a client asks.
"""

from __future__ import annotations

import contextlib
import dataclasses
import functools
import hashlib
import os
import pickle
import sys
import tempfile
import threading
import time
from collections.abc import Iterable
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .envelope import Caveat, Response, ToolError
from .workspace import ParsedProgram, Stamp, Workspace, _stamp

#: Bumped whenever :class:`FileFacts` or anything it holds changes shape:
#: facts on disk from another version are never read.
FACTS_VERSION = "9"

#: The fields only the lineage and statement indexes read. They are most of
#: the bytes of a file's facts (a field-flow report per unit), so on disk they
#: are kept apart, one shard per file, and read back only when one of those
#: indexes is built: a restarted server answers a call-graph or JCL question
#: without unpickling every program's lineage first.
HEAVY_FIELDS = ("lineage", "lineage_problems", "statements")

#: Below this many files to compute, a pool costs more than it saves.
PARALLEL_THRESHOLD = 12

#: Default worker processes: the CPUs, at most this many.
MAX_DEFAULT_WORKERS = 8


@dataclass
class LineageFacts:
    """One unit's field-flow report, as the ``lineage`` index joins it."""

    program: str
    report: dict[str, Any]
    #: ((PROGRAM-ID, line, edge kind, statement), file) of every edge.
    edge_files: list[tuple[tuple[str, int, str, str], str]] = field(
        default_factory=list
    )


@dataclass
class FileFacts:
    """Everything the root-wide indexes take from one program file."""

    path: str
    display: str
    #: (mtime_ns, size) of every file and directory the parse read.
    stamps: dict[str, Stamp] = field(default_factory=dict)
    #: Why the file produced no program at all (then only graph_part is set).
    failed: str | None = None
    caveats: list[Caveat] = field(default_factory=list)
    units: list[Any] = field(default_factory=list)  # codebase_index.UnitFacts
    graph_part: Any = None  # analysis.codebase.GraphPart
    expanded: bool = False
    lineage: list[LineageFacts] = field(default_factory=list)
    lineage_problems: list[str] = field(default_factory=list)
    #: {program, unit_kind, file, depth, grade, score} per unit.
    health: list[dict[str, Any]] = field(default_factory=list)
    #: (unit name, depth, redundancy fingerprints) per unit.
    fingerprints: list[tuple[str, int, dict[str, Any]]] = field(default_factory=list)
    statements: list[Any] = field(default_factory=list)  # navigation.StatementRow
    #: False while the :data:`HEAVY_FIELDS` are on disk, not in memory.
    heavy: bool = True

    def current(self) -> bool:
        return all(_stamp(name) == stamp for name, stamp in self.stamps.items())

    def note(self, caveat: Caveat) -> None:
        if caveat not in self.caveats:
            self.caveats.append(caveat)


def _failed(facts: FileFacts, what: str, exc: Exception) -> None:
    facts.note(
        Caveat(
            "analyzer-failed",
            f"{facts.display}: {what} could not be analyzed: "
            f"{type(exc).__name__}: {exc}",
            f"cross-program answers miss what {facts.display} would add",
        )
    )


def compute_facts(workspace: Workspace, path: Path, builder: Any) -> FileFacts:
    """The facts of program file *path*, from one parse. *builder* is the
    :class:`~cobolparser.analysis.codebase.CodebaseGraphBuilder` whose
    :meth:`absorb` gives the file's graph part."""
    from ..batch import BatchResult

    display = workspace.display(path)
    facts = FileFacts(path=str(path), display=display)
    try:
        parsed = workspace.cached_or_parse(path)
    except Exception as exc:  # noqa: BLE001 -- one file must not sink the root
        facts.failed = (
            str(exc) if isinstance(exc, ToolError) else f"{type(exc).__name__}: {exc}"
        )
        facts.stamps[str(path)] = _stamp(str(path))
        facts.graph_part = builder.absorb(
            BatchResult(path=Path(str(path)), result=None, read_error=facts.failed)
        )
        return facts
    facts.stamps.update(parsed.stamps)
    facts.expanded = bool(parsed.source_map)
    for caveat in parsed.caveats:
        facts.note(caveat)
    facts.graph_part = builder.absorb(
        BatchResult(path=Path(str(path)), result=parsed.result, read_error=None)
    )
    _unit_facts(workspace, parsed, facts)
    _lineage_facts(workspace, parsed, facts)
    _health_facts(parsed, facts)
    _statement_facts(workspace, parsed, facts)
    return facts


def _unit_facts(workspace: Workspace, parsed: ParsedProgram, facts: FileFacts) -> None:
    from ..analysis.codebase import program_graph_ids
    from .codebase_index import (
        UnitFacts,
        _entry_names,
        _units_with_depth,
        unit_commarea,
        unit_services,
    )
    from .tools.brief import _calls
    from .tools.common import _flow

    response = Response()
    graph_ids = program_graph_ids(parsed.ast.program_units(), facts.path)
    for unit, depth in _units_with_depth(parsed.ast):
        unit_facts = UnitFacts(
            program_id=unit.program_name or "",
            file=facts.display,
            depth=depth,
            unit_kind=unit.unit_kind,
            graph_id=graph_ids.get(id(unit), ""),
            entries=_entry_names(unit),
        )
        try:
            unit_facts.calls = _calls(parsed, unit, _flow(parsed, unit), response)
        except Exception as exc:  # noqa: BLE001
            _failed(facts, "called programs", exc)
        try:
            unit_facts.services = unit_services(unit)
            unit_facts.commarea = unit_commarea(unit)
        except Exception as exc:  # noqa: BLE001
            _failed(facts, "services", exc)
        facts.units.append(unit_facts)
    for caveat in response.caveats:
        facts.note(caveat)


def _lineage_facts(
    workspace: Workspace, parsed: ParsedProgram, facts: FileFacts
) -> None:
    from ..analysis.field_lineage import apply_source_map
    from .codebase_index import _field_flow, _units_with_depth

    for unit, _depth in _units_with_depth(parsed.ast):
        name = unit.program_name or "<unnamed>"
        try:
            report = parsed.report(
                "lineage", unit, functools.partial(_field_flow, unit)
            )
            report = apply_source_map(report, parsed.source_map)
        except Exception as exc:  # noqa: BLE001
            _failed(facts, f"field lineage of {name}", exc)
            facts.lineage_problems.append(f"{facts.display}: {name}: no lineage report")
            continue
        data = report.to_dict()
        program = str(data.get("program_id") or "").upper()
        entry = LineageFacts(program=program, report=data)
        for edge in report.edges:
            line = edge.origin_line or edge.line
            if not line:
                continue
            file = (
                workspace.display(edge.origin_file)
                if edge.origin_file
                else facts.display
            )
            entry.edge_files.append(((program, line, edge.kind, edge.statement), file))
        facts.lineage.append(entry)


def _health_facts(parsed: ParsedProgram, facts: FileFacts) -> None:
    from ..analysis.lint import stamp_report_origins
    from ..scan import _stamp_body_origins
    from .codebase_index import _debt, _redundancy, _units_with_depth

    for unit, depth in _units_with_depth(parsed.ast):
        name = unit.program_name or "<unnamed>"
        try:
            redundancy = parsed.report(
                "redundancy", unit, functools.partial(_redundancy, unit)
            )
            debt = parsed.report(
                "debt", unit, functools.partial(_debt, parsed, unit, redundancy)
            )
        except Exception as exc:  # noqa: BLE001
            _failed(facts, f"health of {name}", exc)
            continue
        facts.health.append(
            {
                "program": unit.program_name,
                "unit_kind": unit.unit_kind,
                "file": facts.display,
                "depth": depth,
                "grade": debt.grade,
                "score": debt.score,
            }
        )
        fingerprints = stamp_report_origins(redundancy.to_dict(), parsed.source_map)
        if parsed.source_map:
            # A body COPYed under each program's own header is one source,
            # as in ``scan`` (#470).
            _stamp_body_origins(fingerprints, parsed.source_map)
        facts.fingerprints.append((name, depth, fingerprints))


def _statement_facts(
    workspace: Workspace, parsed: ParsedProgram, facts: FileFacts
) -> None:
    from .navigation import _Lines, statement_rows

    response = Response()
    try:
        facts.statements = list(statement_rows(parsed, _Lines(workspace), response))
    except Exception as exc:  # noqa: BLE001
        _failed(facts, "statements", exc)
    for caveat in response.caveats:
        facts.note(caveat)


# ---------------------------------------------------------------------------
# Worker processes
# ---------------------------------------------------------------------------

_WORKER: dict[str, Any] = {}


def _init_worker(root: str, config: Any) -> None:
    """A worker's own workspace over the same root and (already vetted)
    config; its stdout goes to stderr, never to the protocol channel."""
    with contextlib.suppress(OSError, ValueError):
        os.dup2(2, 1)
    sys.stdout = sys.stderr
    from ..analysis.codebase import CodebaseGraphBuilder

    workspace = Workspace(root, config, cache_size=1)
    builder = CodebaseGraphBuilder(copybook_paths=list(workspace.config.copybook_path))
    builder.begin_build()
    _WORKER["workspace"] = workspace
    _WORKER["builder"] = builder


def _worker_facts(path: str) -> FileFacts:
    from .workspace import stdout_to_stderr

    with stdout_to_stderr():
        return compute_facts(_WORKER["workspace"], Path(path), _WORKER["builder"])


# ---------------------------------------------------------------------------
# The store
# ---------------------------------------------------------------------------


def default_workers() -> int:
    return max(1, min(os.cpu_count() or 1, MAX_DEFAULT_WORKERS))


def default_cache_dir() -> Path:
    """Where the CLI keeps facts: ``$XDG_CACHE_HOME`` (else ``~/.cache``)
    ``/cobol-parser/mcp``. Never under a workspace root."""
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "cobol-parser" / "mcp"


class FactsStore:
    """Per-file facts of one workspace, current ones kept, the rest
    recomputed (in parallel when there are many) and saved to disk."""

    def __init__(
        self,
        workspace: Workspace,
        *,
        workers: int | None = None,
        cache_dir: str | Path | None = None,
    ) -> None:
        self.workspace = workspace
        self.workers = default_workers() if workers is None else max(1, workers)
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.lock = threading.Lock()
        self._facts: dict[str, FileFacts] = {}
        #: Files whose heavy fields were computed since the last save.
        self._heavy_dirty: set[str] = set()
        self._key: str | None = None
        self._loaded = False
        #: Set while a pool computes facts outside :attr:`Workspace.lock`.
        self._busy = threading.Event()
        self._busy.set()
        #: Seconds the last compute took, and how many files it parsed.
        self.last_compute: tuple[float, int] = (0.0, 0)

    # -- identity -------------------------------------------------------------

    def _config_key(self) -> str:
        from .._version import __version__

        config = self.workspace.config
        text = repr(
            (
                FACTS_VERSION,
                __version__,
                sys.version_info[:2],
                str(self.workspace.root),
                config.copybook_path,
                config.source_format,
                config.debug_lines,
                config.define,
                config.extensions,
                config.dialect,
                getattr(config, "encoding", None),
            )
        )
        return hashlib.sha256(text.encode()).hexdigest()[:24]

    def _cache_file(self) -> Path | None:
        if self.cache_dir is None:
            return None
        root = hashlib.sha256(str(self.workspace.root).encode()).hexdigest()[:16]
        return self.cache_dir / f"facts-{root}.pickle"

    # -- disk -----------------------------------------------------------------

    def _load(self, key: str) -> None:
        self._loaded = True
        cache = self._cache_file()
        if cache is None or not cache.is_file():
            return
        try:
            with cache.open("rb") as handle:
                held = pickle.load(handle)  # noqa: S301 -- our own cache dir
        except Exception:  # noqa: BLE001 -- a bad cache is no cache
            return
        if isinstance(held, dict) and held.get("key") == key:
            facts = held.get("facts")
            if isinstance(facts, dict):
                self._facts = facts

    def _shard_file(self, path: str) -> Path | None:
        cache = self._cache_file()
        if cache is None:
            return None
        name = hashlib.sha256(path.encode()).hexdigest()[:24]
        return cache.with_suffix(".d") / f"{name}.pickle"

    def _load_heavy(self, facts: FileFacts) -> bool:
        """Put *facts*' heavy fields back from its shard; False when the
        shard is missing or was written for other stamps or settings."""
        shard = self._shard_file(facts.path)
        if shard is None or not shard.is_file():
            return False
        try:
            with shard.open("rb") as handle:
                held = pickle.load(handle)  # noqa: S301 -- our own cache dir
        except Exception:  # noqa: BLE001 -- a bad shard is no shard
            return False
        if (
            not isinstance(held, dict)
            or held.get("key") != self._key
            or held.get("stamps") != facts.stamps
        ):
            return False
        for name in HEAVY_FIELDS:
            setattr(facts, name, held.get(name) or [])
        facts.heavy = True
        return True

    def _save(self) -> None:
        cache = self._cache_file()
        if cache is None:
            return
        try:
            cache.parent.mkdir(parents=True, exist_ok=True)
            for path in sorted(self._heavy_dirty):
                facts = self._facts.get(path)
                shard = self._shard_file(path)
                if facts is None or not facts.heavy or shard is None:
                    continue
                shard.parent.mkdir(parents=True, exist_ok=True)
                held = {"key": self._key, "stamps": facts.stamps}
                held.update({name: getattr(facts, name) for name in HEAVY_FIELDS})
                _write_atomic(shard, held)
            self._heavy_dirty.clear()
            core = {
                path: dataclasses.replace(
                    facts, lineage=[], lineage_problems=[], statements=[], heavy=False
                )
                for path, facts in self._facts.items()
            }
            _write_atomic(cache, {"key": self._key, "facts": core})
        except Exception:  # noqa: BLE001 -- a cache that cannot be written is
            # a slower next start, never a failed call.
            pass

    def load_extra(self, name: str) -> Any:
        """What :meth:`save_extra` last kept as *name* under the current
        settings, or None."""
        cache = self._cache_file()
        if cache is None:
            return None
        target = cache.with_name(f"{cache.stem}-{name}.pickle")
        if not target.is_file():
            return None
        try:
            with target.open("rb") as handle:
                held = pickle.load(handle)  # noqa: S301 -- our own cache dir
        except Exception:  # noqa: BLE001 -- a bad cache is no cache
            return None
        if isinstance(held, dict) and held.get("key") == self._config_key():
            return held.get("value")
        return None

    def save_extra(self, name: str, value: Any) -> None:
        """Keep *value* on disk as *name* (beside the facts) for the next
        start; best-effort, like the facts themselves."""
        cache = self._cache_file()
        if cache is None:
            return
        try:
            cache.parent.mkdir(parents=True, exist_ok=True)
            _write_atomic(
                cache.with_name(f"{cache.stem}-{name}.pickle"),
                {"key": self._config_key(), "value": value},
            )
        except Exception:  # noqa: BLE001
            pass

    # -- facts ----------------------------------------------------------------

    def facts(
        self, paths: list[Path] | None = None, *, heavy: bool = False
    ) -> list[FileFacts]:
        """Current facts of every program file (or of *paths*), in order;
        with *heavy*, their :data:`HEAVY_FIELDS` too."""
        # A warm-up running in a pool finishes first: computing the same
        # files again here would only double the work.
        self._busy.wait()
        with self.lock:
            return self._facts_locked(paths, heavy=heavy)

    def _facts_locked(
        self, paths: list[Path] | None, *, heavy: bool = False
    ) -> list[FileFacts]:
        key = self._config_key()
        if key != self._key:
            if self._key is not None:
                self._facts = {}
            self._key = key
            if not self._loaded:
                self._load(key)
        wanted = [
            str(p)
            for p in (paths if paths is not None else self.workspace.program_files())
        ]
        stale = [
            p for p in wanted if p not in self._facts or not self._facts[p].current()
        ]
        if heavy:
            stale_set = set(stale)
            stale += [
                p
                for p in wanted
                if p not in stale_set
                and not self._facts[p].heavy
                and not self._load_heavy(self._facts[p])
            ]
        if stale:
            self._compute(stale)
        changed = bool(stale)
        # Files no longer under the root are dropped, so the cache does not
        # grow with every rename.
        if paths is None:
            gone = set(self._facts) - set(wanted)
            for old in gone:
                del self._facts[old]
            changed = changed or bool(gone)
        if changed:
            self._save()
        return [self._facts[p] for p in wanted]

    def _compute(self, stale: list[str], *, report: bool = True) -> None:
        started = time.monotonic()
        total = len(stale)
        done = 0

        def progress(display: str) -> None:
            if report:
                self.workspace.report_progress(done, total, f"reading {display}")

        if self.workers > 1 and total >= PARALLEL_THRESHOLD:
            for facts in self._in_pool(stale):
                self._facts[facts.path] = facts
                self._heavy_dirty.add(facts.path)
                done += 1
                progress(facts.display)
        else:
            from ..analysis.codebase import CodebaseGraphBuilder
            from .workspace import stdout_to_stderr

            builder = CodebaseGraphBuilder(
                copybook_paths=list(self.workspace.config.copybook_path)
            )
            builder.begin_build()
            for path in stale:
                progress(self.workspace.display(Path(path)))
                with stdout_to_stderr():
                    facts = compute_facts(self.workspace, Path(path), builder)
                self._facts[path] = facts
                self._heavy_dirty.add(path)
                done += 1
        self.last_compute = (time.monotonic() - started, total)

    def _in_pool(self, stale: list[str]) -> Iterable[FileFacts]:
        import multiprocessing

        context = multiprocessing.get_context("spawn")
        with ProcessPoolExecutor(
            max_workers=min(self.workers, len(stale)),
            mp_context=context,
            initializer=_init_worker,
            initargs=(str(self.workspace.root), self.workspace.config),
        ) as pool:
            futures = {pool.submit(_worker_facts, path): path for path in stale}
            for future in as_completed(futures):
                path = futures[future]
                try:
                    yield future.result()
                except Exception as exc:  # noqa: BLE001 -- a dead worker
                    # costs that file, never the index.
                    from ..analysis.codebase import CodebaseGraphBuilder
                    from ..batch import BatchResult

                    reason = f"{type(exc).__name__}: {exc}"
                    builder = CodebaseGraphBuilder(
                        copybook_paths=list(self.workspace.config.copybook_path)
                    )
                    builder.begin_build()
                    yield FileFacts(
                        path=path,
                        display=self.workspace.display(Path(path)),
                        stamps={path: _stamp(path)},
                        failed=reason,
                        graph_part=builder.absorb(
                            BatchResult(path=Path(path), result=None, read_error=reason)
                        ),
                    )

    # -- warm-up ----------------------------------------------------------------

    def warm(self) -> threading.Thread | None:
        """Start computing every file's facts in the background; the thread,
        or None when there is nothing to do."""

        def run() -> None:
            try:
                with self.workspace.lock:
                    paths = [str(p) for p in self.workspace.program_files()]
                    key = self._config_key()
                with self.lock:
                    if key != self._key:
                        self._key = key
                        if not self._loaded:
                            self._load(key)
                    stale = [
                        p
                        for p in paths
                        if p not in self._facts or not self._facts[p].current()
                    ]
                    if not stale:
                        return
                    pooled = self.workers > 1 and len(stale) >= PARALLEL_THRESHOLD
                    if pooled:
                        # Outside Workspace.lock: tool calls that need no
                        # facts go on meanwhile; one that does waits here.
                        self._busy.clear()
                        try:
                            self._compute(stale, report=False)
                        finally:
                            self._busy.set()
                        self._save()
                        return
                # One file at a time under both locks, so tool calls
                # interleave with the warm-up rather than wait for it.
                for path in stale:
                    with self.workspace.lock, self.lock:
                        held = self._facts.get(path)
                        if held is None or not held.current():
                            self._compute([path], report=False)
                with self.lock:
                    self._save()
            except Exception:  # noqa: BLE001 -- warm-up is best-effort
                self._busy.set()

        thread = threading.Thread(target=run, name="cobol-facts-warmup", daemon=True)
        thread.start()
        return thread


def _write_atomic(target: Path, value: Any) -> None:
    """Pickle *value* to *target* through a temporary file in its folder."""
    handle = tempfile.NamedTemporaryFile(
        "wb", dir=target.parent, delete=False, suffix=".tmp"
    )
    try:
        with handle:
            pickle.dump(value, handle, protocol=pickle.HIGHEST_PROTOCOL)
        os.replace(handle.name, target)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(handle.name)
        raise


def store_for(workspace: Workspace) -> FactsStore:
    """The workspace's facts store, made with its defaults on first use."""
    store = getattr(workspace, "facts_store", None)
    if store is None:
        store = FactsStore(workspace, workers=1)
        workspace.facts_store = store
    return store


def surveyed(
    workspace: Workspace,
    survey: Any,
    stamps: dict[str, Stamp],
    *,
    heavy: bool = False,
) -> list[FileFacts]:
    """Every program file's facts, recorded in *survey* (files, failures,
    caveats) and *stamps* as the walk used to record them; with *heavy*,
    their lineage and statements too."""
    all_facts = store_for(workspace).facts(heavy=heavy)
    for facts in all_facts:
        survey.files.append(facts.display)
        stamps.update(facts.stamps)
        if facts.failed is not None:
            survey.failed[facts.display] = facts.failed
        for caveat in facts.caveats:
            survey.note(facts.display, caveat)
    return all_facts
