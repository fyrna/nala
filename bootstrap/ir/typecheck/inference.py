"""
bootstrap/ir/typecheck/inference.py

Type inference -- "menebak" tipe suatu ekspresi AST/HIR.

PENTING: modul ini cuma soal MENEBAK tipe, bukan MEMVERIFIKASI kecocokan
dua tipe. Untuk verifikasi kecocokan (mis. "apakah tipe expr cocok dengan
anotasi let"), lihat type_compat.py -- types_compatible().

Fungsi di sini sengaja berdiri sendiri (bukan method class) supaya tidak
diam-diam bergantung ke banyak state HIRBuilder -- setiap state yang
dibutuhkan (symbol table, local variable types, current struct context)
diterima eksplisit sebagai parameter, sesuai prinsip Nala "explicit >
magic" yang coba diikuti compiler ini juga secara arsitektur.
"""

from __future__ import annotations

from nala_ast import (
    Expr, Ident, StringLiteral, IntLiteral, FloatLiteral, BoolLiteral, ByteLiteral,
    StructLiteral, UnionLiteral, EnumVariantAccess, ArrayLiteral, CallExpr,
)
from ir.hir import TypeRef, HExpr, HIdent, HFieldAccess
from ir.typecheck.symbol_table import SymbolTable
from ir.typecheck.type_compat import is_integer_type_name, is_float_type_name


def infer_expr_type(
    expr: Expr,
    table: SymbolTable,
    local_types: dict[str, str],
    current_struct_name: str | None,
    expected_type: str | None = None,
) -> TypeRef:
    """
    Infer tipe dari ekspresi AST.

    Args:
        expr: ekspresi AST yang mau ditebak tipenya
        table: SymbolTable hasil build dari semua top-level decl
        local_types: nama variabel lokal -> nama tipe (state HIRBuilder)
        current_struct_name: nama struct yang sedang diproses (untuk `self`)
        expected_type: tipe yang diharapkan dari context (mis. anotasi
            `let x: i64`, atau tipe parameter fungsi). Dipakai KHUSUS untuk
            resolve literal numerik (IntLiteral/FloatLiteral) supaya tidak
            selalu hardcode i32/f32 -- lihat catatan di IntLiteral/FloatLiteral
            branch di bawah. Untuk ekspresi lain, parameter ini diabaikan.
    """
    if isinstance(expr, StringLiteral):
        return TypeRef("str")
    elif isinstance(expr, IntLiteral):
        # Kalau context minta tipe integer spesifik, literal ini "jadi"
        # tipe itu -- bukan selalu i32. Lintas kelas (mis. context minta
        # float atau string) tetap fallback ke i32, karena integer literal
        # apa adanya memang integer.
        if expected_type is not None and is_integer_type_name(expected_type):
            return TypeRef(expected_type)
        return TypeRef("i32")
    elif isinstance(expr, FloatLiteral):
        if expected_type is not None and is_float_type_name(expected_type):
            return TypeRef(expected_type)
        return TypeRef("f32")
    elif isinstance(expr, ByteLiteral):
        return TypeRef("u8")
    elif isinstance(expr, BoolLiteral):
        return TypeRef("bool")
    elif isinstance(expr, Ident):
        if expr.name in local_types:
            return TypeRef(local_types[expr.name])
        if expr.name == "self" and current_struct_name:
            return TypeRef(current_struct_name)
    elif isinstance(expr, StructLiteral):
        return TypeRef(expr.type_name)
    elif isinstance(expr, UnionLiteral):
        return TypeRef(expr.union_name)
    elif isinstance(expr, EnumVariantAccess):
        return TypeRef(expr.enum_name)
    elif isinstance(expr, ArrayLiteral):
        # Size dan element type sudah eksplisit di literal-nya sendiri
        # ([N]T{...}) -- tidak perlu (dan tidak boleh) ditebak dari
        # elemen pertama.
        return TypeRef(f"[{expr.size}]{expr.element_type}")
    elif isinstance(expr, CallExpr):
        sig = table.fn_signatures.get(expr.callee)
        if sig is not None:
            _param_types, return_type = sig
            return TypeRef(return_type)
        return TypeRef("void")
    return TypeRef("void")  # fallback


def infer_field_type(
    obj: HExpr,
    field: str,
    table: SymbolTable,
    local_types: dict[str, str],
    current_struct_name: str | None,
) -> TypeRef:
    """Infer tipe field dari struct definition."""
    struct_name = None
    if isinstance(obj, HIdent):
        if obj.name == "self" and current_struct_name:
            struct_name = current_struct_name
        elif obj.name in local_types:
            struct_name = local_types[obj.name]
    elif isinstance(obj, HFieldAccess):
        # Chain: a.b.c -- belum support di stage0
        pass

    if struct_name and struct_name in table.struct_fields:
        field_info = table.struct_fields[struct_name].get(field)
        if field_info:
            return TypeRef(field_info[0])
    return TypeRef("void")


def intrinsic_return_type(name: str) -> TypeRef:
    """Infer return type dari intrinsic name."""
    if name in ("print_u8", "print_u16", "print_u32", "print_u64",
                "print_i8", "print_i16", "print_i32", "print_i64",
                "print_f32", "print_f64", "print_bool", "print_string",
                "assert", "assert_eq"):
        return TypeRef("void")
    elif name == "byte_len":
        return TypeRef("usize")
    elif name in ("as_bytes", "slice_bytes"):
        return TypeRef("[]u8")
    elif name == "byte_at":
        return TypeRef("u8")
    elif name == "len":
        return TypeRef("usize")
    return TypeRef("void")
