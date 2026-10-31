#!/usr/bin/env python3
"""
Terse Compiler (tersec) 0.1beta
Native binary via C. Strings, lists, pr, http.serve (minimal socket server).
"""
import sys, os, re, shutil, subprocess, argparse, copy

TERSE_VERSION = "0.3"
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Tuple
from enum import Enum, auto


try:
    from .lexer import TT, Tok, Lexer
    from .ast import (
        TypeNode, Param, Expr, IntLit, FloatLit, BoolLit, StrLit, Var,
        Binary, Unary, Call, Member, IfExpr, TernaryExpr, LetExpr,
        RetExpr, JumpExpr, Lambda, LoopExpr, ForInExpr, AssignExpr,
        Block, ListLit, MapLit, Index, Route, HttpServe, FnDecl,
        RecDecl, TraitDecl, MethodDecl, UseDecl, RecordLit, EnumVariantDecl,
        EnumDecl, FixDecl, Wildcard, LiteralPattern, BindPattern,
        EnumVariant, RecordPattern, TuplePattern, ListPattern, MatchArm, MatchExpr,
        Program,
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
except ImportError:
    from tersec.lexer import TT, Tok, Lexer
    from tersec.ast import (
        TypeNode, Param, Expr, IntLit, FloatLit, BoolLit, StrLit, Var,
        Binary, Unary, Call, Member, IfExpr, TernaryExpr, LetExpr,
        RetExpr, JumpExpr, Lambda, LoopExpr, ForInExpr, AssignExpr,
        Block, ListLit, MapLit, Index, Route, HttpServe, FnDecl,
        RecDecl, TraitDecl, MethodDecl, UseDecl, RecordLit, EnumVariantDecl,
        EnumDecl, FixDecl, Wildcard, LiteralPattern, BindPattern,
        EnumVariant, RecordPattern, TuplePattern, ListPattern, MatchArm, MatchExpr,
        Program,
    )
    from tersec.parser import Parser
    from tersec.typecheck import TypeChecker
    from tersec.utils import (
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
        self.satisfied = set()  # set of (sig_name, struct_name) pairs

    def _type_name(self, t):
        if t is None:
            return 'i64'
        if t.name == 'list' and t.args:
            return f"list_{self._type_name(t.args[0])}"
        return t.name

    def compute_satisfaction(self, prog):
        """Structural trait satisfaction. Generic traits: subst type params with concrete type."""
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

        def matches(struct_name, sig_methods):
            for mname, mparams, mret in sig_methods:
                key = (struct_name, mname)
                if key not in self.methods:
                    return False
                mp, mr = self.methods[key]
                if mp != mparams or mr != mret:
                    return False
            return True

        concrete_recs = [r for r in prog.recs if not getattr(r, 'type_params', None)]
        # Non-generic traits
        for sig_name, sig_methods in self.sigs.items():
            for rec in concrete_recs:
                if matches(rec.name, sig_methods):
                    self.satisfied.add((sig_name, rec.name))

        # Generic traits: for each concrete type C, try Eq[C] etc.
        for sig in prog.sigs:
            tps = getattr(sig, 'type_params', None) or []
            if not tps:
                continue
            for rec in concrete_recs:
                # Default: all type params map to the candidate type (Eq[T] for T=Point)
                if len(tps) == 1:
                    mapping = {tps[0]: rec.name}
                else:
                    # Multi-param traits: only auto-try when all params equal candidate
                    mapping = {tp: rec.name for tp in tps}
                sig_methods = []
                for mname, params, ret in sig.methods:
                    ps = []
                    for p in params:
                        if p.typ is not None:
                            ps.append(self._type_name(_subst_type_node(p.typ, mapping)))
                        else:
                            ps.append('i64')
                    rt = self._type_name(_subst_type_node(ret, mapping)) if ret else 'i64'
                    sig_methods.append((mname, ps, rt))
                if matches(rec.name, sig_methods):
                    args = tuple(mapping[tp] for tp in tps)
                    mangled = _mangle_generic(sig.name, list(args))
                    self.sigs[mangled] = sig_methods
                    self.satisfied.add((sig.name, args, rec.name))
                    self.satisfied.add((mangled, rec.name))  # also as specialized name

    def check_program(self, prog):
        self.prog = prog
        self.compute_satisfaction(prog)
        self.recs = {}
        self.generic_recs = {}
        for r in prog.recs:
            if getattr(r, 'type_params', None):
                self.generic_recs[r.name] = r
            else:
                self.recs[r.name] = {n: (self._type_name(t) if t else 'i64') for n, t in r.fields}
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
        self.overloads = {}  # name -> [(param_types, ret)]
        self.generic_fns = {}  # name -> FnDecl with type_params
        # generic_recs / generic_enums already filled above from prog
        if not hasattr(self, 'generic_recs'):
            self.generic_recs = {}
        if not hasattr(self, 'generic_enums'):
            self.generic_enums = {}
        self.specialized = {}  # mangled -> FnDecl / rec / en
        for f in prog.funcs:
            if getattr(f, 'type_params', None):
                self.generic_fns[f.name] = f
                # Template: do not register concrete overload yet
                continue
            ats = [_norm_type_name(p.typ) if p.typ else 'i64' for p in f.params]
            ret = _norm_type_name(f.ret) if f.ret else 'i64'
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
            self.current_ret = _norm_type_name(f.ret) if f.ret else 'i64'
            self.env = {
                p.name: (
                    _fn_type_tag(p.typ) if p.typ and getattr(p.typ, 'name', None) == 'fn'
                    else (_norm_type_name(p.typ) if p.typ else 'i64')
                )
                for p in f.params
            }
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
    def _type_arg_from_expr(self, e):
        """Type argument written as id[i64] or id[str] — Var name is the type."""
        if isinstance(e, Var):
            return e.name
        if isinstance(e, ListLit):
            return [_type_node_name(self._type_arg_from_expr(x)) for x in e.items]
        if isinstance(e, StrLit):
            return 'str'
        return 'i64'

    def specialize_generic(self, name: str, type_args: list, prog=None):
        """Clone generic fn with type_params substituted; register and typecheck."""
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
        # Deep-copy declaration and substitute TypeNodes
        nf = copy.deepcopy(g)
        nf.name = mangled
        nf.type_params = []
        for p in nf.params:
            if p.typ is not None:
                p.typ = _subst_type_node(p.typ, mapping)
        if nf.ret is not None:
            nf.ret = _subst_type_node(nf.ret, mapping)
        # Walk body TypeNodes on annotations (LetExpr.typ etc.) — best effort
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
        ats = [_norm_type_name(p.typ) if p.typ else 'i64' for p in nf.params]
        ret = _norm_type_name(nf.ret) if nf.ret else 'i64'
        self.funcs[mangled] = (ats, ret)
        self.overloads.setdefault(mangled, []).append((ats, ret))
        self.specialized[mangled] = nf
        if prog is not None and not any(f.name == mangled for f in prog.funcs):
            prog.funcs.append(nf)
        # Typecheck specialized body
        old_fn, old_ret, old_env = self.current_fn, self.current_ret, self.env
        self.current_fn = mangled
        self.current_ret = ret
        self.env = {p.name: (_norm_type_name(p.typ) if p.typ else 'i64') for p in nf.params}
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
        self.recs[mangled] = {n: (self._type_name(t) if t else 'i64') for n, t in nr.fields}
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
                atn = at[5:] if isinstance(at, str) and at.startswith('list_') else ('i64' if at in ('list', 'List', 'list_i64') else at)
                if at in ('list', 'List', 'list_i64'):
                    atn = 'i64'
                elif isinstance(at, str) and at.startswith('list_'):
                    atn = at[5:]
                if not bind(inner, atn):
                    return None
            else:
                tn = _type_node_name(t)
                if not bind(tn, at):
                    return None
        if len(mapping) != len(g.type_params):
            # incomplete inference
            missing = [t for t in g.type_params if t not in mapping]
            self.errors.append(
                f"type error: cannot infer type args for '{g.name}' (need explicit {g.name}[{', '.join(g.type_params)}](...); missing {missing})"
            )
            return None
        return [mapping[t] for t in g.type_params]


    def check(self, e):
        if isinstance(e, (IntLit,)): return 'i64'
        if isinstance(e, BoolLit): return 'bool'
        if isinstance(e, StrLit): return 'str'
        if isinstance(e, ListLit):
            item_types = [self.check(it) for it in e.items]
            if not item_types:
                return 'list'  # empty: inhabits any list_* via annotation
            norms = [_norm_type_name(t) for t in item_types]
            base = norms[0]
            _intish = {'i8','i16','i32','i64','u8','u16','u32','u64','char'}
            for i, t in enumerate(norms[1:], start=2):
                if t == base:
                    continue
                if base in _intish and t in _intish:
                    base = 'i64'
                    continue
                self.errors.append(
                    f"type error: list element {i} has type '{t}', expected '{base}'"
                )
                break
            if base == 'str':
                return 'list_str'
            if base in self.recs:
                return f'list_{base}'
            if base in ('i8','i16','i32','u8','u16','u32','u64','char','f32','f64','bool'):
                return f'list_{base}'
            return 'list_i64'
        if isinstance(e, RecordLit):
            for _, v in e.fields: self.check(v)
            # Box[i64] { ... } — Index ctor
            if isinstance(e.ctor, Index) and isinstance(e.ctor.coll, Var):
                n = e.ctor.coll.name
                if n in getattr(self, 'generic_recs', {}):
                    raw = self._type_arg_from_expr(e.ctor.idx)
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
            return 'i64'
        if isinstance(e, Var):
            if e.name in self.env: return self.env[e.name]
            if hasattr(self, 'fixes') and e.name in self.fixes: return self.fixes[e.name]
            if e.name in self.enums: return e.name
            if e.name in self.funcs or e.name in (
                'pr','len','json','env','str','push','substr','arg',
                'keys','values','has','up','low','trim','split','join',
                'parse','starts','ends','map'
            ): return 'fn'
            if e.name in ('http','db','tst','fs','gcc','io','str','sock'): return 'mod'
            # Unknown identifier — report so host fails before C compile
            self.errors.append(f"unknown name '{e.name}'")
            return 'i64'
        if isinstance(e, Member):
            # Opt[i64].None / Opt[i64].Some — specialize generic enum
            if isinstance(e.obj, Index) and isinstance(e.obj.coll, Var):
                n = e.obj.coll.name
                if n in getattr(self, 'generic_enums', {}):
                    raw = self._type_arg_from_expr(e.obj.idx)
                    targs = raw if isinstance(raw, list) else [raw]
                    mangled = self.specialize_enum(n, targs, getattr(self, 'prog', None))
                    if mangled:
                        e.obj = Var(mangled)
            if isinstance(e.obj, Var) and e.obj.name in self.enums:
                if e.field in self.enums[e.obj.name]:
                    return e.obj.name
            base = self.check(e.obj)
            if base in self.recs:
                return self.recs[base].get(e.field, 'i64')
            if base in self.enums:
                if e.field in self.enums[base]:
                    return base
                return 'i64'
            if base in ('List', 'list') or (isinstance(base, str) and base.startswith('list_')):
                if e.field in ('size', 'len'):
                    return 'i64'
            return 'i64'
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
                    elem = lt[5:] if lt.startswith('list_') else 'i64'
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
                # float arithmetic keeps float width
                if lt in ('f64','f32') or rt in ('f64','f32'):
                    if lt == 'f64' or rt == 'f64' or lt == 'double' or rt == 'double':
                        return 'f64'
                    return 'f32'
                return 'i64'
            return 'bool' if e.op in ('==','!=','<','>','<=','>=','&&','||') else 'i64'
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
            if self.current_ret is not None and not _types_compatible(self.current_ret, 'i64'):
                fn = self.current_fn or '<fn>'
                self.errors.append(
                    f"type error: bare ret is i64 but function '{fn}' returns '{self.current_ret}'"
                )
            return 'i64'
        if isinstance(e, Call) and isinstance(e.func, Member):
            # Opt[i64].Some(x)
            if isinstance(e.func.obj, Index) and isinstance(e.func.obj.coll, Var):
                n = e.func.obj.coll.name
                if n in getattr(self, 'generic_enums', {}):
                    raw = self._type_arg_from_expr(e.func.obj.idx)
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
            # Resolve callee before checking args for better messages
            if isinstance(e.func, Var):
                n = e.func.name
                builtins = {'pr','len','json','env','str','push','substr','arg','keys','values',
                            'has','up','low','trim','split','join','parse','starts','ends','map','fmt'}
                if (n not in self.funcs and n not in builtins and n not in self.env
                        and n not in getattr(self, 'generic_fns', {})):
                    self.errors.append(f"unknown function '{n}'")
            arg_types = [self.check(a) for a in e.args]
            # Generic call: id[i64](x) or id[A,B](…) via Index, or infer id(x)
            if isinstance(e.func, Index) and isinstance(e.func.coll, Var):
                n = e.func.coll.name
                if n in getattr(self, 'generic_fns', {}):
                    raw = self._type_arg_from_expr(e.func.idx)
                    targs = raw if isinstance(raw, list) else [raw]
                    mangled = self.specialize_generic(n, targs, getattr(self, "prog", None))
                    if mangled:
                        e.func = Var(mangled)  # rewrite for codegen
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
                overs = getattr(self, 'overloads', {}).get(n) or []
                if len(overs) > 1:
                    # Type-directed resolution among overloads
                    pack = [(pts, n, ret) for pts, ret in overs]
                    resolved = _resolve_overload(pack, arg_types)
                    if resolved is None:
                        self.errors.append(
                            f"type error: no overload of '{n}' matches ({', '.join(arg_types)})"
                        )
                        return 'i64'
                    return resolved[2]
                if n in self.funcs:
                    return self.funcs[n][1]
                # Builtins handled without treating the name as a value binding
                if n == 'fmt':
                    return 'str'
                if n == 'pr':
                    return 'i64'
            self.check(e.func)
            # Method call: recv.meth(...) — return type from method table
            if isinstance(e.func, Member):
                recv_t = self.check(e.func.obj)
                key = (recv_t, e.func.field)
                if key in getattr(self, 'methods', {}):
                    return self.methods[key][1]
            if isinstance(e.func, Var) and e.func.name == 'push' and e.args:
                return self.check(e.args[0])
            if isinstance(e.func, Member) and isinstance(e.func.obj, Var) \
                    and e.func.obj.name in ('io', 'fs'):
                # std.io: io.in / io.out  (fs.* kept as aliases)
                if e.func.field in ('in', 'read_text'): return 'str'
                if e.func.field in ('out', 'write_text', 'append', 'append_text'): return 'i64'
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
                    return 'i64'
                if f == 'len':
                    return 'i64'
            if isinstance(e.func, Member) and isinstance(e.func.obj, Var) \
                    and e.func.obj.name == 'http' and e.func.field == 'serve':
                return 'i64'
            if isinstance(e.func, Member) and isinstance(e.func.obj, Var) \
                    and e.func.obj.name == 'sock':
                if e.func.field in ('listen', 'accept', 'send', 'close'):
                    return 'i64'
                if e.func.field == 'recv':
                    return 'str'
            if isinstance(e.func, Member) and isinstance(e.func.obj, Var) \
                    and e.func.obj.name == 'gcc' and e.func.field == 'compile':
                return 'i64'
            if isinstance(e.func, Index) and isinstance(e.func.coll, Member) \
                    and isinstance(e.func.coll.obj, Var) and e.func.coll.obj.name == 'db' \
                    and e.func.coll.field in ('query', 'query_one') \
                    and isinstance(e.func.idx, Var):
                return f'list_{e.func.idx.name}'
            if isinstance(e.func, Var):
                n = e.func.name
                if n == 'pr':
                    return 'i64'
                if n in ('json', 'env', 'substr', 'arg', 'trim', 'up', 'low', 'join', 'parse'):
                    return 'str' if n != 'parse' else 'i64'
                if n == 'split':
                    return 'list_str'
                if n == 'len':
                    return 'i64'
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
            return 'i64'
        if isinstance(e, Index):
            coll_type = self.check(e.coll)
            self.check(e.idx)
            if isinstance(coll_type, str) and coll_type.startswith('list_'):
                return coll_type[5:]
            # Legacy List_Token / List_Function field types
            if isinstance(coll_type, str) and coll_type.startswith('List_'):
                return coll_type[5:]
            if isinstance(coll_type, str) and coll_type.startswith('map_'):
                parts = coll_type.split('_')
                return '_'.join(parts[2:]) if len(parts) >= 3 else 'i64'
            return 'i64'
        if isinstance(e, MapLit):
            if not e.entries:
                return 'map_str_i64'
            vt = self.check(e.entries[0][1])
            self.check(e.entries[0][0])
            for k, v in e.entries[1:]:
                self.check(k); self.check(v)
            if vt == 'str':
                return 'map_str_str'
            return 'map_str_i64'
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
                    # `lp i = 0; ...` — bind loop variable
                    t = self.check(e.init.right)
                    self.env[e.init.left.name] = t
                else:
                    self.check(e.init)
            self.check(e.cond)
            self.check(e.body)
            if e.post is not None:
                self.check(e.post)
            self.env = old_env
            return 'i64'
        if isinstance(e, ForInExpr):
            it = self.check(e.iterable)
            if isinstance(it, str) and it.startswith('map_'):
                et = 'str'  # iterate keys
            elif it == 'list_str':
                et = 'str'
            elif isinstance(it, str) and it.startswith('list_'):
                et = it[5:]
            else:
                et = 'i64'
            old = self.env.get(e.var)
            self.env[e.var] = et
            self.check(e.body)
            if old is not None: self.env[e.var] = old
            else: self.env.pop(e.var, None)
            return 'i64'
        if isinstance(e, LetExpr):
            vt = self.check(e.value)
            if e.typ is not None:
                t = _norm_type_name(e.typ)
                if not _types_compatible(t, vt):
                    self.errors.append(
                        f"type error: '{e.name}' declared '{t}' but value is '{vt}'"
                    )
                else:
                    # Prefer declared list/element width (e.g. [] or [1,2] as [i32])
                    if t.startswith('list_') or t in ('list', 'List', 'str', 'bool') or t in (
                        'i8','i16','i32','i64','u8','u16','u32','u64','char','f32','f64'
                    ):
                        vt = t
            else:
                t = vt
            # Store declared type when present so later assigns use it
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
        if isinstance(e, Lambda):
            old = self.env.copy()
            for p in e.params:
                self.env[p.name] = p.typ.name if p.typ else 'i64'  # body often request body
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
                    ft = ftypes[i] if i < len(ftypes) else 'i64'
                    self.check_pattern(sub, ft)
            return
        if isinstance(pat, TuplePattern):
            for p in pat.items: self.check_pattern(p, 'i64')
            return
        if isinstance(pat, ListPattern):
            for p in pat.items: self.check_pattern(p, 'i64')
            return
        if isinstance(pat, RecordPattern):
            for field_name, subpat in pat.fields:
                if subpat is not None:
                    self.check_pattern(subpat, 'i64')
            return
        raise SyntaxError(f"unsupported pattern type {type(pat).__name__}")

# --- C runtime + HTTP server ------------------------------
RUNTIME = r'''
#if !defined(_WIN32)
#define _DEFAULT_SOURCE
#define _POSIX_C_SOURCE 200112L
#endif
#include <stdint.h>
#include <stdbool.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#ifdef _WIN32
#include <process.h>
#else
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>
#endif

#define SQLITE_OK 0
#define SQLITE_ROW 100
#define SQLITE_DONE 101
#define SQLITE_TRANSIENT ((void(*)(void*))-1)

typedef struct sqlite3 sqlite3;
typedef struct sqlite3_stmt sqlite3_stmt;
#ifdef _WIN32
    #define WIN32_LEAN_AND_MEAN
    #include <windows.h>
    static HMODULE terse_sqlite = NULL;
    static int (*sqlite3_initialize)(void) = NULL;
    static int (*sqlite3_open)(const char*, sqlite3**) = NULL;
    static int (*sqlite3_close)(sqlite3*) = NULL;
    static const char* (*sqlite3_errmsg)(sqlite3*) = NULL;
    static int (*sqlite3_prepare_v2)(sqlite3*, const char*, int, sqlite3_stmt**, const char**) = NULL;
    static int (*sqlite3_step)(sqlite3_stmt*) = NULL;
    static int (*sqlite3_finalize)(sqlite3_stmt*) = NULL;
    static int (*sqlite3_bind_int64)(sqlite3_stmt*, int, int64_t) = NULL;
    static int (*sqlite3_bind_text)(sqlite3_stmt*, int, const char*, int, void(*)(void*)) = NULL;
    static int64_t (*sqlite3_column_int64)(sqlite3_stmt*, int) = NULL;
    static int (*sqlite3_column_int)(sqlite3_stmt*, int) = NULL;
    static double (*sqlite3_column_double)(sqlite3_stmt*, int) = NULL;
    static const unsigned char* (*sqlite3_column_text)(sqlite3_stmt*, int) = NULL;
    static int (*sqlite3_column_count)(sqlite3_stmt*) = NULL;
    static int (*sqlite3_changes)(sqlite3*) = NULL;
    static void db_load_sqlite(void) {
        if (terse_sqlite) return;
        terse_sqlite = LoadLibraryA("sqlite3.dll");
        if (!terse_sqlite) { fprintf(stderr, "sqlite3.dll not found\n"); exit(1); }
        #define LOAD_SQLITE(name) name = (void*)GetProcAddress(terse_sqlite, #name)
        LOAD_SQLITE(sqlite3_initialize);
        LOAD_SQLITE(sqlite3_open); LOAD_SQLITE(sqlite3_close);
        LOAD_SQLITE(sqlite3_errmsg); LOAD_SQLITE(sqlite3_prepare_v2);
        LOAD_SQLITE(sqlite3_step); LOAD_SQLITE(sqlite3_finalize);
        LOAD_SQLITE(sqlite3_bind_int64); LOAD_SQLITE(sqlite3_bind_text);
        LOAD_SQLITE(sqlite3_column_int64); LOAD_SQLITE(sqlite3_column_int);
        LOAD_SQLITE(sqlite3_column_double); LOAD_SQLITE(sqlite3_column_text);
        LOAD_SQLITE(sqlite3_column_count);
        LOAD_SQLITE(sqlite3_changes);
        #undef LOAD_SQLITE
    }
#else
    /* DB/sqlite support disabled — stubs so we do not need -lsqlite3 */
    static int sqlite3_open(const char* a, sqlite3** b) { (void)a;(void)b; fprintf(stderr,"db support disabled\n"); exit(1); return 1; }
    static int sqlite3_initialize(void) { return 0; }
    static int sqlite3_close(sqlite3* a) { (void)a; return 0; }
    static const char* sqlite3_errmsg(sqlite3* a) { (void)a; return "db disabled"; }
    static int sqlite3_prepare_v2(sqlite3* a, const char* b, int c, sqlite3_stmt** d, const char** e) { (void)a;(void)b;(void)c;(void)d;(void)e; return 1; }
    static int sqlite3_step(sqlite3_stmt* a) { (void)a; return SQLITE_DONE; }
    static int sqlite3_finalize(sqlite3_stmt* a) { (void)a; return 0; }
    static int sqlite3_bind_int64(sqlite3_stmt* a, int b, int64_t c) { (void)a;(void)b;(void)c; return 0; }
    static int sqlite3_bind_text(sqlite3_stmt* a, int b, const char* c, int d, void(*e)(void*)) { (void)a;(void)b;(void)c;(void)d;(void)e; return 0; }
    static int64_t sqlite3_column_int64(sqlite3_stmt* a, int b) { (void)a;(void)b; return 0; }
    static int sqlite3_column_int(sqlite3_stmt* a, int b) { (void)a;(void)b; return 0; }
    static double sqlite3_column_double(sqlite3_stmt* a, int b) { (void)a;(void)b; return 0; }
    static const unsigned char* sqlite3_column_text(sqlite3_stmt* a, int b) { (void)a;(void)b; return (const unsigned char*)""; }
    static int sqlite3_column_count(sqlite3_stmt* a) { (void)a; return 0; }
    static int sqlite3_changes(sqlite3* a) { (void)a; return 0; }
    static void db_load_sqlite(void) {}
#endif

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

/* --- basic TCP sockets (host surface; HTTP lives in lib/http.te) --- */
static int64_t sock_listen(int64_t port) {
  sock_init();
#ifndef _WIN32
  signal(SIGPIPE, SIG_IGN);
#endif
  sock_t srv = socket(AF_INET, SOCK_STREAM, 0);
  if (srv == (sock_t)SOCK_ERR) { fprintf(stderr, "sock.listen: socket failed\n"); exit(1); }
  int yes = 1;
  setsockopt(srv, SOL_SOCKET, SO_REUSEADDR, (const char*)&yes, sizeof(yes));
  struct sockaddr_in addr;
  memset(&addr, 0, sizeof(addr));
  addr.sin_family = AF_INET;
  addr.sin_addr.s_addr = htonl(INADDR_ANY);
  addr.sin_port = htons((uint16_t)port);
  if (bind(srv, (struct sockaddr*)&addr, sizeof(addr)) == SOCK_ERR) {
    fprintf(stderr, "sock.listen: bind failed on :%lld\n", (long long)port); exit(1);
  }
  if (listen(srv, 64) == SOCK_ERR) {
    fprintf(stderr, "sock.listen: listen failed\n"); exit(1);
  }
  fprintf(stderr, "sock.listen on :%lld\n", (long long)port);
  return (int64_t)(intptr_t)srv;
}
static int64_t sock_accept(int64_t listen_fd) {
  sock_t srv = (sock_t)(intptr_t)listen_fd;
  sock_t cli = accept(srv, NULL, NULL);
  if (cli == (sock_t)SOCK_ERR) return INT64_C(-1);
  return (int64_t)(intptr_t)cli;
}
static char* sock_recv(int64_t fd) {
  sock_t s = (sock_t)(intptr_t)fd;
  /* short timeouts so a stalled client cannot hang the accept loop forever */
#ifdef _WIN32
  DWORD tv = 5000;
  setsockopt(s, SOL_SOCKET, SO_RCVTIMEO, (const char*)&tv, sizeof(tv));
  setsockopt(s, SOL_SOCKET, SO_SNDTIMEO, (const char*)&tv, sizeof(tv));
#else
  struct timeval tv;
  tv.tv_sec = 5; tv.tv_usec = 0;
  setsockopt(s, SOL_SOCKET, SO_RCVTIMEO, (const char*)&tv, sizeof(tv));
  setsockopt(s, SOL_SOCKET, SO_SNDTIMEO, (const char*)&tv, sizeof(tv));
#endif
  char buf[65536];
  int n = 0;
  /* read until end of HTTP headers (\r\n\r\n) or buffer full */
  while (n < (int)sizeof(buf) - 1) {
    int got = (int)recv(s, buf + n, sizeof(buf) - 1 - n, 0);
    if (got <= 0) break;
    n += got;
    buf[n] = 0;
    if (strstr(buf, "\r\n\r\n")) break;
  }
  if (n <= 0) { char* e = (char*)malloc(1); e[0]=0; return e; }
  buf[n] = 0;
  char* sep = strstr(buf, "\r\n\r\n");
  int content_length = 0;
  char* cl = strstr(buf, "Content-Length:");
  if (cl) sscanf(cl, "Content-Length: %d", &content_length);
  int header_length = sep ? (int)(sep - buf) + 4 : n;
  while (sep && n < header_length + content_length && n < (int)sizeof(buf) - 1) {
    int got = (int)recv(s, buf + n, sizeof(buf) - 1 - n, 0);
    if (got <= 0) break;
    n += got;
    buf[n] = 0;
  }
  char* out = (char*)malloc((size_t)n + 1);
  memcpy(out, buf, (size_t)n);
  out[n] = 0;
  return out;
}
static int64_t sock_send(int64_t fd, const char* data) {
  sock_t s = (sock_t)(intptr_t)fd;
  if (!data) data = "";
  int n = (int)strlen(data);
  int sent = 0;
  while (sent < n) {
    int k = (int)send(s, data + sent, (size_t)(n - sent), 0);
    if (k <= 0) break;
    sent += k;
  }
  return (int64_t)sent;
}
static int64_t sock_close(int64_t fd) {
  sock_t s = (sock_t)(intptr_t)fd;
#ifdef _WIN32
  shutdown(s, SD_BOTH);
#else
  shutdown(s, SHUT_RDWR);
#endif
  CLOSESOCK(s);
  return INT64_C(0);
}

typedef struct { int64_t *d; int64_t n; } List;

static List list_new(int64_t n) {
  List L; L.n = n; L.d = (int64_t*)malloc(sizeof(int64_t) * (n > 0 ? n : 1));
  return L;
}
static int64_t list_get(List L, int64_t i) {
  if (i < 0 || i >= L.n) {
    fprintf(stderr, "index out of bounds: index %lld len %lld\n",
            (long long)i, (long long)L.n);
    exit(1);
  }
  return L.d[i];
}
static int64_t list_len(List L) { return L.n; }
static List list_push(List L, int64_t value) {
    L.d = (int64_t*)realloc(L.d, sizeof(int64_t) * (size_t)(L.n + 1));
    L.d[L.n++] = value;
    return L;
}
static List list_concat(List a, List b) {
    List out = list_new(0);
    for (int64_t i = 0; i < a.n; i++) out = list_push(out, a.d[i]);
    for (int64_t i = 0; i < b.n; i++) out = list_push(out, b.d[i]);
    return out;
}

/* maps {K:V} — str keys; i64 or str values */
typedef struct { const char** k; int64_t* v; int64_t n; int64_t cap; } Map_str_i64;
typedef struct { const char** k; const char** v; int64_t n; int64_t cap; } Map_str_str;
static Map_str_i64 map_str_i64_new(void) { Map_str_i64 m = {NULL,NULL,0,0}; return m; }
static Map_str_str map_str_str_new(void) { Map_str_str m = {NULL,NULL,0,0}; return m; }
static int64_t map_str_i64_len(Map_str_i64 m) { return m.n; }
static int64_t map_str_str_len(Map_str_str m) { return m.n; }
static int64_t map_str_i64_get(Map_str_i64 m, const char* key) {
  if (!key) key = "";
  for (int64_t i = 0; i < m.n; i++) if (strcmp(m.k[i] ? m.k[i] : "", key) == 0) return m.v[i];
  return INT64_C(0);
}
static const char* map_str_str_get(Map_str_str m, const char* key) {
  if (!key) key = "";
  for (int64_t i = 0; i < m.n; i++) if (strcmp(m.k[i] ? m.k[i] : "", key) == 0) return m.v[i] ? m.v[i] : "";
  return "";
}
static int64_t map_str_i64_has(Map_str_i64 m, const char* key) {
  if (!key) key = "";
  for (int64_t i = 0; i < m.n; i++) if (strcmp(m.k[i] ? m.k[i] : "", key) == 0) return INT64_C(1);
  return INT64_C(0);
}
static int64_t map_str_str_has(Map_str_str m, const char* key) {
  if (!key) key = "";
  for (int64_t i = 0; i < m.n; i++) if (strcmp(m.k[i] ? m.k[i] : "", key) == 0) return INT64_C(1);
  return INT64_C(0);
}
static Map_str_i64 map_str_i64_put(Map_str_i64 m, const char* key, int64_t val) {
  if (!key) key = "";
  for (int64_t i = 0; i < m.n; i++) {
    if (strcmp(m.k[i] ? m.k[i] : "", key) == 0) { m.v[i] = val; return m; }
  }
  if (m.n >= m.cap) {
    m.cap = m.cap ? m.cap * 2 : 8;
    m.k = (const char**)realloc(m.k, sizeof(const char*) * (size_t)m.cap);
    m.v = (int64_t*)realloc(m.v, sizeof(int64_t) * (size_t)m.cap);
  }
  m.k[m.n] = key; m.v[m.n] = val; m.n++; return m;
}
static Map_str_str map_str_str_put(Map_str_str m, const char* key, const char* val) {
  if (!key) key = "";
  if (!val) val = "";
  for (int64_t i = 0; i < m.n; i++) {
    if (strcmp(m.k[i] ? m.k[i] : "", key) == 0) { m.v[i] = val; return m; }
  }
  if (m.n >= m.cap) {
    m.cap = m.cap ? m.cap * 2 : 8;
    m.k = (const char**)realloc(m.k, sizeof(const char*) * (size_t)m.cap);
    m.v = (const char**)realloc(m.v, sizeof(const char*) * (size_t)m.cap);
  }
  m.k[m.n] = key; m.v[m.n] = val; m.n++; return m;
}



typedef struct {
    int kind; /* 0 = integer, 1 = string */
    int64_t integer;
    const char* string;
} DbValue;

static sqlite3* terse_db = NULL;

static void db_fail(const char* operation, int code) {
    fprintf(stderr, "sqlite %s failed (%d)%s%s\n", operation, code,
        terse_db ? ": " : "", terse_db ? sqlite3_errmsg(terse_db) : "");
    exit(1);
}

static void db_bind(sqlite3_stmt* stmt, int index, DbValue value) {
    int code = value.kind == 1
        ? sqlite3_bind_text(stmt, index, value.string, -1, SQLITE_TRANSIENT)
        : sqlite3_bind_int64(stmt, index, value.integer);
    if (code != SQLITE_OK) db_fail("bind", code);
}

static sqlite3_stmt* db_prepare_query(const char* sql, int argc, DbValue* args) {
    sqlite3_stmt* stmt = NULL;
    int code = sqlite3_prepare_v2(terse_db, sql, -1, &stmt, NULL);
    if (code != SQLITE_OK) db_fail("prepare", code);
    for (int i = 0; i < argc; i++) db_bind(stmt, i + 1, args[i]);
    return stmt;
}

static const char* db_copy_text(const unsigned char* value) {
    if (!value) return "";
    size_t n = strlen((const char*)value);
    char* copy = (char*)malloc(n + 1);
    memcpy(copy, value, n + 1);
    return copy;
}

static int64_t db_connect(const char* url) {
    db_load_sqlite();
    int init_code = sqlite3_initialize();
    if (init_code != SQLITE_OK) db_fail("initialize", init_code);
    const char* path = url;
    if (strncmp(url, "sqlite3://", 10) == 0) path = url + 10;
    if (strncmp(path, "file/", 5) == 0) path += 5;
    if (terse_db) sqlite3_close(terse_db);
    int code = sqlite3_open(path, &terse_db);
    if (code != SQLITE_OK) db_fail("open", code);
    return 0;
}

static int64_t db_exec(const char* sql, int argc, DbValue* args) {
    sqlite3_stmt* stmt = NULL;
    int code = sqlite3_prepare_v2(terse_db, sql, -1, &stmt, NULL);
    if (code != SQLITE_OK) db_fail("prepare", code);
    for (int i = 0; i < argc; i++) db_bind(stmt, i + 1, args[i]);
    code = sqlite3_step(stmt);
    if (code != SQLITE_DONE) db_fail("execute", code);
    sqlite3_finalize(stmt);
    return sqlite3_changes(terse_db);
}

static List db_query(const char* sql, int argc, DbValue* args) {
    sqlite3_stmt* stmt = NULL;
    int code = sqlite3_prepare_v2(terse_db, sql, -1, &stmt, NULL);
    if (code != SQLITE_OK) db_fail("prepare", code);
    for (int i = 0; i < argc; i++) db_bind(stmt, i + 1, args[i]);
    List rows = list_new(0);
    while ((code = sqlite3_step(stmt)) == SQLITE_ROW) {
        if (sqlite3_column_count(stmt) == 0) break;
        rows.d = (int64_t*)realloc(rows.d, sizeof(int64_t) * (rows.n + 1));
        rows.d[rows.n++] = sqlite3_column_int64(stmt, 0);
    }
    if (code != SQLITE_DONE) db_fail("query", code);
    sqlite3_finalize(stmt);
    return rows;
}

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

static char* str_slice(const char* s, int64_t start, int64_t length) {
    int64_t size = str_len(s);
    if (start < 0) start = 0;
    if (start > size) start = size;
    if (length < 0) length = 0;
    if (length > size - start) length = size - start;
    char* result = (char*)malloc((size_t)length + 1);
    if (!result) { fprintf(stderr, "out of memory slicing string\n"); exit(1); }
    memcpy(result, s + start, (size_t)length);
    result[length] = 0;
    return result;
}

/* --- [str] lists --- */
typedef struct { const char **d; int64_t n; int64_t cap; } List_str;
static List_str list_new_str(int64_t n) {
  List_str L = {NULL, 0, n};
  if (n > 0) { L.d = (const char**)calloc((size_t)n, sizeof(const char*)); L.n = n; }
  return L;
}
static List_str list_push_str(List_str L, const char* v) {
  if (L.n >= L.cap) {
    L.cap = L.cap ? L.cap * 2 : 8;
    L.d = (const char**)realloc(L.d, sizeof(const char*) * (size_t)L.cap);
  }
  L.d[L.n++] = v ? v : "";
  return L;
}
static int64_t list_len_str(List_str L) { return L.n; }
static const char* list_get_str(List_str L, int64_t i) {
  if (i < 0 || i >= L.n) {
    fprintf(stderr, "index out of bounds: index %lld len %lld\n",
            (long long)i, (long long)L.n);
    exit(1);
  }
  return L.d[i] ? L.d[i] : "";
}

static List_str list_concat_str(List_str a, List_str b) {
  List_str out = list_new_str(0);
  for (int64_t i = 0; i < a.n; i++) out = list_push_str(out, a.d[i] ? a.d[i] : "");
  for (int64_t i = 0; i < b.n; i++) out = list_push_str(out, b.d[i] ? b.d[i] : "");
  return out;
}

/* Width-accurate numeric lists */
#define TERSE_DECL_LIST(Name, CType) \
typedef struct { CType *d; int64_t n; int64_t cap; } List_##Name; \
static List_##Name list_new_##Name(int64_t n) { \
  List_##Name L = {NULL, 0, n}; \
  if (n > 0) L.d = (CType*)calloc((size_t)n, sizeof(CType)); \
  return L; \
} \
static List_##Name list_push_##Name(List_##Name L, CType v) { \
  if (L.n >= L.cap) { L.cap = L.cap ? L.cap * 2 : 8; L.d = (CType*)realloc(L.d, (size_t)L.cap * sizeof(CType)); } \
  L.d[L.n++] = v; \
  return L; \
} \
static int64_t list_len_##Name(List_##Name L) { return L.n; } \
static CType list_get_##Name(List_##Name L, int64_t i) { \
  if (i < 0 || i >= L.n) { \
    fprintf(stderr, "index out of bounds: index %lld len %lld\n", (long long)i, (long long)L.n); \
    exit(1); } \
  return L.d[i]; \
} \
static List_##Name list_concat_##Name(List_##Name a, List_##Name b) { \
  List_##Name out = list_new_##Name(0); \
  for (int64_t i = 0; i < a.n; i++) out = list_push_##Name(out, a.d[i]); \
  for (int64_t i = 0; i < b.n; i++) out = list_push_##Name(out, b.d[i]); \
  return out; \
}

TERSE_DECL_LIST(i64, int64_t)
TERSE_DECL_LIST(i32, int32_t)
TERSE_DECL_LIST(i16, int16_t)
TERSE_DECL_LIST(i8, int8_t)
TERSE_DECL_LIST(u64, uint64_t)
TERSE_DECL_LIST(u32, uint32_t)
TERSE_DECL_LIST(u16, uint16_t)
TERSE_DECL_LIST(f64, double)
TERSE_DECL_LIST(bool, bool)
/* char is i8 surface */
typedef List_i8 List_char;
static List_char list_new_char(int64_t n) { return list_new_i8(n); }
static List_char list_push_char(List_char L, int8_t v) { return list_push_i8(L, v); }
static int64_t list_len_char(List_char L) { return list_len_i8(L); }
static int8_t list_get_char(List_char L, int64_t i) { return list_get_i8(L, i); }
static List_char list_concat_char(List_char a, List_char b) { return list_concat_i8(a, b); }




static List_str map_str_i64_keys(Map_str_i64 m) {
  List_str out = list_new_str(0);
  for (int64_t i = 0; i < m.n; i++) out = list_push_str(out, m.k[i] ? m.k[i] : "");
  return out;
}
static List_str map_str_str_keys(Map_str_str m) {
  List_str out = list_new_str(0);
  for (int64_t i = 0; i < m.n; i++) out = list_push_str(out, m.k[i] ? m.k[i] : "");
  return out;
}
static List map_str_i64_values(Map_str_i64 m) {
  List out = list_new(0);
  for (int64_t i = 0; i < m.n; i++) out = list_push(out, m.v[i]);
  return out;
}

/* --- std.str surface (terse names) --- */
static int64_t str_has(const char* s, const char* sub) {
  if (!s) s = ""; if (!sub) sub = "";
  return strstr(s, sub) != NULL ? INT64_C(1) : INT64_C(0);
}
static int64_t str_starts(const char* s, const char* prefix) {
  if (!s) s = ""; if (!prefix) prefix = "";
  size_t n = strlen(prefix);
  return strncmp(s, prefix, n) == 0 ? INT64_C(1) : INT64_C(0);
}
static int64_t str_ends(const char* s, const char* suffix) {
  if (!s) s = ""; if (!suffix) suffix = "";
  size_t ns = strlen(s), n = strlen(suffix);
  if (n > ns) return INT64_C(0);
  return strcmp(s + (ns - n), suffix) == 0 ? INT64_C(1) : INT64_C(0);
}

static char* str_up(const char* s) {
  if (!s) s = "";
  size_t n = strlen(s);
  char* r = (char*)malloc(n + 1);
  for (size_t i = 0; i < n; i++) {
    unsigned char c = (unsigned char)s[i];
    r[i] = (c >= 'a' && c <= 'z') ? (char)(c - 32) : (char)c;
  }
  r[n] = 0;
  return r;
}
static char* str_low(const char* s) {
  if (!s) s = "";
  size_t n = strlen(s);
  char* r = (char*)malloc(n + 1);
  for (size_t i = 0; i < n; i++) {
    unsigned char c = (unsigned char)s[i];
    r[i] = (c >= 'A' && c <= 'Z') ? (char)(c + 32) : (char)c;
  }
  r[n] = 0;
  return r;
}
static char* str_trim(const char* s) {
  if (!s) s = "";
  while (*s == ' ' || *s == '\t' || *s == '\n' || *s == '\r') s++;
  size_t n = strlen(s);
  while (n > 0 && (s[n-1] == ' ' || s[n-1] == '\t' || s[n-1] == '\n' || s[n-1] == '\r')) n--;
  char* r = (char*)malloc(n + 1);
  memcpy(r, s, n); r[n] = 0;
  return r;
}
static int64_t str_parse_i64(const char* s) {
  if (!s) return INT64_C(0);
  while (*s == ' ' || *s == '\t') s++;
  int neg = 0;
  if (*s == '-') { neg = 1; s++; }
  else if (*s == '+') s++;
  int64_t v = 0; int any = 0;
  while (*s >= '0' && *s <= '9') {
    any = 1;
    v = v * 10 + (*s - '0');
    s++;
  }
  if (!any) return INT64_C(0);
  return neg ? -v : v;
}
static List_str str_split(const char* s, const char* sep) {
  List_str out = list_new_str(0);
  if (!s) s = "";
  if (!sep || !sep[0]) {
    /* empty sep → each character as its own string */
    for (const char* p = s; *p; p++) {
      char* one = (char*)malloc(2); one[0] = *p; one[1] = 0;
      out = list_push_str(out, one);
    }
    return out;
  }
  size_t sepn = strlen(sep);
  const char* start = s;
  for (;;) {
    const char* found = strstr(start, sep);
    size_t len = found ? (size_t)(found - start) : strlen(start);
    char* part = (char*)malloc(len + 1);
    if (!part) { fprintf(stderr, "oom split\n"); exit(1); }
    memcpy(part, start, len); part[len] = 0;
    out = list_push_str(out, part);
    if (!found) break;
    start = found + sepn;
  }
  return out;
}
static char* str_join(List_str parts, const char* sep) {
  if (!sep) sep = "";
  size_t sepn = strlen(sep);
  size_t total = 1;
  for (int64_t i = 0; i < parts.n; i++) {
    const char* pi = (parts.d && parts.d[i]) ? parts.d[i] : "";
    total += strlen(pi);
    if (i + 1 < parts.n) total += sepn;
  }
  char* r = (char*)malloc(total);
  if (!r) { fprintf(stderr, "oom join\n"); exit(1); }
  size_t off = 0;
  for (int64_t i = 0; i < parts.n; i++) {
    if (i && sepn) { memcpy(r + off, sep, sepn); off += sepn; }
    const char* pi = (parts.d && parts.d[i]) ? parts.d[i] : "";
    size_t li = strlen(pi);
    memcpy(r + off, pi, li); off += li;
  }
  r[off] = 0;
  return r;
}


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
static void print_list_i64(List_i64 L) {
  _terse_did_print = 1;
  printf("[");
  for (int64_t i = 0; i < L.n; i++) {
    if (i) printf(", ");
    printf("%lld", (long long)L.d[i]);
  }
  printf("]\n");
}
static void print_list_i32(List_i32 L) {
  _terse_did_print = 1;
  printf("[");
  for (int64_t i = 0; i < L.n; i++) {
    if (i) printf(", ");
    printf("%d", (int)L.d[i]);
  }
  printf("]\n");
}
static void print_list_str(List_str L) {
  _terse_did_print = 1;
  printf("[");
  for (int64_t i = 0; i < L.n; i++) {
    if (i) printf(", ");
    printf("\"%s\"", L.d[i] ? L.d[i] : "");
  }
  printf("]\n");
}


static void print_i64(int64_t x) { _terse_did_print = 1; printf("%lld\n", (long long)x); }
static void print_bool(bool v) { _terse_did_print = 1; printf(v ? "true\n" : "false\n"); }
static void print_str(const char* s) { _terse_did_print = 1; printf("%s\n", s); }

/* -- std.tst assertion helpers (continue on failure; count via _tst_failures) -- */
static int64_t _tst_failures = 0;
static int64_t _tst_checks = 0;
static int64_t tst_eq_i64(int64_t got, int64_t expected, const char* file, int64_t line) {
  _tst_checks++;
  if (got != expected) {
    _tst_failures++;
    fprintf(stderr, "FAIL %s:%lld: expected %lld, got %lld\n",
            file ? file : "?", (long long)line, (long long)expected, (long long)got);
    return INT64_C(1);
  }
  return INT64_C(0);
}
static int64_t tst_eq_bool(bool got, bool expected, const char* file, int64_t line) {
  _tst_checks++;
  if (got != expected) {
    _tst_failures++;
    fprintf(stderr, "FAIL %s:%lld: expected %s, got %s\n",
            file ? file : "?", (long long)line,
            expected ? "true" : "false", got ? "true" : "false");
    return INT64_C(1);
  }
  return INT64_C(0);
}
static int64_t tst_eq_str(const char* got, const char* expected, const char* file, int64_t line) {
  _tst_checks++;
  const char* g = got ? got : "";
  const char* e = expected ? expected : "";
  if (strcmp(g, e) != 0) {
    _tst_failures++;
    fprintf(stderr, "FAIL %s:%lld: expected \"%s\", got \"%s\"\n",
            file ? file : "?", (long long)line, e, g);
    return INT64_C(1);
  }
  return INT64_C(0);
}
static int64_t tst_ne_i64(int64_t got, int64_t unexpected, const char* file, int64_t line) {
  _tst_checks++;
  if (got == unexpected) {
    _tst_failures++;
    fprintf(stderr, "FAIL %s:%lld: expected not %lld, got %lld\n",
            file ? file : "?", (long long)line, (long long)unexpected, (long long)got);
    return INT64_C(1);
  }
  return INT64_C(0);
}
static int64_t tst_ne_bool(bool got, bool unexpected, const char* file, int64_t line) {
  _tst_checks++;
  if (got == unexpected) {
    _tst_failures++;
    fprintf(stderr, "FAIL %s:%lld: expected not %s, got %s\n",
            file ? file : "?", (long long)line,
            unexpected ? "true" : "false", got ? "true" : "false");
    return INT64_C(1);
  }
  return INT64_C(0);
}
static int64_t tst_ne_str(const char* got, const char* unexpected, const char* file, int64_t line) {
  _tst_checks++;
  const char* g = got ? got : "";
  const char* u = unexpected ? unexpected : "";
  if (strcmp(g, u) == 0) {
    _tst_failures++;
    fprintf(stderr, "FAIL %s:%lld: expected not \"%s\", got \"%s\"\n",
            file ? file : "?", (long long)line, u, g);
    return INT64_C(1);
  }
  return INT64_C(0);
}
static int64_t tst_report(void) {
  /* Quiet on success: only print failures (and SKIP when implemented). */
  _terse_did_print = 1; /* suppress main's leftover numeric print */
  if (_tst_failures != 0) {
    fprintf(stderr, "FAILED %lld of %lld check(s)\n",
            (long long)_tst_failures, (long long)_tst_checks);
  }
  return _tst_failures;
}

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
static void json_field_prefix(char* b, size_t* o, size_t cap, int* first, const char* name) {
    *o += (size_t)snprintf(b + *o, cap - *o, "%s\"%s\":", *first ? "" : ",", name);
    *first = 0;
}
static void json_append_i64(char* b, size_t* o, size_t cap, int* first, const char* name, int64_t value) {
    json_field_prefix(b, o, cap, first, name);
    *o += (size_t)snprintf(b + *o, cap - *o, "%lld", (long long)value);
}
static void json_append_bool(char* b, size_t* o, size_t cap, int* first, const char* name, bool value) {
    json_field_prefix(b, o, cap, first, name);
    *o += (size_t)snprintf(b + *o, cap - *o, "%s", value ? "true" : "false");
}
static void json_append_f64(char* b, size_t* o, size_t cap, int* first, const char* name, double value) {
    json_field_prefix(b, o, cap, first, name);
    *o += (size_t)snprintf(b + *o, cap - *o, "%g", value);
}
static void json_append_str(char* b, size_t* o, size_t cap, int* first, const char* name, const char* value) {
    json_field_prefix(b, o, cap, first, name);
    *o += (size_t)snprintf(b + *o, cap - *o, "\"%s\"", value ? value : "");
}

static const char* env_get(const char* k) {
  const char* v = getenv(k);
  return v ? v : "";
}
#ifndef _WIN32
int setenv(const char *name, const char *value, int overwrite);
#endif
static int64_t env_set(const char* k, const char* v) {
  if (!k) return INT64_C(-1);
#ifdef _WIN32
  /* _putenv_s is preferred on Windows */
  return (_putenv_s(k, v ? v : "") == 0) ? INT64_C(0) : INT64_C(-1);
#else
  return (setenv(k, v ? v : "", 1) == 0) ? INT64_C(0) : INT64_C(-1);
#endif
}

static int terse_argc = 0;
static char** terse_argv = NULL;

static const char* terse_arg(int64_t index) {
    if (index < 0 || index >= terse_argc) return "";
    return terse_argv[index];
}

static int64_t terse_gcc_compile(const char* source, const char* output) {
    /* -O0: large statement-expr C can crash Apple clang at -O2 */
    char* args[24];
    int count = 0;
    const char* cc = getenv("CC");
    if (!cc || !cc[0]) cc = "gcc";
    args[count++] = (char*)cc;
    args[count++] = "-O0";
    args[count++] = "-std=c11";
    args[count++] = "-Wno-unused-function";
    args[count++] = "-Wno-unused-parameter";
    args[count++] = "-Wno-unused-value";
    args[count++] = "-Wno-parentheses";
    args[count++] = (char*)source;
#ifdef _WIN32
    args[count++] = "-lws2_32";
#endif
    args[count++] = "-o";
    args[count++] = (char*)output;
    args[count] = NULL;
#ifdef _WIN32
    return (int64_t)_spawnvp(_P_WAIT, cc, (const char* const*)args);
#else
    pid_t child = fork();
    if (child < 0) {
        perror("tc: fork");
        return 1;
    }
    if (child == 0) {
        execvp(cc, args);
        perror("tc: exec CC");
        _exit(127);
    }
    int status = 0;
    if (waitpid(child, &status, 0) < 0) {
        perror("tc: wait for CC");
        return 1;
    }
    if (WIFEXITED(status)) return WEXITSTATUS(status);
    if (WIFSIGNALED(status)) return 128 + WTERMSIG(status);
    return 1;
#endif
}

static void fs_io_fail(const char* operation, const char* path) {
    fprintf(stderr, "file %s failed for '%s': %s\n", operation, path, strerror(errno));
    exit(1);
}

static char* fs_read_text(const char* path) {
    FILE* file = fopen(path, "rb");
    if (!file) fs_io_fail("read", path);
    if (fseek(file, 0, SEEK_END) != 0) fs_io_fail("read", path);
    long size = ftell(file);
    if (size < 0 || fseek(file, 0, SEEK_SET) != 0) fs_io_fail("read", path);
    char* text = (char*)malloc((size_t)size + 1);
    if (!text) { fclose(file); fprintf(stderr, "out of memory reading '%s'\n", path); exit(1); }
    size_t read_size = fread(text, 1, (size_t)size, file);
    if (ferror(file)) fs_io_fail("read", path);
    if (fclose(file) != 0) fs_io_fail("read", path);
    text[read_size] = 0;
    return text;
}

static int64_t fs_write_text(const char* path, const char* text) {
    FILE* file = fopen(path, "wb");
    if (!file) fs_io_fail("write", path);
    size_t size = strlen(text);
    size_t written = fwrite(text, 1, size, file);
    if (written != size || fclose(file) != 0) fs_io_fail("write", path);
    return (int64_t)written;
}

static int64_t fs_append_text(const char* path, const char* text) {
    FILE* file = fopen(path, "ab");
    if (!file) fs_io_fail("append", path);
    size_t size = text ? strlen(text) : 0;
    size_t written = size ? fwrite(text, 1, size, file) : 0;
    if (written != size || fclose(file) != 0) fs_io_fail("append", path);
    return (int64_t)written;
}

/* -- minimal HTTP/1.1 server -- */
typedef const char* (*route_fn)(const char* method, const char* path, const char* body);

static void http_send(sock_t fd, int code, const char* ctype, const char* body) {
  char hdr[512];
  int blen = body ? (int)strlen(body) : 0;
  const char* msg =
    code==200 ? "OK" : code==201 ? "Created" : code==204 ? "No Content" :
    code==400 ? "Bad Request" : code==401 ? "Unauthorized" : code==403 ? "Forbidden" :
    code==404 ? "Not Found" : code==405 ? "Method Not Allowed" : code==409 ? "Conflict" :
    code==500 ? "Internal Server Error" : "Error";
  int n = snprintf(hdr, sizeof(hdr),
    "HTTP/1.1 %d %s\r\nContent-Type: %s\r\nContent-Length: %d\r\nConnection: close\r\n\r\n",
    code, msg, ctype, blen);
  send(fd, hdr, n, 0);
  if (body && blen) send(fd, body, blen, 0);
}

/* Handler returning status + body + content-type (for http.serve(port, fn)) */
typedef struct { int64_t status; const char* body; const char* ctype; } HttpResC;
typedef HttpResC (*http_res_fn)(const char* method, const char* path, const char* query, const char* body);

static void http_serve_fn(int64_t port, http_res_fn handler) {
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
    char* q = strchr(path, '?');
    char query[2048] = {0};
    if (q) { strncpy(query, q + 1, sizeof(query)-1); *q = 0; }
    char* sep = strstr(buf, "\r\n\r\n");
    int content_length = 0;
    char* content_header = strstr(buf, "Content-Length:");
    if (content_header) sscanf(content_header, "Content-Length: %d", &content_length);
    int header_length = sep ? (int)(sep - buf) + 4 : n;
    while (sep && n < header_length + content_length && n < (int)sizeof(buf) - 1) {
      int received = (int)recv(cli, buf + n, sizeof(buf) - 1 - n, 0);
      if (received <= 0) break;
      n += received;
      buf[n] = 0;
    }
    const char* body = "";
    if (sep) body = sep + 4;
    HttpResC resp = handler(method, path, query, body);
    int code = (int)resp.status;
    const char* ctype = resp.ctype ? resp.ctype : "text/plain";
    const char* rbody = resp.body ? resp.body : "";
    http_send(cli, code, ctype, rbody);
    CLOSESOCK(cli);
  }
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
    char* sep = strstr(buf, "\r\n\r\n");
        int content_length = 0;
        char* content_header = strstr(buf, "Content-Length:");
        if (content_header) sscanf(content_header, "Content-Length: %d", &content_length);
        int header_length = sep ? (int)(sep - buf) + 4 : n;
        while (sep && n < header_length + content_length && n < (int)sizeof(buf) - 1) {
            int received = (int)recv(cli, buf + n, sizeof(buf) - 1 - n, 0);
            if (received <= 0) break;
            n += received;
            buf[n] = 0;
        }
        const char* body = "";
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
    def __init__(self, source_path=None):
        self.lines = []
        self.indent = 0
        self.lam_n = 0
        self.extra = []
        self.known = {}
        self.tmp = 0
        self.env = {}
        self.source_path = source_path or "?"
        self.route_handlers = []  # generated C funcs for routes
        self.record_field_types = {}
        self.method_names = {}
        self.method_returns = {}
        self.interface_methods = {}
        self.interface_method_returns = {}
        self.interface_helpers = {}
        self.enum_values = {}  # enum name -> {variant: value}
        self.func_param_types = {}
        self.func_return_types = {}

    def emit(self, s=""):
        self.lines.append("  " * self.indent + s)

    def zero_value(self, ty):
        """C rvalue matching ty — used after return inside GNU statement exprs."""
        if ty == 'str':
            return '""'
        if ty == 'bool':
            return 'false'
        if ty in ('list_str', 'List_str'):
            return '(List_str){NULL,0,0}'
        if ty in ('List', 'list', 'list_i64'):
            return '(List_i64){NULL,0,0}'
        if isinstance(ty, str) and ty.startswith('list_'):
            return f'(List_{ty[5:]}){{NULL,0,0}}'
        if ty == 'map_str_i64':
            return '(Map_str_i64){NULL,NULL,0,0}'
        if ty == 'map_str_str':
            return '(Map_str_str){NULL,NULL,0,0}'
        if isinstance(ty, str) and ty.startswith('map_'):
            cname = 'Map_' + '_'.join(ty.split('_')[1:])
            return f'({cname}){{NULL,NULL,0,0}}'
        if ty in getattr(self, 'record_field_types', {}) or ty in getattr(self, 'enum_values', {}):
            return f'({self.c_type(ty)}){{0}}'
        return 'INT64_C(0)'

    def tst_where(self, e=None):
        path = self.source_path.replace("\\", "/").replace('"', "")
        line = (getattr(e, "line", 0) or 0) if e is not None else 0
        return f'"{path}", INT64_C({line})'

    def fresh(self):
        self.tmp += 1
        return f"_t{self.tmp}"

    def db_args(self, args):
        if not args:
            return "0, NULL"
        values = []
        for arg in args:
            code, typ = self.gen_expr(arg)
            if typ == 'str':
                values.append(f"{{1, 0, {code}}}")
            else:
                values.append(f"{{0, {code}, NULL}}")
        return f"{len(values)}, (DbValue[]){{{', '.join(values)}}}"

    def type_name(self, typ):
        if typ is None:
            return 'i64'
        if typ.name == 'list' and typ.args:
            inner = self.type_name(typ.args[0])
            if inner == 'str':
                return 'list_str'
            return f"list_{inner}"
        if typ.name == 'map' and len(typ.args) >= 2:
            return f"map_{self.type_name(typ.args[0])}_{self.type_name(typ.args[1])}"
        return typ.name

    def typed_db_code(self, rec):
        name = rec.name
        fields = []
        for index, (field_name, field_type) in enumerate(rec.fields):
            typ = self.type_name(field_type)
            if typ == 'str':
                value = f"db_copy_text(sqlite3_column_text(stmt, {index}))"
            elif typ == 'bool':
                value = f"(sqlite3_column_int(stmt, {index}) != 0)"
            elif typ == 'f64':
                value = f"sqlite3_column_double(stmt, {index})"
            elif typ.startswith('list_'):
                value = f"({self.c_type(typ)}){{NULL, 0, 0}}"
            else:
                value = f"({self.c_type(typ)})sqlite3_column_int64(stmt, {index})"
            fields.append(f"        row.{field_name} = {value};")
        body = "\n".join(fields)
        return f'''static List_{name} list_new_{name}(int64_t n) {{
    List_{name} L = {{NULL, 0, n}};
    if (n > 0) {{ L.d = ({name}*)calloc((size_t)n, sizeof({name})); L.n = n; }}
    return L;
}}
static List_{name} list_push_{name}(List_{name} L, {name} value) {{
    if (L.n == L.cap) {{
        L.cap = L.cap ? L.cap * 2 : 4;
        L.d = ({name}*)realloc(L.d, sizeof({name}) * (size_t)L.cap);
    }}
    L.d[L.n++] = value;
    return L;
}}
static int64_t list_len_{name}(List_{name} L) {{ return L.n; }}
static {name} list_get_{name}(List_{name} L, int64_t i) {{
    if (i < 0 || i >= L.n) {{ fprintf(stderr, "index out of bounds\\n"); exit(1); }}
    return L.d[i];
}}
static List_{name} db_query_{name}(const char* sql, int argc, DbValue* args) {{
    sqlite3_stmt* stmt = db_prepare_query(sql, argc, args);
    List_{name} rows = {{NULL, 0, 0}};
    int code;
    while ((code = sqlite3_step(stmt)) == SQLITE_ROW) {{
        {name} row = {{0}};
{body}
        rows = list_push_{name}(rows, row);
    }}
    if (code != SQLITE_DONE) db_fail("query", code);
    sqlite3_finalize(stmt);
    return rows;
}}
'''

    def record_print_code(self, rec):
        values = []
        for field_name, field_type in rec.fields:
            typ = self.type_name(field_type)
            value = f"row.{field_name}"
            if typ == 'str':
                values.append(f'printf("%s", {value})')
            elif typ == 'bool':
                values.append(f'printf("%s", {value} ? "true" : "false")')
            elif typ == 'f64':
                values.append(f'printf("%g", {value})')
            elif typ.startswith('list_'):
                values.append('printf("<list>")')
            else:
                values.append(f'printf("%lld", (long long){value})')
        body = ', printf(", "), '.join(values)
        return f'''static void print_{rec.name}({rec.name} row) {{
    _terse_did_print = 1;
    printf("{{"); {body}; printf("}}\\n");
}}
'''

    def record_json_code(self, rec):
        fields = []
        for field_name, field_type in rec.fields:
            typ = self.type_name(field_type)
            value = f"L.d[i].{field_name}"
            if typ == 'str':
                fields.append(f'json_append_str(b, &o, cap, &first, "{field_name}", {value})')
            elif typ == 'bool':
                fields.append(f'json_append_bool(b, &o, cap, &first, "{field_name}", {value})')
            elif typ == 'f64':
                fields.append(f'json_append_f64(b, &o, cap, &first, "{field_name}", {value})')
            elif typ.startswith('list_'):
                fields.append(f'json_append_str(b, &o, cap, &first, "{field_name}", "<list>")')
            else:
                fields.append(f'json_append_i64(b, &o, cap, &first, "{field_name}", {value})')
        body = "; ".join(fields)
        return f'''static char* json_list_{rec.name}(List_{rec.name} L) {{
    size_t cap = 256 + L.n * 256;
    char* b = (char*)malloc(cap);
    size_t o = 0;
    b[o++] = '[';
    for (int64_t i = 0; i < L.n; i++) {{
        if (i) b[o++] = ',';
        b[o++] = '{{'; int first = 1; {body}; b[o++] = '}}';
    }}
    b[o++] = ']'; b[o] = 0;
    return b;
}}
'''

    def c_type(self, t):
        if isinstance(t, str) and t.startswith('fn:'):
            # fn:Arg1,Arg2>Ret  →  Ret(*)(Arg1, Arg2)
            try:
                mid, ret = t[3:].rsplit('>', 1)
                args = [a for a in mid.split(',') if a]
                if args:
                    return f"{self.c_type(ret)}(*)({', '.join(self.c_type(a) for a in args)})"
                return f"{self.c_type(ret)}(*)(void)"
            except ValueError:
                return 'void*'
        if t.startswith('list_'):
            inner = t[5:]
            if inner == 'int':
                inner = 'i64'
            if inner == 'str':
                return 'List_str'
            # width + record lists all use List_<inner>
            return f"List_{inner}"
        if t.startswith('map_'):
            # map_str_i64 → Map_str_i64
            return 'Map_' + t[4:]
        return {'fn':'void*','str':'const char*','list':'List_i64','List':'List_i64','i64':'int64_t','i32':'int32_t','i16':'int16_t','i8':'int8_t','char':'int8_t','u64':'uint64_t','u32':'uint32_t','u16':'uint16_t','bool':'bool','f64':'double','f32':'float','float':'float','double':'double'}.get(t, t)

    def expr_type(self, e) -> str:
        if isinstance(e, StrLit):
            return 'str'
        if isinstance(e, IntLit):
            return 'i64'
        if isinstance(e, FloatLit):
            return 'f64'
        if isinstance(e, BoolLit):
            return 'bool'
        if isinstance(e, ListLit):
            if e.items:
                return 'list_' + self.expr_type(e.items[0]) if self.expr_type(e.items[0]) != 'i64' else 'list'
            return 'list'
        if isinstance(e, Call) and isinstance(e.func, Var):
            n = e.func.name
            if n in ('has', 'starts', 'ends'): return 'bool'
            if n in ('trim', 'join', 'substr'): return 'str'
            if n == 'split': return 'list_str'
            if n == 'parse': return 'i64'
        if isinstance(e, Var):
            return self.env.get(e.name, 'i64')
        if isinstance(e, Call) and isinstance(e.func, Member) and isinstance(e.func.obj, Var) and e.func.obj.name in self.enum_values:
            return e.func.obj.name
        if isinstance(e, Call) and isinstance(e.func, Var):
            return self.func_return_types.get(e.func.name, 'i64')
        if isinstance(e, RecordLit):
            return e.ctor.name if isinstance(e.ctor, Var) else 'record'
        if isinstance(e, MapLit):
            if not e.entries:
                return 'map_str_i64'
            # rough: check value side
            return 'map_str_i64'
        if isinstance(e, Member):
            if isinstance(e.obj, Var) and e.obj.name in self.enum_values:
                return e.obj.name
            base_type = self.expr_type(e.obj)
            if base_type in ('List', 'list') or (isinstance(base_type, str) and base_type.startswith('list_')):
                if e.field in ('size', 'len'):
                    return 'i64'
            return self.record_field_types.get(base_type, {}).get(e.field, 'i64')
        return 'i64'


    def gen_loop_body(self, e) -> str:
        """Emit loop body as C statements so break/continue bind to the enclosing while/for."""
        if isinstance(e, JumpExpr):
            if e.kind == 'brk':
                return 'break;'
            return 'continue;'
        if isinstance(e, Block):
            parts = []
            for st in e.stmts:
                parts.append(self.gen_loop_body(st))
            return ' '.join(parts)
        if isinstance(e, IfExpr):
            c, _ = self.gen_expr(e.cond)
            t = self.gen_loop_body(e.then)
            f = self.gen_loop_body(e.els) if e.els is not None else ''
            if f:
                return f"if ({c}) {{ {t} }} else {{ {f} }}"
            return f"if ({c}) {{ {t} }}"
        if isinstance(e, RetExpr):
            if e.value is not None:
                v, _ = self.gen_expr(e.value)
                return f"return {v};"
            return "return INT64_C(0);"
        if isinstance(e, LetExpr):
            # Blocks desugar to LetExpr("_", stmt, rest) — emit as statements
            if e.name == "_":
                head = self.gen_loop_body(e.value)
                if e.body is not None:
                    return head + ' ' + self.gen_loop_body(e.body)
                return head
            expected = self.type_name(e.typ) if e.typ is not None else None
            v, vt = self.gen_expr(e.value, expected)
            if e.typ is not None:
                vt = self.type_name(e.typ)
            # Empty typed lists must use typed list_new_* even if inference missed
            if expected and expected.startswith('list_'):
                elem = expected[5:]
                if elem == 'int':
                    elem = 'i64'
                if 'list_new(' in v and 'list_new_' not in v:
                    v = f"({{ List_{elem} _le = list_new_{elem}(0); _le; }})"
                    vt = expected if expected != 'list_int' else 'list_i64'
            decl = f"{self.c_type(vt)} {e.name} = {v};"
            self.env[e.name] = vt
            if e.body is not None:
                return decl + ' ' + self.gen_loop_body(e.body)
            return decl
        # Default: expression statement
        code, _ = self.gen_expr(e)
        return f"(void)({code});"

    def gen_expr(self, e, expected_type=None) -> Tuple[str, str]:
        if isinstance(e, IntLit):
            if expected_type == 'f64':
                return f"((double){e.value})", "f64"
            if expected_type in ('i32', 'i16', 'i8', 'u32', 'u16', 'char'):
                return f"(({self.c_type(expected_type)})INT64_C({e.value}))", expected_type
            return f"INT64_C({e.value})", "i64"
        if isinstance(e, FloatLit):
            return f"((double){e.value})", "f64"
        if isinstance(e, BoolLit):
            return ("true" if e.value else "false"), "bool"
        if isinstance(e, StrLit):
            s = e.value.replace('\\','\\\\').replace('"','\\"').replace('\r','\\r').replace('\n','\\n').replace('\t','\\t')
            return f'"{s}"', "str"
        if isinstance(e, RecordLit):
            rec_name = e.ctor.name if isinstance(e.ctor, Var) else 'record'
            parts = []
            for name, val in e.fields:
                expected_type = self.record_field_types.get(rec_name, {}).get(name)
                v, _ = self.gen_expr(val, expected_type)
                parts.append(f".{name} = {v}")
            return f"(({rec_name}){{ {', '.join(parts)} }})", rec_name
        if isinstance(e, Var):
            if e.name in self.known:
                return f"(void*){self.known[e.name]}", "fn"
            if e.name in self.env:
                return e.name, self.env[e.name]
            # top-level fix constant
            for c in getattr(self, 'const_decls', []) or []:
                if c.name == e.name:
                    tn = self.env.get(c.name, 'i64')
                    return e.name, tn
            # Last resort — still emit (legacy); prefer typechecker fatal above
            return e.name, self.env.get(e.name, "i64")
        if isinstance(e, Member):
            # Enum variant: Colour.Green (tag-only) or base for Option.Some(...)
            if isinstance(e.obj, Var) and e.obj.name in self.enum_values:
                variants = self.enum_values[e.obj.name]
                if e.field in variants:
                    tag, ftypes = variants[e.field]
                    if not ftypes:
                        if self.enum_has_data.get(e.obj.name):
                            return f"(({e.obj.name}){{ .tag = INT64_C({tag}) }})", e.obj.name
                        return f"INT64_C({tag})", e.obj.name
                    # data variant used without call — treat as incomplete; still emit tag shell
                    return f"(({e.obj.name}){{ .tag = INT64_C({tag}) }})", e.obj.name
            base, btype = self.gen_expr(e.obj)
            if btype in self.interface_methods:
                ret_type = self.interface_method_returns.get((btype, e.field), 'i64')
                return f"(({base}).{e.field})", btype
            # List .size / .len
            if btype in ('List', 'list') or (isinstance(btype, str) and btype.startswith('list_')):
                if e.field in ('size', 'len'):
                    if btype.startswith('list_'):
                        return f"list_len_{btype[5:]}({base})", "i64"
                    return f"list_len_i64({base})", "i64"
            field_type = self.record_field_types.get(btype, {}).get(e.field, 'i64')
            return f"(({base}).{e.field})", field_type
        if isinstance(e, Binary):
            # env("KEY") = value  →  env_set("KEY", value)
            if e.op == '=' and isinstance(e.left, Call) and isinstance(e.left.func, Var) and e.left.func.name == 'env' and e.left.args:
                key_c, _ = self.gen_expr(e.left.args[0], 'str')
                val_c, _ = self.gen_expr(e.right, 'str')
                return f"env_set({key_c}, {val_c})", "i64"
            l, lt = self.gen_expr(e.left)
            # propagate list element type on = and + so [20,30] stays List_i32
            exp_r = None
            if e.op in ('=', '+') and isinstance(lt, str) and lt.startswith('list_'):
                exp_r = lt
            elif e.op == '=':
                exp_r = lt
            r, rt = self.gen_expr(e.right, exp_r)
            if e.op == '=':
                # Map update: m[k] = v  →  m = map_put(m, k, v)
                if isinstance(e.left, Index):
                    coll_e = e.left.coll
                    # need map type of collection
                    ct = self.expr_type(coll_e) if not isinstance(coll_e, Var) else self.env.get(coll_e.name, self.expr_type(coll_e))
                    if isinstance(coll_e, Var):
                        ct = self.env.get(coll_e.name, ct)
                    if isinstance(ct, str) and ct.startswith('map_'):
                        parts = ct.split('_')
                        kty, vty = parts[1], '_'.join(parts[2:])
                        kc, _ = self.gen_expr(e.left.idx)
                        vc, _ = self.gen_expr(e.right, 'str' if vty == 'str' else 'i64')
                        base, _ = self.gen_expr(coll_e)
                        if isinstance(coll_e, Var):
                            return f"({coll_e.name} = map_{kty}_{vty}_put({base}, {kc}, {vc}))", ct
                        return f"map_{kty}_{vty}_put({base}, {kc}, {vc})", ct
                return f"({l} = {r})", lt
            if e.op == '+':
                # [str] + [str]  or  [str] + str (append one)
                if lt == 'list_str' and rt == 'list_str':
                    return f"list_concat_str({l}, {r})", "list_str"
                if lt == 'list_str' and rt == 'str':
                    return f"list_push_str({l}, {r})", "list_str"
                if isinstance(lt, str) and lt.startswith('list_') and lt == rt:
                    elem = lt[5:]
                    return f"list_concat_{elem}({l}, {r})", lt
                if isinstance(lt, str) and lt.startswith('list_') and rt == lt[5:]:
                    elem = lt[5:]
                    return f"list_push_{elem}({l}, {r})", lt
                if isinstance(lt, str) and lt.startswith('list_') and rt == 'i64':
                    elem = lt[5:]
                    return f"list_push_{elem}({l}, ({self.c_type(elem)})({r}))", lt
                if lt in ('List', 'list', 'list_i64') and rt in ('List', 'list', 'list_i64'):
                    return f"list_concat_i64({l}, {r})", "list_i64"
                if lt in ('List', 'list', 'list_i64') and rt == 'i64':
                    return f"list_push_i64({l}, {r})", "list_i64"
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
            if e.op in ('==', '!=') and (lt == 'str' or rt == 'str'):
                cmp = f"(strcmp(({l}) ? ({l}) : \"\", ({r}) ? ({r}) : \"\") == 0)"
                if e.op == '!=':
                    cmp = f"(!{cmp})"
                return cmp, "bool"
            return f"({l} {e.op} {r})", ("bool" if e.op in ('==','!=','<','>','<=','>=','&&','||') else "i64")
        if isinstance(e, Unary):
            x, _ = self.gen_expr(e.expr)
            return f"({e.op}{x})", "i64"
        if isinstance(e, JumpExpr):
            if e.kind == 'brk':
                return "({ break; INT64_C(0); })", "i64"
            return "({ continue; INT64_C(0); })", "i64"
        if isinstance(e, RetExpr):
            if e.value is not None:
                v, vt = self.gen_expr(e.value)
                return f"({{ return {v}; {self.zero_value(vt)}; }})", vt
            return "({ return INT64_C(0); INT64_C(0); })", "i64"
        if isinstance(e, ListLit):
            n = len(e.items)
            tmp = self.fresh()
            element_type = None
            if expected_type and expected_type.startswith('list_'):
                element_type = expected_type[5:]
            elif e.items:
                element_type = self.expr_type(e.items[0])
            width_elems = ('i64', 'i32', 'i16', 'i8', 'u64', 'u32', 'u16', 'f64', 'bool', 'char', 'int')
            if element_type == 'int':
                element_type = 'i64'
            if element_type == 'str' or expected_type == 'list_str':
                parts = [f"List_str {tmp} = list_new_str({n})"]
                for i, item in enumerate(e.items):
                    value, _ = self.gen_expr(item, 'str')
                    parts.append(f"{tmp}.d[{i}] = {value}")
                parts.append(tmp)
                return "({ " + "; ".join(parts) + "; })", "list_str"
            if element_type and (
                element_type in width_elems
                or element_type in self.record_field_types
                or (expected_type and expected_type.startswith('list_'))
            ):
                et = element_type
                if expected_type and expected_type.startswith('list_'):
                    et = expected_type[5:]
                    if et == 'int':
                        et = 'i64'
                parts = [f"List_{et} {tmp} = list_new_{et}({n})"]
                for i, item in enumerate(e.items):
                    value, value_type = self.gen_expr(item, et)
                    # narrow int literals into smaller widths
                    if et in ('i32', 'i16', 'i8', 'u32', 'u16', 'char', 'f64') and value_type == 'i64':
                        value = f"({self.c_type(et)})({value})"
                    parts.append(f"{tmp}.d[{i}] = {value}")
                if n:
                    parts.append(f"{tmp}.n = {n}")
                parts.append(tmp)
                return "({ " + "; ".join(parts) + "; })", f"list_{et}"
            # Default unannotated lists are [i64]
            parts = [f"List_i64 {tmp} = list_new_i64({n})"]
            for i, it in enumerate(e.items):
                v, _ = self.gen_expr(it)
                parts.append(f"{tmp}.d[{i}] = {v}")
            if n:
                parts.append(f"{tmp}.n = {n}")
            parts.append(tmp)
            return "({ " + "; ".join(parts) + "; })", "list_i64"
        if isinstance(e, MapLit):
            mt = expected_type if expected_type and expected_type.startswith('map_') else None
            if mt is None and e.entries:
                # infer from first value
                _, vt = self.gen_expr(e.entries[0][1])
                mt = f"map_str_{vt}" if vt in ('i64', 'str') else 'map_str_i64'
            if mt is None:
                mt = 'map_str_i64'
            # mt like map_str_i64
            parts = mt.split('_')  # map, str, i64 or map, str, str
            if len(parts) < 3:
                mt = 'map_str_i64'; parts = ['map', 'str', 'i64']
            kty, vty = parts[1], '_'.join(parts[2:])
            fn_new = f"map_{kty}_{vty}_new"
            fn_put = f"map_{kty}_{vty}_put"
            tmp = self.fresh()
            ctype = self.c_type(mt)
            lines = [f"{ctype} {tmp} = {fn_new}()"]
            for k, v in e.entries:
                kc, _ = self.gen_expr(k)
                vc, _ = self.gen_expr(v, vty if vty != 'str' else 'str')
                lines.append(f"{tmp} = {fn_put}({tmp}, {kc}, {vc})")
            lines.append(tmp)
            return "({ " + "; ".join(lines) + "; })", mt
        if isinstance(e, Index):
            c, ct = self.gen_expr(e.coll)
            i, _ = self.gen_expr(e.idx)
            if ct == 'str':
                return f"((int64_t)((unsigned char){c}[{i}]))", "i64"
            if ct.startswith('map_'):
                parts = ct.split('_')
                kty, vty = parts[1], '_'.join(parts[2:])
                ret = 'str' if vty == 'str' else 'i64'
                return f"map_{kty}_{vty}_get({c}, {i})", ret
            if ct.startswith('list_'):
                record_name = ct[5:]
                if record_name == 'int':
                    record_name = 'i64'
                if record_name == 'str':
                    return f"list_get_str({c}, {i})", "str"
                return f"list_get_{record_name}({c}, {i})", record_name if record_name not in ('i64',) else 'i64'
            if ct in ('List', 'list', 'List_i64'):
                return f"list_get_i64({c}, {i})", "i64"
            if ct.startswith('map_') or ct == 'Map':
                return f"map_str_i64_get({c}, {i})", "i64"
            # last resort: treat as [i64]
            return f"list_get_i64({c}, {i})", "i64"
        if isinstance(e, Call) and isinstance(e.func, Member) and isinstance(e.func.obj, Var) and e.func.obj.name in self.enum_values:
            ename = e.func.obj.name
            vname = e.func.field
            variants = self.enum_values[ename]
            if vname in variants:
                tag, ftypes = variants[vname]
                parts = [f".tag = INT64_C({tag})"]
                for i, arg in enumerate(e.args):
                    expected = ftypes[i] if i < len(ftypes) else None
                    ac, at = self.gen_expr(arg, expected)
                    parts.append(f".u.{vname}.v{i} = {ac}")
                return f"(({ename}){{ {', '.join(parts)} }})", ename
        if isinstance(e, Call):
            # builtins
            if isinstance(e.func, Var) and e.func.name == 'push':
                collection, collection_type = self.gen_expr(e.args[0])
                value, _ = self.gen_expr(e.args[1])
                if collection_type.startswith('list_'):
                    item_type = collection_type[5:]
                    return f"list_push_{item_type}({collection}, {value})", collection_type
                return f"list_push_i64({collection}, {value})", 'list_i64'
            if isinstance(e.func, Var) and e.func.name == 'fmt':
                # fmt(a, b, ...) — concatenate with auto-stringify (minimal format helper)
                if not e.args:
                    return '""', 'str'
                parts = []
                for a in e.args:
                    code, t = self.gen_expr(a)
                    if t == 'str':
                        parts.append(code)
                    elif t == 'bool':
                        parts.append(f'str_from_bool({code})')
                    elif t in ('f32', 'float', 'f64', 'double'):
                        parts.append(f'str_from_i64((int64_t)({code}))')  # coarse; prefer i64 path
                    else:
                        parts.append(f'str_from_i64((int64_t)({code}))')
                expr = parts[0]
                for p2 in parts[1:]:
                    expr = f'str_concat({expr}, {p2})'
                return expr, 'str'
            if isinstance(e.func, Var) and e.func.name == 'pr':
                a, at = self.gen_expr(e.args[0])
                if at == 'str':
                    return f"(print_str({a}), INT64_C(0))", "i64"
                if at in ('list', 'List', 'list_i64'):
                    return f"(print_list_i64({a}), INT64_C(0))", "i64"
                if at == 'list_str':
                    return f"(print_list_str({a}), INT64_C(0))", "i64"
                if isinstance(at, str) and at.startswith('list_'):
                    # list_i32 etc. — prefer typed printer if present, else i64
                    elem = at[5:]
                    if elem in ('i32', 'i64', 'str'):
                        return f"(print_list_{elem}({a}), INT64_C(0))", "i64"
                    return f"(print_list_i64(*(List_i64*)&({a})), INT64_C(0))", "i64"
                if at == 'bool':
                    return f"(print_bool({a}), INT64_C(0))", "i64"
                if at in self.record_field_types:
                    return f"(print_{at}({a}), INT64_C(0))", "i64"
                return f"(print_i64({a}), INT64_C(0))", "i64"
            if isinstance(e.func, Var) and e.func.name == 'map':
                coll, ct = self.gen_expr(e.args[0])
                fn_e = e.args[1]
                if isinstance(fn_e, Var) and fn_e.name in self.known:
                    fn_c = self.known[fn_e.name]
                else:
                    fn_c, _ = self.gen_expr(fn_e)
                    fn_c = f"((int64_t(*)(int64_t)){fn_c})"
                tmp = self.fresh()
                idx = self.fresh()
                return (
                    f"({{ List_i64 __map_in = {coll}; List_i64 {tmp} = list_new_i64(__map_in.n); "
                    f"for (int64_t {idx} = 0; {idx} < __map_in.n; {idx}++) "
                    f"{tmp}.d[{idx}] = {fn_c}(__map_in.d[{idx}]); "
                    f"{tmp}; }})",
                    "List"
                )
            if isinstance(e.func, Var) and e.func.name == 'len':
                a, at = self.gen_expr(e.args[0])
                if at == 'list_str':
                    return f"list_len_str({a})", "i64"
                if at in ('list', 'List'):
                    return f"list_len_i64({a})", "i64"
                if isinstance(at, str) and at.startswith('list_'):
                    return f"list_len_{at[5:]}({a})", "i64"
                if isinstance(at, str) and at.startswith('map_'):
                    parts = at.split('_')
                    kty, vty = parts[1], '_'.join(parts[2:])
                    return f"map_{kty}_{vty}_len({a})", "i64"
                return (f"str_len({a})", "i64") if at == 'str' else (f"list_len_i64({a})", "i64")
            if isinstance(e.func, Var) and e.func.name == 'json':
                a, at = self.gen_expr(e.args[0])
                if at == 'str': return f"json_str({a})", "str"
                if at in ('list', 'List'): return f"json_list({a})", "str"
                if at.startswith('list_'): return f"json_list_{at[5:]}({a})", "str"
                return f"json_int({a})", "str"
            if isinstance(e.func, Var) and e.func.name == 'env':
                a, _ = self.gen_expr(e.args[0])
                return f"env_get({a})", "str"
            if isinstance(e.func, Var) and e.func.name == 'arg':
                index, _ = self.gen_expr(e.args[0])
                return f"terse_arg({index})", "str"
            if isinstance(e.func, Var) and e.func.name == 'substr':
                text, _ = self.gen_expr(e.args[0])
                start, _ = self.gen_expr(e.args[1])
                length, _ = self.gen_expr(e.args[2])
                return f"str_slice({text}, {start}, {length})", "str"
            # std.str surface (also available unqualified)
            if isinstance(e.func, Var) and e.func.name == 'has' and len(e.args) >= 2:
                a, at = self.gen_expr(e.args[0]); b, _ = self.gen_expr(e.args[1])
                if at == 'str':
                    return f"str_has({a}, {b})", "bool"
                if isinstance(at, str) and at.startswith('map_'):
                    parts = at.split('_')
                    kty, vty = parts[1], '_'.join(parts[2:])
                    return f"map_{kty}_{vty}_has({a}, {b})", "bool"
            if isinstance(e.func, Var) and e.func.name == 'keys' and len(e.args) >= 1:
                a, at = self.gen_expr(e.args[0])
                if isinstance(at, str) and at.startswith('map_'):
                    parts = at.split('_')
                    kty, vty = parts[1], '_'.join(parts[2:])
                    return f"map_{kty}_{vty}_keys({a})", "list_str"
            if isinstance(e.func, Var) and e.func.name == 'values' and len(e.args) >= 1:
                a, at = self.gen_expr(e.args[0])
                if at == 'map_str_i64':
                    return f"map_str_i64_values({a})", "List"
            if isinstance(e.func, Var) and e.func.name == 'starts' and len(e.args) >= 2:
                a, _ = self.gen_expr(e.args[0]); b, _ = self.gen_expr(e.args[1])
                return f"str_starts({a}, {b})", "bool"
            if isinstance(e.func, Var) and e.func.name == 'ends' and len(e.args) >= 2:
                a, _ = self.gen_expr(e.args[0]); b, _ = self.gen_expr(e.args[1])
                return f"str_ends({a}, {b})", "bool"
            if isinstance(e.func, Var) and e.func.name == 'trim' and len(e.args) >= 1:
                a, _ = self.gen_expr(e.args[0])
                return f"str_trim({a})", "str"
            if isinstance(e.func, Var) and e.func.name == 'up' and len(e.args) >= 1:
                a, _ = self.gen_expr(e.args[0])
                return f"str_up({a})", "str"
            if isinstance(e.func, Var) and e.func.name == 'low' and len(e.args) >= 1:
                a, _ = self.gen_expr(e.args[0])
                return f"str_low({a})", "str"
            if isinstance(e.func, Var) and e.func.name == 'parse' and len(e.args) >= 1:
                a, at = self.gen_expr(e.args[0])
                return f"str_parse_i64({a})", "i64"
            if isinstance(e.func, Var) and e.func.name == 'split' and len(e.args) >= 2:
                a, _ = self.gen_expr(e.args[0]); b, _ = self.gen_expr(e.args[1])
                return f"str_split({a}, {b})", "list_str"
            if isinstance(e.func, Var) and e.func.name == 'join' and len(e.args) >= 2:
                a, _ = self.gen_expr(e.args[0]); b, _ = self.gen_expr(e.args[1])
                return f"str_join({a}, {b})", "str"
            # std.str.foo(...) method form when use std.str
            if isinstance(e.func, Member) and isinstance(e.func.obj, Var) and e.func.obj.name == 'str':
                meth = e.func.field
                if meth == 'has' and len(e.args) >= 2:
                    a, _ = self.gen_expr(e.args[0]); b, _ = self.gen_expr(e.args[1])
                    return f"str_has({a}, {b})", "bool"
                if meth == 'starts' and len(e.args) >= 2:
                    a, _ = self.gen_expr(e.args[0]); b, _ = self.gen_expr(e.args[1])
                    return f"str_starts({a}, {b})", "bool"
                if meth == 'ends' and len(e.args) >= 2:
                    a, _ = self.gen_expr(e.args[0]); b, _ = self.gen_expr(e.args[1])
                    return f"str_ends({a}, {b})", "bool"
                if meth == 'trim' and len(e.args) >= 1:
                    a, _ = self.gen_expr(e.args[0])
                    return f"str_trim({a})", "str"
                if meth == 'up' and len(e.args) >= 1:
                    a, _ = self.gen_expr(e.args[0])
                    return f"str_up({a})", "str"
                if meth == 'low' and len(e.args) >= 1:
                    a, _ = self.gen_expr(e.args[0])
                    return f"str_low({a})", "str"
                if meth == 'parse' and len(e.args) >= 1:
                    a, _ = self.gen_expr(e.args[0])
                    return f"str_parse_i64({a})", "i64"
                if meth == 'split' and len(e.args) >= 2:
                    a, _ = self.gen_expr(e.args[0]); b, _ = self.gen_expr(e.args[1])
                    return f"str_split({a}, {b})", "list_str"
                if meth == 'join' and len(e.args) >= 2:
                    a, _ = self.gen_expr(e.args[0]); b, _ = self.gen_expr(e.args[1])
                    return f"str_join({a}, {b})", "str"
            if isinstance(e.func, Member) and isinstance(e.func.obj, Var) \
                    and e.func.obj.name in ('io', 'fs'):
                # std.io — io.in(path) / io.out(path, text)
                # fs.read_text / fs.write_text remain as aliases
                if e.func.field in ('in', 'read_text'):
                    path, _ = self.gen_expr(e.args[0])
                    return f"fs_read_text({path})", "str"
                if e.func.field == 'out' or e.func.field == 'write_text':
                    path, _ = self.gen_expr(e.args[0])
                    text, _ = self.gen_expr(e.args[1])
                    return f"fs_write_text({path}, {text})", "i64"
                if e.func.field == 'append' or e.func.field == 'append_text':
                    path, _ = self.gen_expr(e.args[0])
                    text, _ = self.gen_expr(e.args[1])
                    return f"fs_append_text({path}, {text})", "i64"
            if isinstance(e.func, Member) and isinstance(e.func.obj, Var) \
                    and e.func.obj.name == 'http' and e.func.field == 'serve' and len(e.args) >= 2:
                return self.gen_http_serve_fn(e)
            if isinstance(e.func, Member) and isinstance(e.func.obj, Var) \
                    and e.func.obj.name == 'sock':
                f = e.func.field
                if f == 'listen' and e.args:
                    a, _ = self.gen_expr(e.args[0])
                    return f"sock_listen({a})", "i64"
                if f == 'accept' and e.args:
                    a, _ = self.gen_expr(e.args[0])
                    return f"sock_accept({a})", "i64"
                if f == 'recv' and e.args:
                    a, _ = self.gen_expr(e.args[0])
                    return f"sock_recv({a})", "str"
                if f == 'send' and len(e.args) >= 2:
                    a, _ = self.gen_expr(e.args[0]); b, _ = self.gen_expr(e.args[1])
                    return f"sock_send({a}, {b})", "i64"
                if f == 'close' and e.args:
                    a, _ = self.gen_expr(e.args[0])
                    return f"sock_close({a})", "i64"
            if isinstance(e.func, Member) and isinstance(e.func.obj, Var) \
                    and e.func.obj.name == 'gcc' and e.func.field == 'compile':
                source, _ = self.gen_expr(e.args[0])
                output, _ = self.gen_expr(e.args[1])
                return f"terse_gcc_compile({source}, {output})", "i64"
            # Database operations use the SQLite-backed runtime.
            if isinstance(e.func, Member) and isinstance(e.func.obj, Var) and e.func.obj.name == 'db':
                if e.func.field == 'connect':
                    url, _ = self.gen_expr(e.args[0])
                    return f"db_connect({url})", "i64"
                if e.func.field in ('query', 'query_one'):
                    sql, _ = self.gen_expr(e.args[0])
                    argc_args = self.db_args(e.args[1:])
                    return f"db_query({sql}, {argc_args})", "list"
                if e.func.field == 'exec':
                    sql, _ = self.gen_expr(e.args[0])
                    argc_args = self.db_args(e.args[1:])
                    return f"db_exec({sql}, {argc_args})", "i64"
            # db.query[User](...) / db.query_one[User](...) typed queries.
            if isinstance(e.func, Index) and isinstance(e.func.coll, Member) \
                    and isinstance(e.func.coll.obj, Var) and e.func.coll.obj.name == 'db':
                if e.func.coll.field in ('query', 'query_one'):
                    record_name = e.func.idx.name if isinstance(e.func.idx, Var) else None
                    sql, _ = self.gen_expr(e.args[0])
                    argc_args = self.db_args(e.args[1:])
                    if record_name in self.record_field_types:
                        return f"db_query_{record_name}({sql}, {argc_args})", f"list_{record_name}"
                    return f"db_query({sql}, {argc_args})", "list"
                if e.func.coll.field == 'exec':
                    sql, _ = self.gen_expr(e.args[0])
                    argc_args = self.db_args(e.args[1:])
                    return f"db_exec({sql}, {argc_args})", "i64"
            # std.tst — assertions (abort on mismatch)
            #   tst.eq(got, expected)  |  tst.chk(expected, actual)  |  tst.check.equals(got, expected)
            if isinstance(e.func, Member) and isinstance(e.func.obj, Var) and e.func.obj.name == 'tst':
                if e.func.field == 'report':
                    return "tst_report()", "i64"
                def _tst_lib(kind, got_t):
                    # Prefer Terse overloaded helpers: ..._eq__i64_i64_str_i64
                    # kind is 'eq' or 'ne'; params (got, expected, file, line)
                    gt = got_t if got_t in ('i64', 'str', 'bool') else 'i64'
                    sig = f"{kind}__{gt}_{gt}_str_i64"
                    for name, cname in self.known.items():
                        if 'tst' in name and sig in name:
                            return cname
                    # legacy eq_i64 naming
                    legacy = f"{kind}_{gt}"
                    for name, cname in self.known.items():
                        if 'tst' in name and (name.endswith('_' + legacy) or name.endswith(legacy)):
                            return cname
                    return None
                if e.func.field in ('eq', 'equals') and len(e.args) >= 2:
                    got, got_t = self.gen_expr(e.args[0])
                    exp, _ = self.gen_expr(e.args[1])
                    where = self.tst_where(e)
                    lib = _tst_lib('eq', got_t)
                    if lib:
                        return f"({{ _tst_checks++; if ({lib}({got}, {exp}, {where})) _tst_failures++; INT64_C(0); }})", "i64"
                    helper = {'i64': 'tst_eq_i64', 'bool': 'tst_eq_bool', 'str': 'tst_eq_str'}.get(got_t, 'tst_eq_i64')
                    return f"({helper}({got}, {exp}, {where}), INT64_C(0))", "i64"
                if e.func.field in ('ne', 'not_equals') and len(e.args) >= 2:
                    got, got_t = self.gen_expr(e.args[0])
                    exp, _ = self.gen_expr(e.args[1])
                    where = self.tst_where(e)
                    lib = _tst_lib('ne', got_t)
                    if lib:
                        return f"({{ _tst_checks++; if ({lib}({got}, {exp}, {where})) _tst_failures++; INT64_C(0); }})", "i64"
                    helper = {'i64': 'tst_ne_i64', 'bool': 'tst_ne_bool', 'str': 'tst_ne_str'}.get(got_t, 'tst_ne_i64')
                    return f"({helper}({got}, {exp}, {where}), INT64_C(0))", "i64"
                if e.func.field == 'chk' and len(e.args) >= 2:
                    exp, _ = self.gen_expr(e.args[0])
                    got, got_t = self.gen_expr(e.args[1])
                    where = self.tst_where(e)
                    lib = _tst_lib('eq', got_t)
                    if lib:
                        return f"({{ _tst_checks++; if ({lib}({got}, {exp}, {where})) _tst_failures++; INT64_C(0); }})", "i64"
                    helper = {'i64': 'tst_eq_i64', 'bool': 'tst_eq_bool', 'str': 'tst_eq_str'}.get(got_t, 'tst_eq_i64')
                    return f"({helper}({got}, {exp}, {where}), INT64_C(0))", "i64"
            if isinstance(e.func, Member) and isinstance(e.func.obj, Member) \
                    and isinstance(e.func.obj.obj, Var) and e.func.obj.obj.name == 'tst' \
                    and e.func.obj.field == 'check' and e.func.field == 'equals':
                got, got_t = self.gen_expr(e.args[0])
                exp, _ = self.gen_expr(e.args[1])
                helper = {'i64': 'tst_eq_i64', 'bool': 'tst_eq_bool', 'str': 'tst_eq_str'}.get(got_t, 'tst_eq_i64')
                where = self.tst_where(e)
                return f"({helper}({got}, {exp}, {where}), INT64_C(0))", "i64"
            if isinstance(e.func, Member):
                # Built-in: .len() method on str and List
                if e.func.field == 'len':
                    base, bt = self.gen_expr(e.func.obj)
                    if bt == 'str':
                        return f"str_len({base})", "i64"
                    if bt.startswith('list_'):
                        return f"list_len_{bt[5:]}({base})", "i64"
                    if bt == 'List':
                        return f"list_len_i64({base})", "i64"
                base_type = self.expr_type(e.func.obj)
                if base_type in self.interface_methods and e.func.field in self.interface_methods[base_type]:
                    base_code, _ = self.gen_expr(e.func.obj)
                    ret_type = self.interface_method_returns.get((base_type, e.func.field), 'i64')
                    c_ret_type = self.c_type(ret_type)
                    return f"((({c_ret_type}(*)(void*))(({base_code}).{e.func.field}))(({base_code}).value))", ret_type
                method_key = (base_type, e.func.field)
                if method_key in self.method_names:
                    args = [self.gen_expr(e.func.obj)[0]] + [self.gen_expr(a)[0] for a in e.args]
                    cname = self.method_names[method_key]
                    return f"{cname}({', '.join(args)})", self.method_returns[method_key]
            if isinstance(e.func, Var) and (
                e.func.name in self.known or e.func.name in getattr(self, 'overloads', {})
            ):
                overs = getattr(self, 'overloads', {}).get(e.func.name) or []
                cname = None
                ret_ty = "i64"
                pts = None
                if len(overs) > 1 or (len(overs) == 1 and getattr(self, 'overloads', {}).get(e.func.name)):
                    # Type-directed overload resolution
                    typed_args = []
                    arg_types = []
                    for a in e.args:
                        ac, at = self.gen_expr(a)
                        typed_args.append((ac, at))
                        arg_types.append(at)
                    resolved = _resolve_overload(overs, arg_types) if overs else None
                    if resolved:
                        pts, cname, ret_ty = resolved
                        args = []
                        for (ac, at), expected in zip(typed_args, pts):
                            if expected in self.interface_methods and at in self.record_field_types and (expected, at) in self.interface_helpers:
                                args.append(f"{self.interface_helpers[(expected, at)]}( &({ac}) )")
                            else:
                                args.append(ac)
                        return f"{cname}({', '.join(args)})", ret_ty
                cname = self.known.get(e.func.name)
                if cname is None and overs:
                    pts, cname, ret_ty = overs[0]
                args = []
                param_ts = self.func_param_types.get(cname) or self.func_param_types.get(e.func.name) or []
                if param_ts:
                    for a, expected in zip(e.args, param_ts):
                        arg_code, arg_type = self.gen_expr(a, expected)
                        if expected in self.interface_methods and arg_type in self.record_field_types and (expected, arg_type) in self.interface_helpers:
                            args.append(f"{self.interface_helpers[(expected, arg_type)]}( &({arg_code}) )")
                        else:
                            args.append(arg_code)
                else:
                    args = [self.gen_expr(a)[0] for a in e.args]
                args_str = ", ".join(args)
                return f"{cname}({args_str})", self.func_return_types.get(cname, self.func_return_types.get(e.func.name, "i64"))
            fptr, ft = self.gen_expr(e.func)
            typed = [self.gen_expr(a) for a in e.args]
            args = ", ".join(c for c, _ in typed)
            # ft may be 'fn' or 'fn:Req>Res' style from env
            ret_ty = "i64"
            arg_cs = []
            if isinstance(ft, str) and ft.startswith("fn:"):
                # fn:Arg1,Arg2>Ret
                try:
                    mid, ret_ty = ft[3:].rsplit(">", 1)
                    parts = [x for x in mid.split(",") if x]
                    for i, (c, at) in enumerate(typed):
                        arg_cs.append(self.c_type(parts[i] if i < len(parts) else at))
                except ValueError:
                    arg_cs = [self.c_type(at) for _, at in typed]
            else:
                arg_cs = [self.c_type(at) for _, at in typed]
                # Heuristic: if arg is a known record, keep it
            arg_ts = ", ".join(arg_cs) if arg_cs else "void"
            ret_c = self.c_type(ret_ty)
            return f"(({ret_c}(*)({arg_ts}))({fptr}))({args})", ret_ty
        if isinstance(e, IfExpr):
            # Statement if/else (not C ternary) avoids pointer/integer mismatches when
            # branches have different C types (str assign vs bool assign vs list assign).
            c, _ = self.gen_expr(e.cond)
            t, tt = self.gen_expr(e.then)
            if e.els is not None:
                f, ft = self.gen_expr(e.els)
            else:
                f, ft = None, tt
            result = self.fresh()
            def zero_for(ty):
                if ty == 'str': return '""'
                if ty == 'bool': return 'false'
                if ty == 'i64': return 'INT64_C(0)'
                return f'({self.c_type(ty)}){{0}}'
            if f is None:
                ctype = self.c_type(tt)
                body = f"if ({c}) {{ {result} = {t}; }}"
                return f"({{ {ctype} {result} = {zero_for(tt)}; {body} {result}; }})", tt
            if ft == tt:
                ctype = self.c_type(tt)
                body = f"if ({c}) {{ {result} = {t}; }} else {{ {result} = {f}; }}"
                return f"({{ {ctype} {result} = {zero_for(tt)}; {body} {result}; }})", tt
            # Mismatched branch types: evaluate both for side effects only; yield 0
            return (
                f"({{ if ({c}) {{ (void)({t}); }} else {{ (void)({f}); }} INT64_C(0); }})",
                "i64",
            )
        if isinstance(e, TernaryExpr):
            c, _ = self.gen_expr(e.cond)
            t, tt = self.gen_expr(e.then)
            f, ft = self.gen_expr(e.els)
            result = self.fresh()
            def zero_for(ty):
                if ty == 'str': return '""'
                if ty == 'bool': return 'false'
                if ty in self.record_field_types or ty in self.enum_values:
                    return f"({self.c_type(ty)}){{0}}"
                return "INT64_C(0)"
            if tt == ft:
                ctype = self.c_type(tt)
                body = f"if ({c}) {{ {result} = {t}; }} else {{ {result} = {f}; }}"
                return f"({{ {ctype} {result} = {zero_for(tt)}; {body} {result}; }})", tt
            return (
                f"({{ if ({c}) {{ (void)({t}); }} else {{ (void)({f}); }} INT64_C(0); }})",
                "i64",
            )
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
            body_stmts = self.gen_loop_body(e.body)
            post_c = ''
            if e.post is not None:
                post_e, _ = self.gen_expr(e.post)
                post_c = f"(void)({post_e})"
            self.env = old_env
            # Use for() when post exists so continue still runs the increment
            if post_c and init_decl is not None:
                # init_decl is "type name = val;" — strip trailing ; for for-init
                init_for = init_decl.rstrip(';')
                loop = f"for ({init_for}; {cond_c}; {post_c}) {{ {body_stmts} }}"
                return (f"({{ {loop} INT64_C(0); }})", "i64")
            if post_c and init_stmt is not None:
                loop = f"while({cond_c}) {{ {body_stmts} {post_c}; }}"
                # continue would skip post — wrap body so continue goes through post via for with empty init
                loop = f"for (; {cond_c}; {post_c}) {{ {body_stmts} }}"
                return (f"({{ {init_stmt} {loop} INT64_C(0); }})", "i64")
            if post_c:
                loop = f"for (; {cond_c}; {post_c}) {{ {body_stmts} }}"
                return (f"({{ {loop} INT64_C(0); }})", "i64")
            loop = f"while({cond_c}) {{ {body_stmts} }}"
            if init_decl is not None:
                return (f"({{ {init_decl} {loop} INT64_C(0); }})", "i64")
            if init_stmt is not None:
                return (f"({{ {init_stmt} {loop} INT64_C(0); }})", "i64")
            return (f"({{ {loop} INT64_C(0); }})", "i64")
        if isinstance(e, ForInExpr):
            coll, ct = self.gen_expr(e.iterable)
            # Map for-in iterates keys (str)
            if isinstance(ct, str) and ct.startswith('map_'):
                parts = ct.split('_')
                kty, vty = parts[1], '_'.join(parts[2:])
                coll = f"map_{kty}_{vty}_keys({coll})"
                ct = 'list_str'
            # Element type from list_* / List / map
            if ct == 'list_str' or ct == 'List_str':
                elem_t, c_list, get_elem = 'str', 'List_str', None
                c_elem = 'const char*'
            elif ct.startswith('list_'):
                inner = ct[5:]
                if inner == 'int':
                    inner = 'i64'
                elem_t = inner
                c_list = f'List_{inner}'
                c_elem = self.c_type(inner)
            elif ct in ('list', 'List', 'List_i64'):
                elem_t, c_list, c_elem = 'i64', 'List_i64', 'int64_t'
            else:
                # fallback: treat as i64 list
                elem_t, c_list, c_elem = 'i64', 'List_i64', 'int64_t'
            old = self.env.get(e.var)
            self.env[e.var] = elem_t
            body_stmts = self.gen_loop_body(e.body)
            if old is not None: self.env[e.var] = old
            else: self.env.pop(e.var, None)
            idx = self.fresh()
            tmp = self.fresh()
            if c_list == 'List_str':
                bind = f"const char* {e.var} = list_get_str({tmp}, {idx});"
                len_e = f"list_len_str({tmp})"
            elif c_list in ('List', 'List_i64'):
                bind = f"int64_t {e.var} = list_get_i64({tmp}, {idx});"
                len_e = f"list_len_i64({tmp})"
            else:
                # List_Record etc.
                bind = f"{c_elem} {e.var} = list_get_{elem_t}({tmp}, {idx});"
                len_e = f"list_len_{elem_t}({tmp})"
            return (
                f"({{ {c_list} {tmp} = {coll}; "
                f"for (int64_t {idx} = 0; {idx} < {len_e}; {idx}++) {{ "
                f"{bind} {body_stmts} }} "
                f"INT64_C(0); }})",
                "i64"
            )
        if isinstance(e, MatchExpr):
            subj, st = self.gen_expr(e.subject)
            tmp = self.fresh()
            result = self.fresh()
            bind_names = []
            for arm in e.arms:
                if isinstance(arm.pattern, BindPattern) and arm.pattern.name not in bind_names:
                    bind_names.append(arm.pattern.name)
            probe_env = self.env.copy()
            for bn in bind_names:
                probe_env[bn] = st
            old_env = self.env
            self.env = probe_env
            _, ret_t = self.gen_expr(e.arms[0].value)
            self.env = old_env
            zero = '""' if ret_t == 'str' else ("INT64_C(0)" if ret_t == 'i64' else f"({self.c_type(ret_t)}){{0}}")
            if st in self.enum_has_data and self.enum_has_data[st]:
                ctype = st
            elif st in self.enum_values and not self.enum_has_data.get(st, False):
                ctype = 'int64_t'
            else:
                ctype = self.c_type(st) if st not in ('str',) else 'int64_t'
            parts = [f"{ctype} {tmp} = {subj};"]
            for bn in bind_names:
                parts.append(f"{ctype} {bn} = {tmp};")
            parts.append(f"{self.c_type(ret_t)} {result} = {zero};")
            chain = []
            for arm in e.arms:
                old_env = self.env.copy()
                for bn in bind_names:
                    self.env[bn] = st
                if isinstance(arm.pattern, BindPattern):
                    self.env[arm.pattern.name] = st
                conds = []
                if isinstance(arm.pattern, Wildcard):
                    pass
                elif isinstance(arm.pattern, LiteralPattern):
                    lit, _ = self.gen_expr(arm.pattern.value)
                    conds.append(f"({tmp} == {lit})")
                elif isinstance(arm.pattern, EnumVariant):
                    variants = self.enum_values.get(arm.pattern.ctor, {})
                    if arm.pattern.variant in variants:
                        tag, ftypes = variants[arm.pattern.variant]
                        has_data = self.enum_has_data.get(arm.pattern.ctor, False)
                        if has_data:
                            conds.append(f"({tmp}.tag == INT64_C({tag}))")
                            for i, sub in enumerate(arm.pattern.fields):
                                if isinstance(sub, BindPattern):
                                    ft = ftypes[i] if i < len(ftypes) else 'i64'
                                    self.env[sub.name] = ft
                                    # declare bind in outer parts if needed - extract via assignment in body
                                elif isinstance(sub, Wildcard):
                                    pass
                                else:
                                    # literal compare on payload
                                    lit, _ = self.gen_expr(sub.value) if isinstance(sub, LiteralPattern) else ("0", "i64")
                                    conds.append(f"({tmp}.u.{arm.pattern.variant}.v{i} == {lit})")
                        else:
                            conds.append(f"({tmp} == INT64_C({tag}))")
                    else:
                        conds.append("0")
                elif isinstance(arm.pattern, BindPattern):
                    pass
                else:
                    conds.append("1")
                if arm.guard is not None:
                    g, _ = self.gen_expr(arm.guard)
                    conds.append(f"({g})")
                # bind payload fields before body
                bind_stmts = []
                if isinstance(arm.pattern, EnumVariant) and arm.pattern.fields:
                    variants = self.enum_values.get(arm.pattern.ctor, {})
                    if arm.pattern.variant in variants:
                        _, ftypes = variants[arm.pattern.variant]
                        for i, sub in enumerate(arm.pattern.fields):
                            if isinstance(sub, BindPattern):
                                ft = ftypes[i] if i < len(ftypes) else 'i64'
                                bind_stmts.append(
                                    f"{self.c_type(ft)} {sub.name} = {tmp}.u.{arm.pattern.variant}.v{i};"
                                )
                val_c, _ = self.gen_expr(arm.value)
                self.env = old_env
                cond_str = " && ".join(conds) if conds else "1"
                body_block = " ".join(bind_stmts) + f" {result} = {val_c};"
                chain.append(f"if ({cond_str}) {{ {body_block} }}")
            else_chain = chain[0]
            for c in chain[1:]:
                else_chain += " else " + c
            parts.append(else_chain)
            parts.append(result)
            return "({ " + " ".join(parts) + "; })", ret_t
        if isinstance(e, LetExpr):
            v, vt = self.gen_expr(e.value, self.type_name(e.typ) if e.typ else None)
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
            if len(e.stmts) == 1:
                return self.gen_expr(e.stmts[0])
            parts = []
            for st in e.stmts[:-1]:
                code, _ = self.gen_expr(st)
                parts.append(f"(void)({code})")
            last, lt = self.gen_expr(e.stmts[-1])
            return "({ " + "; ".join(parts) + "; " + last + "; })", lt
        return "INT64_C(0)", "i64"


    def gen_http_serve_fn(self, e: Call):
        """http.serve(port, handler) — handler is Lambda, named fn, or fn-param."""
        if len(e.args) < 2:
            return "INT64_C(0)", "i64"
        port_c, _ = self.gen_expr(e.args[0])
        handler = e.args[1]
        self.lam_n += 1
        wrap = f"__http_fn_{self.lam_n}"
        empty = '""'

        def adapter_body(call_line: str, req_name: str = "req") -> str:
            return (
                f"  Req {req_name} = (Req){{ "
                f".method = method ? method : {empty}, "
                f".path = path ? path : {empty}, "
                f".query = query ? query : {empty}, "
                f".body = body ? body : {empty} }};\n"
                f"  {call_line}\n"
                f"  HttpResC out;\n"
                f"  out.status = (int64_t)(_r.status);\n"
                f"  out.body = _r.body ? _r.body : {empty};\n"
                f"  out.ctype = _r.ctype ? _r.ctype : \"text/plain\";\n"
                f"  return out;\n"
            )

        header = (
            f"static HttpResC {wrap}(const char* method, const char* path, "
            f"const char* query, const char* body)"
        )

        if isinstance(handler, Lambda):
            pname = handler.params[0].name if handler.params else "req"
            old = self.env.copy()
            self.env[pname] = "Req"
            body_c, _bt = self.gen_expr(handler.body)
            self.env = old
            self.extra.append(
                header + " {\n" + adapter_body(f"Res _r = {body_c};", pname) + "}\n"
            )
            return f"(http_serve_fn({port_c}, {wrap}), INT64_C(0))", "i64"

        if isinstance(handler, Var) and handler.name in self.known:
            hn = self.known[handler.name]
            self.extra.append(
                header + " {\n" + adapter_body(f"Res _r = {hn}(req);") + "}\n"
            )
            return f"(http_serve_fn({port_c}, {wrap}), INT64_C(0))", "i64"

        # Parameter or expression: function pointer Res(*)(Req)
        hc, _ = self.gen_expr(handler)
        slot = f"{wrap}_user"
        self.extra.append(f"static Res (*{slot})(Req);\n")
        self.extra.append(
            header + " {\n" + adapter_body(f"Res _r = {slot}(req);") + "}\n"
        )
        return (
            f"({{ {slot} = (Res(*)(Req))({hc}); "
            f"http_serve_fn({port_c}, {wrap}); INT64_C(0); }})",
            "i64",
        )

    def gen_http_serve(self, e: HttpServe) -> Tuple[str, str]:
        port_c, _ = self.gen_expr(e.port)
        self.lam_n += 1
        dispatcher = f"__http_dispatch_{self.lam_n}"
        # Build dispatcher that matches method+path and runs handler
        lines = [f"static const char* {dispatcher}(const char* method, const char* path, const char* body) {{"]
        for i, r in enumerate(e.routes):
            hname = f"__route_{self.lam_n}_{i}"
            route_match = re.fullmatch(r"(.*)\{([A-Za-z_][A-Za-z0-9_]*)\}(.*)", r.path)
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
                param_decls = " ".join(
                    f"const char* {p.name} = arg;" for p in r.handler.params
                )
                self.extra.append(
                    f"static const char* {hname}(const char* arg) {{\n  {param_decls}\n  return {body_c};\n}}\n"
                )
                call_arg = f"route_arg_{i}" if route_match else "body"
                call = f"{hname}({call_arg})"
            else:
                body_c, bt = self.gen_expr(r.handler)
                if bt == 'i64':
                    body_c = f"json_int({body_c})"
                elif bt == 'list':
                    body_c = f"json_list({body_c})"
                elif bt.startswith('list_'):
                    body_c = f"json_list_{bt[5:]}({body_c})"
                elif bt != 'str':
                    body_c = f'"{bt}"'
                # constant / expression handler - embed as function returning that
                self.extra.append(
                    f"static const char* {hname}(const char* body) {{\n  (void)body;\n  return {body_c};\n}}\n"
                )
                call = f"{hname}(body)"
            if route_match:
                prefix, _, suffix = route_match.groups()
                prefix_c = prefix.replace('\\', '\\\\').replace('"', '\\"')
                suffix_c = suffix.replace('\\', '\\\\').replace('"', '\\"')
                prefix_len = len(prefix)
                suffix_len = len(suffix)
                lines.append(
                    f'  if (strcmp(method, "{r.method}") == 0 && '
                    f'strncmp(path, "{prefix_c}", {prefix_len}) == 0 && '
                    f'path[{prefix_len}] != \'\\0\' && '
                    f'({suffix_len} == 0 || (strlen(path) >= {prefix_len + suffix_len} && '
                    f'strcmp(path + strlen(path) - {suffix_len}, "{suffix_c}") == 0))) {{'
                )
                lines.append(f"    char route_arg_{i}[2048];")
                if suffix_len:
                    lines.append(
                        f"    snprintf(route_arg_{i}, sizeof(route_arg_{i}), \"%.*s\", "
                        f"(int)(strlen(path) - {prefix_len + suffix_len}), path + {prefix_len});"
                    )
                else:
                    lines.append(
                        f"    snprintf(route_arg_{i}, sizeof(route_arg_{i}), \"%s\", path + {prefix_len});"
                    )
                lines.append(f"    return {call};")
                lines.append("  }")
            else:
                lines.append(f'  if (strcmp(method, "{r.method}") == 0 && strcmp(path, "{r.path}") == 0) return {call};')
        lines.append("  return NULL;")
        lines.append("}\n")
        self.extra.append("\n".join(lines))
        # http_serve_run never returns
        return f"(http_serve_run({port_c}, {dispatcher}), INT64_C(0))", "i64"

    def gen_fn(self, f: FnDecl):
        cname = getattr(f, '_c_name', None) or self.known[f.name]
        pcs = []
        for p in f.params:
            if p.typ and getattr(p.typ, 'name', None) == 'fn':
                tn = _fn_type_tag(p.typ)
                # C needs: Ret (*name)(Args)  not  Ret(*)(Args) name
                try:
                    mid, ret = tn[3:].rsplit('>', 1)
                    args = [a for a in mid.split(',') if a]
                    args_c = ', '.join(self.c_type(a) for a in args) if args else 'void'
                    pcs.append(f"{self.c_type(ret)} (*{p.name})({args_c})")
                except ValueError:
                    pcs.append(f"void* {p.name}")
            else:
                tn = self.type_name(p.typ) if p.typ else 'i64'
                pcs.append(f"{self.c_type(tn)} {p.name}")
        ret = self.type_name(f.ret) if f.ret else 'i64'
        crt = self.c_type(ret)
        pstr = ", ".join(pcs) if pcs else "void"
        old_env = self.env.copy()
        for p in f.params:
            if p.typ and getattr(p.typ, 'name', None) == 'fn':
                self.env[p.name] = _fn_type_tag(p.typ)
            else:
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

    def generate(self, prog: Program, source_path: Optional[str] = None, as_lib: bool = False, skip_runtime: bool = False) -> str:
        # Skip generic templates; specialized clones (Box__i64) are concrete
        self.record_field_types = {
            r.name: {n: self.type_name(t) for n, t in r.fields}
            for r in prog.recs if not getattr(r, 'type_params', None)
        }
        self.enum_values = {}
        for e in prog.enums:
            if getattr(e, 'type_params', None):
                continue
            m = {}
            for i, v in enumerate(e.variants):
                tag = v.value if getattr(v, 'value', None) is not None else i
                m[v.name] = (tag, [self.type_name(t) for t in v.fields])
            self.enum_values[e.name] = m
        self.enum_has_data = {
            e.name: any(len(v.fields) > 0 for v in e.variants)
            for e in prog.enums if not getattr(e, 'type_params', None)
        }
        self.method_names = {}
        self.method_returns = {}
        self.interface_methods = {
            sig.name: [m[0] for m in sig.methods]
            for sig in prog.sigs if not getattr(sig, 'type_params', None)
        }
        self.interface_method_returns = {
            (sig.name, m[0]): self.type_name(m[2]) if m[2] else 'i64'
            for sig in prog.sigs if not getattr(sig, 'type_params', None)
            for m in sig.methods
        }
        # Top-level fix constants: register types in env for later expressions
        self.const_decls = list(getattr(prog, 'fixes', []) or [])
        for c in self.const_decls:
            tn = self.type_name(c.typ) if c.typ else None
            if tn is None:
                if isinstance(c.value, StrLit):
                    tn = 'str'
                elif isinstance(c.value, BoolLit):
                    tn = 'bool'
                elif isinstance(c.value, IntLit):
                    tn = 'i64'
                else:
                    tn = 'i64'
            self.env[c.name] = tn
        funcs = list(prog.funcs)
        entry_name = None
        for m in prog.methods:
            method_name = f"{m.receiver}_{m.name}"
            self.method_names[(m.receiver, m.name)] = "terse_" + method_name
            self.method_returns[(m.receiver, m.name)] = self.type_name(m.ret) if m.ret else 'i64'
            receiver = Param('self', TypeNode(m.receiver))
            funcs.append(FnDecl(method_name, [receiver] + list(m.params), m.ret, m.body))
        if prog.toplevel is not None:
            entry_name = '__terse_program_entry'
            while any(f.name == entry_name for f in funcs):
                entry_name += '_'
            funcs.append(FnDecl(entry_name, [], TypeNode('i64'), prog.toplevel))
        # Parameter overloads: same source name, distinct C symbols when signatures differ
        from collections import Counter
        name_counts = Counter(f.name for f in funcs)
        self.func_param_types = {}
        self.func_return_types = {}
        self.overloads = {}  # name -> [(param_types, cname, ret)]
        for f in funcs:
            if getattr(f, 'type_params', None):
                continue
            pts = [_norm_type_name(p.typ) if p.typ else 'i64' for p in f.params]
            ret = _norm_type_name(f.ret) if f.ret else 'i64'
            if name_counts[f.name] > 1:
                cname = _mangle_overload(f.name, pts)
            else:
                cname = "terse_" + f.name
            f._c_name = cname
            # Detect identical signatures (same name + same param types)
            for prev_pts, prev_c, _ in self.overloads.get(f.name, []):
                if prev_pts == pts and prev_c != cname:
                    raise SyntaxError(
                        f"duplicate overload '{f.name}({', '.join(pts)})'"
                    )
            self.known[f.name] = cname  # last wins for non-call path; calls use overloads
            self.func_param_types[cname] = pts
            self.func_param_types[f.name] = pts  # single-overload convenience
            self.func_return_types[cname] = ret
            self.func_return_types[f.name] = ret
            self.overloads.setdefault(f.name, []).append((pts, cname, ret))
        out = [RUNTIME, ""]
        # Emit top-level fix constants
        for c in self.const_decls:
            tn = self.env.get(c.name, 'i64')
            ct = self.c_type(tn)
            if isinstance(c.value, StrLit):
                esc = c.value.value.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n').replace('\t', '\\t')
                out.append(f'static const char* {c.name} = "{esc}";')
            elif isinstance(c.value, BoolLit):
                out.append(f'static const bool {c.name} = {"true" if c.value.value else "false"};')
            elif isinstance(c.value, IntLit):
                out.append(f'static const int64_t {c.name} = INT64_C({c.value.value});')
            else:
                val_c, vt = self.gen_expr(c.value)
                out.append(f'static {self.c_type(vt)} {c.name} = {val_c};')
            out.append('')
        for sig in prog.sigs:
            if getattr(sig, 'type_params', None):
                continue
            fields = ["  void* value;"]
            for name, _, _ in sig.methods:
                fields.append(f"  void* (*{name})(void*);")
            out.append(f"typedef struct {{")
            out.extend(fields)
            out.append(f"}} {sig.name};")
            out.append("")
        self.interface_helpers = {}
        # Compute implicit satisfaction: which (sig, struct) pairs are satisfied
        # by structural matching of method signatures.
        type_name = lambda t: t.name if t else 'i64'
        method_sigs = {
            (m.receiver, m.name): (
                [type_name(p.typ) for p in m.params],
                type_name(m.ret),
            )
            for m in prog.methods
        }
        satisfied = set()
        for sig in prog.sigs:
            if getattr(sig, 'type_params', None):
                continue
            sig_methods = [
                (m[0], [type_name(p.typ) for p in m[1]], type_name(m[2]))
                for m in sig.methods
            ]
            for rec in prog.recs:
                struct_name = rec.name
                ok = True
                for mname, mparams, mret in sig_methods:
                    key = (struct_name, mname)
                    if key not in method_sigs:
                        ok = False
                        break
                    mp, mr = method_sigs[key]
                    if mp != mparams or mr != mret:
                        ok = False
                        break
                if ok:
                    satisfied.add((sig.name, struct_name))
        for iface_name, struct_name in satisfied:
            iface_methods = [m for sig in prog.sigs if sig.name == iface_name for m in sig.methods]
            for method_name, _, ret_node in iface_methods:
                if (struct_name, method_name) in self.method_names:
                    helper_name = f"{iface_name}_from_{struct_name}"
                    self.interface_helpers[(iface_name, struct_name)] = helper_name
                    ret_type = self.type_name(ret_node) if ret_node else 'i64'
                    c_ret_type = self.c_type(ret_type)
                    wrapper_name = f"{struct_name}_{method_name}_adapter"
                    self.extra.append(
                        f"static {c_ret_type} {wrapper_name}(void* value) {{\n"
                        f"  {struct_name}* self = ({struct_name}*)value;\n"
                        f"  return ({c_ret_type}){self.known.get(f'{struct_name}_{method_name}', '0')}(*self);\n"
                        f"}}\n"
                    )
                    self.extra.append(
                        f"static {iface_name} {helper_name}({struct_name}* value) {{\n"
                        f"  {iface_name} out = {{0}};\n"
                        f"  out.value = (void*)value;\n"
                        f"  out.{method_name} = (void*(*)(void*)){wrapper_name};\n"
                        f"  return out;\n"
                        f"}}\n"
                    )
        concrete_recs = [r for r in prog.recs if not getattr(r, 'type_params', None)]
        concrete_enums = [e for e in prog.enums if not getattr(e, 'type_params', None)]
        for rec in concrete_recs:
            out.append(f"typedef struct {rec.name} {rec.name};")
        for en in concrete_enums:
            has_data = any(len(v.fields) > 0 for v in en.variants)
            if not has_data:
                out.append(f"typedef enum {{")
                for i, variant in enumerate(en.variants):
                    tag = variant.value if getattr(variant, 'value', None) is not None else i
                    out.append(f"    {en.name}_{variant.name.upper()} = {tag},")
                out.append(f"}} {en.name};")
                out.append("")
            else:
                # tagged union
                out.append(f"typedef struct {en.name} {en.name};")
                out.append(f"struct {en.name} {{")
                out.append(f"  int64_t tag;")
                out.append(f"  union {{")
                out.append(f"    int64_t _pad;")
                for variant in en.variants:
                    if variant.fields:
                        out.append(f"    struct {{")
                        for i, ft in enumerate(variant.fields):
                            tn = self.type_name(ft)
                            out.append(f"      {self.c_type(tn)} v{i};")
                        out.append(f"    }} {variant.name};")
                out.append(f"  }} u;")
                out.append(f"}};")
                out.append("")
        for rec in concrete_recs:
            out.append(f"typedef struct {{ {rec.name} *d; int64_t n; int64_t cap; }} List_{rec.name};")
        if concrete_recs:
            out.append("")
        for rec in concrete_recs:
            fields = []
            for name, typ in rec.fields:
                fields.append(f"  {self.c_type(self.type_name(typ))} {name};")
            if fields:
                out.append(f"struct {rec.name} {{")
                out.extend(fields)
                out.append("};")
                out.append("")
        for rec in concrete_recs:
            out.append(self.typed_db_code(rec))
            out.append(self.record_print_code(rec))
            out.append(self.record_json_code(rec))
        # emit generated fit methods after record declarations so their receiver type is known
        for f in funcs:
            if getattr(f, 'type_params', None):
                continue
            cname = getattr(f, '_c_name', None) or self.known.get(f.name)
            if not cname:
                continue
            pcs = []
            for p in f.params:
                if p.typ and getattr(p.typ, 'name', None) == 'fn':
                    tn = _fn_type_tag(p.typ)
                else:
                    tn = self.type_name(p.typ) if p.typ else 'i64'
                pcs.append(self.c_type(tn))
            ret = self.type_name(f.ret) if f.ret else 'i64'
            crt = self.c_type(ret)
            pstr = ", ".join(pcs) if pcs else "void"
            if getattr(f, 'external_lib', False):
                out.append(f"extern {crt} {cname}({pstr});")
            else:
                out.append(f"{crt} {cname}({pstr});")
        out.append("")
        self.lines = []
        for f in funcs:
            if getattr(f, 'external_lib', False):
                continue
            if getattr(f, 'type_params', None):
                continue  # generic template — only specialized clones are emitted
            self.gen_fn(f)
        out.extend(self.extra)
        out.extend(self.lines)
        if as_lib:
            pass  # no main
        elif entry_name is not None:
            out += [
                "",
                "int main(int argc, char** argv) {",
                "  terse_argc = argc;",
                "  terse_argv = argv;",
                f"  int64_t result = {self.known[entry_name]}();",
                "  if (!_terse_did_print)",
                '    printf("%lld\\n", (long long)result);',
                "  return (int)result;",
                "}"
            ]
        else:
            out += [
                "",
                "int main(int argc, char** argv) {",
                "  (void)argc; (void)argv;",
                "  return 0;",
                "}"
            ]
        return "\n".join(out)


# --- Terse home / out / lib -----------------------------------------------
def _rewrite_module_expr(e, local_functions, imported_modules):
    if isinstance(e, Var):
        if e.name in local_functions:
            return Var(local_functions[e.name])
        return e
    if isinstance(e, Member):
        if isinstance(e.obj, Var) and e.obj.name in imported_modules:
            exports = imported_modules[e.obj.name]
            if '__builtin_module__' in exports:
                return Member(Var(exports['__builtin_module__']), e.field)
            if e.field not in exports:
                raise SyntaxError(f"module '{e.obj.name}' has no function '{e.field}'")
            return Var(exports[e.field])
        e.obj = _rewrite_module_expr(e.obj, local_functions, imported_modules)
    elif isinstance(e, Call):
        if isinstance(e.func, Var) and e.func.name in local_functions:
            e.func = Var(local_functions[e.func.name])
        else:
            e.func = _rewrite_module_expr(e.func, local_functions, imported_modules)
        e.args = [_rewrite_module_expr(arg, local_functions, imported_modules) for arg in e.args]
    elif isinstance(e, Binary):
        e.left = _rewrite_module_expr(e.left, local_functions, imported_modules)
        e.right = _rewrite_module_expr(e.right, local_functions, imported_modules)
    elif isinstance(e, Unary):
        e.expr = _rewrite_module_expr(e.expr, local_functions, imported_modules)
    elif isinstance(e, RetExpr) and e.value is not None:
        e.value = _rewrite_module_expr(e.value, local_functions, imported_modules)
    elif isinstance(e, IfExpr):
        e.cond = _rewrite_module_expr(e.cond, local_functions, imported_modules)
        e.then = _rewrite_module_expr(e.then, local_functions, imported_modules)
        if e.els is not None:
            e.els = _rewrite_module_expr(e.els, local_functions, imported_modules)
    elif isinstance(e, LetExpr):
        e.value = _rewrite_module_expr(e.value, local_functions, imported_modules)
        e.body = _rewrite_module_expr(e.body, local_functions, imported_modules)
    elif isinstance(e, Lambda):
        e.body = _rewrite_module_expr(e.body, local_functions, imported_modules)
    elif isinstance(e, LoopExpr):
        if e.init is not None:
            e.init = _rewrite_module_expr(e.init, local_functions, imported_modules)
        e.cond = _rewrite_module_expr(e.cond, local_functions, imported_modules)
        if e.post is not None:
            e.post = _rewrite_module_expr(e.post, local_functions, imported_modules)
        e.body = _rewrite_module_expr(e.body, local_functions, imported_modules)
    elif isinstance(e, ForInExpr):
        e.iterable = _rewrite_module_expr(e.iterable, local_functions, imported_modules)
        e.body = _rewrite_module_expr(e.body, local_functions, imported_modules)
    elif isinstance(e, MatchExpr):
        e.subject = _rewrite_module_expr(e.subject, local_functions, imported_modules)
        for arm in e.arms:
            if arm.guard is not None:
                arm.guard = _rewrite_module_expr(arm.guard, local_functions, imported_modules)
            arm.value = _rewrite_module_expr(arm.value, local_functions, imported_modules)
    elif isinstance(e, Block):
        e.stmts = [_rewrite_module_expr(stmt, local_functions, imported_modules) for stmt in e.stmts]
    elif isinstance(e, ListLit):
        e.items = [_rewrite_module_expr(item, local_functions, imported_modules) for item in e.items]
    elif isinstance(e, Index):
        e.coll = _rewrite_module_expr(e.coll, local_functions, imported_modules)
        e.idx = _rewrite_module_expr(e.idx, local_functions, imported_modules)
    elif isinstance(e, RecordLit):
        e.ctor = _rewrite_module_expr(e.ctor, local_functions, imported_modules)
        e.fields = [(name, _rewrite_module_expr(value, local_functions, imported_modules))
                    for name, value in e.fields]
    elif isinstance(e, HttpServe):
        e.port = _rewrite_module_expr(e.port, local_functions, imported_modules)
        for route in e.routes:
            route.handler = _rewrite_module_expr(route.handler, local_functions, imported_modules)
    return e


def _source_module_root(source_path):
    if source_path:
        source_dir = os.path.dirname(os.path.abspath(source_path))
        current = source_dir
        while True:
            if os.path.basename(current) == 'src':
                return current
            parent = os.path.dirname(current)
            if parent == current:
                break
            current = parent
    workspace_src = os.path.abspath(os.path.join(os.getcwd(), 'src'))
    if os.path.isdir(workspace_src):
        return workspace_src
    return os.path.dirname(os.path.abspath(source_path)) if source_path else os.getcwd()


def _is_test_source(source_path):
    """tst/**/t_*.te files are unit tests (auto-run all fns if no go)."""
    if not source_path:
        return False
    path = os.path.abspath(source_path).replace("\\", "/")
    base = os.path.basename(path)
    if not (base.startswith('t_') and base.endswith('.te')):
        return False
    # under a tst directory at any depth: .../tst/t_foo.te or .../tst/usage/t_mod.te
    parts = path.split('/')
    return 'tst' in parts


def _project_roots(source_path):
    """Sibling dirs: src/, tst/, std/ under project root."""
    roots = []
    if source_path:
        d = os.path.dirname(os.path.abspath(source_path))
        # if under tst/ or src/, project root is parent
        if os.path.basename(d) in ('tst', 'src', 'std', 'usage'):
            roots.append(os.path.dirname(d))
        roots.append(d)
        parent = os.path.dirname(d)
        if parent:
            roots.append(parent)
    roots.append(os.getcwd())
    # unique preserve order
    seen = set()
    out = []
    for r in roots:
        r = os.path.realpath(r)
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out


def _auto_test_toplevel(program):
    """Call every zero-arg local test fn; continue after failures; report at end."""
    stmts = []
    for f in program.funcs:
        if f.params:
            continue
        if f.name.startswith('__module_'):
            continue
        stmts.append(Call(Var(f.name), []))
    # tst.report() -> failure count (exit status)
    stmts.append(Call(Member(Var('tst'), 'report'), []))
    return Block(stmts)



def _load_source_modules(program, source_path):
    module_root = os.path.realpath(_source_module_root(source_path))
    cache = {}
    loading = set()
    link_objs = []

    def load_module(use):
        if use.path.startswith('std.'):
            # Prefer on-disk std library if present (next to tersec / cwd / module root)
            rel = use.path.replace('.', os.sep) + '.te'  # std/tst.te
            std_candidates = []
            if source_path:
                src_dir = os.path.dirname(os.path.abspath(source_path))
                # src/../lib/std/tst.te  and same-dir
                std_candidates.append(os.path.join(src_dir, '..', 'lib', rel))
                std_candidates.append(os.path.join(src_dir, rel))
            for root in _project_roots(source_path):
                std_candidates.append(os.path.join(root, 'lib', rel))
                std_candidates.append(os.path.join(root, rel))
            std_candidates.extend([
                os.path.join(os.getcwd(), 'lib', rel),
                os.path.join(os.getcwd(), rel),
                os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'lib', rel),
                os.path.join(os.path.dirname(os.path.abspath(__file__)), rel),
                os.path.join(module_root, '..', 'lib', rel),
                os.path.join(module_root, rel),
            ])
            for cand in std_candidates:
                module_file = os.path.realpath(cand)
                if not os.path.isfile(module_file):
                    continue
                if True:
                    # load Terse std module from lib/ (or std/)
                    use = UseDecl(use.path, use.alias, use.symbol, use.glob)
                    if module_file in cache:
                        return cache[module_file]
                    if module_file in loading:
                        raise SyntaxError(f"cyclic module import involving '{use.path}'")
                    loading.add(module_file)
                    with open(module_file, encoding='utf-8') as module_source:
                        child = Parser(Lexer(module_source.read()).tokenize()).parse_program()
                    # rec/methods/traits allowed; filtered on export
                    public_functions = ({f.name for f in child.funcs} if _is_test_source(source_path)
                        else {f.name for f in child.funcs if f.public})
                    from collections import Counter as _Counter
                    _nc = _Counter(f.name for f in child.funcs)
                    own_functions = {}
                    for f in child.funcs:
                        pts = [_norm_type_name(p.typ) if p.typ else 'i64' for p in f.params]
                        base = f"__module_std_{use.path.replace('.', '_')}_{f.name}"
                        if _nc[f.name] > 1:
                            mangled = base + "__" + "_".join(pts)
                        else:
                            mangled = base
                        # last export mapping for simple names; generate() uses unique f.name
                        own_functions[f.name] = mangled
                        f.name = mangled
                    export_recs = list(child.recs) if _is_test_source(source_path) else [r for r in child.recs if getattr(r, 'public', False)]
                    export_methods = list(child.methods) if _is_test_source(source_path) else [
                        m for m in child.methods if m.public or m.receiver in {r.name for r in export_recs}
                    ]
                    export_enums = list(child.enums) if _is_test_source(source_path) else [
                        e for e in child.enums if getattr(e, 'public', True)
                    ]
                    if not child.funcs and not child.recs and not child.enums:
                        # Comment-only stub — try next candidate / builtin
                        loading.discard(module_file)
                        continue
                    bundle = {
                        'functions': list(child.funcs),
                        'exports': {name: own_functions[name] for name in public_functions if name in own_functions},
                        'fixes': list(getattr(child, 'fixes', []) or []),
                        'recs': export_recs,
                        'methods': export_methods,
                        'sigs': list(child.sigs),
                        'enums': export_enums,
                        'builtin': False,
                    }
                    cache[module_file] = bundle
                    loading.discard(module_file)
                    return bundle
            # Built-in std surface (no .te file): empty exports; calls handled in codegen
            return {'functions': [], 'exports': {}, 'fixes': [], 'recs': [], 'methods': [], 'sigs': [], 'enums': [], 'builtin': True}
        relative = use.path.replace('.', os.sep).replace('/', os.sep)
        if relative.endswith('.te'):
            relative = relative[:-3]
        # Search order: next to the importing file, then module_root, then cwd
        candidates = []
        if source_path:
            src_dir = os.path.dirname(os.path.abspath(source_path))
            # same directory as importer
            candidates.append(os.path.join(src_dir, relative + '.te'))
            # Parallel layout: tst/usage/t_mod.te → src/usage/mod.te
            # Replace /tst/ with /src/ in the importer directory, keep subpath
            norm = src_dir.replace("\\", "/")
            if "/tst/" in norm or norm.endswith("/tst"):
                parallel_dir = norm.replace("/tst/", "/src/").replace("/tst", "/src")
                candidates.append(os.path.join(parallel_dir, relative + ".te"))
                # also src/<same relative under tst>
                # e.g. tst/usage → src/usage already handled by parallel_dir
            # preferred roots: lib/ (optional packages), src/, project root
            for root in _project_roots(source_path):
                candidates.append(os.path.join(root, 'lib', relative + '.te'))
                candidates.append(os.path.join(root, 'src', relative + '.te'))
                # if test lives in tst/<sub>/, also try src/<sub>/<module>
                if "/tst/" in norm:
                    sub = norm.split("/tst/", 1)[-1]  # e.g. "usage" or "usage/nested"
                    if sub and sub != norm:
                        candidates.append(os.path.join(root, 'src', sub, relative + '.te'))
                        candidates.append(os.path.join(root, 'lib', sub, relative + '.te'))
            for root in _project_roots(source_path):
                candidates.append(os.path.join(root, relative + '.te'))
            parent = os.path.dirname(src_dir)
            if parent:
                candidates.append(os.path.join(parent, 'lib', relative + '.te'))
                candidates.append(os.path.join(parent, relative + '.te'))
        candidates.append(os.path.join(module_root, 'lib', relative + '.te'))
        candidates.append(os.path.join(module_root, relative + '.te'))
        candidates.append(os.path.join(os.getcwd(), 'lib', relative + '.te'))
        candidates.append(os.path.join(os.getcwd(), relative + '.te'))
        module_file = None
        for cand in candidates:
            cand = os.path.realpath(cand)
            if os.path.isfile(cand):
                module_file = cand
                break
        if module_file is None:
            tried = ', '.join(os.path.realpath(c) for c in candidates)
            raise SyntaxError(
                f"module '{use.path}' not found\n"
                f"  searched: {tried}\n"
                f"  hint: optional packages in lib/ (use math -> lib/math.te); app modules in src/ "
                f"(dots map to paths: use usage.util -> src/usage/util.te)"
            )
        try:
            # stay under workspace-ish roots when possible
            pass
        except ValueError:
            raise SyntaxError(f"invalid module path: '{use.path}'")
        if module_file in loading:
            raise SyntaxError(f"cyclic module import involving '{use.path}'")
        if module_file in cache:
            return cache[module_file]

        loading.add(module_file)
        with open(module_file, encoding='utf-8') as module_source:
            child = Parser(Lexer(module_source.read()).tokenize()).parse_program()
        # rec/methods/traits allowed; filtered on export

        functions_by_name = {}
        child_namespaces = {}
        child_symbols = {}
        for child_use in child.uses:
            if child_use.path.startswith('std.'):
                builtin = child_use.path.split('.')[-1]
                if child_use.alias != builtin:
                    child_namespaces[child_use.alias] = {'__builtin_module__': builtin}
                continue
            child_module = load_module(child_use)
            if child_use.glob:
                for name, qualified in child_module['exports'].items():
                    if name in child_symbols or name in child_namespaces:
                        raise SyntaxError(f"duplicate imported name '{name}' in '{use.path}'")
                    child_symbols[name] = qualified
            elif child_use.symbol:
                if child_use.alias in child_namespaces or child_use.alias in child_symbols:
                    raise SyntaxError(f"duplicate import name '{child_use.alias}' in '{use.path}'")
                if child_use.symbol not in child_module['exports']:
                    raise SyntaxError(f"module '{child_use.path}' has no function '{child_use.symbol}'")
                child_symbols[child_use.alias] = child_module['exports'][child_use.symbol]
            else:
                if child_use.alias in child_namespaces or child_use.alias in child_symbols:
                    raise SyntaxError(f"duplicate import name '{child_use.alias}' in '{use.path}'")
                child_namespaces[child_use.alias] = child_module['exports']
            for function in child_module['functions']:
                functions_by_name[function.name] = function

        prefix = re.sub(r'\W', '_', os.path.relpath(module_file, module_root)[:-3])
        # From tst/t_*.te, allow non-pub symbols of the module under test
        if _is_test_source(source_path):
            public_functions = {function.name for function in child.funcs}
        else:
            public_functions = {function.name for function in child.funcs if function.public}
        from collections import Counter as _Counter2
        _nc2 = _Counter2(function.name for function in child.funcs)
        own_functions = {}
        for function in child.funcs:
            pts = [_norm_type_name(p.typ) if p.typ else 'i64' for p in function.params]
            base = f"__module_{prefix}_{function.name}"
            mangled = (base + "__" + "_".join(pts)) if _nc2[function.name] > 1 else base
            own_functions[function.name] = mangled  # last wins for rewrite of simple calls
            function._orig_name = function.name
            function.name = mangled
        local_functions = dict(child_symbols)
        # Allow same source name only via overloads (already mangled unique)
        local_functions.update({function._orig_name: function.name for function in child.funcs
                                if _nc2[function._orig_name] == 1})
        # For overloads, rewrite of unqualified name is ambiguous — leave mangled in program only
        # fix: private by default — rename file-local constants so they are not importable
        processed_fixes = []
        for fx in child.fixes:
            if fx.public:
                processed_fixes.append(fx)
            else:
                internal = f"__module_{prefix}_fix_{fx.name}"
                local_functions[fx.name] = internal
                processed_fixes.append(FixDecl(internal, fx.value, fx.typ, public=False))
        child.fixes = processed_fixes
        for function in child.funcs:
            function.body = _rewrite_module_expr(function.body, local_functions, child_namespaces)
            # name already mangled above
            functions_by_name[function.name] = function

        try:
            import os as _os
            if _os.environ.get("TERSE_AUTOLIB") == "1":
                key = module_lib_key(use.path)
                if lib_is_fresh(key, [module_file]):
                    for function in functions_by_name.values():
                        function.external_lib = True
                    link_objs.append(lib_obj_path(key))
                else:
                    obj = ensure_module_lib(module_file, use.path, verbose=False, force=False)
                    if obj and os.path.isfile(obj):
                        for function in functions_by_name.values():
                            function.external_lib = True
                        link_objs.append(obj)
        except Exception:
            pass

        if _is_test_source(source_path):
            export_recs = list(child.recs)
            export_methods = list(child.methods)
            export_sigs = list(child.sigs)
        else:
            export_recs = [r for r in child.recs if r.public]
            # methods on exported types, or explicitly public methods
            rec_names = {r.name for r in export_recs}
            export_methods = [
                m for m in child.methods
                if m.public or m.receiver in rec_names
            ]
            export_sigs = list(child.sigs)  # traits are type-level; export all for now
        # Rewrite method bodies with local module function map
        for m in export_methods:
            m.body = _rewrite_module_expr(m.body, local_functions, child_namespaces)
        if _is_test_source(source_path):
            export_enums = list(child.enums)
        else:
            export_enums = [e for e in child.enums if getattr(e, 'public', True)]
        bundle = {
            'functions': list(functions_by_name.values()),
            'exports': {name: own_functions[name] for name in public_functions},
            'fixes': list(child.fixes),
            'recs': export_recs,
            'methods': export_methods,
            'sigs': export_sigs,
            'enums': export_enums,
        }
        cache[module_file] = bundle
        loading.remove(module_file)
        return bundle

    namespaces = {}
    imported_symbols = {}
    imported_functions = {}
    imported_fixes = []
    imported_recs = []
    imported_methods = []
    imported_sigs = []
    imported_enums = []
    for use in program.uses:
        if use.path.startswith('std.'):
            builtin = use.path.split('.')[-1]
            if use.alias in namespaces or use.alias in imported_symbols:
                raise SyntaxError(f"duplicate import name '{use.alias}'")
            # Prefer lib/std/*.te; fall back to host builtin sugar
            module = load_module(use)
            if module.get('functions'):
                namespaces[use.alias] = {'__builtin_module__': builtin}
                namespaces[use.alias].update(module.get('exports') or {})
                for function in module['functions']:
                    imported_functions[function.name] = function
                for fx in module.get('fixes') or []:
                    imported_fixes.append(fx)
                continue
            namespaces[use.alias] = {'__builtin_module__': builtin}
            continue
        module = load_module(use)
        if use.glob:
            for name, qualified in module['exports'].items():
                if name in imported_symbols or name in namespaces:
                    raise SyntaxError(f"duplicate imported name '{name}'")
                imported_symbols[name] = qualified
        elif use.symbol:
            if use.alias in namespaces or use.alias in imported_symbols:
                raise SyntaxError(f"duplicate import name '{use.alias}'")
            if use.symbol not in module['exports']:
                raise SyntaxError(f"module '{use.path}' has no function '{use.symbol}'")
            imported_symbols[use.alias] = module['exports'][use.symbol]
        else:
            if use.alias in namespaces or use.alias in imported_symbols:
                raise SyntaxError(f"duplicate import name '{use.alias}'")
            namespaces[use.alias] = module['exports']
            # In tst/**/t_*.te: unqualified calls (use mod → mod())
            # Function names win over module alias when they share a name
            if _is_test_source(source_path):
                for name, qualified in module['exports'].items():
                    if name not in imported_symbols:
                        imported_symbols[name] = qualified
        for function in module['functions']:
            imported_functions[function.name] = function
        for fx in module.get('fixes') or []:
            imported_fixes.append(fx)
        for rec in module.get('recs') or []:
            imported_recs.append(rec)
        for m in module.get('methods') or []:
            imported_methods.append(m)
        for sg in module.get('sigs') or []:
            imported_sigs.append(sg)
        for en in module.get('enums') or []:
            imported_enums.append(en)

    for function in program.funcs:
        function.body = _rewrite_module_expr(function.body, imported_symbols, namespaces)
    if set(imported_symbols).intersection(function.name for function in program.funcs):
        raise SyntaxError("glob or selective import conflicts with a local function")
    if program.toplevel is not None:
        program.toplevel = _rewrite_module_expr(program.toplevel, imported_symbols, namespaces)
    program.funcs.extend(imported_functions.values())
    # Module fix constants become available to the importer (and module fn bodies)
    existing = {f.name for f in program.fixes}
    for fx in imported_fixes:
        if fx.name not in existing:
            program.fixes.append(fx)
            existing.add(fx.name)
    existing_recs = {r.name for r in program.recs}
    for rec in imported_recs:
        if rec.name not in existing_recs:
            program.recs.append(rec)
            existing_recs.add(rec.name)
    # methods: avoid exact duplicates (receiver, name)
    existing_methods = {(m.receiver, m.name) for m in program.methods}
    for m in imported_methods:
        key = (m.receiver, m.name)
        if key not in existing_methods:
            program.methods.append(m)
            existing_methods.add(key)
    existing_sigs = {sg.name for sg in program.sigs}
    for sg in imported_sigs:
        if sg.name not in existing_sigs:
            program.sigs.append(sg)
            existing_sigs.add(sg.name)
    existing_enums = {e.name for e in program.enums}
    for en in imported_enums:
        if en.name not in existing_enums:
            program.enums.append(en)
            existing_enums.add(en.name)
    return program


def terse_home():
    return os.path.expanduser(os.environ.get("TERSE_HOME", os.path.join("~", ".terse")))

def terse_out_dir():
    d = os.environ.get("TERSE_OUT") or os.path.join(terse_home(), "out")
    os.makedirs(d, exist_ok=True)
    return d

def terse_lib_dir():
    d = os.environ.get("TERSE_LIB") or os.path.join(terse_out_dir(), "lib")
    os.makedirs(d, exist_ok=True)
    return d

def resolve_output_path(source_path, output=None):
    if output:
        out = os.path.expanduser(output)
        if not os.path.isabs(out) and os.path.dirname(out) in ("", "."):
            out = os.path.join(terse_out_dir(), os.path.basename(out))
        parent = os.path.dirname(os.path.abspath(out))
        if parent:
            os.makedirs(parent, exist_ok=True)
        return out
    stem = os.path.splitext(os.path.basename(source_path or "a.out"))[0]
    return os.path.join(terse_out_dir(), stem)

def module_lib_key(use_path):
    return use_path.replace(".", os.sep)

def module_lib_dir(key):
    d = os.path.join(terse_lib_dir(), key)
    os.makedirs(d, exist_ok=True)
    return d

def lib_meta_path(name):
    return os.path.join(module_lib_dir(name), "module.meta")

def lib_obj_path(name):
    return os.path.join(module_lib_dir(name), "module.o")

def write_lib_meta(name, sources, extra=None):
    import json
    meta = {
        "name": name,
        "sources": [os.path.abspath(p) for p in sources],
        "mtimes": {os.path.abspath(p): os.path.getmtime(p) for p in sources if os.path.isfile(p)},
    }
    if extra:
        meta.update(extra)
    with open(lib_meta_path(name), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

def lib_is_fresh(name, sources):
    import json
    obj, meta_p = lib_obj_path(name), lib_meta_path(name)
    if not (os.path.isfile(obj) and os.path.isfile(meta_p)):
        return False
    try:
        meta = json.loads(open(meta_p, encoding="utf-8").read())
    except Exception:
        return False
    for pth in sources:
        ap = os.path.abspath(pth)
        try:
            if meta.get("mtimes", {}).get(ap) != os.path.getmtime(ap):
                return False
        except OSError:
            return False
    return set(meta.get("sources") or []) == set(os.path.abspath(p) for p in sources)

def ensure_module_lib(module_file, use_path, verbose=False, force=False):
    key = module_lib_key(use_path)
    if not force and lib_is_fresh(key, [module_file]):
        return lib_obj_path(key)
    with open(module_file, encoding="utf-8") as f:
        src = f.read()
    code = compile_terse(src, None, keep_c=False, verbose=verbose, source_path=module_file,
                         as_lib=True, force=True, lib_key=key)
    if code != 0:
        return None
    return lib_obj_path(key) if os.path.isfile(lib_obj_path(key)) else None

def compile_terse(src, out_bin, keep_c=False, verbose=False, source_path=None,
                  as_lib=False, link_libs=True, force=False, lib_key=None):
    try:
        source_path = source_path or "input.te"
        deps = [os.path.abspath(source_path)] if os.path.isfile(source_path) else []
        toks = Lexer(src).tokenize()
        if verbose:
            print("tokens:", [(t.t.name, t.v) for t in toks[:40]])
        prog = _load_source_modules(Parser(toks).parse_program(), source_path)
        if prog.toplevel is None and _is_test_source(source_path):
            prog.toplevel = _auto_test_toplevel(prog)
        if verbose:
            print("funcs:", [f.name for f in prog.funcs])
        errs = TypeChecker().check_program(prog)
        fatal = [e for e in errs if (
            e.startswith("type error")
            or e.startswith("unknown")
            or "unknown name" in e
            or "unknown function" in e
            or "does not match" in e
            or "cannot assign" in e
            or "cannot concat" in e
            or "cannot push" in e
            or "cannot compare" in e
            or "list element" in e
            or "declared" in e and "but value" in e
        )]
        for e in errs:
            is_fatal = (
                e in fatal or e.startswith("unknown") or "unknown " in e
                or e.startswith("type error")
            )
            if is_fatal:
                msg = e if e.startswith("type error") or e.startswith("unknown") else f"type error: {e}"
                print(msg, file=sys.stderr)
            else:
                msg = e if e.startswith("type") else f"type warning: {e}"
                print(msg, file=sys.stderr)
        if fatal:
            return 1

        if as_lib:
            key = lib_key or module_lib_key(os.path.splitext(os.path.basename(source_path))[0])
            if lib_key is None and source_path:
                ap = os.path.abspath(source_path).replace("\\", "/")
                for marker in ("/src/", "/std/", "/usage/"):
                    if marker in ap:
                        key = os.path.splitext(ap.split(marker, 1)[1])[0]
                        break
            out_obj = lib_obj_path(key)
            if not force and lib_is_fresh(key, deps):
                if verbose: print(f"Up to date -> {out_obj}")
                return 0
            prefix = re.sub(r"\W", "_", key)
            for f in prog.funcs:
                if not f.name.startswith("__module_"):
                    f.name = f"__module_{prefix}_{f.name}"
            c_code = CodeGen(source_path).generate(prog, source_path=source_path, as_lib=True, skip_runtime=True)
            c_file = os.path.join(module_lib_dir(key), "module.c")
            with open(c_file, "w", encoding="utf-8") as f:
                f.write(c_code)
            cc = os.environ.get("CC", "gcc")
            r = subprocess.run(
                [cc, "-O0", "-std=c11", "-c", c_file, "-o", out_obj,
                 "-Wno-unused-function", "-Wno-unused-parameter", "-Wno-unused-value"],
                capture_output=True, text=True)
            if r.returncode != 0:
                print("C compile failed:", file=sys.stderr)
                print(r.stderr, file=sys.stderr)
                return 1
            write_lib_meta(key, deps, extra={"use_path": key.replace(os.sep, ".")})
            if not keep_c:
                try: os.remove(c_file)
                except OSError: pass
            if verbose: print(f"Library -> {out_obj}")
            return 0

        out_bin = resolve_output_path(source_path, out_bin)
        gcc_out = out_bin
        if sys.platform == "win32" and os.path.splitext(out_bin)[1].lower() != ".exe":
            gcc_out = out_bin + ".exe"

        if not force and os.path.isfile(gcc_out) and deps:
            try:
                bmt = os.path.getmtime(gcc_out)
                if all(os.path.getmtime(d) <= bmt for d in deps if os.path.isfile(d)):
                    if verbose: print(f"Up to date -> {out_bin}")
                    return 0
            except OSError:
                pass

        c_code = CodeGen(source_path).generate(prog, source_path=source_path, as_lib=False, skip_runtime=False)
        c_file = out_bin + ".c"
        os.makedirs(os.path.dirname(os.path.abspath(c_file)) or ".", exist_ok=True)
        with open(c_file, "w", encoding="utf-8") as f:
            f.write(c_code)
        if verbose:
            print("----- C -----"); print(c_code[:1200]); print("-----")

        cc = os.environ.get("CC", "gcc")
        link_objs = []
        if link_libs:
            preferred = getattr(prog, "_link_objs", None) or []
            seen, main_src = set(), os.path.abspath(source_path) if source_path else ""
            for lo in preferred:
                lo_abs = os.path.abspath(lo)
                if lo_abs in seen:
                    continue
                skip = False
                meta = os.path.join(os.path.dirname(lo_abs), "module.meta")
                if main_src and os.path.isfile(meta):
                    try:
                        import json
                        m = json.loads(open(meta, encoding="utf-8").read())
                        if main_src in [os.path.abspath(x) for x in (m.get("sources") or [])]:
                            skip = True
                    except Exception:
                        pass
                if skip:
                    continue
                seen.add(lo_abs)
                link_objs.append(lo_abs)
                if verbose:
                    print(f"link module lib {lo_abs}")

        if link_objs:
            main_obj = out_bin + ".o"
            r = subprocess.run(
                [cc, "-O0", "-std=c11", "-c", c_file, "-o", main_obj,
                 "-Wno-unused-function", "-Wno-unused-parameter", "-Wno-unused-value", "-Wno-parentheses"],
                capture_output=True, text=True)
            if r.returncode != 0:
                print("C compile failed:", file=sys.stderr)
                err = (r.stderr or r.stdout or "").strip()
                if err:
                    # First real error line for quicker scan
                    for line in err.splitlines():
                        if "error:" in line.lower():
                            print(line, file=sys.stderr)
                            break
                    print(err, file=sys.stderr)
                return 1
            cmd_l = [cc, "-O0", "-std=c11", "-o", gcc_out, main_obj] + link_objs
            if sys.platform == "win32":
                cmd_l.extend(["-lws2_32", "-mconsole"])
            r = subprocess.run(cmd_l, capture_output=True, text=True)
            if r.returncode != 0:
                print("C link failed:", file=sys.stderr); print(r.stderr, file=sys.stderr); return 1
            try: os.remove(main_obj)
            except OSError: pass
        else:
            cmd = [cc, "-O0", "-std=c11",
                   "-Wno-unused-function", "-Wno-unused-parameter", "-Wno-unused-value",
                   "-Wno-parentheses", c_file, "-o", gcc_out]
            if sys.platform == "win32":
                cmd.extend(["-lws2_32", "-mconsole"])
            r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode != 0:
                print("C compile failed:", file=sys.stderr)
                err = (r.stderr or r.stdout or "").strip()
                if err:
                    # First real error line for quicker scan
                    for line in err.splitlines():
                        if "error:" in line.lower():
                            print(line, file=sys.stderr)
                            break
                    print(err, file=sys.stderr)
                return 1

        if sys.platform == "win32" and gcc_out != out_bin and os.path.exists(gcc_out):
            shutil.copy2(gcc_out, out_bin)
            try: os.remove(gcc_out)
            except OSError: pass
        if not keep_c:
            try: os.remove(c_file)
            except OSError: pass
        try:
            os.chmod(out_bin, 0o755)
        except OSError:
            pass
        if verbose: print(f"Compiled -> {out_bin}")
        return 0
    except SyntaxError as e:
        print(f"Syntax error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback; traceback.print_exc()
        return 1

def main():
    ap = argparse.ArgumentParser(description="tersec — out ~/.terse/out; libs ~/.terse/out/lib/<mod>/")
    ap.add_argument("-v", "--version", action="store_true",
                    help="print version (0.3) and exit")
    ap.add_argument("-a", "--announce", action="store_true",
                    help="print 'compile <file>' before building")
    ap.add_argument("--verbose", action="store_true",
                    help="extra debug (tokens, funcs, C snippet)")
    ap.add_argument("command", nargs="?", choices=["build", "run", "check", "lib"])
    ap.add_argument("source", nargs="?")
    ap.add_argument("-o", "--output", default=None)
    ap.add_argument("--keep-c", action="store_true")
    ap.add_argument("-f", "--force", action="store_true")
    ap.add_argument("--no-libs", action="store_true")
    args = ap.parse_args()
    if args.version:
        print(f"tersec {TERSE_VERSION}")
        sys.exit(0)
    if not args.command or not args.source:
        ap.error("command and source are required (unless -v)")
    if args.announce:
        print(f"compile {args.source}")
    with open(args.source, encoding="utf-8") as f:
        src = f.read()
    if args.command == "check":
        try:
            prog = _load_source_modules(Parser(Lexer(src).tokenize()).parse_program(), args.source)
            if prog.toplevel is None and _is_test_source(args.source):
                prog.toplevel = _auto_test_toplevel(prog)
            errs = TypeChecker().check_program(prog)
            if errs:
                for e in errs: print(e)
                sys.exit(1)
            print("OK"); sys.exit(0)
        except Exception as e:
            print(e); sys.exit(1)
    if args.command == "lib":
        sys.exit(compile_terse(src, args.output, args.keep_c, args.verbose, args.source,
                               as_lib=True, force=args.force))
    if args.command == "build":
        sys.exit(compile_terse(src, args.output, args.keep_c, args.verbose, args.source,
                               as_lib=False, link_libs=not args.no_libs, force=args.force))
    if args.command == "run":
        code = compile_terse(src, args.output, args.keep_c, args.verbose, args.source,
                             as_lib=False, link_libs=not args.no_libs, force=args.force)
        if code != 0: sys.exit(code)
        sys.exit(subprocess.run([os.path.abspath(resolve_output_path(args.source, args.output))]).returncode)


if __name__ == "__main__":
    main()
