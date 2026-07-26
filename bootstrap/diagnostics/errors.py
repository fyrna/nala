# diagnostics/errors.py
"""
Error and diagnostic definitions.
"""

from enum import Enum, auto
from dataclasses import dataclass, field
from typing import Optional


class DiagnosticKind(Enum):
    ERROR = auto()
    WARNING = auto()
    NOTE = auto()
    HELP = auto()


@dataclass
class Diagnostic:
    kind: DiagnosticKind
    message: str
    file: Optional[str] = None
    line: Optional[int] = None
    col: Optional[int] = None
    span_start: Optional[int] = None
    span_end: Optional[int] = None
    notes: list[str] = field(default_factory=list)
    code: Optional[str] = None


class CompileError(Exception):
    """Base exception for compile errors."""
    def __init__(self, message: str, diagnostic: Optional[Diagnostic] = None):
        super().__init__(message)
        self.diagnostic = diagnostic


class ParseError(CompileError):
    """Syntax error during parsing."""
    def __init__(self, message: str, line: int = 0, col: int = 0, file: str = ""):
        diag = Diagnostic(
            kind=DiagnosticKind.ERROR,
            message=message,
            file=file if file else None,
            line=line if line > 0 else None,
            col=col if col > 0 else None,
            code="E0001",
        )
        super().__init__(message, diag)
        self.line = line
        self.col = col
        self.file = file


class SyntaxError(CompileError):
    pass


class TypeError(CompileError):
    pass


class BorrowError(CompileError):
    pass
