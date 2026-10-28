"""``check_claims``: the checkable statements of a draft answer, each
confirmed, contradicted (with the evidence) or not checkable.

A model that has read some code writes "PROG-A writes CUST.MASTER" or
"2100-CALC is unreachable" from what it saw, and is sometimes wrong about
the part it did not read. Before it answers, it can hand those statements
over as structured claims and get each one back judged against the whole
root by the same analyses the other tools answer from. A verdict is only
ever as strong as the analysis behind it: a claim the analysis cannot
settle (a dynamic CALL, a DD only DISP= speaks for, a field in no report)
is ``not_checkable`` with the reason, never guessed.

Like :mod:`.tools`, this module imports no SDK.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from .envelope import Response, ToolError

if TYPE_CHECKING:
    from .tools import CobolTools

#: Most claims one call checks.
MAX_CLAIMS = 25

CONFIRMED = "confirmed"
CONTRADICTED = "contradicted"
NOT_CHECKABLE = "not_checkable"

#: kind -> what the claim says, with subject (S) and object (O).
CLAIM_KINDS: dict[str, str] = {
    "calls": "program S CALLs, LINKs or XCTLs to program O",
    "copies": "program S COPYs member O",
    "performs": "in file, paragraph S PERFORMs (or GO TOs) procedure O",
    "unreachable": "in file, procedure S can never run",
    "reachable": "in file, procedure S can run",
    "writes_field": "in file, paragraph S writes field O (S omitted: anywhere)",
    "sets_only_in": "in file, field O is written only in paragraphs S (comma list)",
    "reads_dataset": "program S reads dataset O (from the JCL under the root)",
    "writes_dataset": "program S writes dataset O (from the JCL under the root)",
    "flows_to": "the value of field S reaches O (a field, dataset or table column)",
}

_Verdict = tuple[str, str, list[Any]]


def _norm(text: str | None) -> str:
    return " ".join((text or "").upper().split())


def check_claims(tools: CobolTools, claims: list[dict[str, Any]]) -> dict[str, Any]:
    """Each of *claims* judged; see :data:`CLAIM_KINDS` for what they say."""
    if not claims:
        raise ToolError("give at least one claim")
    response = Response()
    shown = response.cap(list(claims), MAX_CLAIMS, "claims")
    results: list[dict[str, Any]] = []
    for claim in shown:
        results.append(_check_one(tools, claim))
    summary: dict[str, int] = {}
    for result in results:
        summary[result["verdict"]] = summary.get(result["verdict"], 0) + 1
    return response.build(
        {
            "summary": summary,
            "results": results,
            "legend": (
                "confirmed: the analysis shows it; contradicted: the analysis "
                "shows otherwise (evidence says where); not_checkable: the "
                "analysis cannot settle it (why says what is missing). Kinds: "
                + "; ".join(f"{k}: {v}" for k, v in CLAIM_KINDS.items())
            ),
        }
    )


def _check_one(tools: CobolTools, claim: dict[str, Any]) -> dict[str, Any]:
    kind = str(claim.get("kind") or "").lower()
    echo = {k: v for k, v in claim.items() if v not in (None, "")}
    checker = _CHECKERS.get(kind)
    if checker is None:
        return {
            "claim": echo,
            "verdict": NOT_CHECKABLE,
            "why": f"unknown kind {kind!r}; known: {', '.join(CLAIM_KINDS)}",
        }
    try:
        verdict, why, evidence = checker(tools, claim)
    except ToolError as exc:
        verdict, why, evidence = NOT_CHECKABLE, str(exc), []
    result: dict[str, Any] = {"claim": echo, "verdict": verdict, "why": why}
    if evidence:
        result["evidence"] = evidence[:10]
    return result


def _need(claim: dict[str, Any], *keys: str) -> None:
    missing = [k for k in keys if not claim.get(k)]
    if missing:
        raise ToolError(f"this kind needs {', '.join(missing)}")


# ---------------------------------------------------------------------------
# Programs
# ---------------------------------------------------------------------------


def _calls(tools: CobolTools, claim: dict[str, Any]) -> _Verdict:
    from .codebase_index import programs_index

    _need(claim, "subject", "object")
    caller, callee = _norm(claim["subject"]), _norm(claim["object"])
    index = programs_index(tools.workspace)
    units = index.units_named(caller)
    if not units:
        raise ToolError(f"no program under the root is named {caller}")
    # A CALL to one of the callee's ENTRY names reaches it too (#521): an
    # assembler routine's ENTRY, a PL/I program's member name.
    callees = {callee} | {
        entry for unit in index.units_named(callee) for entry in unit.entries
    }
    sites: list[Any] = []
    others: list[str] = []
    open_dynamic: list[Any] = []
    for unit in units:
        for row in unit.calls:
            target = _norm(row.get("program"))
            candidates = [_norm(c) for c in row.get("candidates") or []]
            if target in callees or callees & set(candidates):
                sites += [s.get("location") for s in row.get("sites") or []]
            elif row.get("dynamic") and not row.get("candidates_complete"):
                open_dynamic += [s.get("location") for s in row.get("sites") or []]
            elif target:
                others.append(target)
    if sites:
        return CONFIRMED, f"{caller} calls {callee}", sites
    if open_dynamic:
        return (
            NOT_CHECKABLE,
            f"{caller} makes dynamic CALLs whose targets are not all known",
            open_dynamic,
        )
    return (
        CONTRADICTED,
        f"{caller} calls "
        + (", ".join(sorted(set(others))) if others else "no program")
        + f", not {callee}",
        [],
    )


def _copies(tools: CobolTools, claim: dict[str, Any]) -> _Verdict:
    from .codebase_index import programs_index

    _need(claim, "subject", "object")
    program, member = _norm(claim["subject"]), _norm(claim["object"])
    index = programs_index(tools.workspace)
    units = index.units_named(program)
    if not units:
        raise ToolError(f"no program under the root is named {program}")
    files = {u.file for u in units}
    member_key = member.rsplit(".", 1)[0] if "." in member else member
    sites = [
        {"file": s.get("file"), "line": s.get("line")}
        for s in index.copy_sites.get(member_key, [])
        if s.get("file") in files
    ]
    if sites:
        return CONFIRMED, f"{program} copies {member_key}", sites
    copied = sorted(
        m
        for m, held in index.copy_sites.items()
        if any(s.get("file") in files for s in held)
    )
    return (
        CONTRADICTED,
        f"{program}'s file copies "
        + (", ".join(copied) if copied else "no member")
        + f", not {member_key}",
        [],
    )


# ---------------------------------------------------------------------------
# Procedures
# ---------------------------------------------------------------------------


def _procedure(tools: CobolTools, claim: dict[str, Any], name: str) -> dict[str, Any]:
    _need(claim, "file")
    answer = tools.callers_of(claim["file"], name, claim.get("program"))["answer"]
    procedures = answer.get("procedures") or []
    if not procedures:
        raise ToolError(f"no paragraph or section {name} in {claim['file']}")
    procedure: dict[str, Any] = procedures[0]
    return procedure


def _performs(tools: CobolTools, claim: dict[str, Any]) -> _Verdict:
    _need(claim, "subject", "object")
    source, target = _norm(claim["subject"]), _norm(claim["object"])
    procedure = _procedure(tools, claim, target)
    callers = procedure.get("callers") or []
    hits = [
        c.get("location")
        for c in callers
        if _norm(c.get("from")) == source and c.get("type") != "FALL_THROUGH"
    ]
    if hits:
        return CONFIRMED, f"{source} transfers control to {target}", hits
    named = sorted({_norm(c.get("from")) for c in callers if c.get("from")})
    return (
        CONTRADICTED,
        f"{target} is reached from "
        + (", ".join(named) if named else "nowhere")
        + f", not from {source}",
        [c.get("location") for c in callers][:5],
    )


def _reachability(want: bool) -> Callable[[CobolTools, dict[str, Any]], _Verdict]:
    def check(tools: CobolTools, claim: dict[str, Any]) -> _Verdict:
        _need(claim, "subject")
        name = _norm(claim["subject"])
        procedure = _procedure(tools, claim, name)
        reachable = bool(procedure.get("reachable"))
        evidence = [c.get("location") for c in procedure.get("callers") or []][:5]
        state = "can run" if reachable else "can never run"
        verdict = CONFIRMED if reachable == want else CONTRADICTED
        return verdict, f"{name} {state}", evidence or [procedure.get("declared_at")]

    return check


# ---------------------------------------------------------------------------
# Fields
# ---------------------------------------------------------------------------


def _writes(tools: CobolTools, claim: dict[str, Any]) -> list[dict[str, Any]]:
    _need(claim, "file", "object")
    answer = tools.find_statements(
        operand=claim["object"],
        role="write",
        file=claim["file"],
        program=claim.get("program"),
        limit=1000,
    )["answer"]
    rows: list[dict[str, Any]] = answer.get("statements") or []
    return rows


def _writes_field(tools: CobolTools, claim: dict[str, Any]) -> _Verdict:
    field_name = _norm(claim.get("object"))
    rows = _writes(tools, claim)
    paragraph = _norm(claim.get("subject"))
    if paragraph:
        hits = [r for r in rows if _norm(r.get("paragraph")) == paragraph]
    else:
        hits = rows
    if hits:
        return (
            CONFIRMED,
            f"{field_name} is written {'in ' + paragraph if paragraph else ''}".strip(),
            [r["location"] for r in hits],
        )
    elsewhere = sorted({str(r.get("paragraph")) for r in rows})
    return (
        CONTRADICTED,
        f"{field_name} is written "
        + (f"only in {', '.join(elsewhere)}" if elsewhere else "by no statement"),
        [r["location"] for r in rows][:5],
    )


def _sets_only_in(tools: CobolTools, claim: dict[str, Any]) -> _Verdict:
    _need(claim, "subject")
    field_name = _norm(claim.get("object"))
    allowed = {_norm(p) for p in str(claim["subject"]).split(",") if p.strip()}
    rows = _writes(tools, claim)
    outside = [r for r in rows if _norm(r.get("paragraph")) not in allowed]
    if outside:
        return (
            CONTRADICTED,
            f"{field_name} is also written in "
            + ", ".join(sorted({str(r.get("paragraph")) for r in outside})),
            [r["location"] for r in outside],
        )
    if not rows:
        return CONTRADICTED, f"no statement writes {field_name}", []
    return (
        CONFIRMED,
        f"every write of {field_name} is in {', '.join(sorted(allowed))} "
        "(a VALUE clause or a CALL argument passed by reference is not a "
        "statement write)",
        [r["location"] for r in rows],
    )


def _flows_to(tools: CobolTools, claim: dict[str, Any]) -> _Verdict:
    _need(claim, "subject", "object")
    target = _norm(claim["object"])
    answer = tools.impact_of_change(
        claim["subject"], claim.get("file"), claim.get("program"), None, 1000
    )["answer"]
    if not answer.get("found", True):
        raise ToolError(f"no field {_norm(claim['subject'])} in any report")
    hits = answer.get("hits") or []

    def names(hit: dict[str, Any]) -> set[str]:
        field = _norm(hit.get("field"))
        found = {field, field.split(".")[-1], field.split(":")[-1].split("@")[0]}
        return found

    matched = [h for h in hits if target in names(h)]
    matched += [
        h for h in hits if h not in matched and target in _norm(" ".join(h["path"]))
    ]
    for dataset in answer.get("datasets") or []:
        if target and target in _norm(dataset):
            return CONFIRMED, f"the value reaches dataset {dataset}", []
    for table in answer.get("tables") or []:
        if target and target in _norm(table):
            return CONFIRMED, f"the value reaches {table}", []
    if not matched:
        return (
            CONTRADICTED,
            f"no flow from {_norm(claim['subject'])} reaches {target} "
            f"({len(hits)} fields and ports reached)",
            [],
        )
    best = matched[0]
    evidence = [best.get("location")]
    if best.get("may_be_overwritten"):
        if all(" by MOVE" in kill for kill in best["may_be_overwritten"]):
            # A MOVE always replaces the value; a SELECT INTO finding no
            # row or a READ INTO at end of file would not.
            return (
                CONTRADICTED,
                "the value is overwritten before it gets there: "
                + "; ".join(best["may_be_overwritten"]),
                evidence,
            )
        return (
            NOT_CHECKABLE,
            "the only flow found is overwritten on the way: "
            + "; ".join(best["may_be_overwritten"]),
            evidence,
        )
    if best.get("confidence") != "exact":
        return (
            NOT_CHECKABLE,
            f"a flow exists but is {best.get('confidence')}, not exact",
            evidence,
        )
    return CONFIRMED, "; ".join(best.get("path") or [])[:300], evidence


# ---------------------------------------------------------------------------
# Datasets
# ---------------------------------------------------------------------------

_WRITES = {"write", "create", "extend", "update"}
_READS = {"read", "update"}


def _dataset(want_write: bool) -> Callable[[CobolTools, dict[str, Any]], _Verdict]:
    def check(tools: CobolTools, claim: dict[str, Any]) -> _Verdict:
        _need(claim, "subject", "object")
        program, dataset = _norm(claim["subject"]), _norm(claim["object"])
        answer = tools.dataset_users(dataset, 1000)["answer"]
        if "uses" not in answer:
            raise ToolError(str(answer.get("note") or "the JCL tools are unavailable"))
        uses = [
            u
            for u in answer["uses"]
            if program in [_norm(p) for p in u.get("programs") or []]
        ]
        if not uses:
            return (
                CONTRADICTED,
                f"no JCL step running {program} names {dataset}"
                + (
                    f" (it is used by {', '.join(sorted({p for u in answer['uses'] for p in u.get('programs') or []}))})"
                    if answer["uses"]
                    else ""
                ),
                [],
            )
        wanted = _WRITES if want_write else _READS
        sure = [u for u in uses if u.get("access") in wanted]
        if sure:
            return (
                CONFIRMED,
                f"{program} {'writes' if want_write else 'reads'} {dataset} "
                f"({', '.join(sorted({u['access'] for u in sure}))}, from "
                f"{', '.join(sorted({u.get('access_from', 'disp') for u in sure}))})",
                [u.get("location") for u in sure],
            )
        if all(u.get("access_from") == "disp" for u in uses):
            return (
                NOT_CHECKABLE,
                f"only DISP= speaks for it ({', '.join(sorted({str(u.get('disposition')) for u in uses}))}): "
                "the program's source is not under the root",
                [u.get("location") for u in uses],
            )
        return (
            CONTRADICTED,
            f"{program} uses {dataset} for "
            + ", ".join(sorted({str(u.get("access")) for u in uses})),
            [u.get("location") for u in uses],
        )

    return check


_CHECKERS: dict[str, Callable[[CobolTools, dict[str, Any]], _Verdict]] = {
    "calls": _calls,
    "copies": _copies,
    "performs": _performs,
    "unreachable": _reachability(False),
    "reachable": _reachability(True),
    "writes_field": _writes_field,
    "sets_only_in": _sets_only_in,
    "flows_to": _flows_to,
    "reads_dataset": _dataset(False),
    "writes_dataset": _dataset(True),
}
