# parser/stmt.py
"""
Statement parsing for Nala parser.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from lexer import TokenKind
from nala_ast import (
    AssignStmt, BreakStmt, ContinueStmt, DeferStmt, ElifClause,
    Expr, ExprStmt, FieldAccess, ForInStmt, Ident, IfStmt, LetStmt,
    MatchArm, MatchStmt, ReturnStmt, Stmt, WhileStmt,
)
from diagnostics import ParseError

class StmtParser:
    """Statement parser."""

    def __init__(self, parser: Parser):
        self._parser = parser

    @property
    def _current(self):
        return self._parser._current

    def _advance(self):
        return self._parser._advance()

    def _expect(self, kind: TokenKind):
        return self._parser._expect(kind)

    def _save_state(self):
        return self._parser._save_state()

    def _restore_state(self, state):
        self._parser._restore_state(state)

    def _parse_expr(self) -> Expr:
        return self._parser._parse_expr()

    def _parse_block(self) -> list:
        return self._parser._parse_block()

    # --- Public entry point ---
    def parse_stmt(self) -> Stmt:
        if self._current.kind == TokenKind.IDENT:
            if self._current.text == "ret":
                return self.parse_return_stmt()
            elif self._current.text == "if":
                return self.parse_if_stmt()
            elif self._current.text == "for":
                return self.parse_for_stmt()
            elif self._current.text == "match":
                return self.parse_match_stmt()
            elif self._current.text == "continue":
                self._advance()
                self._expect(TokenKind.SEMICOLON)
                return ContinueStmt()
            elif self._current.text == "break":
                self._advance()
                self._expect(TokenKind.SEMICOLON)
                return BreakStmt()
            elif self._current.text == "defer":
                return self.parse_defer_stmt()
        elif self._current.kind == TokenKind.LET:
            return self.parse_let_stmt()

        # Try assignment, fallback to expression statement
        _ASSIGN_OPS = {TokenKind.EQ: "=", TokenKind.PLUS_EQ: "+="}
        saved = self._save_state()
        try:
            target = self.parse_simple_target()
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

    def parse_simple_target(self) -> Expr:
        if self._current.kind != TokenKind.IDENT:
            raise self._parser.ParseError("Expected identifier for assignment target")
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
                target = self._parser._expr_parser._parse_array_index(target, index_expr)
            else:
                break
        return target

    def parse_let_stmt(self) -> LetStmt:
        self._advance()  # let
        is_mut = False
        if self._current.kind == TokenKind.MUT:
            self._advance()
            is_mut = True
        name_tok = self._expect(TokenKind.IDENT)
        type_name = None
        if self._current.kind == TokenKind.COLON:
            self._advance()
            type_name = self._parser._parse_type()
        self._expect(TokenKind.EQ)
        value = self._parse_expr()
        self._expect(TokenKind.SEMICOLON)
        return LetStmt(name_tok.text, value, type_name, is_mut)

    def parse_return_stmt(self) -> ReturnStmt:
        self._advance()
        if self._current.kind == TokenKind.SEMICOLON:
            expr = Ident("")
        else:
            expr = self._parse_expr()
        self._expect(TokenKind.SEMICOLON)
        return ReturnStmt(expr)

    def parse_defer_stmt(self) -> DeferStmt:
        self._advance()  # defer
        expr = self._parse_expr()
        self._expect(TokenKind.SEMICOLON)
        return DeferStmt(expr)

    def parse_if_stmt(self) -> IfStmt:
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

    def parse_for_stmt(self) -> Stmt:
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

    def parse_match_stmt(self) -> MatchStmt:
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
