# nala_ast/visitor.py
"""
Visitor pattern for Nala AST.
Provides base visitor class with visit methods for all node types.
"""
from __future__ import annotations
from typing import Any, Protocol, TypeVar, runtime_checkable

from nala_ast.nodes import (
    AssignStmt, BinaryExpr, BoolLiteral, BreakStmt, ByteLiteral, CallExpr,
    ContinueStmt, DeferStmt, DottedAccess, DottedCall, ElifClause, EnumDecl,
    EnumVariantAccess, ExprStmt, FieldAccess, FloatLiteral, FnDecl, ForInStmt,
    Ident, IfExpr, IfStmt, IntLiteral, IntrinsicCall, LetStmt, MatchArm,
    MatchStmt, MethodCall, Param, ReturnStmt, SelfParam, StringLiteral,
    StructDecl, StructField, StructLiteral, UnaryExpr, UnionDecl, UnionLiteral,
    UnionVariant, WhileStmt,
)


class ASTVisitor:
    """
    Base visitor class for Nala AST.
    Override visit_* methods for specific nodes.
    Default implementation does nothing and returns None.
    """

    def visit(self, node: Any) -> Any:
        """Dispatch to appropriate visit_* method based on node type."""
        method_name = f"visit_{node.__class__.__name__}"
        method = getattr(self, method_name, self.generic_visit)
        return method(node)

    def generic_visit(self, node: Any) -> None:
        """Default visit method - does nothing."""
        pass

    # --- Top-level declarations ---
    def visit_UseDecl(self, node: UseDecl) -> Any:
        return self.generic_visit(node)

    def visit_EnumDecl(self, node: EnumDecl) -> Any:
        return self.generic_visit(node)

    def visit_UnionVariant(self, node: UnionVariant) -> Any:
        return self.generic_visit(node)

    def visit_UnionDecl(self, node: UnionDecl) -> Any:
        return self.generic_visit(node)

    def visit_StructField(self, node: StructField) -> Any:
        return self.generic_visit(node)

    def visit_StructDecl(self, node: StructDecl) -> Any:
        return self.generic_visit(node)

    # --- Expressions ---
    def visit_Ident(self, node: Ident) -> Any:
        return self.generic_visit(node)

    def visit_StringLiteral(self, node: StringLiteral) -> Any:
        return self.generic_visit(node)

    def visit_IntLiteral(self, node: IntLiteral) -> Any:
        return self.generic_visit(node)

    def visit_FloatLiteral(self, node: FloatLiteral) -> Any:
        return self.generic_visit(node)

    def visit_BoolLiteral(self, node: BoolLiteral) -> Any:
        return self.generic_visit(node)

    def visit_ByteLiteral(self, node: ByteLiteral) -> Any:
        return self.generic_visit(node)

    def visit_FieldAccess(self, node: FieldAccess) -> Any:
        self.visit(node.obj)
        return self.generic_visit(node)

    def visit_BinaryExpr(self, node: BinaryExpr) -> Any:
        self.visit(node.left)
        self.visit(node.right)
        return self.generic_visit(node)

    def visit_UnaryExpr(self, node: UnaryExpr) -> Any:
        self.visit(node.operand)
        return self.generic_visit(node)

    def visit_CallExpr(self, node: CallExpr) -> Any:
        for arg in node.args:
            self.visit(arg)
        return self.generic_visit(node)

    def visit_MethodCall(self, node: MethodCall) -> Any:
        self.visit(node.obj)
        for arg in node.args:
            self.visit(arg)
        return self.generic_visit(node)

    def visit_IntrinsicCall(self, node: IntrinsicCall) -> Any:
        for arg in node.args:
            self.visit(arg)
        return self.generic_visit(node)

    def visit_StructLiteral(self, node: StructLiteral) -> Any:
        for _, expr in node.fields:
            self.visit(expr)
        return self.generic_visit(node)

    def visit_UnionLiteral(self, node: UnionLiteral) -> Any:
        if node.payload:
            self.visit(node.payload)
        return self.generic_visit(node)

    def visit_ArrayLiteral(self, node: ArrayLiteral) -> Any:
        for elem in node.elements:
            self.visit(elem)
        return self.generic_visit(node)

    def visit_ArrayIndex(self, node: ArrayIndex) -> Any:
        self.visit(node.obj)
        self.visit(node.index)
        return self.generic_visit(node)

    def visit_EnumVariantAccess(self, node: EnumVariantAccess) -> Any:
        return self.generic_visit(node)

    def visit_DottedAccess(self, node: DottedAccess) -> Any:
        self.visit(node.base)
        return self.generic_visit(node)

    def visit_DottedCall(self, node: DottedCall) -> Any:
        self.visit(node.base)
        for arg in node.args:
            self.visit(arg)
        return self.generic_visit(node)

    def visit_IfExpr(self, node: IfExpr) -> Any:
        self.visit(node.cond)
        self.visit(node.then_branch)
        self.visit(node.else_branch)
        return self.generic_visit(node)

    def visit_MatchArm(self, node: MatchArm) -> Any:
        for stmt in node.body:
            self.visit(stmt)
        if node.guard:
            self.visit(node.guard)
        return self.generic_visit(node)

    def visit_MatchStmt(self, node: MatchStmt) -> Any:
        self.visit(node.expr)
        for arm in node.arms:
            self.visit(arm)
        return self.generic_visit(node)

    # --- Statements ---
    def visit_Param(self, node: Param) -> Any:
        return self.generic_visit(node)

    def visit_SelfParam(self, node: SelfParam) -> Any:
        return self.generic_visit(node)

    def visit_ReturnStmt(self, node: ReturnStmt) -> Any:
        self.visit(node.expr)
        return self.generic_visit(node)

    def visit_ElifClause(self, node: ElifClause) -> Any:
        self.visit(node.cond)
        for stmt in node.body:
            self.visit(stmt)
        return self.generic_visit(node)

    def visit_IfStmt(self, node: IfStmt) -> Any:
        self.visit(node.cond)
        for stmt in node.body:
            self.visit(stmt)
        for elif_clause in node.elifs:
            self.visit(elif_clause)
        for stmt in node.else_body:
            self.visit(stmt)
        return self.generic_visit(node)

    def visit_WhileStmt(self, node: WhileStmt) -> Any:
        self.visit(node.cond)
        for stmt in node.body:
            self.visit(stmt)
        return self.generic_visit(node)

    def visit_ForInStmt(self, node: ForInStmt) -> Any:
        self.visit(node.iterable)
        for stmt in node.body:
            self.visit(stmt)
        return self.generic_visit(node)

    def visit_AssignStmt(self, node: AssignStmt) -> Any:
        self.visit(node.target)
        self.visit(node.value)
        return self.generic_visit(node)

    def visit_ExprStmt(self, node: ExprStmt) -> Any:
        self.visit(node.expr)
        return self.generic_visit(node)

    def visit_ContinueStmt(self, node: ContinueStmt) -> Any:
        return self.generic_visit(node)

    def visit_BreakStmt(self, node: BreakStmt) -> Any:
        return self.generic_visit(node)

    def visit_DeferStmt(self, node: DeferStmt) -> Any:
        self.visit(node.expr)
        return self.generic_visit(node)

    def visit_LetStmt(self, node: LetStmt) -> Any:
        self.visit(node.value)
        return self.generic_visit(node)

    def visit_FnDecl(self, node: FnDecl) -> Any:
        for stmt in node.body:
            self.visit(stmt)
        return self.generic_visit(node)


# Optional: Protocol for type-safe visitors (Python 3.8+)
T = TypeVar('T', covariant=True)

@runtime_checkable
class ASTVisitorProtocol(Protocol[T]):
    """Protocol for AST visitors with return type T."""
    def visit(self, node: Any) -> T: ...
    def generic_visit(self, node: Any) -> T: ...
