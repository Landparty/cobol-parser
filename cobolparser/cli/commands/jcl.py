"""The jcl subcommand: jobs, steps and DD bindings."""

from __future__ import annotations

import argparse
import sys
from typing import Any

from .._common import _add_compact_arg, _add_output_arg, _fail, _json_out, _read_source

# -- Subcommand: jcl ----------------------------------------------------------


def _build_jcl_parser(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "jcl",
        help="Parse z/OS JCL: which program each step runs, and which dataset "
        "each DD name is bound to",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  cobol-parser jcl JOB.jcl\n"
            "  cobol-parser jcl JOB.jcl --dd-map\n"
            "  cobol-parser jcl JOB.jcl --bindings\n"
            "  cobol-parser jcl JOB.jcl --program INVUPDT\n"
            "  cobol-parser jcl JOB.jcl --proc-path proclib/ --bindings\n"
            "  cobol-parser jcl JOB.jcl --strict"
        ),
    )
    p.add_argument("file", help="Path to the JCL file")
    p.add_argument(
        "--dd-map",
        action="store_true",
        help="Emit only the DD name -> datasets mapping, which is what a "
        "COBOL SELECT ... ASSIGN TO ddname resolves through",
    )
    p.add_argument(
        "--bindings",
        action="store_true",
        help="Emit one row per DD binding (ddname, dataset, step, job, DISP, "
        "RECFM, LRECL, program) instead of the job structure; usable as "
        "field-impact --bindings input",
    )
    p.add_argument(
        "--program",
        metavar="NAME",
        help="Report only the steps that run this program",
    )
    p.add_argument(
        "--proc-path",
        action="append",
        default=[],
        metavar="DIR",
        help="Directory holding cataloged procedures and INCLUDE members, one "
        "member per file named after it (repeatable, searched in order). "
        "Without it only in-stream procedures are expanded",
    )
    p.add_argument(
        "--strict",
        action="store_true",
        help="Exit 3 when any card could not be parsed (a CI gate, kept "
        "distinct from exit 1, which still means the run itself failed)",
    )
    _add_compact_arg(p)
    _add_output_arg(p)
    p.set_defaults(func=_cmd_jcl)


def _cmd_jcl(args: argparse.Namespace) -> None:
    """Parse a JCL file.

    The only subcommand that reads a language other than COBOL, so it shares
    none of the COBOL parse flags -- there is no dialect, no source format
    and no copybook path to honour. What it exists for is the join: a COBOL
    ``SELECT INV-FILE ASSIGN TO INVFILE`` names a DD, and only the JCL says
    which dataset that DD is.
    """
    from ...jcl import parse_jcl, resolve_dd_bindings

    source = _read_source(args.file)
    try:
        result = parse_jcl(
            source, filename=args.file, proc_paths=getattr(args, "proc_path", None)
        )
    except ImportError as exc:
        # jcl-parser is the optional [jcl] extra: a plain install is a
        # configuration error to name on one line (the install hint), not a
        # traceback.
        _fail(str(exc))

    payload: dict[str, Any]
    if args.bindings:
        bindings = resolve_dd_bindings(result)
        if args.program:
            # Keyed by job as well as step name: in a deck of several jobs,
            # `S1` of another job runs another program, and its DDs are not
            # this program's.
            running = {id(s) for s in result.steps_running(args.program)}
            wanted = {
                (id(job), step.name)
                for job in result.jobs
                for step in job.steps
                if id(step) in running
            }
            bindings = [
                binding
                for binding, (job, _step, _dd) in zip(
                    bindings, result.all_dd_statements(), strict=True
                )
                if (id(job), binding.step) in wanted
            ]
        payload = {"bindings": [b.to_dict() for b in bindings]}
    elif args.dd_map:
        dd_map = result.dd_map()
        if args.program:
            # Only the DDs of the steps that run this program, exactly as
            # ``--bindings --program`` filters; ``--dd-map --program`` used
            # to return every step's DDs and silently ignore the program.
            # The datasets too come from those steps only: a DD name shared
            # with another step (SYSTSIN, SYSIN) must not bring its datasets.
            running = {id(s) for s in result.steps_running(args.program)}
            dd_map = {}
            for _job, owner, dd in result.all_dd_statements():
                if owner is None or id(owner) not in running:
                    continue
                bucket = dd_map.setdefault(dd.name.upper(), [])
                if dd.dataset is not None and dd.dataset not in bucket:
                    bucket.append(dd.dataset)
        payload = {"dd_map": dd_map}
    elif args.program:
        payload = {
            "program": args.program,
            "steps": [s.to_dict() for s in result.steps_running(args.program)],
        }
    else:
        payload = result.to_dict()

    # Errors and unresolved travel with every view, not just the default
    # one: a --dd-map that silently omitted the cards it could not read
    # would be the exact failure mode this repo's reports exist to avoid.
    payload.setdefault(
        "errors", [{"line": e["line"], "message": e["message"]} for e in result.errors]
    )
    payload.setdefault("unresolved", list(result.unresolved))

    _json_out(
        {"source_file": args.file, **payload},
        args.compact,
        getattr(args, "output", None),
    )

    if args.program and not result.steps_running(args.program):
        # Like every analyzer's --program: an empty answer for a name that
        # matches nothing must not read as "this JCL never runs it" quietly.
        _fail(f"--program {args.program}: no step in {args.file} runs it")
    if args.strict and result.errors:
        sys.exit(3)
