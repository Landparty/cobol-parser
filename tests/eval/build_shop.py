"""Assemble the benchmark shop: the files checked in under ``shop/`` plus
the samples the repository already holds, laid out as the benchmark ran.

    python tests/eval/build_shop.py /tmp/bench/shop

Only what exists nowhere else in the repository is checked in under
``shop/`` (the order-processing programs, their JCL and PROCLIBs, the
``cobol.yml``); the rest is copied from ``tests/samples`` and
``examples/cobol`` so the shop never drifts from the samples it was made
of.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
SAMPLES = REPO / "tests" / "samples"
NIST = REPO / "examples" / "cobol"


def build_shop(target: Path) -> Path:
    """The shop under *target* (created; must not exist yet)."""
    target = Path(target)
    shutil.copytree(HERE / "shop", target)
    shutil.copytree(SAMPLES / "enterprise", target / "enterprise")
    shutil.copytree(
        SAMPLES / "lineage", target / "fees", ignore=shutil.ignore_patterns("*.jcl")
    )
    jcl = target / "jcl"
    shutil.copy2(SAMPLES / "lineage" / "FEEJOB.jcl", jcl / "FEEJOB.jcl")
    for job in sorted((SAMPLES / "jcl").glob("*.jcl")):
        shutil.copy2(job, jcl / job.name)
    (target / "legacy" / "nist").mkdir(parents=True)
    (target / "legacy" / "copy").mkdir()
    for program in sorted(NIST.glob("IC*.CBL")):
        shutil.copy2(program, target / "legacy" / "nist" / program.name)
    for member in sorted(NIST.glob("*.CPY")):
        shutil.copy2(member, target / "legacy" / "copy" / member.name)
    return target


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: build_shop.py TARGET_DIR")
    print(build_shop(Path(sys.argv[1])))
