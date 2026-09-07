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
        "Charset",
        "DecodeResult",
        "DecodedField",
        "DecodedRecord",
        "PlacedField",
        "RecordDecoder",
        "RecordDecodingError",
        "RecordView",
        "RecordViews",
        "build_record_views",
        "decoded_hex_dump",
        "CoverageSummary",
        "EncodingOptions",
        "Endian",
        "Expectation",
        "FileFacts",
        "FixtureBundle",
        "MAX_VARIABLE_RECORD",
        "OdoControl",
        "ProgramLayoutError",
        "ProgramLayoutIndex",
        "RDW_SIZE",
        "RecordEncodingError",
        "RecordFormat",
        "ResolvedField",
        "Scenario",
        "VaryingLength",
        "encode_rdw",
        "encoding_caveats",
        "minimum_record_length",
        "present_indexes",
        "record_length",
        "row_record_length",
        "storage_size",
    ):
        from .data import (
            BUNDLE_VERSION,
            MAX_VARIABLE_RECORD,
            RDW_SIZE,
            BoundaryFixture,
            Charset,
            CoverageSummary,
            DecodedField,
            DecodedRecord,
            DecodeResult,
            EncodingOptions,
            Endian,
            Expectation,
            FileFacts,
            FixtureBundle,
            OdoControl,
            PlacedField,
            ProgramLayoutError,
            ProgramLayoutIndex,
            RecordDecoder,
            RecordDecodingError,
            RecordEncodingError,
            RecordFormat,
            RecordView,
            RecordViews,
            ResolvedField,
            Scenario,
            VaryingLength,
            build_record_views,
            decoded_hex_dump,
            encode_rdw,
            encoding_caveats,
            minimum_record_length,
            present_indexes,
            record_length,
            row_record_length,
            storage_size,
        )

        _map = {
            "BUNDLE_VERSION": BUNDLE_VERSION,
            "BoundaryFixture": BoundaryFixture,
            "Charset": Charset,
            "DecodeResult": DecodeResult,
            "DecodedField": DecodedField,
            "DecodedRecord": DecodedRecord,
            "PlacedField": PlacedField,
            "RecordDecoder": RecordDecoder,
            "RecordDecodingError": RecordDecodingError,
            "RecordView": RecordView,
            "RecordViews": RecordViews,
            "build_record_views": build_record_views,
            "decoded_hex_dump": decoded_hex_dump,
            "CoverageSummary": CoverageSummary,
            "EncodingOptions": EncodingOptions,
            "Endian": Endian,
            "Expectation": Expectation,
            "FileFacts": FileFacts,
            "FixtureBundle": FixtureBundle,
            "MAX_VARIABLE_RECORD": MAX_VARIABLE_RECORD,
            "OdoControl": OdoControl,
            "ProgramLayoutError": ProgramLayoutError,
            "ProgramLayoutIndex": ProgramLayoutIndex,
            "RDW_SIZE": RDW_SIZE,
            "RecordEncodingError": RecordEncodingError,
            "RecordFormat": RecordFormat,
            "ResolvedField": ResolvedField,
            "Scenario": Scenario,
            "VaryingLength": VaryingLength,
            "encode_rdw": encode_rdw,
            "encoding_caveats": encoding_caveats,
            "minimum_record_length": minimum_record_length,
            "present_indexes": present_indexes,
            "record_length": record_length,
            "row_record_length": row_record_length,
            "storage_size": storage_size,
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
    "Charset",
    "CopybookDataGenerator",
    "CopybookLayoutError",
    "CoverageSummary",
    "DataGeneratorOptions",
    "DecodeResult",
    "DecodedField",
    "DecodedRecord",
    "DotFlowchartGenerator",
    "EncodingOptions",
    "Endian",
    "Expectation",
    "FieldCategory",
    "FieldSpec",
    "FileFacts",
    "FixtureBundle",
    "FlowchartOptions",
    "GeneratedDataset",
    "MAX_VARIABLE_RECORD",
    "MermaidFlowchartGenerator",
    "OdoControl",
    "PlacedField",
    "ProgramFixtureGenerator",
    "ProgramLayoutError",
    "ProgramLayoutIndex",
    "RDW_SIZE",
    "RecordDecoder",
    "RecordDecodingError",
    "RecordEncodingError",
    "RecordFormat",
    "RecordView",
    "RecordViews",
    "ResolvedField",
    "Scenario",
    "VaryingLength",
    "build_record_views",
    "decoded_hex_dump",
    "encode_rdw",
    "encoding_caveats",
    "flatten_record",
    "minimum_record_length",
    "parse_copybook_records",
    "present_indexes",
    "record_length",
    "row_record_length",
    "storage_size",
]
