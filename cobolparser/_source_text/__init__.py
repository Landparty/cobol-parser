"""Source text before tokens: fixed-format normalization, source-format
detection, compiler-directive stripping, conditional compilation and the
preprocessing exception hierarchy.

A leaf of the layer stack (it imports only ``_lines`` and
``_source_directive``), so the lexer can normalize fixed-format source and
read the indicator sets without importing :mod:`cobolparser.preprocess`,
which sits above it. :mod:`cobolparser.preprocess` re-exports the public
names, and ``cobolparser.preprocess._normalize`` /
``cobolparser.preprocess.source_format`` remain aliases of these modules.
"""
