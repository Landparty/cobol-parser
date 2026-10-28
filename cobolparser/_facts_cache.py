"""An on-disk cache of per-file analysis facts, for runs over many files.

``scan`` and the MCP server's root-wide indexes parse and analyze every
program under a tree, and most of that work comes out the same as last time:
a shop edits a few programs a day. :class:`FactsCache` keeps what one file
produced (a JSON-serializable value: a scan's per-file report, an index's
per-file facts) next to the stamp of every file and directory that went into
it, and hands it back only while all of those stamps still match.

A stamp is ``(mtime_ns, size)``, or None for a path that did not exist --
the same stamp the MCP server's in-memory caches already invalidate on. The
directories are stamped too: a COPY member that was missing, or one added
earlier on the search path that would now shadow the member used, is a new
directory entry, which changes its directory's mtime even though no file the
parse read did.

The key covers everything else that changes the answer: the package version
(so an upgrade never serves an old analysis), the caller's namespace and
settings (copybook paths, ``>>DEFINE`` symbols, source format, the analyzers
run) and the file's absolute path. Entries are written atomically (a
temporary file renamed over the entry), so worker processes may share one
directory, and a corrupt or unreadable entry is a miss, never an error: the
cache can only ever cost a re-run.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Iterable
from pathlib import Path
from typing import Any

#: Bumped when the entry layout changes.
CACHE_FORMAT = 1

Stamp = tuple[int, int] | None


def stamp(path: str) -> Stamp:
    """``(mtime_ns, size)`` of *path*, or None when it does not exist."""
    try:
        info = os.stat(path)
    except OSError:
        return None
    return (info.st_mtime_ns, info.st_size)


def directory_stamps(directories: Iterable[str]) -> dict[str, Stamp]:
    """The stamp of each directory and of each subdirectory directly in it
    (``COPY X OF LIB`` searches one level down)."""
    out: dict[str, Stamp] = {}
    for base in directories:
        out[str(base)] = stamp(str(base))
        try:
            entries = list(os.scandir(base))
        except OSError:
            continue
        for entry in entries:
            if entry.is_dir():
                out[entry.path] = stamp(entry.path)
    return out


class FactsCache:
    """Per-file facts under *directory*, for one *namespace* and *settings*.

    *settings* is anything with a stable ``repr`` (a tuple, a frozen
    dataclass): two runs share entries only when it is equal.
    """

    def __init__(self, directory: str | Path, namespace: str, settings: Any) -> None:
        from . import __version__

        self.directory = Path(directory) / namespace
        self._prefix = json.dumps(
            [CACHE_FORMAT, __version__, namespace, repr(settings)]
        )
        self.hits = 0
        self.misses = 0

    def _entry(self, path: str) -> Path:
        digest = hashlib.sha256(
            (self._prefix + "\0" + os.path.abspath(path)).encode("utf-8")
        ).hexdigest()
        return self.directory / digest[:2] / f"{digest}.json"

    def get(self, path: str) -> Any | None:
        """The facts stored for *path*, or None when there are none or any
        file or directory they were computed from has changed since."""
        try:
            with open(self._entry(path), encoding="utf-8") as handle:
                entry = json.load(handle)
            stamps = entry["stamps"]
            facts = entry["facts"]
        except (OSError, ValueError, KeyError, TypeError):
            self.misses += 1
            return None
        for name, held in stamps.items():
            current = stamp(name)
            if (list(current) if current is not None else None) != held:
                self.misses += 1
                return None
        self.hits += 1
        return facts

    def put(self, path: str, facts: Any, stamps: dict[str, Stamp]) -> None:
        """Store *facts* for *path*, valid while every one of *stamps* holds.
        A write that fails is ignored: the cache is an optimization."""
        target = self._entry(path)
        entry = {
            "path": os.path.abspath(path),
            "stamps": {
                name: (list(value) if value is not None else None)
                for name, value in stamps.items()
            },
            "facts": facts,
        }
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            handle, temporary = tempfile.mkstemp(dir=target.parent, suffix=".tmp")
            try:
                with os.fdopen(handle, "w", encoding="utf-8") as out:
                    json.dump(entry, out)
                os.replace(temporary, target)
            except BaseException:
                os.unlink(temporary)
                raise
        except (OSError, TypeError, ValueError):
            pass
