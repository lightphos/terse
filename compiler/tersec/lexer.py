#!/usr/bin/env python3
"""Terse Lexer — tokenizes source code into tokens."""
from dataclasses import dataclass
from typing import List, Any
from enum import Enum, auto


class TT(Enum):
    EOF = auto()
    IDENT = auto()
    INT = auto()
    STRING = auto()
    FLOAT = auto()
    FN = auto()
    IF = auto()
    ELSE = auto()
    LP = auto()
    TRUE = auto()
    FALSE = auto()
    RETURN = auto()
    RET = auto()
    TR = auto()
    USE = auto()
    TYPE = auto()
    GO = auto()
    PUB = auto()
    EN = auto()
    VAL = auto()
    VAR = auto()
    FIX = auto()
    REC = auto()
    BRK = auto()
    SKIP = auto()
    ARROW = auto()
    FATARROW = auto()
    PIPEGT = auto()
    PLUSEQ = auto()
    MINUSEQ = auto()
    STAREQ = auto()
    SLASHEQ = auto()
    PERCENTEQ = auto()
    LPAREN = auto()
    RPAREN = auto()
    LBRACE = auto()
    RBRACE = auto()
    LBRACK = auto()
    RBRACK = auto()
    COMMA = auto()
    COLON = auto()
    SEMI = auto()
    ASSIGN = auto()
    DOT = auto()
    PLUS = auto()
    MINUS = auto()
    STAR = auto()
    SLASH = auto()
    PERCENT = auto()
    EQ = auto()
    NEQ = auto()
    LT = auto()
    GT = auto()
    LE = auto()
    GE = auto()
    AND = auto()
    OR = auto()
    NOT = auto()
    PIPE = auto()
    COMPOSE = auto()
    UNDERSCORE = auto()
    QUESTION = auto()
    ASYNC = auto()
    AWAIT = auto()


KW = {
    'fn': TT.FN, 'if': TT.IF, 'else': TT.ELSE, 'lp': TT.LP,
    'true': TT.TRUE, 'false': TT.FALSE, 'return': TT.RETURN, 'ret': TT.RET,
    'use': TT.USE, 'type': TT.TYPE, 'go': TT.GO, 'tr': TT.TR, 'pub': TT.PUB,
    'en': TT.EN,
    'val': TT.VAL, 'var': TT.VAR, 'fix': TT.FIX, 'rec': TT.REC,
    'brk': TT.BRK, 'skip': TT.SKIP,
}


@dataclass
class Tok:
    t: TT
    v: Any
    line: int
    col: int


class Lexer:
    def __init__(self, s: str):
        self.s, self.i, self.line, self.col = s, 0, 1, 1
        self.toks: List[Tok] = []

    def p(self, n: int = 0) -> str:
        return self.s[self.i + n] if self.i + n < len(self.s) else '\0'

    def adv(self) -> str:
        c = self.p()
        self.i += 1
        if c == '\n':
            self.line += 1
            self.col = 1
        else:
            self.col += 1
        return c

    def skip(self) -> None:
        while True:
            c = self.p()
            if c in ' \t\r\n':
                self.adv()
            elif c == '/' and self.p(1) == '/':
                while self.p() not in '\n\0':
                    self.adv()
            elif c == '/' and self.p(1) == '*':
                self.adv()
                self.adv()
                while not (self.p() == '*' and self.p(1) == '/') and self.p() != '\0':
                    self.adv()
                if self.p() == '*':
                    self.adv()
                    self.adv()
            else:
                break

    def num(self) -> Tok:
        ln, cl = self.line, self.col
        s = ''
        if self.p() == '-':
            s += self.adv()
        while self.p().isdigit():
            s += self.adv()
        if self.p() == '.' and self.p(1).isdigit():
            s += self.adv()
            while self.p().isdigit():
                s += self.adv()
            return Tok(TT.FLOAT, float(s), ln, cl)
        return Tok(TT.INT, int(s), ln, cl)

    def string(self) -> Tok:
        ln, cl = self.line, self.col
        self.adv()
        s = ''
        while self.p() not in '"\0':
            if self.p() == '\\':
                self.adv()
                e = self.adv()
                s += {'n': '\n', 'r': '\r', 't': '\t', '"': '"', '\\': '\\', '0': '\0'}.get(e, e)
            else:
                s += self.adv()
        if self.p() == '"':
            self.adv()
        return Tok(TT.STRING, s, ln, cl)

    def ident(self) -> Tok:
        ln, cl = self.line, self.col
        s = ''
        while self.p().isalnum() or self.p() == '_':
            s += self.adv()
        if s == '_':
            return Tok(TT.UNDERSCORE, s, ln, cl)
        return Tok(KW.get(s, TT.IDENT), s, ln, cl)

    def tokenize(self) -> List[Tok]:
        while self.i < len(self.s):
            self.skip()
            if self.i >= len(self.s):
                break
            c, ln, cl = self.p(), self.line, self.col
            if c.isdigit() or (c == '-' and self.p(1).isdigit()):
                self.toks.append(self.num())
            elif c == '"':
                self.toks.append(self.string())
            elif c.isalpha() or c == '_':
                self.toks.append(self.ident())
            elif c == '-' and self.p(1) == '>':
                self.adv()
                self.adv()
                self.toks.append(Tok(TT.ARROW, '->', ln, cl))
            elif c == '=' and self.p(1) == '>':
                self.adv()
                self.adv()
                self.toks.append(Tok(TT.FATARROW, '=>', ln, cl))
            elif c == '=' and self.p(1) == '=':
                self.adv()
                self.adv()
                self.toks.append(Tok(TT.EQ, '==', ln, cl))
            elif c == '!' and self.p(1) == '=':
                self.adv()
                self.adv()
                self.toks.append(Tok(TT.NEQ, '!=', ln, cl))
            elif c == '<' and self.p(1) == '=':
                self.adv()
                self.adv()
                self.toks.append(Tok(TT.LE, '<=', ln, cl))
            elif c == '>' and self.p(1) == '=':
                self.adv()
                self.adv()
                self.toks.append(Tok(TT.GE, '>=', ln, cl))
            elif c == '&' and self.p(1) == '&':
                self.adv()
                self.adv()
                self.toks.append(Tok(TT.AND, '&&', ln, cl))
            elif c == '|' and self.p(1) == '|':
                self.adv()
                self.adv()
                self.toks.append(Tok(TT.OR, '||', ln, cl))
            elif c == '|' and self.p(1) == '>':
                self.adv()
                self.adv()
                self.toks.append(Tok(TT.PIPEGT, '|>', ln, cl))
            elif c == '~' and self.p(1) == '~':
                self.adv(); self.adv()
                self.toks.append(Tok(TT.ASYNC, '~~', ln, cl))
            elif c == '~':
                self.adv()
                self.toks.append(Tok(TT.AWAIT, '~', ln, cl))
            elif c == '>' and self.p(1) == '>':
                self.adv()
                self.adv()
                self.toks.append(Tok(TT.COMPOSE, '>>', ln, cl))
            elif c == '+' and self.p(1) == '=':
                self.adv()
                self.adv()
                self.toks.append(Tok(TT.PLUSEQ, '+=', ln, cl))
            elif c == '-' and self.p(1) == '=':
                self.adv()
                self.adv()
                self.toks.append(Tok(TT.MINUSEQ, '-=', ln, cl))
            elif c == '*' and self.p(1) == '=':
                self.adv()
                self.adv()
                self.toks.append(Tok(TT.STAREQ, '*=', ln, cl))
            elif c == '/' and self.p(1) == '=':
                self.adv()
                self.adv()
                self.toks.append(Tok(TT.SLASHEQ, '/=', ln, cl))
            elif c == '%' and self.p(1) == '=':
                self.adv()
                self.adv()
                self.toks.append(Tok(TT.PERCENTEQ, '%=', ln, cl))
            else:
                m = {
                    '(': TT.LPAREN, ')': TT.RPAREN, '{': TT.LBRACE, '}': TT.RBRACE,
                    '[': TT.LBRACK, ']': TT.RBRACK, ',': TT.COMMA, ':': TT.COLON,
                    ';': TT.SEMI, '=': TT.ASSIGN, '.': TT.DOT, '+': TT.PLUS, '-': TT.MINUS,
                    '*': TT.STAR, '/': TT.SLASH, '%': TT.PERCENT, '<': TT.LT,
                    '>': TT.GT, '!': TT.NOT, '|': TT.PIPE, '_': TT.UNDERSCORE,
                    '?': TT.QUESTION,
                }
                if c in m:
                    self.adv()
                    self.toks.append(Tok(m[c], c, ln, cl))
                else:
                    raise SyntaxError(f"bad char '{c}' at {ln}:{cl}")
        self.toks.append(Tok(TT.EOF, None, self.line, self.col))
        return self.toks