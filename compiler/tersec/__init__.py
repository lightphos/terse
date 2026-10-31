"""Terse compiler package — split from tersec.py into maintainable modules.

The package provides:
- lexer: Tokenizer for Terse language
- ast: Abstract syntax tree dataclasses
- parser: Recursive-descent parser (from tokens to AST)
- typecheck: Type checking and generic specialization
- utils: Shared type helper functions

Usage:
    from compiler.tersec import Parser, TypeChecker, Lexer
    prog = Parser(tokens).parse_program()
    checked = TypeChecker().check(prog)
"""

from .lexer import (
    TT, Tok, Lexer
)

from .ast import (
    Program, FnDecl, RecDecl, EnumDecl, TraitDecl, MethodDecl, UseDecl, FixDecl,
    TypeNode, Param, Expr, IntLit, FloatLit, BoolLit, StrLit, Var,
    Binary, Unary, Call, Member, IfExpr, TernaryExpr, LetExpr,
    RetExpr, JumpExpr, Lambda, LoopExpr, ForInExpr, AssignExpr,
    Block, ListLit, MapLit, Index, Route, HttpServe, RecordLit,
    EnumVariantDecl, Wildcard, LiteralPattern, BindPattern,
    EnumVariant, RecordPattern, TuplePattern, ListPattern, MatchArm, MatchExpr,
)

from .parser import Parser
from .typecheck import TypeChecker

from .utils import (
    _TYPE_ALIASES,
    _fn_type_tag,
    _norm_type_name,
    _mangle_overload,
    _resolve_overload,
    _types_compatible,
    _type_node_name,
    _subst_type_name,
    _subst_type_node,
    _mangle_generic,
)

__all__ = [
    # Core compiler components
    'TT', 'Tok', 'Lexer',
    'Parser', 'TypeChecker',

    # AST nodes (most frequently used)
    'Program', 'FnDecl', 'RecDecl', 'EnumDecl', 'TraitDecl', 'MethodDecl', 'UseDecl', 'FixDecl',
    'TypeNode', 'Param', 'Expr',
    'IntLit', 'FloatLit', 'BoolLit', 'StrLit', 'Var',
    'Binary', 'Unary', 'Call', 'Member', 'IfExpr', 'TernaryExpr', 'LetExpr',
    'RetExpr', 'JumpExpr', 'Lambda', 'LoopExpr', 'ForInExpr', 'AssignExpr',
    'Block', 'ListLit', 'MapLit', 'Index', 'Route', 'HttpServe', 'RecordLit',
    'EnumVariantDecl', 'Wildcard', 'LiteralPattern', 'BindPattern',
    'EnumVariant', 'RecordPattern', 'TuplePattern', 'ListPattern', 'MatchArm', 'MatchExpr',

    # Internal utilities
    '_TYPE_ALIASES', '_fn_type_tag', '_norm_type_name',
    '_mangle_overload', '_resolve_overload', '_types_compatible',
    '_type_node_name', '_subst_type_name', '_subst_type_node',
    '_mangle_generic',
]