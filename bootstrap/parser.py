"""
bootstrap/parser.py

Parser Python yang membangun AST dari token stream yang dihasilkan lexer.py.

ARSITEKTUR DAN DESAIN:

Parser adalah komponen frontend kedua setelah lexer. Tugasnya:
    1. Mengubah token stream menjadi AST (Abstract Syntax Tree)
    2. Memastikan sintaks program Nala valid
    3. Menghasilkan AST "raw" dengan node netral (DottedAccess/DottedCall)

PRINSIP DESAIN PENTING:
    - Parser TIDAK membuat keputusan semantik
    - Parser TIDAK tahu tentang tipe data atau deklarasi
    - Parser hanya mengenali struktur sintaks berdasarkan token
    - Disambiguasi (enum vs union vs field access) dilakukan oleh type checker

ALUR KERJA:
    Token Stream (dari lexer)
        ↓
    Parser.parse_program()
        ↓ parse deklarasi top-level
    Declarations: const, fn, internal fn
        ↓ parse body
    Statements: if, for, match, let, assignment, return, dll
        ↓ parse expressions
    Expressions: binary, unary, call, literal, dotted, dll
        ↓
    AST Raw (dengan DottedAccess/DottedCall)

CATATAN PENTING:
    - Parser menggunakan recursive descent dengan precedence climbing
    - Lookahead minimal (hanya 1 token)
    - Error handling: ParseError exception untuk error fatal
    - Save/restore state untuk backtracking (struct literal parsing)
"""

from __future__ import annotations

from lexer import Lexer, Token, TokenKind
from nala_ast import (
    EnumDecl, StructDecl, StructField, UnionDecl, UnionVariant,
    Expr, Stmt, Ident, StringLiteral, IntLiteral, ByteLiteral,
    BinaryExpr, UnaryExpr, CallExpr, FieldAccess, IntrinsicCall,
    IfExpr, ElifClause, MatchArm, MatchStmt, UnionLiteral,
    Param, ReturnStmt, IfStmt, WhileStmt, AssignStmt, ExprStmt, LetStmt, FnDecl, SelfParam,
    ContinueStmt, BreakStmt, StructLiteral,
    DottedAccess, DottedCall,
    ArrayLiteral, ArrayIndex,
)


class ParseError(Exception):
    """
    Kegagalan parsing yang sifatnya fatal.

    Exception ini dilempar ketika:
        - Token tidak sesuai dengan yang diharapkan
        - Struktur sintaks tidak valid
        - Ada token yang tidak bisa diparse

    Error handling:
        - Parser akan berhenti dan melaporkan error
        - Tidak ada recovery mechanism (fail-fast)
        - Error message mencakup posisi (baris, kolom)
    """
    pass


class Parser:
    """
    Parser utama untuk bahasa Nala - recursive descent parser.

    State:
        - _lexer: Lexer instance untuk mendapatkan token
        - _current: Token saat ini (lookahead 1)
        - _struct_name: Nama struct yang sedang diparse (untuk methods)

    METODE PARSING:
        parse_program() -> parse_decl() -> parse_fn_decl() / parse_struct_body()
        parse_stmt() -> parse_if_stmt() / parse_for_stmt() / parse_match_stmt()
        parse_expr() -> parse_if_expr() -> parse_or() -> parse_and() -> 
                       parse_comparison() -> parse_additive() -> parse_unary() -> 
                       parse_primary()

    PRECEDENCE (dari rendah ke tinggi):
        1. if expression (terendah)
        2. or
        3. and
        4. comparison (==, >=, <=, >, <)
        5. additive (+, -)
        6. unary (!)
        7. primary (ident, literal, call, dotted, dll) (tertinggi)

    INSPIRASI:
        - Rust's parser (recursive descent dengan precedence climbing)
        - Python's parser (LL(1) dengan lookahead 1)
    """

    def __init__(self, source: str):
        """Inisialisasi parser dengan source code Nala."""
        self._lexer = Lexer(source)
        self._current: Token = self._lexer.next_token()
        self._struct_name: str | None = None  # Track struct untuk method parsing

    def _advance(self) -> Token:
        """
        Maju ke token berikutnya dan kembalikan token sebelumnya.

        Returns:
            Token: Token yang baru saja dilewati (current sebelumnya)
        """
        tok = self._current
        self._current = self._lexer.next_token()
        return tok

    def _expect(self, kind: TokenKind) -> Token:
        """
        Verifikasi bahwa token saat ini memiliki kind yang diharapkan.

        Jika cocok, maju ke token berikutnya dan kembalikan token yang cocok.
        Jika tidak cocok, lempar ParseError dengan pesan yang informatif.

        Args:
            kind (TokenKind): Jenis token yang diharapkan

        Returns:
            Token: Token yang cocok

        Raises:
            ParseError: Jika token saat ini tidak sesuai dengan yang diharapkan
        """
        if self._current.kind != kind:
            raise ParseError(
                f"Diharapkan {kind.name}, tapi ketemu {self._current.kind.name} "
                f"({self._current.text!r}) di baris {self._current.span.line}, "
                f"kolom {self._current.span.col}"
            )
        return self._advance()

    def _save_state(self) -> tuple[int, int, int, Token]:
        """
        Simpan state parser saat ini untuk backtracking.

        Digunakan ketika mencoba parse struct literal (yang bisa gagal
        dan perlu rollback).

        Returns:
            tuple: (pos, line, col, current_token)
        """
        return (self._lexer.pos, self._lexer.line, self._lexer.col, self._current)

    def _restore_state(self, state: tuple[int, int, int, Token]) -> None:
        """
        Kembalikan state parser ke state yang disimpan sebelumnya.

        Args:
            state: State yang disimpan oleh _save_state()
        """
        self._lexer.pos, self._lexer.line, self._lexer.col, self._current = state

    def parse_program(self) -> list:
        """
        Entry point utama: parse seluruh source code.

        Mengumpulkan semua deklarasi top-level (const, fn, internal fn)
        sampai mencapai EOF.

        Returns:
            list: List of AST nodes (EnumDecl, StructDecl, UnionDecl, FnDecl)
        """
        decls = []
        while self._current.kind != TokenKind.EOF:
            decls.append(self._parse_decl())
        return decls

    def _parse_decl(self):
        """
        Parse satu deklarasi top-level.

        Format:
            const Name = enum { ... }
            const Name = struct { ... }
            const Name = union { ... }
            fn name(...) -> type { ... }
            internal fn name(...) -> type { ... }

        Returns:
            AST node: EnumDecl | StructDecl | UnionDecl | FnDecl

        Raises:
            ParseError: Jika deklarasi tidak valid
        """
        # Cek internal fn terlebih dahulu
        if self._current.kind == TokenKind.FN:
            return self._parse_fn_decl(is_internal=False)
        if self._current.kind == TokenKind.IDENT and self._current.text == "internal":
            self._advance()
            self._expect(TokenKind.FN)
            return self._parse_fn_decl(is_internal=True, fn_already_consumed=True)

        # Harus 'const' (semua deklarasi tipe dimulai dengan const)
        const_tok = self._expect(TokenKind.IDENT)
        if const_tok.text != "const":
            raise ParseError(
                f"Diharapkan 'const', 'fn', atau 'internal fn', tapi ketemu "
                f"{const_tok.text!r} di baris {const_tok.span.line}"
            )

        name_tok = self._expect(TokenKind.IDENT)
        name = name_tok.text
        self._expect(TokenKind.EQ)
        kind_tok = self._expect(TokenKind.IDENT)

        # Tentukan jenis deklarasi berdasarkan keyword setelah '='
        if kind_tok.text == "enum":
            result = self._parse_enum_body(name)
        elif kind_tok.text == "struct":
            result = self._parse_struct_body(name)
        elif kind_tok.text == "union":
            result = self._parse_union_body(name)
        else:
            raise ParseError(
                f"Diharapkan 'enum', 'struct', atau 'union', tapi ketemu "
                f"{kind_tok.text!r} di baris {kind_tok.span.line}"
            )

        # Consume optional trailing semicolon after const declaration
        # (semicolon di akhir deklarasi adalah opsional)
        if self._current.kind == TokenKind.SEMICOLON:
            self._advance()

        return result

    def _parse_fn_decl(self, is_internal: bool, fn_already_consumed: bool = False, struct_name: str | None = None):
        """
        Parse deklarasi fungsi/method.

        Format:
            fn name(params) -> return_type { body }
            internal fn name(params) -> return_type { body }

        Method (dalam struct):
            fn method(&self, params) -> return_type { body }
            fn method(&mut self, params) -> return_type { body }

        Args:
            is_internal: Apakah fungsi adalah internal (built-in runtime)
            fn_already_consumed: Apakah token 'fn' sudah dikonsumsi
            struct_name: Nama struct jika ini adalah method

        Returns:
            FnDecl: AST node untuk fungsi
        """
        if not fn_already_consumed:
            self._expect(TokenKind.FN)

        name_tok = self._expect(TokenKind.IDENT)
        name = name_tok.text
        self._expect(TokenKind.LPAREN)

        # Parse self parameter (jika ada)
        self_param = self._parse_self_param()
        params = []

        # Jika ada self_param dan diikuti comma, lanjut ke parameter berikutnya
        if self_param is not None and self._current.kind == TokenKind.COMMA:
            self._advance()

        # Parse parameter-parameter fungsi
        while self._current.kind != TokenKind.RPAREN:
            param_name_tok = self._expect(TokenKind.IDENT)
            self._expect(TokenKind.COLON)
            param_type = self._parse_type()
            params.append(Param(param_name_tok.text, param_type))
            if self._current.kind == TokenKind.COMMA:
                self._advance()
            else:
                break
        self._expect(TokenKind.RPAREN)

        # Parse return type (opsional, default void)
        if self._current.kind == TokenKind.ARROW:
            self._advance()
            return_type_tok = self._expect(TokenKind.IDENT)
            return_type = return_type_tok.text
        else:
            return_type = "void"

        # Parse body (block of statements)
        old_struct_name = self._struct_name
        if struct_name is not None:
            self._struct_name = struct_name

        body = self._parse_block()
        self._struct_name = old_struct_name

        return FnDecl(
            name=name,
            params=params,
            return_type=return_type,
            body=body,
            is_internal=is_internal,
            self_param=self_param,
            struct_name=struct_name,
        )

    def _parse_self_param(self) -> SelfParam | None:
        """
        Parse self parameter untuk method.

        Format:
            &self         -> immutable reference (default)
            &mut self     -> mutable reference
            self          -> owned value (belum support)

        Returns:
            SelfParam | None: SelfParam jika ada, None jika tidak
        """
        if self._current.kind == TokenKind.AMPERSAND:
            self._advance()
            is_mut = False
            if self._current.kind == TokenKind.MUT:
                self._advance()
                is_mut = True
            if self._current.kind == TokenKind.IDENT and self._current.text == "self":
                self._advance()
                return SelfParam(is_mut=is_mut, is_ref=True)
            else:
                raise ParseError(
                    f"Diharapkan 'self' setelah & atau &mut, tapi ketemu "
                    f"{self._current.text!r} di baris {self._current.span.line}"
                )
        if self._current.kind == TokenKind.IDENT and self._current.text == "self":
            self._advance()
            return SelfParam(is_mut=False, is_ref=False)
        return None

    def _parse_type(self) -> str:
        """
        Parse tipe data.

        Format:
            ident            -> simple type (i32, str, Token)
            []ident          -> slice type ([]i32, []str)
            [N]ident         -> fixed array type ([3]i32, [5]str)

        Returns:
            str: Nama tipe dalam bentuk string
        """
        if self._current.kind == TokenKind.LBRACKET:
            self._advance()
            # [N]T -> fixed-size array
            if self._current.kind == TokenKind.INT_LITERAL:
                size_tok = self._advance()
                self._expect(TokenKind.RBRACKET)
                inner_tok = self._expect(TokenKind.IDENT)
                return f"[{size_tok.text}]{inner_tok.text}"
            # []T -> slice
            self._expect(TokenKind.RBRACKET)
            inner_tok = self._expect(TokenKind.IDENT)
            return f"[]{inner_tok.text}"
        else:
            type_tok = self._expect(TokenKind.IDENT)
            return type_tok.text

    def _parse_intrinsic(self, name: str) -> IntrinsicCall:
        """
        Parse intrinsic call: name!(args).

        Intrinsic adalah built-in function dengan syntax khusus:
            print!("hello")
            sizeof!(i32)
            assert!(cond)

        Returns:
            IntrinsicCall: AST node untuk intrinsic call
        """
        self._expect(TokenKind.LPAREN)
        args = []
        while self._current.kind != TokenKind.RPAREN:
            args.append(self._parse_expr())
            if self._current.kind == TokenKind.COMMA:
                self._advance()
            else:
                break
        self._expect(TokenKind.RPAREN)
        return IntrinsicCall(name, args)

    def _parse_enum_body(self, name: str) -> EnumDecl:
        """
        Parse body dari enum declaration.

        Format:
            enum {
                Variant1,
                Variant2,
                Variant3,
            }

        Returns:
            EnumDecl: AST node untuk enum
        """
        self._expect(TokenKind.LBRACE)
        variants = []
        while self._current.kind != TokenKind.RBRACE:
            variant_tok = self._expect(TokenKind.IDENT)
            variants.append(variant_tok.text)
            if self._current.kind == TokenKind.COMMA:
                self._advance()
            else:
                break
        self._expect(TokenKind.RBRACE)
        return EnumDecl(name=name, variants=variants)

    def _parse_union_body(self, name: str) -> UnionDecl:
        """
        Parse body dari union declaration.

        Format:
            union {
                VariantName,                    -- unit variant (tanpa payload)
                VariantName(Type),              -- variant dengan payload type
                VariantName(Type1, Type2),      -- multi-payload (belum support)
            }

        Returns:
            UnionDecl: AST node untuk union
        """
        self._expect(TokenKind.LBRACE)
        variants = []
        while self._current.kind != TokenKind.RBRACE:
            variant_tok = self._expect(TokenKind.IDENT)
            payload_types = []
            # Cek apakah diikuti '(' -> variant dengan payload type
            if self._current.kind == TokenKind.LPAREN:
                self._advance()  # konsumsi '('
                if self._current.kind != TokenKind.RPAREN:
                    payload_types.append(self._parse_type())
                    while self._current.kind == TokenKind.COMMA:
                        self._advance()
                        payload_types.append(self._parse_type())
                self._expect(TokenKind.RPAREN)
            # Kalau tidak ada '(', ini unit variant (payload_types tetap [])
            variants.append(UnionVariant(variant_tok.text, payload_types))
            if self._current.kind == TokenKind.COMMA:
                self._advance()
            else:
                break
        self._expect(TokenKind.RBRACE)
        return UnionDecl(name=name, variants=variants)

    def _parse_struct_body(self, name: str) -> StructDecl:
        """
        Parse body dari struct declaration.

        Format:
            struct {
                field1: Type,
                mut field2: Type,
                fn method(&self) -> Type { ... }
            }

        Returns:
            StructDecl: AST node untuk struct (termasuk methods)
        """
        self._expect(TokenKind.LBRACE)
        fields = []
        methods = []
        while self._current.kind != TokenKind.RBRACE:
            # Parse method
            if self._current.kind == TokenKind.FN:
                methods.append(self._parse_fn_decl(is_internal=False, struct_name=name))
                continue
            if self._current.kind == TokenKind.IDENT and self._current.text == "internal":
                self._advance()
                self._expect(TokenKind.FN)
                methods.append(self._parse_fn_decl(is_internal=True, fn_already_consumed=True, struct_name=name))
                continue
            # Parse field
            is_mut = False
            if self._current.kind == TokenKind.MUT:
                self._advance()
                is_mut = True
            field_name_tok = self._expect(TokenKind.IDENT)
            self._expect(TokenKind.COLON)
            field_type = self._parse_type()
            fields.append(StructField(field_name_tok.text, field_type, is_mut))
            if self._current.kind == TokenKind.COMMA:
                self._advance()
        self._expect(TokenKind.RBRACE)
        return StructDecl(name=name, fields=fields, methods=methods)

    # --- Expression Parsing ---
    # Precedence climbing dengan fungsi terpisah per level

    def _parse_expr(self) -> Expr:
        """Parse ekspresi dengan precedence terendah (if expression)."""
        return self._parse_if_expr()

    def _parse_if_expr(self) -> Expr:
        """
        Parse if expression (bukan statement).

        Format:
            if cond { then_expr } else { else_expr }

        If expression menghasilkan nilai, berbeda dengan if statement
        yang tidak menghasilkan nilai.
        """
        if (self._current.kind == TokenKind.IDENT and 
            self._current.text == "if"):
            self._advance()
            cond = self._parse_expr()
            self._expect(TokenKind.LBRACE)
            then_expr = self._parse_expr()
            self._expect(TokenKind.RBRACE)
            if not (self._current.kind == TokenKind.IDENT and self._current.text == "else"):
                raise ParseError(
                    f"Diharapkan 'else' setelah if expression, tapi ketemu "
                    f"{self._current.kind.name} ({self._current.text!r})"
                )
            self._advance()
            self._expect(TokenKind.LBRACE)
            else_expr = self._parse_expr()
            self._expect(TokenKind.RBRACE)
            return IfExpr(cond, then_expr, else_expr)
        return self._parse_or()

    def _parse_or(self) -> Expr:
        """Parse logical OR (precedence: rendah)."""
        left = self._parse_and()
        while self._current.kind == TokenKind.IDENT and self._current.text == "or":
            self._advance()
            right = self._parse_and()
            left = BinaryExpr("or", left, right)
        return left

    def _parse_and(self) -> Expr:
        """Parse logical AND (precedence: sedang)."""
        left = self._parse_comparison()
        while self._current.kind == TokenKind.IDENT and self._current.text == "and":
            self._advance()
            right = self._parse_comparison()
            left = BinaryExpr("and", left, right)
        return left

    def _parse_additive(self) -> Expr:
        """Parse additive expression (+, -) (precedence: tinggi)."""
        left = self._parse_unary()
        while self._current.kind == TokenKind.PLUS:
            self._advance()
            right = self._parse_unary()
            left = BinaryExpr("+", left, right)
        return left

    def _parse_comparison(self) -> Expr:
        """Parse comparison expression (==, >=, <=, >, <) (precedence: lebih tinggi)."""
        left = self._parse_additive()
        _COMPARISON_OPS = {
            TokenKind.EQ_EQ: "==",
            TokenKind.GT_EQ: ">=",
            TokenKind.LT_EQ: "<=",
            TokenKind.GT: ">",
            TokenKind.LT: "<",
        }
        if self._current.kind in _COMPARISON_OPS:
            op = _COMPARISON_OPS[self._current.kind]
            self._advance()
            right = self._parse_additive()
            return BinaryExpr(op, left, right)
        return left

    def _parse_unary(self) -> Expr:
        """Parse unary expression (!expr) (precedence: tertinggi)."""
        if self._current.kind == TokenKind.BANG:
            self._advance()
            operand = self._parse_unary()
            return UnaryExpr("!", operand)
        return self._parse_primary()

    def _parse_primary(self) -> Expr:
        """
        Parse primary expression (atom terkecil).

        Format:
            ident
            literal (string, int, byte)
            ident(...)          -> call
            ident!             -> intrinsic
            ident.name          -> dotted access (NETRAL)
            ident.name(...)     -> dotted call (NETRAL)
            ident { ... }       -> struct literal
            (expr)              -> parenthesized expression

        PRINSIP PENTING: Parser TIDAK melakukan disambiguasi semantik!
        - `base.name` bisa berupa field access, enum variant, atau union variant
        - `base.name(...)` bisa berupa method call atau union constructor
        - Disambiguasi dilakukan oleh type checker

        Stage0: hanya satu level dotted (`base.name`), belum chain (`a.b.c`).
        """
        if self._current.kind == TokenKind.IDENT:
            name_tok = self._advance()

            # --- Dotted access/call (NETRAL) ---
            # Parser tidak menebak makna, type checker yang akan resolve
            if self._current.kind == TokenKind.DOT:
                self._advance()  # konsumsi '.'
                name_tok2 = self._expect(TokenKind.IDENT)

                # Dotted call: base.name(args...)
                if self._current.kind == TokenKind.LPAREN:
                    self._advance()  # konsumsi '('
                    args = []
                    while self._current.kind != TokenKind.RPAREN:
                        args.append(self._parse_expr())
                        if self._current.kind == TokenKind.COMMA:
                            self._advance()
                        else:
                            break
                    self._expect(TokenKind.RPAREN)
                    return DottedCall(
                        base=Ident(name_tok.text),
                        name=name_tok2.text,
                        args=args,
                    )

                # Dotted access: base.name (tanpa kurung)
                return DottedAccess(
                    base=Ident(name_tok.text),
                    name=name_tok2.text,
                )

            # --- Intrinsic call: name!(args) ---
            if self._current.kind == TokenKind.BANG:
                self._advance()
                return self._parse_intrinsic(name_tok.text)

            # --- Function call: name(args) ---
            if self._current.kind == TokenKind.LPAREN:
                return self._parse_call(name_tok.text)

            # --- Struct literal: TypeName { field: value } ---
            if self._current.kind == TokenKind.LBRACE:
                # Coba parse struct literal dengan save/restore
                # Kalau gagal, kembalikan Ident saja
                saved = self._save_state()
                try:
                    return self._parse_struct_literal(name_tok.text)
                except ParseError:
                    self._restore_state(saved)
                    return Ident(name_tok.text)

            # --- Array index: ident[expr] ---
            target = Ident(name_tok.text)
            while self._current.kind == TokenKind.LBRACKET:
                self._advance()
                index_expr = self._parse_expr()
                self._expect(TokenKind.RBRACKET)
                target = ArrayIndex(obj=target, index=index_expr)
            return target

        # --- Literals ---
        elif self._current.kind == TokenKind.STRING_LITERAL:
            tok = self._advance()
            value = tok.text[1:-1]  # Remove quotes
            return StringLiteral(value)
        elif self._current.kind == TokenKind.INT_LITERAL:
            tok = self._advance()
            return IntLiteral(tok.text)
        elif self._current.kind == TokenKind.BYTE_LITERAL:
            tok = self._advance()
            value = tok.text[1:-1]  # Remove quotes
            return ByteLiteral(value)
        elif self._current.kind == TokenKind.INT_LITERAL:
            tok = self._advance()
            return Ident(tok.text)

        # --- Array literal: [1, 2, 3] ---
        elif self._current.kind == TokenKind.LBRACKET:
            self._advance()  # konsumsi '['
            elements = []
            while self._current.kind != TokenKind.RBRACKET:
                elements.append(self._parse_expr())
                if self._current.kind == TokenKind.COMMA:
                    self._advance()
                else:
                    break
            self._expect(TokenKind.RBRACKET)
            return ArrayLiteral(elements=elements)

        # --- Parenthesized expression ---
        elif self._current.kind == TokenKind.LPAREN:
            self._advance()
            inner = self._parse_expr()
            self._expect(TokenKind.RPAREN)
            return inner

        # --- Error ---
        else:
            raise ParseError(
                f"Diharapkan ekspresi, tapi ketemu {self._current.kind.name} "
                f"({self._current.text!r}) di baris {self._current.span.line}"
            )

    def _parse_struct_literal(self, type_name: str) -> StructLiteral:
        """
        Parse struct literal: TypeName { field: value, ... }.

        Contoh: Token { kind: TokenKind.EOF, text: "" }
        """
        self._expect(TokenKind.LBRACE)
        fields: list[tuple[str, Expr]] = []
        while self._current.kind != TokenKind.RBRACE:
            field_name_tok = self._expect(TokenKind.IDENT)
            self._expect(TokenKind.COLON)
            value = self._parse_expr()
            fields.append((field_name_tok.text, value))
            if self._current.kind == TokenKind.COMMA:
                self._advance()
            else:
                break
        self._expect(TokenKind.RBRACE)
        return StructLiteral(type_name=type_name, fields=fields)

    def _parse_call(self, callee: str) -> CallExpr:
        """
        Parse function call: callee(args).

        Contoh: print("hello"), len("test")
        """
        self._expect(TokenKind.LPAREN)
        args = []
        while self._current.kind != TokenKind.RPAREN:
            args.append(self._parse_expr())
            if self._current.kind == TokenKind.COMMA:
                self._advance()
            else:
                break
        self._expect(TokenKind.RPAREN)
        return CallExpr(callee, args)

    # --- Statement Parsing ---

    def _parse_stmt(self) -> Stmt:
        """
        Parse satu statement.

        Statement types:
            ret expr;          -> return
            if cond { ... }    -> if statement
            for cond { ... }   -> while loop
            match expr { ... } -> match statement
            continue;          -> continue
            break;             -> break
            let name = expr;   -> variable declaration
            target = expr;     -> assignment
            expr;              -> expression statement
        """
        # --- Control flow statements ---
        if self._current.kind == TokenKind.IDENT:
            if self._current.text == "ret":
                return self._parse_return_stmt()
            elif self._current.text == "if":
                return self._parse_if_stmt()
            elif self._current.text == "for":
                return self._parse_for_stmt()
            elif self._current.text == "match":
                return self._parse_match_stmt()
            elif self._current.text == "continue":
                self._advance()
                self._expect(TokenKind.SEMICOLON)
                return ContinueStmt()
            elif self._current.text == "break":
                self._advance()
                self._expect(TokenKind.SEMICOLON)
                return BreakStmt()

        # --- Let statement ---
        elif self._current.kind == TokenKind.LET:
            return self._parse_let_stmt()

        # --- Assignment or expression statement ---
        # Try parsing as assignment first, fallback to expression
        _ASSIGN_OPS = {
            TokenKind.EQ: "=",
            TokenKind.PLUS_EQ: "+=",
        }

        saved_state = self._save_state()
        try:
            target = self._parse_simple_target()
            if self._current.kind in _ASSIGN_OPS:
                op = _ASSIGN_OPS[self._current.kind]
                self._advance()
                value = self._parse_expr()
                self._expect(TokenKind.SEMICOLON)
                return AssignStmt(target, value, op=op)
            self._restore_state(saved_state)
        except ParseError:
            self._restore_state(saved_state)

        # --- Expression statement ---
        expr = self._parse_expr()
        self._expect(TokenKind.SEMICOLON)
        return ExprStmt(expr)

    def _parse_simple_target(self) -> Expr:
        """
        Parse assignment target (identifier, field access, atau array index).

        Format:
            ident
            ident.field
            ident[i]
            ident.field.subfield (belum support)

        Returns:
            Expr: Ident, FieldAccess, atau ArrayIndex
        """
        if self._current.kind != TokenKind.IDENT:
            raise ParseError("Diharapkan identifier untuk assignment target")
        name_tok = self._advance()
        target = Ident(name_tok.text)
        while True:
            if self._current.kind == TokenKind.DOT:
                self._advance()
                field_tok = self._expect(TokenKind.IDENT)
                target = FieldAccess(target, field_tok.text)
            elif self._current.kind == TokenKind.LBRACKET:
                self._advance()
                index_expr = self._parse_expr()
                self._expect(TokenKind.RBRACKET)
                target = ArrayIndex(obj=target, index=index_expr)
            else:
                break
        return target

    def _parse_let_stmt(self) -> LetStmt:
        """
        Parse variable declaration: let [mut] name [: type] = expr;

        Format:
            let x = 42;                  -> type inferred
            let x: i32 = 42;             -> explicit type
            let mut count = 0;           -> mutable variable
        """
        self._advance()  # konsumsi 'let'

        is_mut = False
        if self._current.kind == TokenKind.MUT:
            self._advance()
            is_mut = True

        name_tok = self._expect(TokenKind.IDENT)

        type_name = None
        if self._current.kind == TokenKind.COLON:
            self._advance()
            type_name = self._parse_type()

        self._expect(TokenKind.EQ)
        value = self._parse_expr()
        self._expect(TokenKind.SEMICOLON)
        return LetStmt(name=name_tok.text, value=value, type_name=type_name, is_mut=is_mut)

    def _parse_return_stmt(self) -> ReturnStmt:
        """
        Parse return statement: ret expr;

        Format:
            ret 42;
            ret "hello";
            ret;   (untuk fungsi void)
        """
        self._advance()
        if self._current.kind == TokenKind.SEMICOLON:
            expr = Ident("")  # Empty identifier untuk void return
        else:
            expr = self._parse_expr()
        self._expect(TokenKind.SEMICOLON)
        return ReturnStmt(expr)

    def _parse_if_stmt(self) -> IfStmt:
        """
        Parse if statement (bukan expression).

        Format:
            if cond { body }
            if cond { body } else { body_else }
            if cond { body } else if cond2 { body2 } else { body_else }

        Beda dengan if expression: tidak menghasilkan nilai (unit).
        """
        self._advance()
        cond = self._parse_expr()
        body = self._parse_block()
        elifs = []
        else_body = []
        while (self._current.kind == TokenKind.IDENT and 
               self._current.text == "else"):
            saved = self._save_state()
            self._advance()
            if (self._current.kind == TokenKind.IDENT and 
                self._current.text == "if"):
                self._advance()
                elif_cond = self._parse_expr()
                elif_body = self._parse_block()
                elifs.append(ElifClause(elif_cond, elif_body))
            else:
                self._restore_state(saved)
                self._advance()
                else_body = self._parse_block()
                break
        return IfStmt(cond, body, elifs, else_body)

    def _parse_for_stmt(self) -> WhileStmt:
        """
        Parse for statement (while-style loop).

        Format: for cond { body }

        Note: Syntax 'for' bukan 'while' untuk konsistensi dengan Nala.
        """
        self._advance()
        cond = self._parse_expr()
        body = self._parse_block()
        return WhileStmt(cond, body)

    def _parse_match_stmt(self) -> MatchStmt:
        """
        Parse match statement dengan pattern explicit Union.Variant.

        Format:
            match expr {
                Union.Variant => { body },        -- unit variant
                Union.Variant(bind) => { body },  -- variant dengan binding
                Union.Variant2 => { body },
            }

        Penting: Pattern HARUS explicit dengan nama union.
        Type checker akan memverifikasi bahwa union_name sesuai.

        Returns:
            MatchStmt: AST node untuk match statement
        """
        self._advance()  # konsumsi 'match'
        expr = self._parse_expr()
        self._expect(TokenKind.LBRACE)
        arms = []
        while self._current.kind != TokenKind.RBRACE:
            # Pattern HARUS explicit: UnionName.VariantName
            if self._current.kind != TokenKind.IDENT:
                raise ParseError(
                    f"Diharapkan nama union di pattern match, "
                    f"tapi ketemu {self._current.kind.name} ({self._current.text!r}) "
                    f"di baris {self._current.span.line}"
                )

            union_tok = self._advance()
            union_name = union_tok.text
            self._expect(TokenKind.DOT)
            variant_tok = self._expect(TokenKind.IDENT)
            variant_name = variant_tok.text

            # Cek optional binding: Union.Variant(bind)
            # Unit variant: Union.Variant => { body } (tanpa ())
            # Variant dengan payload: Union.Variant(bind) => { body }
            bind_name = None
            if self._current.kind == TokenKind.LPAREN:
                self._advance()  # konsumsi '('
                if self._current.kind != TokenKind.RPAREN:
                    bind_tok = self._expect(TokenKind.IDENT)
                    bind_name = bind_tok.text
                self._expect(TokenKind.RPAREN)

            # Cek optional guard: Union.Variant(bind) if cond => { body }
            guard_expr = None
            if self._current.kind == TokenKind.IDENT and self._current.text == "if":
                self._advance()  # konsumsi 'if'
                guard_expr = self._parse_expr()

            self._expect(TokenKind.FAT_ARROW)
            body = self._parse_block()
            arms.append(MatchArm(
                variant=variant_name,
                body=body,
                union=union_name,
                bind=bind_name,
                guard=guard_expr,
            ))
            if self._current.kind == TokenKind.COMMA:
                self._advance()
        self._expect(TokenKind.RBRACE)
        return MatchStmt(expr, arms)

    def _parse_block(self) -> list:
        """
        Parse block of statements: { stmt1; stmt2; ... }

        Returns:
            list: List of Stmt nodes
        """
        self._expect(TokenKind.LBRACE)
        stmts = []
        while self._current.kind != TokenKind.RBRACE:
            stmts.append(self._parse_stmt())
        self._expect(TokenKind.RBRACE)
        return stmts


def parse_source(source: str) -> list:
    """
    Entry point utama untuk parsing source code Nala.

    Fungsi ini adalah public API yang dipanggil oleh main.py
    untuk mem-parsing file .na menjadi AST.

    Args:
        source (str): Source code Nala dalam bentuk string

    Returns:
        list: List of AST nodes (deklarasi top-level)
    """
    parser = Parser(source)
    return parser.parse_program()
