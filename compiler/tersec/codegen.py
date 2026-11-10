"""Terse C code generator — AST to C."""
from __future__ import annotations

import os
from typing import List, Optional, Dict, Any, Tuple

from .lexer import TT, Tok, Lexer
from .ast import (
    TypeNode, Param, Expr, IntLit, FloatLit, BoolLit, StrLit, Var,
    Binary, Unary, AwaitExpr, Call, Member, IfExpr, TernaryExpr, LetExpr,
    RetExpr, JumpExpr, Lambda, LoopExpr, ForInExpr, AssignExpr,
    Block, ListLit, MapLit, Index, SliceExpr, FnDecl, TrapExpr, TupleLit, TupleLetExpr,
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

def get_runtime() -> str:
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "runtime.c")
    with open(path, encoding="utf-8") as f:
        return f.read()

class CodeGen:

    def rt_num(self, t: str) -> str:
        """Map surface numeric/list elem name to runtime.c suffix (i64, i32, ...)."""
        return {
            'long': 'i64', 'int': 'i32', 'chr': 'i8', 'byte': 'u8',
            'flt': 'f32', 'dbl': 'f64', 'str': 'str',
            'list_long': 'list_i64', 'list_int': 'list_i32', 'list_chr': 'list_i8',
            'list_flt': 'list_f32', 'list_dbl': 'list_f64',
            'map_str_long': 'map_str_i64',
        }.get(t, t)

    def __init__(self, source_path=None):
        self.lines = []
        self.indent = 0
        self.lam_n = 0
        self.extra = []
        self.known = {}
        self.async_fns = set()  # names of ~~ async functions
        self.async_loop_fns = set()  # ~~> event-loop tasks
        self._await_depth = 0
        self.tmp = 0
        self.env = {}
        self.var_aliases = {}
        self.source_path = source_path or "?"
        self.route_handlers = []  # generated C funcs for routes
        self.record_field_types = {}
        self.method_names = {}
        self.method_returns = {}
        self.interface_methods = {}
        self.interface_method_returns = {}
        self.interface_helpers = {}
        self.generic_traits = {}
        self.generic_trait_instances = {}
        self.enum_values = {}  # enum name -> {variant: value}
        self.func_param_types = {}
        self.func_return_types = {}
        self.tuple_types = {}
        self.current_return_type = None

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
        if ty in ('List', 'list', 'list_long'):
            return '(List_i64){NULL,0,0}'
        if isinstance(ty, str) and ty.startswith('list_'):
            return f'(List_{self.rt_num(ty[5:])}){{NULL,0,0}}'
        if ty == 'map_str_long':
            return '(Map_str_i64){NULL,NULL,0,0}'
        if ty == 'map_str_str':
            return '(Map_str_str){NULL,NULL,0,0}'
        if isinstance(ty, str) and ty.startswith('map_'):
            cname = 'Map_' + '_'.join(ty.split('_')[1:])
            return f'({cname}){{NULL,NULL,0,0}}'
        if ty in getattr(self, 'record_field_types', {}) or ty in getattr(self, 'enum_values', {}):
            return f'({self.c_type(ty)}){{0}}'
        if isinstance(ty, str) and ty.startswith('tuple__'):
            return f'({self.c_type(ty)}){{0}}'
        return 'INT64_C(0)'

    def tst_where(self, e=None):
        path = self.source_path.replace("\\", "/").replace('"', "")
        line = (getattr(e, "line", 0) or 0) if e is not None else 0
        return f'"{path}", INT64_C({line})'

    def fresh(self):
        self.tmp += 1
        return f"_t{self.tmp}"

    def _lambda_free_vars(self, e, bound):
        """Names referenced in e that are not in bound (params/locals)."""
        from .ast import (
            Var, Lambda, Call, Member, Binary, Unary, AwaitExpr, IfExpr, TernaryExpr,
            LetExpr, Block, ListLit, MapLit, RecordLit, RetExpr, AssignExpr, LoopExpr,
            ForInExpr, TupleLit,
        )
        found = set()
        def walk(node, bound):
            if node is None:
                return
            if isinstance(node, Var):
                if node.name not in bound:
                    found.add(node.name)
                return
            if isinstance(node, Lambda):
                b2 = set(bound)
                for p in node.params:
                    b2.add(p.name)
                walk(node.body, b2)
                return
            if isinstance(node, LetExpr):
                walk(node.value, bound)
                b2 = set(bound)
                b2.add(node.name)
                walk(node.body, b2)
                return
            if isinstance(node, Block):
                b2 = set(bound)
                for st in node.stmts:
                    if isinstance(st, LetExpr):
                        walk(st.value, b2)
                        b2.add(st.name)
                        if st.body is not None:
                            walk(st.body, b2)
                    else:
                        walk(st, b2)
                return
            if isinstance(node, Call):
                walk(node.func, bound)
                for a in node.args:
                    walk(a, bound)
                return
            if isinstance(node, Member):
                walk(node.obj, bound)
                return
            if isinstance(node, Binary):
                walk(node.left, bound); walk(node.right, bound); return
            if isinstance(node, Unary):
                walk(node.expr, bound); return
            if isinstance(node, AwaitExpr):
                walk(node.value, bound); return
            if isinstance(node, IfExpr):
                walk(node.cond, bound); walk(node.then, bound)
                if node.els is not None:
                    walk(node.els, bound)
                return
            if isinstance(node, TernaryExpr):
                walk(node.cond, bound); walk(node.then, bound); walk(node.els, bound); return
            if isinstance(node, RetExpr) and node.value is not None:
                walk(node.value, bound); return
            if isinstance(node, AssignExpr):
                walk(node.target, bound); walk(node.value, bound); return
            if isinstance(node, ListLit):
                for it in node.items: walk(it, bound)
                return
            if isinstance(node, TupleLit):
                for it in node.items: walk(it, bound)
                return
            if isinstance(node, MapLit):
                for k, v in node.entries:
                    walk(k, bound); walk(v, bound)
                return
            if isinstance(node, RecordLit):
                walk(node.ctor, bound)
                for _, v in node.fields:
                    walk(v, bound)
                return
            if isinstance(node, LoopExpr):
                if node.init: walk(node.init, bound)
                walk(node.cond, bound)
                if node.post: walk(node.post, bound)
                walk(node.body, bound)
                return
            if isinstance(node, ForInExpr):
                walk(node.iterable, bound)
                b2 = set(bound); b2.add(node.var)
                walk(node.body, b2)
                return
        walk(e, set(bound))
        return sorted(found)



    def type_name(self, typ):
        if typ is None:
            return 'long'
        if typ.name in self.generic_traits and typ.args:
            return _mangle_generic(
                typ.name, [_type_node_name(arg) for arg in typ.args]
            )
        if typ.name == 'tuple':
            items = [self.type_name(arg) for arg in typ.args]
            name = 'tuple__' + '__'.join(items)
            self.tuple_types[name] = items
            return name
        if typ.name == 'list' and typ.args:
            inner = self.type_name(typ.args[0])
            if inner == 'str':
                return 'list_str'
            return f"list_{inner}"
        if typ.name == 'map' and len(typ.args) >= 2:
            return f"map_{self.type_name(typ.args[0])}_{self.type_name(typ.args[1])}"
        return typ.name


    def record_print_code(self, rec):
        values = []
        for field_name, field_type in rec.fields:
            typ = self.type_name(field_type)
            value = f"row.{field_name}"
            if typ == 'str':
                values.append(f'printf("%s", {value})')
            elif typ == 'bool':
                values.append(f'printf("%s", {value} ? "true" : "false")')
            elif typ == 'dbl':
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


    def c_type(self, t):
        if isinstance(t, str) and t.startswith('tuple__'):
            return 'Terse_' + t
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
            if inner == 'str':
                return 'List_str'
            # surface long/int/chr → runtime List_i64 / List_i32 / List_i8
            rt = {'long': 'i64', 'int': 'i32', 'chr': 'i8', 'byte': 'u8',
                  'flt': 'f32', 'dbl': 'f64'}.get(inner, inner)
            return f"List_{rt}"
        if t.startswith('map_'):
            # map_str_long → Map_str_i64
            rest = t[4:]  # str_long
            parts = rest.split('_', 1)
            if len(parts) == 2:
                k, v = parts
                v = {'long': 'i64', 'int': 'i32'}.get(v, v)
                return f"Map_{k}_{v}"
            return 'Map_' + rest
        return {'fn':'void*','str':'const char*','list':'List_i64','List':'List_i64',
                'long':'int64_t','int':'int32_t','chr':'int8_t','byte':'uint8_t',
                'bool':'bool','dbl':'double','flt':'float',
                'list_long':'List_i64','list_int':'List_i32','list_chr':'List_i8',
                'list_flt':'List_f32','list_dbl':'List_f64',
                'map_str_long':'Map_str_i64','map_str_int':'Map_str_i64',
                }.get(t, t)

    def expr_type(self, e) -> str:
        if isinstance(e, StrLit):
            return 'str'
        if isinstance(e, IntLit):
            return 'long'
        if isinstance(e, FloatLit):
            return 'dbl'
        if isinstance(e, BoolLit):
            return 'bool'
        if isinstance(e, TupleLit):
            item_types = [self.expr_type(item) for item in e.items]
            tuple_type = 'tuple__' + '__'.join(item_types)
            self.tuple_types.setdefault(tuple_type, item_types)
            return tuple_type
        if isinstance(e, ListLit):
            if e.items:
                return 'list_' + self.expr_type(e.items[0]) if self.expr_type(e.items[0]) != 'long' else 'list'
            return 'list'
        if isinstance(e, Call) and isinstance(e.func, Var):
            n = e.func.name
            if n in ('has', 'starts', 'ends'): return 'bool'
            if n in ('trim', 'join', 'substr'): return 'str'
            if n == 'split': return 'list_str'
            if n == 'parse': return 'long'
        if isinstance(e, Var):
            return self.env.get(e.name, 'long')
        if isinstance(e, Call) and isinstance(e.func, Member) and isinstance(e.func.obj, Var) and e.func.obj.name in self.enum_values:
            return e.func.obj.name
        if isinstance(e, Call) and isinstance(e.func, Var):
            return self.func_return_types.get(e.func.name, 'long')
        if isinstance(e, RecordLit):
            return e.ctor.name if isinstance(e.ctor, Var) else 'record'
        if isinstance(e, MapLit):
            if not e.entries:
                return 'map_str_long'
            # rough: check value side
            return 'map_str_long'
        if isinstance(e, Member):
            if isinstance(e.obj, Var) and e.obj.name in self.enum_values:
                return e.obj.name
            base_type = self.expr_type(e.obj)
            if base_type in ('List', 'list') or (isinstance(base_type, str) and base_type.startswith('list_')):
                if e.field in ('size', 'len'):
                    return 'long'
            return self.record_field_types.get(base_type, {}).get(e.field, 'long')
        return 'long'


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
                if expected in self.interface_methods and vt in self.record_field_types:
                    helper = self.interface_helpers.get((expected, vt))
                    if helper:
                        v = f"{helper}(&({v}))"
                vt = self.type_name(e.typ)
            # Empty typed lists must use typed list_new_* even if inference missed
            if expected and expected.startswith('list_'):
                elem = expected[5:]
                if 'list_new(' in v and 'list_new_' not in v:
                    v = f"({{ List_{self.rt_num(elem)} _le = list_new_{self.rt_num(elem)}(0); _le; }})"
                    vt = expected
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
            if expected_type == 'dbl':
                return f"((double){e.value})", "dbl"
            if expected_type in ('int', 'i16', 'chr', 'u32', 'u16', 'char'):
                return f"(({self.c_type(expected_type)})INT64_C({e.value}))", expected_type
            return f"INT64_C({e.value})", "long"
        if isinstance(e, FloatLit):
            return f"((double){e.value})", "dbl"
        if isinstance(e, BoolLit):
            return ("true" if e.value else "false"), "bool"
        if isinstance(e, StrLit):
            s = e.value.replace('\\','\\\\').replace('"','\\"').replace('\r','\\r').replace('\n','\\n').replace('\t','\\t')
            return f'"{s}"', "str"
        if isinstance(e, TupleLit):
            expected_items = self.tuple_types.get(expected_type, [])
            item_codes = []
            item_types = []
            for i, item in enumerate(e.items):
                expected = expected_items[i] if i < len(expected_items) else None
                code, item_type = self.gen_expr(item, expected)
                item_codes.append(f".v{i} = {code}")
                item_types.append(expected or item_type)
            tuple_type = expected_type or ('tuple__' + '__'.join(item_types))
            self.tuple_types.setdefault(tuple_type, item_types)
            return f"(({self.c_type(tuple_type)}){{ {', '.join(item_codes)} }})", tuple_type
        if isinstance(e, RecordLit):
            rec_name = e.ctor.name if isinstance(e.ctor, Var) else 'record'
            parts = []
            for name, val in e.fields:
                expected_type = self.record_field_types.get(rec_name, {}).get(name)
                v, _ = self.gen_expr(val, expected_type)
                parts.append(f".{name} = {v}")
            return f"(({rec_name}){{ {', '.join(parts)} }})", rec_name
        if isinstance(e, Var):
            if e.name in self.var_aliases:
                al = self.var_aliases[e.name]
                ty = self.env.get(e.name, "long")
                if "_s)" in al or al.rstrip(")").endswith("_s"):
                    ty = "str"
                return al, ty
            if e.name in self.known:
                return f"((void*)terse_clos_new((void*){self.known[e.name]}, NULL))", "fn"
            if e.name in self.env:
                return e.name, self.env[e.name]
            # top-level fix constant
            for c in getattr(self, 'const_decls', []) or []:
                if c.name == e.name:
                    tn = self.env.get(c.name, 'long')
                    return e.name, tn
            # Last resort — still emit (legacy); prefer typechecker fatal above
            return e.name, self.env.get(e.name, "long")
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
                ret_type = self.interface_method_returns.get((btype, e.field), 'long')
                return f"(({base}).{e.field})", btype
            # List .size / .len
            if btype in ('List', 'list') or (isinstance(btype, str) and btype.startswith('list_')):
                if e.field in ('size', 'len'):
                    if btype.startswith('list_'):
                        return f"list_len_{self.rt_num(btype[5:])}({base})", "long"
                    return f"list_len_i64({base})", "long"
            field_type = self.record_field_types.get(btype, {}).get(e.field, 'long')
            return f"(({base}).{e.field})", field_type
        if isinstance(e, Binary):
            # env("KEY") = value  →  env_set("KEY", value)
            if e.op == '=' and isinstance(e.left, Call) and isinstance(e.left.func, Var) and e.left.func.name == 'env' and e.left.args:
                key_c, _ = self.gen_expr(e.left.args[0], 'str')
                val_c, _ = self.gen_expr(e.right, 'str')
                return f"env_set({key_c}, {val_c})", "long"
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
                        vc, _ = self.gen_expr(e.right, 'str' if vty == 'str' else 'long')
                        base, _ = self.gen_expr(coll_e)
                        if isinstance(coll_e, Var):
                            return f"({coll_e.name} = map_{kty}_{self.rt_num(vty)}_put({base}, {kc}, {vc}))", ct
                        return f"map_{kty}_{self.rt_num(vty)}_put({base}, {kc}, {vc})", ct
                return f"({l} = {r})", lt
            if e.op == '+':
                # [str] + [str]  or  [str] + str (append one)
                if lt == 'list_str' and rt == 'list_str':
                    return f"list_concat_str({l}, {r})", "list_str"
                if lt == 'list_str' and rt == 'str':
                    return f"list_push_str({l}, {r})", "list_str"
                if isinstance(lt, str) and lt.startswith('list_') and lt == rt:
                    elem = lt[5:]
                    return f"list_concat_{self.rt_num(elem)}({l}, {r})", lt
                if isinstance(lt, str) and lt.startswith('list_') and rt == lt[5:]:
                    elem = lt[5:]
                    return f"list_push_{self.rt_num(elem)}({l}, {r})", lt
                if isinstance(lt, str) and lt.startswith('list_') and rt == 'long':
                    elem = lt[5:]
                    return f"list_push_{self.rt_num(elem)}({l}, ({self.c_type(elem)})({r}))", lt
                if lt in ('List', 'list', 'list_long') and rt in ('List', 'list', 'list_long'):
                    return f"list_concat_i64({l}, {r})", "list_long"
                if lt in ('List', 'list', 'list_long') and rt == 'long':
                    return f"list_push_i64({l}, {r})", "list_long"
            if e.op == '+' and (lt == 'str' or rt == 'str'):
                if lt == 'str' and rt == 'str':
                    return f"str_concat({l}, {r})", "str"
                if lt == 'str' and rt == 'long':
                    return f"str_concat({l}, str_from_i64({r}))", "str"
                if lt == 'long' and rt == 'str':
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
            return f"({l} {e.op} {r})", ("bool" if e.op in ('==','!=','<','>','<=','>=','&&','||') else "long")
        if isinstance(e, AwaitExpr):
            if getattr(e, 'loop', False):
                v = e.value
                if isinstance(v, Call):
                    name = None
                    mod = None
                    if isinstance(v.func, Var):
                        name = v.func.name
                    elif isinstance(v.func, Member):
                        name = v.func.field
                        if isinstance(v.func.obj, Var):
                            mod = v.func.obj.name
                    # ~> wait / io.wait / tim.wait
                    if name in ('wait', 'sleep') and v.args:
                        ms, _ = self.gen_expr(v.args[0])
                        return f"terse_loop_await_wait({ms})", "long"
                    # ~> io.recv(fd) or ~> recv(fd)
                    if name == 'recv' and v.args and (mod in (None, 'io', 'sock') or mod == 'io'):
                        fd, _ = self.gen_expr(v.args[0])
                        # value is available after resume via result_str; in SM next state uses it
                        return (
                            f"({{ (void)terse_loop_await_recv({fd}); "
                            f"terse_loop_result_str(); }})",
                            "str",
                        )
                    if name == 'send' and len(v.args) >= 2:
                        fd, _ = self.gen_expr(v.args[0])
                        data, _ = self.gen_expr(v.args[1])
                        return (
                            f"({{ (void)terse_loop_await_send({fd}, {data}); "
                            f"terse_loop_result_long(); }})",
                            "long",
                        )
                    if name == 'connect' and len(v.args) >= 2:
                        host, _ = self.gen_expr(v.args[0])
                        port, _ = self.gen_expr(v.args[1])
                        return (
                            f"({{ (void)terse_loop_await_connect({host}, {port}); "
                            f"terse_loop_result_long(); }})",
                            "long",
                        )
            self._await_depth += 1
            try:
                return self.gen_expr(e.value)
            finally:
                self._await_depth -= 1
        if isinstance(e, Unary):
            x, _ = self.gen_expr(e.expr)
            return f"({e.op}{x})", "long"
        if isinstance(e, JumpExpr):
            if e.kind == 'brk':
                return "({ break; INT64_C(0); })", "long"
            return "({ continue; INT64_C(0); })", "long"
        if isinstance(e, RetExpr):
            if e.value is not None:
                v, vt = self.gen_expr(e.value, self.current_return_type)
                return f"({{ return {v}; {self.zero_value(vt)}; }})", vt
            return "({ return INT64_C(0); INT64_C(0); })", "long"
        if isinstance(e, ListLit):
            n = len(e.items)
            tmp = self.fresh()
            element_type = None
            if expected_type and expected_type.startswith('list_'):
                element_type = expected_type[5:]
            elif e.items:
                element_type = self.expr_type(e.items[0])
            width_elems = ('long', 'int', 'chr', 'byte', 'flt', 'dbl', 'bool')
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
                parts = [f"List_{self.rt_num(et)} {tmp} = list_new_{self.rt_num(et)}({n})"]
                for i, item in enumerate(e.items):
                    value, value_type = self.gen_expr(item, et)
                    # narrow int literals into smaller widths
                    if et in ('int', 'i16', 'chr', 'u32', 'u16', 'char', 'dbl') and value_type == 'long':
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
            return "({ " + "; ".join(parts) + "; })", "list_long"
        if isinstance(e, MapLit):
            mt = expected_type if expected_type and expected_type.startswith('map_') else None
            if mt is None and e.entries:
                # infer from first value
                _, vt = self.gen_expr(e.entries[0][1])
                mt = f"map_str_{vt}" if vt in ('long', 'str') else 'map_str_long'
            if mt is None:
                mt = 'map_str_long'
            # mt like map_str_long
            parts = mt.split('_')  # map, str, i64 or map, str, str
            if len(parts) < 3:
                mt = 'map_str_long'; parts = ['map', 'str', 'long']
            kty, vty = parts[1], '_'.join(parts[2:])
            fn_new = f"map_{kty}_{self.rt_num(vty)}_new"
            fn_put = f"map_{kty}_{self.rt_num(vty)}_put"
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
                return f"((int64_t)((unsigned char){c}[{i}]))", "long"
            if ct.startswith('map_'):
                parts = ct.split('_')
                kty, vty = parts[1], '_'.join(parts[2:])
                ret = 'str' if vty == 'str' else 'long'
                return f"map_{kty}_{self.rt_num(vty)}_get({c}, {i})", ret
            if ct.startswith('list_'):
                record_name = ct[5:]
                if record_name == 'str':
                    return f"list_get_str({c}, {i})", "str"
                runtime_name = (
                    self.rt_num(record_name)
                    if record_name in ("long", "int", "chr", "byte", "flt", "dbl", "bool")
                    else record_name
                )
                return f"list_get_{runtime_name}({c}, {i})", record_name
            if ct in ('List', 'list', 'List_i64'):
                return f"list_get_i64({c}, {i})", "long"
            if ct.startswith('map_') or ct == 'Map':
                return f"map_str_i64_get({c}, {i})", "long"
            # last resort: treat as [i64]
            return f"list_get_i64({c}, {i})", "long"
        if isinstance(e, SliceExpr):
            text, _ = self.gen_expr(e.value)
            start, _ = self.gen_expr(e.start)
            end, _ = self.gen_expr(e.end)
            return f"str_slice_range({text}, {start}, {end})", "str"
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
            if isinstance(e.func, Member) and not (
                isinstance(e.func.obj, Var) and e.func.obj.name == 'str'
            ) and self.expr_type(e.func.obj) == 'str':
                receiver, _ = self.gen_expr(e.func.obj)
                method = e.func.field
                args = [self.gen_expr(arg)[0] for arg in e.args]
                if method == 'len' and not args:
                    return f"str_len({receiver})", "long"
                if method in ('fnd', 'has', 'empty', 'split', 'up', 'low', 'rpl', 'rpt'):
                    function_name = f"__module_std_std_str_{method}"
                    cname = self.known.get(function_name)
                    if cname is None:
                        raise SyntaxError(
                            f"string method '{method}' requires 'use std.str'"
                        )
                    ret_type = {
                        "fnd": "long",
                        "has": "bool",
                        "empty": "bool",
                        "split": "list_str",
                    }.get(method, "str")
                    call_args = ", ".join([receiver] + args)
                    return f"{cname}({call_args})", ret_type
                if method == 'trim' and not args:
                    return f"str_trim({receiver})", "str"
                if method == 'start' and len(args) == 1:
                    return f"str_starts({receiver}, {args[0]})", "bool"
                if method == 'end' and len(args) == 1:
                    return f"str_ends({receiver}, {args[0]})", "bool"
            if isinstance(e.func, Var) and e.func.name == 'err':
                message, _ = self.gen_expr(e.args[0], 'str')
                return f"({{ terse_err({message}); INT64_C(0); }})", "long"
            if isinstance(e.func, Var) and e.func.name == 'push':
                collection, collection_type = self.gen_expr(e.args[0])
                value, _ = self.gen_expr(e.args[1])
                if collection_type.startswith('list_'):
                    item_type = collection_type[5:]
                    return f"list_push_{self.rt_num(item_type)}({collection}, {value})", collection_type
                return f"list_push_i64({collection}, {value})", 'list_long'
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
                    elif t in ('flt', 'float', 'dbl', 'double'):
                        parts.append(f'str_from_i64((int64_t)({code}))')  # coarse; prefer i64 path
                    else:
                        parts.append(f'str_from_i64((int64_t)({code}))')
                expr = parts[0]
                for p2 in parts[1:]:
                    expr = f'str_concat({expr}, {p2})'
                return expr, 'str'
            if isinstance(e.func, Var) and e.func.name in ('pr', 'npr', 'pr_'):
                _pr_nnl = e.func.name in ('npr', 'pr_')
                a, at = self.gen_expr(e.args[0])
                if at.startswith('tuple__'):
                    fields = self.tuple_types[at]
                    printers = []
                    for i, field_type in enumerate(fields):
                        field = f"({a}).v{i}"
                        if field_type == 'str':
                            printers.append(f'printf("%s", {field} ? {field} : "")')
                        elif field_type == 'bool':
                            printers.append(f'printf("%s", {field} ? "true" : "false")')
                        elif field_type in ('dbl', 'flt'):
                            printers.append(f'printf("%g", (double){field})')
                        elif field_type == 'int':
                            printers.append(f'printf("%d", (int){field})')
                        else:
                            printers.append(f'printf("%lld", (long long){field})')
                    inner = ', printf(", "), '.join(printers)
                    tmp = self.fresh()
                    return (
                        f'({{ {self.c_type(at)} {tmp} = {a}; '
                        f'_terse_did_print = 1; printf("("); '
                        f'{inner.replace(f"({a}).", f"{tmp}.")}; '
                        f'printf(")\\n"); INT64_C(0); }})',
                        "long",
                    )
                if at == 'str':
                    return (f"(print_str_nnl({a}), INT64_C(0))", "long") if _pr_nnl else (f"(print_str({a}), INT64_C(0))", "long")
                if at in ('list', 'List', 'list_long'):
                    return f"(print_list_i64({a}), INT64_C(0))", "long"
                if at == 'list_str':
                    return f"(print_list_str({a}), INT64_C(0))", "long"
                if isinstance(at, str) and at.startswith('list_'):
                    # list_i32 etc. — prefer typed printer if present, else i64
                    elem = at[5:]
                    if elem in ('int', 'long', 'str'):
                        return f"(print_list_{elem}({a}), INT64_C(0))", "long"
                    return f"(print_list_i64(*(List_i64*)&({a})), INT64_C(0))", "long"
                if at == 'bool':
                    return f"(print_bool({a}), INT64_C(0))", "long"
                if at in self.record_field_types:
                    return f"(print_{at}({a}), INT64_C(0))", "long"
                if _pr_nnl:
                    return f"({{ _terse_did_print = 1; printf(\"%lld\", (long long)({a})); INT64_C(0); }})", "long"
                return f"(print_i64({a}), INT64_C(0))", "long"
            if isinstance(e.func, Var) and e.func.name == 'map':
                coll, ct = self.gen_expr(e.args[0])
                if isinstance(ct, str) and ct.startswith('list_'):
                    elem = ct[5:]
                    lt = f"list_{elem}"
                else:
                    elem, lt = 'long', 'list_long'
                rt = self.rt_num(elem)
                c_list = f"List_{rt}"
                c_elem = self.c_type(elem)
                fn_e = e.args[1]
                tmp = self.fresh()
                idx = self.fresh()
                if isinstance(fn_e, Var) and fn_e.name in self.known:
                    call = f"{self.known[fn_e.name]}(__map_in.d[{idx}])"
                else:
                    fn_c, _ = self.gen_expr(fn_e)
                    call = (
                        f"({{ TerseClos *_tc = (TerseClos*)({fn_c}); {c_elem} _mr; "
                        f"if (_tc->env) _mr = (({c_elem}(*)(void*, {c_elem}))(_tc->fn))(_tc->env, __map_in.d[{idx}]); "
                        f"else _mr = (({c_elem}(*)({c_elem}))(_tc->fn))(__map_in.d[{idx}]); "
                        f"_mr; }})"
                    )
                return (
                    f"({{ {c_list} __map_in = {coll}; {c_list} {tmp} = list_new_{rt}(__map_in.n); "
                    f"for (int64_t {idx} = 0; {idx} < __map_in.n; {idx}++) "
                    f"{tmp}.d[{idx}] = {call}; "
                    f"{tmp}.n = __map_in.n; "
                    f"{tmp}; }})",
                    lt
                )

            
            if isinstance(e.func, Var) and e.func.name == 'len':
                a, at = self.gen_expr(e.args[0])
                if at == 'list_str':
                    return f"list_len_str({a})", "long"
                if at in ('list', 'List'):
                    return f"list_len_i64({a})", "long"
                if isinstance(at, str) and at.startswith('list_'):
                    return f"list_len_{self.rt_num(at[5:])}({a})", "long"
                if isinstance(at, str) and at.startswith('map_'):
                    parts = at.split('_')
                    kty, vty = parts[1], '_'.join(parts[2:])
                    return f"map_{kty}_{self.rt_num(vty)}_len({a})", "long"
                return (f"str_len({a})", "long") if at == 'str' else (f"list_len_i64({a})", "long")
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
                    cname = self.known.get("__module_std_std_str_has")
                    if cname is None:
                        raise SyntaxError("string has requires 'use std.str'")
                    return f"{cname}({a}, {b})", "bool"
                if isinstance(at, str) and at.startswith('map_'):
                    parts = at.split('_')
                    kty, vty = parts[1], '_'.join(parts[2:])
                    return f"map_{kty}_{self.rt_num(vty)}_has({a}, {b})", "bool"
            if isinstance(e.func, Var) and e.func.name == 'keys' and len(e.args) >= 1:
                a, at = self.gen_expr(e.args[0])
                if isinstance(at, str) and at.startswith('map_'):
                    parts = at.split('_')
                    kty, vty = parts[1], '_'.join(parts[2:])
                    return f"map_{kty}_{self.rt_num(vty)}_keys({a})", "list_str"
            if isinstance(e.func, Var) and e.func.name == 'values' and len(e.args) >= 1:
                a, at = self.gen_expr(e.args[0])
                if at == 'map_str_long':
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
            if isinstance(e.func, Var) and e.func.name in ('up', 'low', 'split') \
                    and len(e.args) >= (2 if e.func.name == 'split' else 1):
                method = e.func.name
                cname = self.known.get(f"__module_std_std_str_{method}")
                if cname is None:
                    raise SyntaxError(f"{method} requires 'use std.str'")
                args = [self.gen_expr(arg)[0] for arg in e.args]
                return f"{cname}({', '.join(args)})", (
                    "list_str" if method == "split" else "str"
                )
            if isinstance(e.func, Var) and e.func.name == 'fnd' and len(e.args) >= 2:
                cname = self.known.get("__module_std_std_str_fnd")
                if cname is None:
                    raise SyntaxError("fnd requires 'use std.str'")
                args = [self.gen_expr(arg)[0] for arg in e.args]
                return f"{cname}({', '.join(args)})", "long"
            if isinstance(e.func, Var) and e.func.name == 'parse' and len(e.args) >= 1:
                a, at = self.gen_expr(e.args[0])
                return f"str_parse_i64({a})", "long"
            if isinstance(e.func, Var) and e.func.name == 'join' and len(e.args) >= 2:
                a, _ = self.gen_expr(e.args[0]); b, _ = self.gen_expr(e.args[1])
                return f"str_join({a}, {b})", "str"
            # std.str.foo(...) method form when use std.str
            if isinstance(e.func, Member) and isinstance(e.func.obj, Var) and e.func.obj.name == 'str':
                meth = e.func.field
                if meth in ('fnd', 'has', 'empty', 'split', 'up', 'low', 'rpl', 'rpt') \
                        and e.args:
                    cname = self.known.get(f"__module_std_std_str_{meth}")
                    if cname is None:
                        raise SyntaxError(f"str.{meth} requires 'use std.str'")
                    args = [self.gen_expr(arg)[0] for arg in e.args]
                    ret_type = {
                        "fnd": "long",
                        "has": "bool",
                        "empty": "bool",
                        "split": "list_str",
                    }.get(meth, "str")
                    return f"{cname}({', '.join(args)})", ret_type
                if meth == 'len' and len(e.args) >= 1:
                    a, _ = self.gen_expr(e.args[0])
                    return f"str_len({a})", "long"
                if meth == 'starts' and len(e.args) >= 2:
                    a, _ = self.gen_expr(e.args[0]); b, _ = self.gen_expr(e.args[1])
                    return f"str_starts({a}, {b})", "bool"
                if meth == 'ends' and len(e.args) >= 2:
                    a, _ = self.gen_expr(e.args[0]); b, _ = self.gen_expr(e.args[1])
                    return f"str_ends({a}, {b})", "bool"
                if meth == 'trim' and len(e.args) >= 1:
                    a, _ = self.gen_expr(e.args[0])
                    return f"str_trim({a})", "str"
                if meth == 'parse' and len(e.args) >= 1:
                    a, _ = self.gen_expr(e.args[0])
                    return f"str_parse_i64({a})", "long"
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
                    return f"fs_write_text({path}, {text})", "long"
                if e.func.field == 'append' or e.func.field == 'append_text':
                    path, _ = self.gen_expr(e.args[0])
                    text, _ = self.gen_expr(e.args[1])
                    return f"fs_append_text({path}, {text})", "long"

                if e.func.field == 'wait' and e.args:
                    ms, _ = self.gen_expr(e.args[0])
                    return f"terse_loop_await_wait({ms})", "long"
                if e.func.field == 'recv' and e.args:
                    fd, _ = self.gen_expr(e.args[0])
                    return f"terse_loop_await_recv({fd})", "str"
                if e.func.field == 'send' and len(e.args) >= 2:
                    fd, _ = self.gen_expr(e.args[0])
                    data, _ = self.gen_expr(e.args[1])
                    return f"terse_loop_await_send({fd}, {data})", "long"
                if e.func.field == 'connect' and len(e.args) >= 2:
                    host, _ = self.gen_expr(e.args[0])
                    port, _ = self.gen_expr(e.args[1])
                    return f"terse_loop_await_connect({host}, {port})", "long"
                if e.func.field == 'listen' and e.args:
                    port, _ = self.gen_expr(e.args[0])
                    return f"sock_listen({port})", "long"
                if e.func.field == 'accept' and e.args:
                    fd, _ = self.gen_expr(e.args[0])
                    return f"sock_accept({fd})", "long"
                if e.func.field == 'close' and e.args:
                    fd, _ = self.gen_expr(e.args[0])
                    return f"sock_close({fd})", "long"
            if isinstance(e.func, Member) and isinstance(e.func.obj, Var) \
                    and e.func.obj.name == 'arena':
                f = e.func.field
                if f == 'used':
                    return "arena_used()", "long"
                if f == 'chunks':
                    return "arena_chunk_count()", "long"
                if f == 'reset':
                    return "(arena_reset(), INT64_C(0))", "long"
            if isinstance(e.func, Member) and isinstance(e.func.obj, Var) \
                    and e.func.obj.name == 'sock':
                f = e.func.field
                if f == 'listen' and e.args:
                    a, _ = self.gen_expr(e.args[0])
                    return f"sock_listen({a})", "long"
                if f == 'accept' and e.args:
                    a, _ = self.gen_expr(e.args[0])
                    return f"sock_accept({a})", "long"
                if f == 'recv' and e.args:
                    a, _ = self.gen_expr(e.args[0])
                    return f"sock_recv({a})", "str"
                if f == 'send' and len(e.args) >= 2:
                    a, _ = self.gen_expr(e.args[0]); b, _ = self.gen_expr(e.args[1])
                    return f"sock_send({a}, {b})", "long"
                if f == 'close' and e.args:
                    a, _ = self.gen_expr(e.args[0])
                    return f"sock_close({a})", "long"
                if f == 'connect' and len(e.args) >= 2:
                    a, _ = self.gen_expr(e.args[0]); b, _ = self.gen_expr(e.args[1])
                    return f"sock_connect({a}, {b})", "long"
                if f in ('connect_tls', 'connecttls') and len(e.args) >= 2:
                    a, _ = self.gen_expr(e.args[0]); b, _ = self.gen_expr(e.args[1])
                    return f"sock_connect_tls({a}, {b})", "long"
                if f in ('recv_all', 'recvall') and e.args:
                    a, _ = self.gen_expr(e.args[0])
                    return f"sock_recv_all({a})", "str"
                if f in ('nb_srv', 'nb_serve') and len(e.args) >= 2:
                    return self.gen_sock_nb_srv(e)
            if isinstance(e.func, Member) and isinstance(e.func.obj, Var) \
                    and e.func.obj.name in ('time', 'tim'):
                f = e.func.field
                if f in ('now', 'now_ms') and not e.args:
                    return "terse_time_now_ms()", "long"
                if f in ('now_s', 'unix') and not e.args:
                    return "terse_time_now_s()", "long"
                if f in ('mono', 'mono_ms') and not e.args:
                    return "terse_time_mono_ms()", "long"
                if f in ('sleep', 'wait') and e.args:
                    a, _ = self.gen_expr(e.args[0])
                    return f"terse_time_sleep_ms({a})", "long"
                if f in ('fmt', 'format') and len(e.args) >= 2:
                    a, _ = self.gen_expr(e.args[0]); b, _ = self.gen_expr(e.args[1])
                    return f"terse_time_fmt({a}, {b})", "str"
                if f == 'parse' and e.args:
                    a, _ = self.gen_expr(e.args[0])
                    return f"terse_time_parse({a})", "long"
            if isinstance(e.func, Member) and isinstance(e.func.obj, Var) \
                    and e.func.obj.name == 'async':
                f = e.func.field
                if f == 'drain' and not e.args:
                    return "terse_async_drain()", "long"
            if isinstance(e.func, Member) and isinstance(e.func.obj, Var) \
                    and e.func.obj.name == 'loop':
                if e.func.field == 'run' and e.args:
                    # run a zero-arg ~~> or plain fn to completion (non-server)
                    fc, _ = self.gen_expr(e.args[0])
                    return (
                        f"({{ TerseClos *_tc = (TerseClos*)({fc}); "
                        f"if (_tc->env) ((int64_t(*)(void*))(_tc->fn))(_tc->env); "
                        f"else ((int64_t(*)(void))(_tc->fn))(); "
                        f"INT64_C(0); }})",
                        "long",
                    )

            if isinstance(e.func, Member) and isinstance(e.func.obj, Var) \
                    and e.func.obj.name == 'gcc' and e.func.field == 'compile':
                source, _ = self.gen_expr(e.args[0])
                output, _ = self.gen_expr(e.args[1])
                return f"terse_gcc_compile({source}, {output})", "long"
            
            # std.tst
            # std.tst — assertions (abort on mismatch)
            #   tst.eq(got, expected)  |  tst.chk(expected, actual)  |  tst.check.equals(got, expected)
            if isinstance(e.func, Member) and isinstance(e.func.obj, Var) and e.func.obj.name == 'tst':
                if e.func.field == 'report':
                    return "tst_report()", "long"
                def _tst_lib(kind, got_t):
                    # Prefer Terse overloaded helpers: ..._eq__i64_i64_str_i64
                    # kind is 'eq' or 'ne'; params (got, expected, file, line)
                    gt = got_t if got_t in ('long', 'str', 'bool') else 'long'
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
                        return f"({{ _tst_checks++; if ({lib}({got}, {exp}, {where})) _tst_failures++; INT64_C(0); }})", "long"
                    helper = {'long': 'tst_eq_i64', 'bool': 'tst_eq_bool', 'str': 'tst_eq_str'}.get(got_t, 'tst_eq_i64')
                    return f"({helper}({got}, {exp}, {where}), INT64_C(0))", "long"
                if e.func.field in ('ne', 'not_equals') and len(e.args) >= 2:
                    got, got_t = self.gen_expr(e.args[0])
                    exp, _ = self.gen_expr(e.args[1])
                    where = self.tst_where(e)
                    lib = _tst_lib('ne', got_t)
                    if lib:
                        return f"({{ _tst_checks++; if ({lib}({got}, {exp}, {where})) _tst_failures++; INT64_C(0); }})", "long"
                    helper = {'long': 'tst_ne_i64', 'bool': 'tst_ne_bool', 'str': 'tst_ne_str'}.get(got_t, 'tst_ne_i64')
                    return f"({helper}({got}, {exp}, {where}), INT64_C(0))", "long"
                if e.func.field == 'chk' and len(e.args) >= 2:
                    exp, _ = self.gen_expr(e.args[0])
                    got, got_t = self.gen_expr(e.args[1])
                    where = self.tst_where(e)
                    lib = _tst_lib('eq', got_t)
                    if lib:
                        return f"({{ _tst_checks++; if ({lib}({got}, {exp}, {where})) _tst_failures++; INT64_C(0); }})", "long"
                    helper = {'long': 'tst_eq_i64', 'bool': 'tst_eq_bool', 'str': 'tst_eq_str'}.get(got_t, 'tst_eq_i64')
                    return f"({helper}({got}, {exp}, {where}), INT64_C(0))", "long"
            if isinstance(e.func, Member) and isinstance(e.func.obj, Member) \
                    and isinstance(e.func.obj.obj, Var) and e.func.obj.obj.name == 'tst' \
                    and e.func.obj.field == 'check' and e.func.field == 'equals':
                got, got_t = self.gen_expr(e.args[0])
                exp, _ = self.gen_expr(e.args[1])
                helper = {'long': 'tst_eq_i64', 'bool': 'tst_eq_bool', 'str': 'tst_eq_str'}.get(got_t, 'tst_eq_i64')
                where = self.tst_where(e)
                return f"({helper}({got}, {exp}, {where}), INT64_C(0))", "long"
            if isinstance(e.func, Member):
                # Built-in: .len() method on str and List
                if e.func.field == 'len':
                    base, bt = self.gen_expr(e.func.obj)
                    if bt == 'str':
                        return f"str_len({base})", "long"
                    if bt.startswith('list_'):
                        return f"list_len_{self.rt_num(bt[5:])}({base})", "long"
                    if bt == 'List':
                        return f"list_len_i64({base})", "long"
                base_type = self.expr_type(e.func.obj)
                if base_type in self.interface_methods and e.func.field in self.interface_methods[base_type]:
                    base_code, _ = self.gen_expr(e.func.obj)
                    ret_type = self.interface_method_returns.get((base_type, e.func.field), 'long')
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
                if e.resolved_params is not None:
                    params = e.resolved_params
                    param_types = [
                        self.type_name(p.typ) if p.typ else 'long'
                        for p in params
                    ]
                    resolved = next(
                        (
                            item for item in overs
                            if len(item[0]) == len(param_types)
                            and all(
                                _norm_type_name(actual) == _norm_type_name(expected)
                                for actual, expected in zip(item[0], param_types)
                            )
                        ),
                        None,
                    )
                    cname = resolved[1] if resolved else self.known.get(e.func.name)
                    ret_type = (
                        resolved[2] if resolved
                        else self.func_return_types.get(cname, 'long')
                    )
                    old_env = self.env.copy()
                    old_aliases = self.var_aliases.copy()
                    declarations = []
                    arg_names = []
                    for i, arg in enumerate(e.args):
                        expected = param_types[i]
                        code, _ = self.gen_expr(arg, expected)
                        name = self.fresh()
                        declarations.append(
                            f"{self.c_type(expected)} {name} = {code}"
                        )
                        arg_names.append(name)
                    for i, param in enumerate(params[:len(e.args)]):
                        self.env[param.name] = param_types[i]
                        self.var_aliases[param.name] = arg_names[i]
                    for i, param in enumerate(params[len(e.args):], start=len(e.args)):
                        expected = param_types[i]
                        code, _ = self.gen_expr(param.default, expected)
                        name = self.fresh()
                        declarations.append(
                            f"{self.c_type(expected)} {name} = {code}"
                        )
                        arg_names.append(name)
                        self.env[param.name] = expected
                        self.var_aliases[param.name] = name
                    self.env = old_env
                    self.var_aliases = old_aliases
                    call = f"{cname}({', '.join(arg_names)})"
                    body = "; ".join(declarations + [call])
                    return f"({{ {body}; }})", ret_type
                cname = None
                ret_ty = "long"
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
                        arg_ctypes = []
                        for (ac, at), expected in zip(typed_args, pts):
                            if expected in self.interface_methods and at in self.record_field_types and (expected, at) in self.interface_helpers:
                                args.append(f"{self.interface_helpers[(expected, at)]}( &({ac}) )")
                            else:
                                args.append(ac)
                            arg_ctypes.append(self.c_type(expected if expected else at))
                        fname = e.func.name if isinstance(e.func, Var) else None
                        if fname in getattr(self, 'async_fns', ()) or cname in getattr(self, 'async_fns', ()):
                            wait = getattr(self, '_await_depth', 0) > 0
                            code = self.gen_async_spawn(cname, args, arg_ctypes, wait)
                            return code, "long"
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
                # ~~ async: spawn on background thread
                fname = e.func.name if isinstance(e.func, Var) else None
                if fname in getattr(self, 'async_fns', ()) or cname in getattr(self, 'async_fns', ()):
                    arg_pairs = []
                    if param_ts:
                        for a, expected in zip(e.args, param_ts):
                            ac, at = self.gen_expr(a, expected)
                            arg_pairs.append((ac, self.c_type(expected if expected else at)))
                    else:
                        for a in e.args:
                            ac, at = self.gen_expr(a)
                            arg_pairs.append((ac, self.c_type(at)))
                    wait = getattr(self, '_await_depth', 0) > 0
                    code = self.gen_async_spawn(cname, [p[0] for p in arg_pairs], [p[1] for p in arg_pairs], wait)
                    return code, "long"
                args_str = ", ".join(args)
                return f"{cname}({args_str})", self.func_return_types.get(cname, self.func_return_types.get(e.func.name, "long"))
            fptr, ft = self.gen_expr(e.func)
            typed = [self.gen_expr(a) for a in e.args]
            args = ", ".join(c for c, _ in typed)
            # ft may be 'fn' or 'fn:Req>Res' style from env
            ret_ty = "long"
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
            # TerseClos*: env NULL => plain fn; else fn(env, args...)
            if args.strip():
                env_call = f"(({ret_c}(*)(void*, {arg_ts}))(_tc->fn))(_tc->env, {args})"
                plain_call = f"(({ret_c}(*)({arg_ts}))(_tc->fn))({args})"
            else:
                env_call = f"(({ret_c}(*)(void*))(_tc->fn))(_tc->env)"
                plain_ts = "void"
                plain_call = f"(({ret_c}(*)(void))(_tc->fn))()"
            return (
                f"({{ TerseClos *_tc = (TerseClos*)({fptr}); "
                f"{ret_c} _tr; "
                f"if (_tc->env) _tr = {env_call}; "
                f"else _tr = {plain_call}; "
                f"_tr; }})",
                ret_ty,
            )
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
                if ty == 'long': return 'INT64_C(0)'
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
                "long",
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
                "long",
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
                    self.env[e.init.left.name] = 'long'
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
                return (f"({{ {loop} INT64_C(0); }})", "long")
            if post_c and init_stmt is not None:
                loop = f"while({cond_c}) {{ {body_stmts} {post_c}; }}"
                # continue would skip post — wrap body so continue goes through post via for with empty init
                loop = f"for (; {cond_c}; {post_c}) {{ {body_stmts} }}"
                return (f"({{ {init_stmt} {loop} INT64_C(0); }})", "long")
            if post_c:
                loop = f"for (; {cond_c}; {post_c}) {{ {body_stmts} }}"
                return (f"({{ {loop} INT64_C(0); }})", "long")
            loop = f"while({cond_c}) {{ {body_stmts} }}"
            if init_decl is not None:
                return (f"({{ {init_decl} {loop} INT64_C(0); }})", "long")
            if init_stmt is not None:
                return (f"({{ {init_stmt} {loop} INT64_C(0); }})", "long")
            return (f"({{ {loop} INT64_C(0); }})", "long")
        if isinstance(e, ForInExpr):
            coll, ct = self.gen_expr(e.iterable)
            # Map for-in iterates keys (str)
            if isinstance(ct, str) and ct.startswith('map_'):
                parts = ct.split('_')
                kty, vty = parts[1], '_'.join(parts[2:])
                coll = f"map_{kty}_{self.rt_num(vty)}_keys({coll})"
                ct = 'list_str'
            # Element type from list_* / List / map
            if ct == 'list_str' or ct == 'List_str':
                elem_t, c_list, get_elem = 'str', 'List_str', None
                c_elem = 'const char*'
            elif ct.startswith('list_'):
                inner = ct[5:]
                elem_t = inner
                c_list = f'List_{self.rt_num(inner)}'
                c_elem = self.c_type(inner)
            elif ct in ('list', 'List', 'List_i64'):
                elem_t, c_list, c_elem = 'long', 'List_i64', 'int64_t'
            else:
                # fallback: treat as i64 list
                elem_t, c_list, c_elem = 'long', 'List_i64', 'int64_t'
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
                bind = f"{c_elem} {e.var} = list_get_{self.rt_num(elem_t)}({tmp}, {idx});"
                len_e = f"list_len_{self.rt_num(elem_t)}({tmp})"
            return (
                f"({{ {c_list} {tmp} = {coll}; "
                f"for (int64_t {idx} = 0; {idx} < {len_e}; {idx}++) {{ "
                f"{bind} {body_stmts} }} "
                f"INT64_C(0); }})",
                "long"
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
            zero = '""' if ret_t == 'str' else ("INT64_C(0)" if ret_t == 'long' else f"({self.c_type(ret_t)}){{0}}")
            if st in self.enum_has_data and self.enum_has_data[st]:
                ctype = st
            elif st in self.enum_values and not self.enum_has_data.get(st, False):
                ctype = 'int64_t'
            elif st == 'str':
                ctype = 'const char*'
            else:
                ctype = self.c_type(st)
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
                    lit, lt = self.gen_expr(arm.pattern.value)
                    # String subjects must use strcmp — pointer == is wrong
                    if st == 'str' or lt == 'str' or isinstance(arm.pattern.value, StrLit):
                        conds.append(
                            f"(strcmp(({tmp}) ? ({tmp}) : \"\", ({lit}) ? ({lit}) : \"\") == 0)"
                        )
                    else:
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
                                    ft = ftypes[i] if i < len(ftypes) else 'long'
                                    self.env[sub.name] = ft
                                    # declare bind in outer parts if needed - extract via assignment in body
                                elif isinstance(sub, Wildcard):
                                    pass
                                else:
                                    # literal compare on payload
                                    lit, _ = self.gen_expr(sub.value) if isinstance(sub, LiteralPattern) else ("0", "long")
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
                                ft = ftypes[i] if i < len(ftypes) else 'long'
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
                expected = self.type_name(e.typ)
                if expected in self.interface_methods and vt in self.record_field_types:
                    helper = self.interface_helpers.get((expected, vt))
                    if helper:
                        v = f"{helper}(&({v}))"
                vt = self.type_name(e.typ)
            old = self.env.get(e.name)
            old_alias = self.var_aliases.pop(e.name, None)
            self.env[e.name] = vt
            body, bt = self.gen_expr(e.body)
            if old is not None: self.env[e.name] = old
            else: self.env.pop(e.name, None)
            if old_alias is not None: self.var_aliases[e.name] = old_alias
            if e.name == "_":
                return f"({{ (void)({v}); {body}; }})", bt
            decl = f"{self.c_type(vt)} {e.name} = {v}"
            return f"({{ {decl}; {body}; }})", bt
        if isinstance(e, TupleLetExpr):
            value, tuple_type = self.gen_expr(e.value)
            item_types = self.tuple_types.get(tuple_type, [])
            if len(item_types) != len(e.names):
                return f"({{ (void)({value}); INT64_C(0); }})", "long"
            tmp = self.fresh()
            old_env = self.env.copy()
            declarations = []
            for i, (name, item_type) in enumerate(zip(e.names, item_types)):
                self.env[name] = item_type
                declarations.append(
                    f"{self.c_type(item_type)} {name} = {tmp}.v{i};"
                )
            body, body_type = self.gen_expr(e.body)
            self.env = old_env
            return (
                f"({{ {self.c_type(tuple_type)} {tmp} = {value}; "
                f"{' '.join(declarations)} {body}; }})",
                body_type,
            )
        if isinstance(e, Lambda):
            self.lam_n += 1
            lname = f"__lambda_{self.lam_n}"
            bound = {p.name for p in e.params}
            free = [n for n in self._lambda_free_vars(e.body, bound)
                    if n in self.env or n in self.var_aliases or n in self.known]
            # drop module/builtin names that are functions
            free = [n for n in free if n not in self.known and n not in getattr(self, 'async_fns', ())]
            free = [n for n in free if n in self.env or n in self.var_aliases]
            old_env = self.env.copy()
            old_aliases = self.var_aliases.copy()
            for p in e.params:
                self.env[p.name] = self.type_name(p.typ) if p.typ else 'long'
                self.var_aliases.pop(p.name, None)
            # captures available by name during body gen
            body, bt = self.gen_expr(e.body)
            self.env = old_env
            self.var_aliases = old_aliases
            ret_c = self.c_type(bt)
            if not free:
                ps_c = []
                for p in e.params:
                    tn = self.type_name(p.typ) if p.typ else 'long'
                    ps_c.append(f"{self.c_type(tn)} {p.name}")
                ps = ", ".join(ps_c) or "void"
                self.extra.append(f"static {ret_c} {lname}({ps}) {{\n  return {body};\n}}\n")
                return f"((void*)terse_clos_new((void*){lname}, NULL))", "fn"
            # with captures: env struct + (env, params...) function
            env_ty = f"__env_{self.lam_n}"
            fields = []
            fills = []
            for n in free:
                tn = self.env.get(n) or self.var_aliases.get(n) or 'long'
                if not isinstance(tn, str):
                    tn = 'long'
                if tn == 'fn' or (isinstance(tn, str) and tn.startswith('fn')):
                    ct = 'void*'
                else:
                    ct = self.c_type(tn)
                fields.append(f"  {ct} {n};")
                # read capture from current scope
                if n in self.var_aliases:
                    src = self.var_aliases[n]
                else:
                    src = n
                fills.append(f"_e->{n} = ({ct})({src});")
            # regenerate body with capture loads — re-gen with aliases to env fields
            old_env = self.env.copy()
            old_aliases = self.var_aliases.copy()
            for p in e.params:
                self.env[p.name] = self.type_name(p.typ) if p.typ else 'long'
                self.var_aliases.pop(p.name, None)
            for n in free:
                tn = old_env.get(n) or 'long'
                self.env[n] = tn if isinstance(tn, str) else 'long'
                self.var_aliases[n] = f"((_env)->{n})"
            body, bt = self.gen_expr(e.body)
            ret_c = self.c_type(bt)
            self.env = old_env
            self.var_aliases = old_aliases
            ps_c = [f"{env_ty} *_env"]
            for p in e.params:
                tn = self.type_name(p.typ) if p.typ else 'long'
                ps_c.append(f"{self.c_type(tn)} {p.name}")
            ps = ", ".join(ps_c)
            self.extra.append(
                f"typedef struct {{\n" + "\n".join(fields) + f"\n}} {env_ty};\n"
                f"static {ret_c} {lname}({ps}) {{\n  return {body};\n}}\n"
            )
            tmp = self.fresh()
            fill_s = " ".join(fills).replace("_e->", f"{tmp}->")
            return (
                f"({{ {env_ty} *{tmp} = ({env_ty}*)arena_alloc(sizeof({env_ty})); "
                f"{fill_s} "
                f"(void*)terse_clos_new((void*){lname}, {tmp}); }})",
                "fn",
            )
        if isinstance(e, Block):
            if not e.stmts: return "INT64_C(0)", "long"
            if len(e.stmts) == 1:
                return self.gen_expr(e.stmts[0])
            parts = []
            for st in e.stmts[:-1]:
                code, _ = self.gen_expr(st)
                parts.append(f"(void)({code})")
            last, lt = self.gen_expr(e.stmts[-1])
            return "({ " + "; ".join(parts) + "; " + last + "; })", lt
        if isinstance(e, TrapExpr):
            protected, _ = self.gen_expr(e.expr)
            trap = self.fresh()
            error = self.fresh()
            old_env = self.env.copy()
            old_aliases = self.var_aliases.copy()
            self.env[e.name] = 'str'
            self.var_aliases[e.name] = error
            handler, _ = self.gen_expr(e.handler)
            self.env = old_env
            self.var_aliases = old_aliases
            return (
                f"({{ TerseTrap {trap}; {trap}.prev = _terse_trap; "
                f"_terse_trap = &{trap}; "
                f"if (setjmp({trap}.env) == 0) {{ "
                f"(void)({protected}); _terse_trap = {trap}.prev; "
                f"}} else {{ const char *{error} = _terse_error_message; "
                f"_terse_trap = {trap}.prev; (void)({handler}); }} "
                f"INT64_C(0); }})",
                "long",
            )
        return "INT64_C(0)", "long"





    def gen_sock_nb_srv(self, e: Call):
        """sock.nb_srv(port, handler) — non-blocking HTTP.
        handler may be a local fn-param (fn(Req)->Res) or a known global.
        """
        port_c, _ = self.gen_expr(e.args[0])
        h = e.args[1]
        self.lam_n += 1
        n = self.lam_n
        wrap = f"__nb_http_wrap_{n}"
        slot = f"__nb_http_handler_{n}"
        parse_n = fmt_n = None
        parse_req_n = format_rsp_n = None
        for name, cname in self.known.items():
            base = name.split('.')[-1] if isinstance(name, str) else name
            if base == 'parse_req' or name.endswith('parse_req'):
                parse_n = cname
            if base == 'format_response' or name.endswith('format_response'):
                fmt_n = cname
            if base == 'parseReq' or name.endswith('parseReq'):
                parse_req_n = cname
            if base == 'formatResponse' or name.endswith('formatResponse'):
                format_rsp_n = cname
        if isinstance(h, Var):
            hc, ht = self.gen_expr(h)
        else:
            hc, ht = self.gen_expr(h)
        if parse_req_n and format_rsp_n:
            # Always use step server so ~> wait works when handler is ~~>
            hname = h.name if isinstance(h, Var) else None
            hc_name = None
            if hname:
                hc_name = self.known.get(hname)
            if hc_name is None and isinstance(h, Var):
                hc_name = self.known.get(h.name)
            # Function pointer arg: still wrap via slot; prefer step with dynamic slot
            if hc_name:
                return self.gen_sock_nb_srv_loop(port_c, hc_name, parse_req_n, format_rsp_n, True)
            # Dynamic handler pointer (e.g. nhttp.asrv(port, handler))
            return self.gen_sock_nb_srv_loop(port_c, hc, parse_req_n, format_rsp_n, False)
            self.extra.append(
                f"static Rsp (*{slot})(Req) = NULL;\n"
                f"static char* {wrap}(const char* raw) {{\n"
                f"  Req rq = {parse_req_n}((char*)raw);\n"
                f"  Rsp rs = {slot}(rq);\n"
                f"  return strdup((char*){format_rsp_n}(rs));\n"
                f"}}\n"
            )
            return (
                f"({{ TerseClos *_h = (TerseClos*)({hc}); {slot} = (Rsp(*)(Req))(_h ? _h->fn : NULL); "
                f"sock_nb_srv({port_c}, {wrap}); INT64_C(0); }})",
                "long",
            )
        # Prefer typed Req/Res wrap when helpers are available
        if parse_n and fmt_n:
            self.extra.append(
                f"static Res (*{slot})(Req) = NULL;\n"
                f"static char* {wrap}(const char* raw) {{\n"
                f"  Req rq = {parse_n}((char*)raw);\n"
                f"  Res rs = {slot}(rq);\n"
                f"  return (char*){fmt_n}(rs);\n"
                f"}}\n"
            )
            return (
                f"({{ {slot} = (Res(*)(Req))({hc}); "
                f"sock_nb_srv({port_c}, {wrap}); INT64_C(0); }})",
                "long",
            )
        self.extra.append(
            f"static char* {wrap}(const char* raw) {{\n"
            f"  return ((char*(*)(const char*))({hc}))(raw);\n"
            f"}}\n"
        )
        return f"(sock_nb_srv({port_c}, {wrap}), INT64_C(0))", "long"







    def _collect_let_names(self, e, out=None):
        from .ast import LetExpr, Block, IfExpr, AwaitExpr, Call, Binary, Unary, RetExpr
        if out is None:
            out = []
        if e is None:
            return out
        if isinstance(e, LetExpr):
            if e.name and e.name != '_':
                out.append(e.name)
            self._collect_let_names(e.value, out)
            self._collect_let_names(e.body, out)
            return out
        if isinstance(e, Block):
            for st in e.stmts:
                self._collect_let_names(st, out)
            return out
        for attr in ('body', 'value', 'expr', 'then', 'els', 'cond', 'left', 'right', 'func'):
            self._collect_let_names(getattr(e, attr, None), out)
        for attr in ('stmts', 'args', 'items'):
            for c in getattr(e, attr, None) or []:
                self._collect_let_names(c, out)
        return out

    def _expr_has_loop_await(self, e):

        from .ast import (
            AwaitExpr, Block, Call, Binary, Unary, IfExpr, TernaryExpr, LetExpr,
            RetExpr, AssignExpr, LoopExpr, ForInExpr, ListLit, Member, Lambda,
        )
        if e is None:
            return False
        if isinstance(e, AwaitExpr) and getattr(e, 'loop', False):
            return True
        for attr in ('body', 'value', 'expr', 'then', 'els', 'cond', 'left', 'right',
                     'func', 'target', 'init', 'post', 'iterable'):
            child = getattr(e, attr, None)
            if child is not None and self._expr_has_loop_await(child):
                return True
        for attr in ('stmts', 'args', 'items'):
            for child in getattr(e, attr, None) or []:
                if self._expr_has_loop_await(child):
                    return True
        return False

    def _await_wait_ms_code(self, e):
        """If e is ~> wait/sleep(ms), return C code for ms; else None."""
        from .ast import AwaitExpr, Call, Member, Var
        if not (isinstance(e, AwaitExpr) and getattr(e, 'loop', False)):
            return None
        v = e.value
        if not isinstance(v, Call):
            return None
        name = None
        if isinstance(v.func, Var):
            name = v.func.name
        elif isinstance(v.func, Member):
            name = v.func.field
        if name in ('wait', 'sleep') and v.args:
            ms, _ = self.gen_expr(v.args[0])
            return ms
        return None

    def _await_io_kind(self, e):
        """('wait', arg_ast) | ('recv', fd_ast) | ('send', fd, data) | ('connect', host, port) | None.
        Args are AST nodes; C is generated later with frame aliases in scope.
        """
        from .ast import AwaitExpr, Call, Member, Var
        if not (isinstance(e, AwaitExpr) and getattr(e, 'loop', False)):
            return None
        v = e.value
        if not isinstance(v, Call):
            return None
        name = None
        if isinstance(v.func, Var):
            name = v.func.name
        elif isinstance(v.func, Member):
            name = v.func.field
        if name in ('wait', 'sleep') and v.args:
            return ('wait', v.args[0])
        if name == 'recv' and v.args:
            return ('recv', v.args[0])
        if name == 'send' and len(v.args) >= 2:
            return ('send', v.args[0], v.args[1])
        if name == 'connect' and len(v.args) >= 2:
            return ('connect', v.args[0], v.args[1])
        return None


    def _linearize_loop_body(self, e):
        """Flatten body into [('run', expr)] / [('wait', ms_c)] / [('ret', expr)].

        Function bodies are often desugared to nested LetExpr('_', stmt, rest).
        """
        from .ast import (
            AwaitExpr, Block, RetExpr, IfExpr, LetExpr, Call, Member, Var,
        )
        ops = []
        from .ast import LetExpr as _LE, Block as _B, RetExpr as _RE, AwaitExpr as _AE
        # Unwrap let-chain: "_" is sequencing; named lets bind await results
        while isinstance(e, LetExpr):
            if e.name in ('_',):
                ops.extend(self._linearize_loop_body(e.value))
                e = e.body
                continue
            io = self._await_io_kind(e.value)
            if io is not None:
                ops.append(io)
                # bind result into frame local after resume
                if io[0] in ('recv',):
                    ops.append(('bind_s', e.name))
                else:
                    ops.append(('bind_i', e.name))
                e = e.body
                continue
            if self._expr_has_loop_await(e.value):
                ops.extend(self._linearize_loop_body(e.value))
                e = e.body
                continue
            # plain let: run assignment then body
            ops.append(('run', e))
            return ops
        if e is None:
            return ops
        if isinstance(e, Block):
            for st in e.stmts:
                ops.extend(self._linearize_loop_body(st))
            return ops
        if isinstance(e, RetExpr):
            if e.value is not None and self._expr_has_loop_await(e.value):
                ops.extend(self._linearize_loop_body(e.value))
                return ops
            ops.append(('ret', e.value if e.value is not None else None))
            return ops
        io = self._await_io_kind(e)
        if io is not None:
            ops.append(io)
            return ops
        if isinstance(e, AwaitExpr) and getattr(e, 'loop', False):
            ops.extend(self._linearize_loop_body(e.value))
            return ops
        if not self._expr_has_loop_await(e):
            ops.append(('run', e))
            return ops
        ops.append(('run', e))
        return ops

    def gen_loop_state_machine(self, f, cname, parse_req_n=None, format_rsp_n=None):
        """Emit Frame + step for ~~> fn. Returns (make_name, step_name) or None."""
        from .ast import AwaitExpr
        if not self._expr_has_loop_await(f.body):
            return None
        ops = self._linearize_loop_body(f.body)
        # refine: re-walk for wait points with sequential states
        self.lam_n += 1
        sid = self.lam_n
        frame = f"__sm_frame_{sid}"
        step = f"__sm_step_{sid}"
        make = f"__sm_make_{sid}"
        is_http = parse_req_n and format_rsp_n and f.params and self.type_name(f.params[0].typ) in ('Req', 'Req')
        # Build switch cases from ops: merge consecutive runs, waits create boundaries
        states = []  # list of list of ops for each state; last ends with wait or ret
        cur = []
        for op in ops:
            if op[0] in ('wait', 'recv', 'send', 'connect'):
                cur.append(op)
                states.append(cur)
                cur = []
            else:
                cur.append(op)
        if cur:
            states.append(cur)
        if not states:
            states = [[('run', f.body)]]

        # Frame fields: state + params
        fields = ["  int state;"]
        for p in f.params:
            tn = self.type_name(p.typ) if p.typ else 'long'
            fields.append(f"  {self.c_type(tn)} {p.name};")
        let_names = self._collect_let_names(f.body)
        str_lets = {op[1] for op in ops if op and op[0] == "bind_s"}
        # ensure string binds always use _s in frame
        # default locals to long or str pointer storage
        for ln in let_names:
            if ln in [p.name for p in f.params]:
                continue
            fields.append(f"  int64_t {ln}_i;")
            fields.append(f"  const char* {ln}_s;")

        cases = []
        for si, st_ops in enumerate(states):
            lines = [f"  case {si}: {{"]
            wait_ms = None
            ret_expr = None
            io_suspend = None
            for op in st_ops:
                if op[0] == 'wait':
                    wait_ms = 0
                    io_suspend = ('wait', op[1])
                elif op[0] == 'recv':
                    io_suspend = op
                    wait_ms = 0
                elif op[0] == 'send':
                    io_suspend = op
                    wait_ms = 0
                elif op[0] == 'connect':
                    io_suspend = op
                    wait_ms = 0
                elif op[0] == 'bind_i':
                    lines.append(f"    f->{op[1]}_i = terse_loop_result_long();")
                elif op[0] == 'bind_s':
                    str_lets.add(op[1])
                    lines.append(f"    f->{op[1]}_s = terse_loop_result_str();")
                elif op[0] == 'ret':
                    ret_expr = op[1]
                elif op[0] == 'run':
                    old_env = self.env.copy()
                    old_aliases = self.var_aliases.copy()
                    for p in f.params:
                        self.env[p.name] = self.type_name(p.typ) if p.typ else 'long'
                        self.var_aliases[p.name] = f"(f->{p.name})"
                    for ln in let_names:
                        if ln in str_lets:
                            self.env[ln] = 'str'
                            self.var_aliases[ln] = f"(f->{ln}_s)"
                        else:
                            self.env[ln] = 'long'
                            self.var_aliases[ln] = f"(f->{ln}_i)"
                    code, ct = self.gen_expr(op[1])
                    self.env = old_env
                    self.var_aliases = old_aliases
                    lines.append(f"    (void)({code});")
            if wait_ms is not None or io_suspend is not None:
                next_st = si + 1
                old_env = self.env.copy()
                old_aliases = self.var_aliases.copy()
                for p in f.params:
                    self.env[p.name] = self.type_name(p.typ) if p.typ else 'long'
                    self.var_aliases[p.name] = f"(f->{p.name})"
                for ln in let_names:
                    if ln in str_lets:
                        self.env[ln] = 'str'
                        self.var_aliases[ln] = f"(f->{ln}_s)"
                    else:
                        self.env[ln] = 'long'
                        self.var_aliases[ln] = f"(f->{ln}_i)"
                if io_suspend and io_suspend[0] == 'recv':
                    fd_c, _ = self.gen_expr(io_suspend[1])
                    lines.append(f"    (void)terse_loop_await_recv({fd_c});")
                elif io_suspend and io_suspend[0] == 'send':
                    fd_c, _ = self.gen_expr(io_suspend[1])
                    data_c, _ = self.gen_expr(io_suspend[2])
                    lines.append(f"    (void)terse_loop_await_send({fd_c}, {data_c});")
                elif io_suspend and io_suspend[0] == 'connect':
                    h_c, _ = self.gen_expr(io_suspend[1])
                    p_c, _ = self.gen_expr(io_suspend[2])
                    lines.append(f"    (void)terse_loop_await_connect({h_c}, {p_c});")
                elif io_suspend and io_suspend[0] == 'wait':
                    ms_c, _ = self.gen_expr(io_suspend[1])
                    lines.append(f"    (void)terse_loop_await_wait({ms_c});")
                elif wait_ms is not None:
                    lines.append(f"    (void)terse_loop_await_wait({wait_ms});")
                self.env = old_env
                self.var_aliases = old_aliases
                lines.append(f"    f->state = {next_st};")
                lines.append(f"    *out_wait_ms = 0;")
                lines.append(f"    return NULL;")
            else:
                # done
                if is_http:
                    if ret_expr is not None:
                        old_env = self.env.copy()
                        old_aliases = self.var_aliases.copy()
                        for p in f.params:
                            self.env[p.name] = self.type_name(p.typ) if p.typ else 'long'
                            self.var_aliases[p.name] = f"(f->{p.name})"
                        rc, _ = self.gen_expr(ret_expr)
                        self.env = old_env
                        self.var_aliases = old_aliases
                        lines.append(f"    return strdup((char*){format_rsp_n}({rc}));")
                    else:
                        # last run may have returned via ret in expression - use normal handler
                        lines.append(f"    {{ Rsp _rs = {cname}(" + ", ".join(f"f->{p.name}" for p in f.params) + f"); return strdup((char*){format_rsp_n}(_rs)); }}")
                else:
                    lines.append('    return (char*)"";')
            lines.append(f"  }}")
            cases.append("\n".join(lines))

        body_switch = "\n".join(cases)
        lines_out = []
        lines_out.append(f"typedef struct {{\n" + "\n".join(fields) + f"\n}} {frame};")
        if is_http:
            lines_out.append(f"static void* {make}(const char* raw) {{")
            lines_out.append(f"  {frame}* f = ({frame}*)malloc(sizeof({frame}));")
            lines_out.append(f"  if (!f) return NULL;")
            lines_out.append(f"  f->state = 0;")
            lines_out.append(f"  f->{f.params[0].name} = {parse_req_n}((char*)raw);")
            lines_out.append(f"  return f;")
            lines_out.append(f"}}")
        else:
            lines_out.append(f"static void* {make}(void) {{")
            lines_out.append(f"  {frame}* f = ({frame}*)malloc(sizeof({frame}));")
            lines_out.append(f"  if (!f) return NULL; f->state = 0; return f;")
            lines_out.append(f"}}")
        lines_out.append(f"static char* {step}(void* vf, int event, int64_t* out_wait_ms) {{")
        lines_out.append(f"  {frame}* f = ({frame}*)vf;")
        lines_out.append(f"  (void)event;")
        lines_out.append(f"  *out_wait_ms = -1;")
        lines_out.append(f"  switch (f->state) {{")
        lines_out.append(body_switch)
        lines_out.append(f"  default: return NULL;")
        lines_out.append(f"  }}")
        lines_out.append(f"}}")
        self.extra.append("\n".join(lines_out) + "\n")
        if not hasattr(self, 'loop_sm'):
            self.loop_sm = {}
        self.loop_sm[f.name] = (make, step, is_http)
        self.loop_sm[cname] = (make, step, is_http)
        return make, step, is_http


    def gen_sock_nb_srv_loop(self, port_c, handler_expr, parse_req_n, format_rsp_n, handler_is_cname=True):
        """Wire handler to sock_nb_srv_step. Prefer multi-state SM when registered."""
        sm = getattr(self, 'loop_sm', {}).get(handler_expr) if handler_is_cname else None
        if sm and sm[2]:
            make, step, _ = sm
            return f"(sock_nb_srv_step({port_c}, {make}, {step}), INT64_C(0))", "long"
        # Fallback: single-shot + held response (one ~> wait)
        frame = "loop_frame_" + self.fresh()
        step = "loop_step_" + self.fresh()
        make = "loop_make_" + self.fresh()
        slot = "loop_slot_" + self.fresh()
        call = f"{handler_expr}(f->rq)" if handler_is_cname else f"{slot}(f->rq)"
        lines = []
        if not handler_is_cname:
            lines.append(f"static Rsp (*{slot})(Req) = NULL;")
        lines.append(f"typedef struct {{ int state; Req rq; char* held_resp; }} {frame};")
        lines.append(f"static void* {make}(const char* raw) {{")
        lines.append(f"  {frame}* f = ({frame}*)malloc(sizeof({frame}));")
        lines.append(f"  if (!f) return NULL;")
        lines.append(f"  f->state = 0; f->held_resp = NULL;")
        lines.append(f"  f->rq = {parse_req_n}((char*)raw);")
        lines.append(f"  return f;")
        lines.append(f"}}")
        lines.append(f"static char* {step}(void* vf, int event, int64_t* out_wait_ms) {{")
        lines.append(f"  {frame}* f = ({frame}*)vf;")
        lines.append(f"  *out_wait_ms = -1;")
        lines.append(f"  if (event == 1 || f->state == 1) {{")
        lines.append(f"    if (f->held_resp) {{ char* r = f->held_resp; f->held_resp = NULL; return r; }}")
        lines.append(f"    return strdup(\"HTTP/1.1 500 Error\\r\\nContent-Length: 0\\r\\nConnection: close\\r\\n\\r\\n\");")
        lines.append(f"  }}")
        lines.append(f"  _terse_loop_wait_ms = -1;")
        lines.append(f"  Rsp rs = {call};")
        lines.append(f"  if (_terse_loop_wait_ms >= 0) {{")
        lines.append(f"    int64_t w = _terse_loop_wait_ms; _terse_loop_wait_ms = -1;")
        lines.append(f"    f->state = 1;")
        lines.append(f"    f->held_resp = strdup((char*){format_rsp_n}(rs));")
        lines.append(f"    *out_wait_ms = w;")
        lines.append(f"    return NULL;")
        lines.append(f"  }}")
        lines.append(f"  return strdup((char*){format_rsp_n}(rs));")
        lines.append(f"}}")
        self.extra.append("\n".join(lines) + "\n")
        if handler_is_cname:
            return f"(sock_nb_srv_step({port_c}, {make}, {step}), INT64_C(0))", "long"
        return (
            f"({{ TerseClos *_h = (TerseClos*)({handler_expr}); "
            f"{slot} = (Rsp(*)(Req))(_h ? _h->fn : NULL); "
            f"sock_nb_srv_step({port_c}, {make}, {step}); INT64_C(0); }})",
            "long",
        )


    def gen_async_spawn(self, cname: str, arg_codes: list, arg_ctypes: list, wait: bool) -> str:
        """Spawn cname(args...) on a pthread; wait=True joins."""
        pack = f"__async_pack_{cname}"
        entry = f"__async_run_{cname}"
        key = f"_async_emit_{cname}"
        if not getattr(self, key, False):
            setattr(self, key, True)
            fields = []
            call_args = []
            frees = []
            for i, ct in enumerate(arg_ctypes):
                fields.append(f"  {ct} a{i};")
                call_args.append(f"a->a{i}")
                if "char" in ct:
                    frees.append(f"  free((void*)a->a{i});")
            fields_s = "\n".join(fields) if fields else "  int64_t _pad;"
            call_s = ", ".join(call_args)
            free_s = "\n".join(frees)
            self.extra.append(
                f"typedef struct {{\n{fields_s}\n}} {pack};\n"
                f"static void* {entry}(void* p) {{\n"
                f"  {pack}* a = ({pack}*)p;\n"
                f"  (void){cname}({call_s});\n"
                f"{free_s}\n"
                f"  free(a);\n"
                f"  return NULL;\n"
                f"}}\n"
            )
        tmp = self.fresh()
        lines = [f"{pack}* {tmp} = ({pack}*)malloc(sizeof({pack}));"]
        for i, (ac, ct) in enumerate(zip(arg_codes, arg_ctypes)):
            if "char" in ct:
                lines.append(f'{tmp}->a{i} = strdup({ac} ? {ac} : "");')
            else:
                lines.append(f"{tmp}->a{i} = {ac};")
        if not arg_codes:
            lines.append(f"(void){tmp};")
        w = "1" if wait else "0"
        lines.append(f"terse_async_spawn({entry}, {tmp}, {w});")
        lines.append("INT64_C(0)")
        return "({ " + " ".join(lines) + "; })"

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
                tn = self.type_name(p.typ) if p.typ else 'long'
                pcs.append(f"{self.c_type(tn)} {p.name}")
        ret = self.type_name(f.ret) if f.ret else 'long'
        crt = self.c_type(ret)
        pstr = ", ".join(pcs) if pcs else "void"
        old_env = self.env.copy()
        for p in f.params:
            if p.typ and getattr(p.typ, 'name', None) == 'fn':
                self.env[p.name] = _fn_type_tag(p.typ)
            else:
                self.env[p.name] = self.type_name(p.typ) if p.typ else 'long'
        if f.params and f.params[0].name == 'self':
            self.env['self'] = self.type_name(f.params[0].typ) if f.params[0].typ else 'long'
        old_return_type = self.current_return_type
        self.current_return_type = ret
        body, _ = self.gen_expr(f.body, ret)
        self.current_return_type = old_return_type
        self.env = old_env
        # Multi-state ~~> (non-HTTP): drive body via terse_loop_run
        if getattr(f, 'is_async_loop', False) and self._expr_has_loop_await(f.body):
            try:
                sm = self.gen_loop_state_machine(f, cname)
                if sm and not sm[2] and not f.params:
                    make, step, _ = sm
                    body = f"(terse_loop_run({make}, {step}), INT64_C(0))"
            except Exception:
                pass
        self.emit(f"{crt} {cname}({pstr}) {{")
        self.indent += 1
        self.emit(f"return {body};")
        self.indent -= 1
        self.emit("}")
        self.emit()

    def generate(self, prog: Program, source_path: Optional[str] = None, as_lib: bool = False, skip_runtime: bool = False) -> str:
        self.generic_traits = {
            sig.name: sig for sig in prog.sigs if getattr(sig, 'type_params', None)
        }
        self.generic_trait_instances = {}

        def collect_trait_instances(value, visited):
            if value is None or id(value) in visited:
                return
            if isinstance(value, TypeNode):
                trait = self.generic_traits.get(value.name)
                if trait and len(value.args) == len(trait.type_params):
                    key = self.type_name(value)
                    self.generic_trait_instances[key] = (trait, value.args)
                for arg in value.args:
                    collect_trait_instances(arg, visited)
                return
            if isinstance(value, (list, tuple)):
                for item in value:
                    collect_trait_instances(item, visited)
                return
            if hasattr(value, '__dict__'):
                visited.add(id(value))
                for child in vars(value).values():
                    collect_trait_instances(child, visited)

        collect_trait_instances(prog, set())

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
        interface_specs = {}
        self.interface_methods = {}
        self.interface_method_returns = {}
        for sig in prog.sigs:
            if getattr(sig, 'type_params', None):
                continue
            methods = [
                (m[0], [self.type_name(p.typ) if p.typ else 'long' for p in m[1]],
                 self.type_name(m[2]) if m[2] else 'long')
                for m in sig.methods
            ]
            interface_specs[sig.name] = methods
        for instance_name, (sig, type_args) in self.generic_trait_instances.items():
            mapping = {
                name: _type_node_name(arg)
                for name, arg in zip(sig.type_params, type_args)
            }
            methods = [
                (
                    method_name,
                    [
                        self.type_name(_subst_type_node(p.typ, mapping))
                        if p.typ else 'long'
                        for p in params
                    ],
                    self.type_name(_subst_type_node(ret, mapping))
                    if ret else 'long',
                )
                for method_name, params, ret in sig.methods
            ]
            interface_specs[instance_name] = methods
        self.interface_methods = {
            name: [method[0] for method in methods]
            for name, methods in interface_specs.items()
        }
        self.interface_method_returns = {
            (interface_name, method_name): return_type
            for interface_name, methods in interface_specs.items()
            for method_name, _, return_type in methods
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
                    tn = 'long'
                else:
                    tn = 'long'
            self.env[c.name] = tn
        funcs = list(prog.funcs)
        entry_name = None
        for m in prog.methods:
            method_name = f"{m.receiver}_{m.name}"
            self.method_names[(m.receiver, m.name)] = "terse_" + method_name
            self.method_returns[(m.receiver, m.name)] = self.type_name(m.ret) if m.ret else 'long'
            receiver = Param('self', TypeNode(m.receiver))
            funcs.append(FnDecl(method_name, [receiver] + list(m.params), m.ret, m.body))
        if prog.toplevel is not None:
            entry_name = '__terse_program_entry'
            while any(f.name == entry_name for f in funcs):
                entry_name += '_'
            funcs.append(FnDecl(entry_name, [], TypeNode('long'), prog.toplevel))
        # Parameter overloads: same source name, distinct C symbols when signatures differ
        from collections import Counter
        name_counts = Counter(f.name for f in funcs)
        self.func_param_types = {}
        self.func_return_types = {}
        self.overloads = {}  # name -> [(param_types, cname, ret)]
        for f in funcs:
            if getattr(f, 'type_params', None):
                continue
            pts = [self.type_name(p.typ) if p.typ else 'long' for p in f.params]
            ret = self.type_name(f.ret) if f.ret else 'long'
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
            if getattr(f, 'is_async', False):
                self.async_fns.add(f.name)
                self.async_fns.add(cname)
            if getattr(f, 'is_async_loop', False):
                self.async_loop_fns.add(f.name)
                self.async_loop_fns.add(cname)

            self.func_param_types[cname] = pts
            self.func_param_types[f.name] = pts  # single-overload convenience
            self.func_return_types[cname] = ret
            self.func_return_types[f.name] = ret
            self.overloads.setdefault(f.name, []).append((pts, cname, ret))

        def register_tuple_literals(node):
            if isinstance(node, TupleLit):
                tuple_type = getattr(node, 'inferred_type', None)
                item_types = (
                    tuple_type[7:].split('__') if tuple_type
                    else [self.expr_type(item) for item in node.items]
                )
                tuple_type = tuple_type or ('tuple__' + '__'.join(item_types))
                self.tuple_types.setdefault(tuple_type, item_types)
            if hasattr(node, '__dict__'):
                for value in vars(node).values():
                    if isinstance(value, Expr) or hasattr(value, '__dict__'):
                        register_tuple_literals(value)
                    elif isinstance(value, (list, tuple)):
                        for item in value:
                            if isinstance(item, Expr) or hasattr(item, '__dict__'):
                                register_tuple_literals(item)

        for f in funcs:
            register_tuple_literals(f.body)
        if prog.toplevel is not None:
            register_tuple_literals(prog.toplevel)

        out = [get_runtime(), ""]
        # Emit top-level fix constants
        for c in self.const_decls:
            tn = self.env.get(c.name, 'long')
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
        for iface_name, methods in interface_specs.items():
            fields = ["  void* value;"]
            for name, _, _ in methods:
                fields.append(f"  void* (*{name})(void*);")
            out.append("typedef struct {")
            out.extend(fields)
            out.append(f"}} {iface_name};")
            out.append("")
        self.interface_helpers = {}
        # Build adapters for every concrete record satisfying an interface.
        method_sigs = {
            (m.receiver, m.name): (
                [self.type_name(p.typ) if p.typ else 'long' for p in m.params],
                self.type_name(m.ret) if m.ret else 'long',
            )
            for m in prog.methods
        }
        concrete_recs = [r for r in prog.recs if not getattr(r, 'type_params', None)]
        for iface_name, methods in interface_specs.items():
            for rec in concrete_recs:
                struct_name = rec.name
                if not all(
                    (struct_name, method_name) in method_sigs
                    and method_sigs[(struct_name, method_name)] == (param_types, ret_type)
                    for method_name, param_types, ret_type in methods
                ):
                    continue
                helper_name = f"{iface_name}_from_{struct_name}"
                self.interface_helpers[(iface_name, struct_name)] = helper_name
                assignments = []
                for method_name, _, ret_type in methods:
                    if (struct_name, method_name) not in self.method_names:
                        continue
                    c_ret_type = self.c_type(ret_type)
                    wrapper_name = f"{iface_name}_{struct_name}_{method_name}_adapter"
                    self.extra.append(
                        f"static {c_ret_type} {wrapper_name}(void* value) {{\n"
                        f"  {struct_name}* self = ({struct_name}*)value;\n"
                        f"  return ({c_ret_type}){self.known.get(f'{struct_name}_{method_name}', '0')}(*self);\n"
                        f"}}\n"
                    )
                    assignments.append(
                        f"  out.{method_name} = (void*(*)(void*)){wrapper_name};"
                    )
                self.extra.append(
                    f"static {iface_name} {helper_name}({struct_name}* value) {{\n"
                    f"  {iface_name} out = {{0}};\n"
                    f"  out.value = (void*)value;\n"
                    + "\n".join(assignments) + "\n"
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
        for tuple_name, item_types in self.tuple_types.items():
            out.append("typedef struct {")
            for i, item_type in enumerate(item_types):
                out.append(f"  {self.c_type(item_type)} v{i};")
            out.append(f"}} {self.c_type(tuple_name)};")
            out.append("")
        for rec in concrete_recs:
            out.append(self.record_print_code(rec))
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
                    tn = self.type_name(p.typ) if p.typ else 'long'
                pcs.append(self.c_type(tn))
            ret = self.type_name(f.ret) if f.ret else 'long'
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
                "  terse_async_drain();",
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
