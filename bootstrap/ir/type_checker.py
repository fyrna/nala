"""
bootstrap/ir/type_checker.py

Type Checker / Semantic Analyzer -- AST -> HIR Translator.

Tanggung jawab TUNGGAL modul ini:
    1. Terima AST "raw" (pure syntax) dari parser
    2. Buat HIR "final" (resolved + typed) yang baru
    3. TIDAK mutasi AST -- AST tetap immutable setelah parse

FILOSOFI:
    - Parser shall know nothing except language syntax.
    - Type checker adalah satu-satunya yang membuat keputusan semantik.
    - Codegen HANYA membaca HIR, tidak pernah melihat AST.

ALUR KERJA:
    1. Bangun SymbolTable dari AST top-level declarations
    2. Traversal AST, translate node per node ke HIR
    3. Resolve semua DottedAccess/DottedCall
    4. Infer dan attach TypeRef ke setiap ekspresi
    5. Attach metadata semantik (union_name, bind_type, struct_name)
    6. Return list[HDecl] -- HIR yang siap dikonsumsi codegen

ERROR HANDLING:
    - TypeCheckError untuk semua error semantik
    - Fail-fast: error pertama akan menghentikan kompilasi
"""

from __future__ import annotations

import dataclasses

from nala_ast import (
    # Declarations
    EnumDecl, StructDecl, UnionDecl, UnionVariant, StructField,
    FnDecl, Param, SelfParam,
    # Expressions
    Expr, Ident, StringLiteral, IntLiteral, FloatLiteral, ByteLiteral,
    BinaryExpr, UnaryExpr, CallExpr, FieldAccess, MethodCall,
    IntrinsicCall, StructLiteral, UnionLiteral, EnumVariantAccess,
    IfExpr, DottedAccess, DottedCall,
    ArrayLiteral, ArrayIndex,
    # Statements
    Stmt, ReturnStmt, IfStmt, WhileStmt, ForInStmt, AssignStmt, ExprStmt,
    LetStmt, MatchStmt, MatchArm, ElifClause, ContinueStmt, BreakStmt,
)

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


class TypeCheckError(Exception):
    """Error semantik -- beda dari ParseError (syntax error)."""
    pass


# ---------------------------------------------------------------------------
# SymbolTable -- lookup deklarasi top-level
# ---------------------------------------------------------------------------

class SymbolTable:
    """
    Tabel simbol untuk lookup deklarasi top-level.

    Menyimpan:
        - union_names, enum_names, struct_names: set[str]
        - union_variants: dict[union_name, set[variant_names]]
        - union_payload_types: dict[union_name, dict[variant_name, str|None]]
        - enum_variants: dict[enum_name, set[variant_names]]
        - struct_fields: dict[struct_name, dict[field_name, (type_name, is_mut)]]
    """

    def __init__(self) -> None:
        self.union_names: set[str] = set()
        self.enum_names: set[str] = set()
        self.struct_names: set[str] = set()

        self.union_variants: dict[str, set[str]] = {}
        self.union_payload_types: dict[str, dict[str, str | None]] = {}
        self.enum_variants: dict[str, set[str]] = {}
        self.struct_fields: dict[str, dict[str, tuple[str, bool]]] = {}

    @classmethod
    def build(cls, decls: list) -> "SymbolTable":
        table = cls()
        for decl in decls:
            if isinstance(decl, UnionDecl):
                table.union_names.add(decl.name)
                table.union_variants[decl.name] = {v.name for v in decl.variants}
                table.union_payload_types[decl.name] = {}
                for v in decl.variants:
                    if len(v.payload_types) > 0:
                        table.union_payload_types[decl.name][v.name] = v.payload_types[0]
                    else:
                        table.union_payload_types[decl.name][v.name] = None
            elif isinstance(decl, EnumDecl):
                table.enum_names.add(decl.name)
                table.enum_variants[decl.name] = set(decl.variants)
            elif isinstance(decl, StructDecl):
                table.struct_names.add(decl.name)
                table.struct_fields[decl.name] = {}
                for f in decl.fields:
                    table.struct_fields[decl.name][f.name] = (f.type_name, f.is_mut)
        return table


# ---------------------------------------------------------------------------
# Type Checker / HIR Builder
# ---------------------------------------------------------------------------

class HIRBuilder:
    """
    Builder untuk menerjemahkan AST -> HIR.

    State:
        - table: SymbolTable untuk lookup top-level declarations
        - local_types: dict[str, str] -- tipe variabel lokal (nama -> type_name)
        - current_struct_name: str | None -- struct yang sedang diproses (untuk self)
    """

    def __init__(self, table: SymbolTable) -> None:
        self.table = table
        self.local_types: dict[str, str] = {}
        self.current_struct_name: str | None = None

    # --- Helper: TypeRef ---

    def _type_ref(self, type_name: str | None) -> TypeRef:
        """Buat TypeRef dari nama tipe (fallback ke 'void' kalau None)."""
        return TypeRef(type_name if type_name is not None else "void")

    def _parse_array_type(self, type_name: str) -> tuple[int, str] | None:
        """Parse [N]T -> (N, T) atau None kalau bukan array type."""
        if not type_name.startswith("[") or "]" not in type_name:
            return None
        # Format: [N]T
        bracket_end = type_name.index("]")
        size_str = type_name[1:bracket_end]
        inner_type = type_name[bracket_end + 1:]
        try:
            size = int(size_str)
            return (size, inner_type)
        except ValueError:
            return None

    def _array_element_type(self, type_name: str) -> str | None:
        """Dapatkan tipe elemen dari [N]T, atau None."""
        parsed = self._parse_array_type(type_name)
        return parsed[1] if parsed else None

    def _infer_expr_type(self, expr: Expr) -> TypeRef:
        """Infer tipe dari ekspresi AST (sederhana, untuk local tracking)."""
        if isinstance(expr, StringLiteral):
            return TypeRef("str")
        elif isinstance(expr, IntLiteral):
            return TypeRef("i32")
        elif isinstance(expr, FloatLiteral):
            return TypeRef("f32")
        elif isinstance(expr, ByteLiteral):
            return TypeRef("u8")
        elif isinstance(expr, Ident):
            if expr.name in self.local_types:
                return TypeRef(self.local_types[expr.name])
            if expr.name == "self" and self.current_struct_name:
                return TypeRef(self.current_struct_name)
        elif isinstance(expr, StructLiteral):
            return TypeRef(expr.type_name)
        elif isinstance(expr, UnionLiteral):
            return TypeRef(expr.union_name)
        elif isinstance(expr, EnumVariantAccess):
            return TypeRef(expr.enum_name)
        elif isinstance(expr, ArrayLiteral):
            # Size dan element type sudah eksplisit di literal-nya sendiri
            # ([N]T{...}) -- tidak perlu (dan tidak boleh) ditebak dari
            # elemen pertama.
            return TypeRef(f"[{expr.size}]{expr.element_type}")
        return TypeRef("void")  # fallback

    # --- Translation: Expressions ---

    def _translate_expr(self, expr: Expr) -> HExpr:
        """Translate AST Expr -> HIR HExpr."""
        if isinstance(expr, Ident):
            type_name = self.local_types.get(expr.name)
            if type_name is None and expr.name == "self" and self.current_struct_name:
                type_name = self.current_struct_name
            return HIdent(name=expr.name, type_ref=self._type_ref(type_name))

        elif isinstance(expr, StringLiteral):
            return HStringLiteral(value=expr.value)

        elif isinstance(expr, IntLiteral):
            return HIntLiteral(value=expr.value)

        elif isinstance(expr, FloatLiteral):
            return HFloatLiteral(value=expr.value)

        elif isinstance(expr, ByteLiteral):
            return HByteLiteral(value=expr.value)

        elif isinstance(expr, BinaryExpr):
            left = self._translate_expr(expr.left)
            right = self._translate_expr(expr.right)
            # Infer tipe hasil binary expr (sederhana: aritmetika -> i32, comparison -> bool)
            if expr.op in ("+", "-", "*", "/"):
                result_type = TypeRef("i32")
            elif expr.op in ("==", "!=", ">", "<", ">=", "<=", "and", "or"):
                result_type = TypeRef("bool")
            else:
                result_type = TypeRef("void")
            return HBinaryExpr(op=expr.op, left=left, right=right, type_ref=result_type)

        elif isinstance(expr, UnaryExpr):
            operand = self._translate_expr(expr.operand)
            if expr.op == "!":
                result_type = TypeRef("bool")
            else:
                result_type = TypeRef("void")
            return HUnaryExpr(op=expr.op, operand=operand, type_ref=result_type)

        elif isinstance(expr, CallExpr):
            args = [self._translate_expr(a) for a in expr.args]
            # Untuk fungsi user-defined, kita belum punya signature table
            # Jadi return type di-infer dari context (sederhana: void untuk sekarang)
            return HCallExpr(callee=expr.callee, args=args, type_ref=TypeRef("void"))

        elif isinstance(expr, FieldAccess):
            obj = self._translate_expr(expr.obj)
            # Coba infer tipe field dari struct definition
            field_type = self._infer_field_type(obj, expr.field)
            return HFieldAccess(obj=obj, field=expr.field, type_ref=field_type)

        elif isinstance(expr, MethodCall):
            obj = self._translate_expr(expr.obj)
            args = [self._translate_expr(a) for a in expr.args]
            # AST MethodCall no longer has struct_name -- always infer from context
            struct_name = self.current_struct_name
            if isinstance(expr.obj, Ident):
                if expr.obj.name == "self" and self.current_struct_name:
                    struct_name = self.current_struct_name
                elif expr.obj.name in self.local_types:
                    struct_name = self.local_types[expr.obj.name]
            if struct_name is None:
                raise TypeCheckError(
                    f"MethodCall untuk '{expr.method}' tidak bisa infer struct_name -- "
                    f"tipe objek tidak diketahui."
                )
            return HMethodCall(
                obj=obj, method=expr.method, args=args,
                struct_name=struct_name, type_ref=TypeRef("void")
            )

        elif isinstance(expr, IntrinsicCall):
            args = [self._translate_expr(a) for a in expr.args]
            # Infer return type dari nama intrinsic
            ret_type = self._intrinsic_return_type(expr.name)
            return HIntrinsicCall(name=expr.name, args=args, type_ref=ret_type)

        elif isinstance(expr, StructLiteral):
            fields = [(name, self._translate_expr(val)) for name, val in expr.fields]
            return HStructLiteral(
                type_name=expr.type_name, fields=fields,
                type_ref=TypeRef(expr.type_name)
            )

        elif isinstance(expr, UnionLiteral):
            payload = self._translate_expr(expr.payload) if expr.payload is not None else None
            return HUnionLiteral(
                union_name=expr.union_name,
                variant_name=expr.variant_name,
                payload=payload,
                type_ref=TypeRef(expr.union_name)
            )

        elif isinstance(expr, EnumVariantAccess):
            return HEnumVariantAccess(
                enum_name=expr.enum_name,
                variant_name=expr.variant_name,
                type_ref=TypeRef(expr.enum_name)
            )

        elif isinstance(expr, IfExpr):
            cond = self._translate_expr(expr.cond)
            then_branch = self._translate_expr(expr.then_branch)
            else_branch = self._translate_expr(expr.else_branch)
            # Tipe if-expr = tipe then branch (asumsi then dan else sama tipe)
            return HIfExpr(
                cond=cond, then_branch=then_branch, else_branch=else_branch,
                type_ref=then_branch.type_ref
            )

        elif isinstance(expr, ArrayLiteral):
            # Size dan element type eksplisit dari literal ([N]T{...}) --
            # jumlah elemen wajib persis sama dengan N. Stage0 tidak
            # mendukung auto-fill/padding sisa slot dengan default value;
            # mismatch adalah compile error.
            if len(expr.elements) != expr.size:
                raise TypeCheckError(
                    f"Jumlah elemen array tidak cocok: dideklarasikan "
                    f"[{expr.size}]{expr.element_type}, tapi diberikan "
                    f"{len(expr.elements)} elemen"
                )
            elements = [self._translate_expr(e) for e in expr.elements]
            array_type = f"[{expr.size}]{expr.element_type}"
            return HArrayLiteral(
                elements=elements,
                type_ref=TypeRef(array_type)
            )

        elif isinstance(expr, ArrayIndex):
            obj = self._translate_expr(expr.obj)
            index = self._translate_expr(expr.index)
            # Tipe hasil = tipe elemen array
            elem_type = self._array_element_type(obj.type_ref.name)
            if elem_type is None:
                raise TypeCheckError(
                    f"Indexing pada non-array type: {obj.type_ref.name}"
                )
            return HArrayIndex(
                obj=obj, index=index,
                type_ref=TypeRef(elem_type)
            )

        elif isinstance(expr, DottedAccess):
            return self._resolve_dotted_access(expr)

        elif isinstance(expr, DottedCall):
            return self._resolve_dotted_call(expr)

        else:
            raise TypeCheckError(f"Ekspresi AST tidak dikenal: {type(expr).__name__}")

    def _infer_field_type(self, obj: HExpr, field: str) -> TypeRef:
        """Infer tipe field dari struct definition."""
        # Coba dapatkan nama struct dari obj
        struct_name = None
        if isinstance(obj, HIdent):
            if obj.name == "self" and self.current_struct_name:
                struct_name = self.current_struct_name
            elif obj.name in self.local_types:
                struct_name = self.local_types[obj.name]
        elif isinstance(obj, HFieldAccess):
            # Chain: a.b.c -- belum support di stage0
            pass

        if struct_name and struct_name in self.table.struct_fields:
            field_info = self.table.struct_fields[struct_name].get(field)
            if field_info:
                return TypeRef(field_info[0])
        return TypeRef("void")

    def _intrinsic_return_type(self, name: str) -> TypeRef:
        """Infer return type dari intrinsic name."""
        if name in ("print_u8", "print_u16", "print_u32", "print_u64",
                    "print_i8", "print_i16", "print_i32", "print_i64",
                    "print_f32", "print_f64", "print_bool", "print_string",
                    "assert"):
            return TypeRef("void")
        elif name == "byte_len":
            return TypeRef("usize")
        elif name in ("as_bytes", "slice_bytes"):
            return TypeRef("[]u8")
        elif name == "byte_at":
            return TypeRef("u8")
        elif name == "len":
            return TypeRef("usize")
        return TypeRef("void")

    # --- Resolution: DottedAccess -> HFieldAccess / HUnionLiteral / HEnumVariantAccess

    def _resolve_dotted_access(self, node: DottedAccess) -> HExpr:
        """Resolve DottedAccess (tanpa kurung)."""
        base_name = node.base.name if isinstance(node.base, Ident) else None

        # 1. Union -- unit variant
        if base_name is not None and base_name in self.table.union_names:
            known = self.table.union_variants.get(base_name, set())
            if node.name not in known:
                raise TypeCheckError(
                    f"'{node.name}' bukan variant di union '{base_name}' "
                    f"(yang ada: {sorted(known)})"
                )
            return HUnionLiteral(
                union_name=base_name, variant_name=node.name, payload=None,
                type_ref=TypeRef(base_name)
            )

        # 2. Enum -- variant access
        if base_name is not None and base_name in self.table.enum_names:
            known = self.table.enum_variants.get(base_name, set())
            if node.name not in known:
                raise TypeCheckError(
                    f"'{node.name}' bukan variant di enum '{base_name}' "
                    f"(yang ada: {sorted(known)})"
                )
            return HEnumVariantAccess(
                enum_name=base_name, variant_name=node.name,
                type_ref=TypeRef(base_name)
            )

        # 3. Instance/variable -- field access
        base_expr = self._translate_expr(node.base)
        field_type = self._infer_field_type(base_expr, node.name)
        return HFieldAccess(obj=base_expr, field=node.name, type_ref=field_type)

    # --- Resolution: DottedCall -> HMethodCall / HUnionLiteral

    def _resolve_dotted_call(self, node: DottedCall) -> HExpr:
        """Resolve DottedCall (dengan kurung)."""
        base_name = node.base.name if isinstance(node.base, Ident) else None

        # 1. Union -- variant dengan payload
        if base_name is not None and base_name in self.table.union_names:
            known = self.table.union_variants.get(base_name, set())
            if node.name not in known:
                raise TypeCheckError(
                    f"'{node.name}' bukan variant di union '{base_name}' "
                    f"(yang ada: {sorted(known)})"
                )
            if len(node.args) > 1:
                raise TypeCheckError(
                    f"Union '{base_name}.{node.name}' dipanggil dengan {len(node.args)} "
                    f"argumen, stage0 hanya support 1 payload."
                )
            payload = self._translate_expr(node.args[0]) if len(node.args) == 1 else None
            return HUnionLiteral(
                union_name=base_name, variant_name=node.name, payload=payload,
                type_ref=TypeRef(base_name)
            )

        # 2. Enum -- error (enum tidak punya payload)
        if base_name is not None and base_name in self.table.enum_names:
            raise TypeCheckError(
                f"'{base_name}.{node.name}(...)' tidak valid -- '{base_name}' "
                f"adalah enum, enum variant tidak punya payload."
            )

        # 3. Instance/variable -- method call
        base_expr = self._translate_expr(node.base)
        args = [self._translate_expr(a) for a in node.args]

        # Infer struct_name
        struct_name = self.current_struct_name
        if base_name is not None:
            if base_name == "self" and self.current_struct_name:
                struct_name = self.current_struct_name
            elif base_name in self.local_types:
                struct_name = self.local_types[base_name]

        if struct_name is None:
            raise TypeCheckError(
                f"MethodCall '{node.name}' tidak bisa infer struct_name -- "
                f"tipe objek '{base_name}' tidak diketahui."
            )

        return HMethodCall(
            obj=base_expr, method=node.name, args=args,
            struct_name=struct_name, type_ref=TypeRef("void")
        )

    # --- Translation: Statements ---

    def _translate_stmt(self, stmt: Stmt) -> HStmt:
        """Translate AST Stmt -> HIR HStmt."""
        if isinstance(stmt, ReturnStmt):
            return HReturnStmt(expr=self._translate_expr(stmt.expr))

        elif isinstance(stmt, IfStmt):
            cond = self._translate_expr(stmt.cond)
            body = [self._translate_stmt(s) for s in stmt.body]
            elifs = [HElifClause(
                cond=self._translate_expr(e.cond),
                body=[self._translate_stmt(s) for s in e.body]
            ) for e in stmt.elifs]
            else_body = [self._translate_stmt(s) for s in stmt.else_body]
            return HIfStmt(cond=cond, body=body, elifs=elifs, else_body=else_body)

        elif isinstance(stmt, WhileStmt):
            cond = self._translate_expr(stmt.cond)
            body = [self._translate_stmt(s) for s in stmt.body]
            return HWhileStmt(cond=cond, body=body)

        elif isinstance(stmt, AssignStmt):
            target = self._translate_expr(stmt.target)
            value = self._translate_expr(stmt.value)
            return HAssignStmt(target=target, value=value, op=stmt.op)

        elif isinstance(stmt, ExprStmt):
            return HExprStmt(expr=self._translate_expr(stmt.expr))

        elif isinstance(stmt, LetStmt):
            # Infer tipe dari anotasi atau dari value
            type_name = stmt.type_name
            if type_name is None and isinstance(stmt.value, StructLiteral):
                type_name = stmt.value.type_name
            # Jika masih None, coba infer dari value expression
            if type_name is None:
                type_name = self._infer_expr_type(stmt.value).name

            type_ref = self._type_ref(type_name)
            value = self._translate_expr(stmt.value)

            # Track local type
            self.local_types[stmt.name] = type_name

            return HLetStmt(
                name=stmt.name, value=value, type_ref=type_ref, is_mut=stmt.is_mut
            )

        elif isinstance(stmt, MatchStmt):
            return self._translate_match_stmt(stmt)

        elif isinstance(stmt, ForInStmt):
            return self._translate_forin_stmt(stmt)

        elif isinstance(stmt, ContinueStmt):
            return HContinueStmt()

        elif isinstance(stmt, BreakStmt):
            return HBreakStmt()

        else:
            raise TypeCheckError(f"Statement AST tidak dikenal: {type(stmt).__name__}")

    def _translate_forin_stmt(self, stmt: ForInStmt) -> HForInStmt:
        """Translate ForInStmt -> HForInStmt dengan infer element type."""
        iterable = self._translate_expr(stmt.iterable)

        # Infer element type dari iterable
        elem_type = self._array_element_type(iterable.type_ref.name)
        if elem_type is None:
            raise TypeCheckError(
                f"for-in loop pada non-iterable type: {iterable.type_ref.name}"
            )

        # Track loop variable
        self.local_types[stmt.var_name] = elem_type

        body = [self._translate_stmt(s) for s in stmt.body]

        return HForInStmt(
            var_name=stmt.var_name,
            iterable=iterable,
            body=body,
            var_type=TypeRef(elem_type)
        )

    def _translate_match_stmt(self, stmt: MatchStmt) -> HMatchStmt:
        """Translate MatchStmt dengan attach metadata semantik."""
        expr = self._translate_expr(stmt.expr)

        if not stmt.arms:
            raise TypeCheckError("Match statement tidak punya arm.")

        # Derive union_name dari arm pertama
        first_arm = stmt.arms[0]
        union_name = first_arm.union
        if union_name is None:
            raise TypeCheckError(
                "Match arm harus explicit Union.Variant -- stage0 memerlukan format ini."
            )

        # Validasi semua arm dari union yang sama
        for arm in stmt.arms:
            if arm.union != union_name:
                raise TypeCheckError(
                    f"Arm '{arm.union}.{arm.variant}' tidak konsisten -- "
                    f"semua arm harus dari union '{union_name}'."
                )
            known = self.table.union_variants.get(union_name, set())
            if arm.variant not in known:
                raise TypeCheckError(
                    f"'{arm.variant}' bukan variant di union '{union_name}' "
                    f"(yang ada: {sorted(known)})"
                )

        # Translate arms dengan bind_type
        payload_types = self.table.union_payload_types.get(union_name, {})
        hir_arms = []
        for arm in stmt.arms:
            bind_type = None
            if arm.bind is not None:
                payload_type = payload_types.get(arm.variant)
                if payload_type is None:
                    raise TypeCheckError(
                        f"Arm '{union_name}.{arm.variant}' punya binding '{arm.bind}', "
                        f"tapi variant ini tidak punya payload."
                    )
                bind_type = TypeRef(payload_type)

            guard = self._translate_expr(arm.guard) if arm.guard is not None else None
            body = [self._translate_stmt(s) for s in arm.body]

            hir_arms.append(HMatchArm(
                variant=arm.variant, body=body, union_name=union_name,
                bind=arm.bind, bind_type=bind_type, guard=guard
            ))

        return HMatchStmt(expr=expr, arms=hir_arms, union_name=union_name)

    # --- Translation: Top-level Declarations ---

    def translate_decl(self, decl) -> HDecl:
        """Translate AST top-level declaration -> HIR HDecl."""
        if isinstance(decl, EnumDecl):
            return HEnumDecl(name=decl.name, variants=decl.variants)

        elif isinstance(decl, StructDecl):
            fields = [
                HStructField(name=f.name, type_ref=TypeRef(f.type_name), is_mut=f.is_mut)
                for f in decl.fields
            ]
            methods = [self.translate_decl(m) for m in decl.methods]
            return HStructDecl(name=decl.name, fields=fields, methods=methods)

        elif isinstance(decl, UnionDecl):
            variants = [
                HUnionVariant(
                    name=v.name,
                    payload_type=TypeRef(v.payload_types[0]) if v.payload_types else None
                )
                for v in decl.variants
            ]
            return HUnionDecl(name=decl.name, variants=variants)

        elif isinstance(decl, FnDecl):
            return self._translate_fn_decl(decl)

        else:
            raise TypeCheckError(f"Deklarasi AST tidak dikenal: {type(decl).__name__}")

    def _translate_fn_decl(self, decl: FnDecl) -> HFnDecl:
        """Translate FnDecl -> HFnDecl."""
        old_struct = self.current_struct_name
        old_locals = self.local_types.copy()

        self.current_struct_name = decl.struct_name
        self.local_types = {}

        # Translate params
        params = []
        for p in decl.params:
            params.append(HParam(name=p.name, type_ref=TypeRef(p.type_name)))
            self.local_types[p.name] = p.type_name

        # Translate self_param
        self_param = None
        if decl.self_param is not None:
            self_param = HSelfParam(
                is_mut=decl.self_param.is_mut,
                is_ref=decl.self_param.is_ref
            )
            if decl.struct_name:
                self.local_types["self"] = decl.struct_name

        # Translate body
        body = [self._translate_stmt(s) for s in decl.body]

        result = HFnDecl(
            name=decl.name,
            params=params,
            return_type=TypeRef(decl.return_type),
            body=body,
            is_internal=decl.is_internal,
            self_param=self_param,
            struct_name=decl.struct_name,
        )

        self.current_struct_name = old_struct
        self.local_types = old_locals
        return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def check_program(decls: list) -> list[HDecl]:
    """
    Entry point: AST -> HIR.

    Args:
        decls: List of AST nodes dari parser (raw)

    Returns:
        list[HDecl]: HIR yang sudah resolved, typed, dan lengkap metadata
    """
    table = SymbolTable.build(decls)
    builder = HIRBuilder(table)
    return [builder.translate_decl(d) for d in decls]
