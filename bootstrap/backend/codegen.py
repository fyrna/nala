# backend/codegen.py
"""
HIR → C translator. No semantic decisions, only translation.
"""
from __future__ import annotations

from ir.hir import (
    # --- Types ---
    TypeRef,
    
    # --- Literals ---
    HStringLiteral,
    HIntLiteral,
    HFloatLiteral,
    HByteLiteral,
    HBoolLiteral,
    
    # --- Expressions ---
    HIdent,
    HFieldAccess,
    HBinaryExpr,
    HUnaryExpr,
    HCallExpr,
    HMethodCall,
    HIntrinsicCall,
    HStructLiteral,
    HUnionLiteral,
    HEnumVariantAccess,
    HIfExpr,
    HArrayLiteral,
    HArrayIndex,
    HExpr,
    
    # --- Statements ---
    HParam,
    HSelfParam,
    HReturnStmt,
    HIfStmt,
    HWhileStmt,
    HForInStmt,
    HAssignStmt,
    HExprStmt,
    HLetStmt,
    HMatchStmt,
    HMatchArm,
    HElifClause,
    HContinueStmt,
    HBreakStmt,
    HDeferStmt,
    HStmt,
    
    # --- Declarations ---
    HEnumDecl,
    HStructDecl,
    HStructField,
    HUnionDecl,
    HUnionVariant,
    HFnDecl,
    HDecl,
)

try:
    from backend.runtime import RUNTIME_C
except ImportError:
    RUNTIME_C = "/* runtime not found */"

# Type mapping
_PRIMITIVE_TYPE_MAP = {
    "usize": "size_t",
    "u8": "uint8_t",
    "u16": "uint16_t",
    "u32": "uint32_t",
    "u64": "uint64_t",
    "i8": "int8_t",
    "i16": "int16_t",
    "i32": "int32_t",
    "i64": "int64_t",
    "f32": "float",
    "f64": "double",
    "bool": "bool",
    "[]u8": "NalaSlice",
    "str": "NalaSlice",
    "void": "void",
}

_INTRINSIC_MAP = {
    "print_u8":     "__intrinsic_print_u8",
    "print_u16":    "__intrinsic_print_u16",
    "print_u32":    "__intrinsic_print_u32",
    "print_u64":    "__intrinsic_print_u64",
    "print_i8":     "__intrinsic_print_i8",
    "print_i16":    "__intrinsic_print_i16",
    "print_i32":    "__intrinsic_print_i32",
    "print_i64":    "__intrinsic_print_i64",
    "print_f32":    "__intrinsic_print_f32",
    "print_f64":    "__intrinsic_print_f64",
    "print_bool":   "__intrinsic_print_bool",
    "print_string": "__intrinsic_print_string",
    "print_usize":  "__intrinsic_print_usize",
    "byte_len":     "__intrinsic_byte_len",
    "as_bytes":     "__intrinsic_as_bytes",
    "slice_bytes":  "__intrinsic_slice_bytes",
    "byte_at":      "__intrinsic_byte_at",
    "assert":       "__intrinsic_assert",
    "assert_eq":    "__intrinsic_assert_eq",
}

_BINOP_MAP = {
    ">=": ">=",
    "<=": "<=",
    "==": "==",
    "!=": "!=",
    "and": "&&",
    "or": "||",
    "+": "+",
    "-": "-",
    "*": "*",
    "/": "/",
    "%": "%",
    ">": ">",
    "<": "<",
}

def _parse_array_type(type_name: str):
    if type_name.startswith("[") and "]" in type_name:
        bracket_end = type_name.index("]")
        size_str = type_name[1:bracket_end]
        inner = type_name[bracket_end+1:]
        try:
            return (int(size_str), inner)
        except ValueError:
            return None
    return None

def _array_struct_name(type_name: str) -> str:
    parsed = _parse_array_type(type_name)
    assert parsed is not None
    size, inner = parsed
    return f"Array_{size}_{inner}"

def _c_type(type_ref: TypeRef) -> str:
    parsed = _parse_array_type(type_ref.name)
    if parsed is not None:
        return _array_struct_name(type_ref.name)
    return _PRIMITIVE_TYPE_MAP.get(type_ref.name, type_ref.name)

_temp_counter = 0
_array_types_needed = set()

def _register_array_type(type_name: str) -> None:
    if _parse_array_type(type_name) is not None:
        _array_types_needed.add(type_name)

def _gen_array_struct_defs() -> list[str]:
    lines = []
    for type_name in sorted(_array_types_needed):
        parsed = _parse_array_type(type_name)
        if parsed is None: continue
        size, inner = parsed
        struct_name = _array_struct_name(type_name)
        inner_c_type = _PRIMITIVE_TYPE_MAP.get(inner, inner)
        lines.append(f"typedef struct {{ {inner_c_type} data[{size}]; }} {struct_name};")
    return lines

def _fresh_temp(prefix: str = "__tmp"):
    global _temp_counter
    _temp_counter += 1
    return f"{prefix}_{_temp_counter}"

# ---- Array type collection ----
def _collect_array_types_from_expr(expr: HExpr) -> None:
    if isinstance(expr, HArrayLiteral):
        _register_array_type(expr.type_ref.name)
        for e in expr.elements:
            _collect_array_types_from_expr(e)
    elif isinstance(expr, HBinaryExpr):
        _collect_array_types_from_expr(expr.left); _collect_array_types_from_expr(expr.right)
    elif isinstance(expr, HUnaryExpr):
        _collect_array_types_from_expr(expr.operand)
    elif isinstance(expr, HFieldAccess):
        _collect_array_types_from_expr(expr.obj)
    elif isinstance(expr, (HCallExpr, HMethodCall, HIntrinsicCall)):
        for a in expr.args:
            _collect_array_types_from_expr(a)
    elif isinstance(expr, HStructLiteral):
        for _, v in expr.fields:
            _collect_array_types_from_expr(v)
    elif isinstance(expr, HUnionLiteral):
        if expr.payload:
            _collect_array_types_from_expr(expr.payload)
    elif isinstance(expr, HIfExpr):
        _collect_array_types_from_expr(expr.cond)
        _collect_array_types_from_expr(expr.then_branch)
        _collect_array_types_from_expr(expr.else_branch)
    elif isinstance(expr, HArrayIndex):
        _collect_array_types_from_expr(expr.obj)
        _collect_array_types_from_expr(expr.index)

def _collect_array_types_from_stmt(stmt: HStmt) -> None:
    if isinstance(stmt, HReturnStmt):
        _collect_array_types_from_expr(stmt.expr)
    elif isinstance(stmt, HIfStmt):
        _collect_array_types_from_expr(stmt.cond)
        for s in stmt.body: _collect_array_types_from_stmt(s)
        for e in stmt.elifs:
            _collect_array_types_from_expr(e.cond)
            for s in e.body: _collect_array_types_from_stmt(s)
        for s in stmt.else_body: _collect_array_types_from_stmt(s)
    elif isinstance(stmt, HWhileStmt):
        _collect_array_types_from_expr(stmt.cond)
        for s in stmt.body: _collect_array_types_from_stmt(s)
    elif isinstance(stmt, HForInStmt):
        _register_array_type(stmt.iterable.type_ref.name)
        _collect_array_types_from_expr(stmt.iterable)
        for s in stmt.body: _collect_array_types_from_stmt(s)
    elif isinstance(stmt, HAssignStmt):
        _collect_array_types_from_expr(stmt.target); _collect_array_types_from_expr(stmt.value)
    elif isinstance(stmt, HLetStmt):
        _register_array_type(stmt.type_ref.name)
        _collect_array_types_from_expr(stmt.value)
    elif isinstance(stmt, HExprStmt):
        _collect_array_types_from_expr(stmt.expr)
    elif isinstance(stmt, HMatchStmt):
        _collect_array_types_from_expr(stmt.expr)
        for arm in stmt.arms:
            for s in arm.body: _collect_array_types_from_stmt(s)

def _collect_all_array_types(decls: list[HDecl]) -> None:
    for d in decls:
        if isinstance(d, HFnDecl):
            _register_array_type(d.return_type.name)
            for p in d.params: _register_array_type(p.type_ref.name)
            for s in d.body: _collect_array_types_from_stmt(s)
        elif isinstance(d, HStructDecl):
            for f in d.fields: _register_array_type(f.type_ref.name)
            for m in d.methods:
                _register_array_type(m.return_type.name)
                for p in m.params: _register_array_type(p.type_ref.name)
                for s in m.body: _collect_array_types_from_stmt(s)

# ---- Expression codegen ----
def gen_expr(expr: HExpr) -> str:
    if isinstance(expr, HIdent):
        return expr.name
    elif isinstance(expr, HStringLiteral):
        return f'(NalaSlice){{(uint8_t*)"{expr.value}", {len(expr.value)}}}'
    elif isinstance(expr, HIntLiteral):
        return expr.value
    elif isinstance(expr, HFloatLiteral):
        # C literal desimal default-nya "double" -- kalau HIR type_ref
        # sudah bilang f32 (context-aware dari LetStmt/BinaryExpr/dst),
        # literal ini WAJIB dikasih suffix 'f' supaya representasi biner
        # C-nya juga float, bukan double.
        if expr.type_ref.name == "f32":
            return f"{expr.value}f"
        return expr.value
    elif isinstance(expr, HByteLiteral):
        return f"'{expr.value}'"
    elif isinstance(expr, HBoolLiteral):
        return "true" if expr.value else "false"
    elif isinstance(expr, HFieldAccess):
        obj = gen_expr(expr.obj)
        if isinstance(expr.obj, HIdent) and expr.obj.name == "self":
            return f"{obj}->{expr.field}"
        return f"{obj}.{expr.field}"
    elif isinstance(expr, HBinaryExpr):
        c_op = _BINOP_MAP.get(expr.op)
        if c_op is None:
            raise ValueError(f"Operator {expr.op!r} not supported")
        return f"({gen_expr(expr.left)} {c_op} {gen_expr(expr.right)})"
    elif isinstance(expr, HUnaryExpr):
        if expr.op != "!":
            raise ValueError(f"Unary {expr.op!r} not supported")
        return f"(!{gen_expr(expr.operand)})"
    elif isinstance(expr, HMethodCall):
        obj_str = gen_expr(expr.obj)
        callee = f"{expr.struct_name}_{expr.method}"
        self_arg = obj_str if (isinstance(expr.obj, HIdent) and expr.obj.name == "self") else f"&({obj_str})"
        args_str = ", ".join(gen_expr(a) for a in expr.args)
        return f"{callee}({self_arg}" + (f", {args_str}" if args_str else "") + ")"
    elif isinstance(expr, HIntrinsicCall):
        if expr.name == "len" and expr.args:
            arg = expr.args[0]
            parsed = _parse_array_type(arg.type_ref.name)
            if parsed is not None:
                return str(parsed[0])
            if arg.type_ref.name in ("[]u8", "str"):
                return f"({gen_expr(arg)}.len)"
        c_name = _INTRINSIC_MAP.get(expr.name)
        if c_name is None:
            raise ValueError(f"Intrinsic {expr.name!r} not supported")
        return f"{c_name}({', '.join(gen_expr(a) for a in expr.args)})"
    elif isinstance(expr, HCallExpr):
        return f"{expr.callee}({', '.join(gen_expr(a) for a in expr.args)})"
    elif isinstance(expr, HStructLiteral):
        c_type = _c_type(expr.type_ref)
        parts = ", ".join(f".{name} = {gen_expr(value)}" for name, value in expr.fields)
        return f"({c_type}){{{parts}}}"
    elif isinstance(expr, HUnionLiteral):
        tag = f"{expr.union_name.upper()}_{expr.variant_name.upper()}"
        if expr.payload is not None:
            return f"({expr.union_name}){{.tag = {tag}, .payload.{expr.variant_name} = {gen_expr(expr.payload)}}}"
        return f"({expr.union_name}){{.tag = {tag}}}"
    elif isinstance(expr, HEnumVariantAccess):
        return f"{expr.enum_name.upper()}_{expr.variant_name.upper()}"
    elif isinstance(expr, HArrayLiteral):
        struct_name = _array_struct_name(expr.type_ref.name)
        parts = ", ".join(gen_expr(e) for e in expr.elements)
        return f"({struct_name}){{{{{parts}}}}}"
    elif isinstance(expr, HArrayIndex):
        return f"({gen_expr(expr.obj)}.data[{gen_expr(expr.index)}])"
    elif isinstance(expr, HIfExpr):
        raise ValueError("HIfExpr cannot be used directly in gen_expr; use gen_stmt on a HLetStmt")
    else:
        raise TypeError(f"Unknown HIR expr: {type(expr).__name__}")

# ---- If-expr as statements ----
def _gen_if_expr_as_statements(expr: HIfExpr, temp_name: str, indent: int) -> list[str]:
    pad = "    " * indent
    lines = [f"{pad}if ({gen_expr(expr.cond)}) {{",
             f"{pad}    {temp_name} = {gen_expr(expr.then_branch)};",
             f"{pad}}} else {{",
             f"{pad}    {temp_name} = {gen_expr(expr.else_branch)};",
             f"{pad}}}"]
    return lines

# ---- Statement codegen ----
def gen_stmt(stmt: HStmt, indent: int = 1, pending_defers: list[HExpr] | None = None) -> list[str]:
    """
    Generate satu HIR statement -> baris C.

    pending_defers: daftar expr defer yang aktif di scope function terluar
    (lihat _gen_fn_body_with_defer). Diteruskan ke SEMUA pemanggilan
    rekursif gen_stmt (di dalam if/while/for/match) supaya HReturnStmt di
    level manapun tetap men-trigger flush defer sebelum return -- sesuai
    semantik "defer jalan saat keluar scope, apapun jalurnya".
    """
    if pending_defers is None:
        pending_defers = []
    pad = "    " * indent
    lines = []
    if isinstance(stmt, HReturnStmt):
        lines.extend(_gen_defer_flush(pending_defers, indent))
        lines.append(f"{pad}return {gen_expr(stmt.expr)};")
    elif isinstance(stmt, HIfStmt):
        lines.append(f"{pad}if ({gen_expr(stmt.cond)}) {{")
        for s in stmt.body: lines.extend(gen_stmt(s, indent+1, pending_defers))
        lines.append(f"{pad}}}")
        for e in stmt.elifs:
            lines.append(f"{pad}else if ({gen_expr(e.cond)}) {{")
            for s in e.body: lines.extend(gen_stmt(s, indent+1, pending_defers))
            lines.append(f"{pad}}}")
        if stmt.else_body:
            lines.append(f"{pad}else {{")
            for s in stmt.else_body: lines.extend(gen_stmt(s, indent+1, pending_defers))
            lines.append(f"{pad}}}")
    elif isinstance(stmt, HWhileStmt):
        lines.append(f"{pad}while ({gen_expr(stmt.cond)}) {{")
        for s in stmt.body: lines.extend(gen_stmt(s, indent+1, pending_defers))
        lines.append(f"{pad}}}")
    elif isinstance(stmt, HAssignStmt):
        lines.append(f"{pad}{gen_expr(stmt.target)} {stmt.op} {gen_expr(stmt.value)};")
    elif isinstance(stmt, HLetStmt):
        c_type = _c_type(stmt.type_ref)
        if isinstance(stmt.value, HIfExpr):
            lines.append(f"{pad}{c_type} {stmt.name};")
            lines.extend(_gen_if_expr_as_statements(stmt.value, stmt.name, indent))
        else:
            lines.append(f"{pad}{c_type} {stmt.name} = {gen_expr(stmt.value)};")
    elif isinstance(stmt, HExprStmt):
        lines.append(f"{pad}{gen_expr(stmt.expr)};")
    elif isinstance(stmt, HContinueStmt):
        lines.append(f"{pad}continue;")
    elif isinstance(stmt, HBreakStmt):
        lines.append(f"{pad}break;")
    elif isinstance(stmt, HMatchStmt):
        lines.extend(_gen_match_stmt(stmt, indent, pending_defers))
    elif isinstance(stmt, HForInStmt):
        lines.extend(_gen_forin_stmt(stmt, indent, pending_defers))
    elif isinstance(stmt, HDeferStmt):
        raise ValueError(
            "defer di dalam nested block (if/for/match) belum didukung -- "
            "saat ini defer hanya valid langsung di top-level function body."
        )
    else:
        raise TypeError(f"Unknown HIR stmt: {type(stmt).__name__}")
    return lines

def _gen_forin_stmt(stmt: HForInStmt, indent: int, pending_defers: list[HExpr] | None = None) -> list[str]:
    if pending_defers is None:
        pending_defers = []
    pad = "    " * indent
    iter_expr = gen_expr(stmt.iterable)
    parsed = _parse_array_type(stmt.iterable.type_ref.name)
    if parsed is None:
        raise ValueError(f"for-in on non-array: {stmt.iterable.type_ref.name}")
    size, _ = parsed
    elem_c_type = _c_type(stmt.var_type)
    idx = _fresh_temp("__i")
    lines = [f"{pad}for (size_t {idx} = 0; {idx} < {size}; {idx}++) {{",
             f"{pad}    {elem_c_type} {stmt.var_name} = {iter_expr}.data[{idx}];"]
    for s in stmt.body: lines.extend(gen_stmt(s, indent+2, pending_defers))
    lines.append(f"{pad}}}")
    return lines

def _gen_match_stmt(stmt: HMatchStmt, indent: int, pending_defers: list[HExpr] | None = None) -> list[str]:
    if pending_defers is None:
        pending_defers = []
    pad = "    " * indent
    match_expr = gen_expr(stmt.expr)
    union_name = stmt.union_name
    union_c_type = _c_type(TypeRef(union_name))
    match_var = _fresh_temp("__match")
    matched = _fresh_temp("__matched")
    lines = [f"{pad}{union_c_type} {match_var} = {match_expr};",
             f"{pad}bool {matched} = false;"]
    for arm in stmt.arms:
        tag = f"{union_name.upper()}_{arm.variant.upper()}"
        lines.append(f"{pad}if (!{matched} && {match_var}.tag == {tag}) {{")
        if arm.bind is not None:
            if arm.bind_type is None:
                raise ValueError(f"Match arm {union_name}.{arm.variant} has bind but no bind_type")
            bind_c = _c_type(arm.bind_type)
            lines.append(f"{pad}    {bind_c} {arm.bind} = {match_var}.payload.{arm.variant};")
        has_guard = arm.guard is not None
        if has_guard:
            lines.append(f"{pad}    if ({gen_expr(arm.guard)}) {{")
        body_indent = indent + 1 + (1 if has_guard else 0)
        body_pad = "    " * body_indent
        lines.append(f"{body_pad}{matched} = true;")
        for s in arm.body:
            lines.extend(gen_stmt(s, body_indent, pending_defers))
        if has_guard:
            lines.append(f"{pad}    }}")
        lines.append(f"{pad}}}")
    return lines

# ---- Function codegen ----
def gen_fn(decl: HFnDecl) -> str:
    c_return = _c_type(decl.return_type)
    params = []
    if decl.self_param is not None and decl.struct_name is not None:
        const = "const " if not decl.self_param.is_mut else ""
        params.append(f"{const}{decl.struct_name}* self")
    for p in decl.params:
        params.append(f"{_c_type(p.type_ref)} {p.name}")
    params_str = ", ".join(params)
    prefix = "static " if decl.is_internal else ""
    func_name = f"{decl.struct_name}_{decl.name}" if decl.struct_name is not None else decl.name
    lines = [f"{prefix}{c_return} {func_name}({params_str}) {{"]
    lines.extend(_gen_fn_body_with_defer(decl.body, indent=1))
    lines.append("}")
    return "\n".join(lines)


def _gen_fn_body_with_defer(body: list[HStmt], indent: int) -> list[str]:
    """
    Generate body function dengan dukungan `defer` di level top-level.

    PENTING -- semantik `defer` adalah "jalankan saat KELUAR SCOPE, apapun
    jalurnya" (language.md). Ini berarti walau `defer` sendiri hanya boleh
    DIDEKLARASIKAN di top-level function body (belum nested if/for/match --
    itu fitur terpisah yang belum dibangun), setiap `ret` yang jadi TITIK
    KELUAR function -- di level manapun ia berada, termasuk di dalam
    nested if/for/match -- WAJIB tetap men-trigger flush defer top-level
    sebelum function itu benar-benar return.

    Strategi: HDeferStmt dikumpulkan dulu (dibuang dari body, dicatat
    expr-nya). Sisa body di-generate lewat gen_stmt() seperti biasa, TAPI
    pending_defers dioper sebagai context yang mengalir ke SEMUA level
    nested -- gen_stmt tahu untuk inject flush defer setiap kali ia
    menghasilkan HReturnStmt, di level manapun itu terjadi.
    """
    lines: list[str] = []
    pending_defers: list[HExpr] = []
    body_without_defer: list[HStmt] = []

    for stmt in body:
        if isinstance(stmt, HDeferStmt):
            pending_defers.append(stmt.expr)
        else:
            body_without_defer.append(stmt)

    for stmt in body_without_defer:
        lines.extend(gen_stmt(stmt, indent=indent, pending_defers=pending_defers))

    # Fall-through di akhir function -- HANYA kalau statement terakhir
    # BUKAN return (kalau sudah return, defer sudah di-flush di titik
    # return itu sendiri, di level manapun ia berada).
    last_is_return = len(body_without_defer) > 0 and isinstance(body_without_defer[-1], HReturnStmt)
    if not last_is_return:
        lines.extend(_gen_defer_flush(pending_defers, indent))
    return lines


def _gen_defer_flush(pending_defers: list[HExpr], indent: int) -> list[str]:
    """Generate pemanggilan defer secara LIFO (kebalik urutan pendaftaran)."""
    pad = "    " * indent
    return [f"{pad}{gen_expr(e)};" for e in reversed(pending_defers)]

def _gen_fn_proto(decl: HFnDecl) -> str:
    c_return = _c_type(decl.return_type)
    params = []
    if decl.self_param is not None and decl.struct_name is not None:
        const = "const " if not decl.self_param.is_mut else ""
        params.append(f"{const}{decl.struct_name}* self")
    for p in decl.params:
        params.append(f"{_c_type(p.type_ref)} {p.name}")
    params_str = ", ".join(params)
    prefix = "static " if decl.is_internal else ""
    func_name = f"{decl.struct_name}_{decl.name}" if decl.struct_name is not None else decl.name
    if func_name == "main":
        func_name = "__nala_main"
    return f"{prefix}{c_return} {func_name}({params_str});"

# ---- Type definition codegen ----
def gen_enum(decl: HEnumDecl) -> str:
    lines = ["typedef enum {"]
    for v in decl.variants:
        lines.append(f"    {decl.name.upper()}_{v.upper()},")
    lines.append(f"}} {decl.name};")
    return "\n".join(lines)

def gen_union(decl: HUnionDecl) -> str:
    union_name = decl.name
    tag_enum = f"{union_name}Tag"
    lines = [f"typedef enum {{"]
    for v in decl.variants:
        lines.append(f"    {union_name.upper()}_{v.name.upper()},")
    lines.append(f"}} {tag_enum};")
    lines.append("")
    lines.append(f"typedef struct {{")
    lines.append(f"    {tag_enum} tag;")

    has_payload = any(v.payload_type is not None for v in decl.variants)

    if has_payload:
        lines.append(f"    union {{")
        for v in decl.variants:
            if v.payload_type is not None:
                lines.append(f"        {_c_type(v.payload_type)} {v.name};")

        lines.append(f"    }} payload;")

    lines.append(f"}} {union_name};")
    return "\n".join(lines)

def gen_struct(decl: HStructDecl) -> str:
    lines = [f"typedef struct {{"]
    for f in decl.fields:
        lines.append(f"    {_c_type(f.type_ref)} {f.name};")

    lines.append(f"}} {decl.name};")
    return "\n".join(lines)

# ---- Program codegen (entry point) ----
def gen_program(decls: list[HDecl]) -> str:
    # Collect forward decls
    fwd_protos = []

    for d in decls:
        if isinstance(d, HStructDecl):
            for m in d.methods:
                fwd_protos.append(_gen_fn_proto(m))

        elif isinstance(d, HFnDecl):
            fwd_protos.append(_gen_fn_proto(d))
    has_main = any(isinstance(d, HFnDecl) and d.name == "main" and d.struct_name is None for d in decls)
    # Header
    header = [
        "/* Auto-generated by bootstrap/backend/codegen.py -- DO NOT EDIT */",
        "#include <stdint.h>", "#include <stddef.h>", "#include <stdlib.h>",
        "#include <string.h>", "#include <stdbool.h>",
    ]

    runtime_lines = ["", *RUNTIME_C.strip().split("\n")]
    _collect_all_array_types(decls)
    type_defs = _gen_array_struct_defs()

    for d in decls:
        if isinstance(d, HEnumDecl): type_defs.append(gen_enum(d))
        elif isinstance(d, HStructDecl): type_defs.append(gen_struct(d))
        elif isinstance(d, HUnionDecl): type_defs.append(gen_union(d))
    fwd_lines = ["", "/* Forward declarations */"] + fwd_protos
    impls = []

    for d in decls:
        if isinstance(d, HStructDecl):
            for m in d.methods:
                impls.append(gen_fn(m))

        elif isinstance(d, HFnDecl):
            if d.name == "main" and d.struct_name is None:
                import copy
                renamed = copy.copy(d)
                renamed.name = "__nala_main"
                impls.append(gen_fn(renamed))
            else:
                impls.append(gen_fn(d))

    main_wrapper = []
    if has_main:
        main_wrapper = ["", "/* Nala main wrapper */", "int main(void) {", "    __nala_main();", "    return 0;", "}"]
    all_parts = header + runtime_lines + type_defs + fwd_lines + impls + main_wrapper
    return "\n".join(all_parts) + "\n"
