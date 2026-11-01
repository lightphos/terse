#!/usr/bin/env python3
"""Terse Type Checker — type checks AST programs."""
from __future__ import annotations

import copy

from .ast import (
    TypeNode, Param, Expr, IntLit, FloatLit, BoolLit, StrLit, Var,
    Binary, Unary, Call, Member, IfExpr, TernaryExpr, LetExpr,
    RetExpr, JumpExpr, Lambda, LoopExpr, ForInExpr, AssignExpr,
    Block, ListLit, MapLit, Index, FnDecl, TrapExpr, TupleLit, TupleLetExpr,
    RecDecl, TraitDecl, MethodDecl, UseDecl, RecordLit, EnumVariantDecl,
    EnumDecl, FixDecl, Wildcard, LiteralPattern, BindPattern,
    EnumVariant, RecordPattern, TuplePattern, ListPattern, MatchArm, MatchExpr,
    Program,
)
from .utils import (
    _TYPE_ALIASES, _fn_type_tag, _norm_type_name, _mangle_overload,
    _resolve_overload, _types_compatible, _type_node_name,
    _subst_type_name, _subst_type_node, _mangle_generic,
)


class TypeChecker:
    def __init__(self):
        self.funcs = {}
        self.env = {}
        self.errors = []
        self.current_fn = None
        self.current_ret = None
        self.recs = {}
        self.enums = {}
        self.sigs = {}     # trait name -> list of (method_name, [param_type_names], ret_type_name)
        self.methods = {}  # (receiver, method_name) -> ([param_type_names], ret_type_name)
        self.satisfied = set()  # set of (trait_name, struct_name) pairs
        self.generic_traits = {}
        self.generic_recs = {}
        self.generic_enums = {}
        self.generic_fns = {}  # name -> FnDecl with type_params
        self.overloads = {}  # name -> [(param_types, cname, ret)]
        self.function_decls = {}  # name -> concrete FnDecl overloads
        self.specialized = {}  # mangled -> FnDecl / rec / en
        self.prog = None

    def _type_name(self, t):
        if t is None:
            return 'long'
        if t.name == 'list' and t.args:
            return f"list_{self._type_name(t.args[0])}"
        return t.name

    def compute_satisfaction(self, prog):
        """Structural trait satisfaction."""
        self.prog = prog
        self.generic_traits = {sig.name: sig for sig in prog.sigs if getattr(sig, 'type_params', None)}
        self.sigs = {}
        for sig in prog.sigs:
            if getattr(sig, 'type_params', None):
                continue  # specialized views filled below
            self.sigs[sig.name] = [
                (m[0], [self._type_name(p.typ) for p in m[1]], self._type_name(m[2]))
                for m in sig.methods
            ]
        self.methods = {
            (m.receiver, m.name): (
                [self._type_name(p.typ) for p in m.params],
                self._type_name(m.ret),
            )
            for m in prog.methods
        }
        self.satisfied = set()  # (trait_name, struct) or (trait_name, (args...), struct)

        concrete_recs = [r for r in prog.recs if not getattr(r, 'type_params', None)]
        # Non-generic traits
        for sig_name, sig_methods in self.sigs.items():
            for rec in concrete_recs:
                if self._matches(rec.name, sig_methods):
                    self.satisfied.add((sig_name, rec.name))

        # Generic traits: for each concrete type C, try Eq[C] etc.
        for sig in prog.sigs:
            tps = getattr(sig, 'type_params', None) or []
            if not tps:
                continue
            for rec in concrete_recs:
                if len(tps) == 1:
                    mapping = {tps[0]: rec.name}
                else:
                    mapping = {tp: rec.name for tp in tps}
                sig_methods = []
                for mname, params, ret in sig.methods:
                    ps = []
                    for p in params:
                        if p.typ is not None:
                            ps.append(self._type_name(_subst_type_node(p.typ, mapping)))
                        else:
                            ps.append('long')
                    rt = self._type_name(_subst_type_node(ret, mapping)) if ret else 'long'
                    sig_methods.append((mname, ps, rt))
                if self._matches(rec.name, sig_methods):
                    args = tuple(mapping[tp] for tp in tps)
                    mangled = _mangle_generic(sig.name, list(args))
                    self.sigs[mangled] = sig_methods
                    self.satisfied.add((sig.name, args, rec.name))
                    self.satisfied.add((mangled, rec.name))  # also as specialized name

    def _matches(self, struct_name, sig_methods):
        for mname, mparams, mret in sig_methods:
            key = (struct_name, mname)
            if key not in self.methods:
                return False
            mp, mr = self.methods[key]
            if mp != mparams or mr != mret:
                return False
        return True

    def check_program(self, prog):
        self.prog = prog
        self.compute_satisfaction(prog)
        self.recs = {}
        self.generic_recs = {}
        for r in prog.recs:
            if getattr(r, 'type_params', None):
                self.generic_recs[r.name] = r
            else:
                self.recs[r.name] = {n: (self._type_name(t) if t else 'long') for n, t in r.fields}
        self.enums = {}
        self.generic_enums = {}
        for e in prog.enums:
            if getattr(e, 'type_params', None):
                self.generic_enums[e.name] = e
            else:
                self.enums[e.name] = {v.name: [self._type_name(t) for t in v.fields] for v in e.variants}
        self.fixes = {}
        for c in getattr(prog, 'fixes', []) or []:
            if c.typ is not None:
                self.fixes[c.name] = c.typ.name
            else:
                self.fixes[c.name] = self.check(c.value)
        self.overloads = {}
        self.generic_fns = {}
        self.function_decls = {}
        for f in prog.funcs:
            if getattr(f, 'type_params', None):
                self.generic_fns[f.name] = f
                continue
            self.function_decls.setdefault(f.name, []).append(f)
            ats = [_norm_type_name(p.typ) if p.typ else 'long' for p in f.params]
            ret = _norm_type_name(f.ret) if f.ret else 'long'
            existing = self.overloads.setdefault(f.name, [])
            for pats, pret in existing:
                if pats == ats:
                    self.errors.append(
                        f"type error: duplicate overload '{f.name}({', '.join(ats)})'"
                    )
                    break
            else:
                existing.append((ats, ret))
            self.funcs[f.name] = (ats, ret)  # last wins for simple lookup
        for f in prog.funcs:
            if getattr(f, 'type_params', None):
                continue  # check specialized clones on demand
            self.current_fn = f.name
            self.current_ret = _norm_type_name(f.ret) if f.ret else 'long'
            self.env = {}
            for p in f.params:
                ptype = (
                    _fn_type_tag(p.typ) if p.typ and getattr(p.typ, 'name', None) == 'fn'
                    else (_norm_type_name(p.typ) if p.typ else 'long')
                )
                if p.default is not None:
                    default_type = self.check(p.default)
                    if not _types_compatible(ptype, default_type):
                        self.errors.append(
                            f"type error: default for parameter '{p.name}' in function "
                            f"'{f.name}' has type '{default_type}', expected '{ptype}'"
                        )
                self.env[p.name] = ptype
            body_t = self.check(f.body)
            if body_t and not _types_compatible(self.current_ret, body_t):
                self.errors.append(
                    f"type error: function '{f.name}' returns '{self.current_ret}' but body yields '{body_t}'"
                )
            self.current_fn = None
            self.current_ret = None
        if prog.toplevel is not None:
            self.env = {}
            self.current_fn = None
            self.current_ret = None
            self.check(prog.toplevel)
        return self.errors

    def _infer_generic_args(self, g, arg_types):
        mapping = {}
        def bind(tp, concrete):
            if tp not in g.type_params:
                return True
            if tp in mapping and mapping[tp] != concrete:
                self.errors.append(
                    f"type error: cannot infer '{tp}' as both '{mapping[tp]}' and '{concrete}'"
                )
                return False
            mapping[tp] = concrete
            return True
        for p, at in zip(g.params, arg_types):
            if p.typ is None:
                continue
            t = p.typ
            if isinstance(t, TypeNode) and t.name == 'list' and t.args:
                inner = _type_node_name(t.args[0])
                atn = at[5:] if isinstance(at, str) and at.startswith('list_') else ('long' if at in ('list', 'List', 'list_long') else at)
                if at in ('list', 'List', 'list_long'):
                    atn = 'long'
                elif isinstance(at, str) and at.startswith('list_'):
                    atn = at[5:]
                if not bind(inner, atn):
                    return None
            else:
                tn = _type_node_name(t)
                if not bind(tn, at):
                    return None
        if len(mapping) != len(g.type_params):
            missing = [t for t in g.type_params if t not in mapping]
            self.errors.append(
                f"type error: cannot infer type args for '{g.name}' (need explicit {g.name}[{', '.join(g.type_params)}](...); missing {missing})"
            )
            return None
        return [mapping[t] for t in g.type_params]

    def specialize_generic(self, name: str, type_args: list, prog=None):
        g = self.generic_fns.get(name)
        if not g:
            return None
        if len(type_args) != len(g.type_params):
            self.errors.append(
                f"type error: '{name}' expects {len(g.type_params)} type arg(s), got {len(type_args)}"
            )
            return None
        mapping = {tp: _type_node_name(ta) for tp, ta in zip(g.type_params, type_args)}
        mangled = _mangle_generic(name, list(mapping.values()))
        if mangled in self.funcs:
            return mangled
        nf = copy.deepcopy(g)
        nf.name = mangled
        nf.type_params = []
        for p in nf.params:
            if p.typ is not None:
                p.typ = _subst_type_node(p.typ, mapping)
        if nf.ret is not None:
            nf.ret = _subst_type_node(nf.ret, mapping)
        def walk(e):
            if e is None:
                return
            if isinstance(e, LetExpr) and e.typ is not None:
                e.typ = _subst_type_node(e.typ, mapping)
            for attr in ('body', 'value', 'cond', 'then', 'els', 'left', 'right', 'expr', 'subject'):
                if hasattr(e, attr):
                    walk(getattr(e, attr))
            if hasattr(e, 'stmts'):
                for st in e.stmts:
                    walk(st)
            if hasattr(e, 'args'):
                for a in e.args:
                    walk(a)
            if hasattr(e, 'items'):
                for it in e.items:
                    walk(it)
        walk(nf.body)
        ats = [_norm_type_name(p.typ) if p.typ else 'long' for p in nf.params]
        ret = _norm_type_name(nf.ret) if nf.ret else 'long'
        self.funcs[mangled] = (ats, ret)
        self.overloads.setdefault(mangled, []).append((ats, ret))
        self.function_decls.setdefault(mangled, []).append(nf)
        self.specialized[mangled] = nf
        if prog is not None and not any(f.name == mangled for f in prog.funcs):
            prog.funcs.append(nf)
        old_fn, old_ret, old_env = self.current_fn, self.current_ret, self.env
        self.current_fn = mangled
        self.current_ret = ret
        self.env = {p.name: (_norm_type_name(p.typ) if p.typ else 'long') for p in nf.params}
        body_t = self.check(nf.body)
        if body_t and not _types_compatible(ret, body_t):
            self.errors.append(
                f"type error: function '{mangled}' returns '{ret}' but body yields '{body_t}'"
            )
        self.current_fn, self.current_ret, self.env = old_fn, old_ret, old_env
        return mangled

    def specialize_rec(self, name: str, type_args: list, prog=None):
        g = self.generic_recs.get(name)
        if not g:
            return None
        if len(type_args) != len(g.type_params):
            self.errors.append(
                f"type error: '{name}' expects {len(g.type_params)} type arg(s), got {len(type_args)}"
            )
            return None
        mapping = {tp: _type_node_name(ta) for tp, ta in zip(g.type_params, type_args)}
        mangled = _mangle_generic(name, list(mapping.values()))
        if mangled in self.recs:
            return mangled
        nr = copy.deepcopy(g)
        nr.name = mangled
        nr.type_params = []
        fields = []
        for fname, ft in nr.fields:
            fields.append((fname, _subst_type_node(ft, mapping)))
        nr.fields = fields
        self.recs[mangled] = {n: (self._type_name(t) if t else 'long') for n, t in nr.fields}
        self.specialized[mangled] = nr
        if prog is not None and not any(r.name == mangled for r in prog.recs):
            prog.recs.append(nr)
        return mangled

    def specialize_enum(self, name: str, type_args: list, prog=None):
        g = self.generic_enums.get(name)
        if not g:
            return None
        if len(type_args) != len(g.type_params):
            self.errors.append(
                f"type error: '{name}' expects {len(g.type_params)} type arg(s), got {len(type_args)}"
            )
            return None
        mapping = {tp: _type_node_name(ta) for tp, ta in zip(g.type_params, type_args)}
        mangled = _mangle_generic(name, list(mapping.values()))
        if mangled in self.enums:
            return mangled
        ne = copy.deepcopy(g)
        ne.name = mangled
        ne.type_params = []
        for v in ne.variants:
            v.fields = [_subst_type_node(t, mapping) for t in v.fields]
        self.enums[mangled] = {v.name: [self._type_name(t) for t in v.fields] for v in ne.variants}
        self.specialized[mangled] = ne
        if prog is not None and not any(e.name == mangled for e in prog.enums):
            prog.enums.append(ne)
        return mangled

    def check(self, e):
        if isinstance(e, IntLit): return 'long'
        if isinstance(e, BoolLit): return 'bool'
        if isinstance(e, StrLit): return 'str'
        if isinstance(e, TupleLit):
            e.inferred_type = 'tuple__' + '__'.join(
                _norm_type_name(self.check(item)) for item in e.items
            )
            return e.inferred_type
        if isinstance(e, ListLit):
            item_types = [self.check(it) for it in e.items]
            if not item_types:
                return 'list'  # empty: inhabits any list_* via annotation
            norms = [_norm_type_name(t) for t in item_types]
            base = norms[0]
            _intish = {'i8','i16','int','long','u8','u16','u32','u64','char'}
            for i, t in enumerate(norms[1:], start=2):
                if t == base:
                    continue
                if base in _intish and t in _intish:
                    base = 'long'
                    continue
                self.errors.append(
                    f"type error: list element {i} has type '{t}', expected '{base}'"
                )
                break
            if base == 'str':
                return 'list_str'
            if base in self.recs:
                return f'list_{base}'
            if base in ('i8','i16','int','u8','u16','u32','u64','char','f32','dbl','bool'):
                return f'list_{base}'
            return 'list_long'
        if isinstance(e, RecordLit):
            for _, v in e.fields: self.check(v)
            if isinstance(e.ctor, Index) and isinstance(e.ctor.coll, Var):
                n = e.ctor.coll.name
                if n in getattr(self, 'generic_recs', {}):
                    raw = _type_node_name(self._type_arg_from_expr(e.ctor.idx))
                    targs = raw if isinstance(raw, list) else [raw]
                    mangled = self.specialize_rec(n, targs, getattr(self, 'prog', None))
                    if mangled:
                        e.ctor = Var(mangled)
                        return mangled
            if isinstance(e.ctor, Var) and e.ctor.name in self.recs:
                return e.ctor.name
            if isinstance(e.ctor, Var) and e.ctor.name in getattr(self, 'generic_recs', {}):
                self.errors.append(
                    f"type error: '{e.ctor.name}' is generic; use {e.ctor.name}[T] {{ ... }}"
                )
            return 'long'
        if isinstance(e, Var):
            if e.name in self.env: return self.env[e.name]
            if hasattr(self, 'fixes') and e.name in self.fixes: return self.fixes[e.name]
            if e.name in self.enums: return e.name
            if e.name in self.funcs or e.name in (
                'pr','len','env','str','push','substr','arg',
                'keys','values','has','up','low','trim','split','join',
                'parse','starts','ends','map','fmt','err'
            ): return 'fn'
            if e.name in ('http','db','tst','fs','gcc','io','sock'): return 'mod'
            self.errors.append(f"unknown name '{e.name}'")
            return 'long'
        if isinstance(e, Member):
            if isinstance(e.obj, Index) and isinstance(e.obj.coll, Var):
                n = e.obj.coll.name
                if n in getattr(self, 'generic_enums', {}):
                    raw = _type_node_name(self._type_arg_from_expr(e.obj.idx))
                    targs = raw if isinstance(raw, list) else [raw]
                    mangled = self.specialize_enum(n, targs, getattr(self, 'prog', None))
                    if mangled:
                        e.obj = Var(mangled)
            if isinstance(e.obj, Var) and e.obj.name in self.enums:
                if e.field in self.enums[e.obj.name]:
                    return e.obj.name
            base = self.check(e.obj)
            if base in self.recs:
                return self.recs[base].get(e.field, 'long')
            if base in self.enums:
                if e.field in self.enums[base]:
                    return base
                return 'long'
            if base in ('List', 'list') or (isinstance(base, str) and base.startswith('list_')):
                if e.field in ('size', 'len'):
                    return 'long'
            return 'long'
        if isinstance(e, Binary):
            lt = self.check(e.left); rt = self.check(e.right)
            if e.op == '=':
                if not _types_compatible(lt, rt):
                    self.errors.append(
                        f"type error: cannot assign '{rt}' to '{lt}'"
                    )
                return lt
            if e.op == '+':
                if isinstance(lt, str) and (lt.startswith('list_') or lt in ('list', 'List')):
                    if isinstance(rt, str) and (rt.startswith('list_') or rt in ('list', 'List')):
                        if not _types_compatible(lt, rt):
                            self.errors.append(
                                f"type error: cannot concat '{lt}' and '{rt}'"
                            )
                        return lt if lt.startswith('list_') else rt
                    elem = lt[5:] if lt.startswith('list_') else 'long'
                    if not _types_compatible(elem, rt):
                        self.errors.append(
                            f"type error: cannot push '{rt}' into '{lt}'"
                        )
                    return lt
                if lt == 'list_str' or rt == 'list_str':
                    return 'list_str'
                if lt == 'str' or rt == 'str':
                    return 'str'
            if e.op in ('==', '!=', '<', '>', '<=', '>='):
                if (isinstance(lt, str) and lt.startswith('list_')) or (isinstance(rt, str) and rt.startswith('list_')):
                    if not _types_compatible(lt, rt, strict_list=True):
                        self.errors.append(
                            f"type error: cannot compare '{lt}' and '{rt}'"
                        )
                elif (lt == 'str') != (rt == 'str') and lt != rt:
                    self.errors.append(
                        f"type error: cannot compare '{lt}' and '{rt}'"
                    )
                return 'bool'
            if e.op in ('+','-','*','/','%'):
                if lt in ('dbl','f32') or rt in ('dbl','f32'):
                    if lt == 'dbl' or rt == 'dbl' or lt == 'double' or rt == 'double':
                        return 'dbl'
                    return 'f32'
                return 'long'
            return 'bool' if e.op in ('==','!=','<','>','<=','>=','&&','||') else 'long'
        if isinstance(e, Unary): return self.check(e.expr)
        if isinstance(e, RetExpr):
            if e.value is not None:
                vt = self.check(e.value)
                if self.current_ret is not None and not _types_compatible(self.current_ret, vt):
                    fn = self.current_fn or '<fn>'
                    self.errors.append(
                        f"type error: ret type '{vt}' does not match function '{fn}' return type '{self.current_ret}'"
                    )
                return vt
            if self.current_ret is not None and not _types_compatible(self.current_ret, 'long'):
                fn = self.current_fn or '<fn>'
                self.errors.append(
                    f"type error: bare ret is i64 but function '{fn}' returns '{self.current_ret}'"
                )
            return 'long'
        if isinstance(e, Call) and isinstance(e.func, Member):
            if isinstance(e.func.obj, Index) and isinstance(e.func.obj.coll, Var):
                n = e.func.obj.coll.name
                if n in getattr(self, 'generic_enums', {}):
                    raw = _type_node_name(self._type_arg_from_expr(e.func.obj.idx))
                    targs = raw if isinstance(raw, list) else [raw]
                    mangled = self.specialize_enum(n, targs, getattr(self, 'prog', None))
                    if mangled:
                        e.func.obj = Var(mangled)
                        for a in e.args:
                            self.check(a)
                        return mangled
            if isinstance(e.func.obj, Var) and e.func.obj.name in self.enums:
                for a in e.args:
                    self.check(a)
                return e.func.obj.name
        if isinstance(e, Call):
            if isinstance(e.func, Var):
                n = e.func.name
                builtins = {'pr','len','env','str','push','substr','arg','keys','values',
                            'has','up','low','trim','split','join','parse','starts','ends','map','fmt','err'}
                if (n not in self.funcs and n not in builtins and n not in self.env
                        and n not in getattr(self, 'generic_fns', {})):
                    self.errors.append(f"unknown function '{n}'")
            arg_types = [self.check(a) for a in e.args]
            if isinstance(e.func, Var) and e.func.name == 'err':
                if len(e.args) != 1:
                    self.errors.append(
                        f"type error: function 'err' expects 1 argument(s), got {len(e.args)}"
                    )
                elif not _types_compatible('str', arg_types[0]):
                    self.errors.append(
                        f"type error: argument 1 of 'err' has type '{arg_types[0]}', expected 'str'"
                    )
                return 'long'
            if isinstance(e.func, Index) and isinstance(e.func.coll, Var):
                n = e.func.coll.name
                if n in getattr(self, 'generic_fns', {}):
                    raw = _type_node_name(self._type_arg_from_expr(e.func.idx))
                    targs = raw if isinstance(raw, list) else [raw]
                    mangled = self.specialize_generic(n, targs, getattr(self, "prog", None))
                    if mangled:
                        e.func = Var(mangled)
                        n = mangled
            elif isinstance(e.func, Var):
                n = e.func.name
                if n in getattr(self, 'generic_fns', {}):
                    targs = self._infer_generic_args(self.generic_fns[n], arg_types)
                    if targs:
                        mangled = self.specialize_generic(n, targs, getattr(self, "prog", None))
                        if mangled:
                            e.func = Var(mangled)
                            n = mangled
            if isinstance(e.func, Var):
                n = e.func.name
                declarations = self.function_decls.get(n, [])
                if declarations:
                    arity_candidates = []
                    for fn in declarations:
                        required = next(
                            (i for i, p in enumerate(fn.params) if p.default is not None),
                            len(fn.params),
                        )
                        if required <= len(e.args) <= len(fn.params):
                            pts = [
                                _norm_type_name(p.typ) if p.typ else 'long'
                                for p in fn.params[:len(e.args)]
                            ]
                            ret = _norm_type_name(fn.ret) if fn.ret else 'long'
                            arity_candidates.append((fn, pts, ret))
                    if not arity_candidates:
                        ranges = []
                        for fn in declarations:
                            required = next(
                                (i for i, p in enumerate(fn.params) if p.default is not None),
                                len(fn.params),
                            )
                            ranges.append(
                                str(required) if required == len(fn.params)
                                else f"{required}..{len(fn.params)}"
                            )
                        expected = ", ".join(sorted(set(ranges)))
                        self.errors.append(
                            f"type error: function '{n}' expects {expected} argument(s), "
                            f"got {len(e.args)}"
                        )
                        return 'long'
                    if len(arity_candidates) == 1:
                        selected = [arity_candidates[0][0]]
                        ret_type = arity_candidates[0][2]
                    else:
                        partials = [(pts, fn.name, ret) for fn, pts, ret in arity_candidates]
                        resolved = _resolve_overload(partials, arg_types)
                        if resolved is None:
                            self.errors.append(
                                f"type error: no overload of '{n}' matches ({', '.join(arg_types)})"
                            )
                            return 'long'
                        ret_type = resolved[2]
                        selected = [
                            fn for fn, pts, ret in arity_candidates
                            if pts == resolved[0]
                        ]
                    if len(selected) != 1:
                        self.errors.append(
                            f"type error: call to '{n}' is ambiguous with "
                            f"{len(e.args)} argument(s)"
                        )
                        return ret_type
                    fn = selected[0]
                    if len(e.args) < len(fn.params):
                        e.resolved_params = copy.deepcopy(fn.params)
                        old_env = self.env
                        self.env = old_env.copy()
                        for param in fn.params[:len(e.args)]:
                            self.env[param.name] = (
                                _norm_type_name(param.typ) if param.typ else 'long'
                            )
                        for param in fn.params[len(e.args):]:
                            default_type = self.check(param.default)
                            expected_type = _norm_type_name(param.typ) if param.typ else 'long'
                            if not _types_compatible(expected_type, default_type):
                                self.errors.append(
                                    f"type error: default for parameter '{param.name}' in "
                                    f"function '{n}' has type '{default_type}', "
                                    f"expected '{expected_type}'"
                                )
                            self.env[param.name] = expected_type
                        self.env = old_env
                    if len(declarations) > 1:
                        for i, (actual, param) in enumerate(zip(arg_types, fn.params)):
                            expected_type = _norm_type_name(param.typ) if param.typ else 'long'
                            if not _types_compatible(expected_type, actual):
                                self.errors.append(
                                    f"type error: argument {i + 1} of '{n}' has type "
                                    f"'{actual}', expected '{expected_type}'"
                                )
                    return ret_type
                overs = getattr(self, 'overloads', {}).get(n) or []
                if len(overs) > 1:
                    pack = [(pts, n, ret) for pts, ret in overs]
                    resolved = _resolve_overload(pack, arg_types)
                    if resolved is None:
                        self.errors.append(
                            f"type error: no overload of '{n}' matches ({', '.join(arg_types)})"
                        )
                        return 'long'
                    return resolved[2]
                if n in self.funcs:
                    return self.funcs[n][1]
                if n == 'fmt':
                    return 'str'
                if n == 'pr':
                    return 'long'
            if isinstance(e.func, Member):
                recv_t = self.check(e.func.obj)
                key = (recv_t, e.func.field)
                if key in getattr(self, 'methods', {}):
                    return self.methods[key][1]
            if isinstance(e.func, Var) and e.func.name == 'push' and e.args:
                return self.check(e.args[0])
            if isinstance(e.func, Member) and isinstance(e.func.obj, Var) \
                    and e.func.obj.name in ('io', 'fs'):
                if e.func.field in ('in', 'read_text'): return 'str'
                if e.func.field in ('out', 'write_text', 'append', 'append_text'): return 'long'
            if isinstance(e.func, Member) and isinstance(e.func.obj, Var) \
                    and e.func.obj.name == 'str':
                f = e.func.field
                if f == 'split':
                    return 'list_str'
                if f in ('has', 'starts', 'ends'):
                    return 'bool'
                if f in ('trim', 'up', 'low', 'join'):
                    return 'str'
                if f == 'parse':
                    return 'long'
                if f == 'len':
                    return 'long'
            if isinstance(e.func, Var):
                n = e.func.name
                if n == 'pr':
                    return 'long'
                if n in ( 'env', 'substr', 'arg', 'trim', 'up', 'low', 'join', 'parse'):
                    return 'str' if n != 'parse' else 'long'
                if n == 'split':
                    return 'list_str'
                if n == 'len':
                    return 'long'
                if n == 'has':
                    return 'bool'
                if n == 'keys':
                    return 'list_str'
                if n == 'values':
                    return 'list'
                if n in ('starts', 'ends'):
                    return 'bool'
                if n == 'str':
                    return 'str'
            return 'long'
        if isinstance(e, Index):
            coll_type = self.check(e.coll)
            self.check(e.idx)
            if isinstance(coll_type, str) and coll_type.startswith('list_'):
                return coll_type[5:]
            if isinstance(coll_type, str) and coll_type.startswith('List_'):
                return coll_type[5:]
            if isinstance(coll_type, str) and coll_type.startswith('map_'):
                parts = coll_type.split('_')
                return '_'.join(parts[2:]) if len(parts) >= 3 else 'long'
            return 'long'
        if isinstance(e, MapLit):
            if not e.entries:
                return 'map_str_long'
            vt = self.check(e.entries[0][1])
            self.check(e.entries[0][0])
            for k, v in e.entries[1:]:
                self.check(k); self.check(v)
            if vt == 'str':
                return 'map_str_str'
            return 'map_str_long'
        if isinstance(e, IfExpr):
            self.check(e.cond); t=self.check(e.then)
            if e.els: self.check(e.els)
            return t
        if isinstance(e, TernaryExpr):
            self.check(e.cond)
            t = self.check(e.then)
            self.check(e.els)
            return t
        if isinstance(e, LoopExpr):
            old_env = self.env.copy()
            if e.init is not None:
                if isinstance(e.init, LetExpr):
                    t = e.init.typ.name if e.init.typ else self.check(e.init.value)
                    self.env[e.init.name] = t
                elif isinstance(e.init, Binary) and e.init.op == '=' and isinstance(e.init.left, Var):
                    t = self.check(e.init.right)
                    self.env[e.init.left.name] = t
                else:
                    self.check(e.init)
            self.check(e.cond)
            self.check(e.body)
            if e.post is not None:
                self.check(e.post)
            self.env = old_env
            return 'long'
        if isinstance(e, ForInExpr):
            it = self.check(e.iterable)
            if isinstance(it, str) and it.startswith('map_'):
                et = 'str'  # iterate keys
            elif it == 'list_str':
                et = 'str'
            elif isinstance(it, str) and it.startswith('list_'):
                et = it[5:]
            else:
                et = 'long'
            old = self.env.get(e.var)
            self.env[e.var] = et
            self.check(e.body)
            if old is not None: self.env[e.var] = old
            else: self.env.pop(e.var, None)
            return 'long'
        if isinstance(e, LetExpr):
            vt = self.check(e.value)
            if e.typ is not None:
                t = _norm_type_name(e.typ)
                if not _types_compatible(t, vt):
                    self.errors.append(
                        f"type error: '{e.name}' declared '{t}' but value is '{vt}'"
                    )
                else:
                    if t.startswith('list_') or t in ('list', 'List', 'str', 'bool') or t in (
                        'i8','i16','int','long','u8','u16','u32','u64','char','f32','dbl'
                    ):
                        vt = t
            store = _norm_type_name(e.typ) if e.typ is not None else vt
            if e.typ is not None and _types_compatible(store, vt):
                t = store
            elif e.typ is not None:
                t = store  # keep declared even on error so later checks are consistent
            else:
                t = vt
            old = self.env.get(e.name)
            self.env[e.name] = t
            r = self.check(e.body)
            if old is not None: self.env[e.name] = old
            else: self.env.pop(e.name, None)
            return r
        if isinstance(e, TupleLetExpr):
            tuple_type = self.check(e.value)
            item_types = tuple_type[7:].split('__') if tuple_type.startswith('tuple__') else []
            if len(item_types) != len(e.names):
                self.errors.append(
                    f"type error: tuple destructuring expects {len(e.names)} value(s), "
                    f"got {len(item_types)}"
                )
                item_types = ['long'] * len(e.names)
            old_values = {name: self.env.get(name) for name in e.names}
            for name, item_type in zip(e.names, item_types):
                self.env[name] = item_type
            result = self.check(e.body)
            for name, old in old_values.items():
                if old is None:
                    self.env.pop(name, None)
                else:
                    self.env[name] = old
            return result
        if isinstance(e, Lambda):
            old = self.env.copy()
            for p in e.params:
                self.env[p.name] = p.typ.name if p.typ else 'long'  # body often request body
            self.check(e.body)
            self.env = old
            return 'fn'
        if isinstance(e, MatchExpr):
            subj_type = self.check(e.subject)
            for arm in e.arms:
                self.check_pattern(arm.pattern, subj_type)
                if arm.guard is not None:
                    self.check(arm.guard)
                self.check(arm.value)
            return self.check(e.arms[0].value)

        if isinstance(e, Block):
            t = 'long'
            for s in e.stmts: t = self.check(s)
            return t
        if isinstance(e, TrapExpr):
            self.check(e.expr)
            old_env = self.env.copy()
            self.env[e.name] = 'str'
            self.check(e.handler)
            self.env = old_env
            return 'long'
        return 'long'

    def check_pattern(self, pat, subj_type):
        if isinstance(pat, Wildcard):
            return
        if isinstance(pat, BindPattern):
            self.env[pat.name] = subj_type
            return
        if isinstance(pat, LiteralPattern):
            self.check(pat.value)
            return
        if isinstance(pat, EnumVariant):
            if subj_type in self.enums and pat.variant in self.enums[subj_type]:
                ftypes = self.enums[subj_type][pat.variant]
                for i, sub in enumerate(pat.fields):
                    ft = ftypes[i] if i < len(ftypes) else 'long'
                    self.check_pattern(sub, ft)
            return
        if isinstance(pat, TuplePattern):
            for p in pat.items: self.check_pattern(p, 'long')
            return
        if isinstance(pat, ListPattern):
            for p in pat.items: self.check_pattern(p, 'long')
            return
        if isinstance(pat, RecordPattern):
            for field_name, subpat in pat.fields:
                if subpat is not None:
                    self.check_pattern(subpat, 'long')
            return
        raise SyntaxError(f"unsupported pattern type {type(pat).__name__}")

    def _type_arg_from_expr(self, e):
        if isinstance(e, Var):
            return e.name
        if isinstance(e, ListLit):
            return [_type_node_name(self._type_arg_from_expr(x)) for x in e.items]
        if isinstance(e, StrLit):
            return 'str'
        return 'long'