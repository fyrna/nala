# diagnostics/reporter.py
"""
Error reporter with colored output and source context.
"""

import sys
from dataclasses import dataclass
from typing import Optional

from diagnostics.errors import Diagnostic, DiagnosticKind, CompileError


@dataclass
class DiagnosticReporter:
    color: bool = True
    max_context_lines: int = 3

    def _color(self, text: str, code: str) -> str:
        if not self.color:
            return text
        return f"\033[{code}m{text}\033[0m"

    def report(self, diagnostic: Diagnostic) -> None:
        output = sys.stderr

        if diagnostic.kind == DiagnosticKind.ERROR:
            header = self._color("error", "31;1")
        elif diagnostic.kind == DiagnosticKind.WARNING:
            header = self._color("warning", "33;1")
        elif diagnostic.kind == DiagnosticKind.NOTE:
            header = self._color("note", "34;1")
        else:
            header = diagnostic.kind.name.lower()

        if diagnostic.code:
            code_str = self._color(f"[{diagnostic.code}]", "30;1") if self.color else f"[{diagnostic.code}]"
            print(f"{code_str} {header}: {diagnostic.message}", file=output)
        else:
            print(f"{header}: {diagnostic.message}", file=output)

        if diagnostic.file and diagnostic.line is not None:
            print(f"  --> {diagnostic.file}:{diagnostic.line}:{diagnostic.col or 1}", file=output)

        for note in diagnostic.notes:
            print(f"  {self._color('note:', '34;1')} {note}", file=output)


def report_error(message: str, file: Optional[str] = None,
                 line: Optional[int] = None, col: Optional[int] = None) -> None:
    reporter = DiagnosticReporter()
    diagnostic = Diagnostic(
        kind=DiagnosticKind.ERROR,
        message=message,
        file=file,
        line=line,
        col=col,
    )
    reporter.report(diagnostic)
