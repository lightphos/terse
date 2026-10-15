# Terse Language Specification 0.2

**Terse** is a succinct, statically typed language that compiles to native binaries. It emphasizes compact syntax, first-class functions, and practical facilities for I/O and services.

This document describes the language contract aligned with the parser grammar in `BNF.md`. **Implemented** means supported by the Python reference compiler (`tersec`); **Limited** means only a subset works; **Planned** means the syntax or behavior is not yet available. The Terse-written compiler (`tc.te`) is an experimental subset and is not the reference for language conformance.

## 1. Design Goals

- Extremely terse syntax with high signal-to-noise.
- First-class functions and higher-order programming (pass, return, nest functions).
- Ahead-of-time compilation to a single native binary via a C-based backend.
- Small runtime footprint and straightforward code generation for portability.
- Practical built-ins for simple HTTP services and basic data I/O.
- Type checking and basic inference for the implemented subset.
- A pragmatic implementation path that favors working examples over a complete feature set.

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

Keywords (reserved), aligned with `BNF.md`:

`fn`, `val`, `var`, `fix`, `type`, `if`, `else`, `match`, `use`, `ret`, `true`, `false`, `rec`, `en`, `tr`, `self`, `pub`, `while`, `lp`, `brk`, `skip`, `go`, `pr`

Additional names used by the runtime / std surface (not all are hard keywords in the lexer):  
`None`, `Some`, `Ok`, `Err`, `get`, `post`, `put`, `delete`, `http`, `db`, `json`, `env`, `status`

`let` and `mut` are **not** part of the language. Use `val` (immutable) and `var` (mutable).

### Literals
- Integer: `42`, `-7` (i64 by default)
- Float: `3.14` (f64; limited compiler support)
- String: `"hello"`, basic escapes (`\n`, `\t`, `\"`, `\\`)
- Boolean: `true`, `false`
- Unit: `()`

### Operators
Arithmetic: `+` `-` `*` `/` `%`  
Comparison: `==` `!=` `<` `>` `<=` `>=`  
Logical: `&&` `||` `!`  
Assignment: `=` `+=` `-=` `*=` `/=` `%=`  
Pipe: `|>` (insert left-hand value as first argument of the right-hand call)  
Lambda: `|params| body`  
Postfix: `.` field/method, `()` call, `[]` index, `?` (reserved in grammar)

### Core Semantics

- An executable has exactly one `go` entrypoint: `go { ... }` or `go = expr`. There is no implicit entrypoint; `fn main` is rejected.
- Functions may call declared functions recursively. Omitted parameter and return annotations currently default to `i64` in the reference compiler.
- `&&` and `||` short-circuit. Comparisons and logical operators produce `bool`; arithmetic uses integer values unless `+` performs string concatenation.
- A block evaluates its statements in order and has the value of its final expression. An empty block has value `0`. `ret expr` exits the current function with that value; `ret` returns `0`.
- **`val`** introduces an immutable binding. **`var`** introduces a mutable binding that may be reassigned with `=` / `+=` / etc.
- Strings are UTF-8 byte sequences. `len(str)` / `s.size` count bytes; `str[index]` returns the unsigned value of one byte.
- `pr(value)` writes the value followed by a newline and returns `0`. If `go` returns `0` after printing, the runtime suppresses the extra numeric `0`.
- Integer overflow and division by zero are not portably specified in 0.2.

### Status Labels

Syntax in this document tracks `BNF.md`. Section 12 identifies reference-compiler support. Reserved words may exist before their constructs are fully implemented.

## 3. Types

### Primitive Types
- `i64`, `i32`, `u64`, `bool`, `f64`, `str` (UTF-8 string), `()` (unit)

### Composite
- Function types: `fn(T1, T2) -> R`
- Records: `rec Name { field: Type, ... }`
- Enums: `en Name { Variant, Variant(T), ... }` (tag-only or with typed payloads)
- Traits: `tr Name { fn method(...) -> T }`
- Lists: `[T]`
- Maps: `{K: V}` (v1: `str` keys, `i64` or `str` values)
- Tuples: `(T1, T2, ...)` (grammar present; limited implementation)
- Option / Result: planned (`Option[T]`, `Result[T, E]`)

Type inference is local and limited. Top-level functions often need annotations for non-`i64` cases.

In the current compiler, `i64`, `bool`, `str`, integer lists, named records, enums, traits, and function values have the strongest support.

## 4. Syntax (Core)

Grammar source of truth: `BNF.md`.

### Program
A program is a sequence of items with one `go` entrypoint.

```
item ::= use-decl | type-decl | record-decl | enum-decl
       | trait-decl | fn-decl | go-decl
```

### Records, enums, traits
```
rec Point {
  x: i64,
  y: i64,
}

en Colour {
  Red,
  Green,
  Blue,
}

tr Printable {
  fn str() -> str
}

fn Point.show() -> i64 { 7 }       // method on Point
fn Point.str() -> str { "ok" }     // satisfies Printable implicitly
```

### Enums (with optional payloads)
```
en Colour {
  Red,
  Green,
  Blue,
}

en Option {
  Some(i64),
  None,
}

en Result {
  Ok(i64),
  Err(str),
}

// construction
val c = Colour.Green
val o = Option.Some(42)
val r = Result.Err("fail")

// match with payload binding
match o {
  Option.Some(n) => n
  Option.None => 0
}
```

### Functions
```
fn name(params) -> RetType = expr
fn name(params) -> RetType { stmts }

// Lambda
|param1, param2| expr
|param1: Type| { stmts }
```

Parameters and return types may be omitted (default `i64` in the reference compiler).

Higher-order example:
```
fn apply(f: fn(i64) -> i64, x: i64) -> i64 = f(x)
val double = |n| n * 2
apply(double, 21)
```

### Bindings (`val` / `var`)
```
val name = expr
val name: Type = expr
var name = expr
var name: Type = expr

// reassignment (var only)
name = expr
name += expr
```

- `val` — immutable local binding
- `var` — mutable local; may be updated with assignment operators

### Fixed constants (`fix`)
```
fix NAME: Type = expr
fix NAME = expr
```

Top-level immutable constants. Evaluated at compile time when the initializer is a literal (or a simple constant expression). Usable anywhere in the program after declaration.

Example:
```
fix GREETING: str = "CONST_STRING"
fix ANSWER: i64 = 42

go {
  pr(GREETING)
  pr(ANSWER)
}
```

There is no `let` or `mut` keyword.

### Control Flow
```
if cond { then } else if other { ... } else { otherwise }
ret
ret expr
brk
skip

// for-each
lp x:xs { body }

// while-style
lp cond { body }
while cond { body }

// C-style
lp i = 0; i < xs.size; i = i + 1 { body }

match expr {
  pat1 => result1
  pat2 if guard => result2
  Colour.Red => "red"
  _ => default
}
```

`if` and `match` are expressions. Loops evaluate to `0` when they exit normally. `brk` exits the nearest `lp`/`while`; `skip` continues it (runs the C-style loop step when present).

Ternary: `cond ? then : else`

### Maps
```
var m: {str: i64} = {:}          // empty
val n = {"a": 1, "b": 2}         // literal
m["a"] = 3                       // put (updates m)
pr(m["a"])                       // get (0 / "" if missing)
pr(len(m))
```
Keys: `str`. Values: `i64` or `str` in v1.
 (same types on both branches preferred).

### Match-style `if` (pattern discrimination)
When the body uses `=>` arms, `if` acts like `match`:

```
if r {
  Result.Ok(n) => "ok"
  Result.Err(msg) => msg
  _ => "default"          // catch-all
}
```

Catch-all / default:
- `_ => expr` — wildcard arm (preferred, inside the braces)
- trailing `else { expr }` — sugar for `_ => expr`

Normal boolean `if cond { block }` is unchanged when the body has no `=>`.
`match` remains available as an explicit form.

### Function application & pipe
```
f(arg1, arg2)
xs |> map(double) |> sum()    // pipe: left value becomes first argument
```

## 5. Higher-Order Functions

Functions are first-class values. They can be stored, passed, returned, and nested.

Example:
```
fn make_multiplier(factor: i64) -> fn(i64) -> i64 {
  |x| x * factor
}

val times3 = make_multiplier(3)
times3(10)   // 30
```

Full closures with mutable environment capture remain limited.

## 6. Strings, Lists, Print, Basic I/O

### Strings
```
"hello"
"hel" + "lo"          // concat
len(s)                // length (bytes)
s.size                // same for lists/strings where supported
s[i]                  // byte at index (i64)
pr(s)
```

### Lists (of i64)
```
[1, 2, 3]
len(xs)
xs.size
xs[i]
pr(xs)             // prints [1, 2, 3]
```

Type annotation: `[i64]` in signatures when needed.

### Printing
```
pr(42)
pr("hi")
pr([1, 2])
pr(x)
```
`pr` is a builtin; returns `0`.

### Basic I/O
- `pr(value)` → stdout (ints, strings, lists, records); returns `0`

### File I/O (`fs` module)
Not keywords — library calls. Import is optional for the reference runtime
(names resolve as builtins when the backend provides them).

```
fs.read_text(path: str) -> str
fs.write_text(path: str, text: str) -> i64   // bytes written
```

- Paths are native filesystem paths (string)
- Text is UTF-8
- On failure the process prints an error and exits nonzero
- No partial-read API, binary I/O, or streaming in 0.2

Related driver helpers used by `tc.te`:
```
env(name: str) -> str           // getenv; "" if unset
gcc.compile(c_path: str, out: str) -> i64   // invoke system gcc
arg(index: i64) -> str          // process argv
```

BNF does not list library functions; this section is the contract.

### Example
```
go {
  pr("hello terse")
  val xs = [10, 20, 30]
  pr(xs)
  pr(len(xs))
  pr(xs[1])
  val s = "hel" + "lo"
  pr(s)
}
```

## 7. REST APIs

```
use std.http

http.serve(port: i64) {
  get "/path" => expr_or_block
  get "/users/:id" => |id: i64| { ... }
  post "/users" => |body: User| { ... }
  put ...
  delete ...
}
```

- Minimal `http.serve` for simple route handlers
- Handlers may return strings or JSON values
- Full middleware and rich request decoding are not yet provided
- The `http.serve` block is the main event loop of the process

## 8. Database Access (Limited / disabled in some builds)

```
use std.db

db.connect(url: str)
db.query[T](sql: str, args...) -> [T]
db.query_one[T](sql: str, args...) -> Option[T]
db.exec(sql: str, args...) -> i64
```

Experimental SQLite-backed support exists in some compiler builds. When SQL support is stripped, `db.*` is stubbed. Prefer not depending on it until the API is stable.

## 9. Modules & Visibility

```
use std.http
use std.fs
use usage.moduse

go { mod() }

use usage/moduse
go { moduse.mod() }

use usage.moduse.mod
go { mod() }
```

- `std.*` names refer to compiler-provided modules (e.g. `std.fs`)
- Source import paths are relative to the project's `src/` directory (`.te` without extension)
- Dotted paths import public functions into the current scope; slash paths import a module namespace
- Alias: `use std.fs as files`
- Functions are private by default; use `pub fn` for exports
- Imported files are declaration-only (no `go`)
- Cyclic imports and importing records across modules are not supported

## 10. Memory & Safety Model (Current Implementation)

- Intended long-term direction: ownership and borrowing
- Current reference compiler: value-based semantics and function pointers
- No full borrow checker in the current implementation

## 11. Compilation Model

```sh
python tersec.py build main.te -o app
python tersec.py run main.te
python tersec.py check main.te
```

- Frontend: lexer → parser → type checker → code generation
- Backend: C code generation + system C compiler (gcc/clang)
- `check` parses and type-checks; `build` emits a native executable; `run` builds and executes
- Compile-time errors return nonzero and include source locations where available

## 12. Current Compiler Status (0.2)

### Implemented in `tersec`

- Integer arithmetic, comparisons, compound assignment (`+=` …)
- Booleans and if / else-if / else expressions
- Named functions, methods (`fn Point.show()`), recursion
- Higher-order functions and simple lambdas
- `val` / `var` bindings and blocks
- Top-level `fix` (immutable constants)
- Ternary `cond ? then : else`
- Maps `{K: V}` with `{:}`, literals, `m[k]`, `m[k]=v`, `len(m)`
- Multi-file `use` / `pub fn`
- Pipe `|>`
- Basic type checking
- Compilation to native binary via C
- String literals, concatenation, length, indexing
- Lists, indexing, `.size` / `len`, printing
- Records (`rec`), enums (`en`), traits (`tr`)
- Implicit trait satisfaction (matching method signatures)
- `match` on integers and enum variants (with guards)
- Enum variants with typed payloads and payload patterns (`Option.Some(n)`)
- Pipe operator `|>`
- Loops: `lp x:xs`, `lp i = 0; …; …`, `lp cond`, `while`
- Built-in `pr`, `len`, `map` (list), `json`, minimal `http.serve`
- `go { ... }` entrypoint; native `main` generated by the backend
- Source-module imports for functions and basic `std.fs` text I/O

### Limited or Planned

- Full closures with environment capture
- Nested / rest patterns; multi-field enum payloads beyond basic forms
- General generics, tuples, `Option`, `Result`
- Full ownership / borrowing / borrow checking
- Database support (optional / stubbed in lean builds)
- HTTP middleware and framework-style request decoding
- Top-level `fix` declarations (literals)
- Maps `{K:V}` (str keys; i64/str values)

## 13. Example Programs

See `eg.te` and other `.te` samples alongside the compiler.

