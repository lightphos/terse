#!/usr/bin/env python3
"""Shared type helpers for the Terse compiler."""
from typing import List, Any, Tuple


_TYPE_ALIASES = {
    'long': 'i64', 'int': 'i32', 'short': 'i16', 'char': 'i8',
    'float': 'f32', 'double': 'f64',
    'List': 'list', 'String': 'str',
}


def _fn_type_tag(t) -> str:
    """Encode TypeNode fn(A,B)->R as fn:A,B>R for env / codegen."""
    if t is None:
        return 'i64'
    if isinstance(t, str):
        return t
    if getattr(t, 'name', None) == 'fn':
        args = list(t.args or [])
        if not args:
            return 'fn:>i64'
        if len(args) == 1:
            params, ret = [], args[0]
        else:
            params, ret = args[:-1], args[-1]

        def _nm(x):
            if isinstance(x, str):
                return x
            return x.name if hasattr(x, 'name') else 'i64'

        ps = ",".join(_nm(p) for p in params)
        return f"fn:{ps}>{_nm(ret)}"
    if hasattr(t, 'name'):
        return t.name
    return 'i64'


def _norm_type_name(t) -> str:
    """Normalize a TypeNode or type name string for overload matching."""
    if t is None:
        return 'i64'
    if isinstance(t, str):
        name = t
    else:
        # TypeNode
        name = getattr(t, 'name', None) or 'i64'
        args = getattr(t, 'args', None) or []
        if name in ('list', 'List') and args:
            inner = _norm_type_name(args[0])
            return 'list_str' if inner == 'str' else f'list_{inner}'
        if name == 'map' and len(args) >= 2:
            return f"map_{_norm_type_name(args[0])}_{_norm_type_name(args[1])}"
    return _TYPE_ALIASES.get(name, name)


def _mangle_overload(name: str, param_types) -> str:
    """C symbol for an overloaded function: terse_eq__i64_i64."""
    if not param_types:
        return f"terse_{name}__"
    parts = [str(t).replace(' ', '_') for t in param_types]
    return f"terse_{name}__" + "_".join(parts)


def _resolve_overload(overloads, arg_types):
    """Pick (param_types, cname, ret) matching arg_types.
    overloads: list of (param_types, cname, ret)
    Prefer exact match; then soft numeric width match (i32↔i64 etc.).
    """
    if not overloads:
        return None
    args = [_norm_type_name(a) if not isinstance(a, str) else _TYPE_ALIASES.get(a, a) for a in arg_types]
    # exact
    for pts, cname, ret in overloads:
        if len(pts) != len(args):
            continue
        if all(_norm_type_name(p) == a for p, a in zip(pts, args)):
            return (pts, cname, ret)
    # soft: all integer-ish widths interchangeable for resolution
    _intish = {'i8','i16','i32','i64','u8','u16','u32','u64','int','long','short','char'}

    def soft_ok(p, a):
        p, a = _norm_type_name(p), _norm_type_name(a)
        if p == a:
            return True
        if p in _intish and a in _intish:
            return True
        if p in ('f32','f64','float','double') and a in ('f32','f64','float','double','i64','i32'):
            return True
        return False

    soft = []
    for pts, cname, ret in overloads:
        if len(pts) != len(args):
            continue
        if all(soft_ok(p, a) for p, a in zip(pts, args)):
            soft.append((pts, cname, ret))
    if len(soft) == 1:
        return soft[0]
    if len(soft) > 1:
        # prefer exact width when possible; else first soft
        for pts, cname, ret in soft:
            if all(_norm_type_name(p) == a for p, a in zip(pts, args)):
                return (pts, cname, ret)
        return soft[0]
    return None


def _types_compatible(expected, got, strict_list=False):
    """True if got may be used where expected is required.

    Empty lists are typed as 'list' (polymorphic) and inhabit any list_*.
    Integer list literals default to list_i64 but may assign to list_i32/etc.
    """
    e = _norm_type_name(expected)
    g = _norm_type_name(got)
    if e == g:
        return True
    _intish = {'i8','i16','i32','i64','u8','u16','u32','u64','char'}
    if e in _intish and g in _intish:
        return not strict_list
    if e in ('f32','f64') and g in ('f32','f64','i64','i32'):
        return True
    # Polymorphic empty list
    if e in ('list', 'List') and (g in ('list', 'List') or (isinstance(g, str) and g.startswith('list_'))):
        return True
    if g in ('list', 'List') and (e in ('list', 'List') or (isinstance(e, str) and e.startswith('list_'))):
        return True
    if isinstance(e, str) and isinstance(g, str) and e.startswith('list_') and g.startswith('list_'):
        if e == g:
            return True
        if strict_list:
            # Still allow int-width lists to interconvert (literals are i64)
            return _types_compatible(e[5:], g[5:], strict_list=False)
        return _types_compatible(e[5:], g[5:], strict_list=False)
    if e in ('list', 'List') and isinstance(g, str) and g.startswith('list_'):
        return True
    if g in ('list', 'List') and isinstance(e, str) and e.startswith('list_'):
        return True
    return False


def _type_node_name(t) -> str:
    if t is None:
        return 'i64'
    if isinstance(t, str):
        return t
    if hasattr(t, 'name'):
        n = t.name
        if n == 'list' and getattr(t, 'args', None):
            inner = _type_node_name(t.args[0]) if t.args else 'i64'
            return 'list_i64' if inner == 'i64' else f'list_{inner}'
        if n == 'map' and getattr(t, 'args', None) and len(t.args) >= 2:
            return f"map_{_type_node_name(t.args[0])}_{_type_node_name(t.args[1])}"
        return n
    return 'i64'


def _subst_type_name(name: str, mapping: dict) -> str:
    return mapping.get(name, name)


def _subst_type_node(t, mapping: dict):
    if t is None:
        return None
    if isinstance(t, str):
        return mapping.get(t, t)
    name = mapping.get(t.name, t.name)
    args = [_subst_type_node(a, mapping) for a in (t.args or [])]
    return TypeNode(name, args)


def _mangle_generic(name: str, type_args: list) -> str:
    parts = [_type_node_name(a) if not isinstance(a, str) else a for a in type_args]
    safe = [p.replace('[', '').replace(']', '').replace(',', '_') for p in parts]
    return name + '__' + '_'.join(safe) if safe else name


# Import lazily to avoid circular dependency — needed by _subst_type_node
try:
    from .ast import TypeNode  # noqa: F401
except ImportError:
    pass