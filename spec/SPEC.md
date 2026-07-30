# Terse Language Specification v0.1

**Terse** is a succinct, statically-typed systems language that compiles to native binaries.  
It emphasizes minimal syntax, first-class higher-order functions, and built-in support for serving REST APIs and talking to databases.

This document describes the core language and the intended full feature set. The reference compiler (`tersec`) currently implements a solid subset focused on expressions, functions, and higher-order programming; REST and database features are specified and stubbed for future expansion.

## 1. Design Goals

- Extremely terse syntax with high signal-to-noise.
- First-class functions and higher-order programming (pass, return, nest functions).
- Ahead-of-time compilation to a single static (or mostly static) binary.
- Zero or near-zero runtime overhead for common patterns.
- Practical built-ins for HTTP servers and SQL databases.
- Type inference by default; explicit types when desired.
- Safe defaults (no nulls by default; Option[T] for absence).

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

Keywords (reserved):  
`fn`, `let`, `type`, `if`, `else`, `match`, `use`, `return`, `true`, `false`, `mut`, `struct`, `enum`, `impl`, `self`, `pub`, `as`, `in`, `for`, `while`, `loop`, `break`, `continue`, `None`, `Some`, `Ok`, `Err`, `get`, `post`, `put`, `delete`, `http`, `db`, `json`, `status`

### Literals
- Integer: `42`, `-7`, `0xFF` (i64 by default)
- Float: `3.14` (f64)
- String: `"hello"`, support for basic escapes (`\n`, `\t`, `\"`, `\\`)
- Boolean: `true`, `false`
- Unit: `()`

### Operators
Arithmetic: `+` `-` `*` `/` `%`  
Comparison: `==` `!=` `<` `>` `<=` `>=`  
Logical: `&&` `||` `!`  
Assignment: `=`  
Function: `|params| body` (lambda), `>>` (compose), `_` (placeholder for partial app)

## 3. Types

### Primitive Types
- `i64`, `i32`, `u64`, `bool`, `f64`, `str` (UTF-8 string), `()` (unit)

### Composite
- Function types: `fn(T1, T2) -> R`
- Records / structs: `{field: Type, ...}`
- Option: `Option[T]` (Some(v) | None)
- Result: `Result[T, E]`
- Lists: `[T]`
- Tuples: `(T1, T2, ...)`

Type inference is Hindley-Milner inspired for local variables and lambdas. Top-level functions may require annotations for complex cases.

## 4. Syntax (Core)

### Program
A program is a sequence of top-level declarations (functions, types, uses) ending with an entry point `fn main()`.

```
program ::= item*
item    ::= fn_decl | type_decl | use_decl
```

### Functions
```
fn name(params) -> RetType = expr
fn name(params) -> RetType { stmts }

// Lambda
|param1, param2| expr
|param1: Type| { stmts }
```

Parameters may omit types when inferable. Return type may be omitted when obvious.

Higher-order example:
```
fn apply(f: fn(i64) -> i64, x: i64) -> i64 = f(x)
let double = |n| n * 2
apply(double, 21)
```

### Let Bindings
```
let name = expr
let name: Type = expr
let mut name = expr
```

### Control Flow
```
if cond { then } else { else }
match expr {
  pat1 => result1
  pat2 if guard => result2
  _ => default
}
```

### Function Application & Composition
```
f(arg1, arg2)
f >> g          // composition: g(f(x))
add(5, _)       // partial application
```

## 5. Higher-Order Functions

Functions are first-class values. They can be:

- Stored in variables
- Passed as arguments
- Returned from functions
- Nested (closures)

Closures capture by immutable borrow / value for primitives in the current design. Mutable captures require explicit `mut` and are restricted.

Example:
```
fn make_multiplier(factor: i64) -> fn(i64) -> i64 {
  |x| x * factor
}

let times3 = make_multiplier(3)
times3(10)   // 30
```

## 6. REST APIs (Language Feature)

```
use std.http

http.serve(port: i64) {
  get "/path" => expr_or_block
  get "/users/:id" => |id: i64| { ... }
  post "/users" => |body: User| { ... }
  put ...
  delete ...

  // Middleware / groups
  group "/admin" {
    use require_auth
    get "/stats" => ...
  }
}
```

- Path parameters become function parameters.
- Request body is automatically decoded from JSON into the annotated type.
- Return values are automatically JSON-encoded (or status codes via `status(code)`).
- The `http.serve` block is the main event loop of the process.

## 7. Database Access (Language Feature)

```
use std.db

db.connect(url: str)          // or from env
db.query[T](sql: str, args...) -> [T]
db.query_one[T](sql: str, args...) -> Option[T]
db.exec(sql: str, args...) -> i64   // rows affected
db.tx { ... }                   // transaction block
```

Types are mapped automatically for common primitives and records. Prepared statements are used under the hood.

## 8. Modules & Visibility
```
use std.http
use mylib.{foo, bar}
pub fn ...
```

## 9. Memory & Safety Model (Target)

- Ownership + borrowing (Rust-inspired) for the full language.
- No garbage collector in the default "systems" mode.
- Optional ARC mode for rapid prototyping with cycles.
- Current reference compiler uses a simplified model (mostly value types + function pointers).

## 10. Compilation Model

```
tersec build main.terse -o app
tersec run main.terse
tersec check main.terse
```

- Frontend: lexer → parser → type checker → desugarer
- Backend: currently C code generation + system C compiler (gcc/clang)
- Future: direct LLVM IR emission for better optimization and cross-compilation.

## 11. Current Compiler Status (v0.1)

Supported:
- Integer arithmetic and comparisons
- Booleans and if-expressions
- Named functions and recursion
- Higher-order functions (function values / pointers)
- Simple lambdas (no complex captures yet)
- let bindings
- Basic type checking
- Compilation to native binary via C

Stubbed / Specified but not fully implemented:
- Strings beyond literals in limited contexts
- Full records / pattern matching
- Real HTTP server and SQLite integration
- Closures with environment capture
- Generics beyond basic function types

## 12. Example Programs

See `examples/` directory.

---

*This specification is a living document for the Terse language project.*

## 13. v0.2 Additions — Strings, Lists, Print, Basic I/O

### Strings
```
"hello"
"hel" + "lo"          // concat
len(s)                // length
s[i]                  // byte/char code at index (i64)
p(s)  // or print(s)
```

### Lists (of i64)
```
[1, 2, 3]
len(xs)
xs[i]
p(xs)             // prints [1, 2, 3]
```

Type annotation: `list` or `[i64]` in signatures when needed.

### Printing
```
p(42)
p("hi")
p([1, 2])
print(x)   // alias of p
```
`p` (and alias `print`) is a builtin; returns `0`.

### Basic I/O
- `print` → stdout (ints, strings, lists)
- No file I/O or stdin yet (next)

### Example
```
fn main() -> i64 {
  p("hello terse")
  let xs = [10, 20, 30]
  p(xs)
  print(len(xs))
  print(xs[1])
  let s = "hel" + "lo"
  p(s)  // or print(s)
  0
}
```
