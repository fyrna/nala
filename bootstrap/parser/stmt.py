# parser/stmt.py
"""
Statement parser -- if/while/for/match/let/defer/dst.
"""
from __future__ import annotations
from typing import Optional

from lexer.token import (
    Token, TokenKind, Keyword, Operator, Delimiter, Literal, Special,
    KeywordKind, OperatorKind, DelimiterKind, LiteralKind, SpecialKind,
    describe_token_kind,
)
from nala_ast.nodes import (
    Stmt, ReturnStmt, LoopStmt, ForStmt, ForInStmt, AssignStmt,
    ExprStmt, ContinueStmt, BreakStmt, DeferStmt, LetStmt, MatchStmt,
    MatchArm, Pattern, WildcardPattern, BindPattern, LiteralPattern,
    RangePattern, OrPattern, VariantPattern, StructPattern,
    AtBindPattern, Expr, Ident, IfExpr,
)


class ParseError(Exception):
    pass


_ASSIGN_OPS = {
    Operator(OperatorKind.EQ): "=",
    Operator(OperatorKind.PLUS_EQ): "+=",
    Operator(OperatorKind.MINUS_EQ): "-=",
    Operator(OperatorKind.STAR_EQ): "*=",
    Operator(OperatorKind.SLASH_EQ): "/=",
    Operator(OperatorKind.PERCENT_EQ): "%=",
}

# Token yang MENANDAI awal sebuah statement penuh (bukan expression) --
# dipakai _parse_match_arm() untuk disambiguasi "body arm ini statement
# atau expression tunggal".
_STMT_STARTER_KEYWORDS = frozenset({
    Keyword(KeywordKind.RET),
    Keyword(KeywordKind.BREAK),
    Keyword(KeywordKind.CONTINUE),
    Keyword(KeywordKind.DEFER),
    Keyword(KeywordKind.LET),
    Keyword(KeywordKind.IF),
    Keyword(KeywordKind.FOR),
    Keyword(KeywordKind.LOOP),
    Keyword(KeywordKind.UNSAFE),
})


class StmtParser:
    """
    Mixin, sama pola dengan ExprParser -- butuh self._current/_advance/
    dst dari Parser induk, DAN butuh self.parse_expr() dari ExprParser
    (Parser utama menggabungkan keduanya lewat multiple inheritance,
    lihat parser.py).

    Method-method berikut SENGAJA TIDAK dideklarasikan sebagai stub
    '...' di sini -- stub semacam itu terbukti berbahaya dalam skema
    multiple inheritance (lihat catatan di ExprParser: MRO bisa membuat
    stub kosong "menutupi" implementasi asli dari mixin lain). Kontrak
    yang diharapkan tersedia dari Parser gabungan (parser.py):
      _current() -> Token
      _peek(offset: int = 1) -> Optional[Token]
      _advance() -> Token
      _check(kind: TokenKind) -> bool
      _expect(kind: TokenKind) -> Token
      parse_expr() -> Expr           (dari ExprParser)
      parse_expr_no_struct_literal() -> Expr  (dari ExprParser)
    """

    # ========================================================================
    # Entry point -- satu statement
    # ========================================================================

    def parse_stmt(self) -> Stmt:
        tok = self._current()

        if tok.kind == Keyword(KeywordKind.UNSAFE) and self._peek() is not None and self._peek().kind == Keyword(KeywordKind.LET):
            # unsafe let x = ...; -- treat `unsafe` HANYA valid di sini
            # menempel LANGSUNG ke `let` (pointer.md/error_handling.md:
            # tidak ada bentuk `unsafe { }` block berdiri sendiri, HANYA
            # `unsafe let` dan `unsafe fn` -- lihat _parse_fn_decl()
            # untuk modifier fn, terpisah dari sini). Kalau UNSAFE
            # ditemukan TAPI token setelahnya BUKAN LET, itu BUKAN
            # bentuk valid apa pun sebagai statement -- dibiarkan jatuh
            # ke fallback di bawah (_parse_expr_or_assign_stmt), yang
            # akan gagal alami dengan pesan "unexpected token" dari
            # ExprParser (UNSAFE bukan awal expression yang sah).
            self._advance()  # consume UNSAFE
            return self._parse_let_stmt(is_unsafe=True)
        if tok.kind == Keyword(KeywordKind.LET):
            return self._parse_let_stmt()
        if tok.kind == Keyword(KeywordKind.RET):
            return self._parse_return_stmt()
        if tok.kind == Keyword(KeywordKind.IF):
            # if SEKARANG SATU node (IfExpr) untuk statement maupun
            # sub-ekspresi -- lihat nodes.py & expr.py. Sebagai
            # statement, hasilnya dibungkus ExprStmt. Titik-koma HANYA
            # wajib kalau then/else branch bukan block (persis
            # language.md: "if condition logic();" tetap butuh ';',
            # tapi "if cond { ... }" tidak butuh ';' tambahan setelah
            # '}').
            return self._parse_if_as_stmt()
        if tok.kind == Keyword(KeywordKind.MATCH):
            return self._parse_match_stmt(is_comp=False)
        if tok.kind == Keyword(KeywordKind.COMP) and self._peek() is not None and self._peek().kind == Keyword(KeywordKind.MATCH):
            self._advance()  # consume COMP
            return self._parse_match_stmt(is_comp=True)
        if tok.kind == Keyword(KeywordKind.FOR):
            return self._parse_for_stmt()
        if tok.kind == Keyword(KeywordKind.LOOP):
            return self._parse_loop_stmt()
        if tok.kind == Keyword(KeywordKind.BREAK):
            return self._parse_break_stmt()
        if tok.kind == Keyword(KeywordKind.CONTINUE):
            return self._parse_continue_stmt()
        if tok.kind == Keyword(KeywordKind.DEFER):
            return self._parse_defer_stmt()
        # `fallthrough` DIHAPUS TOTAL dari bahasa -- cabang dispatch
        # untuk ini SENGAJA tidak ada lagi (lihat lexer/token.py).

        # Fallback: expression statement, atau assignment (target diketahui
        # setelah parse expr pertama, baru cek apakah diikuti operator assign)
        return self._parse_expr_or_assign_stmt()

    def parse_block(self) -> list[Stmt]:
        """{ stmt; stmt; ... }"""
        self._expect(Delimiter(DelimiterKind.LBRACE))
        stmts: list[Stmt] = []
        while not self._check(Delimiter(DelimiterKind.RBRACE)):
            stmts.append(self.parse_stmt())
        self._expect(Delimiter(DelimiterKind.RBRACE))
        return stmts

    # ========================================================================
    # let
    # ========================================================================

    def _parse_let_stmt(self, is_unsafe: bool = False) -> LetStmt:
        """
        let selalu wajib diinisialisasi (tidak ada bentuk `let x: T;`
        tanpa nilai -- keputusan bahasa yang sudah disepakati, konsisten
        dengan NLetStmt di NIR). Parser TIDAK perlu logic khusus untuk
        menolak bentuk tanpa nilai -- self._expect(Operator(OperatorKind.EQ)) di
        bawah SUDAH secara struktural memaksa ada '=' diikuti expr.

        Dua 'mut' TERPISAH secara posisi (memory_management.md):
          let mut x        -- binding mutability, 'mut' SEBELUM nama
          let x: mut T     -- value mutability, 'mut' SETELAH ':'
          let mut x: mut T -- keduanya sekaligus, independen

        `is_unsafe` -- SUDAH diputuskan & Keyword(KeywordKind.UNSAFE) SUDAH
        di-consume oleh caller (parse_stmt()) SEBELUM method ini
        dipanggil -- method ini TIDAK mengecek/consume UNSAFE sendiri,
        cukup menerima keputusan itu sebagai parameter dan meneruskannya
        ke LetStmt yang dihasilkan.
        """
        self._expect(Keyword(KeywordKind.LET))
        is_binding_mut = False
        if self._check(Keyword(KeywordKind.MUT)):
            self._advance()
            is_binding_mut = True
        name_tok = self._expect(Literal(LiteralKind.IDENT))
        type_expr = None
        is_value_mut = False
        if self._check(Delimiter(DelimiterKind.COLON)):
            self._advance()
            if self._check(Keyword(KeywordKind.MUT)):
                self._advance()
                is_value_mut = True
            type_expr = self._parse_type_expr()  # type: ignore[attr-defined]
        self._expect(Operator(OperatorKind.EQ))
        value = self.parse_expr()
        self._expect(Delimiter(DelimiterKind.SEMICOLON))
        return LetStmt(
            name=name_tok.text, value=value, type=type_expr,
            is_binding_mut=is_binding_mut, is_value_mut=is_value_mut,
            is_unsafe=is_unsafe,
        )

    # ========================================================================
    # ret
    # ========================================================================

    def _parse_return_stmt(self) -> ReturnStmt:
        self._expect(Keyword(KeywordKind.RET))
        if self._check(Delimiter(DelimiterKind.SEMICOLON)):
            self._advance()
            return ReturnStmt(expr=None)  # ret; -- valid untuk fn -> void
        expr = self.parse_expr()
        self._expect(Delimiter(DelimiterKind.SEMICOLON))
        return ReturnStmt(expr=expr)

    # ========================================================================
    # if (statement form -- beda dari IfExpr di expr.py)
    # ========================================================================

    def _parse_if_as_stmt(self) -> ExprStmt:
        """
        if dipakai sebagai statement -- delegasikan seluruh parsing ke
        _parse_if_expr() (ExprParser), hasilnya dibungkus ExprStmt.
        Titik-koma wajib HANYA kalau branch terakhir yang di-parse
        bukan block (single-expr form, konsisten dengan aturan umum
        semicolon language.md -- "setiap statement diakhiri ';'"; block
        '{ }' sendiri sudah jadi delimiter, tidak butuh ';' tambahan).
        """
        if_expr = self._parse_if_expr()  # type: ignore[attr-defined]
        self._maybe_expect_semicolon_for_if(if_expr)
        return ExprStmt(expr=if_expr)

    def _parse_if_as_stmt_for_nested(self) -> ExprStmt:
        """
        Sama seperti _parse_if_as_stmt(), TAPI tidak mengonsumsi
        titik-koma sendiri -- dipakai untuk kasus 'else if ...' berantai
        (nested), di mana titik-koma di akhir adalah tanggung jawab
        _parse_if_as_stmt() di level PALING LUAR (top-level if),
        bukan tiap level nested if.
        """
        if_expr = self._parse_if_expr()  # type: ignore[attr-defined]
        return ExprStmt(expr=if_expr)

    def _maybe_expect_semicolon_for_if(self, if_expr: IfExpr) -> None:
        last_branch = if_expr.else_branch if if_expr.else_branch is not None else if_expr.then_branch
        if not isinstance(last_branch, list):  # bentuk single-expr, bukan block
            self._expect(Delimiter(DelimiterKind.SEMICOLON))

    def _parse_block_via_stmt_parser(self) -> list[Stmt]:
        """Dipanggil ExprParser._parse_if_branch() untuk parsing block '{ ... }'."""
        return self.parse_block()

    def _parse_stmt_body(self) -> list[Stmt]:
        """
        Body if/for/dst -- boleh block { ... } ATAU single statement
        tanpa kurung kurawal (language.md: "Kurung kurawal opsional
        untuk single statement, tetap wajib ';'").
        """
        if self._check(Delimiter(DelimiterKind.LBRACE)):
            return self.parse_block()
        return [self.parse_stmt()]

    # ========================================================================
    # for -- 4 bentuk (language.md)
    # ========================================================================

    def _parse_for_stmt(self) -> Stmt:
        """
        for -- 2 bentuk:
          for item in ... / for i, item in ...  -- iterasi
          for cond { ... }                      -- while-style
        """
        self._expect(Keyword(KeywordKind.FOR))

        # for item in ... / for i, item in ...
        if self._check(Literal(LiteralKind.IDENT)) and self._is_for_in_ahead():
            return self._parse_for_in_stmt()

        # for cond { ... } -- while-style
        cond = self.parse_expr_no_struct_literal()
        body = self._parse_stmt_body()
        return ForStmt(cond=cond, body=body)

    def _parse_loop_stmt(self) -> LoopStmt:
        """
        loop { ... } -- infinite loop
        """
        self._expect(Keyword(KeywordKind.LOOP))
        body = self.parse_block()
        return LoopStmt(body=body)

    def _is_for_in_ahead(self) -> bool:
        """
        Lookahead: apakah pola saat ini 'IDENT in' atau 'IDENT , IDENT in'?
        Dibedakan dari while-style yang juga bisa mulai dengan IDENT
        (mis. `for count < 10 { ... }` -- IDENT diikuti operator
        perbandingan, bukan 'in'/',').
        """
        if self._peek() is not None and self._peek().kind == Keyword(KeywordKind.IN):
            return True
        if self._peek() is not None and self._peek().kind == Delimiter(DelimiterKind.COMMA):
            after_comma = self._peek(3)  # IDENT , IDENT in -> offset 3 = 'in'?
            return after_comma is not None and after_comma.kind == Keyword(KeywordKind.IN)
        return False

    def _parse_for_in_stmt(self) -> ForInStmt:
        first_tok = self._expect(Literal(LiteralKind.IDENT))
        index_name = None
        var_name = first_tok.text
        if self._check(Delimiter(DelimiterKind.COMMA)):
            self._advance()
            second_tok = self._expect(Literal(LiteralKind.IDENT))
            index_name = first_tok.text
            var_name = second_tok.text
        self._expect(Keyword(KeywordKind.IN))
        iterable = self.parse_expr_no_struct_literal()
        body = self._parse_stmt_body()
        return ForInStmt(index_name=index_name, var_name=var_name, iterable=iterable, body=body)

    # ========================================================================
    # break / continue -- dengan label opsional
    # ========================================================================

    def _parse_break_stmt(self) -> BreakStmt:
        self._expect(Keyword(KeywordKind.BREAK))
        label = None
        if self._check(Delimiter(DelimiterKind.COLON)):
            self._advance()
            label_tok = self._expect(Literal(LiteralKind.IDENT))
            label = label_tok.text
        self._expect(Delimiter(DelimiterKind.SEMICOLON))
        return BreakStmt(label=label)

    def _parse_continue_stmt(self) -> ContinueStmt:
        self._expect(Keyword(KeywordKind.CONTINUE))
        label = None
        if self._check(Delimiter(DelimiterKind.COLON)):
            self._advance()
            label_tok = self._expect(Literal(LiteralKind.IDENT))
            label = label_tok.text
        self._expect(Delimiter(DelimiterKind.SEMICOLON))
        return ContinueStmt(label=label)

    # ========================================================================
    # defer
    # ========================================================================

    def _parse_defer_stmt(self) -> DeferStmt:
        self._expect(Keyword(KeywordKind.DEFER))
        if self._check(Delimiter(DelimiterKind.LBRACE)):
            body = self.parse_block()
        else:
            expr = self.parse_expr()
            self._expect(Delimiter(DelimiterKind.SEMICOLON))
            body = [ExprStmt(expr=expr)]
        return DeferStmt(body=body)

    # ========================================================================
    # match / comp match -- TITIK PERBAIKAN UTAMA dari versi lama
    # ========================================================================

    def _parse_match_stmt(self, is_comp: bool) -> MatchStmt:
        self._expect(Keyword(KeywordKind.MATCH))
        expr = self.parse_expr_no_struct_literal()
        self._expect(Delimiter(DelimiterKind.LBRACE))
        arms: list[MatchArm] = []
        while not self._check(Delimiter(DelimiterKind.RBRACE)):
            arms.append(self._parse_match_arm())
        self._expect(Delimiter(DelimiterKind.RBRACE))
        return MatchStmt(expr=expr, arms=arms, is_comp=is_comp)

    def _parse_match_arm(self) -> MatchArm:
        """
        pattern [if guard] => body

        body BISA berupa:
          { stmt...; }     -- block
          statement single -- ret v;  fallthrough;  dst (BUKAN cuma
                               expression -- pattern_matching.md
                               menunjukkan arm body bisa statement
                               penuh seperti "log(...); fallthrough")
          expr single      -- print! v (tanpa ';' tambahan kalau arm
                               dipisah koma/langsung diikuti arm lain)

        Disambiguasi: kalau token setelah '=>' adalah salah satu
        statement-starter keyword (RET, BREAK, CONTINUE, DEFER, MATCH,
        LET, IF, FOR), delegasikan ke parse_stmt() penuh -- itu sudah
        menangani titik-koma sendiri. Selain itu, treat sebagai
        expression tunggal (ExprStmt).
        """
        pattern = self._parse_pattern()
        guard = None
        if self._check(Keyword(KeywordKind.IF)):
            self._advance()
            guard = self.parse_expr()
        self._expect(Delimiter(DelimiterKind.FAT_ARROW))
        if self._check(Delimiter(DelimiterKind.LBRACE)):
            body = self.parse_block()
        elif self._current().kind in _STMT_STARTER_KEYWORDS:
            body = [self.parse_stmt()]
        else:
            expr = self.parse_expr()
            body = [ExprStmt(expr=expr)]
            if self._check(Delimiter(DelimiterKind.SEMICOLON)):
                self._advance()
        return MatchArm(pattern=pattern, body=body, guard=guard)

    def _parse_pattern(self) -> Pattern:
        """
        Pattern top-level -- handle OR pattern (a | b | c) di level ini,
        delegasikan ke _parse_pattern_atom() untuk satu pattern individual.
        """
        first = self._parse_pattern_atom()
        if self._check(Operator(OperatorKind.PIPE)):
            alternatives = [first]
            while self._check(Operator(OperatorKind.PIPE)):
                self._advance()
                alternatives.append(self._parse_pattern_atom())
            return OrPattern(alternatives=alternatives)
        return first

    def _parse_pattern_atom(self) -> Pattern:
        tok = self._current()

        # Wildcard
        if tok.kind == Literal(LiteralKind.IDENT) and tok.text == "_":
            self._advance()
            return WildcardPattern()

        # Grouped pattern: ( pattern )
        if tok.kind == Delimiter(DelimiterKind.LPAREN):
            self._advance()
            inner = self._parse_pattern()
            self._expect(Delimiter(DelimiterKind.RPAREN))
            return self._maybe_range_or_at(inner)

        if tok.kind == Delimiter(DelimiterKind.DOT):
            return self._parse_variant_or_struct_pattern()

        # Struct destructuring TANPA leading-dot juga tidak didukung
        # sengaja -- pattern_matching.md contohnya SELALU pakai bentuk
        # struct literal biasa `.{ field }` (leading-dot), konsisten
        # dengan leading-dot inference type_system.md.

        # Binding polos, literal, atau range -- disambiguasi:
        # identifier yang bukan wildcard = BindPattern, KECUALI diikuti
        # '@' (AtBindPattern) atau '..'/'..<' (RangePattern dari const).
        if tok.kind == Literal(LiteralKind.IDENT):
            self._advance()
            name = tok.text
            if self._check(Operator(OperatorKind.AT)):
                self._advance()
                inner = self._parse_pattern_atom()
                return AtBindPattern(name=name, inner=inner)
            # Identifier polos tanpa '@' -- BindPattern (match apa pun,
            # bind ke nama itu). Const pattern (mis. EOF, TAB) SECARA
            # SINTAKSIS terlihat identik dengan BindPattern di sini --
            # parser TIDAK tahu apakah "EOF" adalah const atau binding
            # baru (itu makna semantik, keputusan checker -- "be
            # stupid"). BindPattern dipakai sebagai representasi
            # default untuk IDENT polos; checker yang membedakan const
            # vs fresh-binding berdasarkan symbol table.
            return BindPattern(name=name)

        # Literal pattern (int/float/string/bool), termasuk kemungkinan
        # range (90..100)
        if tok.kind in (Literal(LiteralKind.INT_LITERAL), Literal(LiteralKind.FLOAT_LITERAL),
                        Literal(LiteralKind.STRING_LITERAL), Keyword(KeywordKind.TRUE), Keyword(KeywordKind.FALSE),
                        Literal(LiteralKind.BYTE_LITERAL)):
            literal_expr = self._parse_pattern_literal_expr()
            return self._maybe_range_or_at(LiteralPattern(value=literal_expr))

        raise ParseError(f"Unexpected token in pattern: {describe_token_kind(tok.kind)} at {tok.span}")

    def _parse_pattern_literal_expr(self) -> Expr:
        """Parse satu literal sebagai Expr (dipakai LiteralPattern/RangePattern batas)."""
        # Delegasikan ke expr parser -- literal adalah subset primary expr.
        return self.parse_expr()  # type: ignore[misc]

    def _maybe_range_or_at(self, pattern: Pattern) -> Pattern:
        """
        Setelah pattern atom (literal/grouped), cek apakah diikuti
        '..'/'..<' (range) -- pattern harus berbentuk LiteralPattern
        untuk sisi kiri range yang valid (checker yang validasi, parser
        cuma mencatat bentuknya).
        """
        if self._check(Operator(OperatorKind.RANGE)) or self._check(Operator(OperatorKind.RANGE_EXCL)):
            inclusive = self._check(Operator(OperatorKind.RANGE))
            self._advance()
            high = self._parse_pattern_literal_expr()
            low = pattern.value if isinstance(pattern, LiteralPattern) else None
            return RangePattern(low=low, high=high, inclusive=inclusive)
        return pattern

    def _parse_variant_or_struct_pattern(self) -> Pattern:
        """
        Setelah DOT dikonsumsi konteks pattern -- 3 kemungkinan, sama
        polanya dengan leading-dot di expr.py:
          .{ field, ... }      -> StructPattern
          .Variant              -> VariantPattern (bindings kosong)
          .Variant(p1, p2, ...) -> VariantPattern (bindings terisi)
        """
        self._advance()  # consume DOT

        if self._check(Delimiter(DelimiterKind.LBRACE)):
            return self._parse_struct_pattern()

        name_tok = self._expect(Literal(LiteralKind.IDENT))
        bindings: list[Pattern] = []
        if self._check(Delimiter(DelimiterKind.LPAREN)):
            self._advance()
            if not self._check(Delimiter(DelimiterKind.RPAREN)):
                bindings.append(self._parse_pattern())
                while self._check(Delimiter(DelimiterKind.COMMA)):
                    self._advance()
                    bindings.append(self._parse_pattern())
            self._expect(Delimiter(DelimiterKind.RPAREN))
        variant_pattern = VariantPattern(variant_name=name_tok.text, bindings=bindings)
        return self._maybe_at_bind_wrap(variant_pattern)

    def _maybe_at_bind_wrap(self, pattern: Pattern) -> Pattern:
        """Untuk kasus seperti .Circle(r @ 1..10) -- '@' di DALAM bindings
        sudah ditangani _parse_pattern_atom rekursif; ini untuk '@' yang
        menempel LANGSUNG setelah keseluruhan variant pattern (jarang,
        tapi dijaga konsisten)."""
        return pattern

    def _parse_struct_pattern(self) -> StructPattern:
        self._expect(Delimiter(DelimiterKind.LBRACE))
        fields: list[tuple[str, "Pattern | None"]] = []
        ignore_rest = False
        if not self._check(Delimiter(DelimiterKind.RBRACE)):
            self._parse_struct_pattern_field(fields, ignore_rest_ref := [False])
            ignore_rest = ignore_rest_ref[0]
            while self._check(Delimiter(DelimiterKind.COMMA)) and not ignore_rest:
                self._advance()
                if self._check(Delimiter(DelimiterKind.RBRACE)):
                    break
                self._parse_struct_pattern_field(fields, ignore_rest_ref)
                ignore_rest = ignore_rest_ref[0]
        self._expect(Delimiter(DelimiterKind.RBRACE))
        return StructPattern(fields=fields, ignore_rest=ignore_rest)

    def _parse_struct_pattern_field(self, fields: list, ignore_rest_ref: list) -> None:
        if self._check(Operator(OperatorKind.RANGE)):  # '..' -- explicit ignore rest
            self._advance()
            ignore_rest_ref[0] = True
            return
        name_tok = self._expect(Literal(LiteralKind.IDENT))
        if self._check(Delimiter(DelimiterKind.COLON)):
            self._advance()
            sub_pattern = self._parse_pattern()
            fields.append((name_tok.text, sub_pattern))
        else:
            fields.append((name_tok.text, None))  # bind ke nama field itu sendiri

    # ========================================================================
    # Expression statement / assignment
    # ========================================================================

    def _parse_expr_or_assign_stmt(self) -> Stmt:
        expr = self.parse_expr()
        if self._current().kind in _ASSIGN_OPS:
            op_tok = self._advance()
            value = self.parse_expr()
            self._expect(Delimiter(DelimiterKind.SEMICOLON))
            return AssignStmt(target=expr, value=value, op=_ASSIGN_OPS[op_tok.kind])
        self._expect(Delimiter(DelimiterKind.SEMICOLON))
        return ExprStmt(expr=expr)
