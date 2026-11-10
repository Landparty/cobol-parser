"""Run the AST completeness check over the fetched open-source COBOL corpus.

Usage::

    python tools/corpus/fetch.py                      # once
    python tools/corpus/run.py                        # every source
    python tools/corpus/run.py --only carddemo -j 8 --json out.json --md out.md

For each program the harness expands copybooks (missing members are left as
written and reported), parses the expanded text with error recovery set to
collect-all, and diffs the AST against an independent census of the same
text (``census.py``): statements per verb, paragraph and section names, data
description entries. A file is one of:

``clean``      no errors, no dropped-content warnings, census and AST agree
``crash``      the parser raised, or returned no AST
``timeout``    the parse took longer than ``--timeout`` seconds
``errors``     the parser reported errors
``dropped``    a warning says content was dropped from the AST
``mismatch``   no diagnostics, but the AST and the census disagree -- the
               silent-loss case this harness exists for
``unchecked``  the comparison is unreliable (unexpanded COPY, REPLACE), and
               there were no errors

Exit status is 0 unless ``--fail-on`` names a status that occurred.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import sys
import time
import traceback
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from ast_census import ast_census  # noqa: E402
from census import census  # noqa: E402
from fetch import DEFAULT_DEST, REPO_ROOT, load_manifest  # noqa: E402

_UNIT_RE = re.compile(r"\b(PROGRAM-ID|FUNCTION-ID|CLASS-ID)\b", re.I)
_DROP_WARNING_RE = re.compile(
    r"dropped|Unparsed token|Unsupported statement|skipped|ignored|discard", re.I
)
_MISSING_COPY_RE = re.compile(r"COPY (\S+) was not expanded", re.I)
STATUS_ORDER = (
    "crash",
    "timeout",
    "errors",
    "dropped",
    "mismatch",
    "unchecked",
    "clean",
)


@dataclass
class FileResult:
    source: str
    dialect: str
    path: str
    lines: int = 0
    status: str = "clean"
    seconds: float = 0.0
    errors: list[str] = field(default_factory=list)
    drop_warnings: list[str] = field(default_factory=list)
    missing_copybooks: list[str] = field(default_factory=list)
    verb_diff: dict[str, list[int]] = field(
        default_factory=dict
    )  # verb -> [source, ast]
    missing_paragraphs: list[str] = field(default_factory=list)
    extra_paragraphs: list[str] = field(default_factory=list)
    missing_sections: list[str] = field(default_factory=list)
    extra_sections: list[str] = field(default_factory=list)
    data_entries: list[int] = field(default_factory=list)  # [source, ast]
    error_nodes: list[str] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)
    crash: str | None = None


# -- discovery ---------------------------------------------------------------


def _glob_dirs(root: Path, pattern: str) -> list[Path]:
    if pattern in (".", ""):
        return [root]
    return [d for d in root.glob(pattern) if d.is_dir()]


def discover(source: dict, root: Path) -> list[tuple[Path, list[str]]]:
    """(program file, copybook directories) for one manifest source."""
    if source.get("kind") == "gnucobol-at":
        root = root / "_extracted"
        candidates = sorted(
            p
            for p in root.rglob("*")
            if p.is_file() and p.suffix.lower() in (".cob", ".cbl")
        )
        dirs_for = lambda p: [str(p.parent)]  # noqa: E731
    else:
        candidates = sorted(
            {p for g in source["programs"] for p in root.glob(g) if p.is_file()}
        )
        excluded = {p for g in source.get("exclude", []) for p in root.glob(g)}
        candidates = [p for p in candidates if p not in excluded]
        copy_dirs = sorted(
            {str(d) for g in source.get("copybooks", []) for d in _glob_dirs(root, g)}
        )
        dirs_for = lambda p: [str(p.parent), *copy_dirs]  # noqa: E731
    skip_re = (
        re.compile(source["skip_if_first_line"])
        if "skip_if_first_line" in source
        else None
    )
    out = []
    for path in candidates:
        text = path.read_text(encoding="latin-1")
        if not _UNIT_RE.search(text):  # a copybook that carries a program suffix
            continue
        if skip_re and skip_re.search(text.split("\n", 1)[0]):
            continue
        out.append((path, dirs_for(path)))
    return out


# -- one file ------------------------------------------------------------------


class _Timeout(Exception):
    pass


def _alarm(_signum: int, _frame: object) -> None:
    raise _Timeout


def check_file(job: tuple[str, str, str, list[str], int, str]) -> FileResult:
    source_id, dialect, path_str, copy_dirs, timeout, display = job
    from cobolparser import CobolParser, ErrorRecoveryMode
    from cobolparser.preprocess.copybook_expander import expand_copybooks

    res = FileResult(source=source_id, dialect=dialect, path=display)
    raw = Path(path_str).read_text(encoding="latin-1")
    res.lines = raw.count("\n") + 1
    use_alarm = hasattr(signal, "SIGALRM")
    if use_alarm:
        signal.signal(signal.SIGALRM, _alarm)
        signal.alarm(timeout)
    start = time.perf_counter()
    try:
        expansion = expand_copybooks(
            raw,
            copy_dirs,
            preserve_source_locations=True,
            process_conditionals=True,
            skip_missing_copybooks=True,
            source_file=path_str,
        )
        text = expansion.expanded_source
        for warning in getattr(expansion.statistics, "warnings", []) or []:
            m = _MISSING_COPY_RE.search(warning)
            if m:
                res.missing_copybooks.append(m.group(1).rstrip("."))
        result = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL).parse(text)
    except _Timeout:
        res.status = "timeout"
        res.seconds = timeout
        return res
    except Exception as exc:  # noqa: BLE001 -- a crash is a finding
        res.status = "crash"
        res.crash = f"{type(exc).__name__}: {exc}"[:500]
        res.errors.append(traceback.format_exc(limit=4)[-1500:])
        return res
    finally:
        if use_alarm:
            signal.alarm(0)
    res.seconds = round(time.perf_counter() - start, 3)

    res.errors = [str(e)[:300] for e in result.errors]
    for warning in result.warnings:
        w = str(warning)
        if _MISSING_COPY_RE.search(w):
            m = _MISSING_COPY_RE.search(w)
            if m and m.group(1).rstrip(".") not in res.missing_copybooks:
                res.missing_copybooks.append(m.group(1).rstrip("."))
            continue
        if _DROP_WARNING_RE.search(w):
            res.drop_warnings.append(w[:300])
    if result.ast is None:
        res.status = "crash"
        res.crash = "no AST returned"
        return res

    want = census(text)
    got = ast_census(result.ast)
    res.caveats = list(dict.fromkeys(want.caveats))
    res.error_nodes = got.error_nodes
    for verb in sorted(set(want.verbs) | set(got.verbs)):
        if want.verbs[verb] != got.verbs[verb]:
            res.verb_diff[verb] = [want.verbs[verb], got.verbs[verb]]
    src_paras = Counter(name for name, _ in want.paragraphs)
    ast_paras = Counter(got.paragraphs)
    res.missing_paragraphs = sorted((src_paras - ast_paras).elements())
    res.extra_paragraphs = sorted((ast_paras - src_paras).elements())
    src_secs = Counter(name for name, _ in want.sections)
    ast_secs = Counter(got.sections)
    res.missing_sections = sorted((src_secs - ast_secs).elements())
    res.extra_sections = sorted((ast_secs - src_secs).elements())
    res.data_entries = [want.data_entries, got.data_entries]

    disagrees = bool(
        res.verb_diff
        or res.missing_paragraphs
        or res.extra_paragraphs
        or res.missing_sections
        or res.extra_sections
        or want.data_entries != got.data_entries
        or res.error_nodes
    )
    if res.errors:
        res.status = "errors"
    elif res.drop_warnings:
        res.status = "dropped"
    elif disagrees and not (res.caveats or res.missing_copybooks):
        res.status = "mismatch"
    elif disagrees:
        res.status = "unchecked"
    return res


# -- driver ----------------------------------------------------------------------


def collect_jobs(dest: Path, only: list[str] | None, timeout: int) -> list[tuple]:
    jobs = []
    for source in load_manifest():
        if only and source["id"] not in only:
            continue
        root = REPO_ROOT / source["local"] if "local" in source else dest / source["id"]
        if not root.exists():
            print(
                f"skip  {source['id']}: not fetched (run tools/corpus/fetch.py)",
                file=sys.stderr,
            )
            continue
        base = root / "_extracted" if source.get("kind") == "gnucobol-at" else root
        for path, dirs in discover(source, root):
            display = f"{source['id']}/{path.relative_to(base).as_posix()}"
            jobs.append(
                (
                    source["id"],
                    source.get("dialect", "ibm"),
                    str(path),
                    dirs,
                    timeout,
                    display,
                )
            )
    return jobs


def run(jobs: list[tuple], workers: int) -> list[FileResult]:
    if workers <= 1:
        return [check_file(j) for j in jobs]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(check_file, jobs, chunksize=4))


def summarize(results: list[FileResult]) -> dict:
    by_source: dict[str, Counter[str]] = {}
    verb_loss: Counter[str] = Counter()
    verb_gain: Counter[str] = Counter()
    for r in results:
        by_source.setdefault(r.source, Counter())[r.status] += 1
        for verb, (src, ast) in r.verb_diff.items():
            if src > ast:
                verb_loss[verb] += src - ast
            else:
                verb_gain[verb] += ast - src
    total = Counter(r.status for r in results)
    return {
        "files": len(results),
        "lines": sum(r.lines for r in results),
        "status": dict(total),
        "by_source": {k: dict(v) for k, v in sorted(by_source.items())},
        "statements_missing_by_verb": dict(verb_loss.most_common()),
        "statements_extra_by_verb": dict(verb_gain.most_common()),
        "paragraphs_missing": sum(len(r.missing_paragraphs) for r in results),
        "paragraphs_extra": sum(len(r.extra_paragraphs) for r in results),
    }


def markdown(summary: dict, results: list[FileResult]) -> str:
    out = ["# Open-source COBOL corpus: AST completeness", ""]
    out.append(f"{summary['files']} programs, {summary['lines']:,} lines.")
    out.append("")
    out.append("| source | " + " | ".join(STATUS_ORDER) + " |")
    out.append("|---|" + "---|" * len(STATUS_ORDER))
    for src, counts in summary["by_source"].items():
        out.append(
            f"| {src} | "
            + " | ".join(str(counts.get(s, 0)) for s in STATUS_ORDER)
            + " |"
        )
    tot = summary["status"]
    out.append(
        "| **total** | "
        + " | ".join(f"**{tot.get(s, 0)}**" for s in STATUS_ORDER)
        + " |"
    )
    out.append("")
    out.append(
        "Statements in the source but not in the AST, by verb: "
        + ", ".join(
            f"{v} {n}" for v, n in summary["statements_missing_by_verb"].items()
        )
        or "none"
    )
    out.append("")
    for status in STATUS_ORDER[:-1]:
        rows = [r for r in results if r.status == status]
        if not rows:
            continue
        out.append(f"## {status} ({len(rows)})")
        out.append("")
        for r in rows[:400]:
            detail = []
            if r.crash:
                detail.append(r.crash)
            if r.errors and status != "crash":
                detail.append(f"{len(r.errors)} errors, first: {r.errors[0][:160]}")
            if r.drop_warnings:
                detail.append(
                    f"{len(r.drop_warnings)} drop warnings, first: {r.drop_warnings[0][:160]}"
                )
            if r.verb_diff:
                detail.append(
                    "verbs "
                    + ", ".join(f"{v} {s}->{a}" for v, (s, a) in r.verb_diff.items())
                )
            if r.missing_paragraphs:
                detail.append(
                    "missing paragraphs " + ", ".join(r.missing_paragraphs[:8])
                )
            if r.extra_paragraphs:
                detail.append("extra paragraphs " + ", ".join(r.extra_paragraphs[:8]))
            if r.missing_sections or r.extra_sections:
                detail.append(
                    f"sections missing {r.missing_sections[:5]} extra {r.extra_sections[:5]}"
                )
            if r.data_entries and r.data_entries[0] != r.data_entries[1]:
                detail.append(f"data entries {r.data_entries[0]}->{r.data_entries[1]}")
            if r.missing_copybooks:
                detail.append("missing copybooks " + ", ".join(r.missing_copybooks[:6]))
            if r.caveats:
                detail.append("caveats " + "; ".join(r.caveats[:3]))
            out.append(f"- `{r.path}`: " + "; ".join(detail))
        out.append("")
    return "\n".join(out)


# -- baseline ratchet --------------------------------------------------------------

BASELINE = HERE / "baseline.json"


def fingerprint(r: FileResult) -> dict:
    """The numbers a regression would move, for one non-clean file."""
    lost = sum(max(0, s - a) for s, a in r.verb_diff.values())
    added = sum(max(0, a - s) for s, a in r.verb_diff.values())
    src_data, ast_data = (r.data_entries or [0, 0])[:2]
    return {
        "status": r.status,
        "errors": len(r.errors),
        "drop_warnings": len(r.drop_warnings),
        "statements_lost": lost,
        "statements_added": added,
        "paragraphs_lost": len(r.missing_paragraphs) + len(r.missing_sections),
        "paragraphs_added": len(r.extra_paragraphs) + len(r.extra_sections),
        "data_entries_lost": max(0, src_data - ast_data),
        "data_entries_added": max(0, ast_data - src_data),
    }


def make_baseline(results: list[FileResult]) -> dict:
    return {
        r.path: fingerprint(r)
        for r in sorted(results, key=lambda r: r.path)
        if r.status != "clean"
    }


def write_baseline(baseline: dict, path: Path = BASELINE) -> None:
    """One file per line, so a baseline refresh reads as a small diff."""
    lines = [
        f"  {json.dumps(k)}: {json.dumps(v, sort_keys=True)}"
        for k, v in sorted(baseline.items())
    ]
    path.write_text("{\n" + ",\n".join(lines) + "\n}\n")


def compare_baseline(
    results: list[FileResult], baseline: dict
) -> tuple[list[str], list[str]]:
    """(regressions, improvements) of *results* against *baseline*.

    A file regresses when its status gets worse (``STATUS_ORDER``) or any
    count grows; a file missing from the baseline was clean, so any other
    status for it is a regression.
    """
    rank = {s: i for i, s in enumerate(STATUS_ORDER)}
    regressions: list[str] = []
    improvements: list[str] = []
    for r in results:
        now = fingerprint(r) if r.status != "clean" else None
        was = baseline.get(r.path)
        if was is None and now is None:
            continue
        if was is None:
            regressions.append(f"{r.path}: was clean, now {r.status} {now}")
            continue
        if now is None:
            improvements.append(f"{r.path}: now clean (was {was['status']})")
            continue
        worse = [k for k, v in now.items() if k != "status" and v > was.get(k, 0)]
        if rank[r.status] < rank[was["status"]] or worse:
            regressions.append(
                f"{r.path}: {was['status']} -> {r.status}; grew: "
                + ", ".join(f"{k} {was.get(k, 0)}->{now[k]}" for k in worse)
            )
        elif now != was:
            improvements.append(f"{r.path}: {was} -> {now}")
    return regressions, improvements


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dest", type=Path, default=DEFAULT_DEST, help="corpus cache")
    parser.add_argument("--only", action="append", help="source id (repeatable)")
    parser.add_argument("-j", "--jobs", type=int, default=os.cpu_count() or 1)
    parser.add_argument("--timeout", type=int, default=60, help="seconds per file")
    parser.add_argument("--json", type=Path, help="write per-file results here")
    parser.add_argument("--md", type=Path, help="write a Markdown report here")
    parser.add_argument(
        "--fail-on", default="", help="comma list of statuses, e.g. crash,timeout"
    )
    parser.add_argument(
        "--check-baseline",
        action="store_true",
        help=f"fail if any file is worse than {BASELINE.name} (the ratchet)",
    )
    parser.add_argument(
        "--write-baseline",
        action="store_true",
        help=f"record this run as {BASELINE.name} (only for a full run of every source)",
    )
    args = parser.parse_args(argv)

    jobs = collect_jobs(args.dest, args.only, args.timeout)
    results = run(jobs, args.jobs)
    summary = summarize(results)
    if args.json:
        args.json.write_text(
            json.dumps(
                {"summary": summary, "files": [asdict(r) for r in results]}, indent=1
            )
        )
    if args.md:
        args.md.write_text(markdown(summary, results))
    print(json.dumps(summary, indent=1))
    status = 0
    if args.write_baseline:
        write_baseline(make_baseline(results))
        print(f"wrote {BASELINE}")
    if args.check_baseline:
        baseline = json.loads(BASELINE.read_text())
        regressions, improvements = compare_baseline(results, baseline)
        for line in improvements:
            print(f"improved   {line}")
        for line in regressions:
            print(f"REGRESSED  {line}")
        if improvements:
            print("Some files improved: refresh the baseline with --write-baseline.")
        if regressions:
            status = 1
    fail = {s.strip() for s in args.fail_on.split(",") if s.strip()}
    if fail & set(summary["status"]):
        status = 1
    return status


if __name__ == "__main__":
    sys.exit(main())
