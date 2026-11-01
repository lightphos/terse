# Critique of the Terse Language

Based on reviewing `spec/SPEC.md`, `spec/TERSE_BNF.md`, the compiler package under `compiler/tersec/`, and the test suite, here's my analysis:

---

## **Strengths**

1. **Clear Design Vision** — SPEC is well-written, with explicit design goals (terse syntax, AOT native binaries, small std). The status labels (Implemented/Limited/Planned) are honest and useful.

2. **Frozen Std Surface (§8)** — Explicit contract prevents scope creep. This is rare and valuable for a young language.

3. **Monomorphization without Runtime Overhead** — Generics via specialization (`id__long`, `Opt__long`) avoids vtables/dictionaries. Good fit for C backend.

4. **Explicit Module Resolution** — `use` resolution order is deterministic and documented. The parallel `tst/` ↔ `src/` pairing for tests is elegant.

5. **Host Compiler as Conformance Reference** — The Python compiler package under `compiler/tersec/` is the truth; `tc.te` is still experimental. This avoids bootstrapping circularity.

6. **Structural Traits (Implicit Satisfaction)** — `rec` satisfies `tr` by having matching methods — no `impl` boilerplate. Keeps code terse.

7. **Test-as-Code (`tst.check.equals`)** — Tests are just functions run explicitly via `go { ... }`. No magic discovery, no external runner.

---

## **Inconsistencies & Gaps**

| Area | Status | Notes |
|------|--------|-------|
| **BNF vs SPEC drift** | **Done** | BNF `<record-decl>` / `<enum-decl>` / `<trait-decl>` already take `[ <type-params> ]`; orphan trailing `type_params` removed; SPEC §3b documents `[T]` + monomorphization |
| **`fn-name` / methods** | **Done** | BNF `<fn-name> ::= IDENT [ "." IDENT ]` documents `fn Point.add(...)`; matches host parser |
| **`ret` in block vs expr** | **Done** | SPEC §2 clarifies: block value = last expr; `ret` always returns from the **function** |
| **Pattern `if` vs `match`** | **Done** | SPEC §6 documents both as equivalent arm syntax; catch-all `_ =>` |
| **Generic enum pattern names** | **Open** | Still need `Opt__long.Some(x)` in patterns — listed under SPEC Limited |
| **Tuple syntax in SPEC** | **Done** | SPEC §3 table + BNF tuple type form; status **Limited** |
| **`map` builtin** | **Done** | SPEC lists `map` / pipe under Implemented; tests in `t_lambda` / `t_eg` / unit tests |
| **`push` not in std** | **Done** | SPEC: push is `list + elem` only; no separate `push` in the language contract |
| **`std.str` vs map `has`** | **Done** | SPEC: overload by first-arg type (`str` vs map) |

---

## **Language Design Concerns**

### 1. **No Ownership/Borrowing — But Mutable Aliasing Exists**
```terse
var xs: [long] = [1, 2]
var ys = xs       // alias
xs[0] = 99        // mutates ys too?
```
SPEC says lists are values, but C codegen likely uses heap allocation with refcount or copy-on-write. Not specified. This is a soundness hole.

### 2. **`str + long` Auto-Conversion but No `long + str` Symmetry Guarantee**
SPEC: "`str + long` / `long + str` convert the number." But `42 + "hello"` — is that `"42hello"`? Type checker allows both (line 1819), but semantic order matters for concatenation.

### 3. **Map Missing Key Returns `0`/`""` Silently**
```terse
var m: {str: long} = {:}
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
- `sort` only works on `long`/`str` via overloading, or
- Users write `sort_long`, `sort_str` manually

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
- **Setter vs getter**: `env("K") = "v"` is a statement (returns `long`?) vs `env("K")` is expression (returns `str`). No syntax distinction.
- **Scope**: Is `env` per-process (uses `setenv`/`_putenv_s` at C runtime)? SPEC §8 says "builtins" but `env` isn't in the frozen list explicitly.
- **Persistence**: Does `env("K") = "v"` affect child processes? Parent? Subsequent calls in same program?
- **Shadowing**: If `MYENV` was set before program start, does the setter override for this process only?
- **Type**: Getter returns `str`, setter returns `long` (success)? Not in SPEC.
- **Thread safety**: Not specified — relevant when async tasks are added.

---

## **Compiler Implementation Concerns**

1. **`tersec.py` Is No Longer a Single 5300-line Monolith** — The compiler has been split into a package (`compiler/tersec/lexer.py`, `parser.py`, `ast.py`, `typecheck.py`, `codegen.py`, `utils.py`), which is a much healthier structure for maintenance and targeted testing. The concern is no longer sheer file size but keeping module boundaries and interfaces disciplined as the compiler grows.

2. **Type Checker Mutates AST** — `specialize_generic` rewrites `Call.func` from `Index` to `Var(mangled)` in-place (line 1890). Makes debugging hard; AST no longer matches source.

3. **Error Recovery Minimal** — First error aborts. No "continue to find more errors" mode.

4. **No Incremental Compilation** — Every build re-parses, re-typechecks, re-codegens all modules. `~/.terse/out` caches object files but not frontend work.

5. **C Codegen Emits Directly to String** — No intermediate IR. Hard to optimize or target other backends.

6. **Hardcoded Builtins** — Lists in `TypeChecker.check` (lines 1763, 1957): `'pr','len','json','env','str','push','substr',...`. Should be declarative.

---

## **Missing from SPEC (but Implemented)**

| Feature | In Code | In SPEC | Status |
|---------|---------|---------|--------|
| `fmt(...)` multi-arg concat | ✅ | ✅ §8 / status | Done |
| `env("KEY") = "val"` setter | ✅ | ✅ §8 | Done |
| `db.*` (SQLite) | ✅ Runtime | Still lean-build only | Open (optional surface) |
| HTTP | ✅ `lib/cnx/http.te` | ✅ Limited + package table | Done |
| `json` | ✅ Runtime | Still limited | Open |
| Tuple types/patterns | ✅ Parser | ✅ §3 Limited | Done |
| `while` loop | ✅ | ✅ §6 | Done |
| Pipe `\|>` | ✅ | ✅ §2 / §6 | Done |
| Nested `use a.b` packages | ✅ | ✅ module path rule | Done |

---

## **Async Server Design (Scalability Concern)**

### Current: Single-Threaded Blocking
```terse
// lib/http.te — the current srv is blocking, one connection at a time
pub fn srv(port: long, handler: fn(Req) -> Res) {
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
fn fetch(id: long) -> Future[User] = ...
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

**Progress (2026-11):** SPEC/BNF drift items above marked **Done** (generics grammar, methods, `ret` semantics, `if`/`match`, tuples Limited, `map`/`push`/`has`, nested packages, HTTP under `cnx.http`).

**Best path forward**: Resolve the remaining `Opt__long` pattern leak, finish generic trait parameters / decide trait dispatch, then ownership — before large new features (async HTTP, etc.).