"""Opt-in switch for the optional Cython accelerators.

The pure-Python implementation is the default backend. The three compiled
accelerators (``_lexer_fast``, ``_preprocess_fast``, ``_data_fast``) are used
only when ``COBOLPARSER_ACCEL=1`` is set in the environment -- at build time,
so ``setup.py`` compiles them, and at import time, so the modules that own a
fast path swap it in. An installed extension is ignored without the variable,
so a stale or mismatched binary can never change what a default install does.

Zero internal dependencies: ``setup.py`` does not import this module (it reads
the same variable itself), but every runtime import site does.
"""

import os

ENV_VAR = "COBOLPARSER_ACCEL"

_TRUTHY = frozenset({"1", "true", "yes", "on"})


def accelerators_enabled() -> bool:
    """True when the environment opts in to the Cython accelerators.

    Read on every call rather than cached, so a test can flip the variable and
    reload a module that owns a fast path.
    """
    return os.environ.get(ENV_VAR, "").strip().lower() in _TRUTHY
