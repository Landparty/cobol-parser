"""Next-step hints: the one or two calls that usually follow an answer.

A model that has just read a program brief tends to ask next who calls the
program, or to look at the code of its entry paragraph; guessing which tool
answers that, and with which arguments, is a turn. Each answer can carry a
``next`` list of ready-to-make calls, written as ``tool(arg=value, ...)``.

Hints are derived from the answer alone (no second analysis), are never
facts, and only name tools the server offers. Like :mod:`.tools`, this
module imports no SDK.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

#: Most hints on one answer.
MAX_HINTS = 2

_Hint = tuple[str, dict[str, Any]]


def _call(tool: str, **args: Any) -> _Hint:
    return tool, {k: v for k, v in args.items() if v is not None}


def _render(hint: _Hint) -> str:
    tool, args = hint
    shown = ", ".join(
        f"{k}={v!r}" if not isinstance(v, str) else f'{k}="{v}"'
        for k, v in args.items()
    )
    return f"{tool}({shown})"


def _first(items: Any) -> Any:
    return items[0] if isinstance(items, list) and items else None


def _program_file(result: dict[str, Any]) -> str | None:
    program = result.get("program") or {}
    return program.get("file") if isinstance(program, dict) else None


def _brief(answer: dict[str, Any], result: dict[str, Any]) -> Iterable[_Hint]:
    file = _program_file(result)
    entry = _first(answer.get("entry_points"))
    if file and entry:
        yield _call("read_procedure", file=file, name=entry)
    if answer.get("program_id"):
        yield _call("callers_of", name=answer["program_id"])


def _symbol(answer: dict[str, Any], result: dict[str, Any]) -> Iterable[_Hint]:
    file = _program_file(result)
    symbol = _first(answer.get("symbols"))
    if not isinstance(symbol, dict):
        return
    if symbol.get("kind") == "data-item" and file:
        yield _call("where_from", field=symbol.get("name"), file=file)
    writes = [
        r
        for r in symbol.get("references") or []
        if isinstance(r, dict) and r.get("role") == "write"
    ]
    ref = _first(writes) or _first(symbol.get("references"))
    if isinstance(ref, dict) and ref.get("location"):
        location = ref["location"]
        yield _call("read_source", file=location["file"], line=location["line"])


def _callers(answer: dict[str, Any], result: dict[str, Any]) -> Iterable[_Hint]:
    file = _program_file(result)
    procedure = _first(answer.get("procedures"))
    callers = (
        procedure.get("callers") if isinstance(procedure, dict) else None
    ) or answer.get("callers")
    caller = _first(callers)
    if isinstance(caller, dict) and caller.get("location"):
        location = caller["location"]
        yield _call("read_source", file=location["file"], line=location["line"])
    if isinstance(procedure, dict) and file:
        yield _call("read_procedure", file=file, name=procedure.get("name"))


def _lineage(answer: dict[str, Any], result: dict[str, Any]) -> Iterable[_Hint]:
    hit = next(
        (
            h
            for h in answer.get("hits") or []
            if isinstance(h, dict) and h.get("location")
        ),
        None,
    )
    if hit:
        location = hit["location"]
        yield _call("read_source", file=location["file"], line=location["line"])
    dataset = _first(answer.get("datasets"))
    if dataset:
        yield _call("dataset_users", dataset=str(dataset).split("/")[-1])


def _impact(answer: dict[str, Any], result: dict[str, Any]) -> Iterable[_Hint]:
    if answer.get("kind") == "copybook":
        program = _first(answer.get("copied_by"))
        if isinstance(program, dict) and program.get("file"):
            site = _first(program.get("copy_sites"))
            if isinstance(site, dict):
                yield _call("read_source", file=site["file"], line=site["line"])
            yield _call("program_brief", file=program["file"])
        return
    yield from _lineage(answer, result)


def _overview(answer: dict[str, Any], result: dict[str, Any]) -> Iterable[_Hint]:
    programs = {
        row.get("program"): row.get("file")
        for row in answer.get("programs") or []
        if isinstance(row, dict)
    }
    graph = answer.get("call_graph") or {}
    for name in graph.get("entry_programs") or []:
        if programs.get(name):
            yield _call("program_brief", file=programs[name])
            break
    worst = _first((answer.get("health") or {}).get("worst"))
    if isinstance(worst, dict) and worst.get("file"):
        yield _call("lint", file=worst["file"], min_severity="warning")


def _lint(answer: dict[str, Any], result: dict[str, Any]) -> Iterable[_Hint]:
    finding = _first(answer.get("findings"))
    if isinstance(finding, dict) and finding.get("location"):
        location = finding["location"]
        yield _call("read_source", file=location["file"], line=location["line"])


def _jobs(answer: dict[str, Any], result: dict[str, Any]) -> Iterable[_Hint]:
    step = _first(answer.get("steps"))
    if isinstance(step, dict) and step.get("file"):
        yield _call("jcl_job", file=step["file"], job=step.get("job"))


def _datasets(answer: dict[str, Any], result: dict[str, Any]) -> Iterable[_Hint]:
    for use in answer.get("uses") or []:
        for program in use.get("programs") or [] if isinstance(use, dict) else []:
            yield _call("jobs_running", program=program)
            return


def _slice(answer: dict[str, Any], result: dict[str, Any]) -> Iterable[_Hint]:
    file = _program_file(result)
    paragraphs = answer.get("paragraphs") or []
    if file and len(paragraphs) == 1 and paragraphs[0].get("paragraph"):
        yield _call("read_procedure", file=file, name=paragraphs[0]["paragraph"])
    if answer.get("ports") and answer.get("found"):
        # Values cross the program boundary: the lineage tools follow them.
        if answer.get("direction") == "backward":
            yield _call("where_from", field=answer.get("field"), file=file)
        else:
            yield _call("impact_of_change", name=answer.get("field"), file=file)


_HINTERS: dict[str, Callable[[dict[str, Any], dict[str, Any]], Iterable[_Hint]]] = {
    "program_brief": _brief,
    "explain_symbol": _symbol,
    "callers_of": _callers,
    "where_from": _lineage,
    "impact_of_change": _impact,
    "codebase_overview": _overview,
    "lint": _lint,
    "slice": _slice,
    "jobs_running": _jobs,
    "dataset_users": _datasets,
}


def add_hints(tool: str, result: dict[str, Any], enabled: set[str]) -> dict[str, Any]:
    """*result* with a ``next`` list of at most :data:`MAX_HINTS` calls,
    each to a tool in *enabled*; unchanged when there is none."""
    hinter = _HINTERS.get(tool)
    answer = result.get("answer")
    if hinter is None or not isinstance(answer, dict):
        return result
    hints: list[str] = []
    try:
        for hint in hinter(answer, result):
            if hint[0] not in enabled:
                continue
            rendered = _render(hint)
            if rendered not in hints:
                hints.append(rendered)
            if len(hints) == MAX_HINTS:
                break
    except (KeyError, TypeError, AttributeError):
        # A hint is a convenience; an answer shape it did not expect is
        # never a reason to fail the call.
        return result
    if hints:
        result["next"] = hints
    return result
