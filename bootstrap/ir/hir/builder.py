# ir/hir/builder.py
"""
HIRBuilder -- AST -> HIR Translator.

Tanggung jawab TUNGGAL modul ini:
    1. Terima AST "raw" (pure syntax) dari parser
    2. Buat HIR "final" (resolved + typed) yang baru
    3. TIDAK mutasi AST -- AST tetap immutable setelah parse
"""
from __future__ import annotations

from nala_ast import (
    # Declarations
    EnumDecl, StructDecl, UnionDecl, UnionVariant, StructField,
    FnDecl, Param, SelfParam,
    # Expressions
    Expr, Ident, StringLiteral, IntLiteral, FloatLiteral, BoolLiteral, ByteLiteral,
    BinaryExpr, UnaryExpr, CallExpr, FieldAccess, MethodCall,
    IntrinsicCall, StructLiteral, UnionLiteral, EnumVariantAccess,
    IfExpr, DottedAccess, DottedCall,
    ArrayLiteral, ArrayIndex,
    # Statements
    Stmt, ReturnStmt, IfStmt, WhileStmt, ForInStmt, AssignStmt, ExprStmt,
    LetStmt, MatchStmt, MatchArm, ElifClause, ContinueStmt, BreakStmt, DeferStmt,
)

from ir.hir.nodes import (
    # Type
    TypeRef,
    # Expressions
    HIdent, HStringLiteral, HIntLiteral, HFloatLiteral, HBoolLiteral, HByteLiteral,
    HFieldAccess, HBinaryExpr, HUnaryExpr, HCallExpr,
    HMethodCall, HIntrinsicCall, HStructLiteral, HUnionLiteral,
    HEnumVariantAccess, HIfExpr,
    HArrayLiteral, HArrayIndex,
    HExpr,
    # Statements
    HParam, HSelfParam, HReturnStmt, HIfStmt, HWhileStmt, HForInStmt,
    HAssignStmt, HExprStmt, HLetStmt, HMatchStmt, HMatchArm,
    HElifClause, HContinueStmt, HBreakStmt, HDeferStmt,
    HStmt,
    # Declarations
    HEnumDecl, HStructDecl, HStructField, HUnionDecl, HUnionVariant,
    HFnDecl,
    HDecl,
)

from checker.symbol_table import SymbolTable, TypeCheckError
from checker.inference import (
    infer_expr_type, infer_field_type, intrinsic_return_type,
)
from checker.type_compat import (
    parse_type_kind, types_compatible, is_integer_type_name, is_float_type_name,
)

class HIRBuilder:
    """
    Builder untuk menerjemahkan AST -> HIR.

    State:
        - table: SymbolTable untuk lookup top-level declarations
        - local_types: dict[str, str] -- tipe variabel lokal (nama -> type_name)
        - current_struct_name: str | None -- struct yang sedang diproses (untuk self)
        - current_module: str | None -- module yang sedang diproses (untuk use alias)
    """

    def __init__(self, table: SymbolTable, current_module: str | None = None) -> None:
        self.table = table
        self.local_types: dict[str, str] = {}
        self.current_struct_name: str | None = None
        self.current_module = current_module
        self._defer_nesting_level: int = 0  # 0 = top-level fn body, >0 = nested block

    # --- Helper: TypeRef ---

    def _type_ref(self, type_name: str | None) -> TypeRef:
        """Buat TypeRef dari nama tipe (fallback ke 'void' kalau None)."""
        return TypeRef(type_name if type_name is not None else "void")

    def _array_element_type(self, type_name: str) -> str | None:
        """Dapatkan tipe elemen dari [N]T, atau None -- via parse_type_kind."""
        from checker.type_compat import ArrayKind, PrimitiveKind, NamedKind
        kind = parse_type_kind(type_name)
        if isinstance(kind, ArrayKind):
            elem = kind.element
            if isinstance(elem, PrimitiveKind):
                return elem.name
            if isinstance(elem, NamedKind):
                return elem.name
        return None

    def _infer_expr_type(self, expr: Expr) -> TypeRef:
        return infer_expr_type(
            expr, self.table, self.local_types, self.current_struct_name
        )

    def _check_assignable(self, expected_type_name: str, actual: HExpr, context: str) -> None:
        """
        Verifikasi actual.type_ref cocok dengan expected_type_name.

        Raise TypeCheckError kalau tidak cocok. `context` adalah deskripsi
        singkat untuk pesan error (mis. "let x", "argumen ke-1 fungsi foo").

        Kalau salah satu sisi gagal di-parse jadi TypeKind (UnknownKind),
        pengecekan di-skip -- ini kemungkinan besar limitasi parser
        type_name stage0 (mis. tipe generic yang belum didukung), bukan
        kesalahan program yang sebenarnya. Lebih aman skip daripada false
        positive yang menghalangi kode yang sebenarnya benar.
        """
        expected_kind = parse_type_kind(expected_type_name)
        actual_kind = parse_type_kind(actual.type_ref.name)

        from checker.type_compat import UnknownKind
        if isinstance(expected_kind, UnknownKind) or isinstance(actual_kind, UnknownKind):
            return

        if not types_compatible(expected_kind, actual_kind):
            raise TypeCheckError(
                f"Type mismatch di {context}: diharapkan '{expected_type_name}', "
                f"tapi ketemu '{actual.type_ref.name}'"
            )

    def _resolve_dotted_type(self, type_name: str) -> TypeRef:
        """Resolve module-qualified type name to unqualified TypeRef."""
        if '.' not in type_name:
            return TypeRef(type_name)
        
        resolved = self.table.resolve_qualified_name(self.current_module, type_name)
        if resolved is None:
            # Maybe it's a fully qualified std type?
            if type_name.startswith("std."):
                # Strip std. prefix, use the last part
                return TypeRef(type_name.split('.')[-1])
            raise TypeCheckError(f"Unable to resolve qualified type: {type_name}")
        
        module_name, item_name = resolved
        decl = self.table.find_item_in_module(module_name, item_name)
        if decl is None:
            raise TypeCheckError(f"Item '{item_name}' not found in module '{module_name}'")
        # Return unqualified name for codegen
        return TypeRef(item_name)

    def _translate_method_args_and_return(
        self, struct_name: str, method_name: str, raw_args: list[Expr]
    ) -> tuple[list[HExpr], TypeRef]:
        """
        Translate argumen method call + tentukan return type dari
        method_signatures. Dipakai oleh dua titik resolusi method call
        (_translate_expr utk MethodCall dan _resolve_dotted_call) supaya
        keduanya konsisten -- sebelumnya masing-masing hardcode
        TypeRef("void") secara terpisah, itu akar bug yang diperbaiki di sini.

        Kalau signature method tidak ditemukan (mis. dipanggil pada objek
        yang struct_name-nya tidak dikenal SymbolTable), fallback: translate
        args tanpa expected_type, return type "void" -- sama seperti
        fallback yang sudah ada untuk top-level CallExpr yang tidak dikenal.
        """
        sig = self.table.method_signatures.get((struct_name, method_name))
        if sig is not None:
            param_types, return_type = sig
            if len(raw_args) != len(param_types):
                raise TypeCheckError(
                    f"Pemanggilan method '{struct_name}.{method_name}' dengan "
                    f"{len(raw_args)} argumen, tapi method ini butuh "
                    f"{len(param_types)} parameter"
                )
            args = [
                self._translate_expr(a, expected_type=pt)
                for a, pt in zip(raw_args, param_types)
            ]
            for i, (arg, param_type) in enumerate(zip(args, param_types)):
                self._check_assignable(
                    param_type, arg,
                    context=(
                        f"argumen ke-{i + 1} pemanggilan method "
                        f"'{struct_name}.{method_name}'"
                    )
                )
            return args, TypeRef(return_type)
        else:
            args = [self._translate_expr(a) for a in raw_args]
            return args, TypeRef("void")

    # --- Translation: Expressions ---

    def _translate_expr(self, expr: Expr, expected_type: str | None = None) -> HExpr:
        """
        Translate AST Expr -> HIR HExpr.

        Args:
            expr: ekspresi AST yang mau ditranslate
            expected_type: tipe yang diharapkan dari context pemanggil
                (mis. anotasi `let`, tipe parameter fungsi). HANYA dipakai
                untuk resolve literal numerik (IntLiteral/FloatLiteral) --
                lihat catatan di inference.infer_expr_type(). Sengaja TIDAK
                diturunkan ke sub-ekspresi manapun kecuali dijelaskan
                eksplisit (mis. tidak diturunkan ke operand BinaryExpr),
                supaya scope pengaruhnya tetap jelas dan mudah ditelusuri.
        """
        if isinstance(expr, Ident):
            type_name = self.local_types.get(expr.name)
            if type_name is None and expr.name == "self" and self.current_struct_name:
                type_name = self.current_struct_name
            return HIdent(name=expr.name, type_ref=self._type_ref(type_name))

        elif isinstance(expr, StringLiteral):
            return HStringLiteral(value=expr.value)

        elif isinstance(expr, IntLiteral):
            # Kalau context minta tipe integer spesifik, literal ini
            # benar-benar "jadi" tipe itu di HIR -- bukan selalu i32.
            # Lihat inference.infer_expr_type() untuk penjelasan lebih
            # lengkap kenapa ini perlu (tanpa ini, `let x: i64 = 10`
            # false-positive gagal type check meski programnya benar).
            if expected_type is not None and is_integer_type_name(expected_type):
                return HIntLiteral(value=expr.value, type_ref=TypeRef(expected_type))
            return HIntLiteral(value=expr.value)

        elif isinstance(expr, FloatLiteral):
            if expected_type is not None and is_float_type_name(expected_type):
                return HFloatLiteral(value=expr.value, type_ref=TypeRef(expected_type))
            return HFloatLiteral(value=expr.value)

        elif isinstance(expr, ByteLiteral):
            return HByteLiteral(value=expr.value)

        elif isinstance(expr, BoolLiteral):
            return HBoolLiteral(value=expr.value)

        elif isinstance(expr, BinaryExpr):
            _ARITHMETIC_OPS = ("+", "-", "*", "/", "%")
            _COMPARISON_OPS = ("==", "!=", ">", "<", ">=", "<=")
            _LOGICAL_OPS = ("and", "or")

            if expr.op in _ARITHMETIC_OPS:
                # Context-aware DUA ARAH -- literal boleh ada di kiri
                # (`0 + b`) maupun kanan (`a + 5`), dan literal itu harus
                # ikut tipe operand lawannya, bukan cuma satu arah.
                #
                # Strategi: translate kedua sisi dulu TANPA context, lalu
                # deteksi mana yang literal AST-nya (IntLiteral/FloatLiteral)
                # dan mana yang bukan. Kalau salah satu literal & satunya
                # bukan, re-translate sisi literal itu dengan expected_type
                # dari sisi non-literal. Kalau keduanya literal atau
                # keduanya bukan literal, tidak ada context untuk
                # "dipinjam" -- biarkan default masing-masing, lalu
                # _check_assignable yang akan menegur kalau memang beda.
                left_is_literal = isinstance(expr.left, (IntLiteral, FloatLiteral))
                right_is_literal = isinstance(expr.right, (IntLiteral, FloatLiteral))

                left = self._translate_expr(expr.left)
                right = self._translate_expr(expr.right)

                if left_is_literal and not right_is_literal:
                    left = self._translate_expr(expr.left, expected_type=right.type_ref.name)
                elif right_is_literal and not left_is_literal:
                    right = self._translate_expr(expr.right, expected_type=left.type_ref.name)

                self._check_assignable(
                    left.type_ref.name, right,
                    context=f"operand kanan '{expr.op}'"
                )
                result_type = left.type_ref
            elif expr.op in _COMPARISON_OPS or expr.op in _LOGICAL_OPS:
                left = self._translate_expr(expr.left)
                right = self._translate_expr(expr.right)
                result_type = TypeRef("bool")
            else:
                left = self._translate_expr(expr.left)
                right = self._translate_expr(expr.right)
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
            # Lookup signature DULU (sebelum translate args) -- supaya tiap
            # argumen bisa di-translate dengan expected_type dari parameter
            # yang bersangkutan (penting untuk literal numerik context-aware,
            # mis. f(10) ke parameter i64 harus bikin `10` benar-benar
            # ber-type_ref i64, bukan i32 default).
            sig = self.table.fn_signatures.get(expr.callee)
            if sig is not None:
                param_types, return_type = sig
                if len(expr.args) != len(param_types):
                    raise TypeCheckError(
                        f"Pemanggilan '{expr.callee}' dengan {len(expr.args)} argumen, "
                        f"tapi fungsi ini butuh {len(param_types)} parameter"
                    )
                args = [
                    self._translate_expr(a, expected_type=pt)
                    for a, pt in zip(expr.args, param_types)
                ]
                for i, (arg, param_type) in enumerate(zip(args, param_types)):
                    self._check_assignable(
                        param_type, arg,
                        context=f"argumen ke-{i + 1} pemanggilan '{expr.callee}'"
                    )
                return_type_ref = TypeRef(return_type)
            else:
                # Fungsi tidak dikenal (mis. belum ter-collect dari file
                # lain) -- translate args tanpa expected_type, fallback
                # return type ke void.
                args = [self._translate_expr(a) for a in expr.args]
                return_type_ref = TypeRef("void")
            return HCallExpr(callee=expr.callee, args=args, type_ref=return_type_ref)

        elif isinstance(expr, FieldAccess):
            obj = self._translate_expr(expr.obj)
            # Coba infer tipe field dari struct definition
            field_type = self._infer_field_type(obj, expr.field)
            return HFieldAccess(obj=obj, field=expr.field, type_ref=field_type)

        elif isinstance(expr, MethodCall):
            obj = self._translate_expr(expr.obj)
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
            args, return_type_ref = self._translate_method_args_and_return(
                struct_name, expr.method, expr.args
            )
            return HMethodCall(
                obj=obj, method=expr.method, args=args,
                struct_name=struct_name, type_ref=return_type_ref
            )

        elif isinstance(expr, IntrinsicCall):
            # assert_eq! (dan sejenisnya yang membandingkan 2 nilai)
            # butuh context-aware dua arah antar argumennya sendiri --
            # kalau salah satu literal (mis. `assert_eq!(float_var, 3.14)`),
            # literal itu harus ikut tipe argumen lawannya. Tanpa ini,
            # 3.14 selalu di-generate sbg C double, sementara float_var
            # adalah C float -- dua representasi biner beda meski nilai
            # "keliatan" sama, bikin assert_eq! false-negative.
            #
            # Ini SENGAJA khusus utk assert_eq/assert_ne (2 argumen yang
            # memang harus dibandingkan setara) -- TIDAK digeneralisasi ke
            # semua IntrinsicCall, karena intrinsic lain (mis. slice_bytes)
            # argumennya punya makna berbeda-beda, bukan pasangan yg harus
            # setipe.
            _PAIRWISE_COMPARE_INTRINSICS = ("assert_eq", "assert_ne")

            if expr.name in _PAIRWISE_COMPARE_INTRINSICS and len(expr.args) == 2:
                left_ast, right_ast = expr.args[0], expr.args[1]
                left_is_literal = isinstance(left_ast, (IntLiteral, FloatLiteral))
                right_is_literal = isinstance(right_ast, (IntLiteral, FloatLiteral))

                left = self._translate_expr(left_ast)
                right = self._translate_expr(right_ast)

                if left_is_literal and not right_is_literal:
                    left = self._translate_expr(left_ast, expected_type=right.type_ref.name)
                elif right_is_literal and not left_is_literal:
                    right = self._translate_expr(right_ast, expected_type=left.type_ref.name)

                args = [left, right]
            else:
                args = [self._translate_expr(a) for a in expr.args]

            # Infer return type dari nama intrinsic
            ret_type = intrinsic_return_type(expr.name)
            return HIntrinsicCall(name=expr.name, args=args, type_ref=ret_type)

        elif isinstance(expr, StructLiteral):
            # Resolve qualified type name if any
            type_name = expr.type_name
            if '.' in type_name:
                resolved_type = self._resolve_dotted_type(type_name)
                type_name = resolved_type.name
            fields = [(name, self._translate_expr(val)) for name, val in expr.fields]
            return HStructLiteral(
                type_name=type_name, fields=fields,
                type_ref=TypeRef(type_name)
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
        return infer_field_type(
            obj, field, self.table, self.local_types, self.current_struct_name
        )

    # --- Resolution: DottedAccess -> HFieldAccess / HUnionLiteral / HEnumVariantAccess

    def _flatten_dotted(self, node) -> list[str]:
        """Flatten nested DottedAccess/DottedCall into list of parts."""
        if isinstance(node, Ident):
            return [node.name]
        elif isinstance(node, DottedAccess):
            return self._flatten_dotted(node.base) + [node.name]
        else:
            raise TypeCheckError(f"Invalid dotted expression: {type(node).__name__}")

    def _resolve_module_item(self, module_name: str, item_name: str, is_call: bool, args: list = None) -> HExpr:
        """Resolve an item from a specific module."""
        if args is None:
            args = []

        # Try as top-level decl
        item = self.table.find_item_in_module(module_name, item_name)
        if item is not None:
            if isinstance(item, FnDecl):
                if not is_call:
                    raise TypeCheckError(f"Function '{item_name}' must be called")
                sig = self.table.fn_signatures.get(item_name)
                if sig is not None:
                    param_types, return_type = sig
                    if len(args) != len(param_types):
                        raise TypeCheckError(
                            f"Pemanggilan '{item_name}' dengan {len(args)} argumen, "
                            f"tapi fungsi ini butuh {len(param_types)} parameter"
                        )
                    hir_args = [
                        self._translate_expr(a, expected_type=pt)
                        for a, pt in zip(args, param_types)
                    ]
                    for i, (arg, pt) in enumerate(zip(hir_args, param_types)):
                        self._check_assignable(
                            pt, arg,
                            context=f"argumen ke-{i + 1} pemanggilan '{item_name}'"
                        )
                    return HCallExpr(callee=item_name, args=hir_args, type_ref=TypeRef(return_type))
                else:
                    hir_args = [self._translate_expr(a) for a in args]
                    return HCallExpr(callee=item_name, args=hir_args, type_ref=TypeRef("void"))

        # Try as union/enum variant
        variant_info = self.table.find_variant_in_module(module_name, item_name)
        if variant_info is not None:
            kind, type_name, variant = variant_info
            if kind == "union":
                if is_call:
                    payload_types = getattr(variant, "payload_types", [])
                    if payload_types:
                        if len(args) != 1:
                            raise TypeCheckError(
                                f"Union variant '{item_name}' expects 1 payload"
                            )
                        payload = self._translate_expr(args[0], expected_type=payload_types[0])
                        self._check_assignable(
                            payload_types[0], payload,
                            context=f"payload of '{item_name}'"
                        )
                    else:
                        if args:
                            raise TypeCheckError(
                                f"Union variant '{item_name}' is unit variant"
                            )
                        payload = None
                    return HUnionLiteral(
                        union_name=type_name, variant_name=item_name, payload=payload,
                        type_ref=TypeRef(type_name)
                    )
                else:
                    return HUnionLiteral(
                        union_name=type_name, variant_name=item_name, payload=None,
                        type_ref=TypeRef(type_name)
                    )
            elif kind == "enum":
                if is_call:
                    raise TypeCheckError(f"Enum variant '{item_name}' doesn't have payload")
                return HEnumVariantAccess(
                    enum_name=type_name, variant_name=item_name,
                    type_ref=TypeRef(type_name)
                )

        raise TypeCheckError(f"'{item_name}' not found in module '{module_name}'")

    def _resolve_dotted_access(self, node: DottedAccess) -> HExpr:
        """Resolve DottedAccess (tanpa kurung)."""
        parts = self._flatten_dotted(node)
        base_name = parts[0]

        # Case A: Module alias (local.* via use) — alias.item
        if self.current_module and len(parts) == 2:
            target_module = self.table.resolve_alias(self.current_module, base_name)
            if target_module is not None:
                return self._resolve_module_item(target_module, parts[1], is_call=False)

        # Case B: std.* fully qualified path (2+ parts)
        if base_name == "std":
            if len(parts) < 2:
                raise TypeCheckError("std module name cannot be used alone")
            # Use resolve_qualified_name
            qualified = ".".join(parts)
            resolved = self.table.resolve_qualified_name(self.current_module, qualified)
            if resolved is None:
                raise TypeCheckError(f"Unable to resolve std path: {qualified}")
            module_name, item_name = resolved
            # For stage0, only support function calls via DottedCall
            raise TypeCheckError(
                f"std.{item_name} must be called with parentheses (function) "
                f"or used as a type (not yet supported in stage0)"
            )

        # Case C: 2-part — reuse existing logic
        if len(parts) == 2:
            # Union -- unit variant
            if base_name in self.table.union_names:
                known = self.table.union_variants.get(base_name, set())
                if parts[1] in known:
                    return HUnionLiteral(
                        union_name=base_name, variant_name=parts[1], payload=None,
                        type_ref=TypeRef(base_name)
                    )
            # Enum -- variant access
            if base_name in self.table.enum_names:
                known = self.table.enum_variants.get(base_name, set())
                if parts[1] in known:
                    return HEnumVariantAccess(
                        enum_name=base_name, variant_name=parts[1],
                        type_ref=TypeRef(base_name)
                    )
            # Instance/variable -- field access
            base_expr = self._translate_expr(Ident(base_name))
            field_type = self._infer_field_type(base_expr, parts[1])
            return HFieldAccess(obj=base_expr, field=parts[1], type_ref=field_type)

        raise TypeCheckError(f"Cannot resolve dotted access: {'.'.join(parts)}")

    def _resolve_dotted_call(self, node: DottedCall) -> HExpr:
        """Resolve DottedCall (dengan kurung)."""
        parts = self._flatten_dotted(node.base) + [node.name]
        base_name = parts[0]

        # Case A: Module alias (local.* via use) — alias.item(args)
        if self.current_module and len(parts) == 2:
            target_module = self.table.resolve_alias(self.current_module, base_name)
            if target_module is not None:
                return self._resolve_module_item(target_module, parts[1], is_call=True, args=node.args)

        # Case B: std.* fully qualified path (2+ parts: std.print, std.mem.copy)
        if base_name == "std":
            if len(parts) < 2:
                raise TypeCheckError("std module name cannot be used alone")
            qualified = ".".join(parts)
            resolved = self.table.resolve_qualified_name(self.current_module, qualified)
            if resolved is None:
                raise TypeCheckError(f"Unable to resolve std path: {qualified}")
            module_name, item_name = resolved
            # Look up function declaration in that module
            decl = self.table.find_item_in_module(module_name, item_name)
            if decl is None:
                raise TypeCheckError(f"Function '{item_name}' not found in std module '{module_name}'")
            # It must be a FnDecl
            if not isinstance(decl, FnDecl):
                raise TypeCheckError(f"'{item_name}' in std module '{module_name}' is not a function")
            # Get signature from table (already built)
            sig = self.table.fn_signatures.get(item_name)
            if sig is None:
                raise TypeCheckError(f"Function '{item_name}' not found in signatures")
            param_types, return_type = sig
            if len(node.args) != len(param_types):
                raise TypeCheckError(
                    f"Pemanggilan '{item_name}' dengan {len(node.args)} argumen, "
                    f"tapi fungsi ini butuh {len(param_types)} parameter"
                )
            args = [
                self._translate_expr(a, expected_type=pt)
                for a, pt in zip(node.args, param_types)
            ]
            for i, (arg, pt) in enumerate(zip(args, param_types)):
                self._check_assignable(
                    pt, arg,
                    context=f"argumen ke-{i + 1} pemanggilan '{item_name}'"
                )
            return HCallExpr(callee=item_name, args=args, type_ref=TypeRef(return_type))

        # Case C: 2-part base.name(args) — reuse existing logic
        if len(parts) == 2:
            actual_base = parts[0]
            name = parts[1]
            # Union -- variant dengan payload
            if actual_base in self.table.union_names:
                known = self.table.union_variants.get(actual_base, set())
                if name in known:
                    if len(node.args) > 1:
                        raise TypeCheckError(
                            f"Union '{actual_base}.{name}' dipanggil dengan {len(node.args)} "
                            f"argumen, stage0 hanya support 1 payload."
                        )
                    payload = self._translate_expr(node.args[0]) if len(node.args) == 1 else None
                    return HUnionLiteral(
                        union_name=actual_base, variant_name=name, payload=payload,
                        type_ref=TypeRef(actual_base)
                    )
            # Enum -- error
            if actual_base in self.table.enum_names:
                raise TypeCheckError(
                    f"'{actual_base}.{name}(...)' tidak valid -- '{actual_base}' "
                    f"adalah enum, enum variant tidak punya payload."
                )
            # Method call
            base_expr = self._translate_expr(Ident(actual_base))
            struct_name = self.current_struct_name
            if actual_base == "self" and self.current_struct_name:
                struct_name = self.current_struct_name
            elif actual_base in self.local_types:
                struct_name = self.local_types[actual_base]
            if struct_name is None:
                raise TypeCheckError(
                    f"MethodCall '{name}' tidak bisa infer struct_name -- "
                    f"tipe objek '{actual_base}' tidak diketahui."
                )
            args, return_type_ref = self._translate_method_args_and_return(
                struct_name, name, node.args
            )
            return HMethodCall(
                obj=base_expr, method=name, args=args,
                struct_name=struct_name, type_ref=return_type_ref
            )

        raise TypeCheckError(f"Cannot resolve dotted call: {'.'.join(parts)}")

    # --- Translation: Statements ---

    def _translate_stmt(self, stmt: Stmt) -> HStmt:
        """Translate AST Stmt -> HIR HStmt."""
        if isinstance(stmt, ReturnStmt):
            return HReturnStmt(expr=self._translate_expr(stmt.expr))

        elif isinstance(stmt, IfStmt):
            cond = self._translate_expr(stmt.cond)
            self._defer_nesting_level += 1
            body = [self._translate_stmt(s) for s in stmt.body]
            elifs = []
            for e in stmt.elifs:
                e_body = [self._translate_stmt(s) for s in e.body]
                elifs.append(HElifClause(cond=self._translate_expr(e.cond), body=e_body))
            else_body = [self._translate_stmt(s) for s in stmt.else_body]
            self._defer_nesting_level -= 1
            return HIfStmt(cond=cond, body=body, elifs=elifs, else_body=else_body)

        elif isinstance(stmt, WhileStmt):
            cond = self._translate_expr(stmt.cond)
            self._defer_nesting_level += 1
            body = [self._translate_stmt(s) for s in stmt.body]
            self._defer_nesting_level -= 1
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
            if type_name is not None and '.' in type_name:
                resolved_type = self._resolve_dotted_type(type_name)
                type_name = resolved_type.name
            if type_name is None and isinstance(stmt.value, StructLiteral):
                type_name = stmt.value.type_name
            # Jika masih None, coba infer dari value expression
            if type_name is None:
                type_name = self._infer_expr_type(stmt.value).name

            type_ref = self._type_ref(type_name)
            # Translate value with original type_name for context (if any)
            value = self._translate_expr(stmt.value, expected_type=stmt.type_name)

            # Verifikasi kecocokan tipe HANYA kalau ada anotasi eksplisit --
            # kalau type_name di-infer dari value itu sendiri (baris di atas),
            # keduanya otomatis "cocok" secara tautologis, jadi tidak perlu
            # (dan tidak boleh) dicek ulang.
            if stmt.type_name is not None:
                self._check_assignable(
                    stmt.type_name, value, context=f"let '{stmt.name}'"
                )

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

        elif isinstance(stmt, DeferStmt):
            if self._defer_nesting_level > 0:
                raise TypeCheckError(
                    "defer hanya boleh dideklarasikan di top-level function body "
                    "(belum didukung di dalam if/while/for/match)."
                )
            return HDeferStmt(expr=self._translate_expr(stmt.expr))

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

        self._defer_nesting_level += 1
        body = [self._translate_stmt(s) for s in stmt.body]
        self._defer_nesting_level -= 1

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
            self._defer_nesting_level += 1
            body = [self._translate_stmt(s) for s in arm.body]
            self._defer_nesting_level -= 1

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
        old_defer_level = self._defer_nesting_level
        self._defer_nesting_level = 0
        body = [self._translate_stmt(s) for s in decl.body]
        self._defer_nesting_level = old_defer_level

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


def check_program(decls: list) -> list[HDecl]:
    """Entry point: AST -> HIR."""
    table = SymbolTable.build(decls)
    builder = HIRBuilder(table)
    return [builder.translate_decl(d) for d in decls]


def check_program_modules(module_decls: dict[str, list], module_uses: dict[str, list]) -> list[HDecl]:
    """Entry point: multi-module AST -> HIR."""
    table = SymbolTable.build_modules(module_decls, module_uses)
    all_hir = []
    for module_name, decls in module_decls.items():
        builder = HIRBuilder(table, current_module=module_name)
        for d in decls:
            all_hir.append(builder.translate_decl(d))
    return all_hir
