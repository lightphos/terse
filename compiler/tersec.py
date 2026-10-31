#!/usr/bin/env python3
"""
Terse Compiler (tersec) 0.1beta
Native binary via C. Strings, lists, pr, http.serve (minimal socket server).
"""
import sys, os, re, shutil, subprocess, argparse, copy

TERSE_VERSION = "0.3"
from typing import List, Optional, Dict, Any, Tuple

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

try:
    from .codegen import CodeGen, get_runtime
except ImportError:
    from tersec.codegen import CodeGen, get_runtime

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
