"""
Analysis utilities for COBOL AST.

This module provides tools for analyzing COBOL AST structures including
data flow analysis, call graph analysis, value tracking, dead code
detection, and I/O logging.
"""


# Lazy import to avoid circular dependency with cobolparser.plugins
def __getattr__(name: str) -> object:
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
    if name in ("CoverageAnalyzer", "CoverageMap"):
        from .coverage_analyzer import CoverageAnalyzer, CoverageMap

        _map = {
            "CoverageAnalyzer": CoverageAnalyzer,
            "CoverageMap": CoverageMap,
        }
        return _map[name]
    if name in ("TestPlanGenerator", "TestPlan"):
        from .test_plan import TestPlan, TestPlanGenerator

        _map = {
            "TestPlanGenerator": TestPlanGenerator,
            "TestPlan": TestPlan,
        }
        return _map[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "CoverageAnalyzer",
    "CoverageMap",
    "DeadCodeAnalyzer",
    "DeadCodeReport",
    "DeadCodeItem",
    "DynamicCallAnalyzer",
    "IOLogger",
    "IOLogReport",
    "IOOperation",
    "TestPlan",
    "TestPlanGenerator",
]
