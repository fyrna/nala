# parser/parser.py
"""
Recursive-descent parser: token stream → raw AST with neutral DottedAccess/DottedCall.
No semantic decisions; type checker resolves dotted nodes.
Uses precedence climbing: if-expr, or, and, comparison, additive, unary, primary.
"""
from __future__ import annotations

from lexer import Lexer, Token, TokenKind
from nala_ast import (
    AssignStmt, BinaryExpr, BoolLiteral, CallExpr, ContinueStmt, DeferStmt,
    DottedAccess, DottedCall, ElifClause, EnumDecl, Expr, ExprStmt, FieldAccess,
    FnDecl, ForInStmt, Ident, IfExpr, IfStmt, IntLiteral, IntrinsicCall,
    LetStmt, MatchStmt, Param, ReturnStmt, SelfParam, Stmt, StringLiteral,
    StructDecl, StructField, StructLiteral, UnaryExpr, UnionDecl, UnionVariant,
    UseDecl, WhileStmt,
)

from parser.expr import ExprParser
from parser.stmt import StmtParser

from diagnostics import ParseError


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

        # Initialize helper parsers with reference to this parser
        self._expr_parser = ExprParser(self)
        self._stmt_parser = StmtParser(self)

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

    # --- Public API ---
    def parse_program(self) -> list:
        decls = []
        while self._current.kind != TokenKind.EOF:
            decls.append(self._parse_decl())
        return decls

    # --- Top-level declarations ---
    def _parse_decl(self):
        if self._current.kind == TokenKind.FN:
            return self._parse_fn_decl(is_internal=False)
        if self._current.kind == TokenKind.USE:
            return self._parse_use_decl()
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

    def _parse_use_decl(self) -> UseDecl:
        self._expect(TokenKind.USE)
        parts = [self._expect(TokenKind.IDENT).text]
        while self._current.kind == TokenKind.DOT:
            self._advance()
            parts.append(self._expect(TokenKind.IDENT).text)
        module_path = ".".join(parts)
        alias = None
        if self._current.kind == TokenKind.IDENT and self._current.text == "as":
            self._advance()
            alias = self._expect(TokenKind.IDENT).text
        if self._current.kind == TokenKind.SEMICOLON:
            self._advance()
        return UseDecl(module_path, alias)

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

    # --- Block parsing ---
    def _parse_block(self) -> list:
        self._expect(TokenKind.LBRACE)
        stmts = []
        while self._current.kind != TokenKind.RBRACE:
            stmts.append(self._parse_stmt())
        self._expect(TokenKind.RBRACE)
        return stmts

    # --- Expression parsing (delegated to ExprParser) ---
    def _parse_expr(self) -> Expr:
        return self._expr_parser.parse_expr()

    def _parse_intrinsic(self, name: str) -> IntrinsicCall:
        return self._expr_parser.parse_intrinsic(name)

    def _parse_struct_literal(self, type_name: str) -> StructLiteral:
        return self._expr_parser.parse_struct_literal(type_name)

    def _parse_call(self, callee: str) -> CallExpr:
        return self._expr_parser.parse_call(callee)

    # --- Statement parsing (delegated to StmtParser) ---
    def _parse_stmt(self) -> Stmt:
        return self._stmt_parser.parse_stmt()

    def _parse_let_stmt(self) -> LetStmt:
        return self._stmt_parser.parse_let_stmt()

    def _parse_return_stmt(self) -> ReturnStmt:
        return self._stmt_parser.parse_return_stmt()

    def _parse_defer_stmt(self) -> DeferStmt:
        return self._stmt_parser.parse_defer_stmt()

    def _parse_if_stmt(self) -> IfStmt:
        return self._stmt_parser.parse_if_stmt()

    def _parse_for_stmt(self) -> Stmt:
        return self._stmt_parser.parse_for_stmt()

    def _parse_match_stmt(self) -> MatchStmt:
        return self._stmt_parser.parse_match_stmt()

    def _parse_simple_target(self) -> Expr:
        return self._stmt_parser.parse_simple_target()


def parse_source(source: str) -> list:
    """Parse entire source into a list of top-level declarations."""
    return Parser(source).parse_program()
