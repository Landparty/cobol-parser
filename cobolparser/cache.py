"""Persistent content-hash cache for COBOL parse results.

The cache stores pickled :class:`ParseResult` objects on disk, keyed by a
SHA-256 digest of the source text, the transitive copybook closure, the
parser configuration, and the library version. Cache hits skip the entire
parse pipeline (preprocess + lexer + parser + AST construction), which is
the single biggest lever for batch workloads where most files are
unchanged between runs.

Layout::

    ~/.cache/cobolparser/v<__version__>/<sha256[:2]>/<sha256>.pkl[.gz]

The two-level shard (first two hex chars of the digest as a subdirectory)
keeps any single directory well below typical filesystem fan-out limits.

Compression is optional and **off by default**. Plain pickle reads back
roughly 2x faster than gzip-compressed pickle on small ASTs (the gzip
inflate step dominates for files where the parse work itself is small),
at the cost of ~3-4x more disk per entry. For codebases where cache
disk pressure matters, opt in with ``compress=True``. The library has
zero non-stdlib runtime dependencies, so ``zstandard`` isn't required —
``gzip`` is the only compression option exposed.

Cache invalidation is automatic:

* Source edits change the source hash → miss.
* Copybook edits change the transitive closure hash → miss (only for
  files that actually reference that copybook).
* Library upgrades change ``__version__`` → entire cache directory is
  ignored (old entries can be GC'd).
* Parser config changes (dialect, error_recovery, free_form) change the
  config fingerprint → miss.
"""

from __future__ import annotations

import gzip
import hashlib
import os
import pickle
import tempfile
from collections import OrderedDict
from pathlib import Path
from typing import TYPE_CHECKING

from .models.ast_base import relink_parents

if TYPE_CHECKING:
    from .parser import ParseResult
    from .plugins.core import DialectType, ErrorRecoveryMode


# Pickle protocol — protocol 5 (Python 3.8+) supports out-of-band buffers
# and is the fastest stable on-disk format.
_PICKLE_PROTOCOL = 5


def _version() -> str:
    # Deferred lookup avoids a circular import — cobolparser/__init__.py
    # imports this module via batch.py before __version__ is bound at the
    # top level. Function-scope import is cheap (sys.modules cache).
    from . import __version__

    return __version__


def make_config_fingerprint(
    *,
    dialect: DialectType,
    error_recovery: ErrorRecoveryMode,
    free_form: bool,
) -> str:
    """Stable string identifying a parser configuration.

    Any change that could produce a different AST for the same source must
    flip this fingerprint. Enum values are stringified via ``.value`` to
    avoid binding to the enum's repr (which can change across versions).
    """
    return f"d={dialect.value}|e={error_recovery.value}|f={int(free_form)}"


def _hash_source(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8", errors="replace")).hexdigest()


def _hash_file(path: str | os.PathLike[str]) -> str:
    """Hash a file's bytes. Returns an empty hex string on read failure so
    a missing/unreadable copybook still produces a stable key — the parse
    itself will surface the real error."""
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
    except OSError:
        return ""
    return h.hexdigest()


def make_cache_key(
    *,
    source: str,
    config_fingerprint: str,
    copybook_files: list[str] | None = None,
) -> str:
    """Compute the content-hash cache key for a parse invocation.

    The key incorporates:

    * Library version (``__version__``) — bumping the version invalidates
      the entire cache, which is the correct behaviour when the AST shape
      may have changed.
    * Configuration fingerprint (from :func:`make_config_fingerprint`).
    * SHA-256 of the source text.
    * SHA-256 of each transitively-included copybook file (in resolution
      order), so editing a copybook invalidates dependents only.
    """
    h = hashlib.sha256()
    h.update(_version().encode("ascii"))
    h.update(b"\0")
    h.update(config_fingerprint.encode("utf-8"))
    h.update(b"\0")
    h.update(_hash_source(source).encode("ascii"))
    if copybook_files:
        for cb in copybook_files:
            h.update(b"\0")
            h.update(cb.encode("utf-8", errors="replace"))
            h.update(b"=")
            h.update(_hash_file(cb).encode("ascii"))
    return h.hexdigest()


def default_cache_dir() -> Path:
    """Resolve the on-disk cache root.

    Honours ``COBOLPARSER_CACHE_DIR`` for explicit control, otherwise
    falls back to ``$XDG_CACHE_HOME/cobolparser`` or ``~/.cache/cobolparser``.
    The version is appended so old caches are ignored after upgrades.
    """
    override = os.environ.get("COBOLPARSER_CACHE_DIR")
    if override:
        base = Path(override)
    else:
        xdg = os.environ.get("XDG_CACHE_HOME")
        if xdg:
            base = Path(xdg) / "cobolparser"
        else:
            base = Path.home() / ".cache" / "cobolparser"
    return base / f"v{_version()}"


class ParseCache:
    """Two-tier (in-memory + on-disk) parse-result cache.

    The on-disk tier is the durable store; the in-memory tier is a small
    LRU that avoids re-reading and re-unpickling hot files within a
    single process. Both tiers are keyed by the same SHA-256 hex digest
    produced by :func:`make_cache_key`.

    Thread-safety: the in-memory LRU is **not** thread-safe — callers
    that share a cache instance across threads should add their own
    lock or use one instance per thread. Disk operations are atomic
    (write-then-rename) and safe for multiple processes writing the
    same key simultaneously.
    """

    def __init__(
        self,
        cache_dir: str | os.PathLike[str] | None = None,
        *,
        compress: bool = False,
        max_memory_entries: int = 128,
        enabled: bool = True,
    ) -> None:
        self.root = Path(cache_dir) if cache_dir is not None else default_cache_dir()
        self.compress = compress
        self.enabled = enabled
        self._mem: OrderedDict[str, ParseResult] = OrderedDict()
        self._mem_max = max_memory_entries
        self.hits = 0
        self.misses = 0
        self.writes = 0

    # -- Path layout -------------------------------------------------------

    def _shard_dir(self, key: str) -> Path:
        return self.root / key[:2]

    def _path(self, key: str) -> Path:
        suffix = ".pkl.gz" if self.compress else ".pkl"
        return self._shard_dir(key) / f"{key}{suffix}"

    # -- Lookup ------------------------------------------------------------

    def get(self, key: str) -> ParseResult | None:
        """Return the cached :class:`ParseResult`, or ``None`` on miss.

        On hit, parent back-references on the AST are rebuilt before
        returning so consumers that walk via ``node.parent`` see the
        expected topology.
        """
        if not self.enabled:
            return None

        cached = self._mem.get(key)
        if cached is not None:
            self._mem.move_to_end(key)
            self.hits += 1
            return cached

        path = self._path(key)
        if not path.exists():
            self.misses += 1
            return None

        try:
            if self.compress:
                with gzip.open(path, "rb") as gz:
                    result: ParseResult = pickle.load(gz)
            else:
                with open(path, "rb") as f:
                    result = pickle.load(f)
        except (OSError, pickle.UnpicklingError, EOFError):
            # Corrupt or partially-written entry — treat as miss and
            # leave the file in place; next put() will overwrite atomically.
            self.misses += 1
            return None

        # Validate that the unpickled object is actually a ParseResult
        # before dereferencing its fields. Gracefully treat unexpected
        # types (stale/manual writes or corruption that still unpickles)
        # as a cache miss rather than crashing.
        if not hasattr(result, "ast") or not hasattr(result, "errors"):
            self.misses += 1
            return None

        # Rebuild parent links stripped by ASTNode.__getstate__.
        if result.ast is not None:
            result.ast.parent = None
            relink_parents(result.ast)

        self._mem_put(key, result)
        self.hits += 1
        return result

    # -- Insert ------------------------------------------------------------

    def put(self, key: str, result: ParseResult) -> None:
        """Store *result* under *key*. Write is atomic (tmp + rename)."""
        if not self.enabled:
            return

        self._mem_put(key, result)

        shard = self._shard_dir(key)
        try:
            shard.mkdir(parents=True, exist_ok=True)
        except OSError:
            return

        final = self._path(key)
        # Atomic write: pickle to a sibling tmp file, then rename. Rename
        # is atomic on POSIX and best-effort on Windows; partial writes
        # never replace a valid entry.
        try:
            fd, tmp_name = tempfile.mkstemp(
                prefix=f"{key}.", suffix=".tmp", dir=str(shard)
            )
            try:
                with os.fdopen(fd, "wb") as raw:
                    if self.compress:
                        with gzip.GzipFile(
                            fileobj=raw, mode="wb", compresslevel=3, mtime=0
                        ) as gz:
                            pickle.dump(result, gz, protocol=_PICKLE_PROTOCOL)
                    else:
                        pickle.dump(result, raw, protocol=_PICKLE_PROTOCOL)
                os.replace(tmp_name, final)
            except BaseException:
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass
                raise
        except (OSError, pickle.PicklingError):
            # Cache writes are best-effort; never let cache failures
            # propagate into a parse pipeline.
            return

        self.writes += 1

    # -- Maintenance -------------------------------------------------------

    def clear_memory(self) -> None:
        """Drop the in-memory tier (keeps on-disk entries)."""
        self._mem.clear()

    def stats(self) -> dict[str, int]:
        return {
            "hits": self.hits,
            "misses": self.misses,
            "writes": self.writes,
            "memory_entries": len(self._mem),
        }

    # -- Internal ----------------------------------------------------------

    def _mem_put(self, key: str, result: ParseResult) -> None:
        if key in self._mem:
            self._mem.move_to_end(key)
            self._mem[key] = result
            return
        if len(self._mem) >= self._mem_max:
            self._mem.popitem(last=False)
        self._mem[key] = result


__all__ = [
    "ParseCache",
    "make_cache_key",
    "make_config_fingerprint",
    "default_cache_dir",
]
