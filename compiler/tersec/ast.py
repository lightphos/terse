#!/usr/bin/env python3
"""Terse AST — pure dataclass nodes for the parser output."""
from dataclasses import dataclass, field
from typing import List, Optional, Any, Tuple


@dataclass
class TypeNode:
    name: str
    args: List['TypeNode'] = field(default_factory=list)


@dataclass
class Param:
    name: str
    typ: Optional[TypeNode] = None
    default: Optional['Expr'] = None


class Expr:
    """Base class for all expression nodes."""


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
class Var(Expr):
    name: str


@dataclass
class Binary(Expr):
    op: str
    left: Expr
    right: Expr


@dataclass
class AwaitExpr(Expr):
    value: Expr
    loop: bool = False  # True => ~> event-loop await; False => ~ thread join


@dataclass
class Unary(Expr):
    op: str
    expr: Expr


@dataclass
class Call(Expr):
    func: Expr
    args: List[Expr]
    line: int = 0
    col: int = 0
    resolved_params: Optional[List[Param]] = None


@dataclass
class TrapExpr(Expr):
    expr: Expr
    name: str
    handler: Expr


@dataclass
class TupleLit(Expr):
    items: List[Expr]


@dataclass
class TupleLetExpr(Expr):
    names: List[str]
    value: Expr
    body: Expr


@dataclass
class Member(Expr):
    obj: Expr
    field: str


@dataclass
class IfExpr(Expr):
    cond: Expr
    then: Expr
    els: Optional[Expr]


@dataclass
class TernaryExpr(Expr):
    cond: Expr
    then: Expr
    els: Expr


@dataclass
class LetExpr(Expr):
    name: str
    value: Expr
    body: Expr
    typ: Optional[TypeNode] = None


@dataclass
class RetExpr(Expr):
    value: Optional[Expr] = None


@dataclass
class JumpExpr(Expr):
    """brk / skip — loop break and continue."""
    kind: str  # 'brk' | 'skip'
    value: Optional[Expr] = None


@dataclass
class Lambda(Expr):
    params: List[Param]
    body: Expr


@dataclass
class LoopExpr(Expr):
    init: Optional[Expr]
    cond: Expr
    post: Optional[Expr]
    body: Expr


@dataclass
class ForInExpr(Expr):
    var: str
    iterable: Expr
    body: Expr


@dataclass
class AssignExpr(Expr):
    target: Expr
    value: Expr


@dataclass
class Block(Expr):
    stmts: List[Expr]


@dataclass
class ListLit(Expr):
    items: List[Expr]


@dataclass
class MapLit(Expr):
    """Map literal entries as (key_expr, value_expr) pairs. Empty => {:}."""
    entries: List[Tuple[Expr, Expr]]


@dataclass
class Index(Expr):
    coll: Expr
    idx: Expr


@dataclass
class SliceExpr(Expr):
    value: Expr
    start: Expr
    end: Expr


@dataclass
class FnDecl:
    name: str
    params: List[Param]
    ret: Optional[TypeNode]
    body: Expr
    public: bool = False
    external_lib: bool = False
    type_params: List[str] = field(default_factory=list)
    type_param_bounds: dict = field(default_factory=dict)
    is_async: bool = False
    is_async_loop: bool = False  # ~~> event-loop task


@dataclass
class RecDecl:
    name: str
    fields: List[Tuple[str, TypeNode]]
    public: bool = False
    type_params: List[str] = field(default_factory=list)
    type_param_bounds: dict = field(default_factory=dict)


@dataclass
class TraitDecl:
    name: str
    methods: List[Tuple[str, List[Param], Optional[TypeNode]]]
    type_params: List[str] = field(default_factory=list)
    type_param_bounds: dict = field(default_factory=dict)

@dataclass
class MethodDecl:
    receiver: str
    name: str
    params: List[Param]
    ret: Optional[TypeNode]
    body: Expr
    public: bool = False


@dataclass
class UseDecl:
    path: str
    alias: str
    symbol: Optional[str] = None
    glob: bool = False


@dataclass
class RecordLit(Expr):
    ctor: Expr
    fields: List[Tuple[str, Expr]]


@dataclass
class EnumVariantDecl:
    name: str
    fields: List[TypeNode] = field(default_factory=list)  # empty = tag-only
    value: Optional[int] = None  # explicit discriminant, e.g. ok = 200


@dataclass
class EnumDecl:
    name: str
    variants: List[EnumVariantDecl]
    public: bool = True
    type_params: List[str] = field(default_factory=list)
    type_param_bounds: dict = field(default_factory=dict)


@dataclass
class FixDecl:
    name: str
    value: Expr
    typ: Optional[TypeNode] = None
    public: bool = False


# Pattern nodes for pattern-based if arms
@dataclass
class Wildcard:
    pass


@dataclass
class LiteralPattern:
    value: Expr


@dataclass
class BindPattern:
    name: str


@dataclass
class EnumVariant:
    ctor: str
    variant: str
    fields: List[object] = field(default_factory=list)


@dataclass
class RecordPattern:
    name: str
    fields: List[Tuple[str, Optional[object]]]


@dataclass
class TuplePattern:
    items: List[object]


@dataclass
class ListPattern:
    items: List[object]


@dataclass
class MatchArm:
    pattern: object
    guard: Optional[Expr]
    value: Expr


@dataclass
class MatchExpr(Expr):
    subject: Expr
    arms: List[MatchArm]


@dataclass
class Program:
    funcs: List[FnDecl]
    recs: List[RecDecl]
    enums: List[EnumDecl] = field(default_factory=list)
    sigs: List[TraitDecl] = field(default_factory=list)
    methods: List[MethodDecl] = field(default_factory=list)
    toplevel: Optional[Expr] = None
    uses: List[UseDecl] = field(default_factory=list)
    fixes: List[FixDecl] = field(default_factory=list)