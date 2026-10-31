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
from dataclasses import dataclass
from dataclasses import field as dc_field
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


@dataclass
class _Storage:
    """Where field O's bytes live: the other data items whose writes reach
    them, each with whether a write of it surely overwrites all of O (an
    ancestor group, an item covering O's bytes through REDEFINES / RENAMES
    or as another record of the same FD / SD) or only may (a partial
    overlap, a table element, a duplicated name); the FD / SD files whose
    record area holds O; and whether O could be placed at all (when not,
    the aliases are unknown)."""

    aliases: list[tuple[str, bool]] = dc_field(default_factory=list)
    files: set[str] = dc_field(default_factory=set)
    placed: bool = False
    unit: Any = None
    parsed: Any = None


def _file_records(unit: Any) -> dict[str, str]:
    """FILE SECTION 01 record name -> the FD / SD file it describes."""
    from ..models.program import CobolSection

    records: dict[str, str] = {}
    data = unit.get_division("DATA")
    section = data.get_section_by_name("FILE") if data is not None else None
    if not isinstance(section, CobolSection):
        return records
    for item in section.data_items:
        owner = item.get_metadata("fd_file_name")
        if owner and item.name:
            records[item.name.upper()] = str(owner).upper()
    return records


def _storage_aliases(tools: CobolTools, claim: dict[str, Any]) -> _Storage:
    """Field O's storage (see :class:`_Storage`)."""
    from .envelope import Response
    from .tools import _layout_for, _layout_index

    wanted = _norm(claim.get("object")).replace(" IN ", " OF ")
    try:
        parsed = tools.workspace.program(claim["file"])
        unit = parsed.unit(claim.get("program"), Response())
    except ToolError:
        return _Storage()
    layout = _layout_index(unit, Response())
    items = [i for key, rows in layout.items() if not key.startswith(" ") for i in rows]
    field = _layout_for(wanted.split(" OF ")[0], wanted, layout)
    if field is None or field.get("offset_ambiguous"):
        return _Storage(unit=unit, parsed=parsed)
    by_qname = {str(i["qualified_name"]): i for i in items}

    def root(item: dict[str, Any]) -> str:
        return str(item["qualified_name"]).split(".")[0]

    # 01 items that share storage through REDEFINES are one area.
    area: dict[str, str] = {}

    def base(name: str) -> str:
        while area.get(name, name) != name:
            name = area[name]
        return name

    for item in items:
        if item.get("level") in (1, 77) and item.get("redefines_chain"):
            area[base(str(item["qualified_name"]))] = base(
                str(item["redefines_chain"][-1])
            )
    # The 01 records of one FD / SD share its record area: COBOL treats
    # them as implicit redefinitions of each other.
    records = _file_records(unit)
    first_of: dict[str, str] = {}
    file_of_root: dict[str, str] = {}
    for item in items:
        if item.get("level") != 1 or item.get("parent_qualified_name"):
            continue
        owner = records.get(str(item["name"]).upper())
        if owner is None:
            continue
        qname = str(item["qualified_name"])
        file_of_root[qname] = owner
        if owner in first_of:
            mine, theirs = base(qname), base(first_of[owner])
            if mine != theirs:
                area[mine] = theirs
        else:
            first_of[owner] = qname

    def in_table(item: dict[str, Any]) -> bool:
        qname: str | None = str(item["qualified_name"])
        while qname:
            current = by_qname.get(qname)
            if current is None:
                return False
            if current.get("occurs"):
                return True
            qname = current.get("parent_qualified_name")
        return False

    f_name = str(field["qualified_name"])
    f_start = int(field["byte_offset"])
    f_end = f_start + int(field["byte_length"])
    f_area = base(root(field))
    name_counts: dict[str, int] = {}
    for item in items:
        name_counts[str(item["name"]).upper()] = (
            name_counts.get(str(item["name"]).upper(), 0) + 1
        )
    aliases: list[tuple[str, bool]] = []
    for item in items:
        qname = str(item["qualified_name"])
        if qname == f_name or base(root(item)) != f_area:
            continue
        start = int(item["byte_offset"])
        end = start + int(item["byte_length"])
        if end <= f_start or start >= f_end:
            continue
        ancestor = f_name.startswith(qname + ".")
        covers = start <= f_start and end >= f_end
        exact = (
            covers
            and not item.get("offset_ambiguous")
            and (ancestor or not (in_table(item) or in_table(field)))
            and name_counts[str(item["name"]).upper()] == 1
        )
        aliases.append((str(item["name"]).upper(), exact))
    files = {f for qname, f in file_of_root.items() if base(qname) == f_area}
    return _Storage(aliases, files, True, unit, parsed)


def _record_io_writes(
    storage: _Storage, field_name: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Writes of field O that name no data item of O's storage as a
    target: ``READ`` / ``RETURN`` of the file whose record area holds O
    (possible: at end of file the area is left as it was), and ``WRITE`` /
    ``REWRITE`` / ``RELEASE`` record ``FROM`` x, which moves x into the
    record first (sure or possible as a MOVE to that record would be).
    Returns (sure, possible) rows like :func:`_writes`' with ``via``."""
    from .envelope import Response
    from .navigation import _procedure_of, statement_verb
    from .tools import _own_statements

    if storage.unit is None or not storage.placed:
        return [], []
    exact_of = dict(storage.aliases)
    exact_of[field_name.split(" OF ")[0]] = True
    sure: list[dict[str, Any]] = []
    possible: list[dict[str, Any]] = []
    for statement in _own_statements(storage.unit):
        verb = statement_verb(statement)
        exact: bool | None = None
        via = ""
        if verb in ("READ", "RETURN"):
            owner = str(getattr(statement, "file_name", None) or "").upper()
            if owner in storage.files:
                exact, via = False, f"the record area of {owner}"
        elif verb in ("WRITE", "REWRITE", "RELEASE"):
            record = str(getattr(statement, "record_name", None) or "").upper()
            source = getattr(statement, "from_clause", None) or getattr(
                statement, "from_source", None
            )
            if source and record in exact_of:
                # Naming O itself is a direct write: no ``via``.
                exact = exact_of[record]
                via = "" if record == field_name.split(" OF ")[0] else record
        if exact is None:
            continue
        location = getattr(statement, "location", None)
        if location is None or not location.line:
            continue
        located = storage.parsed.locate(location.line, None, Response())
        if located is None:
            continue
        paragraph, _section = _procedure_of(statement)
        row = {
            "location": {"file": located["file"], "line": located["line"]},
            "verb": verb,
            "paragraph": paragraph,
            "text": verb,
            "via": via,
        }
        (sure if exact else possible).append(row)
    return sure, possible


def _alias_writes(
    tools: CobolTools, claim: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], bool]:
    """Writes of field O that a ``role="write"`` search for O misses:
    (direct, sure, possible, placed). ``direct`` rows write O by name
    (``WRITE O FROM x``); the others carry ``via``, the item or record
    area they write O through."""
    storage = _storage_aliases(tools, claim)
    io_sure, possible = _record_io_writes(storage, _norm(claim.get("object")))
    direct = [r for r in io_sure if not r["via"]]
    sure = [r for r in io_sure if r["via"]]
    for name, exact in storage.aliases:
        for row in _writes(tools, {**claim, "object": name}):
            row = {**row, "via": name}
            # INITIALIZE ... REPLACING sets only the named categories.
            replacing = row.get("verb") == "INITIALIZE" and "REPLACING" in _norm(
                row.get("text")
            )
            (sure if exact and not replacing else possible).append(row)
    return direct, sure, possible, storage.placed


def _writes_field(tools: CobolTools, claim: dict[str, Any]) -> _Verdict:
    field_name = _norm(claim.get("object"))
    extra, sure, possible, _placed = _alias_writes(tools, claim)
    direct = _writes(tools, claim) + extra
    paragraph = _norm(claim.get("subject"))

    def here(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not paragraph:
            return rows
        return [r for r in rows if _norm(r.get("paragraph")) == paragraph]

    where = ("in " + paragraph) if paragraph else ""
    if here(direct):
        return (
            CONFIRMED,
            f"{field_name} is written {where}".strip(),
            [r["location"] for r in here(direct)],
        )
    if here(sure):
        via = sorted({r["via"] for r in here(sure)})
        return (
            CONFIRMED,
            f"{field_name} is written {where} through {', '.join(via)}, "
            "which holds all of its bytes".replace("  ", " "),
            [r["location"] for r in here(sure)],
        )
    if here(possible):
        via = sorted({r["via"] for r in here(possible)})
        return (
            NOT_CHECKABLE,
            f"{', '.join(via)} shares storage with {field_name} and is written "
            f"{where}, but whether that write covers {field_name} is not "
            "settled (a partial overlap, a table element, a duplicated name, "
            "INITIALIZE REPLACING, or a READ / RETURN that may meet end of file)".replace(
                "  ", " "
            ),
            [r["location"] for r in here(possible)],
        )
    rows = direct + sure
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
    extra, sure, possible, placed = _alias_writes(tools, claim)
    direct = _writes(tools, claim) + extra
    rows = direct + sure
    outside = [r for r in rows if _norm(r.get("paragraph")) not in allowed]
    if outside:
        return (
            CONTRADICTED,
            f"{field_name} is also written in "
            + ", ".join(
                sorted(
                    {
                        str(r.get("paragraph"))
                        + (f" (through {r['via']})" if r.get("via") else "")
                        for r in outside
                    }
                )
            ),
            [r["location"] for r in outside],
        )
    maybe = [r for r in possible if _norm(r.get("paragraph")) not in allowed]
    if maybe:
        return (
            NOT_CHECKABLE,
            f"{field_name} may also be written in "
            + ", ".join(
                sorted({f"{r['paragraph']} (through {r['via']})" for r in maybe})
            ),
            [r["location"] for r in maybe],
        )
    if not rows:
        return CONTRADICTED, f"no statement writes {field_name}", []
    if not placed:
        return (
            NOT_CHECKABLE,
            f"every statement naming {field_name} is in "
            f"{', '.join(sorted(allowed))}, but its byte layout could not be "
            "placed, so writes through a parent group or a REDEFINES are not "
            "checked",
            [r["location"] for r in rows],
        )
    return (
        CONFIRMED,
        f"every write of {field_name} is in {', '.join(sorted(allowed))}, "
        "through its parent groups, REDEFINES / RENAMES items and the other "
        "records of its FD / SD too, and no READ / RETURN fills its record area "
        "elsewhere (a VALUE clause or a CALL argument passed by reference is not "
        "a statement write)",
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

    def node_names(node: str) -> set[str]:
        # ``PROG:WS-X``, ``PROG:console:SYSOUT@0+7``, ``SCHEMA.TABLE.COL``:
        # whole names only, never a substring (CUSTOMER-ID is not
        # WS-CUSTOMER-ID).
        node = _norm(node)
        return {node, node.split(".")[-1], node.split(":")[-1].split("@")[0]}

    def names(hit: dict[str, Any]) -> set[str]:
        return node_names(hit.get("field") or "")

    def path_names(hit: dict[str, Any]) -> set[str]:
        found: set[str] = set()
        for step in hit.get("path") or []:
            node = str(step).split(" (")[0]
            found |= node_names(node) | node_names(node.split(":", 1)[-1])
        return found

    matched = [h for h in hits if target in names(h)]
    matched += [h for h in hits if h not in matched and target in path_names(h)]
    for dataset in answer.get("datasets") or []:
        # A GDG generation (BASE(+1)) counts for its base.
        if target and target in {_norm(dataset), _norm(dataset).split("(")[0]}:
            return CONFIRMED, f"the value reaches dataset {dataset}", []
    for table in answer.get("tables") or []:
        # SCHEMA.TABLE counts for TABLE.
        if target and target in {_norm(table), _norm(table).split(".")[-1]}:
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
