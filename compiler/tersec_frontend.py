#!/usr/bin/env python3
"""Terse 0.2 lexer, AST, and parser.

Implements the revised Terse BNF:
- val / var bindings
- go as a normal top-level declaration
- expression-oriented blocks
- records, traits, functions, methods
- tuples, unit, lists, lambdas
- if / match / for / while / lp
- ret / brk / cnt
- |> pipelines
- pub visibility
"""

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Tokens
# ---------------------------------------------------------------------------

class TT(Enum):
    EOF = auto()

    IDENT = auto()
    INT = auto()
    FLOAT = auto()
    STRING = auto()

    # Keywords
    VAL = auto()
    VAR = auto()
    FN = auto()
    GO = auto()
    PUB = auto()
    USE = auto()
    TYPE = auto()
    REC = auto()
    TR = auto()
    IF = auto()
    ELSE = auto()
    MATCH = auto()
    FOR = auto()
    WHILE = auto()
    LP = auto()
    RET = auto()
    BRK = auto()
    CNT = auto()
    TRUE = auto()
    FALSE = auto()
    AS = auto()
    MUT = auto()

    # Punctuation
    LPAREN = auto()
    RPAREN = auto()
    LBRACE = auto()
    RBRACE = auto()
    LBRACK = auto()
    RBRACK = auto()
    COMMA = auto()
    COLON = auto()
    SEMI = auto()
    DOT = auto()
    ARROW = auto()       # ->
    FATARROW = auto()    # =>
    QUESTION = auto()    # ?

    # Operators
    ASSIGN = auto()      # =
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
    PIPE = auto()        # |
    PIPELINE = auto()    # |>


KEYWORDS = {
    "val": TT.VAL,
    "var": TT.VAR,
    "fn": TT.FN,
    "go": TT.GO,
    "pub": TT.PUB,
    "use": TT.USE,
    "type": TT.TYPE,
    "rec": TT.REC,
    "tr": TT.TR,
    "if": TT.IF,
    "else": TT.ELSE,
    "match": TT.MATCH,
    "for": TT.FOR,
    "while": TT.WHILE,
    "lp": TT.LP,
    "ret": TT.RET,
    "brk": TT.BRK,
    "cnt": TT.CNT,
    "true": TT.TRUE,
    "false": TT.FALSE,
    "as": TT.AS,
    "mut": TT.MUT,
}


@dataclass
class Tok:
    t: TT
    v: Any
    line: int
    col: int


class LexError(Exception):
    pass


class Lexer:
    ESCAPES = {
        "n": "\n",
        "t": "\t",
        "r": "\r",
        '"': '"',
        "\\": "\\",
        "0": "\0",
    }

    def __init__(self, src: str):
        self.src = src
        self.i = 0
        self.line = 1
        self.col = 1
        self.toks: list[Tok] = []

    def peek(self, offset: int = 0) -> str:
        j = self.i + offset
        return self.src[j] if j < len(self.src) else ""

    def advance(self) -> str:
        c = self.peek()
        if not c:
            return ""
        self.i += 1
        if c == "\n":
            self.line += 1
            self.col = 1
        else:
            self.col += 1
        return c

    def skip_trivia(self):
        while True:
            c = self.peek()
            if c in " \t\r\n":
                self.advance()
            elif c == "/" and self.peek(1) == "/":
                while self.peek() and self.peek() != "\n":
                    self.advance()
            elif c == "/" and self.peek(1) == "*":
                self.advance()
                self.advance()
                while self.peek() and not (
                    self.peek() == "*" and self.peek(1) == "/"
                ):
                    self.advance()
                if not self.peek():
                    raise LexError(f"unterminated block comment at {self.line}:{self.col}")
                self.advance()
                self.advance()
            else:
                return

    def read_number(self) -> Tok:
        line, col = self.line, self.col
        text = ""

        if self.peek() == "0" and self.peek(1) in "xX":
            self.advance()
            self.advance()
            while self.peek().isalnum():
                text += self.advance()
            if not text:
                raise LexError(f"invalid hex literal at {line}:{col}")
            return Tok(TT.INT, int(text, 16), line, col)

        is_float = False
        while self.peek().isdigit():
            text += self.advance()

        if self.peek() == "." and self.peek(1).isdigit():
            is_float = True
            text += self.advance()
            while self.peek().isdigit():
                text += self.advance()

        if self.peek() in "eE":
            is_float = True
            text += self.advance()
            if self.peek() in "+-":
                text += self.advance()
            if not self.peek().isdigit():
                raise LexError(f"invalid exponent at {line}:{col}")
            while self.peek().isdigit():
                text += self.advance()

        value = float(text) if is_float else int(text)
        return Tok(TT.FLOAT if is_float else TT.INT, value, line, col)

    def read_string(self) -> Tok:
        line, col = self.line, self.col
        self.advance()  # opening quote
        out = ""

        while True:
            c = self.peek()
            if not c or c == "\n":
                raise LexError(f"unterminated string at {line}:{col}")
            if c == '"':
                self.advance()
                return Tok(TT.STRING, out, line, col)
            if c == "\\":
                self.advance()
                esc = self.peek()
                if esc not in self.ESCAPES:
                    raise LexError(f"invalid escape \\{esc} at {self.line}:{self.col}")
                out += self.ESCAPES[esc]
                self.advance()
            else:
                out += self.advance()

    def read_ident(self) -> Tok:
        line, col = self.line, self.col
        text = ""
        while self.peek().isalnum() or self.peek() == "_":
            text += self.advance()
        return Tok(KEYWORDS.get(text, TT.IDENT), text, line, col)

    def tokenize(self) -> list[Tok]:
        while self.i < len(self.src):
            self.skip_trivia()
            if self.i >= len(self.src):
                break

            line, col = self.line, self.col
            c = self.peek()

            if c.isdigit():
                self.toks.append(self.read_number())
                continue

            if c.isalpha() or c == "_":
                self.toks.append(self.read_ident())
                continue

            if c == '"':
                self.toks.append(self.read_string())
                continue

            two = c + self.peek(1)

            simple = {
                "(": TT.LPAREN,
                ")": TT.RPAREN,
                "{": TT.LBRACE,
                "}": TT.RBRACE,
                "[": TT.LBRACK,
                "]": TT.RBRACK,
                ",": TT.COMMA,
                ":": TT.COLON,
                ";": TT.SEMI,
                ".": TT.DOT,
                "?": TT.QUESTION,
                "+": TT.PLUS,
                "-": TT.MINUS,
                "*": TT.STAR,
                "/": TT.SLASH,
                "%": TT.PERCENT,
                "<": TT.LT,
                ">": TT.GT,
                "=": TT.ASSIGN,
                "!": TT.NOT,
                "|": TT.PIPE,
            }

            if two == "->":
                self.advance(); self.advance()
                self.toks.append(Tok(TT.ARROW, "->", line, col))
            elif two == "=>":
                self.advance(); self.advance()
                self.toks.append(Tok(TT.FATARROW, "=>", line, col))
            elif two == "|>":
                self.advance(); self.advance()
                self.toks.append(Tok(TT.PIPELINE, "|>", line, col))
            elif two == "==":
                self.advance(); self.advance()
                self.toks.append(Tok(TT.EQ, "==", line, col))
            elif two == "!=":
                self.advance(); self.advance()
                self.toks.append(Tok(TT.NEQ, "!=", line, col))
            elif two == "<=":
                self.advance(); self.advance()
                self.toks.append(Tok(TT.LE, "<=", line, col))
            elif two == ">=":
                self.advance(); self.advance()
                self.toks.append(Tok(TT.GE, ">=", line, col))
            elif two == "&&":
                self.advance(); self.advance()
                self.toks.append(Tok(TT.AND, "&&", line, col))
            elif two == "||":
                self.advance(); self.advance()
                self.toks.append(Tok(TT.OR, "||", line, col))
            elif c in simple:
                self.advance()
                self.toks.append(Tok(simple[c], c, line, col))
            else:
                raise LexError(f"unexpected character {c!r} at {line}:{col}")

        self.toks.append(Tok(TT.EOF, None, self.line, self.col))
        return self.toks


# ---------------------------------------------------------------------------
# AST
# ---------------------------------------------------------------------------

@dataclass
class TypeNode:
    name: str
    args: list["TypeNode"] = field(default_factory=list)


@dataclass
class Param:
    name: str
    type: Optional[TypeNode] = None
    mutable: bool = False


# Expressions

@dataclass
class Expr:
    pass


@dataclass
class IntLit(Expr):
    value: int


@dataclass
class FloatLit(Expr):
    value: float


@dataclass
class BoolLit(Expr):
    value: bool


@dataclass
class StrLit(Expr):
    value: str


@dataclass
class UnitLit(Expr):
    pass


@dataclass
class Var(Expr):
    name: str


@dataclass
class TupleLit(Expr):
    items: list[Expr]


@dataclass
class ListLit(Expr):
    items: list[Expr]


@dataclass
class RecordLit(Expr):
    name: str
    fields: list[tuple[str, Expr]]


@dataclass
class Unary(Expr):
    op: str
    operand: Expr


@dataclass
class Binary(Expr):
    op: str
    left: Expr
    right: Expr


@dataclass
class Call(Expr):
    func: Expr
    args: list[Expr]


@dataclass
class Index(Expr):
    collection: Expr
    index: Expr


@dataclass
class Member(Expr):
    object: Expr
    field: str


@dataclass
class Propagate(Expr):
    expr: Expr


@dataclass
class Lambda(Expr):
    params: list[Param]
    body: Expr


@dataclass
class Block(Expr):
    stmts: list[Expr]
    value: Optional[Expr] = None


@dataclass
class If(Expr):
    cond: Expr
    then: Expr
    else_: Optional[Expr] = None


@dataclass
class MatchArm:
    pattern: "Pattern"
    guard: Optional[Expr]
    value: Expr


@dataclass
class Match(Expr):
    subject: Expr
    arms: list[MatchArm]


@dataclass
class ForLoop(Expr):
    var: str
    iterable: Expr
    body: Expr


@dataclass
class WhileLoop(Expr):
    cond: Expr
    body: Expr


@dataclass
class CLoop(Expr):
    init: Optional[Expr]
    cond: Optional[Expr]
    post: Optional[Expr]
    body: Expr


@dataclass
class Ret(Expr):
    value: Optional[Expr] = None


@dataclass
class Break(Expr):
    value: Optional[Expr] = None


@dataclass
class Continue(Expr):
    pass


@dataclass
class ValBinding(Expr):
    name: str
    value: Expr
    type: Optional[TypeNode] = None


@dataclass
class VarBinding(Expr):
    name: str
    value: Expr
    type: Optional[TypeNode] = None


@dataclass
class Assign(Expr):
    target: Expr
    value: Expr


# Patterns

@dataclass
class Pattern:
    pass


@dataclass
class WildcardPattern(Pattern):
    pass


@dataclass
class LiteralPattern(Pattern):
    value: Any


@dataclass
class BindPattern(Pattern):
    name: str


@dataclass
class TuplePattern(Pattern):
    items: list[Pattern]


@dataclass
class ListPattern(Pattern):
    items: list[Pattern]


@dataclass
class RecordPattern(Pattern):
    name: str
    fields: list[tuple[str, Optional[Pattern]]]


# Declarations

@dataclass
class Decl:
    pass


@dataclass
class UseItem:
    path: list[str]
    alias: Optional[str] = None


@dataclass
class UseDecl(Decl):
    items: list[UseItem]


@dataclass
class TypeDecl(Decl):
    name: str
    params: list[str]
    value: TypeNode
    public: bool = False


@dataclass
class Field:
    name: str
    type: TypeNode


@dataclass
class RecDecl(Decl):
    name: str
    params: list[str]
    fields: list[Field]
    public: bool = False


@dataclass
class TraitMethod:
    name: str
    params: list[Param]
    ret: Optional[TypeNode] = None


@dataclass
class TraitDecl(Decl):
    name: str
    params: list[str]
    methods: list[TraitMethod]
    public: bool = False


@dataclass
class FnDecl(Decl):
    name: str
    receiver: Optional[str]
    params: list[Param]
    ret: Optional[TypeNode]
    body: Expr
    public: bool = False


@dataclass
class GoDecl(Decl):
    body: Expr


@dataclass
class Program:
    items: list[Decl]


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

class ParseError(Exception):
    pass


class Parser:
    def __init__(self, tokens: list[Tok]):
        self.toks = tokens
        self.i = 0

    def cur(self) -> Tok:
        return self.toks[self.i]

    def advance(self) -> Tok:
        tok = self.cur()
        if tok.t != TT.EOF:
            self.i += 1
        return tok

    def check(self, *types: TT) -> bool:
        return self.cur().t in types

    def accept(self, *types: TT) -> Optional[Tok]:
        if self.check(*types):
            return self.advance()
        return None

    def expect(self, type_: TT, what: str = "") -> Tok:
        if not self.check(type_):
            tok = self.cur()
            expected = type_.name
            raise ParseError(
                f"expected {what or expected}, got {tok.t.name} {tok.v!r} "
                f"at {tok.line}:{tok.col}"
            )
        return self.advance()

    def expect_ident(self, what: str = "identifier") -> str:
        return self.expect(TT.IDENT, what).v

    # ------------------------------------------------------------------
    # Program
    # ------------------------------------------------------------------

    def parse_program(self) -> Program:
        items: list[Decl] = []

        while not self.check(TT.EOF):
            items.append(self.parse_item())

        return Program(items)

    def parse_item(self) -> Decl:
        if self.check(TT.USE):
            return self.parse_use()
        if self.check(TT.TYPE):
            return self.parse_type_decl()
        if self.check(TT.REC):
            return self.parse_rec()
        if self.check(TT.TR):
            return self.parse_trait()
        if self.check(TT.FN):
            return self.parse_fn()
        if self.check(TT.GO):
            return self.parse_go()
        if self.check(TT.PUB):
            return self.parse_pub_item()

        tok = self.cur()
        raise ParseError(
            f"expected top-level declaration, got {tok.t.name} {tok.v!r} "
            f"at {tok.line}:{tok.col}"
        )

    def parse_pub_item(self) -> Decl:
        self.expect(TT.PUB)

        if self.check(TT.TYPE):
            decl = self.parse_type_decl()
        elif self.check(TT.REC):
            decl = self.parse_rec()
        elif self.check(TT.TR):
            decl = self.parse_trait()
        elif self.check(TT.FN):
            decl = self.parse_fn()
        else:
            tok = self.cur()
            raise ParseError(
                f"expected type, rec, tr, or fn after pub at {tok.line}:{tok.col}"
            )

        decl.public = True
        return decl

    # ------------------------------------------------------------------
    # use
    # ------------------------------------------------------------------

    def parse_use(self) -> UseDecl:
        self.expect(TT.USE)
        items = [self.parse_use_item()]

        while self.accept(TT.COMMA):
            items.append(self.parse_use_item())

        self.accept(TT.SEMI)
        return UseDecl(items)

    def parse_use_item(self) -> UseItem:
        path = [self.expect_ident("module path")]

        while self.check(TT.DOT):
            self.advance()
            path.append(self.expect_ident("module path"))

        alias = None
        if self.check(TT.AS):
            self.advance()
            alias = self.expect_ident("alias")

        return UseItem(path, alias)

    # ------------------------------------------------------------------
    # type / rec / tr
    # ------------------------------------------------------------------

    def parse_type_decl(self) -> TypeDecl:
        self.expect(TT.TYPE)
        name = self.expect_ident("type name")
        params = self.parse_type_params() if self.check(TT.LBRACK) else []
        self.expect(TT.ASSIGN)
        value = self.parse_type()
        self.accept(TT.SEMI)
        return TypeDecl(name, params, value)

    def parse_rec(self) -> RecDecl:
        self.expect(TT.REC)
        name = self.expect_ident("record name")
        params = self.parse_type_params() if self.check(TT.LBRACK) else []
        self.expect(TT.LBRACE)

        fields: list[Field] = []
        while not self.check(TT.RBRACE):
            field_name = self.expect_ident("field name")
            self.expect(TT.COLON)
            field_type = self.parse_type()
            fields.append(Field(field_name, field_type))

            if not self.accept(TT.COMMA):
                break

        self.expect(TT.RBRACE)
        return RecDecl(name, params, fields)

    def parse_trait(self) -> TraitDecl:
        self.expect(TT.TR)
        name = self.expect_ident("trait name")
        params = self.parse_type_params() if self.check(TT.LBRACK) else []
        self.expect(TT.LBRACE)

        methods: list[TraitMethod] = []
        while not self.check(TT.RBRACE):
            self.expect(TT.FN)
            method_name = self.expect_ident("method name")
            params = self.parse_params()
            ret = self.parse_return_type()
            methods.append(TraitMethod(method_name, params, ret))
            self.accept(TT.SEMI)

        self.expect(TT.RBRACE)
        return TraitDecl(name, params, methods)

    # ------------------------------------------------------------------
    # fn / go
    # ------------------------------------------------------------------

    def parse_fn(self) -> FnDecl:
        self.expect(TT.FN)
        name = self.expect_ident("function name")

        receiver = None
        if self.check(TT.DOT):
            self.advance()
            receiver = name
            name = self.expect_ident("method name")

        params = self.parse_params()
        ret = self.parse_return_type()
        body = self.parse_fn_body()

        return FnDecl(name, receiver, params, ret, body)

    def parse_go(self) -> GoDecl:
        self.expect(TT.GO)
        return GoDecl(self.parse_fn_body())

    def parse_params(self) -> list[Param]:
        self.expect(TT.LPAREN)
        params: list[Param] = []

        while not self.check(TT.RPAREN):
            mutable = bool(self.accept(TT.MUT))
            name = self.expect_ident("parameter name")
            type_ = self.parse_type() if self.accept(TT.COLON) else None
            params.append(Param(name, type_, mutable))

            if not self.accept(TT.COMMA):
                break

        self.expect(TT.RPAREN)
        return params

    def parse_return_type(self) -> Optional[TypeNode]:
        if not self.check(TT.ARROW):
            return None
        self.advance()
        return self.parse_type()

    def parse_fn_body(self) -> Expr:
        if self.check(TT.ASSIGN):
            self.advance()
            return self.parse_expr()
        return self.parse_block()

    # ------------------------------------------------------------------
    # Types
    # ------------------------------------------------------------------

    def parse_type_params(self) -> list[str]:
        self.expect(TT.LBRACK)
        params = [self.expect_ident("type parameter")]

        while self.accept(TT.COMMA):
            params.append(self.expect_ident("type parameter"))

        self.expect(TT.RBRACK)
        return params

    def parse_type(self) -> TypeNode:
        if self.check(TT.IDENT):
            name = self.advance().v
            args = self.parse_type_args() if self.check(TT.LBRACK) else []
            return TypeNode(name, args)

        if self.check(TT.FN):
            self.advance()
            self.expect(TT.LPAREN)
            args: list[TypeNode] = []

            while not self.check(TT.RPAREN):
                args.append(self.parse_type())
                if not self.accept(TT.COMMA):
                    break

            self.expect(TT.RPAREN)
            ret = self.parse_return_type()
            return TypeNode("fn", ([*args, ret] if ret else args))

        if self.check(TT.LBRACK):
            self.advance()
            inner = self.parse_type()
            self.expect(TT.RBRACK)
            return TypeNode("list", [inner])

        if self.check(TT.REC):
            self.advance()
            self.expect(TT.LBRACE)
            fields: list[TypeNode] = []

            while not self.check(TT.RBRACE):
                field_name = self.expect_ident("field name")
                self.expect(TT.COLON)
                field_type = self.parse_type()
                fields.append(TypeNode(field_name, [field_type]))

                if not self.accept(TT.COMMA):
                    break

            self.expect(TT.RBRACE)
            return TypeNode("rec", fields)

        if self.check(TT.LPAREN):
            self.advance()

            if self.accept(TT.RPAREN):
                return TypeNode("unit")

            first = self.parse_type()

            if not self.check(TT.COMMA):
                self.expect(TT.RPAREN)
                return first

            args = [first]
            while self.accept(TT.COMMA):
                if self.check(TT.RPAREN):
                    break
                args.append(self.parse_type())

            self.expect(TT.RPAREN)
            return TypeNode("tuple", args)

        tok = self.cur()
        raise ParseError(f"expected type at {tok.line}:{tok.col}")

    def parse_type_args(self) -> list[TypeNode]:
        self.expect(TT.LBRACK)
        args = [self.parse_type()]

        while self.accept(TT.COMMA):
            if self.check(TT.RBRACK):
                break
            args.append(self.parse_type())

        self.expect(TT.RBRACK)
        return args

    # ------------------------------------------------------------------
    # Expressions
    # ------------------------------------------------------------------

    def parse_expr(self) -> Expr:
        return self.parse_pipeline()

    def parse_pipeline(self) -> Expr:
        left = self.parse_or()

        while self.check(TT.PIPELINE):
            self.advance()
            right = self.parse_or()
            left = Binary("|>", left, right)

        return left

    def parse_or(self) -> Expr:
        left = self.parse_and()

        while self.check(TT.OR):
            op = self.advance().v
            left = Binary(op, left, self.parse_and())

        return left

    def parse_and(self) -> Expr:
        left = self.parse_cmp()

        while self.check(TT.AND):
            op = self.advance().v
            left = Binary(op, left, self.parse_cmp())

        return left

    def parse_cmp(self) -> Expr:
        left = self.parse_add()

        while self.check(TT.EQ, TT.NEQ, TT.LT, TT.GT, TT.LE, TT.GE):
            op = self.advance().v
            left = Binary(op, left, self.parse_add())

        return left

    def parse_add(self) -> Expr:
        left = self.parse_mul()

        while self.check(TT.PLUS, TT.MINUS):
            op = self.advance().v
            left = Binary(op, left, self.parse_mul())

        return left

    def parse_mul(self) -> Expr:
        left = self.parse_unary()

        while self.check(TT.STAR, TT.SLASH, TT.PERCENT):
            op = self.advance().v
            left = Binary(op, left, self.parse_unary())

        return left

    def parse_unary(self) -> Expr:
        if self.check(TT.NOT, TT.MINUS):
            op = self.advance().v
            return Unary(op, self.parse_unary())
        return self.parse_postfix()

    def parse_postfix(self) -> Expr:
        expr = self.parse_primary()

        while True:
            if self.check(TT.DOT):
                self.advance()
                field = self.expect_ident("field or method name")
                expr = Member(expr, field)

            elif self.check(TT.LPAREN):
                self.advance()
                args: list[Expr] = []

                while not self.check(TT.RPAREN):
                    args.append(self.parse_expr())
                    if not self.accept(TT.COMMA):
                        break

                self.expect(TT.RPAREN)
                expr = Call(expr, args)

            elif self.check(TT.LBRACK):
                self.advance()
                index = self.parse_expr()
                self.expect(TT.RBRACK)
                expr = Index(expr, index)

            elif self.check(TT.QUESTION):
                self.advance()
                expr = Propagate(expr)

            else:
                break

        return expr

    def parse_primary(self) -> Expr:
        tok = self.cur()

        if self.check(TT.INT):
            self.advance()
            return IntLit(tok.v)

        if self.check(TT.FLOAT):
            self.advance()
            return FloatLit(tok.v)

        if self.check(TT.STRING):
            self.advance()
            return StrLit(tok.v)

        if self.check(TT.TRUE):
            self.advance()
            return BoolLit(True)

        if self.check(TT.FALSE):
            self.advance()
            return BoolLit(False)

        if self.check(TT.IDENT):
            self.advance()
            return Var(tok.v)

        if self.check(TT.LPAREN):
            return self.parse_paren_or_tuple()

        if self.check(TT.LBRACK):
            return self.parse_list()

        if self.check(TT.PIPE):
            return self.parse_lambda()

        if self.check(TT.IF):
            return self.parse_if()

        if self.check(TT.MATCH):
            return self.parse_match()

        if self.check(TT.FOR):
            return self.parse_for()

        if self.check(TT.WHILE):
            return self.parse_while()

        if self.check(TT.LP):
            return self.parse_c_loop()

        if self.check(TT.LBRACE):
            return self.parse_block()

        if self.check(TT.RET):
            return self.parse_ret()

        if self.check(TT.BRK):
            return self.parse_break()

        if self.check(TT.CNT):
            self.advance()
            return Continue()

        raise ParseError(
            f"expected expression, got {tok.t.name} {tok.v!r} "
            f"at {tok.line}:{tok.col}"
        )

    def parse_paren_or_tuple(self) -> Expr:
        self.expect(TT.LPAREN)

        if self.accept(TT.RPAREN):
            return UnitLit()

        first = self.parse_expr()

        if not self.check(TT.COMMA):
            self.expect(TT.RPAREN)
            return first

        items = [first]
        while self.accept(TT.COMMA):
            if self.check(TT.RPAREN):
                break
            items.append(self.parse_expr())

        self.expect(TT.RPAREN)
        return TupleLit(items)

    def parse_list(self) -> ListLit:
        self.expect(TT.LBRACK)
        items: list[Expr] = []

        while not self.check(TT.RBRACK):
            items.append(self.parse_expr())
            if not self.accept(TT.COMMA):
                break

        self.expect(TT.RBRACK)
        return ListLit(items)

    def parse_lambda(self) -> Lambda:
        self.expect(TT.PIPE)
        params: list[Param] = []

        while not self.check(TT.PIPE):
            mutable = bool(self.accept(TT.MUT))
            name = self.expect_ident("lambda parameter")
            type_ = self.parse_type() if self.accept(TT.COLON) else None
            params.append(Param(name, type_, mutable))

            if not self.accept(TT.COMMA):
                break

        self.expect(TT.PIPE)

        if self.check(TT.ASSIGN):
            self.advance()
            body = self.parse_expr()
        else:
            body = self.parse_block()

        return Lambda(params, body)

    def parse_if(self) -> If:
        self.expect(TT.IF)
        cond = self.parse_expr()
        then = self.parse_block()

        else_ = None
        if self.accept(TT.ELSE):
            if self.check(TT.IF):
                else_ = self.parse_if()
            else:
                else_ = self.parse_block()

        return If(cond, then, else_)

    def parse_match(self) -> Match:
        self.expect(TT.MATCH)
        subject = self.parse_expr()
        self.expect(TT.LBRACE)

        arms: list[MatchArm] = []
        while not self.check(TT.RBRACE):
            pattern = self.parse_pattern()

            guard = None
            if self.check(TT.IF):
                self.advance()
                guard = self.parse_expr()

            self.expect(TT.FATARROW)
            value = self.parse_expr()
            arms.append(MatchArm(pattern, guard, value))

        self.expect(TT.RBRACE)
        return Match(subject, arms)

    def parse_pattern(self) -> Pattern:
        tok = self.cur()

        if self.check(TT.UNDERSCORE) if hasattr(TT, "UNDERSCORE") else False:
            self.advance()
            return WildcardPattern()

        if self.check(TT.IDENT):
            self.advance()

            if self.check(TT.LBRACE):
                return self.parse_record_pattern(tok.v)

            return BindPattern(tok.v)

        if self.check(TT.INT, TT.FLOAT, TT.STRING, TT.TRUE, TT.FALSE):
            self.advance()
            return LiteralPattern(tok.v)

        if self.check(TT.LPAREN):
            self.advance()

            if self.accept(TT.RPAREN):
                return LiteralPattern(())

            first = self.parse_pattern()

            if not self.check(TT.COMMA):
                self.expect(TT.RPAREN)
                return first

            items = [first]
            while self.accept(TT.COMMA):
                if self.check(TT.RPAREN):
                    break
                items.append(self.parse_pattern())

            self.expect(TT.RPAREN)
            return TuplePattern(items)

        if self.check(TT.LBRACK):
            self.advance()
            items: list[Pattern] = []

            while not self.check(TT.RBRACK):
                items.append(self.parse_pattern())
                if not self.accept(TT.COMMA):
                    break

            self.expect(TT.RBRACK)
            return ListPattern(items)

        raise ParseError(
            f"expected pattern, got {tok.t.name} {tok.v!r} "
            f"at {tok.line}:{tok.col}"
        )

    def parse_record_pattern(self, name: str) -> RecordPattern:
        self.expect(TT.LBRACE)
        fields: list[tuple[str, Optional[Pattern]]] = []

        while not self.check(TT.RBRACE):
            field = self.expect_ident("field pattern")

            subpattern = None
            if self.accept(TT.COLON):
                subpattern = self.parse_pattern()

            fields.append((field, subpattern))

            if not self.accept(TT.COMMA):
                break

        self.expect(TT.RBRACE)
        return RecordPattern(name, fields)

    def parse_for(self) -> ForLoop:
        self.expect(TT.FOR)
        var = self.expect_ident("loop variable")
        self.expect(TT.IDENT, "'in'") if False else None

        # `in` is intentionally contextual, not a reserved keyword.
        if self.cur().t != TT.IDENT or self.cur().v != "in":
            tok = self.cur()
            raise ParseError(f"expected 'in' at {tok.line}:{tok.col}")
        self.advance()

        iterable = self.parse_expr()
        body = self.parse_block()
        return ForLoop(var, iterable, body)

    def parse_while(self) -> WhileLoop:
        self.expect(TT.WHILE)
        cond = self.parse_expr()
        body = self.parse_block()
        return WhileLoop(cond, body)

    def parse_c_loop(self) -> CLoop:
        self.expect(TT.LP)
        init = self.parse_stmt(stop_before_condition=True)

        self.expect(TT.SEMI)

        cond = None
        if not self.check(TT.SEMI):
            cond = self.parse_expr()

        self.expect(TT.SEMI)

        post = None
        if not self.check(TT.LBRACE):
            post = self.parse_expr()

        body = self.parse_block()
        return CLoop(init, cond, post, body)

    def parse_ret(self) -> Ret:
        self.expect(TT.RET)

        value = None
        if not self.check(
            TT.RBRACE, TT.SEMI, TT.EOF, TT.RPAREN, TT.RBRACK, TT.COMMA
        ):
            value = self.parse_expr()

        return Ret(value)

    def parse_break(self) -> Break:
        self.expect(TT.BRK)

        value = None
        if not self.check(
            TT.RBRACE, TT.SEMI, TT.EOF, TT.RPAREN, TT.RBRACK, TT.COMMA
        ):
            value = self.parse_expr()

        return Break(value)

    def parse_block(self) -> Block:
        self.expect(TT.LBRACE)
        stmts: list[Expr] = []

        while not self.check(TT.RBRACE) and not self.check(TT.EOF):
            stmts.append(self.parse_stmt())

            if not self.accept(TT.SEMI):
                break

        self.expect(TT.RBRACE)

        value = None
        if stmts and isinstance(stmts[-1], Expr) and not isinstance(
            stmts[-1],
            (ValBinding, VarBinding, Assign, Ret, Break, Continue),
        ):
            value = stmts.pop()

        return Block(stmts, value)

    def parse_stmt(self, stop_before_condition: bool = False) -> Expr:
        if self.check(TT.VAL):
            self.advance()
            name = self.expect_ident("binding name")
            type_ = self.parse_type() if self.accept(TT.COLON) else None
            self.expect(TT.ASSIGN)
            value = self.parse_expr()
            return ValBinding(name, value, type_)

        if self.check(TT.VAR):
            self.advance()
            name = self.expect_ident("binding name")
            type_ = self.parse_type() if self.accept(TT.COLON) else None
            self.expect(TT.ASSIGN)
            value = self.parse_expr()
            return VarBinding(name, value, type_)

        start = self.i
        expr = self.parse_expr()

        if self.check(TT.ASSIGN):
            self.advance()
            value = self.parse_expr()
            return Assign(expr, value)

        if stop_before_condition:
            self.i = start
            return self.parse_expr()

        return expr


def parse(source: str) -> Program:
    return Parser(Lexer(source).tokenize()).parse_program()