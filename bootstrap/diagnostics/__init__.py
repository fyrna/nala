# diagnostics/__init__.py
"""
Diagnostic and error reporting module.
"""

from diagnostics.errors import (
    Diagnostic, DiagnosticKind, CompileError,
    ParseError, SyntaxError, TypeError, BorrowError,
)
from diagnostics.reporter import DiagnosticReporter

__all__ = [
    "Diagnostic", "DiagnosticKind", "CompileError",
    "ParseError", "SyntaxError", "TypeError", "BorrowError",
    "DiagnosticReporter",
]
