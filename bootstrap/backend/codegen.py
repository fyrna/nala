"""
bootstrap/backend/codegen.py

Translasi AST Nala (final, sudah diresolve type checker) menjadi teks kode C.

Filosofi: Codegen HANYA menerjemahkan. Tidak melakukan inferensi,
keputusan semantik, atau resolusi apapun. Semua informasi sudah lengkap
di AST — termasuk tipe untuk match binding dan union name.
"""

from __future__ import annotations

from nala_ast import (
    EnumDecl, StructDecl, StructField, FnDecl, UnionDecl, UnionVariant,
    Expr, Stmt, Ident, StringLiteral, IntLiteral, ByteLiteral,
    BinaryExpr, UnaryExpr, CallExpr, FieldAccess, MethodCall, IntrinsicCall,
    IfExpr, MatchArm, MatchStmt, UnionLiteral, EnumVariantAccess,
    Param, SelfParam, ReturnStmt, IfStmt, WhileStmt, AssignStmt, ExprStmt, LetStmt, ElifClause,
    ContinueStmt, BreakStmt, StructLiteral,
)

try:
    from backend.runtime import RUNTIME_C
except ImportError:
    RUNTIME_C = "/* runtime.py not found */"


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

_temp_counter = 0

def _fresh_temp(prefix: str = "__tmp") -> str:
    global _temp_counter
    _temp_counter += 1
    return f"{prefix}_{_temp_counter}"


def _c_type(type_name: str) -> str:
    """Konversi tipe Nala ke tipe C."""
    return _PRIMITIVE_TYPE_MAP.get(type_name, type_name)


def gen_expr(expr: Expr) -> str:
    if isinstance(expr, Ident):
        return expr.name
    elif isinstance(expr, StringLiteral):
        return f'(NalaSlice){{(uint8_t*)"{expr.value}", {len(expr.value)}}}'
    elif isinstance(expr, IntLiteral):
        return expr.value
    elif isinstance(expr, ByteLiteral):
        return f"'" + expr.value + "'"
    elif isinstance(expr, FieldAccess):
        obj = gen_expr(expr.obj)
        if isinstance(expr.obj, Ident) and expr.obj.name == "self":
            return f"{obj}->{expr.field}"
        return f"{obj}.{expr.field}"
    elif isinstance(expr, BinaryExpr):
        c_op = _BINOP_MAP.get(expr.op)
        if c_op is None:
            raise ValueError(f"Operator belum didukung: {expr.op!r}")
        left = gen_expr(expr.left)
        right = gen_expr(expr.right)
        return f"({left} {c_op} {right})"
    elif isinstance(expr, UnaryExpr):
        if expr.op != "!":
            raise ValueError(f"Operator unary belum didukung: {expr.op!r}")
        return f"(!{gen_expr(expr.operand)})"
    elif isinstance(expr, MethodCall):
        obj_str = gen_expr(expr.obj)
        if expr.struct_name:
            callee = f"{expr.struct_name}_{expr.method}"
        else:
            if isinstance(expr.obj, Ident) and expr.obj.name == "self":
                raise ValueError(f"MethodCall untuk self.{expr.method} harus punya struct_name")
            callee = f"{obj_str}_{expr.method}"
        # Method parameter `self` selalu pointer (const StructName* self).
        # Kalau objeknya adalah `self`, sudah pointer — tidak perlu &.
        # Kalau objeknya instance variable (p, tok, dst), perlu & untuk ambil alamat.
        if isinstance(expr.obj, Ident) and expr.obj.name == "self":
            self_arg = obj_str
        else:
            self_arg = f"&({obj_str})"
        args_str = ", ".join(gen_expr(a) for a in expr.args)
        if args_str:
            return f"{callee}({self_arg}, {args_str})"
        return f"{callee}({self_arg})"
    elif isinstance(expr, IntrinsicCall):
        c_name = _INTRINSIC_MAP.get(expr.name)
        if c_name is None:
            raise ValueError(f"Intrinsic belum didukung: {expr.name}")
        args = ", ".join(gen_expr(a) for a in expr.args)
        return f"{c_name}({args})"
    elif isinstance(expr, CallExpr):
        args_str = ", ".join(gen_expr(a) for a in expr.args)
        return f"{expr.callee}({args_str})"
    elif isinstance(expr, StructLiteral):
        c_type = _PRIMITIVE_TYPE_MAP.get(expr.type_name, expr.type_name)
        parts = ", ".join(f".{name} = {gen_expr(value)}" for name, value in expr.fields)
        return f"({c_type}){{{parts}}}"
    elif isinstance(expr, UnionLiteral):
        # UnionName.VariantName(payload) -> struct initialization
        # Contoh: Option.Some(42) -> (Option){.tag = OPTION_SOME, .payload.Some = 42}
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
    elif isinstance(expr, EnumVariantAccess):
        # EnumName.VariantName -> konstanta C tunggal, konsisten dengan
        # penamaan yang dipakai gen_enum(): ENUMNAME_VARIANTNAME.
        # Contoh: TokenKind.EOF -> TOKENKIND_EOF
        return f"{expr.enum_name.upper()}_{expr.variant_name.upper()}"
    elif isinstance(expr, IfExpr):
        raise ValueError(
            "IfExpr tidak bisa langsung di-gen_expr -- "
            "harus di-handle oleh gen_stmt (LetStmt) atau caller"
        )
    else:
        raise TypeError(f"Tipe ekspresi tidak dikenal: {type(expr)}")


def _gen_if_expr_as_statements(expr: IfExpr, temp_name: str, indent: int) -> list[str]:
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


def gen_stmt(stmt: Stmt, indent: int = 1) -> list[str]:
    pad = "    " * indent
    lines: list[str] = []

    if isinstance(stmt, ReturnStmt):
        lines.append(f"{pad}return {gen_expr(stmt.expr)};")
    elif isinstance(stmt, IfStmt):
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
    elif isinstance(stmt, WhileStmt):
        lines.append(f"{pad}while ({gen_expr(stmt.cond)}) {{")
        for s in stmt.body:
            lines.extend(gen_stmt(s, indent + 1))
        lines.append(f"{pad}}}")
    elif isinstance(stmt, AssignStmt):
        lines.append(f"{pad}{gen_expr(stmt.target)} {stmt.op} {gen_expr(stmt.value)};")
    elif isinstance(stmt, LetStmt):
        if stmt.type_name is None:
            c_type = "__auto_type"
        else:
            c_type = _PRIMITIVE_TYPE_MAP.get(stmt.type_name, stmt.type_name)
        if isinstance(stmt.value, IfExpr):
            if stmt.type_name is None:
                raise ValueError(
                    f"let '{stmt.name}' berisi if-expression tapi tidak punya "
                    f"anotasi tipe -- __auto_type butuh initializer tunggal, "
                    f"tulis anotasi tipe eksplisit untuk kasus ini"
                )
            lines.append(f"{pad}{c_type} {stmt.name};")
            lines.extend(_gen_if_expr_as_statements(stmt.value, stmt.name, indent))
        else:
            lines.append(f"{pad}{c_type} {stmt.name} = {gen_expr(stmt.value)};")
    elif isinstance(stmt, ExprStmt):
        lines.append(f"{pad}{gen_expr(stmt.expr)};")
    elif isinstance(stmt, ContinueStmt):
        lines.append(f"{pad}continue;")
    elif isinstance(stmt, BreakStmt):
        lines.append(f"{pad}break;")
    elif isinstance(stmt, MatchStmt):
        # Butuh stmt.union_name & arm.bind_type dari type checker (lihat check_program()).
        #
        # PENTING: arm TIDAK dirangkai sebagai if/else-if per-tag. Kalau ada guard,
        # tag yang sama bisa muncul di beberapa arm (mis. `Result.Ok(x) if x < 15`,
        # `Result.Ok(x) if x == 15`, ...) — begitu guard di satu arm gagal, C harus
        # tetap lanjut cek arm berikutnya walau tag-nya sama, bukan berhenti karena
        # "sudah masuk cabang else-if yang tag-nya cocok". else-if biasa tidak bisa
        # merepresentasikan ini, jadi dipakai flag __matched_N + rantai if independen:
        #
        #   bool __matched_N = false;
        #   if (!__matched_N && __match_N.tag == VARIANT) {
        #       T bind = __match_N.payload.Variant;   // opsional
        #       if (guard) {                          // opsional
        #           __matched_N = true;
        #           ...body...
        #       }
        #   }
        #   if (!__matched_N && __match_N.tag == VARIANT2) { ... }
        #   ...
        match_result = _fresh_temp("__match")
        match_expr = gen_expr(stmt.expr)

        union_name = stmt.union_name
        if union_name is None:
            raise ValueError(
                "MatchStmt.union_name belum di-attach oleh type checker — "
                "pastikan check_program() dipanggil sebelum codegen."
            )
        union_c_type = _c_type(union_name)
        lines.append(f"{pad}{union_c_type} {match_result} = {match_expr};")

        matched_flag = _fresh_temp("__matched")
        lines.append(f"{pad}bool {matched_flag} = false;")

        for arm in stmt.arms:
            variant_tag = f"{union_name.upper()}_{arm.variant.upper()}"
            lines.append(
                f"{pad}if (!{matched_flag} && {match_result}.tag == {variant_tag}) {{"
            )

            if arm.bind is not None:
                if arm.bind_type is None:
                    raise ValueError(
                        f"MatchArm '{union_name}.{arm.variant}' memiliki binding "
                        f"'{arm.bind}' tapi bind_type belum di-attach — "
                        f"pastikan check_program() sudah dijalankan."
                    )
                payload_field = f"{match_result}.payload.{arm.variant}"
                bind_c_type = _c_type(arm.bind_type)
                lines.append(f"{pad}    {bind_c_type} {arm.bind} = {payload_field};")

            has_guard = arm.guard is not None
            if has_guard:
                lines.append(f"{pad}    if ({gen_expr(arm.guard)}) {{")

            # Set flag SEBELUM body — konsisten dengan semantik "arm ini matched",
            # terlepas apakah body-nya sendiri nanti break/return di tengah jalan.
            body_indent = indent + 1 + (1 if has_guard else 0)
            body_pad = "    " * body_indent
            lines.append(f"{body_pad}{matched_flag} = true;")
            for s in arm.body:
                lines.extend(gen_stmt(s, body_indent))

            if has_guard:
                lines.append(f"{pad}    }}")  # tutup guard
            lines.append(f"{pad}}}")  # tutup arm
    else:
        raise TypeError(f"Tipe statement tidak dikenal: {type(stmt)}")

    return lines


def gen_fn(decl: FnDecl) -> str:
    c_return_type = _PRIMITIVE_TYPE_MAP.get(decl.return_type, decl.return_type)
    all_params = []

    if decl.self_param is not None and decl.struct_name is not None:
        const_qual = "const " if not decl.self_param.is_mut else ""
        all_params.append(f"{const_qual}{decl.struct_name}* self")

    for p in decl.params:
        c_type = _PRIMITIVE_TYPE_MAP.get(p.type_name, p.type_name)
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


def _gen_fn_proto(decl: FnDecl) -> str:
    c_return_type = _PRIMITIVE_TYPE_MAP.get(decl.return_type, decl.return_type)
    all_params = []

    if decl.self_param is not None and decl.struct_name is not None:
        const_qual = "const " if not decl.self_param.is_mut else ""
        all_params.append(f"{const_qual}{decl.struct_name}* self")

    for p in decl.params:
        c_type = _PRIMITIVE_TYPE_MAP.get(p.type_name, p.type_name)
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


def gen_enum(decl: EnumDecl) -> str:
    lines = ["typedef enum {"]
    for variant in decl.variants:
        c_name = f"{decl.name.upper()}_{variant.upper()}"
        lines.append(f"    {c_name},")
    lines.append(f"}} {decl.name};")
    return "\n".join(lines)


def gen_union(decl: UnionDecl) -> str:
    """Generate C code untuk union Nala.

    Contoh:
        const Option = union { Some(u8), None, }
    Menjadi:
        typedef enum { OPTION_SOME, OPTION_NONE } OptionTag;
        typedef struct {
            OptionTag tag;
            union {
                uint8_t Some;
            } payload;
        } Option;

    Variant tanpa payload (None) tidak generate field di union payload.
    """
    union_name = decl.name
    tag_enum_name = f"{union_name}Tag"

    # 1. Tag enum
    lines = [f"typedef enum {{"]
    for v in decl.variants:
        c_name = f"{union_name.upper()}_{v.name.upper()}"
        lines.append(f"    {c_name},")
    lines.append(f"}} {tag_enum_name};")
    lines.append("")

    # 2. Union struct
    lines.append(f"typedef struct {{")
    lines.append(f"    {tag_enum_name} tag;")

    # Cek apakah ada variant dengan payload (non-void)
    has_payload = any(len(v.payload_types) > 0 for v in decl.variants)

    if has_payload:
        lines.append(f"    union {{")
        for v in decl.variants:
            if len(v.payload_types) > 0:
                # Stage0: hanya support 1 payload type per variant
                payload_type = v.payload_types[0]
                c_payload_type = _PRIMITIVE_TYPE_MAP.get(payload_type, payload_type)
                lines.append(f"        {c_payload_type} {v.name};")
        lines.append(f"    }} payload;")

    lines.append(f"}} {union_name};")

    return "\n".join(lines)


def gen_struct(decl: StructDecl) -> str:
    lines = [f"typedef struct {{"]
    for f in decl.fields:
        c_type = _PRIMITIVE_TYPE_MAP.get(f.type_name, f.type_name)
        lines.append(f"    {c_type} {f.name};")
    lines.append(f"}} {decl.name};")
    return "\n".join(lines)


def gen_program(decls: list) -> str:
    """
    Urutan output:
    1. Header (includes)
    2. Runtime C (embedded)
    3. User type definitions (enum, struct, union)
    4. Forward declarations (fungsi/method)
    5. Function implementations
    6. Main wrapper (kalau ada fn main)
    """

    method_decls = []
    for d in decls:
        if isinstance(d, StructDecl):
            for method in d.methods:
                method_decls.append(_gen_fn_proto(method))
        elif isinstance(d, FnDecl):
            method_decls.append(_gen_fn_proto(d))

    has_main = False
    for d in decls:
        if isinstance(d, FnDecl) and d.name == "main" and d.struct_name is None:
            has_main = True
            break

    header = [
        "/* Auto-generated oleh bootstrap/codegen.py -- JANGAN diedit manual */",
        "#include <stdint.h>",
        "#include <stddef.h>",
        "#include <stdlib.h>",
        "#include <string.h>",
        "#include <stdbool.h>",
    ]

    _runtime_content = RUNTIME_C.strip()
    runtime_section = [""] + _runtime_content.split("\n")

    # Phase 2: User type definitions
    type_defs = []
    for d in decls:
        if isinstance(d, EnumDecl):
            type_defs.append(gen_enum(d))
        elif isinstance(d, StructDecl):
            type_defs.append(gen_struct(d))
        elif isinstance(d, UnionDecl):
            type_defs.append(gen_union(d))

    # Phase 3: Forward declarations
    forward_decls = []
    forward_decls.append("")
    forward_decls.append("/* Forward declarations */")
    forward_decls.extend(method_decls)

    # Phase 4: Function implementations
    method_impls = []
    for d in decls:
        if isinstance(d, StructDecl):
            for method in d.methods:
                method_impls.append(gen_fn(method))
        elif isinstance(d, FnDecl):
            if d.name == "main" and d.struct_name is None:
                import copy
                renamed = copy.copy(d)
                renamed.name = "__nala_main"
                method_impls.append(gen_fn(renamed))
            else:
                method_impls.append(gen_fn(d))

    # Phase 5: Main wrapper
    main_wrapper = []
    if has_main:
        main_wrapper.append("")
        main_wrapper.append("/* Nala main wrapper */")
        main_wrapper.append("int main(void) {")
        main_wrapper.append("    __nala_main();")
        main_wrapper.append("    return 0;")
        main_wrapper.append("}")

    all_parts = header + runtime_section + type_defs + forward_decls + method_impls + main_wrapper
    return "\n".join(all_parts) + "\n"
