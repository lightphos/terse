# Critique of the Terse Language

Based on reviewing `spec/SPEC.md`, `spec/TERSE_BNF.md`, `compiler/tersec.py`, and the test suite, here's my analysis:

---

## **Strengths**

1. **Clear Design Vision** — SPEC is well-written, with explicit design goals (terse syntax, AOT native binaries, small std). The status labels (Implemented/Limited/Planned) are honest and useful.

2. **Frozen Std Surface (§8)** — Explicit contract prevents scope creep. This is rare and valuable for a young language.

3. **Monomorphization without Runtime Overhead** — Generics via specialization (`id__i64`, `Opt__i64`) avoids vtables/dictionaries. Good fit for C backend.

4. **Explicit Module Resolution** — `use` resolution order is deterministic and documented. The parallel `tst/` ↔ `src/` pairing for tests is elegant.

5. **Host Compiler as Conformance Reference** — The Python `tersec.py` is the truth; `tc.te` is experimental. This avoids bootstrapping circularity.

6. **Structural Traits (Implicit Satisfaction)** — `rec` satisfies `tr` by having matching methods — no `impl` boilerplate. Keeps code terse.

7. **Test-as-Code (`tst.check.equals`)** — Tests are just functions run explicitly via `go { ... }`. No magic discovery, no external runner.

---

## **Inconsistencies & Gaps**

| Area | Issue | Evidence |
|------|-------|----------|
| **BNF vs SPEC drift** | BNF calls generic type params `<type-params>` and type args `<type-args>`; SPEC uses `[T]` notation but BNF doesn't fully cover generic `rec`/`en` syntax | BNF has `type_params ::= "[" ident ("," ident)* "]"` at end but no `<record-decl>` with type params in grammar proper (though parser handles it) |
| **`fn-name` ambiguity** | BNF: `<fn-name> ::= IDENT [ "." IDENT ]` for methods. But parser also handles `fn Point.add()` via `parse_method` — not a first-class rule | `parse_method` called from `parse_fn` when `IDENT DOT IDENT` seen; not in BNF |
| **`ret` in block vs expr** | SPEC: "blocks evaluate statements in order; value is the last expression (or 0 if empty). `ret expr` returns from current function". But `ret` inside a block *also* returns from function, not block. The distinction between block value and function return is fuzzy | Parser builds `LetExpr` chain; `RetExpr` can appear anywhere |
| **Pattern `if` vs `match`** | Two syntaxes for pattern matching: `if expr { arms }` and `match expr { arms }`. Both exist, slightly different semantics (catch-all via `_` vs `else`). Redundant? | SPEC §6, BNF `<if-expr>` has two forms |
| **Generic enum pattern names** | `Opt[i64].Some(x)` but pattern uses `Opt__i64.Some(x)` — the `__` mangling leaks to user code | Test `t_generic_en.te`: `if o { Opt__i64.Some(x) => ... }` |
| **No tuple syntax in SPEC** | BNF has `TypeNode('tuple', args)` and tuple patterns, but SPEC §3 doesn't document tuples | `tersec.py` line 407-418 parses `(T1, T2, ...)` as tuple type; no examples in SPEC |
| **`map` builtin listed as "limited"** | SPEC §8: "`json` (limited), list `map`, minimal `http.serve` (limited)." But `map` is a core list operation — should be in frozen surface or removed | `test_compiler.py` has no tests for `map` |
| **`push` not in std** | `xs = xs + elem` works for push, but `push(xs, elem)` is mentioned in type checker builtins list. Inconsistent | TypeChecker line 1763: `'push'` in builtins; no SPEC entry |
| **`std.str` unqualified forms** | SPEC: "Unqualified forms accepted when not ambiguous with map `has`" — but `has` is ambiguous! Map `has(m, k)` vs `str.has(s, sub)` | SPEC §8 line 347: "accepted ... when not ambiguous" — but it *is* ambiguous |

---

## **Language Design Concerns**

### 1. **No Ownership/Borrowing — But Mutable Aliasing Exists**
```terse
var xs: [i64] = [1, 2]
var ys = xs       // alias
xs[0] = 99        // mutates ys too?
```
SPEC says lists are values, but C codegen likely uses heap allocation with refcount or copy-on-write. Not specified. This is a soundness hole.

### 2. **`str + i64` Auto-Conversion but No `i64 + str` Symmetry Guarantee**
SPEC: "`str + i64` / `i64 + str` convert the number." But `42 + "hello"` — is that `"42hello"`? Type checker allows both (line 1819), but semantic order matters for concatenation.

### 3. **Map Missing Key Returns `0`/`""` Silently**
```terse
var m: {str: i64} = {:}
m["missing"]  // returns 0 — is this 0 or absent?
```
SPEC: "does **not** abort". But this conflates "key exists with value 0" vs "key missing". `has(m, k)` required to distinguish. Footgun.

### 4. **`fix` is File-Local but `pub fix` Exports — No Module-Level Constants**
`fix` without `pub` is renamed on import. But there's no way to declare a true module-level constant that's visible to importers without `pub`. (Though `pub fix` works.)

### 5. **No Generics Constraints (Yet)**
```terse
fn sort[T](xs: [T]) -> [T] = ...  // T needs Ord
```
Phase 1 explicitly excludes `T: Ord`. This means either:
- `sort` only works on `i64`/`str` via overloading, or
- Users write `sort_i64`, `sort_str` manually

### 6. **Lambda Capture Not Fully Implemented**
SPEC: "Limited — Higher-order / closures with capture". Parser accepts `|x| x + y` but codegen may not capture `y` correctly.

### 7. **Trait Dynamic Dispatch Unclear**
```terse
fn print(p: Printable) { pr(p.str()) }
```
"Today is likely specialized/adapter" — but which? Monomorphization per concrete type? Vtable? The SPEC admits this is unresolved (§7 table).

### 8. **Environment Variable Semantics Underspecified**
```terse
// src/env.te
fn write_read_env() -> str {
  env("MYENV") = "some env"
  ret env("MYENV")
}

go {
  pr("MYENV=" + write_read_env())
}
```
**Open questions:**
- **Setter vs getter**: `env("K") = "v"` is a statement (returns `i64`?) vs `env("K")` is expression (returns `str`). No syntax distinction.
- **Scope**: Is `env` per-process (uses `setenv`/`_putenv_s` at C runtime)? SPEC §8 says "builtins" but `env` isn't in the frozen list explicitly.
- **Persistence**: Does `env("K") = "v"` affect child processes? Parent? Subsequent calls in same program?
- **Shadowing**: If `MYENV` was set before program start, does the setter override for this process only?
- **Type**: Getter returns `str`, setter returns `i64` (success)? Not in SPEC.
- **Thread safety**: Not specified — relevant when async tasks are added.

---

## **Compiler Implementation Concerns**

1. **Single 5300-line `tersec.py`** — Lexer, parser, type checker, codegen all in one file. Hard to maintain/test in isolation.

2. **Type Checker Mutates AST** — `specialize_generic` rewrites `Call.func` from `Index` to `Var(mangled)` in-place (line 1890). Makes debugging hard; AST no longer matches source.

3. **Error Recovery Minimal** — First error aborts. No "continue to find more errors" mode.

4. **No Incremental Compilation** — Every build re-parses, re-typechecks, re-codegens all modules. `~/.terse/out` caches object files but not frontend work.

5. **C Codegen Emits Directly to String** — No intermediate IR. Hard to optimize or target other backends.

6. **Hardcoded Builtins** — Lists in `TypeChecker.check` (lines 1763, 1957): `'pr','len','json','env','str','push','substr',...`. Should be declarative.

---

## **Missing from SPEC (but Implemented)**

| Feature | In Code | In SPEC |
|---------|---------|---------|
| `fmt(...)` multi-arg concat | ✅ TypeChecker lines 1918-1919 | ✅ §8 |
| `env("KEY") = "val"` setter | ✅ TypeChecker line 1944 | ✅ §8 |
| `db.*` (SQLite) | ✅ Runtime + TypeChecker | ❌ "disabled in lean builds" only |
| `http.serve` routes | ✅ Parser + Runtime | ❌ "limited" |
| `json` | ✅ Runtime + builtin | ❌ "limited" |
| Tuple types/patterns | ✅ Parser + TypeChecker | ❌ Not documented |
| `while` loop | ✅ Parser | ✅ §6 |
| `brk` with value | ✅ Parser (`JumpExpr.value`) | ❌ Not documented |

---

## **Async Server Design (Scalability Concern)**

### Current: Single-Threaded Blocking
```terse
// lib/http.te — the current srv is blocking, one connection at a time
pub fn srv(port: i64, handler: fn(Req) -> Res) {
  val ls = sock.listen(port)
  lp true {
    val c = sock.accept(ls)   // blocks
    val raw = sock.recv(c)     // blocks
    val rs = handler(rq)       // your logic blocks
    sock.send(c, out)          // blocks
    sock.close(c)
  }
}
```
**Max ~1K concurrent connections** (one thread per connection).

### What's Missing for 100K Concurrency

| Capability | Node.js / Vert.x | Current Terse | Gap |
|------------|------------------|---------------|-----|
| Non-blocking I/O | `epoll` / `kqueue` | blocking recv/send | ✅ Runtime |
| Event loop | Built-in | None | ✅ Runtime + std |
| Async/await | `await` / `Promise` | None | ✅ Language |
| Task spawning | Worker threads / libuv | None | ✅ Language |
| Channels / select | EventEmitter / async/await | None | ✅ Language + runtime |

### Proposed Extensions

**1. `async fn` → state machine (codegen)**
```terse
fn fetch(id: i64) -> Future[User] = ...
val u = await fetch(id)   // suspends, yields to event loop
```
Codegen transforms each `await` into a yield point: save locals to heap, suspend stackless coroutine, resume when future resolves.

**2. Non-blocking socket runtime (C backend)**
```c
// Epoll wrapper (~150 lines)
int epoll_create();
int epoll_ctl_add(int efd, int fd, uint32_t events);
int epoll_wait(int efd, struct epoll_event* evs, int max, int timeout);
```
Replace `blocking recv/send` with registered callbacks that fire on ready FDs.

**3. Green thread scheduler**
```terse
spawn async { ... }   // lightweight task, not OS thread
await net.accept(l)   // yields until FD ready
```
Work-stealing deque per worker, cooperative multitasking.

### Implementation Order

| Step | Deliverable | Effort | Blocker |
|------|-------------|--------|---------|
| 1 | `sock_set_nonblock` + `epoll` in C runtime | ~150 lines | None |
| 2 | `Future<T>` type in type checker | ~50 lines | None |
| 3 | `async fn` → state machine codegen | ~800 lines | Scheduler |
| 4 | `spawn` / task scheduler | ~300 lines | Codegen step 3 |
| 5 | `select` / channels | ~200 lines | Language design |
| 6 | `std.net` library in Terse | ~500 lines | All above |

### Architecture for 100K Connections
```
OS Threads × N cores
┌─────────┐ ┌─────────┐ ┌─────────┐
│Event Loop│ │Event Loop│ │Event Loop│
└────┬────┘ └────┬────┘ └────┬────┘
     └──────┬────┴───────────┘
            ▼
       ┌────────────┐
       │Scheduler   │  work-stealing deques
       │ (green thrs)│
       └─────┬──────┘
             │
    ┌────────┼────────┐
    ▼        ▼        ▼
  Task 1   Task 2   Task K   (100K+)
```

---

## **Verdict**

Terse is a **coherent, opinionated language** with a clear niche: *small, fast, native binaries with minimal syntax*. The host compiler is surprisingly complete for its size (generics, traits, modules, pattern matching all work). 

The main risks are **underspecified semantics** (list aliasing, trait dispatch, tuple support) and **spec/implementation drift**. The frozen std surface is a strong guardrail — if maintained, it prevents the "kitchen sink" problem that kills many young languages.

**Best path forward**: Finish SPEC coverage for what's already implemented, resolve the `Opt__i64` pattern leak, and decide on trait dispatch before adding more features.