# parser/parser.py
"""
Main parser
"""
from __future__ import annotations
from typing import Optional

from lexer.lexer import Lexer
from lexer.token import (
    Token, TokenKind, Keyword, Operator, Delimiter, Literal, Special,
    KeywordKind, OperatorKind, DelimiterKind, LiteralKind, SpecialKind,
    describe_token_kind,
)

from nala_ast.nodes import (
    TypeExpr, NamedTypeExpr, GenericTypeExpr, ArrayTypeExpr, SliceTypeExpr,
    PointerTypeExpr, ReferenceTypeExpr, SatisfyTypeExpr, FunctionTypeExpr,
    BoundedTypeExpr, IntrinsicTypeExpr, CompilerHint, UseDecl,
    EnumVariantDecl, EnumDecl, SumVariantDecl,
    SumDecl, StructField, StructDecl, TraitMethodDecl, TraitDecl,
    SatisfyDecl, ForeignDecl, FnDecl, Param, SelfParam, TestDecl, Stmt,
)

from parser.expr import ExprParser, ParseError as ExprParseError
from parser.stmt import StmtParser, ParseError as StmtParseError


class ParseError(Exception):
    pass


class Parser(ExprParser, StmtParser):
    """
    Full parser: tokenize entire source up front (simplifies lookahead),
    then recursive-descent over the token list.
    """

    def __init__(self, source: str):
        lexer = Lexer(source)
        tokens: list[Token] = []
        while True:
            tok = lexer.next_token()
            tokens.append(tok)
            if tok.kind == Special(SpecialKind.EOF):
                break
        self.tokens = tokens
        self.pos = 0

    ### Token stream primitives -- kontrak yang dibutuhkan ExprParser/StmtParser

    def _current(self) -> Token:
        return self.tokens[self.pos]

    def _peek(self, offset: int = 1) -> Optional[Token]:
        idx = self.pos + offset
        if idx >= len(self.tokens):
            return None
        return self.tokens[idx]

    def _advance(self) -> Token:
        tok = self.tokens[self.pos]
        if self.pos < len(self.tokens) - 1:
            self.pos += 1
        return tok

    def _check(self, kind: TokenKind) -> bool:
        return self._current().kind == kind

    def _expect(self, kind: TokenKind) -> Token:
        if not self._check(kind):
            cur = self._current()
            raise ParseError(
                f"Expected {describe_token_kind(kind)}, got {describe_token_kind(cur.kind)} ({cur.text!r}) at {cur.span}"
            )
        return self._advance()

    def _match(self, *kinds: TokenKind) -> Optional[Token]:
        if self._current().kind in kinds:
            return self._advance()
        return None

    ### Type expression parsing -- kontrak yang dibutuhkan ExprParser (untuk
    # ArrayLiteral element type) dan StmtParser (untuk let type annotation)

    def _parse_type_expr(self) -> TypeExpr:
        """
        Entry point type parsing. Urutan cek penting:
          satisfy Trait [+ Other]   -> SatisfyTypeExpr
          [N]T atau [_]T            -> ArrayTypeExpr
          []T atau []mut T          -> SliceTypeExpr
          *T atau *mut T            -> PointerTypeExpr
          &T atau &mut T            -> ReferenceTypeExpr
          (T1, T2) -> R              -> FunctionTypeExpr
          Name / Name.Path / Name<Args> -> NamedTypeExpr / GenericTypeExpr

        '<' di posisi ini TIDAK ambigu dengan operator perbandingan --
        _parse_type_expr() HANYA dipanggil dari posisi yang sudah pasti
        mengharapkan tipe (setelah ':', '->', dst), tidak pernah dari
        posisi ekspresi biasa.
        """
        if self._check(Operator(OperatorKind.TICK)):
            return self._parse_bounded_type_expr()

        # self! — type-level intrinsic (intrinsics.md, trait.md §2)
        # Harus dicek SEBELUM named path, karena `self` adalah Keyword, bukan IDENT.
        if self._check(Keyword(KeywordKind.SELF)):
            next = self._peek()
            if next is not None and next.kind == Operator(OperatorKind.BANG):
                self._advance()
                self._advance()
                return IntrinsicTypeExpr(name="self")
        if self._check(Keyword(KeywordKind.SATISFY)):
            return self._parse_satisfy_type_expr()
        if self._check(Delimiter(DelimiterKind.LBRACKET)):
            return self._parse_array_or_slice_type_expr()
        if self._check(Operator(OperatorKind.STAR)):
            return self._parse_pointer_type_expr()
        if self._check(Operator(OperatorKind.AMPERSAND)):
            return self._parse_reference_type_expr()
        if self._check(Delimiter(DelimiterKind.LPAREN)):
            return self._parse_function_type_expr()
        return self._parse_named_or_generic_type_expr()

    def _parse_satisfy_type_expr(self) -> SatisfyTypeExpr:
        self._expect(Keyword(KeywordKind.SATISFY))
        traits = [self._parse_named_type_path()]
        while self._check(Operator(OperatorKind.PLUS)):
            self._advance()
            traits.append(self._parse_named_type_path())
        return SatisfyTypeExpr(traits=traits)

    def _parse_array_or_slice_type_expr(self):
        self._expect(Delimiter(DelimiterKind.LBRACKET))
        if self._check(Delimiter(DelimiterKind.RBRACKET)):
            # []T atau []mut T -- slice
            self._advance()
            is_mut = False
            if self._check(Keyword(KeywordKind.MUT)):
                self._advance()
                is_mut = True
            element = self._parse_type_expr()
            return SliceTypeExpr(element=element, is_mut=is_mut)
        # [N]T atau [_]T -- fixed array
        size: Optional[int] = None
        if self._check(Literal(LiteralKind.INT_LITERAL)):
            size_tok = self._advance()
            size = int(size_tok.text.replace("_", ""))
        elif self._check(Literal(LiteralKind.IDENT)) and self._current().text == "_":
            self._advance()
            size = None
        else:
            raise ParseError(f"Expected array size or '_' at {self._current().span}")
        self._expect(Delimiter(DelimiterKind.RBRACKET))
        element = self._parse_type_expr()
        return ArrayTypeExpr(element=element, size=size)

    def _parse_pointer_type_expr(self) -> PointerTypeExpr:
        self._expect(Operator(OperatorKind.STAR))
        is_mut = False
        if self._check(Keyword(KeywordKind.MUT)):
            self._advance()
            is_mut = True
        pointee = self._parse_type_expr()
        return PointerTypeExpr(pointee=pointee, is_mut=is_mut)

    def _parse_reference_type_expr(self) -> ReferenceTypeExpr:
        self._expect(Operator(OperatorKind.AMPERSAND))
        is_mut = False
        if self._check(Keyword(KeywordKind.MUT)):
            self._advance()
            is_mut = True
        referent = self._parse_type_expr()
        return ReferenceTypeExpr(referent=referent, is_mut=is_mut)

    def _parse_bounded_type_expr(self) -> BoundedTypeExpr:
        """
        'T atau 'mut T — Bounded Pointer (lifetime.md §3).
        """
        self._expect(Operator(OperatorKind.TICK))
        is_mut = False
        if self._check(Keyword(KeywordKind.MUT)):
            self._advance()
            is_mut = True
        bounded = self._parse_type_expr()
        return BoundedTypeExpr(bounded=bounded, is_mut=is_mut)

    def _parse_function_type_expr(self) -> FunctionTypeExpr:
        self._expect(Delimiter(DelimiterKind.LPAREN))
        params: list[TypeExpr] = []
        if not self._check(Delimiter(DelimiterKind.RPAREN)):
            params.append(self._parse_type_expr())
            while self._check(Delimiter(DelimiterKind.COMMA)):
                self._advance()
                params.append(self._parse_type_expr())
        self._expect(Delimiter(DelimiterKind.RPAREN))
        self._expect(Delimiter(DelimiterKind.ARROW))
        return_type = self._parse_type_expr()
        return FunctionTypeExpr(params=params, return_type=return_type)

    def _parse_named_or_generic_type_expr(self):
        base = self._parse_named_type_path()
        if self._check(Operator(OperatorKind.LT)):
            self._advance()
            args = [self._parse_type_expr()]
            while self._check(Delimiter(DelimiterKind.COMMA)):
                self._advance()
                args.append(self._parse_type_expr())
            self._expect(Operator(OperatorKind.GT))
            return GenericTypeExpr(base=base, args=args)
        return base

    def _parse_named_type_path(self) -> NamedTypeExpr:
        """Name atau Name.Sub.Path -- termasuk primitive keyword sebagai path 1 segmen."""
        path = [self._advance_type_segment()]
        while self._check(Delimiter(DelimiterKind.DOT)):
            self._advance()
            path.append(self._advance_type_segment())
        return NamedTypeExpr(path=path)

    _EXTRA_TYPE_NAME_KEYWORDS = frozenset({
        Keyword(KeywordKind.VOID),
        Keyword(KeywordKind.UNIT),
        Keyword(KeywordKind.SELF_TYPE),
        Keyword(KeywordKind.TYPE),  # meta-type `type` (type_system.md: const MyInt: type = i32)
    })

    def _advance_type_segment(self) -> str:
        """
        Satu segmen path tipe -- IDENT biasa
        """
        tok = self._current()
        if tok.kind == Literal(LiteralKind.IDENT) or tok.kind in self._EXTRA_TYPE_NAME_KEYWORDS:
            self._advance()
            return tok.text
        raise ParseError(f"Expected type name, got {tok.kind} at {tok.span}")

    ### foreign

    def _parse_foreign_decl(self) -> ForeignDecl:
        """
        foreign "libname" fn name(params) -> return_type;

        The 'foreign' keyword is followed by a string literal (library
        name), then 'fn', then a standard function signature, then ';'.
        No body — foreign declarations are pure signatures.

        `foreign fn` tidak bisa diberi modifier (internal/inline/comp/
        unsafe) -- ffi.md: "'foreign' sendiri sudah menandakan bahwa
        ini bukan fungsi Nala -- modifier Nala tidak relevan di sini."
        _parse_fn_decl() sendiri reusable dan MAU menyerap modifier
        semacam itu (dipakai juga oleh fn biasa) -- jadi modifier harus
        ditolak eksplisit DI SINI, bukan diam-diam diperbolehkan lewat
        reuse.
        """
        self._expect(Keyword(KeywordKind.FOREIGN))
        lib_tok = self._expect(Literal(LiteralKind.STRING_LITERAL))

        # Modifier TIDAK PERNAH valid di posisi ini -- cek token
        # SEBELUM delegasi ke _parse_fn_decl (yang akan menyerapnya
        # diam-diam kalau tidak dicegat lebih dulu).
        if self._current().kind in (
            Keyword(KeywordKind.INTERNAL),
            Keyword(KeywordKind.INLINE),
            Keyword(KeywordKind.COMP),
            Keyword(KeywordKind.UNSAFE),
        ):
            bad_tok = self._current()
            raise ParseError(
                f"foreign fn tidak boleh diberi modifier '{bad_tok.text}' "
                f"at {bad_tok.span} -- 'foreign' sendiri sudah menandakan "
                f"ini bukan fungsi Nala, modifier internal/inline/comp/"
                f"unsafe tidak relevan di sini."
            )

        # Parse function signature using existing logic.
        # _parse_fn_decl handles both body '{...}' and no-body ';' cases.
        # For foreign fn, we expect ';' (trait-method-style, no body).
        fn = self._parse_fn_decl([])

        # Verify no body was parsed (should end with ';', not '{').
        if fn.body:
            raise ParseError(
                f"foreign fn must not have a body — expected ';' after signature"
            )

        return ForeignDecl(lib_name=lib_tok.text, fn=fn)

    ### Program entry point

    def parse_program(self) -> list:
        """Top-level: sequence of use/struct/sum/enum/trait/satisfy/fn/test."""
        decls = []
        while not self._check(Special(SpecialKind.EOF)):
            decls.append(self._parse_top_level_decl())
        return decls

    def _parse_top_level_decl(self):
        hints = self._parse_compiler_hints()
        tok = self._current()

        if tok.kind == Keyword(KeywordKind.USE):
            return self._parse_use_decl()
        if tok.kind == Keyword(KeywordKind.TEST):
            return self._parse_test_decl()
        if tok.kind == Keyword(KeywordKind.CONST):
            return self._parse_const_decl(hints)
        if tok.kind == Keyword(KeywordKind.SATISFY):
            return self._parse_satisfy_decl()

        if tok.kind == Keyword(KeywordKind.FOREIGN):
            return self._parse_foreign_decl()

        # internal/inline/comp/unsafe fn -- modifier lookahead
        if tok.kind in (Keyword(KeywordKind.INTERNAL), Keyword(KeywordKind.INLINE), Keyword(KeywordKind.COMP),
                        Keyword(KeywordKind.UNSAFE), Keyword(KeywordKind.FN)):
            return self._parse_fn_decl(hints)

        raise ParseError(f"Unexpected top-level token {describe_token_kind(tok.kind)} at {tok.span}")

    def _is_compiler_hint_ahead(self) -> bool:
        if not self._check(Delimiter(DelimiterKind.HASH)):
            return False
        nxt = self._peek()
        return nxt is not None and nxt.kind == Delimiter(DelimiterKind.LBRACKET)

    def _parse_compiler_hint_name(self) -> Token:
        """
        Compiler hint name adalah BARE WORD apa pun -- validitasnya
        sebagai hint yang dikenal compiler adalah closed-set check
        SEMANTIK, BUKAN pembatasan sintaksis "harus non-keyword".
        Parser cukup terima Literal(IDENT) ATAU Keyword(...) apa pun
        sebagai nama hint, "be stupid" -- tidak menyimpulkan mana yang valid, cuma menerima bentuknya.
        """
        tok = self._current()
        if isinstance(tok.kind, (Literal, Keyword)):
            self._advance()
            return tok
        raise ParseError(
            f"Expected compiler hint name (identifier atau keyword), "
            f"got {describe_token_kind(tok.kind)} ({tok.text!r}) at {tok.span}"
        )

    def _parse_compiler_hints(self) -> list[CompilerHint]:
        """#[key] atau #[key(args)] -- boleh berulang, menempel ke satu declaration."""
        hints: list[CompilerHint] = []
        while self._is_compiler_hint_ahead():
            self._advance()  # consume HASH
            self._expect(Delimiter(DelimiterKind.LBRACKET))
            name_tok = self._parse_compiler_hint_name()
            args = []
            if self._check(Delimiter(DelimiterKind.LPAREN)):
                self._advance()
                if not self._check(Delimiter(DelimiterKind.RPAREN)):
                    args.append(self.parse_expr())
                    while self._check(Delimiter(DelimiterKind.COMMA)):
                        self._advance()
                        args.append(self.parse_expr())
                self._expect(Delimiter(DelimiterKind.RPAREN))
            self._expect(Delimiter(DelimiterKind.RBRACKET))
            hints.append(CompilerHint(name=name_tok.text, args=args))
        return hints

    ### use

    def _parse_use_decl(self) -> UseDecl:
        """
        use <namespace> [as <alias>];

        `as` OPSIONAL -- kalau tidak ada, alias default diambil dari
        segmen terakhir `<namespace>` (mis. `use std.mem` -> alias
        "mem"). `as` dipakai HANYA untuk override default itu, biasanya
        untuk menghindari konflik nama antar dua `use` yang segmen
        terakhirnya sama (mis. `use std.fmt` + `use local.fmt as
        myfmt`). Resolusi default alias itu sendiri ada di
        checker/use_alias.py (default_alias_for()).
        """
        self._expect(Keyword(KeywordKind.USE))
        segments = [self._advance_type_segment()]
        while self._check(Delimiter(DelimiterKind.DOT)):
            self._advance()
            segments.append(self._advance_type_segment())
        alias = None
        if self._check(Keyword(KeywordKind.AS)):
            self._advance()
            alias_tok = self._expect(Literal(LiteralKind.IDENT))
            alias = alias_tok.text
        self._expect(Delimiter(DelimiterKind.SEMICOLON))
        return UseDecl(module_path=".".join(segments), alias=alias)

    ### const -- termasuk const yang mengikat struct/sum/enum/trait

    def _parse_const_decl(self, hints: list[CompilerHint]):
        self._expect(Keyword(KeywordKind.CONST))
        name_tok = self._expect(Literal(LiteralKind.IDENT))
        type_params: list[str] = []
        if self._check(Operator(OperatorKind.LT)):
            type_params = self._parse_type_param_list()
        self._expect(Operator(OperatorKind.EQ))

        if self._check(Keyword(KeywordKind.STRUCT)):
            return self._parse_struct_body(name_tok.text, type_params, hints)
        if self._check(Keyword(KeywordKind.SUM)):
            return self._parse_sum_body(name_tok.text, type_params, hints)
        if self._check(Keyword(KeywordKind.ENUM)):
            return self._parse_enum_body(name_tok.text, hints)
        if self._check(Keyword(KeywordKind.TRAIT)):
            return self._parse_trait_body(name_tok.text)

        # const biasa (nilai primitif atau alias) -- untuk sekarang
        # direpresentasikan minimal; detail const-value/alias exhaustive
        # menyusul kalau dibutuhkan kasus konkret lebih lanjut.
        value = self.parse_expr()
        self._expect(Delimiter(DelimiterKind.SEMICOLON))
        return ("ConstDecl", name_tok.text, value)

    def _parse_type_param_list(self) -> list[str]:
        """<T, U, ...> -- nama polos, SYNTAX saja (parser be stupid,
        tidak tahu apakah T valid/dipakai konsisten)."""
        self._expect(Operator(OperatorKind.LT))
        params = [self._expect(Literal(LiteralKind.IDENT)).text]
        # optional ": type" atau ": satisfy Trait" bound -- di-skip
        # strukturnya sederhana dulu, cukup catat nama.
        if self._check(Delimiter(DelimiterKind.COLON)):
            self._advance()
            self._parse_type_expr()
        while self._check(Delimiter(DelimiterKind.COMMA)):
            self._advance()
            params.append(self._expect(Literal(LiteralKind.IDENT)).text)
            if self._check(Delimiter(DelimiterKind.COLON)):
                self._advance()
                self._parse_type_expr()
        self._expect(Operator(OperatorKind.GT))
        return params

    ### struct

    def _parse_struct_body(self, name: str, type_params: list[str], hints: list[CompilerHint]) -> StructDecl:
        self._expect(Keyword(KeywordKind.STRUCT))
        self._expect(Delimiter(DelimiterKind.LBRACE))
        fields: list[StructField] = []
        methods: list[FnDecl] = []

        while not self._check(Delimiter(DelimiterKind.RBRACE)):
            if self._current().kind in (
                Keyword(KeywordKind.INTERNAL),
                Keyword(KeywordKind.INLINE),
                Keyword(KeywordKind.COMP),
                Keyword(KeywordKind.UNSAFE),
                Keyword(KeywordKind.FN),
            ):
                methods.append(self._parse_fn_decl([], struct_name=name))
            else:
                fields.append(self._parse_struct_field())
                if self._check(Delimiter(DelimiterKind.COMMA)):
                    self._advance()
        self._expect(Delimiter(DelimiterKind.RBRACE))
        return StructDecl(name=name, fields=fields, methods=methods, type_params=type_params, hints=hints)

    def _parse_struct_field(self) -> StructField:
        name_tok = self._expect(Literal(LiteralKind.IDENT))
        self._expect(Delimiter(DelimiterKind.COLON))
        field_type = self._parse_type_expr()
        default = None
        if self._check(Operator(OperatorKind.EQ)):
            self._advance()
            default = self.parse_expr()
        return StructField(name=name_tok.text, type=field_type, default=default)

    ### sum type

    def _parse_sum_body(self, name: str, type_params: list[str], hints: list[CompilerHint]) -> SumDecl:
        """
        Parse badan `sum { ... }`
        """
        self._expect(Keyword(KeywordKind.SUM))
        self._expect(Delimiter(DelimiterKind.LBRACE))
        variants: list[SumVariantDecl] = []
        methods: list[FnDecl] = []

        while not self._check(Delimiter(DelimiterKind.RBRACE)):
            if self._current().kind in (
                Keyword(KeywordKind.INTERNAL),
                Keyword(KeywordKind.INLINE),
                Keyword(KeywordKind.COMP),
                Keyword(KeywordKind.UNSAFE),
                Keyword(KeywordKind.FN),
            ):
                methods.append(self._parse_fn_decl([], struct_name=name))
                continue
            variant_name = self._expect(Literal(LiteralKind.IDENT)).text
            payload_types: list[TypeExpr] = []
            if self._check(Delimiter(DelimiterKind.LPAREN)):
                self._advance()
                if not self._check(Delimiter(DelimiterKind.RPAREN)):
                    payload_types.append(self._parse_type_expr())
                    while self._check(Delimiter(DelimiterKind.COMMA)):
                        self._advance()
                        payload_types.append(self._parse_type_expr())
                self._expect(Delimiter(DelimiterKind.RPAREN))
            variants.append(SumVariantDecl(name=variant_name, payload_types=payload_types))
            if self._check(Delimiter(DelimiterKind.COMMA)):
                self._advance()
        self._expect(Delimiter(DelimiterKind.RBRACE))
        return SumDecl(name=name, variants=variants, methods=methods, type_params=type_params, hints=hints)

    ### enum

    def _parse_enum_body(self, name: str, hints: list[CompilerHint]) -> EnumDecl:
        self._expect(Keyword(KeywordKind.ENUM))
        self._expect(Delimiter(DelimiterKind.LBRACE))
        variants: list[EnumVariantDecl] = []
        methods: list[FnDecl] = []
        while not self._check(Delimiter(DelimiterKind.RBRACE)):
            if self._current().kind in (
                Keyword(KeywordKind.INTERNAL),
                Keyword(KeywordKind.INLINE),
                Keyword(KeywordKind.COMP),
                Keyword(KeywordKind.UNSAFE),
                Keyword(KeywordKind.FN),
            ):
                methods.append(self._parse_fn_decl([], struct_name=name))
                continue
            variant_name_tok = self._advance()  # IDENT atau BACKTICK_IDENT (`1`, dst)
            value = None
            if self._check(Operator(OperatorKind.EQ)):
                self._advance()
                value = self.parse_expr()
            variants.append(EnumVariantDecl(name=variant_name_tok.text, value=value))
            if self._check(Delimiter(DelimiterKind.COMMA)):
                self._advance()
        self._expect(Delimiter(DelimiterKind.RBRACE))
        return EnumDecl(name=name, variants=variants, methods=methods, hints=hints)

    ### trait

    def _parse_trait_body(self, name: str) -> TraitDecl:
        self._expect(Keyword(KeywordKind.TRAIT))
        super_traits = []
        if self._check(Delimiter(DelimiterKind.LPAREN)):
            self._advance()
            super_traits.append(self._parse_named_type_path())
            while self._check(Operator(OperatorKind.PLUS)):
                self._advance()
                super_traits.append(self._parse_named_type_path())
            self._expect(Delimiter(DelimiterKind.RPAREN))
        self._expect(Delimiter(DelimiterKind.LBRACE))
        methods: list[TraitMethodDecl] = []
        associated_types: list[str] = []
        while not self._check(Delimiter(DelimiterKind.RBRACE)):
            if self._check(Keyword(KeywordKind.TYPE)):
                self._advance()
                assoc_name = self._expect(Literal(LiteralKind.IDENT)).text
                associated_types.append(assoc_name)
            else:
                methods.append(self._parse_trait_method())
        self._expect(Delimiter(DelimiterKind.RBRACE))
        return TraitDecl(name=name, methods=methods, associated_types=associated_types, super_traits=super_traits)

    def _parse_trait_method(self) -> TraitMethodDecl:
        self._expect(Keyword(KeywordKind.FN))
        name_tok = self._expect(Literal(LiteralKind.IDENT))
        params = self._parse_param_list_with_self()
        return_type = NamedTypeExpr(path=["void"])
        if self._check(Delimiter(DelimiterKind.ARROW)):
            self._advance()
            return_type = self._parse_type_expr()
        default_body = None
        if self._check(Delimiter(DelimiterKind.LBRACE)):
            default_body = self.parse_block()
        else:
            self._expect(Delimiter(DelimiterKind.SEMICOLON))
        return TraitMethodDecl(name=name_tok.text, params=params, return_type=return_type, default_body=default_body)

    ### satisfy

    def _parse_satisfy_decl(self) -> SatisfyDecl:
        self._expect(Keyword(KeywordKind.SATISFY))
        type_name = self._parse_named_type_path()
        self._expect(Delimiter(DelimiterKind.COLON))
        trait_name = self._parse_named_type_path()
        self._expect(Delimiter(DelimiterKind.LBRACE))
        methods: list[FnDecl] = []
        associated_types: dict[str, TypeExpr] = {}

        while not self._check(Delimiter(DelimiterKind.RBRACE)):
            if self._check(Keyword(KeywordKind.TYPE)):
                self._advance()
                assoc_name = self._expect(Literal(LiteralKind.IDENT)).text
                self._expect(Operator(OperatorKind.EQ))
                assoc_type = self._parse_type_expr()
                associated_types[assoc_name] = assoc_type
            else:
                methods.append(self._parse_fn_decl([], struct_name=type_name.path[-1]))
        self._expect(Delimiter(DelimiterKind.RBRACE))
        return SatisfyDecl(type_name=type_name, trait_name=trait_name, methods=methods, associated_types=associated_types)

    ### fn -- dengan modifier order Visibility -> Tag -> Treat (module_system.md)

    def _parse_fn_decl(self, hints: list[CompilerHint], struct_name: Optional[str] = None) -> FnDecl:
        is_internal = False
        is_inline = False
        is_comp = False
        is_unsafe = False
        if self._check(Keyword(KeywordKind.INTERNAL)):
            self._advance()
            is_internal = True
        if self._check(Keyword(KeywordKind.INLINE)):
            self._advance()
            is_inline = True
        if self._check(Keyword(KeywordKind.COMP)):
            self._advance()
            is_comp = True
        if self._check(Keyword(KeywordKind.UNSAFE)):
            self._advance()
            is_unsafe = True
        self._expect(Keyword(KeywordKind.FN))
        name_tok = self._expect(Literal(LiteralKind.IDENT))

        self_param = None
        params: list[Param] = []
        self._expect(Delimiter(DelimiterKind.LPAREN))
        if self._is_self_param_ahead():
            self_param = self._parse_self_param()
            if self._check(Delimiter(DelimiterKind.COMMA)):
                self._advance()
        if not self._check(Delimiter(DelimiterKind.RPAREN)):
            params.append(self._parse_param())
            while self._check(Delimiter(DelimiterKind.COMMA)):
                self._advance()
                if self._check(Delimiter(DelimiterKind.RPAREN)):
                    break
                params.append(self._parse_param())
        self._expect(Delimiter(DelimiterKind.RPAREN))

        return_type = None
        if self._check(Delimiter(DelimiterKind.ARROW)):
            self._advance()
            return_type = self._parse_type_expr()

        body: list[Stmt] = []
        if self._check(Delimiter(DelimiterKind.LBRACE)):
            body = self.parse_block()
        else:
            self._expect(Delimiter(DelimiterKind.SEMICOLON))  # trait method signature tanpa body

        return FnDecl(
            name=name_tok.text, params=params, return_type=return_type, body=body,
            is_internal=is_internal, is_inline=is_inline, is_comp=is_comp, is_unsafe=is_unsafe,
            self_param=self_param, struct_name=struct_name, hints=hints,
        )

    def _is_self_param_ahead(self) -> bool:
        """
        self / &self / &mut self / mut self di posisi parameter
        pertama -- EMPAT bentuk (memory_management.md ss3), BUKAN tiga.
        """
        if self._check(Keyword(KeywordKind.SELF)):
            return True
        if self._check(Keyword(KeywordKind.MUT)):
            nxt = self._peek()
            return nxt is not None and nxt.kind == Keyword(KeywordKind.SELF)
        if self._check(Operator(OperatorKind.AMPERSAND)):
            nxt = self._peek()
            if nxt is not None and nxt.kind == Keyword(KeywordKind.SELF):
                return True
            if nxt is not None and nxt.kind == Keyword(KeywordKind.MUT):
                nxt2 = self._peek(2)
                return nxt2 is not None and nxt2.kind == Keyword(KeywordKind.SELF)
        return False

    def _parse_self_param(self) -> SelfParam:
        """Lihat catatan lengkap di _is_self_param_ahead() soal mut self."""
        if self._check(Keyword(KeywordKind.SELF)):
            self._advance()
            return SelfParam(is_mut=False, is_ref=False, is_binding_mut=False)  # consuming self
        if self._check(Keyword(KeywordKind.MUT)):
            self._advance()
            self._expect(Keyword(KeywordKind.SELF))
            return SelfParam(is_mut=False, is_ref=False, is_binding_mut=True)  # consuming mut self
        self._expect(Operator(OperatorKind.AMPERSAND))
        is_mut = False
        if self._check(Keyword(KeywordKind.MUT)):
            self._advance()
            is_mut = True
        self._expect(Keyword(KeywordKind.SELF))
        return SelfParam(is_mut=is_mut, is_ref=True, is_binding_mut=False)

    def _parse_param(self) -> Param:
        name_tok = self._expect(Literal(LiteralKind.IDENT))
        self._expect(Delimiter(DelimiterKind.COLON))
        is_value_mut = False
        if self._check(Keyword(KeywordKind.MUT)):
            self._advance()
            is_value_mut = True
        param_type = self._parse_type_expr()
        return Param(name=name_tok.text, type=param_type, is_value_mut=is_value_mut)

    def _parse_param_list_with_self(self) -> list[Param]:
        """Untuk trait method signature -- self boleh ada, ditangani terpisah dari Param biasa."""
        self._expect(Delimiter(DelimiterKind.LPAREN))
        params: list[Param] = []
        if self._is_self_param_ahead():
            self._parse_self_param()
            if self._check(Delimiter(DelimiterKind.COMMA)):
                self._advance()
        if not self._check(Delimiter(DelimiterKind.RPAREN)):
            params.append(self._parse_param())
            while self._check(Delimiter(DelimiterKind.COMMA)):
                self._advance()
                params.append(self._parse_param())
        self._expect(Delimiter(DelimiterKind.RPAREN))
        return params

    ### test

    def _parse_test_decl(self) -> TestDecl:
        self._expect(Keyword(KeywordKind.TEST))
        name_tok = self._expect(Literal(LiteralKind.STRING_LITERAL))
        body = self.parse_block()
        return TestDecl(name=name_tok.text, body=body)


def parse(source: str) -> list:
    """Convenience entry point."""
    return Parser(source).parse_program()


### DEBUGGER !
### bukan bagian parser.

def _format_ast(node, indent: int = 0) -> str:
    """
    Cetak satu node AST (dataclass APAPUN dari nala_ast.nodes, atau
    list/tuple berisi node-node itu, atau tuple mentah dari
    _parse_const_decl untuk const biasa) sebagai tree ber-indentasi.

    Sengaja TIDAK memakai repr() dataclass mentah -- untuk node
    bersarang dalam (mis. FnDecl dengan body berisi banyak Stmt, tiap
    Stmt berisi Expr, dst), repr() menghasilkan SATU BARIS PANJANG
    yang nyaris tidak terbaca manusia. Pretty-printer ini murni utk
    keperluan mata manusia membaca output CLI -- bukan representasi
    yang dipakai bagian lain compiler manapun.
    """
    import dataclasses

    pad = "  " * indent

    if node is None:
        return f"{pad}None"

    if isinstance(node, (list, tuple)) and dataclasses.is_dataclass(node) is False:
        if not node:
            return f"{pad}[]"
        lines = [f"{pad}["]
        for item in node:
            lines.append(_format_ast(item, indent + 1))
        lines.append(f"{pad}]")
        return "\n".join(lines)

    if dataclasses.is_dataclass(node):
        cls_name = type(node).__name__
        fields = dataclasses.fields(node)
        if not fields:
            return f"{pad}{cls_name}"
        lines = [f"{pad}{cls_name}"]
        for f in fields:
            value = getattr(node, f.name)
            if dataclasses.is_dataclass(value) or (isinstance(value, (list, tuple)) and value and any(dataclasses.is_dataclass(v) for v in value)):
                lines.append(f"{pad}  {f.name}:")
                lines.append(_format_ast(value, indent + 2))
            else:
                lines.append(f"{pad}  {f.name}: {value!r}")
        return "\n".join(lines)

    # Fallback -- tuple mentah dari _parse_const_decl (const biasa,
    # bukan struct/sum/enum/trait), atau nilai primitif apa pun.
    return f"{pad}{node!r}"


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        print("usage: python -m parser.parser <file.na>")
        sys.exit(1)
    with open(sys.argv[1], "r", encoding="utf-8") as f:
        src = f.read()
    try:
        decls = parse(src)
    except (ParseError, ExprParseError, StmtParseError) as e:
        print(f"ParseError: {e}")
        sys.exit(1)
    for decl in decls:
        print(_format_ast(decl))
        print()
