# backend/__init__.py
"""
Backend code generation for Nala compiler.
"""

from backend.codegen import gen_program

__all__ = [
    "gen_program_hir",
    "gen_program_nir",
]
