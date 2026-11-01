#!/usr/bin/env python3
"""Shared type helpers for the Terse compiler."""
from typing import List, Any, Tuple

# Canonical surface primitives only — no aliases.
_PRIMITIVES = frozenset({
    'bool', 'str',
    'chr', 'byte', 'int', 'long',
    'flt', 'dbl',
})

# Surface name → C type
_C_TYPES = {
    'bool': 'bool',
    'str': 'const char*',
    'chr': 'int8_t',
    'byte': 'uint8_t',
    'int': 'int32_t',
    'long': 'int64_t',
    'flt': 'float',
    'dbl': 'double',
}

# Surface numeric → runtime list/map suffix still used in runtime.c
# (runtime keeps list_new_i64 etc.; codegen maps long → i64 helpers)
_RUNTIME_SUFFIX = {
    'long': 'i64',
    'int': 'i32',
    'chr': 'i8',
    'byte': 'i8',   # list storage as i8; byte is unsigned in scalars only
    'flt': 'f32',
    'dbl': 'f64',
}

# No aliases — empty. Kept as dict so call sites using .get still work.
_TYPE_ALIASES = {}


def _c_type_name(t: str) -> str:
    """C type for a surface type name (primitives only)."""
    return _C_TYPES.get(t, t)


def _runtime_suffix(t: str) -> str:
    """Suffix for list_new_* / list_len_* in runtime.c."""
    return _RUNTIME_SUFFIX.get(t, t)


def _fn_type_tag(t) -> str:
    """Encode TypeNode fn(A,B)->R as fn:A,B>R for env / codegen."""
    if t is None:
        return 'long'
    if isinstance(t, str):
        return t
    if getattr(t, 'name', None) == 'fn':
        args = list(t.args or [])
        if not args:
            return 'fn:>long'
        if len(args) == 1:
            params, ret = [], args[0]
        else:
            params, ret = args[:-1], args[-1]

        def _nm(x):
            if isinstance(x, str):
                return x
            return x.name if hasattr(x, 'name') else 'long'

        ps = ",".join(_nm(p) for p in params)
        return f"fn:{ps}>{_nm(ret)}"
    if hasattr(t, 'name'):
        return t.name
    return 'long'


def _norm_type_name(t) -> str:
    """Normalize a TypeNode or type name string for overload matching."""
    if t is None:
        return 'long'
    if isinstance(t, str):
        name = t
    else:
        name = getattr(t, 'name', None) or 'long'
        args = getattr(t, 'args', None) or []
        if name in ('list', 'List') and args:
            inner = _norm_type_name(args[0])
            return 'list_str' if inner == 'str' else f'list_{inner}'
        if name == 'map' and len(args) >= 2:
            return f"map_{_norm_type_name(args[0])}_{_norm_type_name(args[1])}"
    return name


def _mangle_overload(name: str, param_types) -> str:
    """C symbol for an overloaded function: terse_eq__long_long."""
    if not param_types:
        return f"terse_{name}__"
    parts = [str(t).replace(' ', '_') for t in param_types]
    return f"terse_{name}__" + "_".join(parts)


def _resolve_overload(overloads, arg_types):
    """Pick (param_types, cname, ret) matching arg_types.
    Prefer exact match; then soft numeric width match.
    """
    if not overloads:
        return None
    args = [_norm_type_name(a) for a in arg_types]
    # exact
    for pts, cname, ret in overloads:
        if len(pts) != len(args):
            continue
        if all(_norm_type_name(p) == a for p, a in zip(pts, args)):
            return (pts, cname, ret)
    # soft numeric
    _intish = {'chr', 'byte', 'int', 'long'}
    _floatish = {'flt', 'dbl'}
    for pts, cname, ret in overloads:
        if len(pts) != len(args):
            continue
        ok = True
        for p, a in zip(pts, args):
            pn, an = _norm_type_name(p), a
            if pn == an:
                continue
            if pn in _intish and an in _intish:
                continue
            if pn in _floatish and an in (_floatish | _intish):
                continue
            ok = False
            break
        if ok:
            return (pts, cname, ret)
    return None


def _types_compatible(expected, got, strict_list=False) -> bool:
    e = _norm_type_name(expected)
    g = _norm_type_name(got)
    if e == g:
        return True
    _intish = {'chr', 'byte', 'int', 'long'}
    if e in _intish and g in _intish:
        return not strict_list
    if e in ('flt', 'dbl') and g in ('flt', 'dbl', 'long', 'int'):
        return True
    if e in ('list', 'List') and (g in ('list', 'List') or (isinstance(g, str) and g.startswith('list_'))):
        return True
    if g in ('list', 'List') and (e in ('list', 'List') or (isinstance(e, str) and e.startswith('list_'))):
        return True
    if isinstance(e, str) and isinstance(g, str) and e.startswith('list_') and g.startswith('list_'):
        if e == g:
            return True
        return _types_compatible(e[5:], g[5:], strict_list=False)
    if e in ('list', 'List') and isinstance(g, str) and g.startswith('list_'):
        return True
    if g in ('list', 'List') and isinstance(e, str) and e.startswith('list_'):
        return True
    return False


def _type_node_name(t) -> str:
    if t is None:
        return 'long'
    if isinstance(t, str):
        return t
    if hasattr(t, 'name'):
        n = t.name
        if n == 'list' and getattr(t, 'args', None):
            inner = _type_node_name(t.args[0]) if t.args else 'long'
            return 'list_long' if inner == 'long' else f'list_{inner}'
        if n == 'map' and getattr(t, 'args', None) and len(t.args) >= 2:
            return f"map_{_type_node_name(t.args[0])}_{_type_node_name(t.args[1])}"
        return n
    return 'long'


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


try:
    from .ast import TypeNode  # noqa: F401
except ImportError:
    pass
