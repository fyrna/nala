# backend/codegen.py
"""
NIR → C translator.

Menerjemahkan NIR (completed, immutable) ke C code.
Backend ini hanya READ NIR, tidak memodifikasi apapun.
"""

from __future__ import annotations

from ir.nir import (
    NProgram, NDecl, NFnDecl, NStructDecl, NUnionDecl, NEnumDecl, NGlobalDecl,
    NParam, NSelfParam, NField, NUnionVariant,
    NType, NExpr, NStmt,
    NStringLiteral, NIntLiteral, NFloatLiteral, NByteLiteral, NBoolLiteral,
    NVar, NFieldAccess, NBinaryOp, NUnaryOp,
    NCall, NMethodCall, NIntrinsicCall,
    NStructLiteral, NUnionLiteral, NEnumVariantAccess, NIfExpr,
    NArrayLiteral, NArrayIndex,
    NReturnStmt, NAssignStmt, NExprStmt, NLetStmt,
    NIfStmt, NElifClause, NWhileStmt, NForInStmt,
    NMatchStmt, NMatchArm, NDeferStmt, NContinueStmt, NBreakStmt,
)

try:
    from backend.runtime import RUNTIME_C
except ImportError:
    RUNTIME_C = "/* runtime not found */"


# ============================================================================
# Type Mapping
# ============================================================================

_TYPE_MAP = {
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
    "str": "NalaSlice",
    "void": "void",
}

_OP_MAP = {
    "add": "+",
    "sub": "-",
    "mul": "*",
    "div": "/",
    "mod": "%",
    "eq": "==",
    "ne": "!=",
    "lt": "<",
    "le": "<=",
    "gt": ">",
    "ge": ">=",
    "and": "&&",
    "or": "||",
    "neg": "-",
    "not": "!",
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
    "assert_eq": "__intrinsic_assert_eq",
    "len": "__intrinsic_len",
}


def is_array_type(name: str) -> bool:
    """Check if type is array (fixed-size or slice)."""
    return name.startswith("[") and "]" in name


def is_fixed_array_type(name: str) -> bool:
    """Check if type is fixed-size array [N]T."""
    if not name.startswith("[") or "]" not in name:
        return False
    bracket_end = name.index("]")
    size_str = name[1:bracket_end]
    return size_str.isdigit()


def is_slice_type(name: str) -> bool:
    """Check if type is slice []T."""
    if not name.startswith("[") or "]" not in name:
        return False
    bracket_end = name.index("]")
    size_str = name[1:bracket_end]
    return size_str == ""


def parse_array_type(name: str) -> tuple[int, str]:
    """Parse fixed-size array: [N]T -> (N, T)."""
    bracket_end = name.index("]")
    size = int(name[1:bracket_end])
    inner = name[bracket_end+1:]
    return size, inner


def parse_slice_type(name: str) -> str:
    """Parse slice: []T -> T."""
    bracket_end = name.index("]")
    return name[bracket_end+1:]


def c_type(ntype: NType) -> str:
    """Map Nala type to C type."""
    name = ntype.name
    
    if is_slice_type(name):
        return "NalaSlice"
    
    if is_fixed_array_type(name):
        size, inner = parse_array_type(name)
        return f"Array_{size}_{inner}"
    
    return _TYPE_MAP.get(name, name)


# ============================================================================
# Temporary Counter
# ============================================================================

_temp_counter = 0


def fresh_temp(prefix: str = "__tmp") -> str:
    global _temp_counter
    _temp_counter += 1
    return f"{prefix}_{_temp_counter}"


# ============================================================================
# Expression Codegen
# ============================================================================

def _expr_type_name(expr: NExpr) -> str:
    """Get Nala type name from any NExpr."""
    if isinstance(expr, (NCall, NMethodCall, NIntrinsicCall)):
        return expr.return_type.name
    return expr.type.name


def gen_expr(expr: NExpr) -> str:
    """Generate C code for NIR expression."""
    if isinstance(expr, NVar):
        return expr.name
    
    elif isinstance(expr, NStringLiteral):
        return f'(NalaSlice){{(uint8_t*)"{expr.value}", {len(expr.value)}}}'
    
    elif isinstance(expr, NIntLiteral):
        if expr.type.name == "f32":
            return f"{expr.value}f"
        return expr.value
    
    elif isinstance(expr, NFloatLiteral):
        if expr.type.name == "f32":
            return f"{expr.value}f"
        return expr.value
    
    elif isinstance(expr, NByteLiteral):
        return f"'{expr.value}'"
    
    elif isinstance(expr, NBoolLiteral):
        return "true" if expr.value else "false"
    
    elif isinstance(expr, NFieldAccess):
        obj = gen_expr(expr.obj)
        # self is always passed as pointer in C methods, use ->
        if isinstance(expr.obj, NVar) and expr.obj.name == "self":
            return f"{obj}->{expr.field}"
        return f"{obj}.{expr.field}"
    
    elif isinstance(expr, NBinaryOp):
        op = _OP_MAP.get(expr.op, expr.op)
        return f"({gen_expr(expr.left)} {op} {gen_expr(expr.right)})"
    
    elif isinstance(expr, NUnaryOp):
        op = _OP_MAP.get(expr.op, expr.op)
        return f"({op}{gen_expr(expr.operand)})"
    
    elif isinstance(expr, NCall):
        return f"{expr.name}({', '.join(gen_expr(a) for a in expr.args)})"
    
    elif isinstance(expr, NMethodCall):
        obj = gen_expr(expr.obj)
        callee = f"{expr.struct_name}_{expr.method}"
        self_arg = obj if isinstance(expr.obj, NVar) and expr.obj.name == "self" else f"&({obj})"
        args = ", ".join(gen_expr(a) for a in expr.args)
        return f"{callee}({self_arg}" + (f", {args}" if args else "") + ")"
    
    elif isinstance(expr, NIntrinsicCall):
        # Special handling for 'len' -- works on both slices and fixed arrays
        if expr.name == "len" and expr.args:
            arg = expr.args[0]
            arg_type = _expr_type_name(arg)
            if is_fixed_array_type(arg_type):
                size, _ = parse_array_type(arg_type)
                return str(size)
            elif is_slice_type(arg_type):
                return f"__intrinsic_len({gen_expr(arg)})"
            else:
                raise ValueError(f"len() on unsupported type: {arg_type}")

        c_name = _INTRINSIC_MAP.get(expr.name)
        if c_name is None:
            raise ValueError(f"Intrinsic {expr.name!r} not supported")
        return f"{c_name}({', '.join(gen_expr(a) for a in expr.args)})"
    
    elif isinstance(expr, NStructLiteral):
        ctype = c_type(expr.type)
        parts = ", ".join(f".{name} = {gen_expr(val)}" for name, val in expr.fields)
        return f"({ctype}){{{parts}}}"
    
    elif isinstance(expr, NUnionLiteral):
        tag = f"{expr.union_name.upper()}_{expr.variant_name.upper()}"
        if expr.payload:
            return f"({expr.union_name}){{.tag = {tag}, .payload.{expr.variant_name} = {gen_expr(expr.payload)}}}"
        return f"({expr.union_name}){{.tag = {tag}}}"
    
    elif isinstance(expr, NEnumVariantAccess):
        return f"{expr.enum_name.upper()}_{expr.variant_name.upper()}"
    
    elif isinstance(expr, NIfExpr):
        return f"({gen_expr(expr.cond)} ? {gen_expr(expr.then_branch)} : {gen_expr(expr.else_branch)})"
    
    elif isinstance(expr, NArrayLiteral):
        if is_slice_type(expr.type.name):
            # Slice literal: []T{...} -> NalaSlice
            elem_type = parse_slice_type(expr.type.name)
            elem_c_type = _TYPE_MAP.get(elem_type, elem_type)
            parts = ", ".join(gen_expr(e) for e in expr.elements)
            size = len(expr.elements)
            # Static array initialization then cast to slice
            return f"(NalaSlice){{({elem_c_type}[]){{{parts}}}, {size}}}"
        
        # Fixed-size array
        size, inner = parse_array_type(expr.type.name)
        struct_name = f"Array_{size}_{inner}"
        parts = ", ".join(gen_expr(e) for e in expr.elements)
        return f"({struct_name}){{{{{parts}}}}}"
    
    elif isinstance(expr, NArrayIndex):
        return f"({gen_expr(expr.array)}.data[{gen_expr(expr.index)}])"
    
    else:
        raise TypeError(f"Unknown NIR expr: {type(expr).__name__}")


def gen_if_expr_as_stmts(expr: NIfExpr, temp_name: str, indent: int) -> list[str]:
    """Generate if expression as statements (for let binding)."""
    pad = "    " * indent
    return [
        f"{pad}if ({gen_expr(expr.cond)}) {{",
        f"{pad}    {temp_name} = {gen_expr(expr.then_branch)};",
        f"{pad}}} else {{",
        f"{pad}    {temp_name} = {gen_expr(expr.else_branch)};",
        f"{pad}}}",
    ]


# ============================================================================
# Statement Codegen
# ============================================================================

def gen_stmt(stmt: NStmt, indent: int = 1) -> list[str]:
    """Generate C code for NIR statement."""
    pad = "    " * indent
    lines = []
    
    if isinstance(stmt, NReturnStmt):
        if stmt.expr:
            lines.append(f"{pad}return {gen_expr(stmt.expr)};")
        else:
            lines.append(f"{pad}return;")
    
    elif isinstance(stmt, NAssignStmt):
        lines.append(f"{pad}{gen_expr(stmt.target)} {stmt.op} {gen_expr(stmt.value)};")
    
    elif isinstance(stmt, NExprStmt):
        lines.append(f"{pad}{gen_expr(stmt.expr)};")
    
    elif isinstance(stmt, NLetStmt):
        ctype = c_type(stmt.type)
        if isinstance(stmt.value, NIfExpr):
            lines.append(f"{pad}{ctype} {stmt.name};")
            lines.extend(gen_if_expr_as_stmts(stmt.value, stmt.name, indent))
        else:
            lines.append(f"{pad}{ctype} {stmt.name} = {gen_expr(stmt.value)};")
    
    elif isinstance(stmt, NIfStmt):
        cond_expr = gen_expr(stmt.cond)
        # Avoid double parentheses if cond is already wrapped
        if cond_expr.startswith("(") and cond_expr.endswith(")"):
            cond_expr = cond_expr[1:-1]
        lines.append(f"{pad}if ({cond_expr}) {{")
        for s in stmt.body:
            lines.extend(gen_stmt(s, indent + 1))
        lines.append(f"{pad}}}")
        for e in stmt.elifs:
            elif_cond = gen_expr(e.cond)
            if elif_cond.startswith("(") and elif_cond.endswith(")"):
                elif_cond = elif_cond[1:-1]
            lines.append(f"{pad}else if ({elif_cond}) {{")
            for s in e.body:
                lines.extend(gen_stmt(s, indent + 1))
            lines.append(f"{pad}}}")
        if stmt.else_body:
            lines.append(f"{pad}else {{")
            for s in stmt.else_body:
                lines.extend(gen_stmt(s, indent + 1))
            lines.append(f"{pad}}}")
    
    elif isinstance(stmt, NWhileStmt):
        while_cond = gen_expr(stmt.cond)
        if while_cond.startswith("(") and while_cond.endswith(")"):
            while_cond = while_cond[1:-1]
        lines.append(f"{pad}while ({while_cond}) {{")
        for s in stmt.body:
            lines.extend(gen_stmt(s, indent + 1))
        lines.append(f"{pad}}}")
    
    elif isinstance(stmt, NForInStmt):
        iter_expr = gen_expr(stmt.iterable)
        elem_c_type = c_type(stmt.var_type)
        idx = fresh_temp("__i")
        
        if is_fixed_array_type(stmt.iterable.type.name):
            size, _ = parse_array_type(stmt.iterable.type.name)
            lines.append(f"{pad}for (size_t {idx} = 0; {idx} < {size}; {idx}++) {{")
            lines.append(f"{pad}    {elem_c_type} {stmt.var_name} = {iter_expr}.data[{idx}];")
        elif is_slice_type(stmt.iterable.type.name):
            lines.append(f"{pad}for (size_t {idx} = 0; {idx} < {iter_expr}.len; {idx}++) {{")
            lines.append(f"{pad}    {elem_c_type} {stmt.var_name} = {iter_expr}.data[{idx}];")
        else:
            raise ValueError(f"For-in on non-iterable: {stmt.iterable.type.name}")
        
        for s in stmt.body:
            lines.extend(gen_stmt(s, indent + 2))
        lines.append(f"{pad}}}")
    
    elif isinstance(stmt, NMatchStmt):
        lines.extend(gen_match_stmt(stmt, indent))
    
    elif isinstance(stmt, NDeferStmt):
        lines.append(f"{pad}{gen_expr(stmt.expr)};")
    
    elif isinstance(stmt, NContinueStmt):
        lines.append(f"{pad}continue;")
    
    elif isinstance(stmt, NBreakStmt):
        lines.append(f"{pad}break;")
    
    else:
        raise TypeError(f"Unknown NIR stmt: {type(stmt).__name__}")
    
    return lines


def gen_match_stmt(stmt: NMatchStmt, indent: int) -> list[str]:
    """Generate C code for match statement (if-else chain)."""
    pad = "    " * indent
    match_expr = gen_expr(stmt.expr)
    union_name = stmt.union_type.name
    union_c_type = c_type(stmt.union_type)
    match_var = fresh_temp("__match")
    matched = fresh_temp("__matched")
    
    lines = [
        f"{pad}{union_c_type} {match_var} = {match_expr};",
        f"{pad}bool {matched} = false;",
    ]
    
    for arm in stmt.arms:
        tag = f"{union_name.upper()}_{arm.variant.upper()}"
        lines.append(f"{pad}if (!{matched} && {match_var}.tag == {tag}) {{")
        
        if arm.bind:
            bind_c_type = c_type(arm.bind_type)
            lines.append(f"{pad}    {bind_c_type} {arm.bind} = {match_var}.payload.{arm.variant};")
        
        if arm.guard:
            lines.append(f"{pad}    if ({gen_expr(arm.guard)}) {{")
            lines.append(f"{pad}        {matched} = true;")
            for s in arm.body:
                lines.extend(gen_stmt(s, indent + 2))
            lines.append(f"{pad}    }}")
        else:
            lines.append(f"{pad}    {matched} = true;")
            for s in arm.body:
                lines.extend(gen_stmt(s, indent + 1))
        
        lines.append(f"{pad}}}")
    
    return lines


# ============================================================================
# Function Codegen
# ============================================================================

def gen_fn(decl: NFnDecl) -> str:
    """Generate C function from NIR function."""
    c_return = c_type(decl.return_type)
    
    params = []
    if decl.self_param and decl.struct_name:
        const = "const " if not decl.self_param.is_mut else ""
        params.append(f"{const}{decl.struct_name}* self")
    for p in decl.params:
        params.append(f"{c_type(p.type)} {p.name}")
    
    params_str = ", ".join(params)
    prefix = "static " if decl.is_internal else ""
    func_name = f"{decl.struct_name}_{decl.name}" if decl.struct_name else decl.name
    
    lines = [f"{prefix}{c_return} {func_name}({params_str}) {{"]
    for stmt in decl.body:
        lines.extend(gen_stmt(stmt, 1))
    lines.append("}")
    return "\n".join(lines)


def gen_fn_proto(decl: NFnDecl) -> str:
    """Generate C function prototype."""
    c_return = c_type(decl.return_type)
    
    params = []
    if decl.self_param and decl.struct_name:
        const = "const " if not decl.self_param.is_mut else ""
        params.append(f"{const}{decl.struct_name}* self")
    for p in decl.params:
        params.append(f"{c_type(p.type)} {p.name}")
    
    params_str = ", ".join(params)
    prefix = "static " if decl.is_internal else ""
    func_name = f"{decl.struct_name}_{decl.name}" if decl.struct_name else decl.name
    
    return f"{prefix}{c_return} {func_name}({params_str});"


# ============================================================================
# Type Definitions
# ============================================================================

def gen_enum(decl: NEnumDecl) -> str:
    lines = ["typedef enum {"]
    for v in decl.variants:
        lines.append(f"    {decl.name.upper()}_{v.upper()},")
    lines.append(f"}} {decl.name};")
    return "\n".join(lines)


def gen_union(decl: NUnionDecl) -> str:
    union_name = decl.name
    tag_enum = f"{union_name}Tag"
    lines = [f"typedef enum {{"]
    for v in decl.variants:
        lines.append(f"    {union_name.upper()}_{v.name.upper()},")
    lines.append(f"}} {tag_enum};")
    lines.append("")
    lines.append(f"typedef struct {{")
    lines.append(f"    {tag_enum} tag;")
    
    has_payload = any(v.payload_type for v in decl.variants)
    if has_payload:
        lines.append(f"    union {{")
        for v in decl.variants:
            if v.payload_type:
                lines.append(f"        {c_type(v.payload_type)} {v.name};")
        lines.append(f"    }} payload;")
    
    lines.append(f"}} {union_name};")
    return "\n".join(lines)


def gen_struct(decl: NStructDecl) -> str:
    lines = [f"typedef struct {{"]
    for f in decl.fields:
        lines.append(f"    {c_type(f.type)} {f.name};")
    lines.append(f"}} {decl.name};")
    return "\n".join(lines)


# ============================================================================
# Array Struct Collection
# ============================================================================

def gen_array_structs(decls: list[NDecl]) -> list[str]:
    """Generate array struct definitions."""
    seen = set()
    lines = []
    
    def collect(ntype: NType):
        name = ntype.name
        
        # Skip slice types ([]T) - they use NalaSlice from runtime
        if is_slice_type(name):
            return
        
        # Fixed-size array
        if is_fixed_array_type(name) and name not in seen:
            seen.add(name)
            size, inner = parse_array_type(name)
            inner_c = _TYPE_MAP.get(inner, inner)
            struct_name = f"Array_{size}_{inner}"
            lines.append(f"typedef struct {{ {inner_c} data[{size}]; }} {struct_name};")
    
    def collect_expr(expr: NExpr):
        if isinstance(expr, NVar):
            collect(expr.type)
        elif isinstance(expr, NArrayLiteral):
            collect(expr.type)
        elif isinstance(expr, NBinaryOp):
            collect_expr(expr.left)
            collect_expr(expr.right)
        elif isinstance(expr, NUnaryOp):
            collect_expr(expr.operand)
        elif isinstance(expr, NCall):
            for a in expr.args:
                collect_expr(a)
        elif isinstance(expr, NMethodCall):
            collect_expr(expr.obj)
            for a in expr.args:
                collect_expr(a)
        elif isinstance(expr, NStructLiteral):
            for _, val in expr.fields:
                collect_expr(val)
        elif isinstance(expr, NArrayIndex):
            collect_expr(expr.array)
            collect_expr(expr.index)
    
    def collect_stmt(stmt: NStmt):
        if isinstance(stmt, NReturnStmt):
            if stmt.expr:
                collect_expr(stmt.expr)
        elif isinstance(stmt, NAssignStmt):
            collect_expr(stmt.target)
            collect_expr(stmt.value)
        elif isinstance(stmt, NExprStmt):
            collect_expr(stmt.expr)
        elif isinstance(stmt, NLetStmt):
            collect(stmt.type)
            collect_expr(stmt.value)
        elif isinstance(stmt, NIfStmt):
            collect_expr(stmt.cond)
            for s in stmt.body:
                collect_stmt(s)
            for e in stmt.elifs:
                collect_expr(e.cond)
                for s in e.body:
                    collect_stmt(s)
            for s in stmt.else_body:
                collect_stmt(s)
        elif isinstance(stmt, NWhileStmt):
            collect_expr(stmt.cond)
            for s in stmt.body:
                collect_stmt(s)
        elif isinstance(stmt, NForInStmt):
            collect(stmt.var_type)
            collect_expr(stmt.iterable)
            for s in stmt.body:
                collect_stmt(s)
        elif isinstance(stmt, NMatchStmt):
            collect_expr(stmt.expr)
            for arm in stmt.arms:
                if arm.bind_type:
                    collect(arm.bind_type)
                if arm.guard:
                    collect_expr(arm.guard)
                for s in arm.body:
                    collect_stmt(s)
    
    for d in decls:
        if isinstance(d, NFnDecl):
            collect(d.return_type)
            for p in d.params:
                collect(p.type)
            for s in d.body:
                collect_stmt(s)
        elif isinstance(d, NStructDecl):
            for f in d.fields:
                collect(f.type)
            for m in d.methods:
                collect(m.return_type)
                for p in m.params:
                    collect(p.type)
                for s in m.body:
                    collect_stmt(s)
    
    return lines


# ============================================================================
# Program Codegen
# ============================================================================

def gen_program(program: NProgram) -> str:
    """Generate C code from NIR program."""
    decls = program.decls
    
    # Collect forward declarations
    fwd_protos = []
    for d in decls:
        if isinstance(d, NFnDecl):
            # Skip main forward proto -- it's renamed to __nala_main in impls
            if d.name == "main" and d.struct_name is None:
                continue
            fwd_protos.append(gen_fn_proto(d))
        elif isinstance(d, NStructDecl):
            for m in d.methods:
                fwd_protos.append(gen_fn_proto(m))
    
    # Check if main exists
    has_main = any(
        isinstance(d, NFnDecl) and d.name == "main" and d.struct_name is None
        for d in decls
    )
    
    # Header
    header = [
        "/* Auto-generated by NIR backend */",
        "#include <stdint.h>",
        "#include <stddef.h>",
        "#include <stdlib.h>",
        "#include <string.h>",
        "#include <stdbool.h>",
        "",
    ]
    
    # Runtime
    runtime_lines = RUNTIME_C.strip().split("\n")
    
    # Array structs
    array_lines = gen_array_structs(decls)
    
    # Type definitions
    type_lines = []
    for d in decls:
        if isinstance(d, NEnumDecl):
            type_lines.append(gen_enum(d))
        elif isinstance(d, NUnionDecl):
            type_lines.append(gen_union(d))
        elif isinstance(d, NStructDecl):
            type_lines.append(gen_struct(d))
    
    # Function implementations
    impls = []
    for d in decls:
        if isinstance(d, NStructDecl):
            for m in d.methods:
                impls.append(gen_fn(m))
        elif isinstance(d, NFnDecl):
            if d.name == "main" and d.struct_name is None:
                # Create new NIR function with renamed name (can't mutate frozen)
                renamed = NFnDecl(
                    name="__nala_main",
                    params=d.params,
                    return_type=d.return_type,
                    body=d.body,
                    is_internal=d.is_internal,
                    self_param=d.self_param,
                    struct_name=d.struct_name,
                )
                impls.append(gen_fn(renamed))
            else:
                impls.append(gen_fn(d))

    # Main wrapper
    main_wrapper = []
    if has_main:
        main_wrapper = [
            "",
            "/* Nala main wrapper */",
            "int main(void) {",
            "    __nala_main();",
            "    return 0;",
            "}",
        ]
    
    all_parts = (
        header +
        runtime_lines +
        array_lines +
        type_lines +
        fwd_protos +
        impls +
        main_wrapper
    )
    
    return "\n".join(all_parts) + "\n"
