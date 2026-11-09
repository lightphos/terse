# Terse Language Specification 0.3

**Terse** is a succinct, statically typed language that compiles to native binaries. It emphasizes compact syntax, modules, and a small standard surface for I/O and tests.

This document is the **language contract** aligned with `TERSE_BNF.md` and the **Python reference compiler** (`tersec.py`). The native self-hosting compiler (`tc.te`) is an experimental subset and is **not** the conformance reference.

**Status labels:** **Implemented** (host), **Limited**, **Planned**.

---

## 1. Design Goals

- Extremely terse syntax with high signal-to-noise.
- Ahead-of-time compilation to a single native binary via a C backend.
- Small runtime; practical std for strings, I/O, and unit tests.
- Modules with explicit `pub` exports (enums public by default).
- Prefer working examples and a green test suite over a complete academic feature set.

---

## 2. Lexical Structure

### Comments
```
// line comment
/* block comment */
```

### Identifiers
```
ident ::= [a-zA-Z_][a-zA-Z0-9_]*
```

### Keywords (reserved)
`fn`, `val`, `var`, `fix`, `type`, `if`, `else`, `use`, `ret`, `true`, `false`, `rec`, `en`, `tr`, `self`, `pub`, `lp`, `brk`, `skip`, `go`, `pr`, `npr`


### Literals
- Integer: `42`, `-7` → `long`
- String: `"hello"` with `\n`, `\r`, `\t`, `\"`, `\\`, `\0`
- Boolean: `true`, `false`
- Lists: `[1, 2, 3]`, `["a", "b"]`
- Maps: `{:}`, `{"a": 1}`

### Operators
Arithmetic: `+` `-` `*` `/` `%`  
Comparison: `==` `!=` `<` `>` `<=` `>=`  
Logical: `&&` `||` `!`  
Assignment: `=` `+=` `-=` `*=` `/=` `%=`  
Pipe: `|>`  
Ternary: `cond ? then : else`  
Lambda: `|params| body`

### Core Semantics
- Exactly one `go` entrypoint per executable (`go { ... }` or `go = expr`).
- `val` = immutable binding; `var` = mutable.
- Blocks evaluate statements in order; the **block value** is the last expression (or `0` if empty).
- `ret expr` / `ret` always **return from the enclosing function** (not from the block alone). A bare last expression yields the block value without exiting the function.
- `pr(x)` prints a line; `npr(x)` prints without a trailing newline and returns `0`. If `pr` ran, `main` does not print an extra numeric result.
- `+` on strings concatenates; `str + long` / `long + str` convert the number.
- `+` on lists: concat (`[str]`/`[long]`) or push one element (`list + elem`).

---

## 3. Types

### Primitives

Canonical names only (no aliases):

| Name | C backend | Notes |
|------|-----------|--------|
| `bool` | `bool` | |
| `str` | `const char*` | |
| `chr` | `int8_t` | 8-bit signed |
| `byte` | `uint8_t` | 8-bit unsigned |
| `int` | `int32_t` | 32-bit signed |
| `long` | `int64_t` | **default** for unannotated integer literals |
| `flt` | `float` | 32-bit float |
| `dbl` | `double` | **default** for float literals |

Integer types mix freely; int↔float promotes toward float. `str` does not mix with numbers (type error).

### Composite
| Form | Example | Notes |
|------|---------|--------|
| List | `[long]`, `[str]` | Implemented |
| Map | `{str: long}`, `{str: str}` | Implemented |
| Record | `rec Point { x: long, y: long }` | Implemented |
| Enum | `en Option { Some(long), None }` | Implemented; payloads ok |
| Trait | `tr Printable { fn str() -> str }` | Implemented (implicit satisfaction) |
| Function | `fn(long) -> long` | Limited higher-order |
| Tuple | `(long, str)` | Limited — tuple returns, literals, printing, and local destructuring are implemented; tuple patterns are not |

Inference is local. Annotate non-`long` parameters/returns when needed.

---

## 3b. Generics (phase 1 — host)

Parametric functions with **monomorphization** (no runtime dictionaries):

```terse
fn id[T](x: T) -> T = x
fn first[T](xs: [T]) -> T = xs[0]

id(42)           // infer T=long
id[str]("hi")    // explicit
first(xs)        // infer T from list element
```

- Type params: `[T]` or `[A, B]` after the name.
- Call with inference or explicit `name[Type](...)` / `name[A,B](...)`.
- Each concrete use emits a specialized C function (`id__long`, …).
- Generic **`rec Box[T]`** and **`en Opt[T]`** — monomorphize at use:
  `Box[long] { value: 1 }`, `Opt[long].Some(3)`.
- **Known limitation:** pattern arms may require specialized names (`Opt__long.Some(x)`) until demangling lands.
- Generic **`tr Eq[T]`** — structural satisfaction after substitution is supported for generic bounds and local trait values such as `val s: Show[Point] = point`; generic trait-typed function parameters such as `fn f(p: Show[Point])` remain limited.
- Generic trait bounds are supported on type params: `fn max[T: Ord](a: T, b: T) -> T = a.lt(b) ? b : a`.
- Remaining polish: pretty pattern names without `__`.

## 4. Declarations & Visibility

### Visibility quick reference

| Construct | Default | Export with |
|-----------|---------|-------------|
| `en` | **public** | (always available via `use`) |
| `fn` / `rec` / `tr` | **private** | `pub` |
| `fix` | **file-local** | `pub fix` |

Tests under `tst/**/t_*.te` may call non-`pub` fns from a parallel `src/` module.


| Declaration | Default visibility | Export with |
|-------------|-------------------|-------------|
| `fn` / methods | **private** | `pub fn` |
| `rec` | **private** | `pub rec` |
| `tr` | **private** | `pub tr` (when used) |
| `en` | **public** | (always exportable via `use`) |
| `fix` | **private (file-local)** | `pub fix` |

```
pub fn add(a: long, b: long) -> long = a + b

pub rec Point { x: long, y: long }

en Option { Some(long), None }     // public by default

fix SECRET = 1                    // file-local only
pub fix VERSION: str = "0.3"      // exported
```

Methods: `fn Point.add() -> long { self.x + self.y }`

### Parameter overloading **Implemented (host)**
Multiple functions may share a **name** if their **parameter type lists** differ:

```
fn eq(got: long, exp: long) -> long { ... }
fn eq(got: str, exp: str) -> long { ... }
fn eq(got: int, exp: int) -> long { ... }     // distinct from long overload
```

Rules:
- Resolution is **type-directed** at each call site (argument types after local checking).
- Identical signatures for the same name are a **type error**.
- Integer-width fallback: if no exact overload exists, integer widths may be considered equivalent (e.g. `int` arg to `long` param) when unique.
- Each overload is a distinct C symbol: `terse_eq__long_long`, `terse_eq__str_str`, …
- A single definition of a name still emits `terse_<name>` (no suffix).
- Parameters may have defaults: `fn f(a: long, b: long = a + 1) = ...`.
  Defaulted parameters must be trailing. Omitted defaults are evaluated at the
  call site, with references to earlier parameters substituted from the call.
  Defaults are supported for functions; methods do not yet support them.
- Calls must provide every required argument and no more than the declared
  parameter count.
- Return type is not part of the overload key (only parameters).


---

## 5. Modules (`use`)

```
use std.tst
use std.str
use std.io
use math                  // → lib/math.te  (optional package)
use arith                 // → src/arith.te (app module)
use usage.result_option   // → src/usage/result_option.te
```

### Resolution order (importer `path/to/file.te`)

Dots in the path become directories: `use foo.bar` → `foo/bar.te`.

1. Same directory as the importer  
2. **Parallel `src/`** when under `tst/` (`tst/usage/t_mod.te` → `src/usage/mod.te`)  
3. Project **`lib/<module>.te`** (optional packages shipped with Terse)  
4. Project **`src/<module>.te`** (application modules)  
5. Project root / cwd / parent fallbacks  

For `use std.*` only:

1. `lib/std/<name>.te`  
2. `std/<name>.te`  
3. Host builtin surface (no file required)

### Optional packages (`lib/`)

Optional libraries that ship with the Terse tree but are **not** part of the frozen std surface (§8):

| File | Import | Call style |
|------|--------|------------|
| `lib/calc/math.te` | `use calc.math` | `math.abs(x)`, `math.fact(5)` (alias = last segment) |
| `lib/cnx/http.te` | `use cnx.http` | `http.srv(...)`, `http.success(...)` |
| `lib/std/tst.te` | `use std.tst` | `tst.eq(...)` |

**Path rule:** `use a.b.c` maps to path segments under `lib/` or `src/` (first hit wins):

1. Next to the importing file  
2. `lib/a/b/c.te`  
3. `src/a/b/c.te`  
4. Project root `a/b/c.te`  

Alias is the **last** segment (`use calc.math` → `math`). In `tst/` sources, public names are also available unqualified.

Rules:

- Export with **`pub fn`** / **`pub rec`** (tests under `tst/` may see non-`pub` too)
- Prefer package paths under `lib/` for optional libraries
- No package registry yet — “install” means the file is on the search path
- Optional: `python3 compiler/tersec.py lib lib/calc/math.te` builds `~/.terse/out/lib/...`

### What `use m` imports
- `pub fn` (and all fns when the importer is a **test** `tst/**/t_*.te`)
- `pub rec` and methods on exported types (tests see all recs/methods)
- All `en` (public by default)
- `pub fix` only (plain `fix` stays file-local; rewritten internally for module code)
- `std.*` is a builtin surface (no `.te` required when the file is missing)

Call through the module alias: `math.fact(5)`, not `fact.fact(5)`.

Unqualified calls after `use m` in **tests**: `use mod` → `mod()` works even when the function is named `mod`.

Modules may contain `go` (ignored when imported as a library).

---

## 6. Control Flow

```
if cond { ... } else if ... { ... } else { ... }

// Pattern if (arms with =>)
if r {
  Result.Ok(n) => n
  Result.Err(msg) => 0
  _ => -1
}

lp x: xs { ... }         // for-in (lists, map keys)
lp i = 0; i < n; i = i + 1 { ... }
lp cond { ... }

ret expr                 // return from function (not only the block)
brk                      // break loop
skip                     // continue loop

work() trap e: {          // handle err(...) raised by work()
  pr("failed: " + e)
}
```


`trap name: { ... }` attaches to the immediately preceding expression and catches the nearest `err(message)` raised while evaluating it, including errors propagated from called functions. The handler binding is a `str`. A handler may rethrow with `err(name)`; that error propagates to the next enclosing trap. An uncaught error prints to stderr and exits with status 1. A trap expression evaluates to `0`.

Ternary: `cond ? then : else`

**Pipe** `|>` is left-to-right application (parse rewrite): `xs |> map(f) |> sum()` → `sum(map(xs, f))`.

---

## 7. Lists & Maps

### Lists
```
var xs: [long] = []
xs = xs + 1              // push one element (preferred; no separate push())
xs = xs + [2, 3]         // concat
len(xs)
xs[i]
map(xs, f)               // apply f to each element → new list
xs |> map(|n| n * 2)     // pipe form

var ss: [str] = []
ss = ss + ["a"] + "b"
```

`map` is part of the host list surface (not “limited”). There is no separate `push` builtin — use `list + elem`.


### Maps — missing keys

- `m[k]` on a missing key returns **`0`** (`{str:long}`) or **`""`** (`{str:str}`); it does **not** abort.
- Use `has(m, k)` before read when absence is an error.
- List index OOB still aborts: `index out of bounds: index N len M`.

### Maps
Host supports **string keys** and **long or str values** (`{str: long}`, `{str: str}`).

```
var m: {str: long} = {:}
m["a"] = 3
pr(m["a"])
len(m)
has(m, "a")              // bool
keys(m)                  // [str]
lp k: m { ... }          // iterate keys
```

---

### Traits (`tr`) — current + needed for maturity

**Today (structural, non-generic):**

```terse
tr Printable { fn str() -> str }
fn Point.str() -> str { ... }
fn print(p: Printable) { pr(p.str()) }
```

A `rec` **satisfies** a trait when it has methods with matching names and signatures (implicit; no `impl` keyword).
Trait-typed parameters and local bindings accept structurally satisfying records:

```terse
val p = Point { x: 1, y: 2 }
val printable: Printable = p
print(printable)
```

Trait method calls dispatch through the generated adapter for the concrete record type.

**To grow traits later (not phase 1):**

| Need | Why |
|------|-----|
| Generic traits `tr Eq[T]` | Shared behavior over type params |
| Explicit `impl` or keep structural | Clarity vs ceremony |
| Dynamic dispatch (vtable) **or** monomorphize trait params | `fn f(p: Printable)` today is likely specialized/adapter |
| Super-traits / defaults | Only if real demand |
| `tr` + generics interaction | `fn sort[T: Ord]` |

Prefer **structural + monomorphize** to stay Terse; add vtables only if you need heterogeneous lists of trait objects.

## 8. Standard Library Surface (frozen host 0.3)

**Freeze:** the host implements **only** what is listed here. New std APIs require a SPEC + BNF note and a test.  
Names are not keywords — use `use std.*` or call the same names as builtins (host).

### Strings: `+` and `fmt`

**Concatenation** uses `+`. At least one side is `str`; the other may be `str`, `long`/`long`, or `bool` (converted automatically):

```terse
"hi " + name
"n=" + 42
"ok=" + true
```

**`fmt(...)`** is a minimal multi-arg helper: each argument is stringified and concatenated (same conversions as `+`). Prefer this when chaining many pieces:

```terse
fmt("x=", x, " y=", y)
fmt(GREETING, " ", ANSWER)   // fix/str + int
```

There is no `"{x}"` interpolation yet — use `+` or `fmt`.

### `std.str`
```
str.has(s, sub) -> bool
str.starts(s, prefix) -> bool
str.ends(s, suffix) -> bool
str.fnd(s, sub) -> long
str.rpl(s, old, new) -> str
str.trim(s) -> str
str.up(s) / str.low(s) -> str
str.parse(s) -> long
str.split(s, sep) -> [str]
str.join(parts, sep) -> str
str.rpt(s, count) -> str
str.empty(s) -> bool
str.len(s) -> long
str.sub(s, start, end) -> str
```
String operations also have receiver-method spellings: `s.has(sub)`,
`s.start(prefix)`, `s.end(suffix)`, `s.fnd(sub)`, `s.rpl(old, new)`,
`s.trim()`, `s.up()`, `s.low()`, `s.split(sep)`, `s.rpt(count)`,
`s.empty()`, and `s.len()`. The module names for start/end checks are
`str.starts` and `str.ends`; `fnd`, `rpl`, and `rpt` use the same names in
receiver and module form. `parse` and `join` are available in `str` module form.
`len`, `sub`, `fnd`, `has`, `starts`, `ends`, `trim`, `split`, `up`, `low`,
`empty`, `rpl`, and `rpt` are implemented in `lib/std/str.te`; use
`use std.str` when calling them.

String indexing, lengths, and slices use UTF-8 bytes, not Unicode code points.
`str.sub(s, start, end)` and slice syntax `s[start..end]` use half-open ranges:
the start is included and the end is excluded.
Endpoints are clamped to the string; if the clamped end is before the start,
the result is empty. `fnd` returns the first byte offset or `-1`.
`rpl` replaces all non-overlapping occurrences; an empty search string
leaves the input unchanged. `rpt` returns an empty string for non-positive
counts. Case conversion is ASCII-only, and trim removes ASCII spaces, tabs,
carriage returns, and newlines from both ends. `split` preserves empty fields;
an empty separator splits into one-byte strings.
The library's `len` wrapper and `sub` implementation use the host's basic
length and slice primitives.

Unqualified `has`/`starts`/`ends` prefer `std.str` when the receiver is `str`;
map `has(m, k)` requires a map as first argument (overload by type).

### `std.io`
```
io.in(path) -> str       // read text file
io.out(path, text) -> long
```

### `std.err`
```
err(message)             // raise a string error; caught by the nearest trap
```

`use std.err` makes the error API explicit; `err(message)` is also available as a host builtin.

### `std.tst`
```
tst.eq(got, expected)      // fail if unequal
tst.ne(got, unexpected)    // fail if equal
tst.chk(expected, actual)  // eq, expected first
tst.report()               // summary (auto in t_*.te)
```
Continues after failure; process exit code is the failure count.

### Environment
```
env("KEY")           // -> str; missing key → ""
env("KEY") = "value" // set process env (setenv / _putenv_s)
```

### Maps (builtins)
```
has(m, key) -> bool
keys(m) -> [str]
len(m) -> long
```

### Other core builtins
`pr`, `len`, `arg`.

### Limited / not part of the freeze
`json` (limited), list `map`, minimal `http.serve` (limited). SQL/`db` is **disabled** in lean builds.

---

## 9. Unit Tests

Layout:

```
src/…              // libraries under test
tst/t_*.te         // tests (any depth, e.g. tst/usage/t_mod.te)
tst/expect_fail/   // must fail asserts (non-zero exit)
tst/expect_error/  // must fail to compile (clear error message)
std/               // std surface docs / stubs
```

Rules for `tst/**/t_*.te`:
- Auto-run every zero-arg `fn` (no `go` required)
- Non-`pub` functions of the module under test are visible
- Parallel path: `use mod` from `tst/usage/` loads `src/usage/mod.te`

```sh
bash test.sh
# pass tests + expect_fail + expect_error
```

---


## 10. Diagnostics

The host compiler (`tersec.py`) reports problems before or instead of opaque C errors whenever possible.

### Hard errors (compile aborted)

| Message | Meaning |
|---------|---------|
| `type error: unknown name 'X'` | Identifier not in scope (locals, `fix`, enums, imports) |
| `type error: unknown function 'X'` | Call to an undefined function |
| `type error: type mismatch: ...` | Assign/arg/compare with incompatible types (e.g. `str` vs `int`) |
| `error: N error(s) — compile aborted` | Summary after one or more hard errors |

Hard errors of the form `unknown …` stop the pipeline **before** gcc/clang, so you should not see `undeclared identifier` from the C compiler for simple name mistakes.

### Warnings

Other type-checker findings may be printed as `type warning: …` without aborting (limited coverage in 0.3).

### Source locations

When the AST carries line/column (e.g. calls), messages may include `at line:col`. Coverage is best-effort and still expanding.

### Loops

C-style `lp i = 0; cond; step { … }` introduces `i` into the type-checker environment for the loop body and step, so `i` is not reported as unknown inside the loop.

### Tests

`tst.eq` / `tst.ne` failures print `FAIL file:line: …` on stderr, continue the suite, and set a non-zero process exit code equal to the failure count. See §9.

---

## 11. Compilation

### Standard library & packages (host)
- Frozen std: `lib/std/<name>.te` (fallback `std/<name>.te`, then host builtins)
- Optional packages: `lib/<name>.te` → `use <name>` (e.g. `lib/math.te` → `use math`)
- `use std.tst` loads `lib/std/tst.te` when present (Terse helpers); host still provides `tst.report` counting

### Output layout (host)
- Default binary directory: `~/.terse/out/` (env `TERSE_OUT` or `TERSE_HOME`, default home `~/.terse`)
- Library objects: `~/.terse/out/lib/<module>.o` via `python3 tersec.py lib module.te`
- Shared runtime: `~/.terse/out/lib/terse_rt.o`
- Rebuild skipped when the binary is newer than source inputs; `-f` forces rebuild
- `--no-libs` skips linking objects from the lib directory

## 11b. Compilation (commands)


```sh
python3 tersec.py build main.te -o app
python3 tersec.py run main.te
```

- Frontend: lexer → parser → modules → type check → C codegen  
- Backend: `gcc`/`clang` `-O0 -std=c11` ( `-O0` avoids optimizer stress on generated C )  
- Unknown names/functions are **hard errors** (compile aborted before gcc when possible)

---

## 12. Compiler Status (0.3 host)

### Implemented
- Arithmetic, comparisons, `val`/`var`, blocks, `ret`, ternary, pipe `|>`  
- `fix` / `pub fix` (private by default)  
- Functions, methods, recursion, simple lambdas (no capture)  
- Parameter overloading (distinct param type lists)  
- Records, enums (+ payloads), non-generic traits (implicit satisfaction)  
- Pattern `if` arms
- Loops: for-in, C-style, condition; `brk` / `skip`  
- Lists width types `[int]`/`[long]`/`[dbl]`/`[str]`/… (+, len, index, `map`)  
- Maps `{str:long|str}`: put/get, `has`, `keys`, `len`, for-in keys  
- Modules: `use`, `pub`, nested packages (`use calc.math` → `lib/calc/math.te`), parallel `tst`↔`src`  
- Frozen std: `std.str`, `std.io`, `std.tst`; `env` get/set; `fmt`  
- `go` entry; `pr`; string/int concat  
- Unit-test runner; hard errors for unknown names/functions  
- Output: `~/.terse/out`; optional `lib` objects (`TERSE_AUTOLIB` for auto-link)  

### Limited
- Higher-order / closures with capture  
- Generics: monomorphized `fn`/`rec`/`en`; specialized pattern names (`Opt__long`); generic trait *params* incomplete  
- Tuple types/patterns (parsed; not a polished feature)  
- HTTP via `lib/cnx/http.te` (blocking single-connection `srv`)  
- Full structural type errors (beyond unknown names)

### Planned / not host-complete
- Ownership/borrowing  
- Native `tc.te` feature parity with host  
- Trait constraints / demangled generic patterns  
- Async / scalable HTTP  
  

---

## 13. Examples

See `eg.te`, `src/`, `usage/`, and `tst/` alongside the compiler.


## Async models

### Thread async (`~~` / `~`)

- `~~ fn f(...)` — may run on a host thread
- `f(...)` without `~` — fire-and-forget (tracked; drain at exit)
- `~ f(...)` — spawn and join (blocks the calling thread)

### Event-loop async (`~~>` / `~>`)

- `~~> fn handle(...)` — connection task for `sock.nb_srv` / `nhttp.asrv`
- `~> tim.wait(ms)` — **suspend** this connection; the select loop continues serving others
- Response is delayed until the wait completes (not a background side-effect)

Use `~~>` handlers with non-blocking servers. Do not use bare `tim.wait` or `~` (thread join) inside the loop thread.

