"""The package version, in a leaf module.

Lower layers (the facts cache, ``CobolProgram.to_dict()`` metadata, SARIF
output, the CLI ``--version``) need the version string. Importing it from
the ``cobolparser`` facade would make each of them depend on the top of the
package; this module has no imports, so anything may read it. release-please
rewrites the line marked ``x-release-please-version``.
"""

__version__ = "4.0.1"  # x-release-please-version
