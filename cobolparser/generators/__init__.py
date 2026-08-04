"""Code generators for COBOL parser."""


# Lazy import (mirrors cobolparser.analysis.__init__): cobolparser.generators
# eagerly re-exporting every submodule at package-init time was the root
# cause of a recurring circular import -- program_fixtures.py (reached via
# this package's own init chain) genuinely depends at runtime on
# cobolparser.analysis.constraints / .domains / .program_flow, which in turn
# are reachable from cobolparser.analysis modules that need generators.data.*
# utilities. Importing any single one of those as the *first* touch of the
# package used to fail with "partially initialized module" -- found three
# times over (bundle.py, boundary_inventory.py, constraints.py, domains.py)
# before this fix addressed the actual root cause instead of patching each
# occurrence individually.
def __getattr__(name: str) -> object:
    if name in (
        "CopybookDataGenerator",
        "CopybookLayoutError",
        "DataGeneratorOptions",
        "FieldCategory",
        "FieldSpec",
        "GeneratedDataset",
        "flatten_record",
        "parse_copybook_records",
    ):
        from .copybook_data import (
            CopybookDataGenerator,
            CopybookLayoutError,
            DataGeneratorOptions,
            FieldCategory,
            FieldSpec,
            GeneratedDataset,
            flatten_record,
            parse_copybook_records,
        )

        _map = {
            "CopybookDataGenerator": CopybookDataGenerator,
            "CopybookLayoutError": CopybookLayoutError,
            "DataGeneratorOptions": DataGeneratorOptions,
            "FieldCategory": FieldCategory,
            "FieldSpec": FieldSpec,
            "GeneratedDataset": GeneratedDataset,
            "flatten_record": flatten_record,
            "parse_copybook_records": parse_copybook_records,
        }
        return _map[name]
    if name in (
        "BUNDLE_VERSION",
        "BoundaryFixture",
        "CoverageSummary",
        "Expectation",
        "FileFacts",
        "FixtureBundle",
        "ProgramLayoutError",
        "ProgramLayoutIndex",
        "ResolvedField",
        "Scenario",
    ):
        from .data import (
            BUNDLE_VERSION,
            BoundaryFixture,
            CoverageSummary,
            Expectation,
            FileFacts,
            FixtureBundle,
            ProgramLayoutError,
            ProgramLayoutIndex,
            ResolvedField,
            Scenario,
        )

        _map = {
            "BUNDLE_VERSION": BUNDLE_VERSION,
            "BoundaryFixture": BoundaryFixture,
            "CoverageSummary": CoverageSummary,
            "Expectation": Expectation,
            "FileFacts": FileFacts,
            "FixtureBundle": FixtureBundle,
            "ProgramLayoutError": ProgramLayoutError,
            "ProgramLayoutIndex": ProgramLayoutIndex,
            "ResolvedField": ResolvedField,
            "Scenario": Scenario,
        }
        return _map[name]
    if name in (
        "DotFlowchartGenerator",
        "FlowchartOptions",
        "MermaidFlowchartGenerator",
    ):
        from .flowchart import (
            DotFlowchartGenerator,
            FlowchartOptions,
            MermaidFlowchartGenerator,
        )

        _map = {
            "DotFlowchartGenerator": DotFlowchartGenerator,
            "FlowchartOptions": FlowchartOptions,
            "MermaidFlowchartGenerator": MermaidFlowchartGenerator,
        }
        return _map[name]
    if name == "ProgramFixtureGenerator":
        from .program_fixtures import ProgramFixtureGenerator

        return ProgramFixtureGenerator
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "BUNDLE_VERSION",
    "BoundaryFixture",
    "CopybookDataGenerator",
    "CopybookLayoutError",
    "CoverageSummary",
    "DataGeneratorOptions",
    "DotFlowchartGenerator",
    "Expectation",
    "FieldCategory",
    "FieldSpec",
    "FileFacts",
    "FixtureBundle",
    "FlowchartOptions",
    "GeneratedDataset",
    "MermaidFlowchartGenerator",
    "ProgramFixtureGenerator",
    "ProgramLayoutError",
    "ProgramLayoutIndex",
    "ResolvedField",
    "Scenario",
    "flatten_record",
    "parse_copybook_records",
]
