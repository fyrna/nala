# parser/expr.py
"""
Expression parser -- precedence climbing untuk operator biner/unary,
plus leading-dot detection di _parse_primary().

Prinsip "parser be stupid": parser TIDAK memvalidasi apakah nama
Variant/method/field valid -- ia cuma mencatat BENTUK sintaksis yang
dilihat (LeadingDotAccess/LeadingDotCall/LeadingDotStructLiteral vs
DottedAccess/DottedCall). Validitas semantik sepenuhnya delegasi ke
checker/hir_builder.

Precedence (rendah ke tinggi), mengikuti language.md:
  or
  and
  == != > < >= <=
  |  (bitwise or)
  ^  (bitwise xor)
  &  (bitwise and -- overlap simbol dgn reference, context menentukan: prefix = reference/addr-of, infix = bitwise and)
  << >>
  + -
  * / %
  unary: - ! ~ & *     (prefix)
  postfix: call, index, field access, dotted access
"""
from __future__ import annotations
from typing import Optional

from lexer.token import (
    Token, TokenKind, Keyword, Operator, Delimiter, Literal, Special,
    KeywordKind, OperatorKind, DelimiterKind, LiteralKind, SpecialKind,
    describe_token_kind,
)

from nala_ast.nodes import (
    Expr, BinaryExpr, UnaryExpr, CallExpr, MethodCall, IntrinsicCall,
    Ident, StringLiteral, IntLiteral, FloatLiteral, BoolLiteral, ByteLiteral, UnitLiteral,
    FieldAccess, ArrayIndex, IfExpr, StructLiteral, FieldInit,
    DottedAccess, DottedCall, LeadingDotAccess, LeadingDotCall,
    LeadingDotStructLiteral, ArrayLiteral, TryExpr,
)


class ParseError(Exception):
    pass


# Suffix set -- SAMA PERSIS dengan lexer/lexer.py:_INT_SUFFIXES/_FLOAT_SUFFIXES
# (harus tetap sinkron -- lexer yang MENDETEKSI kemunculan suffix di
# source, parser di sini yang MEMISAHKAN-nya dari bagian angka murni.
# Urutan "isize"/"usize" (5 char) SEBELUM "i8" dst penting -- sama
# alasan longest-match dengan catatan di lexer.
_INT_LITERAL_SUFFIXES = ("isize", "usize", "i8", "i16", "i32", "i64", "u8", "u16", "u32", "u64")
_FLOAT_LITERAL_SUFFIXES = ("f32", "f64")


def _split_literal_suffix(raw_text: str, allowed_suffixes: tuple[str, ...]) -> tuple[str, "str | None"]:
    # Hex / binary tetap boleh punya type suffix (0xABCu32, 0b1010u8).
    # Hanya tolak split kalau karakter yang akan dianggap suffix
    # ternyata adalah digit hex/binary yang sah (jebakan klasik 0xf64).
    for suffix in allowed_suffixes:
        if raw_text.endswith(suffix) and len(raw_text) > len(suffix):
            prefix = raw_text[: -len(suffix)]
            # Jaga ambiguitas gaya 0xf64: kalau "suffix"-nya terdiri
            # dari digit hex dan prefix-nya literal hex, anggap seluruh
            # string sebagai nilai, jangan dipisah.
            if prefix[:2].lower() in ("0x", "0b") and all(c in "0123456789abcdefABCDEF" for c in suffix):
                continue
            return raw_text[: -len(suffix)], suffix
    return raw_text, None


class ExprParser:
    """
    Dipakai sebagai mixin/komponen oleh Parser utama (parser.py) --
    butuh akses ke stream token yang sama (self._current, self._advance,
    dst disediakan Parser induk). Di sini diasumsikan method-method itu
    sudah tersedia lewat inheritance atau composition -- lihat parser.py.
    """

    # Flag context -- ketika True, IDENT langsung diikuti '{' TIDAK
    # dianggap StructLiteral. Diaktifkan StmtParser di posisi yang '{'
    # setelahnya WAJIB berarti pembuka block (kondisi if/for/match),
    # bukan diserahkan ke penebakan ExprParser. Ini menyelesaikan
    # ambiguitas klasik "if x { ... }" -- apakah x diikuti block, atau
    # x { ... } adalah struct literal -- secara STRUKTURAL (lewat
    # context eksplisit), bukan heuristik tebak-tebakan.
    _no_struct_literal: bool = False

    def parse_expr_no_struct_literal(self) -> Expr:
        """
        Entry point khusus untuk posisi yang '{' setelahnya WAJIB
        berarti pembuka block -- kondisi if/for/match/while. StmtParser
        HARUS memanggil ini (bukan parse_expr() biasa) di semua posisi
        semacam itu.
        """
        prev = self._no_struct_literal
        self._no_struct_literal = True
        try:
            return self.parse_expr()
        finally:
            self._no_struct_literal = prev

    # ========================================================================
    # Entry point
    # ========================================================================

    def parse_expr(self) -> Expr:
        return self._parse_or()

    # ========================================================================
    # Precedence climbing -- rendah ke tinggi
    # ========================================================================

    def _parse_or(self) -> Expr:
        left = self._parse_and()
        while self._check(Keyword(KeywordKind.OR)):
            self._advance()
            right = self._parse_and()
            left = BinaryExpr(op="or", left=left, right=right)
        return left

    def _parse_and(self) -> Expr:
        left = self._parse_equality()
        while self._check(Keyword(KeywordKind.AND)):
            self._advance()
            right = self._parse_equality()
            left = BinaryExpr(op="and", left=left, right=right)
        return left

    def _parse_equality(self) -> Expr:
        left = self._parse_comparison()
        while self._check(Operator(OperatorKind.EQ_EQ)) or self._check(Operator(OperatorKind.NOT_EQ)):
            op_tok = self._advance()
            right = self._parse_comparison()
            left = BinaryExpr(op=op_tok.text, left=left, right=right)
        return left

    def _parse_comparison(self) -> Expr:
        left = self._parse_bitwise_or()
        while self._check(Operator(OperatorKind.GT)) or self._check(Operator(OperatorKind.LT)) or \
              self._check(Operator(OperatorKind.GT_EQ)) or self._check(Operator(OperatorKind.LT_EQ)):
            op_tok = self._advance()
            right = self._parse_bitwise_or()
            left = BinaryExpr(op=op_tok.text, left=left, right=right)
        return left

    def _parse_bitwise_or(self) -> Expr:
        left = self._parse_bitwise_xor()
        while self._check(Operator(OperatorKind.PIPE)):
            self._advance()
            right = self.parse_bitwise_xor()
            left = BinaryExpr(op="|", left=left, right=right)
        return left

    def _parse_bitwise_xor(self) -> Expr:
        left = self._parse_bitwise_and()
        while self._check(Operator(OperatorKind.CARET)):
            op_tok = self._advance()
            right = self._parse_bitwise_and()
            left = BinaryExpr(op=op_tok.text, left=left, right=right)
        return left

    def _parse_bitwise_and(self) -> Expr:
        left = self._parse_shift()
        while self._check(Operator(OperatorKind.AMPERSAND)):
            self._advance()
            right = self._parse_shift()
            left = BinaryExpr(op="&", left=left, right=right)
        return left

    def _parse_shift(self) -> Expr:
        left = self._parse_additive()
        while self._check(Operator(OperatorKind.SHL)) or self._check(Operator(OperatorKind.SHR)):
            op_tok = self._advance()
            right = self._parse_additive()
            left = BinaryExpr(op=op_tok.text, left=left, right=right)
        return left

    def _parse_additive(self) -> Expr:
        left = self._parse_multiplicative()
        while self._check(Operator(OperatorKind.PLUS)) or self._check(Operator(OperatorKind.MINUS)):
            op_tok = self._advance()
            right = self._parse_multiplicative()
            left = BinaryExpr(op=op_tok.text, left=left, right=right)
        return left

    def _parse_multiplicative(self) -> Expr:
        left = self._parse_unary()
        while self._check(Operator(OperatorKind.STAR)) or self._check(Operator(OperatorKind.SLASH)) or self._check(Operator(OperatorKind.PERCENT)):
            op_tok = self._advance()
            right = self._parse_unary()
            left = BinaryExpr(op=op_tok.text, left=left, right=right)
        return left

    def _parse_unary(self) -> Expr:
        """
        Prefix: - ! ~ &  (negation, logical not, bitwise not, reference).
        Dereference (`p.*`) BUKAN prefix -- ia POSTFIX, ditangani
        _parse_postfix() (lihat cabang DOT diikuti STAR di sana), TIDAK
        PERNAH `*p`. Docstring versi lama menyebut '*' sebagai salah
        satu prefix di sini -- itu SALAH/tidak pernah benar-benar
        diimplementasikan (dikonfirmasi: tidak ada cabang Operator(OperatorKind.STAR)
        di method ini sama sekali sebelumnya), dan sekarang secara
        eksplisit dikonfirmasi salah oleh spesifikasi (pointer.md:
        "p.*.*.*.* -- postfix, tidak ada cara lain").
        """
        if self._check(Keyword(KeywordKind.TRY)):
            # try MENGIKAT SELURUH CHAIN di kanannya (error_handling.md:
            # "try mengikat seluruh chain method di kanannya" -- mis.
            # "try io.open().read()" -- try membungkus HASIL
            # _parse_postfix() PENUH, bukan cuma satu primary atom.
            # Precedence-nya sengaja lebih rendah dari operator unary
            # lain di sini (-, !, ~, &) tapi lebih tinggi dari binary
            # manapun -- konsisten dengan posisi "keyword prefix" yang
            # mengikat operand tunggal tapi operand itu sendiri boleh
            # berupa chain postfix kompleks.
            self._advance()
            inner = self._parse_postfix()
            return TryExpr(inner=inner)
        if self._check(Operator(OperatorKind.MINUS)) or self._check(Operator(OperatorKind.BANG)) or \
           self._check(Operator(OperatorKind.TILDE)):
            op_tok = self._advance()
            operand = self._parse_unary()
            return UnaryExpr(op=op_tok.text, operand=operand)
        if self._check(Operator(OperatorKind.AMPERSAND)):
            # &expr atau &mut expr -- reference/borrow
            self._advance()
            is_mut = False
            if self._check(Keyword(KeywordKind.MUT)):
                self._advance()
                is_mut = True
            operand = self._parse_unary()
            return UnaryExpr(op="&mut" if is_mut else "&", operand=operand)
        return self._parse_postfix()

    # ========================================================================
    # Postfix: call, index, field access, intrinsic call
    # ========================================================================

    def _parse_postfix(self) -> Expr:
        expr = self._parse_primary()
        while True:
            if self._check(Delimiter(DelimiterKind.LPAREN)):
                # foo(args) -- hanya valid kalau expr adalah Ident (nama fn)
                args = self._parse_call_args()
                if isinstance(expr, Ident):
                    expr = CallExpr(callee=expr, args=args)
                else:
                    # Bentuk lain (mis. hasil field access dipanggil) --
                    # parser tetap "stupid", biarkan checker yang putuskan
                    # validitasnya. Direpresentasikan sebagai MethodCall
                    # generik dengan method="" sebagai placeholder call
                    # langsung -- TODO: node CallOnExpr kalau kasus ini
                    # ternyata sering muncul di source nyata.
                    expr = MethodCall(obj=expr, method="", args=args)
            elif self._check(Operator(OperatorKind.BANG)):
                # intrinsic! atau intrinsic!(args) -- HANYA valid kalau
                # expr adalah Ident (nama intrinsic seperti sizeof, popcount).
                # self! juga masuk sini (SELF token sudah jadi Ident-like
                # sebelumnya -- lihat _parse_primary soal SELF).
                if not isinstance(expr, Ident):
                    break  # BANG di sini bukan intrinsic call, biarkan
                           # ditangani sebagai operator lain di level atas
                self._advance()  # consume !
                args = []
                if self._check(Delimiter(DelimiterKind.LPAREN)):
                    args = self._parse_call_args()
                expr = IntrinsicCall(name=expr.name, args=args)
            elif self._check(Delimiter(DelimiterKind.DOT)):
                self._advance()
                if self._check(Operator(OperatorKind.STAR)):
                    # p.* -- POSTFIX dereference (pointer.md: "p.*.*.*.*
                    # -- postfix, tidak ada cara lain"). BUKAN prefix
                    # *p (itu TIDAK PERNAH valid syntax Nala). Chaining
                    # natural lewat loop postfix ini sendiri -- p.*.*
                    # otomatis kerja karena habis consume '.' + '*' di
                    # sini, loop while di atas lanjut lagi dari awal,
                    # ketemu '.' berikutnya (kalau ada) diproses ulang
                    # persis sama. p.*.field / p.*.method() juga
                    # otomatis natural dengan alasan yang sama -- hasil
                    # UnaryExpr(op="*") ini jadi `expr` baru, iterasi
                    # while berikutnya melihat DOT lagi (kalau ada) dan
                    # memprosesnya sebagai field/method access BIASA
                    # pada hasil deref, TIDAK butuh kasus khusus apa pun.
                    self._advance()  # consume STAR
                    expr = UnaryExpr(op="*", operand=expr)
                    continue
                name_tok = self._expect(Literal(LiteralKind.IDENT))
                if self._check(Delimiter(DelimiterKind.LPAREN)):
                    args = self._parse_call_args()
                    expr = DottedCall(base=expr, name=name_tok.text, args=args)
                else:
                    expr = DottedAccess(base=expr, name=name_tok.text)
            elif self._check(Delimiter(DelimiterKind.LBRACKET)):
                self._advance()
                index = self.parse_expr()
                self._expect(Delimiter(DelimiterKind.RBRACKET))
                expr = ArrayIndex(obj=expr, index=index)
            else:
                break
        return expr

    def _parse_call_args(self) -> list[Expr]:
        self._expect(Delimiter(DelimiterKind.LPAREN))
        args: list[Expr] = []
        if not self._check(Delimiter(DelimiterKind.RPAREN)):
            args.append(self.parse_expr())
            while self._check(Delimiter(DelimiterKind.COMMA)):
                self._advance()
                args.append(self.parse_expr())
        self._expect(Delimiter(DelimiterKind.RPAREN))
        return args

    # ========================================================================
    # Primary -- TITIK PALING KRITIS: leading-dot detection di sini
    # ========================================================================

    def _parse_primary(self) -> Expr:
        tok = self._current()

        # --- LEADING-DOT: token PERTAMA adalah DOT, tanpa base sama
        # sekali. Ini yang GAGAL TOTAL di versi lama -- _parse_primary
        # lama tidak punya cabang ini sama sekali. ---
        if tok.kind == Delimiter(DelimiterKind.DOT):
            return self._parse_leading_dot()

        if tok.kind == Literal(LiteralKind.INT_LITERAL):
            self._advance()
            numeric_part, suffix = _split_literal_suffix(tok.text, _INT_LITERAL_SUFFIXES)
            return IntLiteral(value=numeric_part, suffix=suffix)

        if tok.kind == Literal(LiteralKind.FLOAT_LITERAL):
            self._advance()
            numeric_part, suffix = _split_literal_suffix(tok.text, _FLOAT_LITERAL_SUFFIXES)
            return FloatLiteral(value=numeric_part, suffix=suffix)

        if tok.kind == Literal(LiteralKind.STRING_LITERAL):
            self._advance()
            return StringLiteral(value=tok.text)

        if tok.kind == Literal(LiteralKind.BYTE_LITERAL):
            self._advance()
            return ByteLiteral(value=tok.text)

        if tok.kind == Keyword(KeywordKind.TRUE):
            self._advance()
            return BoolLiteral(value=True)

        if tok.kind == Keyword(KeywordKind.FALSE):
            self._advance()
            return BoolLiteral(value=False)

        if tok.kind == Keyword(KeywordKind.SELF):
            # self sebagai EXPRESSION (bukan parameter -- itu ditangani
            # parser signature fn terpisah). self! (intrinsic) ditangani
            # otomatis oleh _parse_postfix lewat cabang BANG di atas,
            # karena Ident(name="self") diperlakukan sama seperti nama
            # intrinsic lain.
            self._advance()
            return Ident(name="self")
 
        if tok.kind == Keyword(KeywordKind.SOLE):
            # Nilai literal dari tipe `unit` (type_system.md §2).
            # `unit` sendiri HANYA tipe (sudah ditangani di type parser
            # lewat _EXTRA_TYPE_NAME_KEYWORDS). `sole` adalah satu-satunya
            # penghuni himpunan unit.
            self._advance()
            return UnitLiteral()

        if tok.kind == Keyword(KeywordKind.IF):
            return self._parse_if_expr()

        if tok.kind == Delimiter(DelimiterKind.LPAREN):
            self._advance()
            inner = self.parse_expr()
            self._expect(Delimiter(DelimiterKind.RPAREN))
            return inner

        if tok.kind == Delimiter(DelimiterKind.LBRACKET):
            return self._parse_array_literal()

        if tok.kind == Literal(LiteralKind.IDENT):
            self._advance()
            # StructLiteral eksplisit: Name { field: val, ... } --
            # HANYA kalau langsung diikuti '{' DAN kita TIDAK sedang di
            # posisi yang '{' setelahnya wajib berarti block (lihat
            # _no_struct_literal / parse_expr_no_struct_literal di atas).
            # Ini menyelesaikan ambiguitas "if x { ... }" secara
            # struktural -- StmtParser eksplisit menandai posisi mana
            # yang butuh disambiguasi ini, bukan ExprParser menebak.
            if self._check(Delimiter(DelimiterKind.LBRACE)) and not self._no_struct_literal:
                return self._parse_struct_literal(tok.text)
            return Ident(name=tok.text)

        raise ParseError(f"Unexpected token {describe_token_kind(tok.kind)} ({tok.text!r}) at {tok.span}")

    def _parse_leading_dot(self) -> Expr:
        """
          .{ ... }        -> LeadingDotStructLiteral
          .Variant        -> LeadingDotAccess
          .Variant(args)  -> LeadingDotCall
        """
        self._advance()  # consume DOT

        if self._check(Delimiter(DelimiterKind.LBRACE)):
            return self._parse_leading_dot_struct_literal()

        name_tok = self._expect(Literal(LiteralKind.IDENT))
        if self._check(Delimiter(DelimiterKind.LPAREN)):
            args = self._parse_call_args()
            return LeadingDotCall(name=name_tok.text, args=args)
        return LeadingDotAccess(name=name_tok.text)

    def _parse_leading_dot_struct_literal(self) -> LeadingDotStructLiteral:
        self._expect(Delimiter(DelimiterKind.LBRACE))
        fields: list[FieldInit] = []
        if not self._check(Delimiter(DelimiterKind.RBRACE)):
            fields.append(self._parse_field_init())
            while self._check(Delimiter(DelimiterKind.COMMA)):
                self._advance()
                if self._check(Delimiter(DelimiterKind.RBRACE)):
                    break  # trailing comma
                fields.append(self._parse_field_init())
        self._expect(Delimiter(DelimiterKind.RBRACE))
        return LeadingDotStructLiteral(fields=fields)

    def _parse_field_init(self) -> FieldInit:
        name_tok = self._expect(Literal(LiteralKind.IDENT))
        self._expect(Delimiter(DelimiterKind.COLON))
        value = self.parse_expr()
        return FieldInit(name=name_tok.text, value=value)

    def _parse_struct_literal(self, type_name: str) -> StructLiteral:
        self._expect(Delimiter(DelimiterKind.LBRACE))
        fields: list[FieldInit] = []
        if not self._check(Delimiter(DelimiterKind.RBRACE)):
            fields.append(self._parse_field_init())
            while self._check(Delimiter(DelimiterKind.COMMA)):
                self._advance()
                if self._check(Delimiter(DelimiterKind.RBRACE)):
                    break
                fields.append(self._parse_field_init())
        self._expect(Delimiter(DelimiterKind.RBRACE))
        return StructLiteral(type_name=type_name, fields=fields)

    def _parse_array_literal(self) -> ArrayLiteral:
        """[N]T{...} atau [_]T{...} (type_system.md)."""
        self._expect(Delimiter(DelimiterKind.LBRACKET))
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

        # element type -- parser type parsing didelegasikan ke method
        # yang disediakan Parser induk (lihat parser.py: _parse_type_expr)
        element_type = self._parse_type_expr()  # type: ignore[attr-defined]

        self._expect(Delimiter(DelimiterKind.LBRACE))
        elements: list[Expr] = []
        if not self._check(Delimiter(DelimiterKind.RBRACE)):
            elements.append(self.parse_expr())
            while self._check(Delimiter(DelimiterKind.COMMA)):
                self._advance()
                if self._check(Delimiter(DelimiterKind.RBRACE)):
                    break
                elements.append(self.parse_expr())
        self._expect(Delimiter(DelimiterKind.RBRACE))
        return ArrayLiteral(size=size, element_type=element_type, elements=elements)

    def _parse_if_expr(self) -> IfExpr:
        """
        if cond expr [else expr]              -- single expression
        if cond { stmt...; ret v; } [else ...] -- block, value dari
                                                   ret eksplisit

        else OPSIONAL di level parser -- validasi "wajib ada kalau
        dipakai sebagai value" adalah tugas checker (parser be stupid,
        tidak tahu konteks pemakaian node ini). Tidak ada else-if
        berantai untuk bentuk ekspresi (sengaja dibatasi).

        Titik-koma HANYA di paling akhir seluruh struktur if/else,
        TIDAK PERNAH di antara then-branch dan 'else':
            if condition logic();                   -- 1 titik-koma
            if condition logic() else other();       -- 1 titik-koma,
                                                         di paling akhir
        Parser di sini TIDAK mengonsumsi titik-koma apa pun -- itu
        tanggung jawab caller (StmtParser._parse_if_as_stmt) setelah
        seluruh if/else selesai di-parse.
        """
        self._expect(Keyword(KeywordKind.IF))
        cond = self.parse_expr_no_struct_literal()
        then_branch = self._parse_if_branch()
        else_branch = None
        if self._check(Keyword(KeywordKind.ELSE)):
            self._advance()
            else_branch = self._parse_if_branch()
        return IfExpr(cond=cond, then_branch=then_branch, else_branch=else_branch)

    def _parse_if_branch(self):
        """
        Satu cabang if/else -- tiga kemungkinan:
          { stmt...; }  -> block, list[Stmt]
          if ...        -> ELSE-IF sebagai NESTED statement (bukan
                            struktur "elif" khusus -- ini valid HANYA
                            untuk pemakaian if sebagai STATEMENT, bukan
                            ekspresi/value; nested if di sini dibungkus
                            sebagai list[Stmt] berisi satu ExprStmt(IfExpr))
          expr lain     -> single Expr

        _parse_block_via_stmt_parser()/_parse_if_as_stmt_for_nested()
        disediakan StmtParser lewat multiple inheritance di kelas
        Parser gabungan (parser.py).
        """
        if self._check(Delimiter(DelimiterKind.LBRACE)):
            return self._parse_block_via_stmt_parser()  # type: ignore[attr-defined]
        if self._check(Keyword(KeywordKind.IF)):
            # else-if berantai: simpan IfExpr itu sendiri supaya
            # else_branch berisi IfExpr (bentuk ekspresi), bukan
            # list[ExprStmt]. Caller yang memakai if sebagai statement
            # tetap dapat tree yang valid; checker yang memutuskan
            # apakah bentuk ini boleh dipakai sebagai value.
            return self._parse_if_expr()
        return self.parse_expr()
