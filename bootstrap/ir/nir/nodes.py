# ir/nir/nodes.py
"""
NIR - Nala Intermediate Representation (Completed, Immutable).
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


# ============================================================================
# Types
# ============================================================================

@dataclass(frozen=True)
class NType:
    name: str
    
    def __str__(self) -> str:
        return self.name


# ============================================================================
# Literals
# ============================================================================

@dataclass(frozen=True)
class NStringLiteral:
    value: str
    type: NType = field(default_factory=lambda: NType("str"))


@dataclass(frozen=True)
class NIntLiteral:
    value: str
    type: NType


@dataclass(frozen=True)
class NFloatLiteral:
    value: str
    type: NType


@dataclass(frozen=True)
class NBoolLiteral:
    value: bool
    type: NType = field(default_factory=lambda: NType("bool"))


@dataclass(frozen=True)
class NByteLiteral:
    value: str
    type: NType = field(default_factory=lambda: NType("u8"))


# ============================================================================
# Expressions
# ============================================================================

@dataclass(frozen=True)
class NVar:
    name: str
    type: NType


@dataclass(frozen=True)
class NFieldAccess:
    obj: NExpr
    field: str
    type: NType


@dataclass(frozen=True)
class NBinaryOp:
    op: str
    left: NExpr
    right: NExpr
    type: NType


@dataclass(frozen=True)
class NUnaryOp:
    op: str
    operand: NExpr
    type: NType


@dataclass(frozen=True)
class NCall:
    name: str
    args: list[NExpr]
    return_type: NType


@dataclass(frozen=True)
class NMethodCall:
    obj: NExpr
    method: str
    args: list[NExpr]
    struct_name: str
    return_type: NType


@dataclass(frozen=True)
class NIntrinsicCall:
    name: str
    args: list[NExpr]
    return_type: NType


@dataclass(frozen=True)
class NStructLiteral:
    type_name: str
    type: NType
    fields: list[tuple[str, NExpr]] = field(default_factory=list)


@dataclass(frozen=True)
class NUnionLiteral:
    union_name: str
    variant_name: str
    type: NType
    payload: Optional[NExpr] = None


@dataclass(frozen=True)
class NEnumVariantAccess:
    enum_name: str
    variant_name: str
    type: NType


@dataclass(frozen=True)
class NIfExpr:
    cond: NExpr
    then_branch: NExpr
    else_branch: NExpr
    type: NType


@dataclass(frozen=True)
class NArrayLiteral:
    type: NType
    elements: list[NExpr] = field(default_factory=list)


@dataclass(frozen=True)
class NArrayIndex:
    array: NExpr
    index: NExpr
    type: NType


NExpr = (
    NStringLiteral | NIntLiteral | NFloatLiteral | NBoolLiteral | NByteLiteral |
    NVar | NFieldAccess | NBinaryOp | NUnaryOp |
    NCall | NMethodCall | NIntrinsicCall |
    NStructLiteral | NUnionLiteral | NEnumVariantAccess | NIfExpr |
    NArrayLiteral | NArrayIndex
)


# ============================================================================
# Statements
# ============================================================================

@dataclass(frozen=True)
class NReturnStmt:
    expr: Optional[NExpr] = None


@dataclass(frozen=True)
class NAssignStmt:
    target: NExpr
    value: NExpr
    op: str = "="


@dataclass(frozen=True)
class NExprStmt:
    expr: NExpr


@dataclass(frozen=True)
class NLetStmt:
    name: str
    type: NType
    value: NExpr
    is_mut: bool = False


@dataclass(frozen=True)
class NElifClause:
    cond: NExpr
    body: list[NStmt]


@dataclass(frozen=True)
class NIfStmt:
    cond: NExpr
    body: list[NStmt]
    elifs: list[NElifClause] = field(default_factory=list)
    else_body: list[NStmt] = field(default_factory=list)


@dataclass(frozen=True)
class NWhileStmt:
    cond: NExpr
    body: list[NStmt]


@dataclass(frozen=True)
class NForInStmt:
    var_name: str
    var_type: NType
    iterable: NExpr
    body: list[NStmt]


@dataclass(frozen=True)
class NMatchArm:
    variant: str
    union_name: str
    body: list[NStmt]
    bind: Optional[str] = None
    bind_type: Optional[NType] = None
    guard: Optional[NExpr] = None


@dataclass(frozen=True)
class NMatchStmt:
    expr: NExpr
    arms: list[NMatchArm]
    union_type: NType


@dataclass(frozen=True)
class NDeferStmt:
    expr: NExpr


@dataclass(frozen=True)
class NContinueStmt:
    pass


@dataclass(frozen=True)
class NBreakStmt:
    pass


NStmt = (
    NReturnStmt | NAssignStmt | NExprStmt | NLetStmt |
    NIfStmt | NWhileStmt | NForInStmt |
    NMatchStmt | NDeferStmt | NContinueStmt | NBreakStmt
)


# ============================================================================
# Top-level Declarations
# ============================================================================

@dataclass(frozen=True)
class NParam:
    name: str
    type: NType


@dataclass(frozen=True)
class NSelfParam:
    is_mut: bool = False
    is_ref: bool = True


@dataclass(frozen=True)
class NField:
    name: str
    type: NType
    is_mut: bool = False


@dataclass(frozen=True)
class NStructDecl:
    name: str
    fields: list[NField]
    methods: list[NFnDecl] = field(default_factory=list)


@dataclass(frozen=True)
class NUnionVariant:
    name: str
    payload_type: Optional[NType] = None


@dataclass(frozen=True)
class NUnionDecl:
    name: str
    variants: list[NUnionVariant]


@dataclass(frozen=True)
class NEnumDecl:
    name: str
    variants: list[str]


@dataclass(frozen=True)
class NFnDecl:
    name: str
    params: list[NParam]
    return_type: NType
    body: list[NStmt]
    is_internal: bool = False
    self_param: Optional[NSelfParam] = None
    struct_name: Optional[str] = None


@dataclass(frozen=True)
class NGlobalDecl:
    name: str
    type: NType
    value: Optional[NExpr] = None
    is_mut: bool = False


NDecl = NStructDecl | NUnionDecl | NEnumDecl | NFnDecl | NGlobalDecl


@dataclass(frozen=True)
class NProgram:
    decls: list[NDecl]
    entry_point: Optional[str] = None
