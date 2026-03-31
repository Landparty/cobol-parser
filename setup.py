import setuptools  # must be imported before mypyc to patch distutils on Python 3.12+
from mypyc.build import mypycify
from setuptools import setup

modules = [
    "cobolparser/__init__.py",
    "cobolparser/_errors.py",
    "cobolparser/batch.py",
    "cobolparser/lexer.py",
    "cobolparser/parser.py",
    # analysis
    "cobolparser/analysis/__init__.py",
    "cobolparser/analysis/io_coverage_reporter.py",
    "cobolparser/analysis/io_diagnostics.py",
    "cobolparser/analysis/value_tracker.py",
    # core
    "cobolparser/core/__init__.py",
    "cobolparser/core/ast_factory.py",
    "cobolparser/core/exceptions.py",
    "cobolparser/core/interfaces.py",
    "cobolparser/core/registry.py",
    "cobolparser/core/token_stream.py",
    # dialects
    "cobolparser/dialects/__init__.py",
    "cobolparser/dialects/ibm_enterprise.py",
    # models
    "cobolparser/models/__init__.py",
    "cobolparser/models/ast_base.py",
    "cobolparser/models/data_items.py",
    "cobolparser/models/program.py",
    "cobolparser/models/sql_statements.py",
    "cobolparser/models/statements/__init__.py",
    "cobolparser/models/statements/arithmetic.py",
    "cobolparser/models/statements/base.py",
    "cobolparser/models/statements/call.py",
    "cobolparser/models/statements/control.py",
    "cobolparser/models/statements/data.py",
    "cobolparser/models/statements/io.py",
    "cobolparser/models/statements/misc.py",
    # parsers
    "cobolparser/parsers/__init__.py",
    "cobolparser/parsers/divisions/__init__.py",
    "cobolparser/parsers/divisions/base.py",
    "cobolparser/parsers/divisions/data.py",
    "cobolparser/parsers/divisions/environment.py",
    "cobolparser/parsers/divisions/factory.py",
    "cobolparser/parsers/divisions/identification.py",
    "cobolparser/parsers/divisions/procedure.py",
    "cobolparser/parsers/statements/__init__.py",
    "cobolparser/parsers/statements/_utils.py",
    "cobolparser/parsers/statements/arithmetic_parsers.py",
    "cobolparser/parsers/statements/call_parser.py",
    "cobolparser/parsers/statements/close_parser.py",
    "cobolparser/parsers/statements/delete_parser.py",
    "cobolparser/parsers/statements/display_parser.py",
    "cobolparser/parsers/statements/entry_parser.py",
    "cobolparser/parsers/statements/evaluate_parser.py",
    "cobolparser/parsers/statements/go_parser.py",
    "cobolparser/parsers/statements/ibm_exec_statements.py",
    "cobolparser/parsers/statements/if_parser.py",
    "cobolparser/parsers/statements/move_parser.py",
    "cobolparser/parsers/statements/open_parser.py",
    "cobolparser/parsers/statements/perform_parser.py",
    "cobolparser/parsers/statements/read_parser.py",
    "cobolparser/parsers/statements/rewrite_parser.py",
    "cobolparser/parsers/statements/start_parser.py",
    "cobolparser/parsers/statements/stop_parser.py",
    "cobolparser/parsers/statements/write_parser.py",
    # plugins
    "cobolparser/plugins/__init__.py",
    "cobolparser/plugins/core.py",
    # preprocess
    "cobolparser/preprocess/__init__.py",
    "cobolparser/preprocess/copy_statement_parser.py",
    "cobolparser/preprocess/copybook_expander.py",
    "cobolparser/preprocess/models.py",
    "cobolparser/preprocess/path_resolver.py",
]

setup(
    ext_modules=mypycify(modules),
)
