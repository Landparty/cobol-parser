"""The cobol-parser subcommands, one module per area.

Each module holds, per subcommand, a ``_build_<name>_parser()`` that adds
the subparser and a ``_cmd_<name>()`` handler; ``cli/parse.py`` assembles
them into the top-level parser.
"""
