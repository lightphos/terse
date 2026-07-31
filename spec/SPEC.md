# Terse Language Specification 0.1-beta

**Terse** is a succinct, statically-typed systems language that compiles to native binaries.  
It emphasizes minimal syntax, first-class higher-order functions, and a small set of built-in conveniences for I/O, JSON, and lightweight HTTP services.

This document describes the language shape and the current reference compiler behavior. The reference compiler (`tersec`) currently implements a working subset focused on expressions, functions, higher-order programming, strings, lists, basic I/O, and a minimal HTTP server runtime; broader features such as full records, pattern matching, and database integration remain future work.

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

Keywords (reserved):  
`fn`, `let`, `type`, `if`, `else`, `match`, `use`, `return`, `true`, `false`, `mut`, `struct`, `enum`, `impl`, `self`, `pub`, `as`, `in`, `for`, `while`, `loop`, `break`, `continue`, `None`, `Some`, `Ok`, `Err`, `get`, `post`, `pr`, `put`, `go`, `env`, `delete`, `http`, `db`, `json`, `status`

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
- Records / structs: `rec {field: Type, ...}`
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
## 6. Strings, Lists, Print, Basic I/O

### Strings
```
"hello"
"hel" + "lo"          // concat
len(s)                // length
s[i]                  // byte/char code at index (i64)
pr(s)
```

### Lists (of i64)
```
[1, 2, 3]
len(xs)
xs[i]
pr(xs)             // prints [1, 2, 3]
```

Type annotation: `list` or `[i64]` in signatures when needed.

### Printing
```
pr(42)
pr("hi")
pr([1, 2])
pr(x)
```
`pr` is a builtin; returns `0`.

### Basic I/O
- `pr` → stdout (ints, strings, lists)
- No file I/O or stdin yet (next)

### Example
```
fn main() -> i64 {
  pr("hello terse")
  let xs = [10, 20, 30]
  pr(xs)
  pr(len(xs))
  pr(xs[1])
  let s = "hel" + "lo"
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

  // Middleware / groups
  group "/admin" {
    use require_auth
    get "/stats" => ...
  }
}
```

- The current compiler implements a minimal `http.serve` construct for simple route handlers.
- Route handlers may return strings or JSON values; the runtime responds with text/JSON output.
- The implementation is intentionally small and does not yet provide full middleware, path-parameter plumbing, or framework-style request decoding.
- The `http.serve` block is the main event loop of the process for the current runtime.

## 8. Database Access (Planned, Not Implemented)

```
use std.db

db.connect(url: str)          // or from env
db.query[T](sql: str, args...) -> [T]
db.query_one[T](sql: str, args...) -> Option[T]
db.exec(sql: str, args...) -> i64   // rows affected
db.tx { ... }                   // transaction block
```

Types are mapped automatically for common primitives and records in the intended design, but the current compiler does not implement database access or prepared statements.

## 9. Modules & Visibility
```
use std.http
use mylib.{foo, bar}
pub fn ...
```

## 10. Memory & Safety Model (Current Implementation)

- The full language is still intended to evolve toward an ownership-and-borrowing model.
- The current reference compiler uses a simplified runtime model with value-based semantics and function pointers.
- There is no full borrow checker or ownership system in the current implementation.
- The compiler is currently focused on correctness and portability over advanced safety features.

## 11. Compilation Model

```
tersec build main.terse -o app
tersec run main.terse
tersec check main.terse
```

- Frontend: lexer → parser → type checker → code generation
- Backend: currently C code generation + system C compiler (gcc/clang)
- Possible future backend: direct LLVM IR emission for better optimization and cross-compilation.

## 12. Current Compiler Status (0.1beta)

Implemented:
- Integer arithmetic and comparisons
- Booleans and if-expressions
- Named functions and recursion
- Higher-order functions (function values / pointers)
- Simple lambdas
- let bindings and blocks
- Basic type checking
- Compilation to native binary via C
- String literals, string concatenation, length, and indexing
- Lists, list indexing, and printing
- Built-in `pr`, `len`, `json`, and a minimal `http.serve` runtime
- Top-level expressions and a `go { ... }` entry-point alias

Not yet implemented or still limited:
- Full closures with environment capture
- Tiny structs / records and basic pattern matching
- Generics beyond the current subset
- Full ownership / borrowing / borrow checking
- Real database integration

## 13. Example Programs

See `examples/` directory.


