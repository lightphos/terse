"""Terse compiler package — split from tersec.py into maintainable modules."""
from .lexer import TT, Tok, Lexer
from .parser import Parser
from .typecheck import TypeChecker
from .codegen import CodeGen, get_runtime
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
    'TT', 'Tok', 'Lexer',
    'Parser', 'TypeChecker', 'CodeGen', 'get_runtime',
    '_TYPE_ALIASES', '_fn_type_tag', '_norm_type_name',
    '_mangle_overload', '_resolve_overload', '_types_compatible',
    '_type_node_name', '_subst_type_name', '_subst_type_node',
    '_mangle_generic',
]
