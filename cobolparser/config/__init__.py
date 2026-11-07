"""The universal project config file (``cobol.yml``).

One file per project, read by every tool in the family. See
`cobolparser.config.project` for the schema and discovery rules, and
`docs/project-config.md` for the user-facing reference.

    from cobolparser.config import load_project_config

    config = load_project_config()          # walks up from the cwd
    config.copybook_path                     # absolute, relative to the file
    config.tool_section("mockymock")          # another tool's raw section
"""

from ._yaml import YamlError, parse_yaml
from .project import (
    CONFIG_FILE_NAMES,
    SCHEMA_VERSION,
    ConfigError,
    DataDefaults,
    LimitDefaults,
    LintDefaults,
    ProjectConfig,
    build_config,
    find_config_file,
    load_project_config,
    resolve,
)

__all__ = [
    "CONFIG_FILE_NAMES",
    "ConfigError",
    "DataDefaults",
    "LimitDefaults",
    "LintDefaults",
    "ProjectConfig",
    "SCHEMA_VERSION",
    "YamlError",
    "build_config",
    "find_config_file",
    "load_project_config",
    "parse_yaml",
    "resolve",
]
