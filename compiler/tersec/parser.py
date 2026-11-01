#!/usr/bin/env python3
"""Terse Parser — recursive-descent parser from tokens to AST."""
from __future__ import annotations

from .lexer import TT, Tok, Lexer
from .ast import (
    TypeNode, Param, Expr, IntLit, FloatLit, BoolLit, StrLit, Var,
    Binary, Unary, Call, Member, IfExpr, TernaryExpr, LetExpr,
    RetExpr, JumpExpr, Lambda, LoopExpr, ForInExpr, AssignExpr,
    Block, ListLit, MapLit, Index, FnDecl,
    RecDecl, TraitDecl, MethodDecl, UseDecl, RecordLit, EnumVariantDecl,
    EnumDecl, FixDecl, Wildcard, LiteralPattern, BindPattern,
    EnumVariant, RecordPattern, TuplePattern, ListPattern, MatchArm, MatchExpr,
    Program,
)


class Parser:
    def __init__(self, toks):
        self.toks, self.i = toks, 0

    def cur(self):
        return self.toks[self.i]

    def adv(self):
        t = self.cur()
        if t.t != TT.EOF: self.i += 1
        return t

    def expect(self, tt):
        if self.cur().t != tt:
            t = self.cur()
            raise SyntaxError(f"expected {tt.name} got {t.t.name}('{t.v}') at {t.line}:{t.col}")
        return self.adv()

    def match(self, *ts):
        return self.cur().t in ts

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
            elif self.match(TT.LBRACK):
                self.adv()
                while not self.match(TT.RBRACK):
                    args.append(self.parse_type())
                    if self.match(TT.COMMA): self.adv()
                self.expect(TT.RBRACK)
                return TypeNode(name, args)
            # Do NOT consume LBRACE after a type name — body `{ ... }` after
            # `-> Type` must stay for the expression parser. Map/record types
            # use a leading `{` (handled below) or `map`/`rec` keywords.
            if self.match(TT.LPAREN):
                self.adv()
                if self.match(TT.RPAREN):
                    self.adv()
                    return TypeNode('unit', [])
                first = self.parse_type()
                if self.match(TT.COMMA):
                    args = [first]
                    while self.match(TT.COMMA):
                        self.adv()
                        if self.match(TT.RPAREN): break
                        args.append(self.parse_type())
                    self.expect(TT.RPAREN)
                    return TypeNode(name, args)
                self.expect(TT.RPAREN)
                return TypeNode(name, [])
            return TypeNode(name, args)
        if self.match(TT.LBRACK):
            self.adv()
            inner = self.parse_type()
            self.expect(TT.RBRACK)
            return TypeNode('list', [inner])
        if self.match(TT.REC):
            self.adv()
            self.expect(TT.LBRACE)
            while not self.match(TT.RBRACE):
                self.expect(TT.IDENT)
                self.expect(TT.COLON)
                self.parse_type()
                if self.match(TT.COMMA): self.adv()
            self.expect(TT.RBRACE)
            return TypeNode('record', [])
        if self.match(TT.LBRACE):
            # {K: V} map type  |  {field: T, ...} anonymous record (multi-field)
            self.adv()
            if self.match(TT.RBRACE):
                self.adv()
                raise SyntaxError("empty {} is not a type; use {K: V} for maps")
            # Try map: type ":" type ["}"]
            k = self.parse_type()
            self.expect(TT.COLON)
            v = self.parse_type()
            if self.match(TT.RBRACE):
                self.adv()
                return TypeNode('map', [k, v])
            # Multi-field anonymous record — consume remaining field: type pairs
            while self.match(TT.COMMA):
                self.adv()
                if self.match(TT.RBRACE): break
                self.expect(TT.IDENT)
                self.expect(TT.COLON)
                self.parse_type()
            self.expect(TT.RBRACE)
            return TypeNode('record', [])
        if self.match(TT.LPAREN):
            self.adv()
            if self.match(TT.RPAREN):
                self.adv()
                return TypeNode('unit', [])
            first = self.parse_type()
            if self.match(TT.COMMA):
                args = [first]
                while self.match(TT.COMMA):
                    self.adv()
                    if self.match(TT.RPAREN): break
                    args.append(self.parse_type())
                self.expect(TT.RPAREN)
                return TypeNode('tuple', args)
            self.expect(TT.RPAREN)
        raise SyntaxError(f"type expected at {self.cur().line}:{self.cur().col}")

    def parse_program(self):
        fs = []
        recs = []
        enums = []
        sigs = []
        methods = []
        uses = []
        fixes = []
        top_stmts = []
        go_body = None
        while not self.match(TT.EOF):
            if self.match(TT.USE):
                uses.extend(self.skip_use())
            elif self.match(TT.REC):
                recs.append(self.parse_rec())
            elif self.match(TT.IDENT):
                next_tok = self.toks[self.i + 1] if self.i + 1 < len(self.toks) else None
                if (self.cur().v in ('rec', 'struct') and next_tok is not None and next_tok.t == TT.IDENT and self.i + 2 < len(self.toks) and self.toks[self.i + 2].t == TT.LBRACE) or (next_tok is not None and next_tok.t == TT.LBRACE):
                    recs.append(self.parse_rec())
                else:
                    top_stmts.append(('expr', self.parse_expr()))
                    if self.match(TT.SEMI): self.adv()
            elif self.match(TT.TYPE):
                self.skip_type()
            elif self.match(TT.TR):
                sigs.append(self.parse_trait())
            elif self.match(TT.PUB):
                self.adv()
                if self.match(TT.FN):
                    decl = self.parse_fn()
                    decl.public = True
                    if isinstance(decl, MethodDecl):
                        methods.append(decl)
                    else:
                        fs.append(decl)
                elif self.match(TT.REC) or (self.match(TT.IDENT) and self.cur().v in ('rec', 'struct')):
                    decl = self.parse_rec()
                    decl.public = True
                    recs.append(decl)
                elif self.match(TT.IDENT) and self.i + 1 < len(self.toks) and self.toks[self.i + 1].t == TT.LBRACE:
                    # pub Point { ... } sugar
                    decl = self.parse_rec()
                    decl.public = True
                    recs.append(decl)
                elif self.match(TT.FIX):
                    self.adv()
                    name = self.expect(TT.IDENT).v
                    typ = None
                    if self.match(TT.COLON):
                        self.adv()
                        typ = self.parse_type()
                    self.expect(TT.ASSIGN)
                    val = self.parse_expr()
                    fixes.append(FixDecl(name, val, typ, public=True))
                    if self.match(TT.SEMI): self.adv()
                else:
                    raise SyntaxError("expected fn, rec, or fix after pub")
            elif self.match(TT.FN):
                decl = self.parse_fn()
                if isinstance(decl, MethodDecl):
                    methods.append(decl)
                else:
                    fs.append(decl)
            elif self.match(TT.EN):
                enums.append(self.parse_enum())
            elif self.match(TT.FIX):
                self.adv()
                name = self.expect(TT.IDENT).v
                typ = None
                if self.match(TT.COLON):
                    self.adv()
                    typ = self.parse_type()
                self.expect(TT.ASSIGN)
                val = self.parse_expr()
                fixes.append(FixDecl(name, val, typ))
                if self.match(TT.SEMI): self.adv()
            elif self.match(TT.GO):
                if go_body is not None:
                    raise SyntaxError("multiple go entry points")
                go_body = self.parse_go()
            elif self.match(TT.VAL, TT.VAR):
                name, val, typ = self.parse_binding()
                top_stmts.append(('let', name, val, typ))
                if self.match(TT.SEMI): self.adv()
            else:
                # top-level expression (side effects + final value)
                top_stmts.append(('expr', self.parse_expr()))
                if self.match(TT.SEMI): self.adv()
        if any(function.name == 'main' for function in fs):
            raise SyntaxError("fn main is no longer an entry point; use go { ... } or go()")
        toplevel = None
        if go_body is not None:
            if top_stmts:
                raise SyntaxError("top-level statements cannot accompany a go entry point")
            toplevel = go_body
        elif top_stmts:
            raise SyntaxError("program entry point required; use go { ... } or go()")
        return Program(fs, recs, enums, sigs, methods, toplevel, uses, fixes)

    def parse_go(self):
        if self.match(TT.GO):
            self.adv()
        if self.match(TT.LPAREN) and self.toks[self.i + 1].t == TT.RPAREN:
            self.adv()
            self.adv()
            return IntLit(0)
        return self.parse_expr()

    def parse_binding(self):
        self.adv()  # consume val/var
        name = self.expect(TT.IDENT).v
        typ = None
        if self.match(TT.COLON):
            self.adv(); typ = self.parse_type()
        self.expect(TT.ASSIGN)
        val = self.parse_expr()
        return name, val, typ

    def parse_while(self):
        self.expect(TT.WHILE)
        cond = self.parse_expr()
        body = self.parse_block() if self.match(TT.LBRACE) else self.parse_expr()
        return LoopExpr(None, cond, None, body)

    def parse_loop(self):
        self.expect(TT.LP)
        # `lp x: xs { body }`  — for-in over list (BNF: lp IDENT ":" expr block)
        if self.match(TT.IDENT):
            if self.i + 1 < len(self.toks) and self.toks[self.i + 1].t == TT.COLON:
                var = self.adv().v
                self.expect(TT.COLON)
                iterable = self.parse_expr()
                body = self.parse_block() if self.match(TT.LBRACE) else self.parse_expr()
                return ForInExpr(var, iterable, body)

        init = None
        cond = None
        post = None

        if self.match(TT.VAL, TT.VAR):
            name, val, typ = self.parse_binding()
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

        body = self.parse_block() if self.match(TT.LBRACE) else self.parse_expr()
        return LoopExpr(init, cond, post, body)

    def parse_block(self):
        self.expect(TT.LBRACE)
        stmts = []
        while not self.match(TT.RBRACE):
            if self.match(TT.VAL, TT.VAR):
                name, val, typ = self.parse_binding()
                stmts.append(('let', name, val, typ))
            elif self.match(TT.RET):
                stmts.append(('ret', self.parse_ret()))
            else:
                e = self.parse_expr()
                stmts.append(('expr', e))
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
        if self.match(TT.LBRACE):
            save = self.i
            self.adv()
            is_match = False
            if not self.match(TT.RBRACE):
                try:
                    probe_i = self.i
                    self.parse_pattern()
                    if self.match(TT.IF):
                        self.adv()
                        self.parse_expr()
                    if self.match(TT.FATARROW):
                        is_match = True
                    self.i = probe_i
                except Exception:
                    self.i = save + 1
            if is_match:
                arms = []
                while not self.match(TT.RBRACE):
                    pat = self.parse_pattern()
                    guard = None
                    if self.match(TT.IF):
                        self.adv()
                        guard = self.parse_expr()
                    self.expect(TT.FATARROW)
                    value = self.parse_expr()
                    arms.append(MatchArm(pat, guard, value))
                    if self.match(TT.COMMA): self.adv()
                self.expect(TT.RBRACE)
                if self.match(TT.ELSE):
                    self.adv()
                    if self.match(TT.IF):
                        raise SyntaxError("match-style if cannot use 'else if'; use '_ =>' or a final else block")
                    els = self.parse_block() if self.match(TT.LBRACE) else self.parse_expr()
                    arms.append(MatchArm(Wildcard(), None, els))
                return MatchExpr(cond, arms)
            self.i = save
            then = self.parse_block()
        else:
            then = self.parse_expr()
        els = None
        if self.match(TT.ELSE):
            self.adv()
            if self.match(TT.IF):
                els = self.parse_if()
            else:
                els = self.parse_block() if self.match(TT.LBRACE) else self.parse_expr()
        return IfExpr(cond, then, els)

    def parse_match(self):
        self.expect(TT.MATCH)
        subject = self.parse_expr()
        self.expect(TT.LBRACE)
        arms = []
        while not self.match(TT.RBRACE):
            pat = self.parse_pattern()
            guard = None
            if self.match(TT.IF):
                self.adv()
                guard = self.parse_expr()
            self.expect(TT.FATARROW)
            value = self.parse_expr()
            arms.append(MatchArm(pat, guard, value))
            if self.match(TT.COMMA): self.adv()
        self.expect(TT.RBRACE)
        return MatchExpr(subject, arms)

    def parse_pattern(self):
        t = self.cur()
        if self.match(TT.UNDERSCORE):
            self.adv()
            return Wildcard()
        if self.match(TT.INT):
            self.adv()
            return LiteralPattern(IntLit(t.v))
        if self.match(TT.STRING):
            self.adv()
            return LiteralPattern(StrLit(t.v))
        if self.match(TT.TRUE):
            self.adv()
            return LiteralPattern(BoolLit(True))
        if self.match(TT.FALSE):
            self.adv()
            return LiteralPattern(BoolLit(False))
        if self.match(TT.LPAREN):
            self.adv()
            if self.match(TT.RPAREN):
                self.adv()
                return LiteralPattern(IntLit(0))
            first = self.parse_pattern()
            if not self.match(TT.COMMA):
                self.expect(TT.RPAREN)
                return first
            items = [first]
            while self.match(TT.COMMA):
                self.adv()
                if self.match(TT.RPAREN): break
                items.append(self.parse_pattern())
            self.expect(TT.RPAREN)
            return TuplePattern(items)
        if self.match(TT.LBRACK):
            self.adv()
            items = []
            while not self.match(TT.RBRACK):
                items.append(self.parse_pattern())
                if self.match(TT.COMMA): self.adv()
            self.expect(TT.RBRACK)
            return ListPattern(items)
        if self.match(TT.IDENT):
            name = self.adv().v
            if self.match(TT.DOT):
                self.adv()
                variant = self.expect(TT.IDENT).v
                fields = []
                if self.match(TT.LPAREN):
                    self.adv()
                    while not self.match(TT.RPAREN):
                        fields.append(self.parse_pattern())
                        if self.match(TT.COMMA): self.adv()
                    self.expect(TT.RPAREN)
                return EnumVariant(name, variant, fields)
            if self.match(TT.LBRACE):
                return self.parse_record_pattern(name)
            return BindPattern(name)
        raise SyntaxError(f"unexpected pattern token {t.t.name} ('{t.v}') at {t.line}:{t.col}")

    def parse_record_pattern(self, name: str):
        self.expect(TT.LBRACE)
        fields = []
        while not self.match(TT.RBRACE):
            field = self.expect(TT.IDENT).v
            subpat = None
            if self.match(TT.COLON):
                self.adv()
                subpat = self.parse_pattern()
            fields.append((field, subpat))
            if self.match(TT.COMMA): self.adv()
        self.expect(TT.RBRACE)
        return RecordPattern(name, fields)


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

    def parse_primary(self):
        t = self.cur()
        if self.match(TT.INT): self.adv(); return IntLit(t.v)
        if self.match(TT.FLOAT): self.adv(); return FloatLit(float(t.v))
        if self.match(TT.TRUE): self.adv(); return BoolLit(True)
        if self.match(TT.FALSE): self.adv(); return BoolLit(False)
        if self.match(TT.STRING): self.adv(); return StrLit(t.v)
        if self.match(TT.IDENT): self.adv(); return Var(t.v)
        if self.match(TT.RET): return self.parse_ret()
        if self.match(TT.BRK):
            self.adv()
            value = None
            if not self.match(TT.RBRACE, TT.SEMI, TT.EOF, TT.COMMA):
                value = self.parse_expr()
            return JumpExpr('brk', value)
        if self.match(TT.SKIP):
            self.adv()
            return JumpExpr('skip', None)
        if self.match(TT.LPAREN):
            self.adv()
            if self.match(TT.RPAREN):
                self.adv()
                return IntLit(0)
            e = self.parse_expr()
            if self.match(TT.COMMA):
                while self.match(TT.COMMA):
                    self.adv()
                    if self.match(TT.RPAREN): break
                    self.parse_expr()
                self.expect(TT.RPAREN)
                return e
            self.expect(TT.RPAREN)
            return e
        if self.match(TT.LBRACK): return self.parse_list()
        if self.match(TT.PIPE): return self.parse_lambda()
        if self.match(TT.LBRACE): return self.parse_brace()
        if self.match(TT.IF): return self.parse_if()
        if self.match(TT.MATCH): return self.parse_match()
        if self.match(TT.WHILE): return self.parse_while()
        if self.match(TT.LP): return self.parse_loop()
        raise SyntaxError(f"unexpected {t.t.name} ('{t.v}') at {t.line}:{t.col}")

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

    def parse_brace(self):
        """Disambiguate map literal {:}/{k:v} from block { stmts }."""
        save = self.i
        self.expect(TT.LBRACE)
        if self.match(TT.COLON):
            self.adv()
            self.expect(TT.RBRACE)
            return MapLit([])
        if self.match(TT.RBRACE):
            self.adv()
            return IntLit(0)
        if self.match(TT.VAL, TT.VAR, TT.IF, TT.LP, TT.WHILE, TT.RET, TT.BRK, TT.SKIP,
                      TT.MATCH, TT.FN, TT.GO, TT.FIX):
            self.i = save
            return self.parse_block()
        try:
            first = self.parse_expr()
            if self.match(TT.COLON):
                self.adv()
                val = self.parse_expr()
                entries = [(first, val)]
                while self.match(TT.COMMA):
                    self.adv()
                    if self.match(TT.RBRACE):
                        break
                    k = self.parse_expr()
                    self.expect(TT.COLON)
                    v = self.parse_expr()
                    entries.append((k, v))
                self.expect(TT.RBRACE)
                return MapLit(entries)
        except Exception:
            pass
        self.i = save
        return self.parse_block()

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

    def parse_postfix(self):
        e = self.parse_primary()
        while True:
            if self.match(TT.DOT):
                self.adv()
                tok = self.cur()
                if tok.t == TT.IDENT or (isinstance(tok.v, str) and tok.v.isidentifier()):
                    field = self.adv().v
                else:
                    field = self.expect(TT.IDENT).v
                e = Member(e, field)
            elif self.match(TT.LBRACE):
                if isinstance(e, (Var, Member, Index)):
                    if (self.i + 1 < len(self.toks) and self.toks[self.i + 1].t == TT.IDENT
                            and self.i + 2 < len(self.toks) and self.toks[self.i + 2].t == TT.COLON):
                        e = self.parse_record_lit(e)
                    else:
                        break
                else:
                    break
            elif self.match(TT.LPAREN):
                call_tok = self.cur()
                self.adv()
                args = []
                while not self.match(TT.RPAREN):
                    args.append(self.parse_expr())
                    if self.match(TT.COMMA): self.adv()
                self.expect(TT.RPAREN)
                e = Call(e, args, line=call_tok.line, col=call_tok.col)
            elif self.match(TT.LBRACK):
                self.adv()
                parts = [self.parse_expr()]
                while self.match(TT.COMMA):
                    self.adv()
                    parts.append(self.parse_expr())
                self.expect(TT.RBRACK)
                if len(parts) == 1:
                    e = Index(e, parts[0])
                else:
                    e = Index(e, ListLit(parts))
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

    def parse_ternary(self):
        l = self.parse_or()
        if self.match(TT.QUESTION):
            self.adv()
            then = self.parse_expr()
            self.expect(TT.COLON)
            els = self.parse_ternary()
            return TernaryExpr(l, then, els)
        return l

    def parse_assign(self):
        l = self.parse_ternary()
        if self.match(TT.ASSIGN):
            self.adv()
            r = self.parse_assign()
            return Binary('=', l, r)
        if self.match(TT.PLUSEQ, TT.MINUSEQ, TT.STAREQ, TT.SLASHEQ, TT.PERCENTEQ):
            op = self.adv().v
            r = self.parse_assign()
            base_op = op[0]
            return Binary('=', l, Binary(base_op, l, r))
        return l

    def parse_pipe(self):
        l = self.parse_assign()
        while self.match(TT.PIPEGT):
            self.adv()
            r = self.parse_assign()
            if isinstance(r, Call):
                l = Call(r.func, [l] + list(r.args))
            else:
                l = Call(r, [l])
        return l

    def parse_expr(self):
        return self.parse_pipe()

    def skip_use(self):
        self.expect(TT.USE)
        uses = []
        while True:
            segments = [self.expect(TT.IDENT).v]
            separators = []
            while self.match(TT.DOT, TT.SLASH):
                if self.i + 1 < len(self.toks) and self.toks[self.i + 1].t == TT.LBRACE:
                    self.adv()
                    break
                separators.append(self.adv().v)
                segments.append(self.expect(TT.IDENT).v)
            if self.match(TT.LBRACE):
                self.adv()
                while not self.match(TT.RBRACE):
                    sub_segs = [self.expect(TT.IDENT).v]
                    while self.match(TT.DOT):
                        self.adv()
                        sub_segs.append(self.expect(TT.IDENT).v)
                    sub_alias = sub_segs[-1]
                    if self.match(TT.IDENT) and self.cur().v == 'as':
                        self.adv()
                        sub_alias = self.expect(TT.IDENT).v
                    base = segments[0]
                    for sep, seg in zip(separators, segments[1:]):
                        base += sep + seg
                    uses.append(UseDecl(base, sub_alias, sub_segs[-1], False))
                    if self.match(TT.COMMA): self.adv()
                self.expect(TT.RBRACE)
                if self.match(TT.COMMA):
                    self.adv(); continue
                break
            symbol = None
            glob = False
            if (segments[0] != 'std' and len(segments) >= 3
                    and '/' not in separators):
                symbol = segments.pop()
                separators.pop()
                path = '/'.join(segments)
            else:
                path = segments[0]
                for separator, segment in zip(separators, segments[1:]):
                    path += separator + segment
            alias = symbol or path.replace('.', '/').split('/')[-1]
            explicit_alias = False
            if self.match(TT.IDENT) and self.cur().v == 'as':
                self.adv()
                alias = self.expect(TT.IDENT).v
                explicit_alias = True
            if path.startswith('io.') or path in ('io',) or segments[0] == 'io':
                path = 'std.' + path if not path.startswith('std.') else path
            # Dotted paths are packages: use calc.math → lib/calc/math.te, alias math
            # (namespace math.abs). Do not treat 2-segment paths as globs.
            glob = False
            uses.append(UseDecl(path, alias, symbol, glob))
            if self.match(TT.COMMA):
                self.adv(); continue
            break
        if self.match(TT.SEMI): self.adv()
        return uses

    def skip_type(self):
        self.expect(TT.TYPE)
        self.expect(TT.IDENT)
        self.expect(TT.ASSIGN)
        self.parse_type()
        if self.match(TT.SEMI): self.adv()

    def parse_rec(self):
        if self.match(TT.REC):
            self.adv()
            name = self.expect(TT.IDENT).v
        elif self.match(TT.IDENT):
            tok = self.adv()
            if tok.v in ('rec', 'struct'):
                name = self.expect(TT.IDENT).v
            else:
                name = tok.v
        else:
            raise SyntaxError(f"expected record name at {self.cur().line}:{self.cur().col}")
        type_params = []
        if self.match(TT.LBRACK):
            self.adv()
            while not self.match(TT.RBRACK):
                type_params.append(self.expect(TT.IDENT).v)
                if self.match(TT.COMMA):
                    self.adv()
            self.expect(TT.RBRACK)
        self.expect(TT.LBRACE)
        fields = []
        while not self.match(TT.RBRACE):
            field_name = self.expect(TT.IDENT).v
            self.expect(TT.COLON)
            field_type = self.parse_type()
            fields.append((field_name, field_type))
            if self.match(TT.COMMA): self.adv()
        self.expect(TT.RBRACE)
        return RecDecl(name, fields, type_params=type_params)

    def parse_enum(self):
        self.expect(TT.EN)
        name = self.expect(TT.IDENT).v
        type_params = []
        if self.match(TT.LBRACK):
            self.adv()
            while not self.match(TT.RBRACK):
                type_params.append(self.expect(TT.IDENT).v)
                if self.match(TT.COMMA):
                    self.adv()
            self.expect(TT.RBRACK)
        self.expect(TT.LBRACE)
        variants = []
        while not self.match(TT.RBRACE):
            vname = self.expect(TT.IDENT).v
            fields = []
            disc = None
            if self.match(TT.ASSIGN):
                self.adv()
                tok = self.expect(TT.INT)
                disc = int(tok.v)
            elif self.match(TT.LPAREN):
                self.adv()
                while not self.match(TT.RPAREN):
                    fields.append(self.parse_type())
                    if self.match(TT.COMMA): self.adv()
                self.expect(TT.RPAREN)
            variants.append(EnumVariantDecl(vname, fields, value=disc))
            if self.match(TT.COMMA): self.adv()
        self.expect(TT.RBRACE)
        return EnumDecl(name, variants, type_params=type_params)

    def parse_trait(self):
        self.expect(TT.TR)
        name = self.expect(TT.IDENT).v
        type_params = []
        if self.match(TT.LBRACK):
            self.adv()
            while not self.match(TT.RBRACK):
                type_params.append(self.expect(TT.IDENT).v)
                if self.match(TT.COMMA):
                    self.adv()
            self.expect(TT.RBRACK)
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
        return TraitDecl(name, methods, type_params=type_params)

    def parse_method(self, receiver: str, name: str):
        params = self.parse_params()
        ret = None
        if self.match(TT.ARROW):
            self.adv(); ret = self.parse_type()
        if self.match(TT.ASSIGN): self.adv()
        body = self.parse_expr()
        return MethodDecl(receiver, name, params, ret, body)

    def parse_fn(self):
        if self.match(TT.FN):
            self.adv()
        name_tok = self.expect(TT.IDENT)
        name = name_tok.v
        if self.match(TT.DOT):
            self.adv()
            method_name = self.expect(TT.IDENT).v
            return self.parse_method(name, method_name)
        type_params = []
        if self.match(TT.LBRACK):
            self.adv()
            while not self.match(TT.RBRACK):
                type_params.append(self.expect(TT.IDENT).v)
                if self.match(TT.COMMA):
                    self.adv()
            self.expect(TT.RBRACK)
        params = self.parse_params()
        ret = None
        if self.match(TT.ARROW):
            self.adv(); ret = self.parse_type()
        if self.match(TT.ASSIGN): self.adv()
        body = self.parse_expr()
        return FnDecl(name, params, ret, body, type_params=type_params)