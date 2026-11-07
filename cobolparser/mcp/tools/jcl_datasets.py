"""The ``dataset_users`` tool: every job, step and program that uses a dataset
or DB2 table, with DB2 utility SQL and the COBOL programs whose EXEC SQL
touch a table."""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..._lines import split_source_lines
from ...jcl.models import JobStep
from ..envelope import Response, ToolError, clamp_limit
from ..workspace import Workspace
from .jcl_common import (
    _MEMBER_RE,
    _WRITES,
    _access,
    _base,
    _cards,
    _carry_index,
    _ControlMembers,
    _idcams_named,
    _ProgramUses,
    _step_access,
    _utility_uses,
)
from .jcl_index import JclFile, _Locator, jcl_index


def _filter_regex(pattern: str) -> re.Pattern[str]:
    """A z/OS dataset name filter as a regex: ``%`` is one character, ``*``
    any characters within one qualifier, ``**`` any number of qualifiers
    (``A.**`` is ``A`` and everything under it)."""
    out = ""
    qualifiers = pattern.split(".")
    for n, qualifier in enumerate(qualifiers):
        if qualifier == "**":
            if n == 0:
                out = r"(?:[^.]+\.)*" if len(qualifiers) > 1 else r".+"
            else:
                out = out[:-2] + r"(?:\.[^.]+)*\."
            continue
        out += "".join(
            "[^.]*" if c == "*" else "[^.]" if c == "%" else re.escape(c)
            for c in qualifier
        )
        out += r"\."
    if out.endswith(r"\."):
        out = out[:-2]
    return re.compile(out)


def _matcher(pattern: str) -> Callable[[str], bool]:
    wanted = pattern.strip().strip("'").upper()
    if not wanted:
        raise ToolError("no dataset given")
    if any(c in wanted for c in "*%"):
        regex = _filter_regex(wanted)
        return lambda ds: bool(regex.fullmatch(ds) or regex.fullmatch(_base(ds)))
    if "(" in wanted:
        return lambda ds: ds == wanted
    return lambda ds: _base(ds) == wanted


#: The DB2 sample programs that run the SQL statements in their SYSIN:
#: DSNTEP2 / DSNTEP4 (any SQL), DSNTIAD (DDL, DCL and data changes) and
#: DSNTIAUL (an unload: each SELECT writes its rows to a SYSRECnn DD).
_DB2_SQL_PROGRAMS = frozenset({"DSNTEP2", "DSNTEP4", "DSNTIAD", "DSNTIAUL"})


_TSO_PROGRAMS = frozenset({"IKJEFT01", "IKJEFT1A", "IKJEFT1B"})


_RUN_PROGRAM_RE = re.compile(r"\bRUN\s+PROG(?:RAM)?\s*\(\s*([A-Z0-9@#$]+)\s*\)")


_SQL_NAME = r"([A-Z0-9@#$_]+(?:\.[A-Z0-9@#$_]+){0,2})"


#: (statement start, access) for the table a SQL statement changes.
_SQL_CHANGES = (
    (re.compile(rf"INSERT\s+INTO\s+{_SQL_NAME}"), "insert"),
    (re.compile(rf"UPDATE\s+{_SQL_NAME}"), "update"),
    (re.compile(rf"DELETE\s+FROM\s+{_SQL_NAME}"), "delete"),
    (re.compile(rf"MERGE\s+INTO\s+{_SQL_NAME}"), "merge"),
    (re.compile(rf"TRUNCATE\s+(?:TABLE\s+)?{_SQL_NAME}"), "delete"),
    (re.compile(rf"CREATE\s+TABLE\s+{_SQL_NAME}"), "create table"),
    (re.compile(rf"DROP\s+TABLE\s+{_SQL_NAME}"), "drop table"),
    (re.compile(rf"ALTER\s+TABLE\s+{_SQL_NAME}"), "alter table"),
    (
        re.compile(rf"CREATE\s+(?:UNIQUE\s+)?INDEX\s+\S+\s+ON\s+{_SQL_NAME}"),
        "create index",
    ),
)


_SQL_READS = re.compile(rf"\b(?:FROM|JOIN)\s+{_SQL_NAME}")


_SQL_CURSOR_RE = re.compile(
    r"\b(?:OPEN|FETCH)\s+(?:(?:NEXT|PRIOR|FIRST|LAST|FROM)\s+)*([A-Z][A-Z0-9-]*)"
)


def _control_dd(
    step: JobStep, ddname: str, members: _ControlMembers, jfile: JclFile
) -> tuple[Path | None, list[tuple[int, str]]]:
    """The cards of a step's control DD (SYSIN, SYSTSIN), in-stream (line
    0: the DD card's location is the step's) or from the member under the
    root its ``DSN=LIB(MEMBER)`` names, with that member's line numbers;
    ``/* */`` comment lines and the sequence area (73-80) dropped."""
    for dd in step.dd_statements:
        if (dd.name or "").upper() != ddname:
            continue
        if dd.is_instream:
            return None, [(0, ln.upper()) for ln in dd.instream_lines if ln.strip()]
        found = _MEMBER_RE.search(dd.dataset or "")
        path = members.find(found.group(1), jfile.display) if found else None
        if path is None:
            return None, []
        cards = []
        for number, line in enumerate(split_source_lines(Workspace.read_text(path))):
            card = line[:72].strip()
            if card and not card.startswith(("/*", "*")):
                cards.append((number + 1, card.upper()))
        return path, cards
    return None, []


def _sql_statements(cards: list[tuple[int, str]]) -> list[tuple[int, str, str]]:
    """``(first line, statement, statement with its literals blanked)`` for
    each ``;``-ended SQL statement in *cards*, ``--`` comments dropped and
    blanks collapsed. The blanked copy is what to search for table names."""
    out: list[tuple[int, str, str]] = []
    held: list[tuple[str, str]] = []
    start = 0

    def flush() -> None:
        raw = " ".join(" ".join(r for r, _ in held).split())
        blanked = " ".join(" ".join(b for _, b in held).split())
        out.append((start, raw, blanked))
        held.clear()

    for number, card in cards:
        # Literal contents blanked in place, so offsets match the card.
        blanked = re.sub(r"'[^']*'", lambda m: "'" + " " * (len(m[0]) - 2) + "'", card)
        cut = blanked.find("--")
        if cut >= 0:
            card, blanked = card[:cut], blanked[:cut]
        at = 0
        for i, piece in enumerate(blanked.split(";")):
            raw = card[at : at + len(piece)]
            at += len(piece) + 1
            if i and held:
                flush()
            if piece.strip():
                if not held:
                    start = number
                held.append((raw, piece))
    if held:
        flush()
    return out


def _sql_tables(statement: str) -> list[tuple[str, str]]:
    """``(table, access)`` for the tables one SQL statement names: the one
    it changes (insert, update, delete, merge, create / drop / alter table,
    create index), and any it reads (FROM, JOIN)."""
    found: list[tuple[str, str]] = []
    for regex, access in _SQL_CHANGES:
        match = regex.match(statement)
        if match:
            found.append((match.group(1), access))
            break
    changed = {table for table, _ in found}
    for match in _SQL_READS.finditer(statement):
        if match.group(1) not in changed and (match.group(1), "read") not in found:
            found.append((match.group(1), "read"))
    return found


def _db2_program(
    step: JobStep, members: _ControlMembers, jfile: JclFile
) -> tuple[str, str] | None:
    """``(program, how)`` when *step* runs a DB2 SQL utility: directly, or
    as TSO ``RUN PROGRAM(...)`` in SYSTSIN under IKJEFT01."""
    program = (step.program or "").upper()
    if program in _DB2_SQL_PROGRAMS:
        return program, f"EXEC PGM={program}"
    if program not in _TSO_PROGRAMS:
        return None
    path, cards = _control_dd(step, "SYSTSIN", members, jfile)
    text = " ".join(card for _, card in cards)
    found = _RUN_PROGRAM_RE.search(text)
    if found is None or found.group(1) not in _DB2_SQL_PROGRAMS:
        return None
    where = "in-stream SYSTSIN" if path is None else f"SYSTSIN member {path.stem}"
    return found.group(1), f"{program} RUN PROGRAM({found.group(1)}) ({where})"


def _db2_utility_uses(
    step: JobStep, members: _ControlMembers, jfile: JclFile, workspace: Workspace
) -> list[dict[str, Any]]:
    """The SQL tables a DB2 utility step's SYSIN statements name, one row per
    table and access: what it does, the statement's text and where it is
    (the control member's line, or the step for in-stream SQL). A DSNTIAUL
    SELECT says the SYSRECnn dataset it unloads to; DSNTIAUL without
    ``PARMS('SQL')`` unloads each table its SYSIN names whole."""
    runs = _db2_program(step, members, jfile)
    if runs is None:
        return []
    program, how = runs
    path, cards = _control_dd(step, "SYSIN", members, jfile)
    statements = _sql_statements(cards)
    unload_sql = program == "DSNTIAUL" and "SQL" in (
        " ".join(c for _, c in _control_dd(step, "SYSTSIN", members, jfile)[1])
        + " "
        + (step.parm or "").upper()
    )
    sysrec = {
        (dd.name or "").upper(): dd.dataset
        for dd in step.dd_statements
        if (dd.name or "").upper().startswith("SYSREC")
    }
    rows: list[dict[str, Any]] = []
    selects = 0
    for line, statement, blanked in statements:
        if program == "DSNTIAUL" and not unload_sql:
            tables = [(blanked.split()[0], "read")]
        else:
            tables = _sql_tables(blanked)
        unloads = program == "DSNTIAUL" and (
            not unload_sql or statement.startswith(("SELECT", "WITH"))
        )
        target = None
        if unloads:
            target = sysrec.get(f"SYSREC{selects:02d}")
            selects += 1
        for table, access in tables:
            row: dict[str, Any] = {
                "table": table,
                "access": access,
                "program": program,
                "runs_as": how,
                "sql": statement if len(statement) <= 200 else statement[:199] + "…",
                "sql_from": (
                    "in-stream SYSIN"
                    if path is None
                    else f"SYSIN member {workspace.display(path)}"
                ),
            }
            if path is not None and line:
                row["sql_location"] = {"file": workspace.display(path), "line": line}
            if target:
                row["unloaded_to"] = target
            rows.append(row)
    return rows


def _jobs_by_effect(found: list[dict[str, Any]]) -> dict[str, Any]:
    """The jobs that change the dataset (any use but a read: a write,
    load, delete, define, or DISP=OLD with nothing more known), each with
    every step that uses it and what it does (a utility's copy with where
    it copies from or to), and the jobs that only read it. Counted,
    so an answer's "N jobs change it" is never a guess."""
    changing = {str(r["job"]) for r in found if r["access"] != "read"}
    steps: dict[str, list[tuple[tuple[int, int], str]]] = {}
    readers: set[str] = set()
    for row in found:
        job = str(row["job"])
        if job not in changing:
            readers.add(job)
            continue
        what = row.get("command") or row["access"]
        said = f"{row['step'] or 'JOB'}: {what}"
        if row["access"] not in what.lower():
            said += f" ({row['access']})"
        if row.get("access_from") in ("utility", "program") and row["programs"]:
            said += " by " + ", ".join(row["programs"])
        if row.get("copied_from"):
            said += " from " + ", ".join(row["copied_from"])
        if row.get("copied_to"):
            said += " to " + ", ".join(row["copied_to"])
        at = (
            (row.get("location") or {}).get("line") or 0,
            (row.get("sql_location") or {}).get("line") or 0,
        )
        if all(said != text for _, text in steps.setdefault(job, [])):
            steps[job].append((at, said))
    # In the order the steps are coded (cards of one JCL file), and a DB2
    # utility step's statements in their order.
    changes = {job: [t for _, t in sorted(rows)] for job, rows in steps.items()}
    only_read = sorted(readers - set(changes))
    return {
        "change_it": {"count": len(changes), "jobs": dict(sorted(changes.items()))},
        "only_read_it": {"count": len(only_read), "jobs": only_read},
    }


def _utility_datasets(step: JobStep, use: str) -> list[str]:
    """The datasets a utility step reads (*use* "read": SORTIN, SYSUT1, a
    REPRO INFILE or INDATASET, an ICETOOL FROM) or writes ("write")."""
    uses = _utility_uses(step) or {}
    found: list[str] = []
    for dd in step.dd_statements:
        if uses.get((dd.name or "").upper()) == use and dd.dataset:
            found.append(dd.dataset)
    for key, value in uses.items():
        if key.startswith("DSN:") and value == use:
            found.append(key[4:])
    side = "INDATASET" if use == "read" else "OUTDATASET"
    for named, access, command in _idcams_named(step):
        if side in command and (access == "read") == (use == "read"):
            found.append(named)
    return list(dict.fromkeys(found))


def _sql_programs(workspace: Workspace, table: str) -> dict[str, Any] | None:
    """The programs whose EXEC SQL names DB2 table *table* (qualified or
    not), split into those that change its rows (each statement with its
    paragraph and line) and those that only read it; None when none does."""
    from ..navigation import _operand_roles, statements_index

    changed: dict[str, list[str]] = {}
    read: dict[str, list[str]] = {}
    for row in statements_index(workspace).rows:
        if not row.verb.startswith("EXEC SQL"):
            continue
        roles = _operand_roles(row.operands, table)
        if roles is None:
            continue
        what = row.verb.removeprefix("EXEC SQL ")
        cursor = _SQL_CURSOR_RE.search(row.text.upper())
        if cursor is not None:
            what += f" cursor {cursor.group(1)}"
        said = f"{what} in {row.paragraph or '-'} at {row.file}:{row.line}"
        bucket = changed if set(roles) - {"read"} else read
        held = bucket.setdefault(row.program, [])
        if said not in held:
            held.append(said)
    if not changed and not read:
        return None
    only_read = {k: v for k, v in read.items() if k not in changed}
    for program, reads in read.items():
        if program in changed:
            changed[program] += reads
    return {
        "change_it": {"count": len(changed), "programs": dict(sorted(changed.items()))},
        "only_read_it": {
            "count": len(only_read),
            "programs": dict(sorted(only_read.items())),
        },
        "note": "EXEC SQL statements in COBOL programs under the root that "
        "name this table; jobs_running on a program says which JCL runs it",
    }


def dataset_users(
    workspace: Workspace, dataset: str, limit: int | None = None
) -> dict[str, Any]:
    """Every DD under the root that names *dataset*, and what it does."""
    matches = _matcher(dataset)
    index = jcl_index(workspace)
    response = Response()

    found: list[dict[str, Any]] = []
    programs = _ProgramUses(workspace, response)
    members = _ControlMembers(workspace)
    for jfile in index.parsed():
        assert jfile.result is not None
        locator = _Locator(jfile, workspace)
        for job, step, dd, path in _cards(jfile.result, locator):
            if dd.dataset is None or not matches(dd.dataset.upper()):
                continue
            row: dict[str, Any] = {
                "dataset": dd.dataset,
                "file": jfile.display,
                "job": job.name,
                "step": None if step is None else step.name,
                "programs": [] if step is None else step.effective_programs(),
                "ddname": dd.name,
                "disposition": dd.disposition,
                "location": locator.at(path, dd.line),
            }
            access, source = _step_access(step, dd, _access(dd.disposition), programs)
            row["access"] = access
            row["access_from"] = source
            if source != "disp":
                row["disposition_access"] = _access(dd.disposition)
            if source == "program" and step is not None:
                row["access_because"] = programs.because(
                    step, dd.name or "", dd.disposition
                )
            if source == "utility" and step is not None:
                if access in _WRITES:
                    inputs = _utility_datasets(step, "read")
                    if inputs:
                        row["copied_from"] = inputs
                elif access == "read":
                    outputs = _utility_datasets(step, "write")
                    if outputs:
                        row["copied_to"] = outputs
            if dd.dataset.startswith("&&"):
                row["temporary"] = True
            found.append(row)

        for job in jfile.result.jobs:
            for step in job.steps:
                for use in _db2_utility_uses(step, members, jfile, workspace):
                    table = str(use["table"])
                    if not (matches(table) or matches(table.rsplit(".", 1)[-1])):
                        continue
                    access = str(use["access"])
                    verb = str(use["sql"]).split(" ", 1)[0]
                    command = f"{use['program']} " + (
                        verb if access == "read" else access.upper()
                    )
                    row = {
                        "dataset": table,
                        "file": jfile.display,
                        "job": job.name,
                        "step": step.name,
                        "programs": [use["program"]],
                        "ddname": None,
                        "command": command,
                        "access": use["access"],
                        "access_from": "db2 sql",
                        "location": locator.step(step),
                        **{
                            k: use[k]
                            for k in ("runs_as", "sql_from", "sql_location", "sql")
                            if k in use
                        },
                    }
                    if "unloaded_to" in use:
                        row["copied_to"] = [use["unloaded_to"]]
                    found.append(row)
                for named, access, command in _idcams_named(step):
                    if not matches(named.upper()):
                        continue
                    found.append(
                        {
                            "dataset": named,
                            "file": jfile.display,
                            "job": job.name,
                            "step": step.name,
                            "programs": ["IDCAMS"],
                            "ddname": None,
                            "command": command,
                            "access": access,
                            "access_from": "idcams command",
                            "location": locator.step(step),
                        }
                    )

    wanted = dataset.strip().strip("'").upper()
    _carry_index(
        index,
        response,
        None if any(c in wanted for c in "*%") else _base(wanted),
        {row["file"] for row in found},
    )
    by_access: dict[str, list[str]] = {}
    for row in found:
        bucket = by_access.setdefault(row["access"], [])
        for name in row["programs"] or [f"{row['job']}.{row['step'] or 'JOB'}"]:
            if name not in bucket:
                bucket.append(name)
    answer: dict[str, Any] = {
        "dataset": dataset.strip().strip("'").upper(),
        "use_count": len(found),
        "by_access": by_access,
        "jobs": sorted({row["job"] for row in found}),
        "jobs_by_effect": _jobs_by_effect(found),
        "uses": response.cap(found, clamp_limit(limit), "uses"),
        "jcl_files": len(index.files),
        "access_legend": "access_from program: the COBOL program's OPEN mode "
        "for the DD (read, write, update, extend; create when DISP=NEW); "
        "utility: what SORT, IEBGENER, IDCAMS REPRO or ICETOOL do with the "
        "DD; idcams command: an IDCAMS DELETE, DEFINE, REPRO / BLDINDEX "
        "INDATASET / OUTDATASET or AIX RELATE in SYSIN names the dataset "
        "itself; db2 sql: a DSNTEP2 / DSNTEP4 / DSNTIAD / DSNTIAUL step's "
        "SYSIN SQL names the DB2 table (insert, update, delete, merge, create "
        "/ drop / alter table, create index; read for FROM / JOIN; a DSNTIAUL "
        "unload's copied_to is its SYSRECnn dataset); disp: only DISP= was "
        "known (SHR/OLD say nothing about reading or writing)",
    }
    sql = None if any(c in wanted for c in "*%") else _sql_programs(workspace, wanted)
    if sql:
        answer["sql_programs"] = sql
    if not found and not sql:
        answer["note"] = "no DD under the root names this dataset" + (
            "" if index.files else " (the root holds no .jcl / .job file)"
        )
    elif any(row.get("temporary") for row in found):
        answer["temporary_note"] = (
            "a && temporary dataset exists only within its job: uses in "
            "different jobs are different datasets"
        )
    return response.build(answer)
