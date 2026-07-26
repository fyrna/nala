# ir/__init__.py
"""
Intermediate Representations for Nala compiler.
"""

# HIR
from ir.hir import (
    TypeRef,
    HStringLiteral, HIntLiteral, HFloatLiteral, HByteLiteral, HBoolLiteral,
    HIdent, HFieldAccess, HBinaryExpr, HUnaryExpr,
    HCallExpr, HMethodCall, HIntrinsicCall,
    HStructLiteral, HUnionLiteral, HEnumVariantAccess, HIfExpr,
    HArrayLiteral, HArrayIndex,
    HExpr,
    HParam, HSelfParam, HReturnStmt, HIfStmt, HWhileStmt, HForInStmt,
    HAssignStmt, HExprStmt, HLetStmt, HMatchStmt, HMatchArm,
    HElifClause, HContinueStmt, HBreakStmt, HDeferStmt,
    HStmt,
    HEnumDecl, HStructDecl, HStructField, HUnionDecl, HUnionVariant, HFnDecl,
    HDecl,
)
from ir.hir.builder import HIRBuilder, check_program, check_program_modules

# NIR
from ir.nir import (
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
    NIRLower,
)

__all__ = [
    # HIR
    "TypeRef",
    "HStringLiteral", "HIntLiteral", "HFloatLiteral", "HByteLiteral", "HBoolLiteral",
    "HIdent", "HFieldAccess", "HBinaryExpr", "HUnaryExpr",
    "HCallExpr", "HMethodCall", "HIntrinsicCall",
    "HStructLiteral", "HUnionLiteral", "HEnumVariantAccess", "HIfExpr",
    "HArrayLiteral", "HArrayIndex", "HExpr",
    "HParam", "HSelfParam", "HReturnStmt", "HIfStmt", "HWhileStmt", "HForInStmt",
    "HAssignStmt", "HExprStmt", "HLetStmt", "HMatchStmt", "HMatchArm",
    "HElifClause", "HContinueStmt", "HBreakStmt", "HDeferStmt", "HStmt",
    "HEnumDecl", "HStructDecl", "HStructField", "HUnionDecl", "HUnionVariant", "HFnDecl", "HDecl",
    "HIRBuilder", "check_program", "check_program_modules",
    # NIR
    "NType",
    "NStringLiteral", "NIntLiteral", "NFloatLiteral", "NByteLiteral", "NBoolLiteral",
    "NVar", "NFieldAccess", "NBinaryOp", "NUnaryOp",
    "NCall", "NMethodCall", "NIntrinsicCall",
    "NStructLiteral", "NUnionLiteral", "NEnumVariantAccess", "NIfExpr",
    "NArrayLiteral", "NArrayIndex", "NExpr",
    "NReturnStmt", "NAssignStmt", "NExprStmt", "NLetStmt",
    "NIfStmt", "NElifClause", "NWhileStmt", "NForInStmt",
    "NMatchStmt", "NMatchArm", "NDeferStmt", "NContinueStmt", "NBreakStmt", "NStmt",
    "NParam", "NSelfParam", "NField",
    "NStructDecl", "NUnionDecl", "NUnionVariant", "NEnumDecl", "NFnDecl", "NGlobalDecl",
    "NDecl", "NProgram",
    "NIRLower",
]
