# ir/nir/lower.py
"""
HIR → NIR lowering.

Mengubah HIR (mutable, high-level) menjadi NIR (immutable, completed).
"""

from __future__ import annotations

from ir.hir import (
    HDecl, HExpr, HStmt,
    HEnumDecl, HStructDecl, HStructField, HUnionDecl, HUnionVariant, HFnDecl,
    HParam, HSelfParam,
    HIdent, HStringLiteral, HIntLiteral, HFloatLiteral, HByteLiteral, HBoolLiteral,
    HBinaryExpr, HUnaryExpr, HCallExpr, HMethodCall, HIntrinsicCall,
    HFieldAccess, HStructLiteral, HUnionLiteral, HEnumVariantAccess,
    HIfExpr, HArrayLiteral, HArrayIndex,
    HReturnStmt, HIfStmt, HWhileStmt, HForInStmt, HAssignStmt, HExprStmt,
    HLetStmt, HMatchStmt, HMatchArm, HElifClause, HContinueStmt, HBreakStmt, HDeferStmt,
)

from ir.nir.nodes import (
    NProgram, NDecl, NFnDecl, NStructDecl, NUnionDecl, NEnumDecl, NGlobalDecl,
    NField, NParam, NSelfParam, NUnionVariant,
    NType, NExpr, NStmt,
    NVar, NStringLiteral, NIntLiteral, NFloatLiteral, NByteLiteral, NBoolLiteral,
    NBinaryOp, NUnaryOp, NCall, NMethodCall, NIntrinsicCall,
    NFieldAccess, NStructLiteral, NUnionLiteral, NEnumVariantAccess,
    NIfExpr, NArrayLiteral, NArrayIndex,
    NReturnStmt, NAssignStmt, NExprStmt, NLetStmt,
    NIfStmt, NElifClause, NWhileStmt, NForInStmt,
    NMatchStmt, NMatchArm, NDeferStmt, NContinueStmt, NBreakStmt,
)

from checker.symbol_table import SymbolTable


class NIRLower:
    """
    Lower HIR to NIR.
    
    NIR adalah representasi FINAL - tidak ada proses lagi setelah ini.
    Backend hanya membaca NIR dan generate code.
    """
    
    def __init__(self, table: SymbolTable, current_module: str | None = None):
        self.table = table
        self._current_module = current_module
        self._current_struct: str | None = None
    
    def lower_program(self, hir_decls: list[HDecl]) -> NProgram:
        """Lower seluruh program HIR → NIR."""
        decls = []
        for d in hir_decls:
            decls.append(self.lower_decl(d))
        
        entry = None
        for d in decls:
            if isinstance(d, NFnDecl) and d.name == "main" and d.struct_name is None:
                entry = d.name
                break
        
        return NProgram(decls=decls, entry_point=entry)
    
    def lower_decl(self, decl: HDecl) -> NDecl:
        """Lower satu deklarasi."""
        if isinstance(decl, HEnumDecl):
            return NEnumDecl(name=decl.name, variants=decl.variants)
        
        elif isinstance(decl, HStructDecl):
            self._current_struct = decl.name
            fields = [
                NField(name=f.name, type=NType(f.type_ref.name), is_mut=f.is_mut)
                for f in decl.fields
            ]
            methods = [self.lower_decl(m) for m in decl.methods]
            self._current_struct = None
            return NStructDecl(name=decl.name, fields=fields, methods=methods)
        
        elif isinstance(decl, HUnionDecl):
            variants = [
                NUnionVariant(
                    name=v.name,
                    payload_type=NType(v.payload_type.name) if v.payload_type else None
                )
                for v in decl.variants
            ]
            return NUnionDecl(name=decl.name, variants=variants)
        
        elif isinstance(decl, HFnDecl):
            return self.lower_function(decl)
        
        else:
            raise ValueError(f"Unknown HIR decl: {type(decl)}")
    
    def lower_function(self, decl: HFnDecl) -> NFnDecl:
        """Lower HIR function → NIR function."""
        params = [
            NParam(name=p.name, type=NType(p.type_ref.name))
            for p in decl.params
        ]
        
        self_param = None
        if decl.self_param is not None:
            self_param = NSelfParam(
                is_mut=decl.self_param.is_mut,
                is_ref=decl.self_param.is_ref
            )
        
        body = [self.lower_stmt(s) for s in decl.body]
        
        return NFnDecl(
            name=decl.name,
            params=params,
            return_type=NType(decl.return_type.name),
            body=body,
            is_internal=decl.is_internal,
            self_param=self_param,
            struct_name=decl.struct_name,
        )
    
    def lower_expr(self, expr: HExpr) -> NExpr:
        """Lower HIR expression → NIR expression."""
        if isinstance(expr, HIdent):
            return NVar(name=expr.name, type=NType(expr.type_ref.name))
        
        elif isinstance(expr, HStringLiteral):
            return NStringLiteral(value=expr.value)
        
        elif isinstance(expr, HIntLiteral):
            return NIntLiteral(value=expr.value, type=NType(expr.type_ref.name))
        
        elif isinstance(expr, HFloatLiteral):
            return NFloatLiteral(value=expr.value, type=NType(expr.type_ref.name))
        
        elif isinstance(expr, HByteLiteral):
            return NByteLiteral(value=expr.value)
        
        elif isinstance(expr, HBoolLiteral):
            return NBoolLiteral(value=expr.value)
        
        elif isinstance(expr, HBinaryExpr):
            return NBinaryOp(
                op=self._map_binary_op(expr.op),
                left=self.lower_expr(expr.left),
                right=self.lower_expr(expr.right),
                type=NType(expr.type_ref.name)
            )
        
        elif isinstance(expr, HUnaryExpr):
            return NUnaryOp(
                op=self._map_unary_op(expr.op),
                operand=self.lower_expr(expr.operand),
                type=NType(expr.type_ref.name)
            )
        
        elif isinstance(expr, HCallExpr):
            return NCall(
                name=expr.callee,
                args=[self.lower_expr(a) for a in expr.args],
                return_type=NType(expr.type_ref.name)
            )
        
        elif isinstance(expr, HMethodCall):
            return NMethodCall(
                obj=self.lower_expr(expr.obj),
                method=expr.method,
                args=[self.lower_expr(a) for a in expr.args],
                struct_name=expr.struct_name,
                return_type=NType(expr.type_ref.name)
            )
        
        elif isinstance(expr, HIntrinsicCall):
            return NIntrinsicCall(
                name=expr.name,
                args=[self.lower_expr(a) for a in expr.args],
                return_type=NType(expr.type_ref.name)
            )
        
        elif isinstance(expr, HFieldAccess):
            return NFieldAccess(
                obj=self.lower_expr(expr.obj),
                field=expr.field,
                type=NType(expr.type_ref.name)
            )
        
        elif isinstance(expr, HStructLiteral):
            type_name = expr.type_name
            if '.' in type_name:
                resolved = self.table.resolve_qualified_name(
                    self._current_module or "local", type_name
                )
                if resolved:
                    _, type_name = resolved
            
            fields = [
                (name, self.lower_expr(val))
                for name, val in expr.fields
            ]
            return NStructLiteral(
                type_name=type_name,
                fields=fields,
                type=NType(expr.type_ref.name)
            )
        
        elif isinstance(expr, HUnionLiteral):
            return NUnionLiteral(
                union_name=expr.union_name,
                variant_name=expr.variant_name,
                payload=self.lower_expr(expr.payload) if expr.payload else None,
                type=NType(expr.type_ref.name)
            )
        
        elif isinstance(expr, HEnumVariantAccess):
            return NEnumVariantAccess(
                enum_name=expr.enum_name,
                variant_name=expr.variant_name,
                type=NType(expr.type_ref.name)
            )
        
        elif isinstance(expr, HIfExpr):
            return NIfExpr(
                cond=self.lower_expr(expr.cond),
                then_branch=self.lower_expr(expr.then_branch),
                else_branch=self.lower_expr(expr.else_branch),
                type=NType(expr.type_ref.name)
            )
        
        elif isinstance(expr, HArrayLiteral):
            return NArrayLiteral(
                elements=[self.lower_expr(e) for e in expr.elements],
                type=NType(expr.type_ref.name)
            )
        
        elif isinstance(expr, HArrayIndex):
            return NArrayIndex(
                array=self.lower_expr(expr.obj),
                index=self.lower_expr(expr.index),
                type=NType(expr.type_ref.name)
            )
        
        else:
            raise ValueError(f"Unknown HIR expr: {type(expr)}")
    
    def lower_stmt(self, stmt: HStmt) -> NStmt:
        """Lower HIR statement → NIR statement."""
        if isinstance(stmt, HReturnStmt):
            expr = self.lower_expr(stmt.expr) if stmt.expr else None
            return NReturnStmt(expr=expr)
        
        elif isinstance(stmt, HAssignStmt):
            return NAssignStmt(
                target=self.lower_expr(stmt.target),
                value=self.lower_expr(stmt.value),
                op=stmt.op
            )
        
        elif isinstance(stmt, HExprStmt):
            return NExprStmt(expr=self.lower_expr(stmt.expr))
        
        elif isinstance(stmt, HLetStmt):
            return NLetStmt(
                name=stmt.name,
                value=self.lower_expr(stmt.value),
                type=NType(stmt.type_ref.name),
                is_mut=stmt.is_mut
            )
        
        elif isinstance(stmt, HIfStmt):
            elifs = [
                NElifClause(
                    cond=self.lower_expr(e.cond),
                    body=[self.lower_stmt(s) for s in e.body]
                )
                for e in stmt.elifs
            ]
            return NIfStmt(
                cond=self.lower_expr(stmt.cond),
                body=[self.lower_stmt(s) for s in stmt.body],
                elifs=elifs,
                else_body=[self.lower_stmt(s) for s in stmt.else_body]
            )
        
        elif isinstance(stmt, HWhileStmt):
            return NWhileStmt(
                cond=self.lower_expr(stmt.cond),
                body=[self.lower_stmt(s) for s in stmt.body]
            )
        
        elif isinstance(stmt, HForInStmt):
            return NForInStmt(
                var_name=stmt.var_name,
                var_type=NType(stmt.var_type.name),
                iterable=self.lower_expr(stmt.iterable),
                body=[self.lower_stmt(s) for s in stmt.body]
            )
        
        elif isinstance(stmt, HMatchStmt):
            arms = []
            for arm in stmt.arms:
                arms.append(NMatchArm(
                    variant=arm.variant,
                    union_name=arm.union_name,
                    bind=arm.bind,
                    bind_type=NType(arm.bind_type.name) if arm.bind_type else None,
                    guard=self.lower_expr(arm.guard) if arm.guard else None,
                    body=[self.lower_stmt(s) for s in arm.body]
                ))
            return NMatchStmt(
                expr=self.lower_expr(stmt.expr),
                arms=arms,
                union_type=NType(stmt.union_name)
            )
        
        elif isinstance(stmt, HDeferStmt):
            return NDeferStmt(expr=self.lower_expr(stmt.expr))
        
        elif isinstance(stmt, HContinueStmt):
            return NContinueStmt()
        
        elif isinstance(stmt, HBreakStmt):
            return NBreakStmt()
        
        else:
            raise ValueError(f"Unknown HIR stmt: {type(stmt)}")
    
    def _map_binary_op(self, op: str) -> str:
        """Map HIR binary op to semantic NIR op."""
        return op
    
    def _map_unary_op(self, op: str) -> str:
        """Map HIR unary op to semantic NIR op."""
        return op
