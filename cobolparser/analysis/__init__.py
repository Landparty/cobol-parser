"""
Analysis utilities for COBOL AST.

This module provides tools for analyzing COBOL AST structures including
data flow analysis, call graph analysis, value tracking, and I/O logging.
"""


# Lazy import to avoid circular dependency with cobolparser.plugins
def __getattr__(name: str) -> object:
    if name == "DynamicCallAnalyzer":
        from .value_tracker import DynamicCallAnalyzer

        return DynamicCallAnalyzer
    if name in ("IOLogger", "IOLogReport", "IOOperation"):
        from .io_logger import IOLogger, IOLogReport, IOOperation

        _map = {
            "IOLogger": IOLogger,
            "IOLogReport": IOLogReport,
            "IOOperation": IOOperation,
        }
        return _map[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["DynamicCallAnalyzer", "IOLogger", "IOLogReport", "IOOperation"]
