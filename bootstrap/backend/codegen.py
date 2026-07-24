"""
bootstrap/backend/codegen.py

Translasi HIR (High-level IR) menjadi teks kode C.

FILOSOFI:
    - Codegen HANYA menerjemahkan HIR ke C.
    - TIDAK ada inferensi, TIDAK ada keputusan semantik.
    - Semua informasi sudah lengkap di HIR -- termasuk tipe, union_name,
      struct_name, bind_type, dll.
    - HIR adalah "kontrak final" -- codegen hanya mengeksekusi translasi.

ARSITEKTUR:
    HIR (dari ir/type_checker.py)
        ↓
    gen_program() -- entry point
        ↓
    gen_enum() / gen_struct() / gen_union() / gen_fn()
        ↓
    gen_expr() / gen_stmt()
        ↓
    C Code
"""

from __future__ import annotations

from ir.hir import (
    # Type
    TypeRef,
    # Expressions
    HIdent, HStringLiteral, HIntLiteral, HFloatLiteral, HByteLiteral,
    HFieldAccess, HBinaryExpr, HUnaryExpr, HCallExpr,
    HMethodCall, HIntrinsicCall, HStructLiteral, HUnionLiteral,
    HEnumVariantAccess, HIfExpr,
    HArrayLiteral, HArrayIndex,
    HExpr,
    # Statements
    HParam, HSelfParam, HReturnStmt, HIfStmt, HWhileStmt, HForInStmt,
    HAssignStmt, HExprStmt, HLetStmt, HMatchStmt, HMatchArm,
    HElifClause, HContinueStmt, HBreakStmt,
    HStmt,
    # Declarations
    HEnumDecl, HStructDecl, HStructField, HUnionDecl, HUnionVariant,
    HFnDecl,
    HDecl,
)

try:
    from backend.runtime import RUNTIME_C
except ImportError:
    RUNTIME_C = "/* runtime.py not found */"


# Type mapping: Nala type -> C type
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
    "print_u8": "__intrinsic_print_u8",
    "print_u16": "__intrinsic_print_u16",
    "print_u32": "__intrinsic_print_u32",
    "print_u64": "__intrinsic_print_u64",
    "print_i8": "__intrinsic_print_i8",
    "print_i16": "__intrinsic_print_i16",
    "print_i32": "__intrinsic_print_i32",
    "print_i64": "__intrinsic_print_i64",
    "print_f32": "__intrinsic_print_f32",
    "print_f64": "__intrinsic_print_f64",
    "print_bool": "__intrinsic_print_bool",
    "print_string": "__intrinsic_print_string",
    "print_usize": "__intrinsic_print_usize",
    "byte_len": "__intrinsic_byte_len",
    "as_bytes": "__intrinsic_as_bytes",
    "slice_bytes": "__intrinsic_slice_bytes",
    "byte_at": "__intrinsic_byte_at",
    "assert": "__intrinsic_assert",
}

_BINOP_MAP = {
    ">=": ">=",
    "<=": "<=",
    "==": "==",
    "and": "&&",
    "or": "||",
    "+": "+",
    ">": ">",
    "<": "<",
}

def _parse_array_type(type_name: str) -> tuple[int, str] | None:
    """Parse [N]T -> (N, T) atau None."""
    if not type_name.startswith("[") or "]" not in type_name:
        return None
    bracket_end = type_name.index("]")
    size_str = type_name[1:bracket_end]
    inner_type = type_name[bracket_end + 1:]
    try:
        return (int(size_str), inner_type)
    except ValueError:
        return None


def _array_struct_name(type_name: str) -> str:
    """Generate nama struct wrapper untuk [N]T: Array_3_i32."""
    parsed = _parse_array_type(type_name)
    assert parsed is not None
    size, inner = parsed
    return f"Array_{size}_{inner}"


def _c_type(type_ref: TypeRef) -> str:
    """Konversi TypeRef ke tipe C."""
    # Check array type
    parsed = _parse_array_type(type_ref.name)
    if parsed is not None:
        return _array_struct_name(type_ref.name)
    return _PRIMITIVE_TYPE_MAP.get(type_ref.name, type_ref.name)


# Temp variable generator


_temp_counter = 0

# Track array types yang perlu di-generate struct wrapper-nya
_array_types_needed: set[str] = set()


def _register_array_type(type_name: str) -> None:
    """Register [N]T type untuk generate struct wrapper."""
    if _parse_array_type(type_name) is not None:
        _array_types_needed.add(type_name)


def _gen_array_struct_defs() -> list[str]:
    """Generate C struct wrapper untuk semua [N]T yang terpakai."""
    lines = []
    for type_name in sorted(_array_types_needed):
        parsed = _parse_array_type(type_name)
        if parsed is None:
            continue
        size, inner = parsed
        struct_name = _array_struct_name(type_name)
        inner_c_type = _PRIMITIVE_TYPE_MAP.get(inner, inner)
        lines.append(f"typedef struct {{ {inner_c_type} data[{size}]; }} {struct_name};")
    return lines


def _fresh_temp(prefix: str = "__tmp") -> str:
    global _temp_counter
    _temp_counter += 1
    return f"{prefix}_{_temp_counter}"


# ---------------------------------------------------------------------------
# Array type collection -- recursively scan HIR before code generation
# ---------------------------------------------------------------------------

def _collect_array_types_from_expr(expr: HExpr) -> None:
    """Recursively collect array types from HIR expression."""
    if isinstance(expr, HArrayLiteral):
        _register_array_type(expr.type_ref.name)
        for e in expr.elements:
            _collect_array_types_from_expr(e)
    elif isinstance(expr, HBinaryExpr):
        _collect_array_types_from_expr(expr.left)
        _collect_array_types_from_expr(expr.right)
    elif isinstance(expr, HUnaryExpr):
        _collect_array_types_from_expr(expr.operand)
    elif isinstance(expr, HFieldAccess):
        _collect_array_types_from_expr(expr.obj)
    elif isinstance(expr, HCallExpr):
        for a in expr.args:
            _collect_array_types_from_expr(a)
    elif isinstance(expr, HMethodCall):
        _collect_array_types_from_expr(expr.obj)
        for a in expr.args:
            _collect_array_types_from_expr(a)
    elif isinstance(expr, HIntrinsicCall):
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
    """Recursively collect array types from HIR statement."""
    if isinstance(stmt, HReturnStmt):
        _collect_array_types_from_expr(stmt.expr)
    elif isinstance(stmt, HIfStmt):
        _collect_array_types_from_expr(stmt.cond)
        for s in stmt.body:
            _collect_array_types_from_stmt(s)
        for e in stmt.elifs:
            _collect_array_types_from_expr(e.cond)
            for s in e.body:
                _collect_array_types_from_stmt(s)
        for s in stmt.else_body:
            _collect_array_types_from_stmt(s)
    elif isinstance(stmt, HWhileStmt):
        _collect_array_types_from_expr(stmt.cond)
        for s in stmt.body:
            _collect_array_types_from_stmt(s)
    elif isinstance(stmt, HForInStmt):
        _register_array_type(stmt.iterable.type_ref.name)
        _collect_array_types_from_expr(stmt.iterable)
        for s in stmt.body:
            _collect_array_types_from_stmt(s)
    elif isinstance(stmt, HAssignStmt):
        _collect_array_types_from_expr(stmt.target)
        _collect_array_types_from_expr(stmt.value)
    elif isinstance(stmt, HLetStmt):
        _register_array_type(stmt.type_ref.name)
        _collect_array_types_from_expr(stmt.value)
    elif isinstance(stmt, HExprStmt):
        _collect_array_types_from_expr(stmt.expr)
    elif isinstance(stmt, HMatchStmt):
        _collect_array_types_from_expr(stmt.expr)
        for arm in stmt.arms:
            for s in arm.body:
                _collect_array_types_from_stmt(s)


def _collect_all_array_types(decls: list[HDecl]) -> None:
    """Collect all array types from entire HIR program."""
    for d in decls:
        if isinstance(d, HFnDecl):
            _register_array_type(d.return_type.name)
            for p in d.params:
                _register_array_type(p.type_ref.name)
            for s in d.body:
                _collect_array_types_from_stmt(s)
        elif isinstance(d, HStructDecl):
            for f in d.fields:
                _register_array_type(f.type_ref.name)
            for m in d.methods:
                _register_array_type(m.return_type.name)
                for p in m.params:
                    _register_array_type(p.type_ref.name)
                for s in m.body:
                    _collect_array_types_from_stmt(s)


# Expression code generation


def gen_expr(expr: HExpr) -> str:
    """Generate C code untuk HIR expression."""
    if isinstance(expr, HIdent):
        return expr.name

    elif isinstance(expr, HStringLiteral):
        return f'(NalaSlice){{(uint8_t*)"{expr.value}", {len(expr.value)}}}'

    elif isinstance(expr, HIntLiteral):
        return expr.value

    elif isinstance(expr, HFloatLiteral):
        return expr.value

    elif isinstance(expr, HByteLiteral):
        return f"'{expr.value}'"

    elif isinstance(expr, HFieldAccess):
        obj = gen_expr(expr.obj)
        if isinstance(expr.obj, HIdent) and expr.obj.name == "self":
            return f"{obj}->{expr.field}"
        return f"{obj}.{expr.field}"

    elif isinstance(expr, HBinaryExpr):
        c_op = _BINOP_MAP.get(expr.op)
        if c_op is None:
            raise ValueError(f"Operator belum didukung: {expr.op!r}")
        left = gen_expr(expr.left)
        right = gen_expr(expr.right)
        return f"({left} {c_op} {right})"

    elif isinstance(expr, HUnaryExpr):
        if expr.op != "!":
            raise ValueError(f"Operator unary belum didukung: {expr.op!r}")
        return f"(!{gen_expr(expr.operand)})"

    elif isinstance(expr, HMethodCall):
        obj_str = gen_expr(expr.obj)
        callee = f"{expr.struct_name}_{expr.method}"
        # self parameter: kalau objeknya self, sudah pointer; kalau tidak, perlu &
        if isinstance(expr.obj, HIdent) and expr.obj.name == "self":
            self_arg = obj_str
        else:
            self_arg = f"&({obj_str})"
        args_str = ", ".join(gen_expr(a) for a in expr.args)
        if args_str:
            return f"{callee}({self_arg}, {args_str})"
        return f"{callee}({self_arg})"

    elif isinstance(expr, HIntrinsicCall):
        # Special handling for len!
        if expr.name == "len" and expr.args:
            arg = expr.args[0]

            # Array: compile-time constant
            parsed = _parse_array_type(arg.type_ref.name)
            if parsed is not None:
                size, _ = parsed
                return str(size)

            # Slice: runtime .len
            if arg.type_ref.name in ("[]u8", "str"):
                arg_str = gen_expr(arg)
                return f"({arg_str}.len)"
        c_name = _INTRINSIC_MAP.get(expr.name)
        if c_name is None:
            raise ValueError(f"Intrinsic belum didukung: {expr.name}")
        args = ", ".join(gen_expr(a) for a in expr.args)
        return f"{c_name}({args})"

    elif isinstance(expr, HCallExpr):
        args_str = ", ".join(gen_expr(a) for a in expr.args)
        return f"{expr.callee}({args_str})"

    elif isinstance(expr, HStructLiteral):
        c_type = _c_type(expr.type_ref)
        parts = ", ".join(f".{name} = {gen_expr(value)}" for name, value in expr.fields)
        return f"({c_type}){{{parts}}}"

    elif isinstance(expr, HUnionLiteral):
        union_name = expr.union_name
        variant_name = expr.variant_name
        tag_name = f"{union_name.upper()}_{variant_name.upper()}"

        if expr.payload is not None:
            payload_expr = gen_expr(expr.payload)
            return (
                f"({union_name}){{"
                f".tag = {tag_name}, "
                f".payload.{variant_name} = {payload_expr}"
                f"}}"
            )
        else:
            return f"({union_name}){{.tag = {tag_name}}}"

    elif isinstance(expr, HEnumVariantAccess):
        return f"{expr.enum_name.upper()}_{expr.variant_name.upper()}"

    elif isinstance(expr, HArrayLiteral):
        struct_name = _array_struct_name(expr.type_ref.name)
        parts = ", ".join(gen_expr(e) for e in expr.elements)
        return f"({struct_name}){{{{{parts}}}}}"

    elif isinstance(expr, HArrayIndex):
        obj_str = gen_expr(expr.obj)
        index_str = gen_expr(expr.index)
        return f"({obj_str}.data[{index_str}])"

    elif isinstance(expr, HIfExpr):
        raise ValueError(
            "HIfExpr tidak bisa langsung di-gen_expr -- "
            "harus di-handle oleh gen_stmt (HLetStmt) atau caller"
        )

    else:
        raise TypeError(f"Tipe ekspresi HIR tidak dikenal: {type(expr).__name__}")


# If-expression as statements (untuk let dengan if-expr value)


def _gen_if_expr_as_statements(expr: HIfExpr, temp_name: str, indent: int) -> list[str]:
    """Generate if/else statements untuk assign hasil if-expr ke temp variable."""
    pad = "    " * indent
    lines: list[str] = []
    cond = gen_expr(expr.cond)
    then_expr = gen_expr(expr.then_branch)
    else_expr = gen_expr(expr.else_branch)
    lines.append(f"{pad}if ({cond}) {{")
    lines.append(f"{pad}    {temp_name} = {then_expr};")
    lines.append(f"{pad}}} else {{")
    lines.append(f"{pad}    {temp_name} = {else_expr};")
    lines.append(f"{pad}}}")
    return lines


# Statement code generation


def gen_stmt(stmt: HStmt, indent: int = 1) -> list[str]:
    """Generate C code untuk HIR statement."""
    pad = "    " * indent
    lines: list[str] = []

    if isinstance(stmt, HReturnStmt):
        lines.append(f"{pad}return {gen_expr(stmt.expr)};")

    elif isinstance(stmt, HIfStmt):
        lines.append(f"{pad}if ({gen_expr(stmt.cond)}) {{")
        for s in stmt.body:
            lines.extend(gen_stmt(s, indent + 1))
        lines.append(f"{pad}}}")
        for elif_clause in stmt.elifs:
            lines.append(f"{pad}else if ({gen_expr(elif_clause.cond)}) {{")
            for s in elif_clause.body:
                lines.extend(gen_stmt(s, indent + 1))
            lines.append(f"{pad}}}")
        if stmt.else_body:
            lines.append(f"{pad}else {{")
            for s in stmt.else_body:
                lines.extend(gen_stmt(s, indent + 1))
            lines.append(f"{pad}}}")

    elif isinstance(stmt, HWhileStmt):
        lines.append(f"{pad}while ({gen_expr(stmt.cond)}) {{")
        for s in stmt.body:
            lines.extend(gen_stmt(s, indent + 1))
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
        lines.extend(_gen_match_stmt(stmt, indent))

    elif isinstance(stmt, HForInStmt):
        lines.extend(_gen_forin_stmt(stmt, indent))

    else:
        raise TypeError(f"Tipe statement HIR tidak dikenal: {type(stmt).__name__}")

    return lines


def _gen_forin_stmt(stmt: HForInStmt, indent: int) -> list[str]:
    """Generate C code untuk for-in loop."""
    pad = "    " * indent
    lines: list[str] = []

    iter_expr = gen_expr(stmt.iterable)
    iter_type = stmt.iterable.type_ref.name
    parsed = _parse_array_type(iter_type)

    if parsed is None:
        raise ValueError(f"for-in pada non-array type: {iter_type}")

    size, _ = parsed
    elem_c_type = _c_type(stmt.var_type)
    index_var = _fresh_temp("__i")

    lines.append(f"{pad}for (size_t {index_var} = 0; {index_var} < {size}; {index_var}++) {{")
    lines.append(f"{pad}    {elem_c_type} {stmt.var_name} = {iter_expr}.data[{index_var}];")
    for s in stmt.body:
        lines.extend(gen_stmt(s, indent + 2))
    lines.append(f"{pad}}}")

    return lines


def _gen_match_stmt(stmt: HMatchStmt, indent: int) -> list[str]:
    """Generate C code untuk match statement dengan flag-based dispatch."""
    pad = "    " * indent
    lines: list[str] = []

    match_result = _fresh_temp("__match")
    match_expr = gen_expr(stmt.expr)
    union_name = stmt.union_name
    union_c_type = _c_type(TypeRef(union_name))

    lines.append(f"{pad}{union_c_type} {match_result} = {match_expr};")

    matched_flag = _fresh_temp("__matched")
    lines.append(f"{pad}bool {matched_flag} = false;")

    for arm in stmt.arms:
        variant_tag = f"{union_name.upper()}_{arm.variant.upper()}"
        lines.append(f"{pad}if (!{matched_flag} && {match_result}.tag == {variant_tag}) {{")

        if arm.bind is not None:
            if arm.bind_type is None:
                raise ValueError(
                    f"MatchArm '{union_name}.{arm.variant}' punya binding "
                    f"tapi bind_type None -- bug di type checker."
                )
            payload_field = f"{match_result}.payload.{arm.variant}"
            bind_c_type = _c_type(arm.bind_type)
            lines.append(f"{pad}    {bind_c_type} {arm.bind} = {payload_field};")

        has_guard = arm.guard is not None
        if has_guard:
            lines.append(f"{pad}    if ({gen_expr(arm.guard)}) {{")

        body_indent = indent + 1 + (1 if has_guard else 0)
        body_pad = "    " * body_indent
        lines.append(f"{body_pad}{matched_flag} = true;")
        for s in arm.body:
            lines.extend(gen_stmt(s, body_indent))

        if has_guard:
            lines.append(f"{pad}    }}")
        lines.append(f"{pad}}}")

    return lines


# Function code generation


def gen_fn(decl: HFnDecl) -> str:
    """Generate C code untuk HIR function declaration."""
    c_return_type = _c_type(decl.return_type)
    all_params = []

    if decl.self_param is not None and decl.struct_name is not None:
        const_qual = "const " if not decl.self_param.is_mut else ""
        all_params.append(f"{const_qual}{decl.struct_name}* self")

    for p in decl.params:
        c_type = _c_type(p.type_ref)
        all_params.append(f"{c_type} {p.name}")

    params_str = ", ".join(all_params)
    prefix = "static " if decl.is_internal else ""

    if decl.struct_name is not None:
        func_name = f"{decl.struct_name}_{decl.name}"
    else:
        func_name = decl.name

    lines = [f"{prefix}{c_return_type} {func_name}({params_str}) {{"]
    for stmt in decl.body:
        lines.extend(gen_stmt(stmt, indent=1))
    lines.append("}")
    return "\n".join(lines)


def _gen_fn_proto(decl: HFnDecl) -> str:
    """Generate C forward declaration untuk HIR function."""
    c_return_type = _c_type(decl.return_type)
    all_params = []

    if decl.self_param is not None and decl.struct_name is not None:
        const_qual = "const " if not decl.self_param.is_mut else ""
        all_params.append(f"{const_qual}{decl.struct_name}* self")

    for p in decl.params:
        c_type = _c_type(p.type_ref)
        all_params.append(f"{c_type} {p.name}")

    params_str = ", ".join(all_params)
    prefix = "static " if decl.is_internal else ""

    if decl.struct_name is not None:
        func_name = f"{decl.struct_name}_{decl.name}"
    else:
        func_name = decl.name
        if func_name == "main":
            func_name = "__nala_main"

    return f"{prefix}{c_return_type} {func_name}({params_str});"


# Type definition code generation


def gen_enum(decl: HEnumDecl) -> str:
    """Generate C enum dari HIR."""
    lines = ["typedef enum {"]
    for variant in decl.variants:
        c_name = f"{decl.name.upper()}_{variant.upper()}"
        lines.append(f"    {c_name},")
    lines.append(f"}} {decl.name};")
    return "\n".join(lines)


def gen_union(decl: HUnionDecl) -> str:
    """Generate C union struct dari HIR."""
    union_name = decl.name
    tag_enum_name = f"{union_name}Tag"

    # Tag enum
    lines = [f"typedef enum {{"]
    for v in decl.variants:
        c_name = f"{union_name.upper()}_{v.name.upper()}"
        lines.append(f"    {c_name},")
    lines.append(f"}} {tag_enum_name};")
    lines.append("")

    # Union struct
    lines.append(f"typedef struct {{")
    lines.append(f"    {tag_enum_name} tag;")

    has_payload = any(v.payload_type is not None for v in decl.variants)

    if has_payload:
        lines.append(f"    union {{")
        for v in decl.variants:
            if v.payload_type is not None:
                c_payload_type = _c_type(v.payload_type)
                lines.append(f"        {c_payload_type} {v.name};")
        lines.append(f"    }} payload;")

    lines.append(f"}} {union_name};")
    return "\n".join(lines)


def gen_struct(decl: HStructDecl) -> str:
    """Generate C struct dari HIR."""
    lines = [f"typedef struct {{"]
    for f in decl.fields:
        c_type = _c_type(f.type_ref)
        lines.append(f"    {c_type} {f.name};")
    lines.append(f"}} {decl.name};")
    return "\n".join(lines)


# Program code generation (entry point)


def gen_program(decls: list[HDecl]) -> str:
    """
    Entry point: generate C code lengkap dari HIR.

    Urutan output:
        1. Header (includes)
        2. Runtime C (embedded)
        3. User type definitions (enum, struct, union)
        4. Forward declarations
        5. Function implementations
        6. Main wrapper (kalau ada fn main)
    """
    # Collect forward declarations
    method_decls = []
    for d in decls:
        if isinstance(d, HStructDecl):
            for method in d.methods:
                method_decls.append(_gen_fn_proto(method))
        elif isinstance(d, HFnDecl):
            method_decls.append(_gen_fn_proto(d))

    has_main = False
    for d in decls:
        if isinstance(d, HFnDecl) and d.name == "main" and d.struct_name is None:
            has_main = True
            break

    # Header
    header = [
        "/* Auto-generated oleh bootstrap/backend/codegen.py -- JANGAN diedit manual */",
        "#include <stdint.h>",
        "#include <stddef.h>",
        "#include <stdlib.h>",
        "#include <string.h>",
        "#include <stdbool.h>",
    ]

    # Runtime
    _runtime_content = RUNTIME_C.strip()
    runtime_section = [""] + _runtime_content.split("\n")

    # Collect array types from entire HIR program
    _collect_all_array_types(decls)

    # Type definitions
    type_defs = []
    # Array struct wrappers first
    type_defs.extend(_gen_array_struct_defs())
    for d in decls:
        if isinstance(d, HEnumDecl):
            type_defs.append(gen_enum(d))
        elif isinstance(d, HStructDecl):
            type_defs.append(gen_struct(d))
        elif isinstance(d, HUnionDecl):
            type_defs.append(gen_union(d))

    # Forward declarations
    forward_decls = ["", "/* Forward declarations */"]
    forward_decls.extend(method_decls)

    # Function implementations
    method_impls = []
    for d in decls:
        if isinstance(d, HStructDecl):
            for method in d.methods:
                method_impls.append(gen_fn(method))
        elif isinstance(d, HFnDecl):
            if d.name == "main" and d.struct_name is None:
                import copy
                renamed = copy.copy(d)
                renamed.name = "__nala_main"
                method_impls.append(gen_fn(renamed))
            else:
                method_impls.append(gen_fn(d))

    # Main wrapper
    main_wrapper = []
    if has_main:
        main_wrapper.extend([
            "",
            "/* Nala main wrapper */",
            "int main(void) {",
            "    __nala_main();",
            "    return 0;",
            "}",
        ])

    all_parts = header + runtime_section + type_defs + forward_decls + method_impls + main_wrapper
    return "\n".join(all_parts) + "\n"
