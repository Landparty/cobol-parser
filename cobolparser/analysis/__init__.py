"""
Analysis utilities for COBOL AST.

This module provides tools for analyzing COBOL AST structures including
data flow analysis, call graph analysis, value tracking, dead code
detection, and I/O logging.
"""


# Lazy import to avoid circular dependency with cobolparser.plugins
def __getattr__(name: str) -> object:
    if name == "ProgramContext":
        from .context import ProgramContext

        return ProgramContext
    if name == "DynamicCallAnalyzer":
        from .value_tracker import DynamicCallAnalyzer

        return DynamicCallAnalyzer
    if name in ("DeadCodeAnalyzer", "DeadCodeReport", "DeadCodeItem"):
        from .dead_code import DeadCodeAnalyzer, DeadCodeItem, DeadCodeReport

        _map = {
            "DeadCodeAnalyzer": DeadCodeAnalyzer,
            "DeadCodeReport": DeadCodeReport,
            "DeadCodeItem": DeadCodeItem,
        }
        return _map[name]
    if name in ("IOLogger", "IOLogReport", "IOOperation"):
        from .io_logger import IOLogger, IOLogReport, IOOperation

        _map = {
            "IOLogger": IOLogger,
            "IOLogReport": IOLogReport,
            "IOOperation": IOOperation,
        }
        return _map[name]
    if name in (
        "ProgramFlowAnalyzer",
        "ProgramFlowReport",
        "FlowNode",
        "FlowEdge",
        "FlowEdgeType",
        "BranchArm",
        "BranchNode",
    ):
        from .program_flow import (
            BranchArm,
            BranchNode,
            FlowEdge,
            FlowEdgeType,
            FlowNode,
            ProgramFlowAnalyzer,
            ProgramFlowReport,
        )

        _map = {
            "ProgramFlowAnalyzer": ProgramFlowAnalyzer,
            "ProgramFlowReport": ProgramFlowReport,
            "FlowNode": FlowNode,
            "FlowEdge": FlowEdge,
            "FlowEdgeType": FlowEdgeType,
            "BranchArm": BranchArm,
            "BranchNode": BranchNode,
        }
        return _map[name]
    if name in (
        "LanguageEnvironmentAnalyzer",
        "LEAnalysisResult",
        "LEFunctionUsage",
        "LEServiceCall",
    ):
        from .language_env_analyzer import (
            LanguageEnvironmentAnalyzer,
            LEAnalysisResult,
            LEFunctionUsage,
            LEServiceCall,
        )

        _map = {
            "LanguageEnvironmentAnalyzer": LanguageEnvironmentAnalyzer,
            "LEAnalysisResult": LEAnalysisResult,
            "LEFunctionUsage": LEFunctionUsage,
            "LEServiceCall": LEServiceCall,
        }
        return _map[name]
    if name in ("IMSSegmentAnalyzer", "IMSDLICall", "IMSEntryPoint"):
        from .ims_segment_analyzer import IMSDLICall, IMSEntryPoint, IMSSegmentAnalyzer

        _map = {
            "IMSSegmentAnalyzer": IMSSegmentAnalyzer,
            "IMSDLICall": IMSDLICall,
            "IMSEntryPoint": IMSEntryPoint,
        }
        return _map[name]
    if name in (
        "IOSequenceAnalyzer",
        "IOSequenceReport",
        "IOSequenceViolation",
        "IOViolationKind",
    ):
        from .io_sequence import (
            IOSequenceAnalyzer,
            IOSequenceReport,
            IOSequenceViolation,
            IOViolationKind,
        )

        _map = {
            "IOSequenceAnalyzer": IOSequenceAnalyzer,
            "IOSequenceReport": IOSequenceReport,
            "IOSequenceViolation": IOSequenceViolation,
            "IOViolationKind": IOViolationKind,
        }
        return _map[name]
    if name in (
        "MoveTypeChecker",
        "MoveTypeReport",
        "MoveTypeViolation",
        "MoveViolationKind",
        "DataCategory",
    ):
        from .move_type_checker import (
            DataCategory,
            MoveTypeChecker,
            MoveTypeReport,
            MoveTypeViolation,
            MoveViolationKind,
        )

        _map = {
            "MoveTypeChecker": MoveTypeChecker,
            "MoveTypeReport": MoveTypeReport,
            "MoveTypeViolation": MoveTypeViolation,
            "MoveViolationKind": MoveViolationKind,
            "DataCategory": DataCategory,
        }
        return _map[name]
    if name in (
        "LinkageChecker",
        "LinkageReport",
        "LinkageViolation",
        "LinkageViolationKind",
    ):
        from .linkage_checker import (
            LinkageChecker,
            LinkageReport,
            LinkageViolation,
            LinkageViolationKind,
        )

        _map = {
            "LinkageChecker": LinkageChecker,
            "LinkageReport": LinkageReport,
            "LinkageViolation": LinkageViolation,
            "LinkageViolationKind": LinkageViolationKind,
        }
        return _map[name]
    if name in (
        "HostVariableResolver",
        "HostVariableInfo",
        "HostVarResolutionReport",
    ):
        from .host_var_resolver import (
            HostVariableInfo,
            HostVariableResolver,
            HostVarResolutionReport,
        )

        _map = {
            "HostVariableResolver": HostVariableResolver,
            "HostVariableInfo": HostVariableInfo,
            "HostVarResolutionReport": HostVarResolutionReport,
        }
        return _map[name]
    if name in (
        "CRUDMatrixGenerator",
        "CRUDMatrix",
        "CRUDFlags",
        "FileEntry",
        "TableEntry",
    ):
        from .crud_matrix import (
            CRUDFlags,
            CRUDMatrix,
            CRUDMatrixGenerator,
            FileEntry,
            TableEntry,
        )

        _map = {
            "CRUDMatrixGenerator": CRUDMatrixGenerator,
            "CRUDMatrix": CRUDMatrix,
            "CRUDFlags": CRUDFlags,
            "FileEntry": FileEntry,
            "TableEntry": TableEntry,
        }
        return _map[name]
    if name in (
        "UnusedVariableAnalyzer",
        "UnusedVariableReport",
        "UnusedVariableItem",
    ):
        from .unused_variables import (
            UnusedVariableAnalyzer,
            UnusedVariableItem,
            UnusedVariableReport,
        )

        _map = {
            "UnusedVariableAnalyzer": UnusedVariableAnalyzer,
            "UnusedVariableReport": UnusedVariableReport,
            "UnusedVariableItem": UnusedVariableItem,
        }
        return _map[name]
    if name in (
        "RecursionRiskAnalyzer",
        "RecursionRiskReport",
        "RecursionRisk",
    ):
        from .recursion_risk import (
            RecursionRisk,
            RecursionRiskAnalyzer,
            RecursionRiskReport,
        )

        _map = {
            "RecursionRiskAnalyzer": RecursionRiskAnalyzer,
            "RecursionRiskReport": RecursionRiskReport,
            "RecursionRisk": RecursionRisk,
        }
        return _map[name]
    if name in (
        "ComplexityAnalyzer",
        "ComplexityReport",
        "ComplexityThresholds",
        "ProcedureComplexity",
    ):
        from .complexity import (
            ComplexityAnalyzer,
            ComplexityReport,
            ComplexityThresholds,
            ProcedureComplexity,
        )

        _map = {
            "ComplexityAnalyzer": ComplexityAnalyzer,
            "ComplexityReport": ComplexityReport,
            "ComplexityThresholds": ComplexityThresholds,
            "ProcedureComplexity": ProcedureComplexity,
        }
        return _map[name]
    if name in (
        "BusinessRuleExtractor",
        "BusinessRuleReport",
        "BusinessRule",
        "RuleBranch",
        "RuleAction",
        "ConditionNameDefinition",
    ):
        from .business_rules import (
            BusinessRule,
            BusinessRuleExtractor,
            BusinessRuleReport,
            ConditionNameDefinition,
            RuleAction,
            RuleBranch,
        )

        _map = {
            "BusinessRuleExtractor": BusinessRuleExtractor,
            "BusinessRuleReport": BusinessRuleReport,
            "BusinessRule": BusinessRule,
            "RuleBranch": RuleBranch,
            "RuleAction": RuleAction,
            "ConditionNameDefinition": ConditionNameDefinition,
        }
        return _map[name]
    if name in (
        "RedundancyAnalyzer",
        "RedundancyReport",
        "CloneGroup",
        "CloneMember",
    ):
        from .redundancy import (
            CloneGroup,
            CloneMember,
            RedundancyAnalyzer,
            RedundancyReport,
        )

        _map = {
            "RedundancyAnalyzer": RedundancyAnalyzer,
            "RedundancyReport": RedundancyReport,
            "CloneGroup": CloneGroup,
            "CloneMember": CloneMember,
        }
        return _map[name]
    if name in (
        "TechnicalDebtAnalyzer",
        "TechnicalDebtReport",
        "DebtWeights",
        "ComponentBreakdown",
        "OffenderProcedure",
    ):
        from .technical_debt import (
            ComponentBreakdown,
            DebtWeights,
            OffenderProcedure,
            TechnicalDebtAnalyzer,
            TechnicalDebtReport,
        )

        _map = {
            "TechnicalDebtAnalyzer": TechnicalDebtAnalyzer,
            "TechnicalDebtReport": TechnicalDebtReport,
            "DebtWeights": DebtWeights,
            "ComponentBreakdown": ComponentBreakdown,
            "OffenderProcedure": OffenderProcedure,
        }
        return _map[name]
    if name in ("DclgenChecker", "DclgenReport", "DclgenViolation"):
        from .dclgen_check import DclgenChecker, DclgenReport, DclgenViolation

        _map = {
            "DclgenChecker": DclgenChecker,
            "DclgenReport": DclgenReport,
            "DclgenViolation": DclgenViolation,
        }
        return _map[name]
    if name in ("LintAnalyzer", "LintReport", "LintFinding"):
        # RULES/SEVERITIES are deliberately not re-exported here: this
        # __getattr__ hands back classes, and the two rule/severity
        # vocabularies are tuples of strings. Import them from
        # cobolparser.analysis.lint directly.
        from .lint import LintAnalyzer, LintFinding, LintReport

        _map = {
            "LintAnalyzer": LintAnalyzer,
            "LintReport": LintReport,
            "LintFinding": LintFinding,
        }
        return _map[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "ProgramContext",
    "CRUDFlags",
    "DclgenChecker",
    "DclgenReport",
    "DclgenViolation",
    "LintAnalyzer",
    "LintReport",
    "LintFinding",
    "CRUDMatrix",
    "CRUDMatrixGenerator",
    "FileEntry",
    "TableEntry",
    "HostVarResolutionReport",
    "HostVariableInfo",
    "HostVariableResolver",
    "LanguageEnvironmentAnalyzer",
    "LEAnalysisResult",
    "LEFunctionUsage",
    "LEServiceCall",
    "DataCategory",
    "DeadCodeAnalyzer",
    "DeadCodeReport",
    "DeadCodeItem",
    "DynamicCallAnalyzer",
    "IMSDLICall",
    "IMSEntryPoint",
    "IMSSegmentAnalyzer",
    "IOLogger",
    "IOLogReport",
    "IOOperation",
    "IOSequenceAnalyzer",
    "IOSequenceReport",
    "IOSequenceViolation",
    "IOViolationKind",
    "LinkageChecker",
    "LinkageReport",
    "LinkageViolation",
    "LinkageViolationKind",
    "MoveTypeChecker",
    "MoveTypeReport",
    "MoveTypeViolation",
    "MoveViolationKind",
    "ProgramFlowAnalyzer",
    "ProgramFlowReport",
    "FlowNode",
    "FlowEdge",
    "FlowEdgeType",
    "UnusedVariableAnalyzer",
    "UnusedVariableReport",
    "UnusedVariableItem",
    "RecursionRiskAnalyzer",
    "RecursionRiskReport",
    "RecursionRisk",
    "ComplexityAnalyzer",
    "ComplexityReport",
    "ComplexityThresholds",
    "ProcedureComplexity",
    "BusinessRuleExtractor",
    "BusinessRuleReport",
    "BusinessRule",
    "RuleBranch",
    "RuleAction",
    "ConditionNameDefinition",
    "RedundancyAnalyzer",
    "RedundancyReport",
    "CloneGroup",
    "CloneMember",
    "TechnicalDebtAnalyzer",
    "TechnicalDebtReport",
    "DebtWeights",
    "ComponentBreakdown",
    "OffenderProcedure",
]
