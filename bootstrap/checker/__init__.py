# checker/__init__.py
"""
Type checker module for Nala compiler.
"""

from checker.symbol_table import SymbolTable, TypeCheckError
from checker.type_compat import (
    parse_type_kind, types_compatible, types_compatible_str,
    is_integer_type_name, is_float_type_name,
    TypeKind, PrimitiveKind, ArrayKind, NamedKind, UnknownKind,
)
from checker.inference import infer_expr_type, infer_field_type, intrinsic_return_type
# from checker.borrow import BorrowChecker
# from checker.sema import Sema

__all__ = [
    "SymbolTable", "TypeCheckError",
    "parse_type_kind", "types_compatible", "types_compatible_str",
    "is_integer_type_name", "is_float_type_name",
    "TypeKind", "PrimitiveKind", "ArrayKind", "NamedKind", "UnknownKind",
    "infer_expr_type", "infer_field_type", "intrinsic_return_type",
    # "BorrowChecker", "Sema",
]
