"""AST completeness over open-source COBOL: the ratchet over ``tools/corpus``.

``tools/corpus/run.py`` parses every program of the corpus listed in
``tools/corpus/manifest.toml`` and diffs the AST against an independent
census of the source (statements per verb, paragraph and section names, data
entries). ``tools/corpus/baseline.json`` records every file that is not clean
today. These tests fail when a file gets worse than its baseline entry -- a
clean file starts dropping a statement, a file gains an error -- and pass
when files improve (refresh the baseline with ``--write-baseline`` then).

The NIST COBOL-85 suite is vendored in ``examples/cobol``, so that check
always runs. The rest of the corpus is fetched, never vendored
(``python tools/corpus/fetch.py``); its check runs only when the cache exists
(``.corpus/`` or ``$COBOLPARSER_CORPUS``).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.slow

REPO = Path(__file__).resolve().parents[2]
CORPUS_TOOLS = REPO / "tools" / "corpus"
sys.path.insert(0, str(CORPUS_TOOLS))

import run as corpus_run  # noqa: E402

CORPUS_DIR = Path(os.environ.get("COBOLPARSER_CORPUS", REPO / ".corpus"))


def _check(only: list[str] | None, dest: Path) -> tuple[list[str], int]:
    jobs = corpus_run.collect_jobs(dest, only, timeout=120)
    results = corpus_run.run(jobs, workers=min(4, os.cpu_count() or 1))
    baseline = json.loads(corpus_run.BASELINE.read_text())
    regressions, _ = corpus_run.compare_baseline(results, baseline)
    return regressions, len(results)


def test_nist_suite_is_no_worse_than_baseline() -> None:
    regressions, checked = _check(["nist-cobol85"], CORPUS_DIR)
    assert checked > 400
    assert not regressions, "\n".join(regressions)


@pytest.mark.skipif(
    not CORPUS_DIR.is_dir(),
    reason="open-source corpus not fetched (python tools/corpus/fetch.py)",
)
def test_fetched_corpus_is_no_worse_than_baseline() -> None:
    regressions, checked = _check(None, CORPUS_DIR)
    assert checked > 400
    assert not regressions, "\n".join(regressions)


def test_baseline_lists_only_known_sources() -> None:
    ids = {s["id"] for s in corpus_run.load_manifest()}
    baseline = json.loads(corpus_run.BASELINE.read_text())
    assert {path.split("/", 1)[0] for path in baseline} <= ids
