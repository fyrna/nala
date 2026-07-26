# ir/nir/__init__.py
"""
NIR - Nala Intermediate Representation (Completed, Immutable).

NIR adalah representasi final program yang sudah selesai dikompilasi.
"""

from ir.nir.nodes import (
    NType,
    NStringLiteral, NIntLiteral, NFloatLiteral, NByteLiteral, NBoolLiteral,
    NVar, NFieldAccess, NBinaryOp, NUnaryOp,
    NCall, NMethodCall, NIntrinsicCall,
    NStructLiteral, NUnionLiteral, NEnumVariantAccess, NIfExpr,
    NArrayLiteral, NArrayIndex,
    NExpr,
    NReturnStmt, NAssignStmt, NExprStmt, NLetStmt,
    NIfStmt, NElifClause, NWhileStmt, NForInStmt,
    NMatchStmt, NMatchArm, NDeferStmt, NContinueStmt, NBreakStmt,
    NStmt,
    NParam, NSelfParam, NField,
    NStructDecl, NUnionDecl, NUnionVariant, NEnumDecl, NFnDecl, NGlobalDecl,
    NDecl, NProgram,
)

from ir.nir.lower import NIRLower

__all__ = [
    "NType",
    "NStringLiteral", "NIntLiteral", "NFloatLiteral", "NByteLiteral", "NBoolLiteral",
    "NVar", "NFieldAccess", "NBinaryOp", "NUnaryOp",
    "NCall", "NMethodCall", "NIntrinsicCall",
    "NStructLiteral", "NUnionLiteral", "NEnumVariantAccess", "NIfExpr",
    "NArrayLiteral", "NArrayIndex",
    "NExpr",
    "NReturnStmt", "NAssignStmt", "NExprStmt", "NLetStmt",
    "NIfStmt", "NElifClause", "NWhileStmt", "NForInStmt",
    "NMatchStmt", "NMatchArm", "NDeferStmt", "NContinueStmt", "NBreakStmt",
    "NStmt",
    "NParam", "NSelfParam", "NField",
    "NStructDecl", "NUnionDecl", "NUnionVariant", "NEnumDecl", "NFnDecl", "NGlobalDecl",
    "NDecl", "NProgram",
    "NIRLower",
]
