"""The program a step really runs, when ``PGM=`` names a launcher.

A DB2 batch program is run as ``EXEC PGM=IKJEFT01`` (or ``IKJEFT1A`` /
``IKJEFT1B``) with ``RUN PROGRAM(x)`` in its ``SYSTSIN``; an IMS batch
program as ``EXEC PGM=DFSRRC00,PARM='DLI,x,...'``. Asked which steps run
``x``, both ``JclParseResult.steps_running`` and field lineage
(``analysis.lineage_jcl``) read the launcher's input through this one copy
of the rules, so the two JCL consumers cannot disagree about a deck.

Pure text in, names out: no dependency on jcl-parser or on either model.
"""

from __future__ import annotations

import re

#: TSO terminal monitor programs: ``RUN PROGRAM(x)`` in ``SYSTSIN``.
TSO_PROGRAMS = frozenset({"IKJEFT01", "IKJEFT1A", "IKJEFT1B"})
#: The IMS region controller: the program is a ``PARM`` positional.
IMS_CONTROLLER = "DFSRRC00"
#: IMS region types whose ``PARM`` names the application program second.
IMS_BATCH_REGIONS = frozenset({"DLI", "DBB", "BMP"})
RUN_PROGRAM_RE = re.compile(r"\bRUN\s+PROGRAM\s*\(\s*([A-Z0-9@#$]+)\s*\)")


def run_programs(systsin: str) -> list[str]:
    """Every program a TSO ``SYSTSIN`` runs (``RUN PROGRAM(x)``), in order,
    each once."""
    return list(
        dict.fromkeys(m.group(1) for m in RUN_PROGRAM_RE.finditer(systsin.upper()))
    )


def ims_program(parm: object) -> str | None:
    """The application program of an IMS batch region: the second ``PARM``
    positional when the first is ``DLI`` / ``DBB`` / ``BMP``. ``parm`` is the
    coded text (``'BMP,LOANPMT,LOANPSB'``) or its positionals as a list."""
    if isinstance(parm, (list, tuple)):
        parts = [str(p) for p in parm]
    elif parm is not None:
        parts = str(parm).strip().strip("()'").split(",")
    else:
        return None
    parts = [p.strip().strip("'").upper() for p in parts]
    if len(parts) > 1 and parts[0] in IMS_BATCH_REGIONS and parts[1]:
        return parts[1]
    return None
