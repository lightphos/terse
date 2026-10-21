# Terse Language Specification 0.3

**Terse** is a succinct, statically typed language that compiles to native binaries. It emphasizes compact syntax, modules, and a small standard surface for I/O and tests.

This document is the **language contract** aligned with `terse_bnf.md` and the **Python reference compiler** (`tersec.py`). The native self-hosting compiler (`tc.te`) is an experimental subset and is **not** the conformance reference.

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
`fn`, `val`, `var`, `fix`, `type`, `if`, `else`, `match`, `use`, `ret`, `true`, `false`, `rec`, `en`, `tr`, `self`, `pub`, `while`, `lp`, `brk`, `skip`, `go`, `pr`


### Literals
- Integer: `42`, `-7` → `i64`
- String: `"hello"` with `\n`, `\t`, `\"`, `\\`
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
- Blocks evaluate statements in order; value is the last expression (or `0` if empty).
- `ret expr` returns from the current function; `ret` returns `0`.
- `pr(x)` prints a line and returns `0`. If `pr` ran, `main` does not print an extra numeric result.
- `+` on strings concatenates; `str + i64` / `i64 + str` convert the number.
- `+` on lists: concat (`[str]`/`[i64]`) or push one element (`list + elem`).

---

## 3. Types

### Primitives
Primary: `i64`, `bool`, `str`.

Integers (aliases in parentheses):  
`i8` (`char`), `i16` (`short`), `i32` (`int`), `i64` (`long`),  
`u8`, `u16`, `u32`, `u64`

Floats: `f32` (`float`), `f64` (`double`) — float literals are `f64`.

Integer types mix freely; int↔float promotes toward float. `str` does not mix with numbers (type error).

### Composite
| Form | Example | Notes |
|------|---------|--------|
| List | `[i64]`, `[str]` | Implemented |
| Map | `{str: i64}`, `{str: str}` | Implemented |
| Record | `rec Point { x: i64, y: i64 }` | Implemented |
| Enum | `en Option { Some(i64), None }` | Implemented; payloads ok |
| Trait | `tr Printable { fn str() -> str }` | Implemented (implicit satisfaction) |
| Function | `fn(i64) -> i64` | Limited higher-order |

Inference is local. Annotate non-`i64` parameters/returns when needed.

---

## 4. Declarations & Visibility

| Declaration | Default visibility | Export with |
|-------------|-------------------|-------------|
| `fn` / methods | **private** | `pub fn` |
| `rec` | **private** | `pub rec` |
| `tr` | **private** | `pub tr` (when used) |
| `en` | **public** | (always exportable via `use`) |
| `fix` | **private (file-local)** | `pub fix` |

```
pub fn add(a: i64, b: i64) -> i64 = a + b

pub rec Point { x: i64, y: i64 }

en Option { Some(i64), None }     // public by default

fix SECRET = 1                    // file-local only
pub fix VERSION: str = "0.3"      // exported
```

Methods: `fn Point.add() -> i64 { self.x + self.y }`

### Parameter overloading **Implemented (host)**
Multiple functions may share a **name** if their **parameter type lists** differ:

```
fn eq(got: i64, exp: i64) -> i64 { ... }
fn eq(got: str, exp: str) -> i64 { ... }
fn eq(got: long, exp: long) -> i64 { ... }   // long ≡ i64 → same as first; error if identical
```

Rules:
- Resolution is **type-directed** at each call site (argument types after local checking).
- Identical signatures for the same name (after alias normalization) are a **type error**.
- Aliases normalize before comparing: `long`≡`i64`, `int`≡`i32`, `short`≡`i16`, `char`≡`i8`, `float`≡`f32`, `double`≡`f64`.
- Soft match: if no exact overload, integer widths may match each other (e.g. `i32` arg to `i64` param) when unique.
- Each overload is a distinct C symbol: `terse_eq__i64_i64`, `terse_eq__str_str`, …
- A single definition of a name still emits `terse_<name>` (no suffix).
- Arity must match; no default arguments or optional parameters.
- Return type is not part of the overload key (only parameters).


---

## 5. Modules (`use`)

```
use std.tst
use std.str
use std.io
use arith                 // → src/arith.te (or parallel path)
use usage.result_option   // → usage/result_option.te
```

### Resolution order (importer `path/to/file.te`)
1. Same directory as the importer  
2. **Parallel `src/`** when under `tst/` (`tst/usage/t_mod.te` → `src/usage/mod.te`)  
3. Project `src/<module>.te`  
4. Project root / cwd fallbacks  

### What `use m` imports
- `pub fn` (and all fns when the importer is a **test** `tst/**/t_*.te`)
- `pub rec` and methods on exported types (tests see all recs/methods)
- All `en` (public by default)
- `pub fix` only (plain `fix` stays file-local; rewritten internally for module code)
- `std.*` is a builtin surface (no `.te` required)

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
while cond { ... }

ret expr
brk                      // break
skip                     // continue
```

Ternary: `cond ? then : else`

---

## 7. Lists & Maps

### Lists
```
var xs: [i64] = []
xs = xs + 1
xs = xs + [2, 3]
len(xs)
xs[i]

var ss: [str] = []
ss = ss + ["a"] + "b"
```

### Maps
Host supports **string keys** and **i64 or str values** (`{str: i64}`, `{str: str}`).

```
var m: {str: i64} = {:}
m["a"] = 3
pr(m["a"])
len(m)
has(m, "a")              // bool
keys(m)                  // [str]
lp k: m { ... }          // iterate keys
```

---

## 8. Standard Library Surface (frozen host 0.3)

**Freeze:** the host implements **only** what is listed here. New std APIs require a SPEC + BNF note and a test.  
Names are not keywords — use `use std.*` or call the same names as builtins (host).

### `std.str`
```
str.has(s, sub) -> bool
str.starts(s, prefix) -> bool
str.ends(s, suffix) -> bool
str.trim(s) -> str
str.up(s) / str.low(s) -> str
str.parse(s) -> i64
str.split(s, sep) -> [str]
str.join(parts, sep) -> str
```
Unqualified forms (`has(s, sub)`, …) are accepted by the host when not ambiguous with map `has`.

### `std.io`
```
io.in(path) -> str       // read text file
io.out(path, text) -> i64
```

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
len(m) -> i64
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
| `type error: type mismatch: ...` | Assign/arg/compare with incompatible types (e.g. `str` vs `i32`) |
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

### Standard library location (host)
- Preferred: `lib/std/<name>.te` (project `lib/`, or `src/../lib/`)
- Fallback: `std/<name>.te`, then host builtins
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
- Arithmetic, comparisons, `val`/`var`, blocks, `ret`, ternary  
- `fix` / `pub fix` (private by default)  
- Functions, methods, recursion, simple lambdas  
- Parameter overloading (distinct param type lists)  
- Records, enums (+ payloads), traits (implicit)  
- Pattern `if` / `match`  
- Loops: for-in, C-style, condition; `brk` / `skip`  
- Lists width types `[i32]`/`[i64]`/`[f64]`/`[str]`/… (+, len, index, push)  
- Maps `{str:i64|str}`: put/get, `has`, `keys`, `len`, for-in keys  
- Modules: `use`, `pub`, parallel `tst`↔`src`  
- Frozen std: `std.str`, `std.io`, `std.tst`; `env` get/set  
- `go` entry; `pr`; string/int concat  
- Unit-test runner; hard errors for unknown names/functions  
- Output: `~/.terse/out`; optional `lib` objects (`TERSE_AUTOLIB` for auto-link)  

### Limited
- Higher-order / closures with capture  
- Full generics, tuples  
- HTTP beyond minimal serve  
- Full structural type errors (beyond unknown names)

### Planned / not host-complete
- Ownership/borrowing  
- Native `tc.te` feature parity with host  
- Richer package system beyond path `use`  
  

---

## 13. Examples

See `eg.te`, `src/`, `usage/`, and `tst/` alongside the compiler.
