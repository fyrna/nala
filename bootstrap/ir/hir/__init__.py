# ir/hir/__init__.py
"""
HIR (High-level Intermediate Representation) module.
"""

from ir.hir.nodes import (
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

from ir.hir.builder import HIRBuilder, check_program, check_program_modules

__all__ = [
    # --- Types ---
    "TypeRef",
    
    # --- Literals ---
    "HStringLiteral",
    "HIntLiteral",
    "HFloatLiteral",
    "HByteLiteral",
    "HBoolLiteral",
    
    # --- Expressions ---
    "HIdent",
    "HFieldAccess",
    "HBinaryExpr",
    "HUnaryExpr",
    "HCallExpr",
    "HMethodCall",
    "HIntrinsicCall",
    "HStructLiteral",
    "HUnionLiteral",
    "HEnumVariantAccess",
    "HIfExpr",
    "HArrayLiteral",
    "HArrayIndex",
    "HExpr",
    
    # --- Statements ---
    "HParam",
    "HSelfParam",
    "HReturnStmt",
    "HIfStmt",
    "HWhileStmt",
    "HForInStmt",
    "HAssignStmt",
    "HExprStmt",
    "HLetStmt",
    "HMatchStmt",
    "HMatchArm",
    "HElifClause",
    "HContinueStmt",
    "HBreakStmt",
    "HDeferStmt",
    "HStmt",
    
    # --- Declarations ---
    "HEnumDecl",
    "HStructDecl",
    "HStructField",
    "HUnionDecl",
    "HUnionVariant",
    "HFnDecl",
    "HDecl",
    
    # --- Builder ---
    "HIRBuilder",
    "check_program",
    "check_program_modules",
]
