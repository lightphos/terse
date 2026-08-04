#!/usr/bin/env python3
"""
Terse Compiler (tersec) 0.1beta
Native binary via C. Strings, lists, pr, http.serve (minimal socket server).
"""
import sys, os, shutil, subprocess, argparse
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Tuple
from enum import Enum, auto

# --- Lexer -----------------------------------------------
class TT(Enum):
    EOF=auto(); IDENT=auto(); INT=auto(); STRING=auto()
    FN=auto(); LET=auto(); IF=auto(); ELSE=auto(); LP=auto()
    TRUE=auto(); FALSE=auto(); RETURN=auto(); RET=auto(); SIG=auto(); FIT=auto(); AS=auto()
    USE=auto(); TYPE=auto(); GO=auto()
    ARROW=auto(); FATARROW=auto()
    LPAREN=auto(); RPAREN=auto(); LBRACE=auto(); RBRACE=auto()
    LBRACK=auto(); RBRACK=auto()
    COMMA=auto(); COLON=auto(); SEMI=auto(); ASSIGN=auto(); DOT=auto()
    PLUS=auto(); MINUS=auto(); STAR=auto(); SLASH=auto(); PERCENT=auto()
    EQ=auto(); NEQ=auto(); LT=auto(); GT=auto(); LE=auto(); GE=auto()
    AND=auto(); OR=auto(); NOT=auto(); PIPE=auto(); COMPOSE=auto()
    UNDERSCORE=auto()

KW = {'fn':TT.FN,'let':TT.LET,'if':TT.IF,'else':TT.ELSE,'lp':TT.LP,
      'true':TT.TRUE,'false':TT.FALSE,'return':TT.RETURN,'ret':TT.RET,
      'use':TT.USE,'type':TT.TYPE,'go':TT.GO,'sig':TT.SIG,'fit':TT.FIT,'as':TT.AS}

@dataclass
class Tok:
    t: TT; v: Any; line: int; col: int

class Lexer:
    def __init__(self, s):
        self.s, self.i, self.line, self.col = s, 0, 1, 1
        self.toks = []
    def p(self, n=0):
        return self.s[self.i+n] if self.i+n < len(self.s) else '\0'
    def adv(self):
        c = self.p(); self.i += 1
        if c == '\n': self.line += 1; self.col = 1
        else: self.col += 1
        return c
    def skip(self):
        while True:
            c = self.p()
            if c in ' \t\r\n': self.adv()
            elif c=='/' and self.p(1)=='/':
                while self.p() not in '\n\0': self.adv()
            elif c=='/' and self.p(1)=='*':
                self.adv(); self.adv()
                while not (self.p()=='*' and self.p(1)=='/') and self.p()!='\0': self.adv()
                if self.p()=='*': self.adv(); self.adv()
            else: break
    def num(self):
        ln,cl = self.line, self.col; s=''
        if self.p()=='-': s+=self.adv()
        while self.p().isdigit(): s+=self.adv()
        return Tok(TT.INT, int(s), ln, cl)
    def string(self):
        ln,cl = self.line, self.col; self.adv(); s=''
        while self.p() not in '"\0':
            if self.p()=='\\':
                self.adv(); e=self.adv()
                s += {'n':'\n','t':'\t','"':'"','\\':'\\'}.get(e, e)
            else: s+=self.adv()
        if self.p()=='"': self.adv()
        return Tok(TT.STRING, s, ln, cl)
    def ident(self):
        ln,cl = self.line, self.col; s=''
        while self.p().isalnum() or self.p()=='_': s+=self.adv()
        return Tok(KW.get(s, TT.IDENT), s, ln, cl)
    def tokenize(self):
        while self.i < len(self.s):
            self.skip()
            if self.i >= len(self.s): break
            c, ln, cl = self.p(), self.line, self.col
            if c.isdigit() or (c=='-' and self.p(1).isdigit()): self.toks.append(self.num())
            elif c=='"': self.toks.append(self.string())
            elif c.isalpha() or c=='_': self.toks.append(self.ident())
            elif c=='-' and self.p(1)=='>': self.adv(); self.adv(); self.toks.append(Tok(TT.ARROW,'->',ln,cl))
            elif c=='=' and self.p(1)=='>': self.adv(); self.adv(); self.toks.append(Tok(TT.FATARROW,'=>',ln,cl))
            elif c=='=' and self.p(1)=='=': self.adv(); self.adv(); self.toks.append(Tok(TT.EQ,'==',ln,cl))
            elif c=='!' and self.p(1)=='=': self.adv(); self.adv(); self.toks.append(Tok(TT.NEQ,'!=',ln,cl))
            elif c=='<' and self.p(1)=='=': self.adv(); self.adv(); self.toks.append(Tok(TT.LE,'<=',ln,cl))
            elif c=='>' and self.p(1)=='=': self.adv(); self.adv(); self.toks.append(Tok(TT.GE,'>=',ln,cl))
            elif c=='&' and self.p(1)=='&': self.adv(); self.adv(); self.toks.append(Tok(TT.AND,'&&',ln,cl))
            elif c=='|' and self.p(1)=='|': self.adv(); self.adv(); self.toks.append(Tok(TT.OR,'||',ln,cl))
            elif c=='>' and self.p(1)=='>': self.adv(); self.adv(); self.toks.append(Tok(TT.COMPOSE,'>>',ln,cl))
            else:
                m = {'(':TT.LPAREN,')':TT.RPAREN,'{':TT.LBRACE,'}':TT.RBRACE,
                     '[':TT.LBRACK,']':TT.RBRACK,',':TT.COMMA,':':TT.COLON,
                     ';':TT.SEMI,'=':TT.ASSIGN,'.':TT.DOT,'+':TT.PLUS,'-':TT.MINUS,
                     '*':TT.STAR,'/':TT.SLASH,'%':TT.PERCENT,'<':TT.LT,
                     '>':TT.GT,'!':TT.NOT,'|':TT.PIPE,'_':TT.UNDERSCORE}
                if c in m: self.adv(); self.toks.append(Tok(m[c],c,ln,cl))
                else: raise SyntaxError(f"bad char '{c}' at {ln}:{cl}")
        self.toks.append(Tok(TT.EOF,None,self.line,self.col))
        return self.toks

# --- AST -------------------------------------------------
@dataclass
class TypeNode:
    name: str
    args: List['TypeNode'] = field(default_factory=list)

@dataclass
class Param:
    name: str
    typ: Optional[TypeNode] = None

class Expr: pass

@dataclass
class IntLit(Expr):
    value: int
@dataclass
class BoolLit(Expr):
    value: bool
@dataclass
class StrLit(Expr):
    value: str
@dataclass
class Var(Expr):
    name: str
@dataclass
class Binary(Expr):
    op: str; left: Expr; right: Expr
@dataclass
class Unary(Expr):
    op: str; expr: Expr
@dataclass
class Call(Expr):
    func: Expr; args: List[Expr]
@dataclass
class Member(Expr):
    obj: Expr; field: str
@dataclass
class IfExpr(Expr):
    cond: Expr; then: Expr; els: Optional[Expr]
@dataclass
class LetExpr(Expr):
    name: str; value: Expr; body: Expr; typ: Optional[TypeNode] = None
@dataclass
class RetExpr(Expr):
    value: Optional[Expr] = None
@dataclass
class Lambda(Expr):
    params: List[Param]; body: Expr
@dataclass
class LoopExpr(Expr):
    init: Optional[Expr]
    cond: Expr
    post: Optional[Expr]
    body: Expr
@dataclass
class Block(Expr):
    stmts: List[Expr]
@dataclass
class ListLit(Expr):
    items: List[Expr]
@dataclass
class Index(Expr):
    coll: Expr; idx: Expr
@dataclass
class Route:
    method: str   # GET, POST, ...
    path: str
    handler: Expr
@dataclass
class HttpServe(Expr):
    port: Expr
    routes: List[Route]
@dataclass
class FnDecl:
    name: str; params: List[Param]; ret: Optional[TypeNode]; body: Expr
@dataclass
class RecDecl:
    name: str
    fields: List[Tuple[str, TypeNode]]
@dataclass
class SigDecl:
    name: str
    methods: List[Tuple[str, List[Param], Optional[TypeNode]]]
@dataclass
class FitDecl:
    name: str
    ifaces: List[str] = field(default_factory=list)
    methods: List[FnDecl] = field(default_factory=list)
@dataclass
class RecordLit(Expr):
    ctor: Expr
    fields: List[Tuple[str, Expr]]
@dataclass
class Program:
    funcs: List[FnDecl]
    recs: List[RecDecl]
    sigs: List[SigDecl] = field(default_factory=list)
    fits: List[FitDecl] = field(default_factory=list)
    toplevel: Optional[Expr] = None  # top-level body or go body

# --- Parser -----------------------------------------------
class Parser:
    def __init__(self, toks):
        self.toks, self.i = toks, 0
    def cur(self): return self.toks[self.i]
    def adv(self):
        t = self.cur()
        if t.t != TT.EOF: self.i += 1
        return t
    def expect(self, tt):
        if self.cur().t != tt:
            t = self.cur()
            raise SyntaxError(f"expected {tt.name} got {t.t.name}('{t.v}') at {t.line}:{t.col}")
        return self.adv()
    def match(self, *ts): return self.cur().t in ts

    def parse_type(self):
        if self.match(TT.IDENT, TT.FN):
            name = self.adv().v
            args = []
            if name == 'fn' and self.match(TT.LPAREN):
                self.adv()
                while not self.match(TT.RPAREN):
                    args.append(self.parse_type())
                    if self.match(TT.COMMA): self.adv()
                self.expect(TT.RPAREN)
                if self.match(TT.ARROW):
                    self.adv(); args.append(self.parse_type())
            return TypeNode(name, args)
        if self.match(TT.LBRACK):
            self.adv()
            inner = self.parse_type()
            self.expect(TT.RBRACK)
            return TypeNode('list', [inner])
        if self.match(TT.LBRACE):  # {id: i64, name: str}
            self.adv()
            while not self.match(TT.RBRACE):
                self.expect(TT.IDENT)
                self.expect(TT.COLON)
                self.parse_type()
                if self.match(TT.COMMA): self.adv()
            self.expect(TT.RBRACE)
            return TypeNode('record', [])
        raise SyntaxError(f"type expected at {self.cur().line}:{self.cur().col}")

    def parse_params(self):
        ps = []
        self.expect(TT.LPAREN)
        while not self.match(TT.RPAREN):
            name = self.expect(TT.IDENT).v
            typ = None
            if self.match(TT.COLON):
                self.adv(); typ = self.parse_type()
            ps.append(Param(name, typ))
            if self.match(TT.COMMA): self.adv()
        self.expect(TT.RPAREN)
        return ps

    def parse_list(self):
        self.expect(TT.LBRACK)
        items = []
        while not self.match(TT.RBRACK):
            items.append(self.parse_expr())
            if self.match(TT.COMMA): self.adv()
        self.expect(TT.RBRACK)
        return ListLit(items)

    def parse_ret(self):
        self.expect(TT.RET)
        value = None
        if not self.match(TT.RBRACE, TT.SEMI, TT.EOF):
            value = self.parse_expr()
        return RetExpr(value)

    def parse_primary(self):
        t = self.cur()
        if self.match(TT.INT): self.adv(); return IntLit(t.v)
        if self.match(TT.TRUE): self.adv(); return BoolLit(True)
        if self.match(TT.FALSE): self.adv(); return BoolLit(False)
        if self.match(TT.STRING): self.adv(); return StrLit(t.v)
        if self.match(TT.IDENT): self.adv(); return Var(t.v)
        if self.match(TT.RET): return self.parse_ret()
        if self.match(TT.LPAREN):
            self.adv(); e = self.parse_expr(); self.expect(TT.RPAREN); return e
        if self.match(TT.LBRACK): return self.parse_list()
        if self.match(TT.PIPE): return self.parse_lambda()
        if self.match(TT.LBRACE): return self.parse_block()
        if self.match(TT.IF): return self.parse_if()
        if self.match(TT.LP): return self.parse_loop()
        raise SyntaxError(f"unexpected {t.t.name} ('{t.v}') at {t.line}:{t.col}")

    def parse_lambda(self):
        self.expect(TT.PIPE)
        ps = []
        while not self.match(TT.PIPE):
            name = self.expect(TT.IDENT).v
            typ = None
            if self.match(TT.COLON): self.adv(); typ = self.parse_type()
            ps.append(Param(name, typ))
            if self.match(TT.COMMA): self.adv()
        self.expect(TT.PIPE)
        return Lambda(ps, self.parse_expr())

    def parse_loop(self):
        self.expect(TT.LP)
        init = None
        cond = None
        post = None

        if self.match(TT.LET):
            self.adv()
            name = self.expect(TT.IDENT).v
            typ = None
            if self.match(TT.COLON):
                self.adv(); typ = self.parse_type()
            self.expect(TT.ASSIGN)
            val = self.parse_expr()
            init = LetExpr(name, val, IntLit(0), typ=typ)
        else:
            init = self.parse_expr()

        if self.match(TT.SEMI):
            self.adv()
            if self.match(TT.SEMI):
                cond = BoolLit(True)
            else:
                cond = self.parse_expr()
            self.expect(TT.SEMI)
            if not self.match(TT.LBRACE):
                post = self.parse_expr()
        else:
            cond = init
            init = None

        body = self.parse_expr()
        return LoopExpr(init, cond, post, body)

    def parse_block(self):
        self.expect(TT.LBRACE)
        stmts = []
        while not self.match(TT.RBRACE):
            if self.match(TT.LET):
                self.adv()
                name = self.expect(TT.IDENT).v
                typ = None
                if self.match(TT.COLON):
                    self.adv()
                    typ = self.parse_type()
                self.expect(TT.ASSIGN)
                val = self.parse_expr()
                stmts.append(('let', name, val, typ))
            elif self.match(TT.RET):
                stmts.append(('ret', self.parse_ret()))
            else:
                stmts.append(('expr', self.parse_expr()))
            if self.match(TT.SEMI): self.adv()
        self.expect(TT.RBRACE)
        if not stmts:
            return IntLit(0)

        body = None
        for kind, *rest in reversed(stmts):
            if kind == 'let':
                name, val, typ = rest
                body = LetExpr(name, val, body if body is not None else IntLit(0), typ=typ)
            elif kind == 'ret':
                body = rest[0]
            else:
                e = rest[0]
                if body is None:
                    body = e
                else:
                    body = LetExpr("_", e, body)
        return body if body is not None else IntLit(0)

    def parse_if(self):
        self.expect(TT.IF)
        cond = self.parse_expr()
        then = self.parse_expr()
        els = None
        if self.match(TT.ELSE):
            self.adv(); els = self.parse_expr()
        return IfExpr(cond, then, els)

    def is_http_serve_call(self, e: Expr) -> bool:
        # Call(Member(Var("http"), "serve"), [...])
        if not isinstance(e, Call) or not e.args:
            return False
        f = e.func
        return (isinstance(f, Member) and isinstance(f.obj, Var)
                and f.obj.name == 'http' and f.field == 'serve')

    def parse_routes(self) -> List[Route]:
        routes = []
        self.expect(TT.LBRACE)
        while not self.match(TT.RBRACE):
            # get/post/put/delete as IDENT
            if not self.match(TT.IDENT):
                t = self.cur()
                raise SyntaxError(f"expected method at {t.line}:{t.col}")
            method = self.adv().v.upper()
            if method not in ('GET','POST','PUT','DELETE','PATCH'):
                raise SyntaxError(f"unknown method {method}")
            path_tok = self.expect(TT.STRING)
            self.expect(TT.FATARROW)
            handler = self.parse_expr()
            routes.append(Route(method, path_tok.v, handler))
            if self.match(TT.SEMI): self.adv()
        self.expect(TT.RBRACE)
        return routes

    def parse_record_lit(self, ctor: Expr):
        self.expect(TT.LBRACE)
        fields = []
        while not self.match(TT.RBRACE):
            name = self.expect(TT.IDENT).v
            self.expect(TT.COLON)
            value = self.parse_expr()
            fields.append((name, value))
            if self.match(TT.COMMA): self.adv()
        self.expect(TT.RBRACE)
        return RecordLit(ctor, fields)

    def parse_postfix(self):
        e = self.parse_primary()
        while True:
            if self.match(TT.DOT):
                self.adv()
                field = self.expect(TT.IDENT).v
                e = Member(e, field)
            elif self.match(TT.LBRACE):
                if isinstance(e, (Var, Member)):
                    e = self.parse_record_lit(e)
                else:
                    break
            elif self.match(TT.LPAREN):
                self.adv()
                args = []
                while not self.match(TT.RPAREN):
                    args.append(self.parse_expr())
                    if self.match(TT.COMMA): self.adv()
                self.expect(TT.RPAREN)
                e = Call(e, args)
                # http.serve(port) { routes }
                if self.is_http_serve_call(e) and self.match(TT.LBRACE):
                    routes = self.parse_routes()
                    e = HttpServe(e.args[0], routes)
            elif self.match(TT.LBRACK):
                self.adv()
                idx = self.parse_expr()
                self.expect(TT.RBRACK)
                e = Index(e, idx)
            else:
                break
        return e

    def parse_unary(self):
        if self.match(TT.NOT, TT.MINUS):
            op = self.adv().v
            return Unary(op, self.parse_unary())
        return self.parse_postfix()

    def parse_mul(self):
        l = self.parse_unary()
        while self.match(TT.STAR, TT.SLASH, TT.PERCENT):
            op = self.adv().v
            l = Binary(op, l, self.parse_unary())
        return l

    def parse_add(self):
        l = self.parse_mul()
        while self.match(TT.PLUS, TT.MINUS):
            op = self.adv().v
            l = Binary(op, l, self.parse_mul())
        return l

    def parse_cmp(self):
        l = self.parse_add()
        while self.match(TT.EQ, TT.NEQ, TT.LT, TT.GT, TT.LE, TT.GE):
            op = self.adv().v
            l = Binary(op, l, self.parse_add())
        return l

    def parse_and(self):
        l = self.parse_cmp()
        while self.match(TT.AND):
            self.adv(); l = Binary('&&', l, self.parse_cmp())
        return l

    def parse_or(self):
        l = self.parse_and()
        while self.match(TT.OR):
            self.adv(); l = Binary('||', l, self.parse_and())
        return l

    def parse_assign(self):
        l = self.parse_or()
        if self.match(TT.ASSIGN):
            self.adv()
            r = self.parse_assign()
            return Binary('=', l, r)
        return l

    def parse_expr(self):
        return self.parse_assign()

    def skip_use(self):
        # use std.http, std.db
        self.expect(TT.USE)
        while True:
            self.expect(TT.IDENT)
            while self.match(TT.DOT):
                self.adv(); self.expect(TT.IDENT)
            if self.match(TT.COMMA):
                self.adv(); continue
            break
        if self.match(TT.SEMI): self.adv()

    def skip_type(self):
        # type User = { ... }  or type User = i64
        self.expect(TT.TYPE)
        self.expect(TT.IDENT)
        self.expect(TT.ASSIGN)
        self.parse_type()
        if self.match(TT.SEMI): self.adv()

    def parse_rec(self):
        if self.match(TT.IDENT):
            tok = self.adv()
            if tok.v in ('rec', 'struct'):
                name = self.expect(TT.IDENT).v
            else:
                name = tok.v
        else:
            raise SyntaxError(f"expected record name at {self.cur().line}:{self.cur().col}")
        self.expect(TT.LBRACE)
        fields = []
        while not self.match(TT.RBRACE):
            field_name = self.expect(TT.IDENT).v
            self.expect(TT.COLON)
            field_type = self.parse_type()
            fields.append((field_name, field_type))
            if self.match(TT.COMMA): self.adv()
        self.expect(TT.RBRACE)
        return RecDecl(name, fields)

    def parse_sig(self):
        self.expect(TT.SIG)
        name = self.expect(TT.IDENT).v
        self.expect(TT.LBRACE)
        methods = []
        while not self.match(TT.RBRACE):
            self.expect(TT.FN)
            method_name = self.expect(TT.IDENT).v
            params = self.parse_params()
            ret = None
            if self.match(TT.ARROW):
                self.adv(); ret = self.parse_type()
            methods.append((method_name, params, ret))
            if self.match(TT.SEMI): self.adv()
        self.expect(TT.RBRACE)
        return SigDecl(name, methods)

    def parse_fit(self):
        self.expect(TT.FIT)
        name = self.expect(TT.IDENT).v
        ifaces = []
        if self.match(TT.AS):
            self.adv()
            ifaces.append(self.expect(TT.IDENT).v)
            while self.match(TT.COMMA):
                self.adv()
                ifaces.append(self.expect(TT.IDENT).v)
        self.expect(TT.LBRACE)
        methods = []
        while not self.match(TT.RBRACE):
            methods.append(self.parse_fn())
        self.expect(TT.RBRACE)
        return FitDecl(name, ifaces, methods)

    def parse_fn(self):
        if self.match(TT.FN):
            self.adv()
        name = self.expect(TT.IDENT).v
        params = self.parse_params()
        ret = None
        if self.match(TT.ARROW):
            self.adv(); ret = self.parse_type()
        if self.match(TT.ASSIGN): self.adv()
        body = self.parse_expr()
        return FnDecl(name, params, ret, body)

    def parse_go(self):
        # caller already matched/consumed GO, or we consume it here
        if self.match(TT.GO):
            self.adv()
        return self.parse_expr()

    def parse_program(self):
        fs = []
        recs = []
        sigs = []
        fits = []
        top_stmts = []
        go_body = None
        while not self.match(TT.EOF):
            if self.match(TT.USE):
                self.skip_use()
            elif self.match(TT.IDENT):
                next_tok = self.toks[self.i + 1] if self.i + 1 < len(self.toks) else None
                if (self.cur().v in ('rec', 'struct') and next_tok is not None and next_tok.t == TT.IDENT and self.i + 2 < len(self.toks) and self.toks[self.i + 2].t == TT.LBRACE) or (next_tok is not None and next_tok.t == TT.LBRACE):
                    recs.append(self.parse_rec())
                else:
                    top_stmts.append(('expr', self.parse_expr()))
                    if self.match(TT.SEMI): self.adv()
            elif self.match(TT.TYPE):
                self.skip_type()
            elif self.match(TT.SIG):
                sigs.append(self.parse_sig())
            elif self.match(TT.FIT):
                fit = self.parse_fit()
                fits.append(fit)
            elif self.match(TT.FN):
                fs.append(self.parse_fn())
            elif self.match(TT.GO):
                if go_body is not None:
                    raise SyntaxError("multiple go entry points")
                go_body = self.parse_go()
            elif self.match(TT.LET):
                self.adv()
                name = self.expect(TT.IDENT).v
                typ = None
                if self.match(TT.COLON):
                    self.adv()
                    typ = self.parse_type()
                self.expect(TT.ASSIGN)
                val = self.parse_expr()
                top_stmts.append(('let', name, val, typ))
                if self.match(TT.SEMI): self.adv()
            else:
                # top-level expression (side effects + final value)
                top_stmts.append(('expr', self.parse_expr()))
                if self.match(TT.SEMI): self.adv()
        # Prefer: fn main > go > toplevel stmts
        has_main = any(f.name == 'main' for f in fs)
        toplevel = None
        if not has_main:
            if go_body is not None:
                toplevel = go_body
            elif top_stmts:
                body = IntLit(0)
                first = True
                for kind, *rest in reversed(top_stmts):
                    if kind == 'let':
                        name, val, typ = rest
                        body = LetExpr(name, val, body, typ=typ)
                    else:
                        e = rest[0]
                        if first:
                            body = e
                            first = False
                        else:
                            body = LetExpr("_", e, body)
                toplevel = body
            elif not fs:
                toplevel = IntLit(0)
        return Program(fs, recs, sigs, fits, toplevel)

# --- Type check (light) -----------------------------------
class TypeChecker:
    def __init__(self):
        self.funcs = {}
        self.env = {}
        self.errors = []
        self.recs = {}
    def check_program(self, prog):
        self.recs = {r.name: {n: t.name if t else 'i64' for n, t in r.fields} for r in prog.recs}
        for f in prog.funcs:
            ats = [p.typ.name if p.typ else 'i64' for p in f.params]
            self.funcs[f.name] = (ats, f.ret.name if f.ret else 'i64')
        for f in prog.funcs:
            self.env = {p.name: (p.typ.name if p.typ else 'i64') for p in f.params}
            self.check(f.body)
        if prog.toplevel is not None:
            self.env = {}
            self.check(prog.toplevel)
        return self.errors
    def check(self, e):
        if isinstance(e, (IntLit,)): return 'i64'
        if isinstance(e, BoolLit): return 'bool'
        if isinstance(e, StrLit): return 'str'
        if isinstance(e, ListLit):
            for it in e.items: self.check(it)
            return 'list'
        if isinstance(e, RecordLit):
            for _, v in e.fields: self.check(v)
            if isinstance(e.ctor, Var) and e.ctor.name in self.recs:
                return e.ctor.name
            return 'i64'
        if isinstance(e, Var):
            if e.name in self.env: return self.env[e.name]
            if e.name in self.funcs or e.name in ('pr','len','json','env','str'): return 'fn'
            if e.name in ('http','db'): return 'mod'
            return 'i64'
        if isinstance(e, Member):
            base = self.check(e.obj)
            if base in self.recs:
                return self.recs[base].get(e.field, 'i64')
            return 'i64'
        if isinstance(e, Binary):
            self.check(e.left); self.check(e.right)
            return 'str' if e.op == '+' else ('bool' if e.op in '==!=<=>=<>&&||' else 'i64')
        if isinstance(e, Unary): return self.check(e.expr)
        if isinstance(e, RetExpr):
            if e.value is not None:
                return self.check(e.value)
            return 'i64'
        if isinstance(e, Call):
            self.check(e.func)
            for a in e.args: self.check(a)
            if isinstance(e.func, Var) and e.func.name in ('pr','json','env'): return 'str' if e.func.name in ('json','env') else 'i64'
            if isinstance(e.func, Var) and e.func.name == 'len': return 'i64'
            return 'i64'
        if isinstance(e, Index):
            self.check(e.coll); self.check(e.idx); return 'i64'
        if isinstance(e, IfExpr):
            self.check(e.cond); t=self.check(e.then)
            if e.els: self.check(e.els)
            return t
        if isinstance(e, LoopExpr):
            old_env = self.env.copy()
            if e.init is not None:
                if isinstance(e.init, LetExpr):
                    t = e.init.typ.name if e.init.typ else self.check(e.init.value)
                    old = self.env.get(e.init.name)
                    self.env[e.init.name] = t
                else:
                    self.check(e.init)
            self.check(e.cond)
            self.check(e.body)
            if e.post is not None:
                self.check(e.post)
            self.env = old_env
            return 'i64'
        if isinstance(e, LetExpr):
            t = e.typ.name if e.typ else self.check(e.value)
            old = self.env.get(e.name)
            self.env[e.name] = t
            r = self.check(e.body)
            if old is not None: self.env[e.name] = old
            else: self.env.pop(e.name, None)
            return r
        if isinstance(e, Lambda):
            old = self.env.copy()
            for p in e.params:
                self.env[p.name] = p.typ.name if p.typ else 'i64'  # body often request body
            self.check(e.body)
            self.env = old
            return 'fn'
        if isinstance(e, HttpServe):
            self.check(e.port)
            for r in e.routes:
                self.check(r.handler)
            return 'i64'
        if isinstance(e, Block):
            t = 'i64'
            for s in e.stmts: t = self.check(s)
            return t
        return 'i64'

# --- C runtime + HTTP server ------------------------------
RUNTIME = r'''
#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifdef _WIN32
  #define WIN32_LEAN_AND_MEAN
  #include <windows.h>
  #include <winsock2.h>
  #include <ws2tcpip.h>
  typedef SOCKET sock_t;
  #define CLOSESOCK closesocket
  #define SOCK_ERR SOCKET_ERROR
  static void sock_init(void) {
    WSADATA wsa;
    if (WSAStartup(MAKEWORD(2,2), &wsa) != 0) { fprintf(stderr, "WSAStartup failed\n"); exit(1); }
  }
  static void sock_fini(void) { WSACleanup(); }
#else
  #include <unistd.h>
  #include <sys/socket.h>
  #include <netinet/in.h>
  #include <arpa/inet.h>
  #include <signal.h>
  typedef int sock_t;
  #define CLOSESOCK close
  #define SOCK_ERR (-1)
  static void sock_init(void) {}
  static void sock_fini(void) {}
#endif

typedef struct { int64_t *d; int64_t n; } List;

static List list_new(int64_t n) {
  List L; L.n = n; L.d = (int64_t*)malloc(sizeof(int64_t) * (n > 0 ? n : 1));
  return L;
}
static int64_t list_get(List L, int64_t i) {
  if (i < 0 || i >= L.n) { fprintf(stderr, "index out of bounds\n"); exit(1); }
  return L.d[i];
}
static int64_t list_len(List L) { return L.n; }

static char* str_from_i64(int64_t x) {
  char* b = (char*)malloc(32);
  snprintf(b, 32, "%lld", (long long)x);
  return b;
}
static char* str_from_bool(bool v) {
  const char* s = v ? "true" : "false";
  size_t n = strlen(s);
  char* b = (char*)malloc(n + 1);
  memcpy(b, s, n + 1);
  return b;
}
static char* str_concat(const char* a, const char* b) {
  size_t na = strlen(a), nb = strlen(b);
  char* r = (char*)malloc(na + nb + 1);
  memcpy(r, a, na); memcpy(r + na, b, nb); r[na+nb] = 0;
  return r;
}
static int64_t str_len(const char* s) { return (int64_t)strlen(s); }

static int _terse_did_print = 0;
static void print_int(int64_t x) { _terse_did_print = 1; printf("%lld\n", (long long)x); }
static void print_list(List L) {
  _terse_did_print = 1;
  printf("[");
  for (int64_t i = 0; i < L.n; i++) {
    if (i) printf(", ");
    printf("%lld", (long long)L.d[i]);
  }
  printf("]\n");
}

static void print_i64(int64_t x) { _terse_did_print = 1; printf("%lld\n", (long long)x); }
static void print_bool(bool v) { _terse_did_print = 1; printf(v ? "true\n" : "false\n"); }
static void print_str(const char* s) { _terse_did_print = 1; printf("%s\n", s); }

static char* json_int(int64_t x) {
  char* b = (char*)malloc(32);
  snprintf(b, 32, "%lld", (long long)x);
  return b;
}
static char* json_str(const char* s) {
  size_t n = strlen(s);
  char* b = (char*)malloc(n + 3);
  b[0] = '"'; memcpy(b+1, s, n); b[n+1] = '"'; b[n+2] = 0;
  return b;
}
static char* json_list(List L) {
  /* rough buffer */
  size_t cap = 64 + L.n * 24;
  char* b = (char*)malloc(cap);
  size_t o = 0;
  b[o++] = '[';
  for (int64_t i = 0; i < L.n; i++) {
    if (i) b[o++] = ',';
    o += (size_t)snprintf(b+o, cap-o, "%lld", (long long)L.d[i]);
  }
  b[o++] = ']'; b[o] = 0;
  return b;
}

static const char* env_get(const char* k) {
  const char* v = getenv(k);
  return v ? v : "";
}

/* -- minimal HTTP/1.1 server -- */
typedef const char* (*route_fn)(const char* method, const char* path, const char* body);

static void http_send(sock_t fd, int code, const char* ctype, const char* body) {
  char hdr[512];
  int blen = body ? (int)strlen(body) : 0;
  const char* msg = code==200 ? "OK" : code==404 ? "Not Found" : "Error";
  int n = snprintf(hdr, sizeof(hdr),
    "HTTP/1.1 %d %s\r\nContent-Type: %s\r\nContent-Length: %d\r\nConnection: close\r\n\r\n",
    code, msg, ctype, blen);
  send(fd, hdr, n, 0);
  if (body && blen) send(fd, body, blen, 0);
}

static void http_serve_run(int64_t port, route_fn handler) {
  sock_init();
#ifndef _WIN32
  signal(SIGPIPE, SIG_IGN);
#endif
  sock_t srv = socket(AF_INET, SOCK_STREAM, 0);
  if (srv == (sock_t)SOCK_ERR) { fprintf(stderr, "socket failed\n"); exit(1); }
  int yes = 1;
  setsockopt(srv, SOL_SOCKET, SO_REUSEADDR, (const char*)&yes, sizeof(yes));
  struct sockaddr_in addr;
  memset(&addr, 0, sizeof(addr));
  addr.sin_family = AF_INET;
  addr.sin_addr.s_addr = htonl(INADDR_ANY);
  addr.sin_port = htons((uint16_t)port);
  if (bind(srv, (struct sockaddr*)&addr, sizeof(addr)) == SOCK_ERR) {
    fprintf(stderr, "bind failed\n"); exit(1);
  }
  if (listen(srv, 64) == SOCK_ERR) { fprintf(stderr, "listen failed\n"); exit(1); }
  fprintf(stderr, "terse http listening on :%lld\n", (long long)port);
  for (;;) {
    sock_t cli = accept(srv, NULL, NULL);
    if (cli == (sock_t)SOCK_ERR) continue;
    char buf[65536];
    int n = (int)recv(cli, buf, sizeof(buf)-1, 0);
    if (n <= 0) { CLOSESOCK(cli); continue; }
    buf[n] = 0;
    char method[16] = {0}, path[2048] = {0};
    sscanf(buf, "%15s %2047s", method, path);
    const char* body = "";
    char* sep = strstr(buf, "\r\n\r\n");
    if (sep) body = sep + 4;
    const char* resp = handler(method, path, body);
    if (resp)
      http_send(cli, 200, "application/json; charset=utf-8", resp);
    else
      http_send(cli, 404, "text/plain", "not found");
    CLOSESOCK(cli);
  }
}
'''

class CodeGen:
    def __init__(self):
        self.lines = []
        self.indent = 0
        self.lam_n = 0
        self.extra = []
        self.known = {}
        self.tmp = 0
        self.env = {}
        self.route_handlers = []  # generated C funcs for routes
        self.record_field_types = {}
        self.method_names = {}
        self.method_returns = {}

    def emit(self, s=""):
        self.lines.append("  " * self.indent + s)

    def fresh(self):
        self.tmp += 1
        return f"_t{self.tmp}"

    def type_name(self, typ):
        return typ.name if typ else 'i64'

    def c_type(self, t):
        return {'fn':'void*','str':'const char*','list':'List','i64':'int64_t','i32':'int32_t','u64':'uint64_t','bool':'bool','f64':'double'}.get(t, t)

    def expr_type(self, e) -> str:
        if isinstance(e, Var):
            return self.env.get(e.name, 'i64')
        if isinstance(e, RecordLit):
            return e.ctor.name if isinstance(e.ctor, Var) else 'record'
        if isinstance(e, Member):
            base_type = self.expr_type(e.obj)
            return self.record_field_types.get(base_type, {}).get(e.field, 'i64')
        return 'i64'

    def gen_expr(self, e) -> Tuple[str, str]:
        if isinstance(e, IntLit):
            return f"INT64_C({e.value})", "i64"
        if isinstance(e, BoolLit):
            return ("true" if e.value else "false"), "bool"
        if isinstance(e, StrLit):
            s = e.value.replace('\\','\\\\').replace('"','\\"').replace('\n','\\n').replace('\t','\\t')
            return f'"{s}"', "str"
        if isinstance(e, RecordLit):
            rec_name = e.ctor.name if isinstance(e.ctor, Var) else 'record'
            parts = []
            for name, val in e.fields:
                v, _ = self.gen_expr(val)
                parts.append(f".{name} = {v}")
            return f"(({rec_name}){{ {', '.join(parts)} }})", rec_name
        if isinstance(e, Var):
            if e.name in self.known:
                return f"(void*){self.known[e.name]}", "fn"
            return e.name, self.env.get(e.name, "i64")
        if isinstance(e, Member):
            base, btype = self.gen_expr(e.obj)
            field_type = self.record_field_types.get(btype, {}).get(e.field, 'i64')
            return f"(({base}).{e.field})", field_type
        if isinstance(e, Binary):
            l, lt = self.gen_expr(e.left)
            r, rt = self.gen_expr(e.right)
            if e.op == '+' and (lt == 'str' or rt == 'str'):
                if lt == 'str' and rt == 'str':
                    return f"str_concat({l}, {r})", "str"
                if lt == 'str' and rt == 'i64':
                    return f"str_concat({l}, str_from_i64({r}))", "str"
                if lt == 'i64' and rt == 'str':
                    return f"str_concat(str_from_i64({l}), {r})", "str"
                if lt == 'str' and rt == 'bool':
                    return f"str_concat({l}, str_from_bool({r}))", "str"
                if lt == 'bool' and rt == 'str':
                    return f"str_concat(str_from_bool({l}), {r})", "str"
            return f"({l} {e.op} {r})", ("bool" if e.op in ('==','!=','<','>','<=','>=','&&','||') else "i64")
        if isinstance(e, Unary):
            x, _ = self.gen_expr(e.expr)
            return f"({e.op}{x})", "i64"
        if isinstance(e, RetExpr):
            if e.value is not None:
                v, vt = self.gen_expr(e.value)
                return f"({{ return {v}; INT64_C(0); }})", vt
            return "({ return INT64_C(0); INT64_C(0); })", "i64"
        if isinstance(e, ListLit):
            n = len(e.items)
            tmp = self.fresh()
            parts = [f"List {tmp} = list_new({n})"]
            for i, it in enumerate(e.items):
                v, _ = self.gen_expr(it)
                parts.append(f"{tmp}.d[{i}] = {v}")
            parts.append(tmp)
            return "({ " + "; ".join(parts) + "; })", "list"
        if isinstance(e, Index):
            c, ct = self.gen_expr(e.coll)
            i, _ = self.gen_expr(e.idx)
            if ct == 'str':
                return f"((int64_t)((unsigned char){c}[{i}]))", "i64"
            return f"list_get({c}, {i})", "i64"
        if isinstance(e, Call):
            # builtins
            if isinstance(e.func, Var) and e.func.name == 'pr':
                a, at = self.gen_expr(e.args[0])
                if at == 'str':
                    return f"(print_str({a}), INT64_C(0))", "i64"
                if at == 'list':
                    return f"(print_list({a}), INT64_C(0))", "i64"
                if at == 'bool':
                    return f"(print_bool({a}), INT64_C(0))", "i64"
                return f"(print_i64({a}), INT64_C(0))", "i64"
            if isinstance(e.func, Var) and e.func.name == 'len':
                a, at = self.gen_expr(e.args[0])
                return (f"str_len({a})", "i64") if at == 'str' else (f"list_len({a})", "i64")
            if isinstance(e.func, Var) and e.func.name == 'json':
                a, at = self.gen_expr(e.args[0])
                if at == 'str': return f"json_str({a})", "str"
                if at == 'list': return f"json_list({a})", "str"
                return f"json_int({a})", "str"
            if isinstance(e.func, Var) and e.func.name == 'env':
                a, _ = self.gen_expr(e.args[0])
                return f"env_get({a})", "str"
            # db.connect / db.query stubs
            if isinstance(e.func, Member) and isinstance(e.func.obj, Var) and e.func.obj.name == 'db':
                if e.func.field == 'connect':
                    return "INT64_C(0)", "i64"  # no-op success
                if e.func.field in ('query', 'query_one', 'exec'):
                    # return empty list / empty
                    return "list_new(0)", "list"
            if isinstance(e.func, Member):
                base_type = self.expr_type(e.func.obj)
                method_key = (base_type, e.func.field)
                if method_key in self.method_names:
                    args = [self.gen_expr(e.func.obj)[0]] + [self.gen_expr(a)[0] for a in e.args]
                    cname = self.method_names[method_key]
                    return f"{cname}({', '.join(args)})", self.method_returns[method_key]
            if isinstance(e.func, Var) and e.func.name in self.known:
                cname = self.known[e.func.name]
                args = ", ".join(self.gen_expr(a)[0] for a in e.args)
                return f"{cname}({args})", "i64"
            fptr, _ = self.gen_expr(e.func)
            args = ", ".join(self.gen_expr(a)[0] for a in e.args)
            n = len(e.args)
            arg_ts = ", ".join(["int64_t"] * n) if n else "void"
            return f"((int64_t(*)({arg_ts}))({fptr}))({args})", "i64"
        if isinstance(e, IfExpr):
            c, _ = self.gen_expr(e.cond)
            t, tt = self.gen_expr(e.then)
            f, _ = self.gen_expr(e.els) if e.els else ("INT64_C(0)", "i64")
            return f"({c} ? {t} : {f})", tt
        if isinstance(e, LoopExpr):
            old_env = self.env.copy()
            init_decl = None
            init_stmt = None
            if e.init is not None:
                if isinstance(e.init, LetExpr):
                    v, vt = self.gen_expr(e.init.value)
                    if e.init.typ is not None:
                        vt = self.type_name(e.init.typ)
                    init_decl = f"{self.c_type(vt)} {e.init.name} = {v};"
                    self.env[e.init.name] = vt
                elif isinstance(e.init, Binary) and isinstance(e.init.left, Var) and e.init.left.name not in self.env:
                    right, _ = self.gen_expr(e.init.right)
                    init_decl = f"int64_t {e.init.left.name} = {right};"
                    self.env[e.init.left.name] = 'i64'
                else:
                    init_e, _ = self.gen_expr(e.init)
                    init_stmt = f"(void)({init_e});"
            cond_c, _ = self.gen_expr(e.cond)
            body_c, _ = self.gen_expr(e.body)
            post_c = ''
            if e.post is not None:
                post_e, _ = self.gen_expr(e.post)
                post_c = f"(void)({post_e});"
            self.env = old_env
            if init_decl is not None:
                return (f"({{ {init_decl} while({cond_c}) {{ (void)({body_c}); {post_c} }} INT64_C(0); }})", "i64")
            if init_stmt is not None:
                return (f"({{ {init_stmt} while({cond_c}) {{ (void)({body_c}); {post_c} }} INT64_C(0); }})", "i64")
            return (f"({{ while({cond_c}) {{ (void)({body_c}); {post_c} }} INT64_C(0); }})", "i64")
        if isinstance(e, LetExpr):
            v, vt = self.gen_expr(e.value)
            if e.typ is not None:
                vt = self.type_name(e.typ)
            old = self.env.get(e.name)
            self.env[e.name] = vt
            body, bt = self.gen_expr(e.body)
            if old is not None: self.env[e.name] = old
            else: self.env.pop(e.name, None)
            if e.name == "_":
                return f"({{ (void)({v}); {body}; }})", bt
            decl = f"{self.c_type(vt)} {e.name} = {v}"
            return f"({{ {decl}; {body}; }})", bt
        if isinstance(e, Lambda):
            self.lam_n += 1
            lname = f"__lambda_{self.lam_n}"
            # HTTP body handlers often take str body
            ps_c = []
            for p in e.params:
                tn = self.type_name(p.typ) if p.typ else 'i64'
                ps_c.append(f"{self.c_type(tn)} {p.name}")
            ps = ", ".join(ps_c) or "void"
            # save env params
            old_env = self.env.copy()
            for p in e.params:
                self.env[p.name] = self.type_name(p.typ) if p.typ else 'i64'
            body, bt = self.gen_expr(e.body)
            self.env = old_env
            ret_c = self.c_type(bt)
            self.extra.append(f"static {ret_c} {lname}({ps}) {{\n  return {body};\n}}\n")
            return f"(void*){lname}", "fn"
        if isinstance(e, HttpServe):
            return self.gen_http_serve(e)
        if isinstance(e, Block):
            if not e.stmts: return "INT64_C(0)", "i64"
            return self.gen_expr(e.stmts[-1])
        return "INT64_C(0)", "i64"

    def gen_http_serve(self, e: HttpServe) -> Tuple[str, str]:
        port_c, _ = self.gen_expr(e.port)
        self.lam_n += 1
        dispatcher = f"__http_dispatch_{self.lam_n}"
        # Build dispatcher that matches method+path and runs handler
        lines = [f"static const char* {dispatcher}(const char* method, const char* path, const char* body) {{"]
        for i, r in enumerate(e.routes):
            hname = f"__route_{self.lam_n}_{i}"
            # Generate handler wrapper
            # If handler is Lambda with 1 param, pass body
            if isinstance(r.handler, Lambda) and len(r.handler.params) >= 1:
                old = self.env.copy()
                for p in r.handler.params:
                    self.env[p.name] = 'str'
                body_c, bt = self.gen_expr(r.handler.body)
                self.env = old
                if bt != 'str':
                    body_c = f"json_int({body_c})"
                self.extra.append(
                    f"static const char* {hname}(const char* body) {{\n  return {body_c};\n}}\n"
                )
                call = f"{hname}(body)"
            else:
                body_c, bt = self.gen_expr(r.handler)
                if bt == 'i64':
                    body_c = f"json_int({body_c})"
                elif bt == 'list':
                    body_c = f"json_list({body_c})"
                elif bt != 'str':
                    body_c = f'"{bt}"'
                # constant / expression handler - embed as function returning that
                self.extra.append(
                    f"static const char* {hname}(const char* body) {{\n  (void)body;\n  return {body_c};\n}}\n"
                )
                call = f"{hname}(body)"
            lines.append(f'  if (strcmp(method, "{r.method}") == 0 && strcmp(path, "{r.path}") == 0) return {call};')
        lines.append("  return NULL;")
        lines.append("}\n")
        self.extra.append("\n".join(lines))
        # http_serve_run never returns
        return f"(http_serve_run({port_c}, {dispatcher}), INT64_C(0))", "i64"

    def gen_fn(self, f: FnDecl):
        cname = self.known[f.name]
        pcs = []
        for p in f.params:
            tn = self.type_name(p.typ) if p.typ else 'i64'
            pcs.append(f"{self.c_type(tn)} {p.name}")
        ret = self.type_name(f.ret) if f.ret else 'i64'
        crt = self.c_type(ret)
        pstr = ", ".join(pcs) if pcs else "void"
        old_env = self.env.copy()
        for p in f.params:
            self.env[p.name] = self.type_name(p.typ) if p.typ else 'i64'
        if f.params and f.params[0].name == 'self':
            self.env['self'] = self.type_name(f.params[0].typ) if f.params[0].typ else 'i64'
        body, _ = self.gen_expr(f.body)
        self.env = old_env
        self.emit(f"{crt} {cname}({pstr}) {{")
        self.indent += 1
        self.emit(f"return {body};")
        self.indent -= 1
        self.emit("}")
        self.emit()

    def generate(self, prog: Program) -> str:
        self.record_field_types = {r.name: {n: self.type_name(t) for n, t in r.fields} for r in prog.recs}
        self.method_names = {}
        self.method_returns = {}
        funcs = list(prog.funcs)
        for fit in prog.fits:
            for m in fit.methods:
                method_name = f"{fit.name}_{m.name}"
                self.method_names[(fit.name, m.name)] = "terse_" + method_name
                self.method_returns[(fit.name, m.name)] = self.type_name(m.ret) if m.ret else 'i64'
                receiver = Param('self', TypeNode(fit.name))
                funcs.append(FnDecl(method_name, [receiver] + list(m.params), m.ret, m.body))
        if prog.toplevel is not None and not any(f.name == 'main' for f in funcs):
            funcs = funcs + [FnDecl('main', [], TypeNode('i64'), prog.toplevel)]
        for f in funcs:
            self.known[f.name] = "terse_" + f.name
        out = [RUNTIME, ""]
        for rec in prog.recs:
            fields = []
            for name, typ in rec.fields:
                fields.append(f"  {self.c_type(self.type_name(typ))} {name};")
            if fields:
                out.append("typedef struct {")
                out.extend(fields)
                out.append(f"}} {rec.name};")
                out.append("")
        # emit generated fit methods after record declarations so their receiver type is known
        for f in funcs:
            cname = self.known[f.name]
            pcs = []
            for p in f.params:
                tn = self.type_name(p.typ) if p.typ else 'i64'
                pcs.append(self.c_type(tn))
            ret = self.type_name(f.ret) if f.ret else 'i64'
            crt = self.c_type(ret)
            pstr = ", ".join(pcs) if pcs else "void"
            out.append(f"{crt} {cname}({pstr});")
        out.append("")
        self.lines = []
        for f in funcs:
            self.gen_fn(f)
        out.extend(self.extra)
        out.extend(self.lines)
        if any(f.name == 'main' for f in prog.funcs):
            out += [
                "",
                "int main(int argc, char** argv) {",
                "  int64_t result = terse_main();",
                "  /* skip trailing 0 when pr already produced output */",
                "  if (!(_terse_did_print && result == 0))",
                "    printf(\"%lld\\n\", (long long)result);",
                "  return 0;",
                "}"
            ]
        return "\n".join(out)

# --- Driver -----------------------------------------------
def compile_terse(src, out_bin, keep_c=False, verbose=False):
    try:
        toks = Lexer(src).tokenize()
        if verbose:
            print("tokens:", [(t.t.name, t.v) for t in toks[:50]])
        prog = Parser(toks).parse_program()
        if verbose:
            print("funcs:", [f.name for f in prog.funcs])
        errs = TypeChecker().check_program(prog)
        for e in errs:
            print(f"type warning: {e}", file=sys.stderr)
        c_code = CodeGen().generate(prog)
        c_file = out_bin + ".c"
        with open(c_file, "w", encoding="utf-8") as f:
            f.write(c_code)
        if verbose:
            print("----- C -----"); print(c_code); print("-----")

        gcc_out = out_bin
        if sys.platform == "win32" and os.path.splitext(out_bin)[1].lower() != ".exe":
            gcc_out = out_bin + ".exe"

        cmd = ["gcc", "-O2", "-std=c11", c_file, "-o", gcc_out]
        if sys.platform == "win32":
            cmd.append("-lws2_32")
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            print("C compile failed:", file=sys.stderr)
            print(r.stderr, file=sys.stderr)
            return 1
        if sys.platform == "win32" and gcc_out != out_bin and os.path.exists(gcc_out):
            shutil.copy2(gcc_out, out_bin)
            try:
                os.remove(gcc_out)
            except OSError:
                pass
        if not keep_c:
            try: os.remove(c_file)
            except: pass
        print(f"Compiled -> {out_bin}")
        return 0
    except SyntaxError as e:
        print(f"Syntax error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback; traceback.print_exc()
        return 1

def main():
    ap = argparse.ArgumentParser(description="tersec v0.3")
    ap.add_argument("command", choices=["build","run","check"])
    ap.add_argument("source")
    ap.add_argument("-o", "--output", default=None)
    ap.add_argument("--keep-c", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    with open(args.source, encoding="utf-8") as f:
        src = f.read()
    if args.command == "check":
        try:
            prog = Parser(Lexer(src).tokenize()).parse_program()
            errs = TypeChecker().check_program(prog)
            if errs:
                for e in errs: print(e)
                sys.exit(1)
            print("OK"); sys.exit(0)
        except Exception as e:
            print(e); sys.exit(1)
    out = args.output or os.path.splitext(os.path.basename(args.source))[0]
    if args.command == "build":
        sys.exit(compile_terse(src, out, args.keep_c, args.verbose))
    if args.command == "run":
        if compile_terse(src, out, args.keep_c, args.verbose) != 0:
            sys.exit(1)
        sys.exit(subprocess.run([os.path.abspath(out)]).returncode)

if __name__ == "__main__":
    main()
