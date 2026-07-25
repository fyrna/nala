# bootstrap/parser.py
"""
Recursive-descent parser: token stream → raw AST with neutral DottedAccess/DottedCall.
No semantic decisions; type checker resolves dotted nodes.
Uses precedence climbing: if-expr, or, and, comparison, additive, unary, primary.
"""
from __future__ import annotations
from lexer import Lexer, Token, TokenKind
from nala_ast import (
    EnumDecl, StructDecl, StructField, UnionDecl, UnionVariant,
    Expr, Stmt, Ident, StringLiteral, IntLiteral, FloatLiteral, BoolLiteral, ByteLiteral,
    BinaryExpr, UnaryExpr, CallExpr, FieldAccess, IntrinsicCall,
    IfExpr, ElifClause, MatchArm, MatchStmt, UnionLiteral,
    Param, ReturnStmt, IfStmt, WhileStmt, ForInStmt, AssignStmt, ExprStmt, LetStmt, FnDecl, SelfParam,
    ContinueStmt, BreakStmt, StructLiteral,
    DottedAccess, DottedCall,
    ArrayLiteral, ArrayIndex,
)

class ParseError(Exception):
    """Fatal syntax error."""
    pass

class Parser:
    """
    LL(1) parser with one-token lookahead. Methods:
    parse_program() -> parse_decl() -> parse_fn_decl() / parse_struct_body()
    parse_stmt() -> parse_if_stmt() / parse_for_stmt() / parse_match_stmt()
    parse_expr() -> parse_if_expr() -> parse_or() -> ... -> parse_primary()
    Precedence: if < or < and < comparison < additive < unary < primary.
    """
    def __init__(self, source: str):
        self._lexer = Lexer(source)
        self._current: Token = self._lexer.next_token()
        self._struct_name: str | None = None

    def _advance(self) -> Token:
        tok = self._current
        self._current = self._lexer.next_token()
        return tok

    def _expect(self, kind: TokenKind) -> Token:
        if self._current.kind != kind:
            raise ParseError(
                f"Expected {kind.name}, got {self._current.kind.name} ({self._current.text!r}) "
                f"at line {self._current.span.line}, col {self._current.span.col}"
            )
        return self._advance()

    def _save_state(self):
        return (self._lexer.pos, self._lexer.line, self._lexer.col, self._current)

    def _restore_state(self, state):
        self._lexer.pos, self._lexer.line, self._lexer.col, self._current = state

    def parse_program(self) -> list:
        decls = []
        while self._current.kind != TokenKind.EOF:
            decls.append(self._parse_decl())
        return decls

    def _parse_decl(self):
        if self._current.kind == TokenKind.FN:
            return self._parse_fn_decl(is_internal=False)
        if self._current.kind == TokenKind.IDENT and self._current.text == "internal":
            self._advance()
            self._expect(TokenKind.FN)
            return self._parse_fn_decl(is_internal=True, fn_already_consumed=True)
        const_tok = self._expect(TokenKind.IDENT)
        if const_tok.text != "const":
            raise ParseError(f"Expected 'const', 'fn', or 'internal fn', got {const_tok.text!r}")
        name_tok = self._expect(TokenKind.IDENT)
        name = name_tok.text
        self._expect(TokenKind.EQ)
        kind_tok = self._expect(TokenKind.IDENT)
        if kind_tok.text == "enum":
            result = self._parse_enum_body(name)
        elif kind_tok.text == "struct":
            result = self._parse_struct_body(name)
        elif kind_tok.text == "union":
            result = self._parse_union_body(name)
        else:
            raise ParseError(f"Expected 'enum', 'struct', or 'union', got {kind_tok.text!r}")
        if self._current.kind == TokenKind.SEMICOLON:
            self._advance()
        return result

    def _parse_fn_decl(self, is_internal: bool, fn_already_consumed: bool = False, struct_name: str | None = None):
        if not fn_already_consumed:
            self._expect(TokenKind.FN)
        name_tok = self._expect(TokenKind.IDENT)
        name = name_tok.text
        self._expect(TokenKind.LPAREN)
        self_param = self._parse_self_param()
        params = []
        if self_param is not None and self._current.kind == TokenKind.COMMA:
            self._advance()
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
        return_type = "void"
        if self._current.kind == TokenKind.ARROW:
            self._advance()
            return_type = self._expect(TokenKind.IDENT).text
        old_struct_name = self._struct_name
        if struct_name is not None:
            self._struct_name = struct_name
        body = self._parse_block()
        self._struct_name = old_struct_name
        return FnDecl(name, params, return_type, body, is_internal, self_param, struct_name)

    def _parse_self_param(self) -> SelfParam | None:
        if self._current.kind == TokenKind.AMPERSAND:
            self._advance()
            is_mut = False
            if self._current.kind == TokenKind.MUT:
                self._advance()
                is_mut = True
            if self._current.kind == TokenKind.IDENT and self._current.text == "self":
                self._advance()
                return SelfParam(is_mut, True)
            raise ParseError(f"Expected 'self' after &, got {self._current.text!r}")
        if self._current.kind == TokenKind.IDENT and self._current.text == "self":
            self._advance()
            return SelfParam(False, False)
        return None

    def _parse_type(self) -> str:
        if self._current.kind == TokenKind.LBRACKET:
            self._advance()
            if self._current.kind == TokenKind.INT_LITERAL:
                size_tok = self._advance()
                self._expect(TokenKind.RBRACKET)
                inner_tok = self._expect(TokenKind.IDENT)
                return f"[{size_tok.text}]{inner_tok.text}"
            self._expect(TokenKind.RBRACKET)
            inner_tok = self._expect(TokenKind.IDENT)
            return f"[]{inner_tok.text}"
        else:
            return self._expect(TokenKind.IDENT).text

    def _parse_intrinsic(self, name: str) -> IntrinsicCall:
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
        return EnumDecl(name, variants)

    def _parse_union_body(self, name: str) -> UnionDecl:
        self._expect(TokenKind.LBRACE)
        variants = []
        while self._current.kind != TokenKind.RBRACE:
            variant_tok = self._expect(TokenKind.IDENT)
            payload_types = []
            if self._current.kind == TokenKind.LPAREN:
                self._advance()
                if self._current.kind != TokenKind.RPAREN:
                    payload_types.append(self._parse_type())
                    while self._current.kind == TokenKind.COMMA:
                        self._advance()
                        payload_types.append(self._parse_type())
                self._expect(TokenKind.RPAREN)
            variants.append(UnionVariant(variant_tok.text, payload_types))
            if self._current.kind == TokenKind.COMMA:
                self._advance()
            else:
                break
        self._expect(TokenKind.RBRACE)
        return UnionDecl(name, variants)

    def _parse_struct_body(self, name: str) -> StructDecl:
        self._expect(TokenKind.LBRACE)
        fields = []
        methods = []
        while self._current.kind != TokenKind.RBRACE:
            if self._current.kind == TokenKind.FN:
                methods.append(self._parse_fn_decl(False, struct_name=name))
                continue
            if self._current.kind == TokenKind.IDENT and self._current.text == "internal":
                self._advance()
                self._expect(TokenKind.FN)
                methods.append(self._parse_fn_decl(True, True, name))
                continue
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
        return StructDecl(name, fields, methods)

    # --- Expression parsing (precedence climbing) ---
    def _parse_expr(self) -> Expr:
        return self._parse_if_expr()

    def _parse_if_expr(self) -> Expr:
        if self._current.kind == TokenKind.IDENT and self._current.text == "if":
            self._advance()
            cond = self._parse_expr()
            self._expect(TokenKind.LBRACE)
            then_expr = self._parse_expr()
            self._expect(TokenKind.RBRACE)
            if not (self._current.kind == TokenKind.IDENT and self._current.text == "else"):
                raise ParseError(f"Expected 'else' after if expression, got {self._current.kind.name}")
            self._advance()
            self._expect(TokenKind.LBRACE)
            else_expr = self._parse_expr()
            self._expect(TokenKind.RBRACE)
            return IfExpr(cond, then_expr, else_expr)
        return self._parse_or()

    def _parse_or(self) -> Expr:
        left = self._parse_and()
        while self._current.kind == TokenKind.IDENT and self._current.text == "or":
            self._advance()
            left = BinaryExpr("or", left, self._parse_and())
        return left

    def _parse_and(self) -> Expr:
        left = self._parse_comparison()
        while self._current.kind == TokenKind.IDENT and self._current.text == "and":
            self._advance()
            left = BinaryExpr("and", left, self._parse_comparison())
        return left

    def _parse_comparison(self) -> Expr:
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
            return BinaryExpr(op, left, self._parse_additive())
        return left

    def _parse_additive(self) -> Expr:
        left = self._parse_unary()
        while self._current.kind == TokenKind.PLUS:
            self._advance()
            left = BinaryExpr("+", left, self._parse_unary())
        return left

    def _parse_unary(self) -> Expr:
        if self._current.kind == TokenKind.BANG:
            self._advance()
            return UnaryExpr("!", self._parse_unary())
        return self._parse_primary()

    def _parse_primary(self) -> Expr:
        if self._current.kind == TokenKind.IDENT:
            name_tok = self._advance()
            if name_tok.text == "true":
                return BoolLiteral(True)
            if name_tok.text == "false":
                return BoolLiteral(False)
            # Dotted access/call (neutral)
            if self._current.kind == TokenKind.DOT:
                self._advance()
                name_tok2 = self._expect(TokenKind.IDENT)
                if self._current.kind == TokenKind.LPAREN:
                    self._advance()
                    args = []
                    while self._current.kind != TokenKind.RPAREN:
                        args.append(self._parse_expr())
                        if self._current.kind == TokenKind.COMMA:
                            self._advance()
                        else:
                            break
                    self._expect(TokenKind.RPAREN)
                    return DottedCall(Ident(name_tok.text), name_tok2.text, args)
                return DottedAccess(Ident(name_tok.text), name_tok2.text)
            # Intrinsic
            if self._current.kind == TokenKind.BANG:
                self._advance()
                return self._parse_intrinsic(name_tok.text)
            # Call
            if self._current.kind == TokenKind.LPAREN:
                return self._parse_call(name_tok.text)
            # Struct literal (tentative, backtracking)
            if self._current.kind == TokenKind.LBRACE:
                saved = self._save_state()
                try:
                    return self._parse_struct_literal(name_tok.text)
                except ParseError:
                    self._restore_state(saved)
                    return Ident(name_tok.text)
            # Array index
            target = Ident(name_tok.text)
            while self._current.kind == TokenKind.LBRACKET:
                self._advance()
                index_expr = self._parse_expr()
                self._expect(TokenKind.RBRACKET)
                target = ArrayIndex(target, index_expr)
            return target

        if self._current.kind == TokenKind.STRING_LITERAL:
            tok = self._advance()
            return StringLiteral(tok.text[1:-1])
        if self._current.kind == TokenKind.INT_LITERAL:
            return IntLiteral(self._advance().text)
        if self._current.kind == TokenKind.FLOAT_LITERAL:
            return FloatLiteral(self._advance().text)
        if self._current.kind == TokenKind.BYTE_LITERAL:
            return ByteLiteral(self._advance().text[1:-1])

        # Array literal: [N]T{...}
        if self._current.kind == TokenKind.LBRACKET:
            self._advance()
            if self._current.kind != TokenKind.INT_LITERAL:
                raise ParseError(f"Array literal must have explicit size, got {self._current.kind.name}")
            size = int(self._advance().text)
            self._expect(TokenKind.RBRACKET)
            element_type = self._expect(TokenKind.IDENT).text
            self._expect(TokenKind.LBRACE)
            elements = []
            while self._current.kind != TokenKind.RBRACE:
                elements.append(self._parse_expr())
                if self._current.kind == TokenKind.COMMA:
                    self._advance()
                else:
                    break
            self._expect(TokenKind.RBRACE)
            return ArrayLiteral(size, element_type, elements)

        if self._current.kind == TokenKind.LPAREN:
            self._advance()
            inner = self._parse_expr()
            self._expect(TokenKind.RPAREN)
            return inner

        raise ParseError(f"Expected expression, got {self._current.kind.name} ({self._current.text!r})")

    def _parse_struct_literal(self, type_name: str) -> StructLiteral:
        self._expect(TokenKind.LBRACE)
        fields = []
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
        return StructLiteral(type_name, fields)

    def _parse_call(self, callee: str) -> CallExpr:
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

    # --- Statement parsing ---
    def _parse_stmt(self) -> Stmt:
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
        elif self._current.kind == TokenKind.LET:
            return self._parse_let_stmt()

        # Try assignment, fallback to expression statement
        _ASSIGN_OPS = {TokenKind.EQ: "=", TokenKind.PLUS_EQ: "+="}
        saved = self._save_state()
        try:
            target = self._parse_simple_target()
            if self._current.kind in _ASSIGN_OPS:
                op = _ASSIGN_OPS[self._current.kind]
                self._advance()
                value = self._parse_expr()
                self._expect(TokenKind.SEMICOLON)
                return AssignStmt(target, value, op)
            self._restore_state(saved)
        except ParseError:
            self._restore_state(saved)

        expr = self._parse_expr()
        self._expect(TokenKind.SEMICOLON)
        return ExprStmt(expr)

    def _parse_simple_target(self) -> Expr:
        if self._current.kind != TokenKind.IDENT:
            raise ParseError("Expected identifier for assignment target")
        name_tok = self._advance()
        target = Ident(name_tok.text)
        while True:
            if self._current.kind == TokenKind.DOT:
                self._advance()
                target = FieldAccess(target, self._expect(TokenKind.IDENT).text)
            elif self._current.kind == TokenKind.LBRACKET:
                self._advance()
                index_expr = self._parse_expr()
                self._expect(TokenKind.RBRACKET)
                target = ArrayIndex(target, index_expr)
            else:
                break
        return target

    def _parse_let_stmt(self) -> LetStmt:
        self._advance()  # let
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
        return LetStmt(name_tok.text, value, type_name, is_mut)

    def _parse_return_stmt(self) -> ReturnStmt:
        self._advance()
        if self._current.kind == TokenKind.SEMICOLON:
            expr = Ident("")
        else:
            expr = self._parse_expr()
        self._expect(TokenKind.SEMICOLON)
        return ReturnStmt(expr)

    def _parse_if_stmt(self) -> IfStmt:
        self._advance()
        cond = self._parse_expr()
        body = self._parse_block()
        elifs = []
        else_body = []
        while self._current.kind == TokenKind.IDENT and self._current.text == "else":
            saved = self._save_state()
            self._advance()
            if self._current.kind == TokenKind.IDENT and self._current.text == "if":
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

    def _parse_for_stmt(self) -> Stmt:
        self._advance()  # for
        # Try for-in: var in iterable
        if self._current.kind == TokenKind.IDENT:
            saved = self._save_state()
            var_name = self._advance().text
            if self._current.kind == TokenKind.IDENT and self._current.text == "in":
                self._advance()
                iterable = self._parse_expr()
                body = self._parse_block()
                return ForInStmt(var_name, iterable, body)
            self._restore_state(saved)
        # while-style: for cond { body }
        cond = self._parse_expr()
        body = self._parse_block()
        return WhileStmt(cond, body)

    def _parse_match_stmt(self) -> MatchStmt:
        self._advance()  # match
        expr = self._parse_expr()
        self._expect(TokenKind.LBRACE)
        arms = []
        while self._current.kind != TokenKind.RBRACE:
            union_tok = self._expect(TokenKind.IDENT)
            union_name = union_tok.text
            self._expect(TokenKind.DOT)
            variant_tok = self._expect(TokenKind.IDENT)
            variant_name = variant_tok.text
            bind_name = None
            if self._current.kind == TokenKind.LPAREN:
                self._advance()
                if self._current.kind != TokenKind.RPAREN:
                    bind_name = self._expect(TokenKind.IDENT).text
                self._expect(TokenKind.RPAREN)
            guard_expr = None
            if self._current.kind == TokenKind.IDENT and self._current.text == "if":
                self._advance()
                guard_expr = self._parse_expr()
            self._expect(TokenKind.FAT_ARROW)
            body = self._parse_block()
            arms.append(MatchArm(variant_name, body, union_name, bind_name, guard_expr))
            if self._current.kind == TokenKind.COMMA:
                self._advance()
        self._expect(TokenKind.RBRACE)
        return MatchStmt(expr, arms)

    def _parse_block(self) -> list:
        self._expect(TokenKind.LBRACE)
        stmts = []
        while self._current.kind != TokenKind.RBRACE:
            stmts.append(self._parse_stmt())
        self._expect(TokenKind.RBRACE)
        return stmts

def parse_source(source: str) -> list:
    """Parse entire source into a list of top-level declarations."""
    return Parser(source).parse_program()
