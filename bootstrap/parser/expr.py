# parser/expr.py
"""
Expression parsing for Nala parser.
Precedence: if < or < and < comparison < additive < unary < primary.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from lexer import TokenKind
from nala_ast import (
    ArrayIndex, ArrayLiteral, BinaryExpr, BoolLiteral, CallExpr,
    DottedAccess, DottedCall, Expr, FloatLiteral, Ident, IfExpr,
    IntLiteral, IntrinsicCall, StringLiteral, StructLiteral, UnaryExpr,
)

from diagnostics import ParseError


class ExprParser:
    """Expression parser with precedence climbing."""

    def __init__(self, parser: Parser):
        self._parser = parser

    @property
    def _current(self):
        return self._parser._current

    @property
    def _lexer(self):
        return self._parser._lexer

    def _advance(self):
        return self._parser._advance()

    def _expect(self, kind: TokenKind):
        return self._parser._expect(kind)

    def _save_state(self):
        return self._parser._save_state()

    def _restore_state(self, state):
        self._parser._restore_state(state)

    def _parse_type(self) -> str:
        return self._parser._parse_type()

    # --- Public entry point ---
    def parse_expr(self) -> Expr:
        return self._parse_if_expr()

    # --- Precedence levels ---
    def _parse_if_expr(self) -> Expr:
        if self._current.kind == TokenKind.IDENT and self._current.text == "if":
            self._advance()
            cond = self.parse_expr()
            self._expect(TokenKind.LBRACE)
            then_expr = self.parse_expr()
            self._expect(TokenKind.RBRACE)
            if not (self._current.kind == TokenKind.IDENT and self._current.text == "else"):
                raise self._parser.ParseError(
                    f"Expected 'else' after if expression, got {self._current.kind.name}"
                )
            self._advance()
            self._expect(TokenKind.LBRACE)
            else_expr = self.parse_expr()
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

    _ADDITIVE_OPS = {TokenKind.PLUS: "+", TokenKind.MINUS: "-"}
    _MULTIPLICATIVE_OPS = {TokenKind.STAR: "*", TokenKind.SLASH: "/", TokenKind.PERCENT: "%"}

    def _parse_additive(self) -> Expr:
        left = self._parse_multiplicative()
        while self._current.kind in self._ADDITIVE_OPS:
            op = self._ADDITIVE_OPS[self._current.kind]
            self._advance()
            left = BinaryExpr(op, left, self._parse_multiplicative())
        return left

    def _parse_multiplicative(self) -> Expr:
        left = self._parse_unary()
        while self._current.kind in self._MULTIPLICATIVE_OPS:
            op = self._MULTIPLICATIVE_OPS[self._current.kind]
            self._advance()
            left = BinaryExpr(op, left, self._parse_unary())
        return left

    def _parse_unary(self) -> Expr:
        if self._current.kind == TokenKind.BANG:
            self._advance()
            return UnaryExpr("!", self._parse_unary())
        return self._parse_primary()

    # --- Primary expressions ---
    def _parse_primary(self) -> Expr:
        if self._current.kind == TokenKind.IDENT:
            name_tok = self._advance()
            if name_tok.text == "true":
                return BoolLiteral(True)
            if name_tok.text == "false":
                return BoolLiteral(False)
            # Dotted access/call with chaining support
            if self._current.kind == TokenKind.DOT:
                return self._parse_dotted(name_tok.text)
            # Intrinsic
            if self._current.kind == TokenKind.BANG:
                self._advance()
                return self.parse_intrinsic(name_tok.text)
            # Call
            if self._current.kind == TokenKind.LPAREN:
                return self.parse_call(name_tok.text)
            # Struct literal (tentative, backtracking)
            if self._current.kind == TokenKind.LBRACE:
                saved = self._save_state()
                try:
                    return self.parse_struct_literal(name_tok.text)
                except ParseError:
                    self._restore_state(saved)
                    return Ident(name_tok.text)
            # Array index
            target = Ident(name_tok.text)
            while self._current.kind == TokenKind.LBRACKET:
                self._advance()
                index_expr = self.parse_expr()
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

        # Array literal: [N]T{...}
        if self._current.kind == TokenKind.LBRACKET:
            return self._parse_array_literal()

        if self._current.kind == TokenKind.LPAREN:
            self._advance()
            inner = self.parse_expr()
            self._expect(TokenKind.RPAREN)
            return inner

        raise ParseError(
            f"Expected expression, got {self._current.kind.name} ({self._current.text!r})"
        )

    def _parse_dotted(self, first: str) -> Expr:
        parts = [first]
        while self._current.kind == TokenKind.DOT:
            self._advance()
            parts.append(self._expect(TokenKind.IDENT).text)
            if self._current.kind == TokenKind.LPAREN:
                self._advance()
                args = []
                while self._current.kind != TokenKind.RPAREN:
                    args.append(self.parse_expr())
                    if self._current.kind == TokenKind.COMMA:
                        self._advance()
                    else:
                        break
                self._expect(TokenKind.RPAREN)
                base = Ident(parts[0])
                for part in parts[1:-1]:
                    base = DottedAccess(base, part)
                return DottedCall(base, parts[-1], args)
        base = Ident(parts[0])
        for part in parts[1:-1]:
            base = DottedAccess(base, part)
        return DottedAccess(base, parts[-1])

    def _parse_array_literal(self) -> Expr:
        self._advance()
        if self._current.kind != TokenKind.INT_LITERAL:
            raise ParseError(
                f"Array literal must have explicit size, got {self._current.kind.name}"
            )
        size = int(self._advance().text)
        self._expect(TokenKind.RBRACKET)
        element_type = self._expect(TokenKind.IDENT).text
        self._expect(TokenKind.LBRACE)
        elements = []
        while self._current.kind != TokenKind.RBRACE:
            elements.append(self.parse_expr())
            if self._current.kind == TokenKind.COMMA:
                self._advance()
            else:
                break
        self._expect(TokenKind.RBRACE)
        return ArrayLiteral(size, element_type, elements)

    def _parse_array_index(self, target: Expr, index_expr: Expr) -> ArrayIndex:
        """parse array index: arr[i]"""
        return ArrayIndex(target, index_expr)

    # --- Helper parsers ---
    def parse_intrinsic(self, name: str) -> IntrinsicCall:
        self._expect(TokenKind.LPAREN)
        args = []
        while self._current.kind != TokenKind.RPAREN:
            args.append(self.parse_expr())
            if self._current.kind == TokenKind.COMMA:
                self._advance()
            else:
                break
        self._expect(TokenKind.RPAREN)
        return IntrinsicCall(name, args)

    def parse_struct_literal(self, type_name: str) -> StructLiteral:
        self._expect(TokenKind.LBRACE)
        fields = []
        while self._current.kind != TokenKind.RBRACE:
            field_name_tok = self._expect(TokenKind.IDENT)
            self._expect(TokenKind.COLON)
            value = self.parse_expr()
            fields.append((field_name_tok.text, value))
            if self._current.kind == TokenKind.COMMA:
                self._advance()
            else:
                break
        self._expect(TokenKind.RBRACE)
        return StructLiteral(type_name, fields)

    def parse_call(self, callee: str) -> CallExpr:
        self._expect(TokenKind.LPAREN)
        args = []
        while self._current.kind != TokenKind.RPAREN:
            args.append(self.parse_expr())
            if self._current.kind == TokenKind.COMMA:
                self._advance()
            else:
                break
        self._expect(TokenKind.RPAREN)
        return CallExpr(callee, args)
