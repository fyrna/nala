# nala_ast/nodes.py
"""
AST for Nala. Parser produces raw AST with DottedAccess/DottedCall; type checker resolves them.
All nodes are dataclasses for debuggability.
"""
from dataclasses import dataclass, field
from typing import Union


# --- Top-level declarations ---
@dataclass
class UseDecl:
    module_path: str
    alias: str | None = None


@dataclass
class EnumDecl:
    """const Name = enum { A, B }; C-style enum without payload."""
    name: str
    variants: list[str] = field(default_factory=list)


@dataclass
class UnionVariant:
    """One variant: VariantName(type1, ...)"""
    name: str
    payload_types: list[str] = field(default_factory=list)


@dataclass
class UnionDecl:
    """const Name = union { Variant(type), ... }; tagged union."""
    name: str
    variants: list[UnionVariant] = field(default_factory=list)


@dataclass
class StructField:
    """[mut] name: type"""
    name: str
    type_name: str
    is_mut: bool = False


@dataclass
class StructDecl:
    """const Name = struct { fields; methods... };"""
    name: str
    fields: list[StructField] = field(default_factory=list)
    methods: list["FnDecl"] = field(default_factory=list)


# --- Expressions ---
@dataclass
class Ident:
    name: str


@dataclass
class StringLiteral:
    value: str


@dataclass
class IntLiteral:
    value: str


@dataclass
class FloatLiteral:
    value: str


@dataclass
class BoolLiteral:
    value: bool


@dataclass
class ByteLiteral:
    value: str


@dataclass
class FieldAccess:
    obj: "Expr"
    field: str


@dataclass
class BinaryExpr:
    op: str
    left: "Expr"
    right: "Expr"


@dataclass
class UnaryExpr:
    op: str
    operand: "Expr"


@dataclass
class CallExpr:
    callee: str
    args: list["Expr"] = field(default_factory=list)


@dataclass
class MethodCall:
    obj: "Expr"
    method: str
    args: list["Expr"] = field(default_factory=list)


@dataclass
class IntrinsicCall:
    name: str
    args: list["Expr"] = field(default_factory=list)


@dataclass
class StructLiteral:
    type_name: str
    fields: list[tuple[str, "Expr"]] = field(default_factory=list)


@dataclass
class UnionLiteral:
    union_name: str
    variant_name: str
    payload: "Expr | None" = None


@dataclass
class ArrayLiteral:
    size: int
    element_type: str
    elements: list["Expr"]


@dataclass
class ArrayIndex:
    obj: "Expr"
    index: "Expr"


@dataclass
class EnumVariantAccess:
    enum_name: str
    variant_name: str


# Neutral nodes that must be resolved by type checker
@dataclass
class DottedAccess:
    base: "Expr"
    name: str


@dataclass
class DottedCall:
    base: "Expr"
    name: str
    args: list["Expr"] = field(default_factory=list)


@dataclass
class IfExpr:
    cond: "Expr"
    then_branch: "Expr"
    else_branch: "Expr"


@dataclass
class MatchArm:
    variant: str
    body: list["Stmt"]
    union: str | None = None
    bind: str | None = None
    guard: "Expr | None" = None


@dataclass
class MatchStmt:
    expr: "Expr"
    arms: list[MatchArm]


# Type aliases
Expr = Union[
    BinaryExpr, UnaryExpr, CallExpr, MethodCall, IntrinsicCall, Ident,
    StringLiteral, IntLiteral, FloatLiteral, BoolLiteral, ByteLiteral, FieldAccess, IfExpr,
    StructLiteral, UnionLiteral, EnumVariantAccess,
    DottedAccess, DottedCall,
    ArrayLiteral, ArrayIndex,
]


# --- Statements ---
@dataclass
class Param:
    name: str
    type_name: str


@dataclass
class SelfParam:
    is_mut: bool = False
    is_ref: bool = True


@dataclass
class ReturnStmt:
    expr: Expr


@dataclass
class ElifClause:
    cond: Expr
    body: list["Stmt"]


@dataclass
class IfStmt:
    cond: Expr
    body: list["Stmt"] = field(default_factory=list)
    elifs: list[ElifClause] = field(default_factory=list)
    else_body: list["Stmt"] = field(default_factory=list)


@dataclass
class WhileStmt:
    cond: Expr
    body: list["Stmt"] = field(default_factory=list)


@dataclass
class ForInStmt:
    var_name: str
    iterable: "Expr"
    body: list["Stmt"] = field(default_factory=list)


@dataclass
class AssignStmt:
    target: Expr
    value: Expr
    op: str = "="


@dataclass
class ExprStmt:
    expr: Expr


@dataclass
class ContinueStmt:
    pass


@dataclass
class BreakStmt:
    pass


@dataclass
class DeferStmt:
    """
    defer expr; -- jalankan expr saat keluar scope (LIFO).

    Versi pertama: hanya di level function body langsung (belum nested
    if/for/match), satu statement/call per defer (belum block form).
    """
    expr: Expr


@dataclass
class LetStmt:
    name: str
    value: Expr
    type_name: str | None = None
    is_mut: bool = False


# Type alias for statements
Stmt = Union[
    ReturnStmt, IfStmt, WhileStmt, ForInStmt, AssignStmt, LetStmt, ExprStmt,
    MatchStmt, ContinueStmt, BreakStmt, DeferStmt,
]


@dataclass
class FnDecl:
    name: str
    params: list[Param] = field(default_factory=list)
    return_type: str = "void"
    body: list[Stmt] = field(default_factory=list)
    is_internal: bool = False
    self_param: SelfParam | None = None
    struct_name: str | None = None
